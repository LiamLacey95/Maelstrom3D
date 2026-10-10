# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Paint layer stack of the Texture workspace (F4) for Maelstrom3D: the channels, the layer data, the node chains, the
paint target, Merge Down, Flatten and the flattening Export uses.

Blender has no paint layers, so the stack is data on the material (Material.m3d_layers, bottom to top) and a node
chain per channel that is rebuilt from it: Image Texture -> Mix (blend mode, factor = image alpha x opacity x mask) over
the layer below, the top of the chain feeding the Principled BSDF. The chains live in one frame per channel; only nodes
that carry the m3d_layer custom property are ever touched. A layer's mask is a stack of effects (m3d_masks.py) built as
one more chain, in a frame of its own per layer, whose result multiplies the factor of every channel the layer has.
The same blend math in numpy flattens a stack (Merge Down, Flatten, Export). Painting needs no special support: the
active layer's image for the active channel (or its mask's Paint effect) is made the material's active paint slot.

Folders: a layer of kind FOLDER holds the layers whose `parent` is its uid (folders nest). The stack stays one list,
bottom to top, with each folder right after the layers inside it, so the list read backwards is what the UI shows. A
folder's layers are composited together over transparent first (color and coverage, `over` in numpy; in the nodes a
sub-chain that carries a coverage socket next to the color), then the result is blended onto the stack below with the
folder's blend, opacity and mask like a layer's own image. Freezing bakes that result into one image per channel (the
alpha is the coverage), after which the folder is a leaf of the chains: one Image Texture and one Mix per channel.

The Layers page (panels) is in m3d_texture.py.
"""

import uuid
from collections import namedtuple
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, PropertyGroup, UIList

import m3d_masks as MK
from m3d_masks import image_size, muted, pixels_of, write_pixels
from m3d_sculpt import mesh_of

# -----------------------------------------------------------------------------
# Channels: what a layer can hold. A channel is a Principled BSDF input fed by its chain.

Channel = namedtuple("Channel", "id label slot_type color srgb")
# slot_type: the type of paint.add_texture_paint_slot (None: wired here); color: what a new image starts as.
CHANNELS = (
    Channel('BASE_COLOR', "Base Color", 'BASE_COLOR', (0.8, 0.8, 0.8, 1.0), True),
    Channel('ROUGHNESS', "Roughness", 'ROUGHNESS', (0.5, 0.5, 0.5, 1.0), False),
    Channel('METALLIC', "Metallic", 'METALLIC', (0.0, 0.0, 0.0, 1.0), False),
    Channel('NORMAL', "Normal", 'NORMAL', (0.5, 0.5, 1.0, 1.0), False),
    Channel('HEIGHT', "Height", 'BUMP', (0.5, 0.5, 0.5, 1.0), False),
    Channel('EMISSION', "Emission", None, (0.0, 0.0, 0.0, 1.0), True),
)
CHANNEL_BY_ID = {ch.id: ch for ch in CHANNELS}
CHANNEL_INDEX = {ch.id: i for i, ch in enumerate(CHANNELS)}
CHANNEL_ITEMS = [(ch.id, ch.label, "") for ch in CHANNELS]
SCALARS = {'ROUGHNESS', 'METALLIC', 'HEIGHT'}   # One value per pixel: fill layers use a number, not a color.
# Principled BSDF input a chain feeds directly -> channel (Normal and Height go through a Normal Map / Bump node)
SOCKETS = {'BASE_COLOR': "Base Color", 'ROUGHNESS': "Roughness", 'METALLIC': "Metallic", 'EMISSION': "Emission Color"}
SOCKET_CHANNELS = {name: ch for ch, name in SOCKETS.items()}

BLENDS = (   # Mix node blend types. All of them are exact in the numpy flattening too (see BLEND_FUNCTIONS).
    ('MIX', "Mix"), ('MULTIPLY', "Multiply"), ('ADD', "Add"), ('OVERLAY', "Overlay"), ('SCREEN', "Screen"),
    ('SOFT_LIGHT', "Soft Light"), ('SUBTRACT', "Subtract"), ('DIFFERENCE', "Difference"), ('COLOR', "Color"),
    ('DARKEN', "Darken"), ('LIGHTEN', "Lighten"),
)
TAG = "m3d_layer"   # Custom property (value: channel id) and name prefix of every node the stack creates.
MEMORY_WARN = 12    # Warn from this many 4K images (8 bit RGBA) on.


def principled_of(mat):
    return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if mat.node_tree else None


def set_channel_space(image, ch):
    image.colorspace_settings.name = 'sRGB' if ch.srgb else 'Non-Color'
    image["m3d_channel"] = ch.id


def node_channel(node):
    """Channel an image node feeds by its link: a Principled input directly, or through a Normal Map / Bump node."""
    for link in node.outputs[0].links:
        to = link.to_node
        if to.type == 'BSDF_PRINCIPLED' and link.to_socket.name in SOCKET_CHANNELS:
            return SOCKET_CHANNELS[link.to_socket.name]
        if to.type in {'NORMAL_MAP', 'BUMP'}:
            return 'NORMAL' if to.type == 'NORMAL_MAP' else 'HEIGHT'
    return None


# -----------------------------------------------------------------------------
# Pixels: colour space and blend math (numpy). Everything composites in linear light like the shader nodes do.

def to_linear(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((np.maximum(c, 0.04045) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def to_srgb(c):
    c = np.clip(np.asarray(c, np.float32), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.maximum(c, 0.0031308) ** (1 / 2.4) - 0.055).astype(np.float32)


def rgb_to_hsv(c):
    mx, mn = c.max(axis=-1), c.min(axis=-1)
    d = mx - mn
    safe = np.where(d > 0, d, 1.0)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    h = np.where(mx == r, ((g - b) / safe) % 6.0, np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0)) / 6.0
    return np.where(d > 0, h, 0.0), np.where(mx > 0, d / np.where(mx > 0, mx, 1.0), 0.0), mx


def hsv_to_rgb(h, s, v):
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = (i % 6).astype(int)[..., None]
    return np.choose(i, [np.stack(x, -1) for x in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))])


def blend_color(back, src):
    """Hue and saturation of `src` on the value of `back` (Mix node, Color)."""
    h, s, _ = rgb_to_hsv(src)
    return np.where((s != 0)[..., None], hsv_to_rgb(h, s, rgb_to_hsv(back)[2]), back)


# What the Mix node's blend types compute before the factor: result = back + factor * (blend - back).
BLEND_FUNCTIONS = {
    'MIX': lambda b, s: s,
    'MULTIPLY': lambda b, s: b * s,
    'ADD': lambda b, s: b + s,
    'OVERLAY': lambda b, s: np.where(b < 0.5, 2 * b * s, 1 - 2 * (1 - b) * (1 - s)),
    'SCREEN': lambda b, s: 1 - (1 - b) * (1 - s),
    'SOFT_LIGHT': lambda b, s: (1 - b) * s * b + b * (1 - (1 - s) * (1 - b)),
    'SUBTRACT': lambda b, s: b - s,
    'DIFFERENCE': lambda b, s: np.abs(b - s),
    'COLOR': blend_color,
    'DARKEN': np.minimum,
    'LIGHTEN': np.maximum,
}


def over(back_rgb, back_a, rgb, a, mode):
    """`rgb` with coverage `a` blended over the backdrop (standard alpha compositing with a blend mode; on an opaque
    backdrop it is exactly the Mix node: back + a * (blend - back)). Clamped to 0-1 like the nodes. -> (rgb, alpha)"""
    blended = BLEND_FUNCTIONS[mode](back_rgb, rgb)
    a3, b3 = a[..., None], back_a[..., None]
    alpha = a + back_a * (1 - a)
    out = ((1 - a3) * b3 * back_rgb + a3 * ((1 - b3) * rgb + b3 * blended)) / np.maximum(alpha, 1e-8)[..., None]
    return np.clip(out, 0.0, 1.0).astype(np.float32), alpha.astype(np.float32)


def default_linear(ch):
    """What a channel is below its bottom layer (linear light): the starting color of a new image."""
    rgb = np.array(ch.color[:3], np.float32)
    return to_linear(rgb) if ch.srgb else rgb


# -----------------------------------------------------------------------------
# Data

def _changed(self, context):
    """Property update: the node chains and the paint target follow the layer data."""
    if not MK._muted[0] and isinstance(self.id_data, bpy.types.Material):
        refresh(context, self.id_data)


class M3D_LayerChannel(PropertyGroup):
    """What a layer holds for one channel: an image (paint layers, made when it is first painted) or a fill value."""
    channel: StringProperty()
    use: BoolProperty(name="Enabled", default=False, update=_changed,
                      description="The layer has this channel (paint layers make the image when it is first painted)")
    image: PointerProperty(type=bpy.types.Image, update=_changed)
    color: FloatVectorProperty(name="Color", size=4, subtype='COLOR', min=0.0, max=1.0, default=(0.8, 0.8, 0.8, 1.0),
                               update=_changed)
    value: FloatProperty(name="Value", min=0.0, max=1.0, default=0.5, update=_changed)


def _expanded_changed(self, context):
    """Closing a folder that holds the active layer makes the folder active (the list would show nothing selected)."""
    mat = self.id_data
    if self.expanded or MK._muted[0] or not isinstance(mat, bpy.types.Material):
        return
    active = active_layer(mat)
    if active is not None and any(a.uid == self.uid for a in ancestors(active)):
        with muted():
            mat.m3d_layer_index = index_of(mat, self.uid)
        refresh(context, mat)


class M3D_Layer(PropertyGroup):
    """One layer of a material's stack (or a folder of layers)."""
    name: StringProperty(name="Name", default="Layer", update=_changed)
    uid: StringProperty(description="Names the layer's nodes")
    kind: EnumProperty(name="Type", default='PAINT', items=(
        ('PAINT', "Paint Layer", "Pixels you paint, one image per channel"),
        ('FILL', "Fill Layer", "A value or color over the whole mesh (use a mask to limit it)"),
        ('FOLDER', "Folder", "Layers that are combined with each other first, then blended onto the stack below")))
    parent: StringProperty(description="uid of the folder the layer is in (empty: it is not in a folder)")
    expanded: BoolProperty(name="Expanded", default=True, update=_expanded_changed,
                           description="Show the layers inside the folder in the list")
    frozen: BoolProperty(name="Frozen", default=False, description="The folder is baked into one image per channel: its "
                         "layers are kept, but cannot be edited until the folder is unfrozen")
    visible: BoolProperty(name="Visible", default=True, update=_changed)
    use_alpha: BoolProperty(name="Image Alpha", default=True, update=_changed,
                            description="The image's transparency shows the layers below (off for the Base layer made from "
                            "existing paint slots, where alpha was never used)")
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_changed)
    blend: EnumProperty(name="Blend", default='MIX', items=[(k, label, "") for k, label in BLENDS], update=_changed,
                        description="How the layer combines with the layers below (the Normal channel always mixes)")
    channels: CollectionProperty(type=M3D_LayerChannel)
    mask_stack: CollectionProperty(type=MK.M3D_MaskEffect)   # The mask: effects combined from the bottom up.
    mask_index: IntProperty(name="Active Effect", default=0, min=0, update=_changed)
    paint_mask: BoolProperty(name="Paint Mask", default=False, update=_changed,
                             description="Brush strokes go to the mask's Paint effect instead of the layer's channel")
    # Before mask stacks a layer had one mask image (and Invert Mask): upgrade() turns them into effects.
    mask: PointerProperty(type=bpy.types.Image, update=_changed)
    mask_invert: BoolProperty(name="Invert Mask", default=False, update=_changed)


def entry_of(layer, ch_id):
    return layer.channels[CHANNEL_INDEX[ch_id]]


def active_layer(mat):
    i = mat.m3d_layer_index
    return mat.m3d_layers[i] if 0 <= i < len(mat.m3d_layers) else None


def active_effect(layer):
    stack = layer.mask_stack
    return stack[layer.mask_index] if 0 <= layer.mask_index < len(stack) else None


def paint_effect(layer):
    """The Paint effect strokes go to: the selected one, else the top-most (None: the mask has none)."""
    e = active_effect(layer)
    return e if e is not None and e.kind == 'PAINT' else next((e for e in list(layer.mask_stack)[::-1] if e.kind == 'PAINT'), None)


# Folders: the layers of a folder are the ones whose `parent` is its uid; a folder is listed after them (see the top).

def layer_by_uid(mat, uid):
    return next((l for l in mat.m3d_layers if l.uid == uid), None)


def index_of(mat, uid):
    return next((i for i, l in enumerate(mat.m3d_layers) if l.uid == uid), -1)


def kids_of(mat, uid=""):
    """The layers directly inside a folder (empty uid: at the top level), bottom to top."""
    return [l for l in mat.m3d_layers if l.parent == uid]


def children(layer):
    return kids_of(layer.id_data, layer.uid) if layer.kind == 'FOLDER' else []


def descendants(layer):
    """Everything inside a folder, in stack order (a nested folder after its own layers)."""
    out = []
    for kid in children(layer):
        out += descendants(kid) + [kid]
    return out


def ancestors(layer):
    """The folders a layer is in, innermost first."""
    found, parent = [], layer.parent
    while parent and len(found) < 64:   # (a damaged file with a loop ends here)
        folder = layer_by_uid(layer.id_data, parent)
        if folder is None:
            break
        found.append(folder)
        parent = folder.parent
    return found


def depth_of(layer):
    return len(ancestors(layer))


def in_frozen(layer):
    """Is the layer inside a frozen folder (so it is kept in the data but not in the node chains, and not editable)?"""
    return any(a.frozen for a in ancestors(layer))


def frozen_root(layer):
    """The outermost frozen folder the layer is in, or is itself (None: it is live)."""
    found = [a for a in ancestors(layer) if a.frozen]
    return found[-1] if found else layer if layer.kind == 'FOLDER' and layer.frozen else None


def live_layers(mat):
    """The layers the node chains are made of: all but the ones inside a frozen folder."""
    layers = list(mat.m3d_layers)
    frozen = {l.uid for l in layers if l.frozen}
    if not frozen:
        return layers
    parents = {l.uid: l.parent for l in layers}

    def dead(layer):
        parent, hops = layer.parent, 0
        while parent and hops < 64:
            if parent in frozen:
                return True
            parent, hops = parents.get(parent), hops + 1
        return False
    return [l for l in layers if not dead(l)]


def uses_image(layer):
    """Does the layer read an image per channel: a paint layer's, or a frozen folder's."""
    return layer.kind == 'PAINT' or (layer.kind == 'FOLDER' and layer.frozen)


def has_content(layer, ch_id):
    """Does the layer change this channel: a fill value, a painted (or frozen) image, or (a folder that is not frozen)
    anything inside it."""
    if layer.kind == 'FOLDER' and not layer.frozen:
        return any(has_content(kid, ch_id) for kid in children(layer))
    e = entry_of(layer, ch_id)
    return e.use and (layer.kind == 'FILL' or e.image is not None)


def content_channels(mat):
    top = kids_of(mat)
    return [ch.id for ch in CHANNELS if any(has_content(l, ch.id) for l in top)]


def fill_rgba(layer, ch_id):
    """The fill color of a layer's channel (linear light, as the Mix node takes it)."""
    e = entry_of(layer, ch_id)
    if ch_id == 'NORMAL':
        return (0.5, 0.5, 1.0, 1.0)   # Flat: a fill layer resets the normals (use a mask to limit it).
    if ch_id in SCALARS:
        return (e.value, e.value, e.value, 1.0)
    return tuple(e.color)


def layer_images(layer):
    return [e.image for e in layer.channels if e.image] + MK.owned_images(layer) + ([layer.mask] if layer.mask else [])


def stack_images(mat):
    out = []
    for layer in mat.m3d_layers:
        out += [img for img in layer_images(layer) if img not in out]
    return out


def memory_bytes(mat):
    return sum(w * h * (16 if img.is_float else 4) for img in stack_images(mat) for w, h in [image_size(img)])


def memory_equivalent(mat):
    """The stack's images in units of one 4K image (8 bit RGBA)."""
    return memory_bytes(mat) / (4096 * 4096 * 4)


def stack_size(mat):
    """Largest side of the stack's channel images (0: none yet)."""
    return max((max(image_size(e.image)) for l in mat.m3d_layers for e in l.channels if e.image), default=0)


def image_in_use(image):
    """Is the image used by anything else: a layer of any material, or a node the stack did not make."""
    if image.use_fake_user:
        return True
    for mat in bpy.data.materials:
        for layer in mat.m3d_layers:
            if layer.mask == image or any(e.image == image for e in layer.channels) or any(
                    e.image == image or e.image2 == image for e in layer.mask_stack):
                return True
        if mat.node_tree and any(n.type in {'TEX_IMAGE', 'TEX_ENVIRONMENT'} and n.image == image and TAG not in n.keys()
                                 for n in mat.node_tree.nodes):
            return True
    return False


def release(images):
    """Remove images nothing uses any more (call after the layers and nodes using them are gone)."""
    for image in {i.name: i for i in images if i is not None}.values():
        if not image_in_use(image):
            bpy.data.images.remove(image)


# -----------------------------------------------------------------------------
# Node chains

# Settings of the nodes the chains make that the user may have set (or that came from the node a layer replaced): they
# are carried over when a chain is rebuilt, so tiling, interpolation, Normal Map and Bump strengths are not lost.
_PROPS = {'TEX_IMAGE': ("interpolation", "extension", "projection", "projection_blend"),
          'NORMAL_MAP': ("space", "uv_map"), 'BUMP': ("invert",)}
_VALUES = {'NORMAL_MAP': ("Strength",), 'BUMP': ("Strength", "Distance")}
_LINKED = {'TEX_IMAGE': ("Vector",), 'NORMAL_MAP': ("Strength",), 'BUMP': ("Strength", "Distance")}
_carry = {}   # node name -> settings, waiting for the node to be made


def settings_of(node):
    """(properties, input values, {input: socket feeding it}) of a node, for the kinds in _PROPS."""
    return ({k: getattr(node, k) for k in _PROPS.get(node.type, ())},
            {k: node.inputs[k].default_value for k in _VALUES.get(node.type, ())},
            {k: l.from_socket for k in _LINKED.get(node.type, ()) for l in node.inputs[k].links
             if TAG not in l.from_node.keys()})


def restore_settings(node):
    props, values, links = _carry.pop(node.name, ({}, {}, {}))
    for key, value in props.items():
        setattr(node, key, value)
    for key, value in values.items():
        node.inputs[key].default_value = value
    for key, socket in links.items():
        node.id_data.links.new(socket, node.inputs[key])


def part(ch_id, uid, key):
    return "%s.%s.%s.%s" % (TAG, ch_id, uid, key)


def chain_tree(layers, ch_id):
    """[(layer, inside)] of the layers (one level, bottom to top) that change channel `ch_id`: `inside` is the same for
    the layers of a folder that is not frozen (a frozen folder is one image, like a paint layer)."""
    return [(l, chain_tree(children(l), ch_id) if l.kind == 'FOLDER' and not l.frozen else [])
            for l in layers if has_content(l, ch_id)]


def walk(tree):
    """Every layer of a chain_tree, a folder's layers before the folder."""
    for layer, inside in tree:
        yield from walk(inside)
        yield layer


def signature(tree, ch_id):
    """What decides the chain's nodes and links; anything else (opacity, blend, fill, names) is only a value."""
    return repr([(l.uid, l.kind, entry_of(l, ch_id).image.name if uses_image(l) else "", bool(l.mask_stack), l.use_alpha,
                  *((signature(inside, ch_id),) if inside else ())) for l, inside in tree])


def set_values(nt, layer, ch_id):
    """Opacity, visibility, blend mode, fill value and names of a layer's nodes (no node or link changes)."""
    opv = nt.nodes.get(part(ch_id, layer.uid, "opv"))
    if opv is None:
        return
    mix, fill = nt.nodes.get(part(ch_id, layer.uid, "mix")), nt.nodes.get(part(ch_id, layer.uid, "fill"))
    want = layer.opacity if layer.visible else 0.0
    if abs(opv.inputs[1].default_value - want) > 1e-6:
        opv.inputs[1].default_value = want
    blend = 'MIX' if ch_id == 'NORMAL' else layer.blend
    if mix is not None and mix.blend_type != blend:
        mix.blend_type = blend
    if layer.kind == 'FILL':   # (inside a folder a fill is a color node: both its Mix nodes read it)
        target = fill.outputs[0] if fill is not None else mix.inputs[7] if mix is not None else None
        if target is not None:
            _set(target, fill_rgba(layer, ch_id))
    for key in ("mix", "tex", "fill"):
        node = nt.nodes.get(part(ch_id, layer.uid, key))
        if node is not None and node.label != layer.name:
            node.label = layer.name


# The mask chain of a layer: per effect, [map image ->] node group (or image / fill) -> Mix (blend, factor = opacity)
# over the effect below; the first one over white. All of it in one frame per layer, tagged "MASK".

def mask_signature(layer):
    """What decides the mask chain's nodes and links; everything else (values, blend, opacity) is only a value."""
    return repr([(e.uid, e.kind, e.image.name if e.image else "", e.image2.name if e.image2 else "",
                  e.space if e.kind == 'NOISE' else "") for e in layer.mask_stack])


def mask_node(nt, layer, key, e):
    return nt.nodes.get(part("MASK", layer.uid, "%s.%s" % (key, e.uid)))


def mask_top(nt, layer):
    """The socket holding the layer's mask (None: no mask effects)."""
    node = mask_node(nt, layer, "mix", layer.mask_stack[-1]) if len(layer.mask_stack) else None
    return node.outputs[2] if node is not None else None


def build_mask(mat, layer, index, sig):
    nt, bsdf = mat.node_tree, principled_of(mat)
    nodes, links = nt.nodes, nt.links
    y = bsdf.location.y - 700 - len(CHANNELS) * 900 - index * 700
    x0 = bsdf.location.x - 800 - len(layer.mask_stack) * 700
    frame = nodes.new("NodeFrame")
    frame.name, frame.label = "%s.MASK.%s" % (TAG, layer.uid), "Mask: " + layer.name
    frame[TAG], frame["m3d_mask"], frame["m3d_sig"] = "MASK", layer.uid, sig

    def new(idname, key, e, x, y_):
        node = nodes.new(idname)
        node.name = part("MASK", layer.uid, "%s.%s" % (key, e.uid))
        node[TAG], node["m3d_mask"] = "MASK", layer.uid
        node.parent = frame
        node.location = (x, y_)
        restore_settings(node)
        return node

    below = None
    for i, e in enumerate(layer.mask_stack):
        x, kind = x0 + i * 700, e.kind
        mix = new("ShaderNodeMix", "mix", e, x + 450, y)
        mix.data_type, mix.clamp_result = 'RGBA', True
        value = None

        def image_socket(key, image, y_):
            tex = new("ShaderNodeTexImage", key, e, x, y_)
            tex.image = image
            return tex.outputs["Color"]

        if kind in {'PAINT', 'BLUR'}:
            if e.image is not None:
                bw = new("ShaderNodeRGBToBW", "bw", e, x + 250, y)   # The mask is the image's luminance.
                links.new(image_socket("tex", e.image, y), bw.inputs["Color"])
                value = bw.outputs["Val"]
        elif kind in MK.GROUPED:
            grp = new("ShaderNodeGroup", "grp", e, x + 250, y)
            grp.node_tree = MK.group_of(kind)
            if kind in MK.FILTERS:
                if below is None:
                    grp.inputs["Value"].default_value = 1.0
                else:
                    links.new(below.outputs[2], grp.inputs["Value"])
            elif kind == 'NOISE':
                coord = new("ShaderNodeTexCoord", "coord", e, x, y)
                links.new(coord.outputs["Object" if e.space == 'OBJECT' else "UV"], grp.inputs["Vector"])
            else:
                sockets = ("Normal", "Position") if kind == 'TOPDOWN' else ("Map",)
                for n, (name, image) in enumerate(zip(sockets, (e.image, e.image2))):
                    if image is not None:
                        links.new(image_socket("tex%d" % n if n else "tex", image, y - 300 * n), grp.inputs[name])
            value = grp.outputs["Value"]
        if below is None:
            mix.inputs[6].default_value = (1.0, 1.0, 1.0, 1.0)
        else:
            links.new(below.outputs[2], mix.inputs[6])
        if value is not None:
            links.new(value, mix.inputs[7])
        below = mix


def _set(socket, value):
    """Set a socket's default value when it differs (no needless updates)."""
    now = socket.default_value
    if hasattr(now, "__len__"):
        if any(abs(a - b) > 1e-6 for a, b in zip(now, value)):
            socket.default_value = value
    elif abs(now - value) > 1e-6:
        socket.default_value = value


def set_mask_values(nt, layer):
    """Opacity, visibility, blend modes, fill values, group inputs and names of a layer's mask nodes."""
    for e in layer.mask_stack:
        mix = mask_node(nt, layer, "mix", e)
        if mix is None:
            return
        _set(mix.inputs[0], e.opacity if e.visible else 0.0)
        blend = 'MIX' if e.kind in MK.FILTERS else e.blend
        if mix.blend_type != blend:
            mix.blend_type = blend
        if e.kind == 'FILL':
            _set(mix.inputs[7], (e.value, e.value, e.value, 1.0))
        grp = mask_node(nt, layer, "grp", e)
        if grp is not None:
            for name, value in MK.params(e).items():
                _set(grp.inputs[name], value)
        for node in (mix, grp):
            if node is not None and node.label != e.name:
                node.label = e.name


def rebuild_masks(mat):
    """Make the mask chains match the layers' mask stacks: nothing to do when only values changed. True when nodes changed."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    if nt is None or bsdf is None:
        return False
    live = {l.uid for l in live_layers(mat)}   # (the layers of a frozen folder have no nodes)
    wanted = {l.uid: (i, l) for i, l in enumerate(mat.m3d_layers) if l.mask_stack and l.uid in live}
    changed = False
    for uid in {n["m3d_mask"] for n in nt.nodes if n.get(TAG) == "MASK"}:
        frame = nt.nodes.get("%s.MASK.%s" % (TAG, uid))
        if uid in wanted and frame is not None and frame.get("m3d_sig") == mask_signature(wanted[uid][1]):
            continue
        for node in [n for n in nt.nodes if n.get(TAG) == "MASK" and n.get("m3d_mask") == uid]:
            if node.type in _PROPS:
                _carry[node.name] = settings_of(node)
            nt.nodes.remove(node)
        changed = True
    for uid, (i, layer) in wanted.items():
        if nt.nodes.get("%s.MASK.%s" % (TAG, uid)) is None:
            build_mask(mat, layer, i, mask_signature(layer))
            changed = True
    return changed


def link_masks(mat):
    """Feed every channel chain's mask multiply from its layer's mask chain (the chains are made apart)."""
    nt = mat.node_tree
    for layer in mat.m3d_layers:
        top = mask_top(nt, layer)
        for ch in CHANNELS if top is not None else ():
            mul = nt.nodes.get(part(ch.id, layer.uid, "maskmul"))
            if mul is not None and not any(l.from_socket == top for l in mul.inputs[1].links):
                nt.links.new(top, mul.inputs[1])


def build_channel(mat, ch, tree, sig):
    """The frame with one chain for `ch`: Image Texture (or fill) -> Mix per layer, bottom to top, into the shader. The
    layers of a folder are chained the same way first, but over nothing instead of the channel's value: that chain
    carries the color and the coverage (how much of the pixel the layers cover), and the folder is one more layer of
    the chain below it, its image being that color and its alpha that coverage."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    nodes, links = nt.nodes, nt.links
    y = bsdf.location.y - 700 - CHANNEL_INDEX[ch.id] * 900
    x_top = bsdf.location.x - 800
    frame = nodes.new("NodeFrame")
    frame.name, frame.label = "%s.%s" % (TAG, ch.id), ch.label + " Layers"
    frame[TAG], frame["m3d_sig"] = ch.id, sig
    columns, placed = len(list(walk(tree))), [0]

    def new(idname, name, x, y_):
        node = nodes.new(idname)
        node.name = name
        node[TAG] = ch.id
        node.parent = frame
        node.location = (x, y_)
        restore_settings(node)
        return node

    def mix_node(layer, key, x, y_, data_type='RGBA', clamp=False):
        node = new("ShaderNodeMix", part(ch.id, layer.uid, key), x, y_)
        node.data_type, node.clamp_result = data_type, clamp
        return node

    def source(layer, inside, depth):
        """The nodes every layer has: color and factor (coverage x opacity x mask). -> (x, y, color socket (None: a
        fill, which the caller makes), factor socket)"""
        color = cover = None
        if inside:
            color, cover = stacked(inside, depth + 1)
        x, uid, y_ = x_top - (columns - 1 - placed[0]) * 1000, layer.uid, y - depth * 450
        placed[0] += 1
        opv = new("ShaderNodeMath", part(ch.id, uid, "opv"), x + 300, y_ - 80)   # coverage x opacity (0 when hidden)
        opv.operation = 'MULTIPLY'
        if inside:
            links.new(cover, opv.inputs[0])
        elif uses_image(layer):
            tex = new("ShaderNodeTexImage", part(ch.id, uid, "tex"), x, y_)
            tex.image = entry_of(layer, ch.id).image
            color = tex.outputs["Color"]
            if layer.use_alpha:
                links.new(tex.outputs["Alpha"], opv.inputs[0])
            else:
                opv.inputs[0].default_value = 1.0
        else:
            opv.inputs[0].default_value = 1.0
        factor = opv.outputs[0]
        if layer.mask_stack:
            mul = new("ShaderNodeMath", part(ch.id, uid, "maskmul"), x + 500, y_ - 200)   # x the layer's mask
            mul.operation = 'MULTIPLY'
            links.new(factor, mul.inputs[0])
            factor = mul.outputs[0]
        return x, y_, color, factor

    def stacked(items, depth):
        """A folder's layers over nothing: -> (color, coverage) sockets of the result. A layer (color k, factor f) over
        a result (c, a): its color is blended only where there is something below, s = mix(k, blend(c, k), a); the
        new color is c moved toward s by f / a', the new coverage is a' = a + f (1 - a): what `over` does."""
        color = cover = None
        for layer, inside in items:
            x, y_, src, factor = source(layer, inside, depth)
            if src is None:
                src = new("ShaderNodeRGB", part(ch.id, layer.uid, "fill"), x, y_).outputs[0]
            if color is None:
                color, cover = src, factor
            else:
                blended = mix_node(layer, "mix", x + 750, y_)
                blended.inputs[0].default_value = 1.0
                links.new(color, blended.inputs[6])
                links.new(src, blended.inputs[7])
                shown = mix_node(layer, "shown", x + 750, y_ - 250)
                links.new(cover, shown.inputs[0])
                links.new(src, shown.inputs[6])
                links.new(blended.outputs[2], shown.inputs[7])
                total = mix_node(layer, "total", x + 500, y_ - 400, 'FLOAT')
                links.new(factor, total.inputs[0])
                links.new(cover, total.inputs[2])
                total.inputs[3].default_value = 1.0
                share = new("ShaderNodeMath", part(ch.id, layer.uid, "share"), x + 750, y_ - 450)
                share.operation = 'DIVIDE'
                links.new(factor, share.inputs[0])
                links.new(total.outputs[0], share.inputs[1])
                out = mix_node(layer, "out", x + 900, y_ - 150, clamp=True)
                links.new(share.outputs[0], out.inputs[0])
                links.new(color, out.inputs[6])
                links.new(shown.outputs[2], out.inputs[7])
                color, cover = out.outputs[2], total.outputs[0]
            set_values(nt, layer, ch.id)
        return color, cover

    below = None
    for layer, inside in tree:
        x, y_, src, factor = source(layer, inside, 0)
        mix = mix_node(layer, "mix", x + 750, y_, clamp=True)
        if src is not None:
            links.new(src, mix.inputs[7])
        links.new(factor, mix.inputs[0])
        if below is None:
            mix.inputs[6].default_value = (*default_linear(ch), 1.0)
        else:
            links.new(below.outputs[2], mix.inputs[6])
        below = mix
        set_values(nt, layer, ch.id)
    top = below.outputs[2]
    if ch.id in SOCKETS:
        links.new(top, bsdf.inputs[SOCKETS[ch.id]])
        if ch.id == 'EMISSION' and bsdf.inputs["Emission Strength"].default_value <= 0.0:
            bsdf.inputs["Emission Strength"].default_value = 1.0
    elif ch.id == 'NORMAL':
        node = new("ShaderNodeNormalMap", "%s.NORMAL.map" % TAG, bsdf.location.x - 300, y)
        node.space = 'TANGENT'
        links.new(top, node.inputs["Color"])
    else:
        node = new("ShaderNodeBump", "%s.HEIGHT.bump" % TAG, bsdf.location.x - 300, y)
        links.new(top, node.inputs["Height"])


def link_normal(mat):
    """The Principled BSDF's Normal comes from our Bump node (fed by our Normal Map node when there is one), else from
    our Normal Map node; a link from a node the stack did not make is left alone when we have neither."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    normal_map, bump = nt.nodes.get("%s.NORMAL.map" % TAG), nt.nodes.get("%s.HEIGHT.bump" % TAG)
    final = bump or normal_map
    if final is None:
        return
    if normal_map and bump and not any(l.from_node == normal_map for l in bump.inputs["Normal"].links):
        nt.links.new(normal_map.outputs[0], bump.inputs["Normal"])
    if not any(l.from_node == final for l in bsdf.inputs["Normal"].links):
        nt.links.new(final.outputs[0], bsdf.inputs["Normal"])


SCRATCH = "m3dScratch"   # Image of the node strokes go to when nothing can be painted (never saved or exported).


def ensure_scratch(mat):
    """The scratch image: an 8 x 8 image in an unconnected, tagged Image Texture node of the material (which makes it a
    paint slot). Painting it changes nothing anyone sees."""
    bsdf = principled_of(mat)
    if bsdf is None:
        return None
    nodes = mat.node_tree.nodes
    node = nodes.get("%s.scratch" % TAG)
    if node is None:
        node = nodes.new("ShaderNodeTexImage")
        node.name, node[TAG] = "%s.scratch" % TAG, "SCRATCH"
        node.label, node.hide = "Paint target when nothing can be painted", True
        node.location = (bsdf.location.x - 1000, bsdf.location.y + 500)
        node.image = bpy.data.images.get(SCRATCH) or bpy.data.images.new(SCRATCH, 8, 8, alpha=False)
        bpy.context.view_layer.update()   # Lists it as a paint slot.
    return node.image


def remove_scratch(mat):
    node = mat.node_tree.nodes.get("%s.scratch" % TAG) if mat.node_tree else None
    if node is not None:
        image = node.image
        mat.node_tree.nodes.remove(node)
        if image is not None and not any(n.image == image for m in bpy.data.materials if m.node_tree
                                         for n in m.node_tree.nodes if n.type == 'TEX_IMAGE'):
            bpy.data.images.remove(image)


def refresh_slots(mat):
    """Blender lists a material's paint slots when an image node's image is set (not when a node is removed): set one."""
    probe = mat.node_tree.nodes.new("ShaderNodeTexImage")
    probe.image = None
    bpy.context.view_layer.update()
    mat.node_tree.nodes.remove(probe)


def rebuild(mat, ch_id):
    """Make channel `ch_id`'s chain match the layers: nothing to do when only values changed, otherwise the channel's
    nodes are removed and made again. Idempotent. True when nodes changed."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    if nt is None or bsdf is None:
        return False
    tree = chain_tree(kids_of(mat), ch_id)
    sig = signature(tree, ch_id)
    frame = nt.nodes.get("%s.%s" % (TAG, ch_id))
    if frame is not None and tree and frame.get("m3d_sig") == sig:
        for layer in walk(tree):
            set_values(nt, layer, ch_id)
        return False
    ours = [n for n in nt.nodes if n.get(TAG) == ch_id]
    for node in ours:
        if node.type in _PROPS:
            _carry[node.name] = settings_of(node)
        nt.nodes.remove(node)
    if tree:
        build_channel(mat, CHANNEL_BY_ID[ch_id], tree, sig)
    if ch_id in {'NORMAL', 'HEIGHT'}:
        link_normal(mat)
    return bool(ours or tree)


def rebuild_all(mat):
    upgrade(mat)
    live = live_layers(mat)
    for layer in live:
        MK.ensure_caches(layer)
    changed = [rebuild_masks(mat)] + [rebuild(mat, ch.id) for ch in CHANNELS]
    _carry.clear()
    if not mat.m3d_layers:
        remove_scratch(mat)
    if any(changed):
        refresh_slots(mat)
    if mat.node_tree is not None:
        link_masks(mat)
        for layer in live:
            set_mask_values(mat.node_tree, layer)
            MK.refresh_blurs(layer)
        sync_maskview(mat)
    return any(changed)


# -----------------------------------------------------------------------------
# Show Mask: the material shows the active layer's mask instead of its shader

MASKVIEW = "%s.maskview" % TAG


def output_node(nt):
    outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    return next((n for n in outs if n.is_active_output), outs[0] if outs else None)


def maskview_off(mat):
    """Back to the shader: our Emission node goes and the link it replaced (remembered on the material) returns."""
    nt = mat.node_tree
    emit, state, out = nt.nodes.get(MASKVIEW), mat.get("m3d_maskview"), output_node(nt)
    if emit is not None:
        nt.nodes.remove(emit)
    node = nt.nodes.get(state[0]) if state else None
    socket = next((s for s in node.outputs if s.identifier == state[1]), None) if node is not None else None
    if socket is not None and out is not None:
        nt.links.new(socket, out.inputs["Surface"])
    if "m3d_maskview" in mat.keys():
        del mat["m3d_maskview"]


def sync_maskview(mat):
    """Make the material match Material.m3d_show_mask: on, the Material Output shows an Emission node fed by the
    active layer's mask (white when it has none); the link it replaces is kept in the material's m3d_maskview."""
    nt = mat.node_tree
    out = output_node(nt) if nt is not None else None
    if nt is None or out is None or not mat.m3d_show_mask:
        if nt is not None and (nt.nodes.get(MASKVIEW) is not None or "m3d_maskview" in mat.keys()):
            maskview_off(mat)
        return
    surface = out.inputs["Surface"]
    emit = nt.nodes.get(MASKVIEW)
    if "m3d_maskview" not in mat.keys():
        link = surface.links[0] if surface.links and surface.links[0].from_node != emit else None
        mat["m3d_maskview"] = [link.from_node.name, link.from_socket.identifier] if link else []
    if emit is None:
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.name, emit.label, emit[TAG] = MASKVIEW, "Show Mask", "MASKVIEW"
        emit.location = (out.location.x - 250, out.location.y - 200)
    layer = active_layer(mat)
    top = mask_top(nt, layer) if layer is not None else None
    color = emit.inputs["Color"]
    if top is not None:
        if not any(l.from_socket == top for l in color.links):
            nt.links.new(top, color)
    else:
        for link in list(color.links):
            nt.links.remove(link)
        color.default_value = (1.0, 1.0, 1.0, 1.0)
    if not any(l.from_node == emit for l in surface.links):
        nt.links.new(emit.outputs[0], surface)


def _show_mask_changed(self, _context):
    sync_maskview(self)


# -----------------------------------------------------------------------------
# Mask effects

def upgrade(mat):
    """Files from before mask stacks: a layer's mask image becomes a Paint effect (and Invert Mask an Invert filter),
    so the layer looks the same. True when a layer was upgraded."""
    done = False
    for layer in mat.m3d_layers:
        if layer.mask is None:
            continue
        with muted():
            e = add_effect(layer, 'PAINT', "Mask")
            e.image = layer.mask
            if layer.mask_invert:
                add_effect(layer, 'INVERT')
            layer.mask, layer.mask_invert = None, False
        done = True
    return done


def add_effect(layer, kind, name=None, white=True):
    """A new effect at the end of the layer's mask stack (the caller places it). Over other effects a source is
    neutral at first: a white Paint or a generator multiplies, a black Paint adds."""
    first = not len(layer.mask_stack)
    with muted():
        e = layer.mask_stack.add()
        e.uid = MK.new_uid()
        e.kind = kind
        e.name = name or MK.unique_name(layer, MK.KIND_BY_ID[kind].label)
        for key, value in MK.OVERRIDES.get(kind, {}).items():
            setattr(e, key, value)
        if not first and kind not in MK.FILTERS and kind != 'FILL':
            e.blend = 'ADD' if kind == 'PAINT' and not white else 'MULTIPLY'
    return e


def place_effect(layer):
    """Move the effect just added (the last one) up to sit above the selected one, and select it. Returns its index."""
    stack = layer.mask_stack
    target = min(layer.mask_index + 1, len(stack) - 1) if len(stack) > 1 else 0
    stack.move(len(stack) - 1, target)
    with muted():
        layer.mask_index = target
    return target


def assign_map(e, key, image):
    setattr(e, ("image", "image2")[MK.needed_maps(e).index(key)], image)


def map_keys(mat):
    """The baked maps the material's mask effects read."""
    return sorted({key for layer in mat.m3d_layers for e in layer.mask_stack for key in MK.needed_maps(e)})


def link_maps(mat, ob, replace=False):
    """Effects that read a baked map the mesh has since (a bake in the Bake tab, an effect made before the bake) pick
    it up; `replace`: every effect reads this mesh's maps (the texture set's, see m3d_texture.texture_set)."""
    import m3d_texture
    with muted():
        for layer in mat.m3d_layers:
            for e in layer.mask_stack:
                have = MK.map_images(e)
                for key in MK.needed_maps(e):
                    image = m3d_texture.map_image(ob, MK.MAP_LABELS[key])
                    if image is not None and (replace or have[key] is None):
                        assign_map(e, key, image)


def prepare(context, mat):
    """Before the stack is flattened: bake the maps its mask effects still miss, bring the blur caches up to date."""
    ob = mesh_of(context)
    missing = {key for layer in mat.m3d_layers for _e, key in MK.missing_maps(layer)}
    if missing and ob is not None and ob.active_material == mat and ob.data.uv_layers:
        import m3d_texture
        m3d_texture.ensure_maps(context, ob, sorted(missing))
        link_maps(mat, ob)
    rebuild_all(mat)


# -----------------------------------------------------------------------------
# Images and the paint target

def image_name(mat, layer, label):
    return ("%s_%s_%s" % (mat.name, layer.name, label.replace(" ", "")))[:60]


def make_channel_image(mat, layer, ch, size, opaque):
    """A new image for a layer's channel. `opaque`: the bottom layer's kind, filled with the channel's starting color
    (data channels without alpha, like a new paint slot); otherwise transparent, so only painted pixels show."""
    alpha = ch.id == 'BASE_COLOR' or not opaque
    image = bpy.data.images.new(image_name(mat, layer, ch.label), size, size, alpha=alpha, is_data=not ch.srgb)
    image.generated_color = (*ch.color[:3], 1.0 if opaque else 0.0)
    set_channel_space(image, ch)
    return image


def make_mask_image(mat, layer, size, white):
    """The image of a Paint effect: white shows the layer, black hides it."""
    image = bpy.data.images.new(image_name(mat, layer, "Mask"), size, size, alpha=False, is_data=True)
    image.generated_color = (1.0, 1.0, 1.0, 1.0) if white else (0.0, 0.0, 0.0, 1.0)
    return image


def copy_image(image, name):
    w, h = image.size
    new = bpy.data.images.new(name[:60], w, h, alpha=image.depth in {32, 128}, float_buffer=image.is_float,
                              is_data=image.colorspace_settings.is_data)
    new.colorspace_settings.name = image.colorspace_settings.name
    if "m3d_channel" in image.keys():
        new["m3d_channel"] = image["m3d_channel"]
    write_pixels(new, pixels_of(image, w))
    return new


def new_size(context):
    return int(context.scene.m3d_tex.resolution)


def target_image(context, mat, create):
    """The image strokes should go to: the active layer's Paint effect when Paint Mask is on (always for a fill layer or
    a folder), else its image for the active channel (made here when `create`). None for a fill layer or a folder
    without a Paint effect, a layer in a frozen folder, or a channel the layer does not have."""
    index = mat.m3d_layer_index
    layer = active_layer(mat)
    if layer is None or in_frozen(layer):   # (a frozen folder's layers are no paint slots: nothing can be painted)
        return None
    effect = paint_effect(layer)
    if effect is not None and (layer.paint_mask or layer.kind != 'PAINT'):
        return effect.image
    ch = CHANNEL_BY_ID[mat.m3d_channel]
    e = entry_of(layer, ch.id)
    if layer.kind != 'PAINT' or not e.use:
        return None
    if e.image is None and create:
        with muted():
            e.image = make_channel_image(mat, layer, ch, new_size(context), opaque=index == 0)
        rebuild_all(mat)
    return e.image


def sync_target(context, mat, create):
    """Point the material's paint slot at the paint target (see target_image)."""
    image = target_image(context, mat, create)
    if image is None and len(mat.m3d_layers):
        image = ensure_scratch(mat)   # Nothing paintable here: strokes must not land on some other layer's image.
    images = list(mat.texture_paint_images)
    if image is not None and image in images:
        mat.paint_active_slot = images.index(image)
    return image


def refresh(context, mat):
    """The layer data changed: rebuild the chains, then aim the brush."""
    ob = getattr(context, "object", None)
    if ob is not None and ob.type == 'MESH' and ob.active_material == mat:
        link_maps(mat, ob)
    rebuild_all(mat)
    if ob is not None and ob.type == 'MESH' and ob.active_material == mat:
        sync_target(context, mat, True)


def paint_channel(context, ob, ch):
    """Paint channel `ch` on the active layer: the layer gets the channel and, once, its image. Returns the image."""
    mat = ob.active_material
    layer = active_layer(mat)
    if layer is None:
        return None
    with muted():
        mat.m3d_channel = ch.id
        if in_frozen(layer):
            raise RuntimeError("The folder is frozen: unfreeze it to paint its layers")
        if layer.kind == 'FOLDER' and paint_effect(layer) is None:
            raise RuntimeError("A folder cannot be painted: pick a layer inside it")
        if layer.kind == 'FILL' and paint_effect(layer) is None:
            raise RuntimeError("A Fill Layer cannot be painted: use Convert to Paint Layer")
        if layer.kind == 'PAINT':
            entry_of(layer, ch.id).use = True
            layer.paint_mask = False
    return sync_target(context, mat, True)


def stack_slots(mat):
    """{channel id: (slot index, image)}: where each channel with a painted image is painted, the active layer first."""
    images = list(mat.texture_paint_images)
    found = {}
    active = mat.m3d_layer_index
    order = [active] + [i for i in reversed(range(len(mat.m3d_layers))) if i != active]
    for ch in CHANNELS:
        for i in order:
            if not 0 <= i < len(mat.m3d_layers):
                continue
            layer = mat.m3d_layers[i]
            e = entry_of(layer, ch.id)
            if layer.kind == 'PAINT' and e.use and e.image is not None and e.image in images:
                found[ch.id] = (images.index(e.image), e.image)
                break
    return found


# -----------------------------------------------------------------------------
# Compositing (numpy): what the node chain computes, for Merge Down, Flatten and Export

def layer_planes(layer, ch, size):
    """(linear rgb, coverage) of a layer's channel: the image alpha x opacity x mask (0 when hidden) is the coverage. A
    folder is what its layers make together over nothing (or its frozen image: the same, within what the image stores)."""
    e = entry_of(layer, ch.id)
    if layer.kind == 'FOLDER' and not layer.frozen:
        rgb, alpha = stack_planes(children(layer), ch, size)
    elif layer.kind == 'FILL':
        rgb = np.broadcast_to(np.array(fill_rgba(layer, ch.id)[:3], np.float32), (size, size, 3))
        alpha = np.ones((size, size), np.float32)
    else:
        px = pixels_of(e.image, size)
        rgb, alpha = px[..., :3], px[..., 3] if layer.use_alpha else np.ones((size, size), np.float32)
        if ch.srgb:
            rgb = to_linear(rgb)
    alpha = alpha * np.float32(layer.opacity if layer.visible else 0.0)
    if layer.mask_stack:
        alpha = alpha * MK.stack_value(layer, size)
    return rgb, alpha


def stack_planes(layers, ch, size, rgb=None, alpha=None):
    """`layers` (bottom to top) composited over (rgb, alpha), over nothing when those are not given: (rgb, alpha)."""
    if rgb is None:
        rgb, alpha = np.zeros((size, size, 3), np.float32), np.zeros((size, size), np.float32)
    for layer in layers:
        if has_content(layer, ch.id):
            lrgb, la = layer_planes(layer, ch, size)
            rgb, alpha = over(rgb, alpha, lrgb, la, 'MIX' if ch.id == 'NORMAL' else layer.blend)
    return rgb, alpha


def composite(mat, ch_id, size):
    """The channel's visible stack over the channel's starting value, in linear light: (size, size, 3)."""
    ch = CHANNEL_BY_ID[ch_id]
    rgb = np.broadcast_to(default_linear(ch), (size, size, 3)).astype(np.float32)
    return stack_planes(kids_of(mat), ch, size, rgb, np.ones((size, size), np.float32))[0]


def encode(ch, rgb, alpha=None):
    """Linear light to the values an image of this channel stores (sRGB encoded, or as is for data)."""
    out = np.ones(rgb.shape[:2] + (4,), np.float32)
    out[..., :3] = to_srgb(rgb) if ch.srgb else rgb
    if alpha is not None:
        out[..., 3] = alpha
    return out


def flatten_channel(mat, ch_id, size):
    """The channel as it looks, ready for a file: (size, size, 4), opaque. Single-value channels are grey, as the
    shader reads them."""
    ch = CHANNEL_BY_ID[ch_id]
    rgb = composite(mat, ch_id, size)
    if ch_id in SCALARS:
        rgb = np.repeat((rgb @ MK.LUMA)[..., None], 3, axis=-1)
    return encode(ch, rgb)


@contextmanager
def flattened_material(ob, mat, size):
    """For exporters that read the material: the slots using `mat` hold a copy where the layer chains are replaced by
    one flattened image per channel. The layers and their nodes are not touched; everything temporary goes after."""
    temp = mat.copy()
    images = []
    slots = [s for s in ob.material_slots if s.material == mat]
    try:
        nt = temp.node_tree
        maskview_off(temp)   # Show Mask replaced the shader's link: the exporter needs it back.
        for node in [n for n in nt.nodes if TAG in n.keys()]:
            nt.nodes.remove(node)
        bsdf = principled_of(temp)
        for ch_id in content_channels(mat):
            if ch_id == 'HEIGHT':
                continue   # glTF has no height map.
            ch = CHANNEL_BY_ID[ch_id]
            image = bpy.data.images.new("m3dFlat" + ch_id, size, size, alpha=False, is_data=not ch.srgb)
            write_pixels(image, flatten_channel(mat, ch_id, size))
            set_channel_space(image, ch)
            images.append(image)
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = image
            if ch_id == 'NORMAL':
                node = nt.nodes.new("ShaderNodeNormalMap")
                nt.links.new(tex.outputs["Color"], node.inputs["Color"])
                nt.links.new(node.outputs["Normal"], bsdf.inputs["Normal"])
            else:
                nt.links.new(tex.outputs["Color"], bsdf.inputs[SOCKETS[ch_id]])
        if 'EMISSION' in content_channels(mat):
            bsdf.inputs["Emission Strength"].default_value = 1.0
        for slot in slots:
            slot.material = temp
        yield temp
    finally:
        for slot in slots:
            slot.material = mat
        bpy.data.materials.remove(temp)
        for image in images:
            bpy.data.images.remove(image)


# -----------------------------------------------------------------------------
# Layer edits (all of them leave the chains rebuilt by their operator)

def unique_name(mat, base):
    names = {l.name for l in mat.m3d_layers}
    return next(n for n in (base, *("%s %d" % (base, i) for i in range(2, 10000))) if n not in names)


def add_layer(mat, kind, name=None):
    """A new layer at the end of the stack (the caller moves it)."""
    layer = mat.m3d_layers.add()
    with muted():
        layer.uid = uuid.uuid4().hex[:6]
        layer.name = name or unique_name(mat, {'PAINT': "Paint Layer", 'FILL': "Fill Layer", 'FOLDER': "Folder"}[kind])
        layer.kind = kind
        for ch in CHANNELS:
            e = layer.channels.add()
            e.channel = ch.id
            e.use = kind == 'PAINT' or (kind == 'FILL' and ch.id == 'BASE_COLOR')
            e.color = (*default_linear(ch), 1.0)
            e.value = ch.color[0]
    return layer


def read_tree(mat):
    """{folder uid (empty: the top level): [uid of each layer directly inside, bottom to top]}; every folder is a key."""
    tree = {"": []}
    for layer in mat.m3d_layers:
        tree.setdefault(layer.parent, []).append(layer.uid)
        if layer.kind == 'FOLDER':
            tree.setdefault(layer.uid, [])
    return tree


def write_tree(mat, tree):
    """Make the stack follow `tree` (see read_tree): parents are set and the layers put in order, each folder right
    after the layers inside it. A tree that does not hold every layer once is ignored."""
    order, parents = [], {}

    def flatten(uid):
        for kid in tree.get(uid, ()):
            parents[kid] = uid
            flatten(kid)
            order.append(kid)
    flatten("")
    layers = mat.m3d_layers
    if sorted(order) != sorted(l.uid for l in layers):
        return
    with muted():
        for layer in layers:
            if layer.parent != parents[layer.uid]:
                layer.parent = parents[layer.uid]
        for i, uid in enumerate(order):
            j = next(k for k in range(i, len(layers)) if layers[k].uid == uid)
            if j != i:
                layers.move(j, i)


def activate(mat, uid):
    with muted():
        mat.m3d_layer_index = max(index_of(mat, uid), 0)


def anchor_of(mat):
    """uid of the layer a new layer goes above: the active one (the frozen folder it is in, when it is in one). Empty:
    there is none."""
    layer = active_layer(mat)
    if layer is None:
        return ""
    return (frozen_root(layer) if in_frozen(layer) else layer).uid


def place_above(mat, uid, anchor_uid):
    """Put the layer `uid` (and what is inside it) directly above the layer `anchor_uid`, in the folder that one is in.
    Without an anchor it goes on top of the stack."""
    tree = read_tree(mat)
    for kids in tree.values():
        if uid in kids:
            kids.remove(uid)
    kids = next((k for k in tree.values() if anchor_uid and anchor_uid in k), tree[""])
    kids.insert(kids.index(anchor_uid) + 1 if anchor_uid in kids else len(kids), uid)
    write_tree(mat, tree)


def add_folder(mat, anchor_uid, group=False):
    """A new empty folder above the layer `anchor_uid` (the top of the stack without one); `group`: that layer is
    moved into the folder, which takes its place. Returns the folder's uid."""
    uid = add_layer(mat, 'FOLDER').uid
    tree = read_tree(mat)
    tree[""].remove(uid)
    tree[uid] = []
    kids = next((k for k in tree.values() if anchor_uid and anchor_uid in k), tree[""])
    if anchor_uid in kids and group:
        kids[kids.index(anchor_uid)] = uid
        tree[uid].append(anchor_uid)
    else:
        kids.insert(kids.index(anchor_uid) + 1 if anchor_uid in kids else len(kids), uid)
    write_tree(mat, tree)
    return uid


def step_layer(mat, layer, delta):
    """Move a layer (with what is inside it) one place up (delta > 0) or down in the list the way it is shown: past a
    neighbour, into an open folder next to it, or out of the folder it is at the end of. False at the ends."""
    tree, up = read_tree(mat), delta > 0
    uid, parent = layer.uid, layer.parent
    kids = tree[parent]
    k = kids.index(uid)
    j = k + (1 if up else -1)
    if 0 <= j < len(kids):
        other = layer_by_uid(mat, kids[j])
        if other.kind == 'FOLDER' and other.expanded and not other.frozen:
            kids.remove(uid)
            tree[other.uid].insert(0 if up else len(tree[other.uid]), uid)
        else:
            kids[k], kids[j] = kids[j], kids[k]
    elif parent:
        kids.remove(uid)
        outer = tree[layer_by_uid(mat, parent).parent]
        outer.insert(outer.index(parent) + (1 if up else 0), uid)
    else:
        return False
    write_tree(mat, tree)
    return True


def move_into(mat, layer, folder):
    """The layer (with what is inside it) goes to the top of `folder`, which is opened. False when that cannot be: a
    folder cannot go into itself, into a folder inside it, or into a frozen folder."""
    if folder.frozen or in_frozen(folder) or folder.uid == layer.uid or any(a.uid == layer.uid for a in ancestors(folder)):
        return False
    tree, uid = read_tree(mat), folder.uid
    tree[layer.parent].remove(layer.uid)
    tree[uid].append(layer.uid)
    write_tree(mat, tree)
    with muted():
        layer_by_uid(mat, uid).expanded = True   # (the layers moved in memory: look the folder up again)
    return True


def move_out(mat, layer):
    """The layer (with what is inside it) goes above the folder it is in. False when it is not in one."""
    parent = layer_by_uid(mat, layer.parent)
    if parent is None:
        return False
    tree = read_tree(mat)
    tree[parent.uid].remove(layer.uid)
    outer = tree[parent.parent]
    outer.insert(outer.index(parent.uid) + 1, layer.uid)
    write_tree(mat, tree)
    return True


def migrate(mat):
    """A material with paint slots but no layers: each slot's image becomes a channel of the bottom layer "Base" (no
    pixels change); the image nodes that fed the shader directly, and their Normal Map / Bump nodes, are replaced by
    the chains, which take over their settings (interpolation, extension, projection, a linked Vector input such as a
    Mapping node, Normal Map space / UV map / strength, Bump invert / strength / distance). True when a layer was made."""
    if len(mat.m3d_layers) or mat.node_tree is None:
        return False
    found = {}
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image is not None and TAG not in node.keys():
            ch = node_channel(node)
            if ch and ch not in found:
                found[ch] = node
    if not found:
        return False
    images = list(mat.texture_paint_images)
    active = images[mat.paint_active_slot] if mat.paint_active_slot < len(images) else None
    layer = add_layer(mat, 'PAINT', "Base")
    with muted():
        layer.use_alpha = False   # A slot's alpha never showed anything through: the look must not change.
        for ch in CHANNELS:
            e = entry_of(layer, ch.id)
            e.use = ch.id in found
            if ch.id in found:
                e.image = found[ch.id].image
                found[ch.id].image["m3d_channel"] = ch.id
                if e.image == active:
                    mat.m3d_channel = ch.id   # The slot that was being painted stays the channel being painted.
        mat.m3d_layer_index = 0
    for ch_id, node in found.items():
        _carry[part(ch_id, layer.uid, "tex")] = settings_of(node)
        mids = [l.to_node for l in node.outputs[0].links if l.to_node.type in {'NORMAL_MAP', 'BUMP'}]
        mat.node_tree.nodes.remove(node)
        for mid in mids:
            _carry["%s.%s.%s" % (TAG, ch_id, "map" if mid.type == 'NORMAL_MAP' else "bump")] = settings_of(mid)
            if all(s.name in _LINKED[mid.type] or not s.links for s in mid.inputs):
                mat.node_tree.nodes.remove(mid)
    return True


def subtree(layer):
    """A layer and everything inside it (a folder is last)."""
    return descendants(layer) + [layer]


def remove_layers(mat, uids):
    layers = mat.m3d_layers
    with muted():
        for i in reversed(range(len(layers))):
            if layers[i].uid in uids:
                layers.remove(i)


def delete_layer(mat, index):
    """Remove a layer (a folder: with everything inside it) and its nodes; its images go too unless something else uses
    them."""
    group = subtree(mat.m3d_layers[index])
    images = [img for l in group for img in layer_images(l)]
    remove_layers(mat, {l.uid for l in group})
    with muted():
        mat.m3d_layer_index = max(0, min(index - len(group) + 1, len(mat.m3d_layers) - 1))
    rebuild_all(mat)
    release(images)


def copy_layer(mat, uid):
    """A copy of one layer, with copies of its images, at the end of the stack (the caller places it)."""
    src = layer_by_uid(mat, uid)
    new = add_layer(mat, src.kind)   # Adding can move the collection: look the source up again.
    src = layer_by_uid(mat, uid)
    with muted():
        new.name = unique_name(mat, src.name + " Copy")
        new.visible, new.opacity, new.blend, new.use_alpha = src.visible, src.opacity, src.blend, src.use_alpha
        new.paint_mask, new.expanded, new.frozen = src.paint_mask, src.expanded, src.frozen
        for ch in CHANNELS:
            a, b = entry_of(src, ch.id), entry_of(new, ch.id)
            b.use, b.color, b.value = a.use, a.color, a.value
            if a.image is not None:
                b.image = copy_image(a.image, image_name(mat, new, ch.label))
        for e in src.mask_stack:   # Paint images are copied; the blur caches are made again; baked maps are shared.
            copy = new.mask_stack.add()
            MK.copy_params(e, copy)
            copy.uid = MK.new_uid()
            copy.image2 = e.image2
            if e.kind == 'PAINT':
                copy.image = copy_image(e.image, image_name(mat, new, "Mask"))
            elif e.kind != 'BLUR':
                copy.image = e.image
        new.mask_index = src.mask_index
    return new


def duplicate_layer(mat, index):
    """Copy a layer, or a folder with everything inside it, just above it (images are copied). Returns the index of the
    copy (a folder's copy is listed after its layers)."""
    top = mat.m3d_layers[index]
    group = subtree(top)
    uids, parents, top_uid, top_parent = [l.uid for l in group], {l.uid: l.parent for l in group}, top.uid, top.parent
    copies = {uid: copy_layer(mat, uid).uid for uid in uids}
    tree = read_tree(mat)
    for uid in copies.values():
        tree[""].remove(uid)
    for uid in uids[:-1]:
        tree[copies[parents[uid]]].append(copies[uid])
    kids = tree[top_parent]
    kids.insert(kids.index(top_uid) + 1, copies[top_uid])
    write_tree(mat, tree)
    return index_of(mat, copies[top_uid])


def below_sibling(layer):
    """The layer directly under this one in the same folder (None: it is the lowest there)."""
    kids = kids_of(layer.id_data, layer.parent)
    k = next(i for i, l in enumerate(kids) if l.uid == layer.uid)
    return kids[k - 1] if k else None


def merge_down(mat, index, default_size):
    """Flatten layer `index` (a folder with its layers is one layer too) into the one below it in the same folder. Per
    channel the two are composited (the upper layer's blend mode over the lower layer) into the lower layer's image; its
    opacity and mask are baked into the pixels. Exact when the lower layer is opaque or the upper one uses Mix; the
    merged layer keeps the lower layer's blend mode."""
    top = mat.m3d_layers[index]
    low = below_sibling(top)
    group = subtree(top)
    low_uid, group_uids = low.uid, {l.uid for l in group}
    images = [img for l in group for img in layer_images(l)]
    old_masks = []
    if top.visible:
        chans = [ch for ch in CHANNELS if has_content(top, ch.id) or has_content(low, ch.id)]
        sizes = [max(image_size(e.image)) for l in (*group, low) for e in l.channels if e.image]
        size = max(sizes, default=default_size)
        with muted():
            for ch in chans:
                zero = (np.zeros((size, size, 3), np.float32), np.zeros((size, size), np.float32))
                rgb, alpha = layer_planes(low, ch, size) if has_content(low, ch.id) else zero
                top_rgb, top_alpha = layer_planes(top, ch, size) if has_content(top, ch.id) else zero
                rgb, alpha = over(rgb, alpha, top_rgb, top_alpha, 'MIX' if ch.id == 'NORMAL' else top.blend)
                e = entry_of(low, ch.id)
                if e.image is None:
                    e.image = make_channel_image(mat, low, ch, size, opaque=False)
                elif max(image_size(e.image)) != size:
                    e.image.scale(size, size)
                write_pixels(e.image, encode(ch, rgb, alpha))
                e.use = True
            low.kind, low.opacity, low.visible, low.use_alpha = 'PAINT', 1.0, True, True
            old_masks = MK.owned_images(low)
            low.mask_stack.clear()
            low.mask_index, low.paint_mask = 0, False
    remove_layers(mat, group_uids)
    activate(mat, low_uid)
    rebuild_all(mat)
    release(images + old_masks)


# Folders: freezing and merging

def folder_size(folder, default_size):
    """Size of the images a folder is baked into: the largest image of the layers inside it (the default without any)."""
    return max((max(image_size(e.image)) for l in descendants(folder) for e in l.channels if e.image),
               default=default_size)


def bake_folder(mat, folder, default_size):
    """What the folder's layers make together over nothing, as one image per channel they change (the alpha is what
    they cover), stored the way a paint layer's images are. -> {channel id: image}"""
    size, kids, images = folder_size(folder, default_size), children(folder), {}
    for ch in CHANNELS:
        if any(has_content(kid, ch.id) for kid in kids):
            rgb, alpha = stack_planes(kids, ch, size)
            images[ch.id] = make_channel_image(mat, folder, ch, size, opaque=False)
            write_pixels(images[ch.id], encode(ch, rgb, alpha))
    return images


def set_folder_images(mat, folder, images, label=""):
    """The folder's own image per channel (the frozen ones, or the paint layer a merged folder becomes)."""
    with muted():
        for ch in CHANNELS:
            e = entry_of(folder, ch.id)
            e.use, e.image = ch.id in images, images.get(ch.id)
            if e.image is not None:
                e.image.name = image_name(mat, folder, ch.label + label)


def freeze_folder(mat, index, default_size):
    """Bake the folder into one image per channel it changes: it costs one texture read per channel from then on. Its
    layers stay in the data (not in the node chains, not editable) until the folder is unfrozen."""
    folder = mat.m3d_layers[index]
    uid, active = folder.uid, active_layer(mat)
    set_folder_images(mat, folder, bake_folder(mat, folder, default_size), " Frozen")
    with muted():
        folder.use_alpha, folder.frozen = True, True
        if active is not None and any(a.uid == uid for a in ancestors(active)):
            mat.m3d_layer_index = index_of(mat, uid)
    rebuild_all(mat)


def unfreeze_folder(mat, index):
    folder = mat.m3d_layers[index]
    images = [e.image for e in folder.channels if e.image]
    with muted():
        folder.frozen = False
    set_folder_images(mat, folder, {})
    rebuild_all(mat)
    release(images)


def merge_folder(mat, index, default_size):
    """Turn a folder into one paint layer holding what its layers make together (or its frozen images): the layers inside
    are deleted, the paint layer keeps the folder's name, blend mode, opacity, visibility and mask. Nothing changes in
    the look."""
    folder = mat.m3d_layers[index]
    uid = folder.uid
    inside = descendants(folder)
    images = [img for l in inside for img in layer_images(l)]
    made = ({e.channel: e.image for e in folder.channels if e.image} if folder.frozen
            else bake_folder(mat, folder, default_size))
    remove_layers(mat, {l.uid for l in inside})
    folder = layer_by_uid(mat, uid)   # (the layers moved in memory)
    set_folder_images(mat, folder, made)
    with muted():
        folder.kind, folder.frozen, folder.use_alpha = 'PAINT', False, True
    activate(mat, uid)
    rebuild_all(mat)
    release(images)


def flatten_all(mat, default_size):
    """Replace the stack by one opaque "Base" layer holding what it looks like (hidden layers are dropped)."""
    chans = content_channels(mat)
    size = stack_size(mat) or default_size
    flat = {c: flatten_channel(mat, c, size) for c in chans}
    old = stack_images(mat)
    with muted():
        mat.m3d_layers.clear()
        base = add_layer(mat, 'PAINT', "Base")
        for ch in CHANNELS:
            e = entry_of(base, ch.id)
            e.use = ch.id in flat
            if ch.id in flat:
                e.image = make_channel_image(mat, base, ch, size, opaque=True)
                write_pixels(e.image, flat[ch.id])
        mat.m3d_layer_index = 0
    rebuild_all(mat)
    release(old)


def convert_layer(mat, index, size):
    layer = mat.m3d_layers[index]
    with muted():
        for ch in CHANNELS:
            e = entry_of(layer, ch.id)
            if e.use:
                rgb = np.broadcast_to(np.array(fill_rgba(layer, ch.id)[:3], np.float32), (size, size, 3))
                e.image = make_channel_image(mat, layer, ch, size, opaque=True)
                write_pixels(e.image, encode(ch, rgb))
        layer.kind = 'PAINT'
    rebuild_all(mat)


# -----------------------------------------------------------------------------
# Operators

class _LayerOp:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        mat = ob.active_material if ob is not None else None
        return mat is not None and principled_of(mat) is not None

    @staticmethod
    def material(context):
        return mesh_of(context).active_material


class _ActiveLayerOp(_LayerOp):
    """Needs an active layer that can be edited (not one inside a frozen folder)."""
    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        layer = active_layer(mesh_of(context).active_material)
        return layer is not None and not in_frozen(layer)


def _done(context, mat):
    refresh(context, mat)
    return {'FINISHED'}


class M3D_OT_layer_add(_LayerOp, Operator):
    """Add a layer above the active one. The paint slots a material already has become its bottom layer first"""
    bl_idname = "m3d.layer_add"
    bl_label = "Add Layer"

    kind: EnumProperty(items=(('PAINT', "Paint Layer", ""), ('FILL', "Fill Layer", "")))

    @classmethod
    def description(cls, _context, props):
        if props.kind == 'FILL':
            return "Add a Fill Layer: a value or color over the whole mesh (limit it with a mask)"
        return "Add a Paint Layer: a transparent layer you paint, one image per channel (made when first painted)"

    def execute(self, context):
        mat = self.material(context)
        migrate(mat)
        anchor, uid = anchor_of(mat), add_layer(mat, self.kind).uid
        place_above(mat, uid, anchor)
        activate(mat, uid)
        return _done(context, mat)


class M3D_OT_layer_folder_add(_LayerOp, Operator):
    """Add a folder above the active layer: its layers are combined with each other first, then the result is blended
    onto the stack below with the folder's blend mode, opacity and mask"""
    bl_idname = "m3d.layer_folder_add"
    bl_label = "New Folder"

    group: BoolProperty(name="Group Active", default=False,
                        description="Put the active layer into the new folder instead of leaving it empty")

    @classmethod
    def description(cls, _context, props):
        if props.group:
            return "Put the active layer into a new folder (a folder blends, fades and masks its layers together)"
        return "Add an empty folder above the active layer (move layers into it with Move Into Folder or the arrows)"

    def execute(self, context):
        mat = self.material(context)
        migrate(mat)
        activate(mat, add_folder(mat, anchor_of(mat), self.group))
        return _done(context, mat)


class M3D_OT_layer_duplicate(_ActiveLayerOp, Operator):
    """Duplicate the active layer, or the active folder with its layers (images are copied)"""
    bl_idname = "m3d.layer_duplicate"
    bl_label = "Duplicate Layer"

    def execute(self, context):
        mat = self.material(context)
        index = duplicate_layer(mat, mat.m3d_layer_index)
        with muted():
            mat.m3d_layer_index = index
        return _done(context, mat)


class M3D_OT_layer_remove(_ActiveLayerOp, Operator):
    """Delete the active layer, or the active folder with its layers, and their images (images used elsewhere stay)"""
    bl_idname = "m3d.layer_remove"
    bl_label = "Delete Layer"

    def execute(self, context):
        mat = self.material(context)
        delete_layer(mat, mat.m3d_layer_index)
        return _done(context, mat)


class M3D_OT_layer_move(_ActiveLayerOp, Operator):
    """Move the active layer up (above its neighbour) or down in the stack, one place of the list at a time: it enters
    an open folder next to it and leaves a folder at its first or last place"""
    bl_idname = "m3d.layer_move"
    bl_label = "Move Layer"

    delta: IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Move the active layer %s (into and out of open folders)" % ("up" if props.delta > 0 else "down")

    def execute(self, context):
        mat = self.material(context)
        uid = active_layer(mat).uid
        if not step_layer(mat, active_layer(mat), self.delta):
            return {'CANCELLED'}
        activate(mat, uid)
        return _done(context, mat)


def target_folders(mat, layer):
    """The folders the layer could be moved into: not itself or one of its own, not frozen or inside a frozen one."""
    inside = {l.uid for l in subtree(layer)}
    return [f for f in mat.m3d_layers if f.kind == 'FOLDER' and f.uid not in inside and not f.frozen
            and not in_frozen(f) and f.uid != layer.parent]


_folder_items = []   # (Python must keep the strings of a dynamic enum alive)


def folder_items(_self, context):
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    layer = active_layer(mat) if mat is not None else None
    _folder_items[:] = [(f.uid, f.name, "Move the layer to the top of this folder")
                        for f in (target_folders(mat, layer) if layer is not None else [])]
    return _folder_items or [("", "No folder", "")]


class M3D_OT_layer_move_into(_ActiveLayerOp, Operator):
    """Move the active layer (a folder: with its layers) to the top of a folder"""
    bl_idname = "m3d.layer_move_into"
    bl_label = "Move Into Folder"
    bl_property = "folder"   # (the search list of invoke)

    folder: EnumProperty(name="Folder", items=folder_items)

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        mat = mesh_of(context).active_material
        return bool(target_folders(mat, active_layer(mat)))

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        mat = self.material(context)
        layer, folder = active_layer(mat), layer_by_uid(mat, self.folder)
        uid = layer.uid
        if folder is None or folder.uid not in {f.uid for f in target_folders(mat, layer)}                 or not move_into(mat, layer, folder):
            self.report({'WARNING'}, "Pick a folder that is not frozen")
            return {'CANCELLED'}
        activate(mat, uid)
        return _done(context, mat)


class M3D_OT_layer_move_out(_ActiveLayerOp, Operator):
    """Move the active layer out of its folder, to the place above the folder"""
    bl_idname = "m3d.layer_move_out"
    bl_label = "Move Out of Folder"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and bool(active_layer(mesh_of(context).active_material).parent)

    def execute(self, context):
        mat = self.material(context)
        uid = active_layer(mat).uid
        if not move_out(mat, active_layer(mat)):
            return {'CANCELLED'}
        activate(mat, uid)
        return _done(context, mat)


def folder_index(mat, index, freeze):
    """Index of the folder an operator is for. `index` is a layer of the list (negative: the active layer). Freezing:
    that folder, or the one the layer is in; unfreezing: the outermost frozen folder it is in. -1: there is none."""
    i = mat.m3d_layer_index if index < 0 else index
    layer = mat.m3d_layers[i] if 0 <= i < len(mat.m3d_layers) else None
    if layer is None:
        return -1
    if freeze:
        folder = layer if layer.kind == 'FOLDER' else layer_by_uid(mat, layer.parent)
        return index_of(mat, folder.uid) if folder is not None and not folder.frozen and not in_frozen(folder) else -1
    folder = frozen_root(layer)
    return index_of(mat, folder.uid) if folder is not None else -1


class M3D_OT_layer_freeze(_LayerOp, Operator):
    """Freeze the folder: its layers are baked into one image per channel, so it costs about one texture read per
    channel while you work on the rest. The layers stay in the folder but cannot be edited until it is unfrozen"""
    bl_idname = "m3d.layer_freeze"
    bl_label = "Freeze Folder"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'}, description="Layer of the list (-1: the active one)")

    def execute(self, context):
        mat = self.material(context)
        i = folder_index(mat, self.index, True)
        if i < 0:
            self.report({'WARNING'}, "Select a folder (or a layer in one) that is not frozen")
            return {'CANCELLED'}
        prepare(context, mat)
        freeze_folder(mat, i, new_size(context))
        folder = mat.m3d_layers[i]
        images = [e.image for e in folder.channels if e.image]
        self.report({'INFO'}, "Froze %s: %d images of %d px" % (folder.name, len(images),
                                                               max(image_size(images[0])) if images else 0))
        return _done(context, mat)


class M3D_OT_layer_unfreeze(_LayerOp, Operator):
    """Unfreeze the folder: its layers are live again (the frozen images are deleted) and can be edited"""
    bl_idname = "m3d.layer_unfreeze"
    bl_label = "Unfreeze Folder"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'}, description="Layer of the list (-1: the active one)")

    def execute(self, context):
        mat = self.material(context)
        i = folder_index(mat, self.index, False)
        if i < 0:
            self.report({'WARNING'}, "Select a frozen folder (or a layer in one)")
            return {'CANCELLED'}
        unfreeze_folder(mat, i)
        return _done(context, mat)


class M3D_OT_layer_merge_folder(_ActiveLayerOp, Operator):
    """Merge the active folder into one paint layer: the layers inside are combined into its images and deleted; the
    new layer keeps the folder's blend mode, opacity and mask. The look does not change"""
    bl_idname = "m3d.layer_merge_folder"
    bl_label = "Merge Folder"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).kind == 'FOLDER'

    def execute(self, context):
        mat = self.material(context)
        prepare(context, mat)
        merge_folder(mat, mat.m3d_layer_index, new_size(context))
        return _done(context, mat)


class M3D_OT_layer_visible(_ActiveLayerOp, Operator):
    """Show or hide the active layer"""
    bl_idname = "m3d.layer_visible"
    bl_label = "Show / Hide Layer"

    def execute(self, context):
        layer = active_layer(self.material(context))
        layer.visible = not layer.visible
        return {'FINISHED'}


class M3D_OT_layer_mask_add(_ActiveLayerOp, Operator):
    """Add a mask to the active layer: a Paint effect that starts white (the layer shows everywhere) or black (hidden
    everywhere). Add more effects on top of it"""
    bl_idname = "m3d.layer_mask_add"
    bl_label = "Add Mask"

    fill: EnumProperty(name="Start", default='WHITE', items=(
        ('WHITE', "White (Show All)", "The layer shows everywhere; paint black to hide it"),
        ('BLACK', "Black (Hide All)", "The layer is hidden; paint white to show it")))

    @classmethod
    def poll(cls, context):
        return super().poll(context) and not active_layer(mesh_of(context).active_material).mask_stack

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        white = self.fill == 'WHITE'
        e = add_effect(layer, 'PAINT', white=white)
        with muted():
            e.image = make_mask_image(mat, layer, new_size(context), white)
            layer.mask_index, layer.paint_mask = 0, True
        return _done(context, mat)


class M3D_OT_layer_mask_remove(_ActiveLayerOp, Operator):
    """Remove the active layer's mask with all its effects (paint images are deleted unless something else uses them)"""
    bl_idname = "m3d.layer_mask_remove"
    bl_label = "Remove Mask"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and bool(active_layer(mesh_of(context).active_material).mask_stack)

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        images = MK.owned_images(layer)
        with muted():
            layer.mask_stack.clear()
            layer.mask_index, layer.paint_mask = 0, False
        rebuild_all(mat)
        release(images)
        return _done(context, mat)


class M3D_OT_layer_mask_invert(_ActiveLayerOp, Operator):
    """Invert the active layer's mask (the layer shows where it was hidden): adds an Invert effect on top, or removes it
    again"""
    bl_idname = "m3d.layer_mask_invert"
    bl_label = "Invert Mask"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and bool(active_layer(mesh_of(context).active_material).mask_stack)

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        stack = layer.mask_stack
        with muted():
            if stack[-1].kind == 'INVERT':
                stack.remove(len(stack) - 1)
            else:
                add_effect(layer, 'INVERT')
            layer.mask_index = len(stack) - 1
        return _done(context, mat)


class M3D_OT_layer_paint_mask(_ActiveLayerOp, Operator):
    """Switch between painting the active layer's mask (its selected Paint effect; one is added when it has none) and
    its channel"""
    bl_idname = "m3d.layer_paint_mask"
    bl_label = "Paint Mask"

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        if not layer.paint_mask and paint_effect(layer) is None:
            e = add_effect(layer, 'PAINT')
            with muted():
                e.image = make_mask_image(mat, layer, new_size(context), True)
                place_effect(layer)
        layer.paint_mask = not layer.paint_mask
        return _done(context, mat)


class M3D_OT_mask_effect_add(_ActiveLayerOp, Operator):
    """Add an effect to the active layer's mask, above the selected one"""
    bl_idname = "m3d.mask_effect_add"
    bl_label = "Add Mask Effect"

    kind: EnumProperty(items=[(k.id, k.label, k.text) for k in MK.KINDS])
    fill: EnumProperty(name="Start", default='WHITE', items=(
        ('WHITE', "White", "A new Paint effect starts white: paint black to hide the layer"),
        ('BLACK', "Black", "A new Paint effect starts black: paint white to show the layer")))

    @classmethod
    def description(cls, _context, props):
        text = MK.KIND_BY_ID[props.kind].text
        if props.kind == 'PAINT':
            return text + (" (starts black)" if props.fill == 'BLACK' else " (starts white)")
        return text + (" (baked once from the mesh)" if MK.KIND_BY_ID[props.kind].maps else "")

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        needs = MK.KIND_BY_ID[self.kind].maps
        images = {}
        if needs:
            ob = mesh_of(context)
            if not ob.data.uv_layers:
                self.report({'WARNING'}, "This mesh has no UVs: use Auto Unwrap")
                return {'CANCELLED'}
            import m3d_texture
            try:
                images = m3d_texture.ensure_maps(context, ob, needs)
            except RuntimeError as err:
                self.report({'ERROR'}, str(err).strip())
                return {'CANCELLED'}
        white = self.fill == 'WHITE'
        e = add_effect(layer, self.kind, white=white)
        with muted():
            if self.kind == 'PAINT':
                e.image = make_mask_image(mat, layer, new_size(context), white)
                layer.paint_mask = True
            for key, image in images.items():
                assign_map(e, key, image)
            place_effect(layer)
        return _done(context, mat)


class M3D_OT_mask_effect_remove(_ActiveLayerOp, Operator):
    """Remove the selected mask effect (a Paint effect's image is deleted unless something else uses it)"""
    bl_idname = "m3d.mask_effect_remove"
    bl_label = "Remove Mask Effect"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_effect(active_layer(mesh_of(context).active_material)) is not None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        i = layer.mask_index
        e = layer.mask_stack[i]
        images = [e.image] if e.kind in MK.OWNED and e.image is not None else []
        with muted():
            layer.mask_stack.remove(i)
            layer.mask_index = max(0, min(i, len(layer.mask_stack) - 1))
            if paint_effect(layer) is None:
                layer.paint_mask = False
        rebuild_all(mat)
        release(images)
        return _done(context, mat)


class M3D_OT_mask_effect_move(_ActiveLayerOp, Operator):
    """Move the selected mask effect up (later in the bottom-up order) or down"""
    bl_idname = "m3d.mask_effect_move"
    bl_label = "Move Mask Effect"

    delta: IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Move the selected mask effect %s" % ("up" if props.delta > 0 else "down")

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_effect(active_layer(mesh_of(context).active_material)) is not None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        i, j = layer.mask_index, layer.mask_index + self.delta
        if not 0 <= j < len(layer.mask_stack):
            return {'CANCELLED'}
        layer.mask_stack.move(i, j)
        with muted():
            layer.mask_index = j
        return _done(context, mat)


class M3D_OT_mask_effect_duplicate(_ActiveLayerOp, Operator):
    """Duplicate the selected mask effect (a Paint effect's image is copied)"""
    bl_idname = "m3d.mask_effect_duplicate"
    bl_label = "Duplicate Mask Effect"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_effect(active_layer(mesh_of(context).active_material)) is not None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        i = layer.mask_index
        src = layer.mask_stack[i]
        with muted():
            e = layer.mask_stack.add()
            MK.copy_params(src, e)
            e.uid, e.name = MK.new_uid(), MK.unique_name(layer, src.name + " Copy")
            e.image2 = src.image2
            if src.kind == 'PAINT':
                e.image = copy_image(src.image, image_name(mat, layer, "Mask"))
            elif src.kind != 'BLUR':
                e.image = src.image
            layer.mask_stack.move(len(layer.mask_stack) - 1, i + 1)
            layer.mask_index = i + 1
        return _done(context, mat)


class M3D_OT_mask_rebake(_ActiveLayerOp, Operator):
    """Bake the maps the mask effects read again (Edges, Cavity, Top-down, Thickness, Noise in Object space), at the
    resolution of the Bake tab. Use it after the mesh or the bake settings changed"""
    bl_idname = "m3d.mask_rebake"
    bl_label = "Rebake Maps"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return super().poll(context) and bool(ob.data.uv_layers) and bool(map_keys(ob.active_material))

    def execute(self, context):
        ob = mesh_of(context)
        mat = ob.active_material
        import m3d_texture
        try:
            m3d_texture.ensure_maps(context, ob, map_keys(mat), force=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        link_maps(mat, ob, replace=True)
        return _done(context, mat)


class M3D_OT_layer_merge_down(_ActiveLayerOp, Operator):
    """Merge the active layer (or folder) into the layer below it in the same folder (the pixels are combined with the
    layer's blend mode, opacity and mask; the result keeps the lower layer's blend mode)"""
    bl_idname = "m3d.layer_merge_down"
    bl_label = "Merge Down"

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        low = below_sibling(active_layer(mesh_of(context).active_material))
        return low is not None and low.kind != 'FOLDER'

    def execute(self, context):
        mat = self.material(context)
        prepare(context, mat)
        merge_down(mat, mat.m3d_layer_index, new_size(context))
        return _done(context, mat)


class M3D_OT_layer_flatten(_ActiveLayerOp, Operator):
    """Flatten the whole stack into one layer (hidden layers are dropped). The look does not change"""
    bl_idname = "m3d.layer_flatten"
    bl_label = "Flatten"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and len(mesh_of(context).active_material.m3d_layers) > 1

    def execute(self, context):
        mat = self.material(context)
        prepare(context, mat)
        flatten_all(mat, new_size(context))
        return _done(context, mat)


class M3D_OT_layer_convert(_ActiveLayerOp, Operator):
    """Turn the active Fill Layer into a Paint Layer holding the fill, so it can be painted"""
    bl_idname = "m3d.layer_convert"
    bl_label = "Convert to Paint Layer"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).kind == 'FILL'

    def execute(self, context):
        mat = self.material(context)
        convert_layer(mat, mat.m3d_layer_index, new_size(context))
        return _done(context, mat)


# -----------------------------------------------------------------------------
# UI list of the stack (top layer first)

KIND_ICONS = {'PAINT': 'IMAGE_DATA', 'FILL': 'COLOR', 'FOLDER': 'FILE_FOLDER'}


class M3D_UL_layers(UIList):
    def filter_items(self, _context, data, propname):
        """Hide what is inside a folder that is closed."""
        layers = list(getattr(data, propname))
        closed = {l.uid for l in layers if l.kind == 'FOLDER' and not l.expanded}
        parents = {l.uid: l.parent for l in layers}

        def hidden(layer):
            parent, hops = layer.parent, 0
            while parent and hops < 64:
                if parent in closed:
                    return True
                parent, hops = parents.get(parent), hops + 1
            return False
        return [0 if hidden(l) else self.bitflag_filter_item for l in layers], []

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, index):
        row = layout.row(align=True)
        row.enabled = not in_frozen(item)   # (a frozen folder's layers are kept, not editable)
        depth = depth_of(item)
        if depth:
            row.separator(factor=2.0 * depth)
        folder = item.kind == 'FOLDER'
        if folder:
            row.prop(item, "expanded", text="", icon='TRIA_DOWN' if item.expanded else 'TRIA_RIGHT', emboss=False)
        row.prop(item, "visible", text="", icon='HIDE_OFF' if item.visible else 'HIDE_ON', emboss=False)
        row.label(text="", icon=KIND_ICONS[item.kind])
        row.prop(item, "name", text="", emboss=False)
        if item.mask_stack:
            row.label(text="", icon='MOD_MASK')
        sub = row.row(align=True)
        sub.scale_x = 0.9
        sub.prop(item, "blend", text="")
        row.prop(item, "opacity", text="", slider=True)
        if folder:
            op = row.operator("m3d.layer_unfreeze" if item.frozen else "m3d.layer_freeze", text="", icon='FREEZE',
                              depress=item.frozen)
            op.index = index
        else:
            row.label(text="".join(ch.label[0] for ch in CHANNELS if has_content(item, ch.id)))


class M3D_UL_mask_effects(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", icon='HIDE_OFF' if item.visible else 'HIDE_ON', emboss=False)
        row.label(text="", icon=MK.KIND_BY_ID[item.kind].icon)
        row.prop(item, "name", text="", emboss=False)
        if item.kind not in MK.FILTERS:   # A filter changes what is below it: only how much is left to say.
            sub = row.row(align=True)
            sub.scale_x = 0.9
            sub.prop(item, "blend", text="")
        row.prop(item, "opacity", text="", slider=True)


classes = (
    M3D_LayerChannel,
    MK.M3D_MaskEffect,
    M3D_Layer,
    M3D_OT_layer_add,
    M3D_OT_layer_folder_add,
    M3D_OT_layer_duplicate,
    M3D_OT_layer_remove,
    M3D_OT_layer_move,
    M3D_OT_layer_move_into,
    M3D_OT_layer_move_out,
    M3D_OT_layer_freeze,
    M3D_OT_layer_unfreeze,
    M3D_OT_layer_merge_folder,
    M3D_OT_layer_visible,
    M3D_OT_layer_mask_add,
    M3D_OT_layer_mask_remove,
    M3D_OT_layer_mask_invert,
    M3D_OT_layer_paint_mask,
    M3D_OT_mask_effect_add,
    M3D_OT_mask_effect_remove,
    M3D_OT_mask_effect_move,
    M3D_OT_mask_effect_duplicate,
    M3D_OT_mask_rebake,
    M3D_OT_layer_merge_down,
    M3D_OT_layer_flatten,
    M3D_OT_layer_convert,
    M3D_UL_layers,
    M3D_UL_mask_effects,
)


@bpy.app.handlers.persistent
def load_post(*_args):
    """Files from before mask stacks: upgrade their masks right away, so the Mask panel and the nodes agree."""
    for mat in bpy.data.materials:
        if mat.node_tree is not None and any(l.mask is not None for l in mat.m3d_layers):
            rebuild_all(mat)


_pending = [False]


def _follow_strokes():
    """Timer: bring the Blur caches up to date after something painted an image (a stroke ends with an image update)."""
    _pending[0] = False
    for mat in bpy.data.materials:
        if mat.node_tree is not None and any(e.kind == 'BLUR' for l in mat.m3d_layers for e in l.mask_stack):
            for layer in live_layers(mat):
                MK.refresh_blurs(layer)


@bpy.app.handlers.persistent
def depsgraph_post(_scene, depsgraph):
    if not _pending[0] and depsgraph.id_type_updated('IMAGE'):
        _pending[0] = True
        bpy.app.timers.register(_follow_strokes, first_interval=0.4)


MK._hook[0] = _changed


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    mat = bpy.types.Material
    mat.m3d_layers = CollectionProperty(type=M3D_Layer)
    mat.m3d_layer_index = IntProperty(name="Active Layer", default=0, min=0, update=_changed)
    mat.m3d_channel = EnumProperty(name="Channel", default='BASE_COLOR', items=CHANNEL_ITEMS, update=_changed,
                                   description="Channel the brush paints on the active layer")
    mat.m3d_show_mask = BoolProperty(name="Show Mask", default=False, update=_show_mask_changed,
                                     description="Show the active layer's mask in the 3D view instead of the material "
                                     "(white shows the layer, black hides it)")
    bpy.app.handlers.load_post.append(load_post)
    bpy.app.handlers.depsgraph_update_post.append(depsgraph_post)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(depsgraph_post)
    bpy.app.handlers.load_post.remove(load_post)
    del bpy.types.Material.m3d_show_mask, bpy.types.Material.m3d_channel, bpy.types.Material.m3d_layer_index
    del bpy.types.Material.m3d_layers
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
