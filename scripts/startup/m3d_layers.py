# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Paint layer stack of the Texture workspace (F4) for Maelstrom3D: the channels, the layer data, the node chains, the
paint target, Merge Down, Flatten and the flattening Export uses.

Blender has no paint layers, so the stack is data on the material (Material.m3d_layers, bottom to top) and a node
chain per channel that is rebuilt from it: Image Texture -> Mix (blend mode, factor = image alpha x opacity x mask) over
the layer below, the top of the chain feeding the Principled BSDF. The chains live in one frame per channel; only nodes
that carry the m3d_layer custom property are ever touched. The same blend math in numpy flattens a stack (Merge Down,
Flatten, Export). Painting needs no special support: the active layer's image for the active channel (or its mask) is
made the material's active paint slot.

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


def pixels_of(image, size):
    """The image's pixels as a (size, size, 4) array (resampled when it has another size)."""
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    w, h = image.size
    px = px.reshape(h, w, 4)
    if (w, h) != (size, size):
        px = px[np.ix_(np.arange(size) * h // size, np.arange(size) * w // size)]
    return px


def write_pixels(image, array):
    image.pixels.foreach_set(np.ascontiguousarray(array, np.float32).ravel())
    image.update()


def image_size(image):
    """(width, height) without loading a generated image that nothing has touched yet."""
    if image.source == 'GENERATED' and not image.has_data:
        return image.generated_width, image.generated_height
    return tuple(image.size)


def default_linear(ch):
    """What a channel is below its bottom layer (linear light): the starting color of a new image."""
    rgb = np.array(ch.color[:3], np.float32)
    return to_linear(rgb) if ch.srgb else rgb


# -----------------------------------------------------------------------------
# Data

_muted = [0]


@contextmanager
def muted():
    """Property updates do nothing inside (operators edit many properties, then rebuild once)."""
    _muted[0] += 1
    try:
        yield
    finally:
        _muted[0] -= 1


def _changed(self, context):
    """Property update: the node chains and the paint target follow the layer data."""
    if not _muted[0] and isinstance(self.id_data, bpy.types.Material):
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


class M3D_Layer(PropertyGroup):
    """One layer of a material's stack."""
    name: StringProperty(name="Name", default="Layer", update=_changed)
    uid: StringProperty(description="Names the layer's nodes")
    kind: EnumProperty(name="Type", default='PAINT', items=(
        ('PAINT', "Paint Layer", "Pixels you paint, one image per channel"),
        ('FILL', "Fill Layer", "A value or color over the whole mesh (use a mask to limit it)")))
    visible: BoolProperty(name="Visible", default=True, update=_changed)
    use_alpha: BoolProperty(name="Image Alpha", default=True, update=_changed,
                            description="The image's transparency shows the layers below (off for the Base layer made from "
                            "existing paint slots, where alpha was never used)")
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_changed)
    blend: EnumProperty(name="Blend", default='MIX', items=[(k, label, "") for k, label in BLENDS], update=_changed,
                        description="How the layer combines with the layers below (the Normal channel always mixes)")
    channels: CollectionProperty(type=M3D_LayerChannel)
    mask: PointerProperty(type=bpy.types.Image, update=_changed)
    mask_invert: BoolProperty(name="Invert Mask", default=False, update=_changed)
    paint_mask: BoolProperty(name="Paint Mask", default=False, update=_changed,
                             description="Brush strokes go to the layer's mask instead of its channel")


def entry_of(layer, ch_id):
    return layer.channels[CHANNEL_INDEX[ch_id]]


def active_layer(mat):
    i = mat.m3d_layer_index
    return mat.m3d_layers[i] if 0 <= i < len(mat.m3d_layers) else None


def has_content(layer, ch_id):
    """Does the layer change this channel: a fill value, or a painted image."""
    e = entry_of(layer, ch_id)
    return e.use and (layer.kind == 'FILL' or e.image is not None)


def content_channels(mat):
    return [ch.id for ch in CHANNELS if any(has_content(l, ch.id) for l in mat.m3d_layers)]


def fill_rgba(layer, ch_id):
    """The fill color of a layer's channel (linear light, as the Mix node takes it)."""
    e = entry_of(layer, ch_id)
    if ch_id == 'NORMAL':
        return (0.5, 0.5, 1.0, 1.0)   # Flat: a fill layer resets the normals (use a mask to limit it).
    if ch_id in SCALARS:
        return (e.value, e.value, e.value, 1.0)
    return tuple(e.color)


def layer_images(layer):
    return [e.image for e in layer.channels if e.image] + ([layer.mask] if layer.mask else [])


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
            if layer.mask == image or any(e.image == image for e in layer.channels):
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


def signature(layers, ch_id):
    """What decides the chain's nodes and links; anything else (opacity, blend, fill, names) is only a value."""
    return repr([(l.uid, l.kind, entry_of(l, ch_id).image.name if l.kind == 'PAINT' else "",
                  l.mask.name if l.mask else "", l.mask_invert, l.use_alpha) for l in layers])


def set_values(nt, layer, ch_id):
    """Opacity, visibility, blend mode, fill value and names of a layer's nodes (no node or link changes)."""
    opv = nt.nodes.get(part(ch_id, layer.uid, "opv"))
    mix = nt.nodes.get(part(ch_id, layer.uid, "mix"))
    if opv is None or mix is None:
        return
    want = layer.opacity if layer.visible else 0.0
    if abs(opv.inputs[1].default_value - want) > 1e-6:
        opv.inputs[1].default_value = want
    blend = 'MIX' if ch_id == 'NORMAL' else layer.blend
    if mix.blend_type != blend:
        mix.blend_type = blend
    if layer.kind == 'FILL':
        color = fill_rgba(layer, ch_id)
        if any(abs(a - b) > 1e-6 for a, b in zip(mix.inputs[7].default_value, color)):
            mix.inputs[7].default_value = color
    for key in ("mix", "tex"):
        node = nt.nodes.get(part(ch_id, layer.uid, key))
        if node is not None and node.label != layer.name:
            node.label = layer.name


def build_channel(mat, ch, layers, sig):
    """The frame with one chain for `ch`: Image Texture (or fill) -> Mix per layer, bottom to top, into the shader."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    nodes, links = nt.nodes, nt.links
    y = bsdf.location.y - 700 - CHANNEL_INDEX[ch.id] * 900
    x_top = bsdf.location.x - 800
    frame = nodes.new("NodeFrame")
    frame.name, frame.label = "%s.%s" % (TAG, ch.id), ch.label + " Layers"
    frame[TAG], frame["m3d_sig"] = ch.id, sig

    def new(idname, name, x, y_):
        node = nodes.new(idname)
        node.name = name
        node[TAG] = ch.id
        node.parent = frame
        node.location = (x, y_)
        restore_settings(node)
        return node

    below = None
    for i, layer in enumerate(layers):
        x, uid = x_top - (len(layers) - 1 - i) * 1000, layer.uid
        opv = new("ShaderNodeMath", part(ch.id, uid, "opv"), x + 300, y - 80)   # image alpha x opacity (0 when hidden)
        opv.operation = 'MULTIPLY'
        mix = new("ShaderNodeMix", part(ch.id, uid, "mix"), x + 750, y)
        mix.data_type, mix.clamp_result = 'RGBA', True
        if layer.kind == 'PAINT':
            tex = new("ShaderNodeTexImage", part(ch.id, uid, "tex"), x, y)
            tex.image = entry_of(layer, ch.id).image
            if layer.use_alpha:
                links.new(tex.outputs["Alpha"], opv.inputs[0])
            else:
                opv.inputs[0].default_value = 1.0
            links.new(tex.outputs["Color"], mix.inputs[7])
        else:
            opv.inputs[0].default_value = 1.0
        factor = opv.outputs[0]
        if layer.mask:
            tex = new("ShaderNodeTexImage", part(ch.id, uid, "mask"), x, y - 330)
            tex.image = layer.mask
            value = tex.outputs["Color"]
            if layer.mask_invert:
                inv = new("ShaderNodeMath", part(ch.id, uid, "maskinv"), x + 300, y - 330)
                inv.operation = 'SUBTRACT'
                inv.inputs[0].default_value = 1.0
                links.new(value, inv.inputs[1])
                value = inv.outputs[0]
            mul = new("ShaderNodeMath", part(ch.id, uid, "maskmul"), x + 500, y - 200)
            mul.operation = 'MULTIPLY'
            links.new(factor, mul.inputs[0])
            links.new(value, mul.inputs[1])
            factor = mul.outputs[0]
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
    layers = [l for l in mat.m3d_layers if has_content(l, ch_id)]
    sig = signature(layers, ch_id)
    frame = nt.nodes.get("%s.%s" % (TAG, ch_id))
    if frame is not None and layers and frame.get("m3d_sig") == sig:
        for layer in layers:
            set_values(nt, layer, ch_id)
        return False
    ours = [n for n in nt.nodes if n.get(TAG) == ch_id]
    for node in ours:
        if node.type in _PROPS:
            _carry[node.name] = settings_of(node)
        nt.nodes.remove(node)
    if layers:
        build_channel(mat, CHANNEL_BY_ID[ch_id], layers, sig)
    if ch_id in {'NORMAL', 'HEIGHT'}:
        link_normal(mat)
    return bool(ours or layers)


def rebuild_all(mat):
    changed = [rebuild(mat, ch.id) for ch in CHANNELS]
    _carry.clear()
    if not mat.m3d_layers:
        remove_scratch(mat)
    if any(changed):
        refresh_slots(mat)
    return any(changed)


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
    """The image strokes should go to: the active layer's mask when Paint Mask is on (always for a fill layer), else
    its image for the active channel (made here when `create`). None for a fill layer without a mask, or a channel the
    layer does not have."""
    index = mat.m3d_layer_index
    layer = active_layer(mat)
    if layer is None:
        return None
    if layer.mask and (layer.paint_mask or layer.kind == 'FILL'):
        return layer.mask
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
    rebuild_all(mat)
    ob = getattr(context, "object", None)
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
        if layer.kind == 'FILL' and not layer.mask:
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
    """(linear rgb, coverage) of a layer's channel: the image alpha x opacity x mask (0 when hidden) is the coverage."""
    e = entry_of(layer, ch.id)
    if layer.kind == 'FILL':
        rgb = np.broadcast_to(np.array(fill_rgba(layer, ch.id)[:3], np.float32), (size, size, 3))
        alpha = np.ones((size, size), np.float32)
    else:
        px = pixels_of(e.image, size)
        rgb, alpha = px[..., :3], px[..., 3] if layer.use_alpha else np.ones((size, size), np.float32)
        if ch.srgb:
            rgb = to_linear(rgb)
    alpha = alpha * np.float32(layer.opacity if layer.visible else 0.0)
    if layer.mask:
        mask = pixels_of(layer.mask, size)[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        alpha = alpha * np.clip(1.0 - mask if layer.mask_invert else mask, 0.0, 1.0)
    return rgb, alpha


def composite(mat, ch_id, size):
    """The channel's visible stack over the channel's starting value, in linear light: (size, size, 3)."""
    ch = CHANNEL_BY_ID[ch_id]
    rgb = np.broadcast_to(default_linear(ch), (size, size, 3)).astype(np.float32)
    alpha = np.ones((size, size), np.float32)
    for layer in mat.m3d_layers:
        if has_content(layer, ch_id):
            lrgb, la = layer_planes(layer, ch, size)
            rgb, alpha = over(rgb, alpha, lrgb, la, 'MIX' if ch_id == 'NORMAL' else layer.blend)
    return rgb


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
        rgb = np.repeat((rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None], 3, axis=-1)
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
        layer.name = name or unique_name(mat, "Paint Layer" if kind == 'PAINT' else "Fill Layer")
        layer.kind = kind
        for ch in CHANNELS:
            e = layer.channels.add()
            e.channel = ch.id
            e.use = kind == 'PAINT' or ch.id == 'BASE_COLOR'
            e.color = (*default_linear(ch), 1.0)
            e.value = ch.color[0]
    return layer


def insert_above(mat, layer_count_before):
    """Move the layer just added to the end up to sit above the active layer; returns its index."""
    layers = mat.m3d_layers
    target = min(mat.m3d_layer_index + 1, layer_count_before) if layer_count_before else 0
    layers.move(len(layers) - 1, target)
    return target


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


def delete_layer(mat, index):
    """Remove a layer and its nodes; its images go too unless something else uses them."""
    images = layer_images(mat.m3d_layers[index])
    with muted():
        mat.m3d_layers.remove(index)
        mat.m3d_layer_index = max(0, min(mat.m3d_layer_index, len(mat.m3d_layers) - 1))
    rebuild_all(mat)
    release(images)


def duplicate_layer(mat, index):
    """Copy a layer (with copies of its images) just above it. Returns the new index."""
    count = len(mat.m3d_layers)
    new = add_layer(mat, mat.m3d_layers[index].kind)   # Adding can move the collection: look the source up again.
    src = mat.m3d_layers[index]
    with muted():
        new.name = unique_name(mat, src.name + " Copy")
        new.visible, new.opacity, new.blend, new.mask_invert = src.visible, src.opacity, src.blend, src.mask_invert
        new.use_alpha = src.use_alpha
        for ch in CHANNELS:
            a, b = entry_of(src, ch.id), entry_of(new, ch.id)
            b.use, b.color, b.value = a.use, a.color, a.value
            if a.image is not None:
                b.image = copy_image(a.image, image_name(mat, new, ch.label))
        if src.mask:
            new.mask = copy_image(src.mask, image_name(mat, new, "Mask"))
    mat.m3d_layers.move(count, index + 1)
    return index + 1


def merge_down(mat, index, default_size):
    """Flatten layer `index` into the one below it. Per channel the two are composited (the upper layer's blend mode
    over the lower layer) into the lower layer's image; its opacity and mask are baked into the pixels. Exact when the
    lower layer is opaque or the upper one uses Mix; the merged layer keeps the lower layer's blend mode."""
    layers = mat.m3d_layers
    top, low = layers[index], layers[index - 1]
    if top.visible:
        chans = [ch for ch in CHANNELS if has_content(top, ch.id) or has_content(low, ch.id)]
        sizes = [max(image_size(e.image)) for l in (top, low) for e in l.channels if e.image]
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
            old_mask = low.mask
            low.mask, low.mask_invert, low.paint_mask = None, False, False
    else:
        old_mask = None
    images = layer_images(top) + ([old_mask] if old_mask else [])
    with muted():
        layers.remove(index)
        mat.m3d_layer_index = index - 1
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
    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material) is not None


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
        before = len(mat.m3d_layers)
        add_layer(mat, self.kind)
        with muted():
            mat.m3d_layer_index = insert_above(mat, before)
        return _done(context, mat)


class M3D_OT_layer_duplicate(_ActiveLayerOp, Operator):
    """Duplicate the active layer (its images are copied)"""
    bl_idname = "m3d.layer_duplicate"
    bl_label = "Duplicate Layer"

    def execute(self, context):
        mat = self.material(context)
        index = duplicate_layer(mat, mat.m3d_layer_index)
        with muted():
            mat.m3d_layer_index = index
        return _done(context, mat)


class M3D_OT_layer_remove(_ActiveLayerOp, Operator):
    """Delete the active layer and its images (images used elsewhere stay)"""
    bl_idname = "m3d.layer_remove"
    bl_label = "Delete Layer"

    def execute(self, context):
        mat = self.material(context)
        delete_layer(mat, mat.m3d_layer_index)
        return _done(context, mat)


class M3D_OT_layer_move(_ActiveLayerOp, Operator):
    """Move the active layer up (above its neighbour) or down in the stack"""
    bl_idname = "m3d.layer_move"
    bl_label = "Move Layer"

    delta: IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Move the active layer %s" % ("up" if props.delta > 0 else "down")

    def execute(self, context):
        mat = self.material(context)
        i, j = mat.m3d_layer_index, mat.m3d_layer_index + self.delta
        if not 0 <= j < len(mat.m3d_layers):
            return {'CANCELLED'}
        mat.m3d_layers.move(i, j)
        with muted():
            mat.m3d_layer_index = j
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
    """Add a mask to the active layer: white shows the layer, black hides it. Paint the mask like any channel"""
    bl_idname = "m3d.layer_mask_add"
    bl_label = "Add Mask"

    fill: EnumProperty(name="Start", default='WHITE', items=(
        ('WHITE', "White (Show All)", "The layer shows everywhere; paint black to hide it"),
        ('BLACK', "Black (Hide All)", "The layer is hidden; paint white to show it")))

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).mask is None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        with muted():
            layer.mask = make_mask_image(mat, layer, new_size(context), self.fill == 'WHITE')
            layer.paint_mask = True
        return _done(context, mat)


class M3D_OT_layer_mask_remove(_ActiveLayerOp, Operator):
    """Remove the active layer's mask (the image is deleted unless something else uses it)"""
    bl_idname = "m3d.layer_mask_remove"
    bl_label = "Remove Mask"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).mask is not None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        image = layer.mask
        with muted():
            layer.mask, layer.mask_invert, layer.paint_mask = None, False, False
        rebuild_all(mat)
        release([image])
        return _done(context, mat)


class M3D_OT_layer_mask_invert(_ActiveLayerOp, Operator):
    """Invert the active layer's mask (the layer shows where it was hidden); the mask image is not changed"""
    bl_idname = "m3d.layer_mask_invert"
    bl_label = "Invert Mask"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).mask is not None

    def execute(self, context):
        layer = active_layer(self.material(context))
        layer.mask_invert = not layer.mask_invert
        return {'FINISHED'}


class M3D_OT_layer_paint_mask(_ActiveLayerOp, Operator):
    """Switch between painting the active layer's mask and its channel"""
    bl_idname = "m3d.layer_paint_mask"
    bl_label = "Paint Mask"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).mask is not None

    def execute(self, context):
        layer = active_layer(self.material(context))
        layer.paint_mask = not layer.paint_mask
        return {'FINISHED'}


class M3D_OT_layer_merge_down(_ActiveLayerOp, Operator):
    """Merge the active layer into the one below it (the pixels are combined with the layer's blend mode, opacity and
    mask; the result keeps the lower layer's blend mode)"""
    bl_idname = "m3d.layer_merge_down"
    bl_label = "Merge Down"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and mesh_of(context).active_material.m3d_layer_index > 0

    def execute(self, context):
        mat = self.material(context)
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

class M3D_UL_layers(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", icon='HIDE_OFF' if item.visible else 'HIDE_ON', emboss=False)
        row.label(text="", icon='IMAGE_DATA' if item.kind == 'PAINT' else 'COLOR')
        row.prop(item, "name", text="", emboss=False)
        if item.mask:
            row.label(text="", icon='MOD_MASK')
        sub = row.row(align=True)
        sub.scale_x = 0.9
        sub.prop(item, "blend", text="")
        row.prop(item, "opacity", text="", slider=True)
        row.label(text="".join(ch.label[0] for ch in CHANNELS if has_content(item, ch.id)))


classes = (
    M3D_LayerChannel,
    M3D_Layer,
    M3D_OT_layer_add,
    M3D_OT_layer_duplicate,
    M3D_OT_layer_remove,
    M3D_OT_layer_move,
    M3D_OT_layer_visible,
    M3D_OT_layer_mask_add,
    M3D_OT_layer_mask_remove,
    M3D_OT_layer_mask_invert,
    M3D_OT_layer_paint_mask,
    M3D_OT_layer_merge_down,
    M3D_OT_layer_flatten,
    M3D_OT_layer_convert,
    M3D_UL_layers,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    mat = bpy.types.Material
    mat.m3d_layers = CollectionProperty(type=M3D_Layer)
    mat.m3d_layer_index = IntProperty(name="Active Layer", default=0, min=0, update=_changed)
    mat.m3d_channel = EnumProperty(name="Channel", default='BASE_COLOR', items=CHANNEL_ITEMS, update=_changed,
                                   description="Channel the brush paints on the active layer")


def unregister():
    del bpy.types.Material.m3d_channel, bpy.types.Material.m3d_layer_index, bpy.types.Material.m3d_layers
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
