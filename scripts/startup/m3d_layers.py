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
The same blend math in numpy flattens a stack (Merge Down, Flatten, Export). Painting needs little support: the first
channel image of the brush material (or the active layer's mask's Paint effect) is made the material's active paint slot,
and the paint code is told, through a window manager property, which other channel images the stroke paints along with
it (target_set, TARGETS).

Folders: a layer of kind FOLDER holds the layers whose `parent` is its uid (folders nest). The stack stays one list,
bottom to top, with each folder right after the layers inside it, so the list read backwards is what the UI shows. A
folder's layers are composited together over transparent first (color and coverage, `over` in numpy; in the nodes a
sub-chain that carries a coverage socket next to the color), then the result is blended onto the stack below with the
folder's blend, opacity and mask like a layer's own image. Freezing bakes that result into one image per channel (the
alpha is the coverage), after which the folder is a leaf of the chains: one Image Texture and one Mix per channel.

Blend mode and opacity are per channel: every layer has an entry for each channel (M3D_LayerChannel) with its own blend
mode and opacity, so a layer can add to Height and multiply Roughness at different strengths. Passthrough leaves a channel
out of the layer (no nodes, no pixels), Replace ignores the image's own transparency; Color Burn and Color Dodge are a
blend Mix node followed by a plain Mix (their node formulas are not linear in the factor, the numpy math is). Layers saved
before that have one blend and one opacity for all channels: `upgrade` copies them into every channel.

The list rows draw a content thumbnail (the image of the channel the panel's dropdown picks, a swatch for a fill) and a mask
thumbnail as preview icons made on a timer from a small numpy downscale: drawing only asks for them, and the depsgraph hook
below makes the ones whose image was painted again (see "Thumbnails"). The right-click menu of the list is an item of
UI_MT_button_context_menu; its commands run through m3d.layer_do, which selects the layer under the pointer first. A UI list has
no drag and drop, so the arrows (m3d.layer_move) order the layers.

The Layers page (panels) is in m3d_texture.py.
"""

import math
import re
import time
import uuid
from collections import namedtuple
from contextlib import contextmanager

import bpy
import bpy.utils.previews
import numpy as np
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

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

BLENDS = (   # (id, label): the Mix node's blend types, Replace and Passthrough. All but those two are exact in numpy (BLEND_FUNCTIONS).
    ('MIX', "Normal"), ('PASSTHROUGH', "Passthrough"), ('REPLACE', "Replace"), ('MULTIPLY', "Multiply"), ('DIVIDE', "Divide"),
    ('DARKEN', "Darken"), ('LIGHTEN', "Lighten"), ('ADD', "Add (Linear Dodge)"), ('SUBTRACT', "Subtract"),
    ('DIFFERENCE', "Difference"), ('OVERLAY', "Overlay"), ('SCREEN', "Screen"), ('BURN', "Color Burn"), ('DODGE', "Color Dodge"),
    ('SOFT_LIGHT', "Soft Light"), ('LINEAR_LIGHT', "Linear Light"), ('HUE', "Hue"), ('SATURATION', "Saturation"),
    ('COLOR', "Color"), ('VALUE', "Value"),
)
BLEND_SHORT = {'MIX': "Norm", 'PASSTHROUGH': "Pthr", 'REPLACE': "Repl", 'MULTIPLY': "Mult", 'DIVIDE': "Div", 'DARKEN': "Dark",
               'LIGHTEN': "Light", 'ADD': "Add", 'SUBTRACT': "Sub", 'DIFFERENCE': "Diff", 'OVERLAY': "Ovrl", 'SCREEN': "Scrn",
               'BURN': "Burn", 'DODGE': "Dodge", 'SOFT_LIGHT': "Soft", 'LINEAR_LIGHT': "LLgt", 'HUE': "Hue", 'SATURATION': "Sat",
               'COLOR': "Col", 'VALUE': "Val"}
BLEND_TEXT = {
    'MIX': "The layer covers what is below, as much as its opacity, image transparency and mask say",
    'PASSTHROUGH': "The layer does not touch this channel (no nodes, no pixels, whatever the channel holds)",
    'REPLACE': "The layer's pixels replace what is below, also where the image is transparent (opacity and mask still fade it)",
    'ADD': "Adds the layer to what is below (Linear Dodge). With a Height image that is 0.5 flat, Linear Light is the "
           "mode that leaves 0.5 alone",
    'LINEAR_LIGHT': "Adds twice the layer minus one: 0.5 changes nothing, white raises, black lowers",
}
# (the saved value of an enum is its number: a new mode goes last, with the next number)
BLEND_ITEMS = [(k, label, BLEND_TEXT.get(k, ""), 'NONE', i) for i, (k, label) in enumerate(BLENDS)]
LEGACY_BLENDS = ('MIX', 'MULTIPLY', 'ADD', 'OVERLAY', 'SCREEN', 'SOFT_LIGHT', 'SUBTRACT', 'DIFFERENCE', 'COLOR', 'DARKEN',
                 'LIGHTEN')   # the modes of the one blend a layer had before every channel had its own, in their saved order
TWO_STEP = {'BURN', 'DODGE'}   # modes whose node formula is not linear in the factor: a Mix node at full strength, then a plain Mix
TAG = "m3d_layer"   # Custom property (value: channel id) and name prefix of every node the stack creates.
# The baked mesh maps the shader of a texture set uses, in the viewport only (Export, Merge Down and Flatten read the layers' pixels):
# the Normal map is the base of the Normal channel (the layers' normal goes on top of it as detail), the AO map darkens the Base
# Color. Material.<property> holds each map; link_maps sets them.
BAKED_PROPS = {"Normal": "m3d_baked_normal", "AO": "m3d_baked_ao", "Position": "m3d_baked_position",
               "WorldNormal": "m3d_baked_worldnormal"}   # (the last two: what tri-planar fills project with)
AO_MUL, AO_TEX = "%s.view.ao" % TAG, "%s.view.aotex" % TAG   # the nodes of the AO multiply (tagged "VIEW")
FILL_TEXTURE = "m3d_fill_texture"   # Custom property of an image file picked as a fill's texture (value: the channel it was first picked for).
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


def blend_hue(back, src):
    """Hue of `src` on the saturation and value of `back` (nothing happens where `src` is grey)."""
    h, s, _ = rgb_to_hsv(src)
    _, sb, vb = rgb_to_hsv(back)
    return np.where((s != 0)[..., None], hsv_to_rgb(h, sb, vb), back)


def blend_saturation(back, src):
    hb, sb, vb = rgb_to_hsv(back)
    return np.where((sb != 0)[..., None], hsv_to_rgb(hb, rgb_to_hsv(src)[1], vb), back)


def blend_value(back, src):
    hb, sb, _ = rgb_to_hsv(back)
    return hsv_to_rgb(hb, sb, rgb_to_hsv(src)[2])


def blend_divide(back, src):
    """back / src; where src is 0 the Mix node leaves back as it is."""
    return np.where(src != 0, back / np.where(src != 0, src, 1.0), back)


def blend_burn(back, src):
    return np.where(src > 0, np.clip(1.0 - (1.0 - back) / np.where(src > 0, src, 1.0), 0.0, 1.0), 0.0)


def blend_dodge(back, src):
    return np.where(back != 0, np.where(src >= 1, 1.0, np.minimum(back / np.where(src < 1, 1.0 - src, 1.0), 1.0)), 0.0)


# What the Mix node's blend types compute at full strength: result = back + factor * (blend - back) (Color Burn and Dodge
# are the two that are not linear in the factor: the chain makes them a Mix node at factor 1, then a plain Mix by the factor).
# Replace is Normal with the layer's own transparency ignored (see node_mode), Passthrough is no layer at all.
BLEND_FUNCTIONS = {
    'MIX': lambda b, s: s,
    'MULTIPLY': lambda b, s: b * s,
    'DIVIDE': blend_divide,
    'DARKEN': np.minimum,
    'LIGHTEN': np.maximum,
    'ADD': lambda b, s: b + s,
    'SUBTRACT': lambda b, s: b - s,
    'DIFFERENCE': lambda b, s: np.abs(b - s),
    'OVERLAY': lambda b, s: np.where(b < 0.5, 2 * b * s, 1 - 2 * (1 - b) * (1 - s)),
    'SCREEN': lambda b, s: 1 - (1 - b) * (1 - s),
    'BURN': blend_burn,
    'DODGE': blend_dodge,
    'SOFT_LIGHT': lambda b, s: (1 - b) * s * b + b * (1 - (1 - s) * (1 - b)),
    'LINEAR_LIGHT': lambda b, s: b + 2 * s - 1,
    'HUE': blend_hue,
    'SATURATION': blend_saturation,
    'COLOR': blend_color,
    'VALUE': blend_value,
}


def node_mode(blend):
    """The blend type of the Mix node a mode uses (Replace mixes; Passthrough has no node)."""
    return 'MIX' if blend == 'REPLACE' else blend


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


def _index_changed(self, context):
    """Material.m3d_layer_index set by a click in the list (on a row, its name): the layer is picked with its content, like a
    click on its content thumbnail (strokes paint it, Properties shows its settings). Code that keeps the part sets it muted."""
    layer = active_layer(self) if not MK._muted[0] else None
    if layer is not None and layer.paint_mask:
        with muted():
            layer.paint_mask = False
    _changed(self, context)


def _texture_changed(self, context):
    """A fill's texture was picked: a file the stack has not seen takes the color space of the channel (the first channel an
    image is used for decides it; a generated image keeps its own: choosing the color space again blanks it)."""
    image, ch = self.texture, CHANNEL_BY_ID.get(self.channel)
    if image is not None and ch is not None and image.source == 'FILE' and FILL_TEXTURE not in image.keys():
        image.colorspace_settings.name = 'sRGB' if ch.srgb else 'Non-Color'
        image[FILL_TEXTURE] = ch.id
    _changed(self, context)


class M3D_LayerChannel(PropertyGroup):
    """What a layer holds for one channel: an image (paint layers, made when it is first painted), a fill value, or (fill
    layers) a texture that is the fill instead of the value."""
    channel: StringProperty()
    use: BoolProperty(name="Enabled", default=False, update=_changed,
                      description="The layer has this channel (paint layers make the image when it is first painted)")
    image: PointerProperty(type=bpy.types.Image, update=_changed)
    texture: PointerProperty(type=bpy.types.Image, name="Texture", update=_texture_changed,
                             description="Fill the channel with this image instead of the value: it follows the UV map, "
                             "moved by the layer's Tiling, Rotation and Offset")
    color: FloatVectorProperty(name="Color", size=4, subtype='COLOR', min=0.0, max=1.0, default=(0.8, 0.8, 0.8, 1.0),
                               update=_changed)
    value: FloatProperty(name="Value", min=0.0, max=1.0, default=0.5, update=_changed)
    blend: EnumProperty(name="Blend", default='MIX', items=BLEND_ITEMS, update=_changed,
                        description="How the layer combines with the layers below in this channel")
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_changed,
                           description="How strongly the layer applies in this channel")
    opacity_pct: MK.percent_of("opacity", "How strongly the layer applies in this channel")   # (the list rows: "50%")


def _projection_changed(self, context):
    """Tri-planar picked: the texture set takes the baked Position and World Normal maps of the mesh, if it has them (link_maps)."""
    mat = self.id_data
    ob = mesh_of(context) if context is not None else None
    if self.projection == 'TRIPLANAR' and ob is not None and any(s.material == mat for s in ob.material_slots):
        link_maps(mat, ob)
    _changed(self, context)


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
    visible: BoolProperty(name="Visible", default=True, update=_changed,
                          description="Show or hide the layer (a hidden layer adds nothing to the material)")
    use_alpha: BoolProperty(name="Image Alpha", default=True, update=_changed,
                            description="The image's transparency shows the layers below (off for the Base layer made from "
                            "existing paint slots, where alpha was never used)")
    per_channel: BoolProperty(description="The blend mode and opacity are the channels' own. Off: a layer saved before that, "
                              "whose one blend and opacity (raw properties 'blend' and 'opacity') `upgrade` copies into every channel")
    use_mask: BoolProperty(name="Use Mask", default=True, update=_changed,
                           description="The layer's mask applies (off: the layer shows as if it had none; the mask is kept)")
    channels: CollectionProperty(type=M3D_LayerChannel)
    mask_stack: CollectionProperty(type=MK.M3D_MaskEffect)   # The mask: effects combined from the bottom up.
    mask_index: IntProperty(name="Active Effect", default=0, min=0, update=_changed)
    # Which thumbnail of the layer is selected (see mask_active): the mask (strokes paint its Paint effect, Properties shows it)
    # or the content (strokes paint the channels, Properties shows the layer). The name is from when it was a Paint Mask switch.
    paint_mask: BoolProperty(name="Mask Selected", default=False, update=_changed,
                             description="The mask thumbnail is selected: strokes paint the mask's Paint effect and Properties "
                             "shows the mask (off: the layer's content)")
    # The UV transform of a fill layer's textures (the Mapping node in front of them): see fill_mapping.
    uv_tiling: FloatVectorProperty(name="Tiling", size=2, default=(1.0, 1.0), min=0.01, soft_max=32.0, update=_changed,
                                   description="How many times the texture repeats over the UV map, across and up")
    uv_rotation: FloatProperty(name="Rotation", subtype='ANGLE', default=0.0, update=_changed,
                               description="Turn the texture around the middle of the UV map")
    uv_offset: FloatVectorProperty(name="Offset", size=2, default=(0.0, 0.0), soft_min=-1.0, soft_max=1.0, update=_changed,
                                   description="Slide the texture across the UV map (1 is the width of the UV map)")
    # How a fill layer's textures meet the mesh: the UV map, or tri-planar (see triplanar).
    projection: EnumProperty(name="Projection", default='UV', update=_projection_changed, items=(
        ('UV', "UV", "The textures follow the UV map (they break where UV shells meet)"),
        ('TRIPLANAR', "Tri-planar", "The textures are projected from the three axes and blended where the surface turns: no seams, "
                                    "no stretching. Needs the baked Position and World Normal maps")))
    tri_scale: FloatProperty(name="Scale", default=1.0, min=0.001, soft_max=100.0, update=_changed,
                             description="How many times the texture repeats per unit (meter) of the mesh")
    tri_sharpness: FloatProperty(name="Blend Sharpness", default=4.0, min=1.0, soft_max=32.0, update=_changed,
                                 description="How quickly the projections hand over where the surface turns: higher is a narrower blend")
    # Before mask stacks a layer had one mask image (and Invert Mask): upgrade() turns them into effects.
    mask: PointerProperty(type=bpy.types.Image, update=_changed)
    mask_invert: BoolProperty(name="Invert Mask", default=False, update=_changed)


def entry_of(layer, ch_id):
    return layer.channels[CHANNEL_INDEX[ch_id]]


def blend_of(layer, ch_id):
    return entry_of(layer, ch_id).blend


def opacity_of(layer, ch_id):
    return entry_of(layer, ch_id).opacity


def passes(layer, ch_id):
    """Does the layer leave this channel alone (Passthrough)?"""
    return entry_of(layer, ch_id).blend == 'PASSTHROUGH'


def replaces(layer, ch_id):
    """Does the layer ignore its image's own transparency in this channel (Replace)? A folder always counts what its
    layers cover, so for a folder Replace is Normal."""
    return entry_of(layer, ch_id).blend == 'REPLACE' and (layer.kind != 'FOLDER' or layer.frozen)


def two_step(layer, ch_id):
    """Color Burn and Color Dodge: a Mix node at full strength, then a plain Mix by the factor."""
    return entry_of(layer, ch_id).blend in TWO_STEP


def mode_of(layer, ch_id):
    """The blend function (BLEND_FUNCTIONS) the layer's channel uses."""
    return node_mode(entry_of(layer, ch_id).blend)


def set_look(layer, blend=None, opacity=None, channel=None):
    """Set the blend mode and / or the opacity of a layer's channel `channel`, or of every channel (Normal keeps its blend
    mode then: it is a direction, not a value: name it to change it). The chains are rebuilt once."""
    with muted():
        for ch in CHANNELS:
            if channel not in {None, ch.id}:
                continue
            e = entry_of(layer, ch.id)
            if blend is not None and (channel is not None or ch.id != 'NORMAL'):
                e.blend = blend
            if opacity is not None:
                e.opacity = opacity
    if not MK._muted[0] and isinstance(layer.id_data, bpy.types.Material):
        refresh(bpy.context, layer.id_data)


def legacy_look(layer):
    """(blend, opacity) a layer saved before every channel had its own: the single values it stored (the properties are gone,
    the numbers are still in the layer's raw data)."""
    index, opacity = layer.get("blend", 0), layer.get("opacity", 1.0)
    return (LEGACY_BLENDS[index] if isinstance(index, int) and 0 <= index < len(LEGACY_BLENDS) else 'MIX',
            float(opacity) if isinstance(opacity, (int, float)) else 1.0)


def active_layer(mat):
    i = mat.m3d_layer_index
    return mat.m3d_layers[i] if 0 <= i < len(mat.m3d_layers) else None


def active_effect(layer):
    stack = layer.mask_stack
    return stack[layer.mask_index] if 0 <= layer.mask_index < len(stack) else None


def mask_active(layer):
    """Is the layer's mask selected (its thumbnail) rather than its content? Then strokes paint the mask and Properties shows it."""
    return layer.paint_mask and bool(layer.mask_stack)


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


def channel_off(mat, ch_id):
    """Is the channel removed from the material's texture set? Its layer images are kept, but the stack builds, paints and
    exports nothing for it until it is added again."""
    return ch_id in mat.m3d_off.split("|")


def set_channels(mat):
    """The channels of the material's texture set, in the order of CHANNELS."""
    off = mat.m3d_off.split("|")
    return [ch for ch in CHANNELS if ch.id not in off]


def channel_depth(mat, ch_id):
    """Bits of the images the stack makes for a channel: 16 (half float) or 8."""
    return 16 if ch_id in mat.m3d_depth.split("|") else 8


def has_content(layer, ch_id):
    """Does the layer change this channel: a fill value, a painted (or frozen) image, or (a folder that is not frozen)
    anything inside it. Not when its blend mode is Passthrough, or the channel is removed from the texture set."""
    if passes(layer, ch_id) or channel_off(layer.id_data, ch_id):
        return False
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


def has_texture(layer, ch_id):
    """Is the channel of a fill layer filled with a texture (instead of its value)?"""
    return layer.kind == 'FILL' and entry_of(layer, ch_id).texture is not None


def fill_matrix(layer):
    """(2 x 2 matrix, offset) of a fill layer's UV transform: the texture is read at m @ uv + offset for the point uv of the UV
    map. Tiling scales and Rotation turns around the middle of the UV map; Offset slides on top of that. The Mapping node of
    the chain computes the same (Point: location + rotation x (scale x vector))."""
    tx, ty = layer.uv_tiling
    c, s = math.cos(layer.uv_rotation), math.sin(layer.uv_rotation)
    m = np.array([[c * tx, -s * ty], [s * tx, c * ty]])
    middle = np.array([0.5, 0.5])
    return m, middle - m @ middle + np.array(layer.uv_offset)


def fill_mapping(layer):
    """(location, rotation, scale) of the Mapping node in front of a fill layer's textures (see fill_matrix)."""
    _m, loc = fill_matrix(layer)
    return (float(loc[0]), float(loc[1]), 0.0), (0.0, 0.0, layer.uv_rotation), (layer.uv_tiling[0], layer.uv_tiling[1], 1.0)


TRI_AXES = ((1, 2), (0, 2), (0, 1))   # the texture's plane seen along x (y, z), along y (x, z) and along z (x, y)


def triplanar(layer):
    """(Position map, World Normal map) a fill layer projects its textures with: set to Tri-planar and the texture set has both baked
    maps (link_maps). None: by the UV map (a Tri-planar fill without the maps shows as UV until they are baked). The shader and numpy
    read the same two images, so what the 3D view shows is what Export writes."""
    if layer.kind != 'FILL' or layer.projection != 'TRIPLANAR':
        return None
    mat = layer.id_data
    pos, nrm = mat.m3d_baked_position, mat.m3d_baked_worldnormal
    return (pos, nrm) if pos is not None and nrm is not None else None


def tri_values(layer, pos):
    """(multiply, add) that turn the Position map's 0-1 values into points of the projection: the world position at the bake (the
    bounds the bake scaled to, kept with the image) x Scale."""
    bounds = pos.get("m3d_bounds")
    lo, hi = (np.array(bounds[:3], np.float32), np.array(bounds[3:], np.float32)) if bounds is not None else (np.zeros(3), np.ones(3))
    span = np.maximum(hi - lo, 1e-6)
    return (span * layer.tri_scale).astype(np.float32), (lo * layer.tri_scale).astype(np.float32)


def triplanar_planes(layer, tri, size):
    """(points, weights), (size, size, 3) each, of the tri-planar projection at the texels of a size x size image: the points (see
    tri_values) and the share of each axis, |world normal| ^ Blend Sharpness adding up to 1."""
    pos, nrm = tri
    mul, add = tri_values(layer, pos)
    p = (pixels_of(pos, size)[..., :3] * mul + add).astype(np.float32)
    n = np.abs(pixels_of(nrm, size)[..., :3] * 2.0 - 1.0) ** np.float32(layer.tri_sharpness)
    return p, (n / np.maximum(n.sum(axis=-1, keepdims=True), 1e-6)).astype(np.float32)


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
    """Side of the texture set as its channel images say (0: none yet): the largest, at full size when they are painted at a
    working size (work_factor)."""
    return max((max(image_size(e.image)) for l in mat.m3d_layers for e in l.channels if e.image), default=0) * work_factor(mat)


def work_factor(mat):
    """How much smaller than the set's size its images are painted (Texture Set Settings > Working Size): 1, 2 or 4."""
    return int(mat.m3d_work) if mat is not None and mat.m3d_work else 1


def image_in_use(image):
    """Is the image used by anything else: a layer of any material, or a node the stack did not make."""
    if image.use_fake_user:
        return True
    for mat in bpy.data.materials:
        for layer in mat.m3d_layers:
            if layer.mask == image or any(image in {e.image, e.texture} for e in layer.channels) or any(
                    e.image == image or e.image2 == image for e in layer.mask_stack):
                return True
        if mat.node_tree and any(n.type in {'TEX_IMAGE', 'TEX_ENVIRONMENT'} and n.image == image and TAG not in n.keys()
                                 for n in mat.node_tree.nodes):
            return True
    return False


def remove_image(image):
    """Remove an image. A material that had it in an Image Texture node lists it as a paint slot, and Blender does not list the slots
    again when the image goes: the slot would point at the freed image (a crash later), so they are refreshed."""
    mats = [m for m in bpy.data.materials if m.node_tree and any(n.type == 'TEX_IMAGE' and n.image == image for n in m.node_tree.nodes)]
    bpy.data.images.remove(image)
    for mat in mats:
        refresh_slots(mat)


def release(images):
    """Remove images nothing uses any more (call after the layers and nodes using them are gone), with their full size originals."""
    for image in {i.name: i for i in images if i is not None}.values():
        if not image_in_use(image):
            full = image.get(MK.FULL)
            remove_image(image)
            if isinstance(full, bpy.types.Image):
                bpy.data.images.remove(full)


# -----------------------------------------------------------------------------
# Baked mesh maps in the shader: the Normal map under the Normal channel, the AO map over the Base Color

def view_ao_on():
    """Scene.m3d_tex.view_ao: does the AO map darken the Base Color in the viewport (Display Settings > AO in viewport)?"""
    scene = getattr(bpy.context, "scene", None)
    tex = getattr(scene, "m3d_tex", None)
    return tex is None or tex.view_ao


_rendering = [False]   # a render is being made: the viewport's AO multiply is out of the shader meanwhile (render_pre, render_end)


def baked_image(mat, label):
    """The baked map `label` ("Normal", "AO") the material's shader uses, or None. Only a texture set (a material with layers) uses
    them; the Normal map needs the Normal channel to be in the set, the AO map the "AO in viewport" option (and not a render)."""
    if not len(mat.m3d_layers):
        return None
    image = getattr(mat, BAKED_PROPS[label])
    if image is None or (label == "Normal" and channel_off(mat, 'NORMAL')) or (label == "AO" and (_rendering[0] or not view_ao_on())):
        return None
    return image


def normal_flip(image):
    """Was the baked normal map made with its green channel down (DirectX)? The bake says so on the image: the project's setting
    may have been changed since."""
    return image.get("m3d_nfmt") == 'DIRECTX'


def baked_signature(image):
    """What decides the nodes of a baked normal map (a map made again is another image, even with the same name)."""
    return repr(("baked", image.name, image.session_uid, normal_flip(image)))


def baked_normal_pixels(image, size):
    """The baked normal map as (size, size, 4) pixels, the green channel as OpenGL (what the Normal Map node reads)."""
    px = pixels_of(image, size).copy()
    if normal_flip(image):
        px[..., 1] = 1.0 - px[..., 1]
    return px


def combine_normals(base, detail):
    """Tangent space normals as pixels (0-1, OpenGL): `detail` on top of `base`, as the whiteout combine does: the slopes add up (x and
    y), the z's multiply, and the result is made one long. A flat detail (0.5, 0.5, 1) leaves the base as it is, a flat base leaves
    the detail. The nodes of the Normal channel compute the same (baked_normal_nodes)."""
    b, d = base[..., :3] * 2.0 - 1.0, detail[..., :3] * 2.0 - 1.0
    n = np.stack((b[..., 0] + d[..., 0], b[..., 1] + d[..., 1], b[..., 2] * d[..., 2]), axis=-1)
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-20)
    out = np.ones(base.shape[:2] + (4,), np.float32)
    out[..., :3] = n * 0.5 + 0.5
    return out


def flatten_normal(mat, size):
    """The Normal as the shader shows it and Export writes it, (size, size, 4): the layers' normal, on top of the baked normal map when
    the set has one (the layers alone otherwise). Merge Down and Flatten use flatten_channel: the baked map is not a layer."""
    layers = flatten_channel(mat, 'NORMAL', size)
    base = baked_image(mat, "Normal")
    return combine_normals(baked_normal_pixels(base, size), layers) if base is not None else layers


def node_factory(nodes, frame, tag):
    """new(idname, name, x, y): makes a node of the chain `tag` in `frame`, with the settings of the node it replaces."""
    def new(idname, name, x, y):
        node = nodes.new(idname)
        node.name = name
        node[TAG] = tag
        node.parent = frame
        node.location = (x, y)
        restore_settings(node)
        return node
    return new


def baked_normal_nodes(new, links, image, detail, x, y):
    """The nodes of the baked normal map: its Image Texture (a MULTIPLY_ADD turns the green channel over first when the bake made it
    DirectX), and with `detail` (a color socket: the layers' normal) the whiteout combine on top of it, in tangent space: decode both
    to -1..1, add the slopes, multiply the z's, normalize, encode. Returns the color socket for the Normal Map node."""
    def vector(key, operation, at, *inputs):
        node = new("ShaderNodeVectorMath", "%s.NORMAL.%s" % (TAG, key), x + at[0], y + at[1])
        node.operation = operation
        for i, value in enumerate(inputs):
            if isinstance(value, tuple):
                node.inputs[i].default_value = value
            else:
                links.new(value, node.inputs[i])
        return node.outputs[0]

    tex = new("ShaderNodeTexImage", "%s.NORMAL.base" % TAG, x, y)
    tex.image = image
    color = tex.outputs["Color"]
    if normal_flip(image):
        color = vector("flip", 'MULTIPLY_ADD', (300, 0), color, (1.0, -1.0, 1.0), (0.0, 1.0, 0.0))
    if detail is None:
        return color
    base_n = vector("base", 'MULTIPLY_ADD', (600, 0), color, (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0))
    detail_n = vector("detail", 'MULTIPLY_ADD', (600, -200), detail, (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0))
    total, product = vector("sum", 'ADD', (900, 0), base_n, detail_n), vector("prod", 'MULTIPLY', (900, -200), base_n, detail_n)
    sep_total, sep_product = (new("ShaderNodeSeparateXYZ", "%s.NORMAL.%s" % (TAG, key), x + 1200, y + dy)
                              for key, dy in (("sep_sum", 0), ("sep_prod", -200)))
    links.new(total, sep_total.inputs[0])
    links.new(product, sep_product.inputs[0])
    both = new("ShaderNodeCombineXYZ", "%s.NORMAL.comb" % TAG, x + 1500, y)
    links.new(sep_total.outputs["X"], both.inputs["X"])
    links.new(sep_total.outputs["Y"], both.inputs["Y"])
    links.new(sep_product.outputs["Z"], both.inputs["Z"])
    unit = vector("unit", 'NORMALIZE', (1800, 0), both.outputs[0])
    return vector("encode", 'MULTIPLY_ADD', (2100, 0), unit, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5))


def build_baked_normal(mat, image, sig):
    """The Normal chain of a texture set whose layers have no normal: the baked normal map into a Normal Map node."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    frame = nt.nodes.new("NodeFrame")
    frame.name, frame.label = "%s.NORMAL" % TAG, "Normal (baked map)"
    frame[TAG], frame["m3d_sig"] = 'NORMAL', sig
    new = node_factory(nt.nodes, frame, 'NORMAL')
    y = bsdf.location.y - 700 - CHANNEL_INDEX['NORMAL'] * 900
    node = new("ShaderNodeNormalMap", "%s.NORMAL.map" % TAG, bsdf.location.x - 300, y)
    node.space = 'TANGENT'
    nt.links.new(baked_normal_nodes(new, nt.links, image, None, bsdf.location.x - 1000, y), node.inputs["Color"])


def base_source(mat):
    """The socket that feeds the Principled BSDF's Base Color before the viewport's AO multiply (None: nothing does)."""
    socket = principled_of(mat).inputs["Base Color"]
    link = socket.links[0] if socket.links else None
    if link is not None and link.from_node.name == AO_MUL:
        links = link.from_node.inputs[6].links
        return links[0].from_socket if links else None
    return link.from_socket if link is not None else None


def sync_ao(mat):
    """The viewport's AO multiply: Base Color x the baked AO map (Image Texture -> Mix, Multiply) between the Base Color chain and the
    Principled BSDF, while the material has a baked AO map, a Base Color chain and "AO in viewport" is on; none otherwise. It is only
    in the nodes: Export reads the layers. True when nodes changed."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    if nt is None or bsdf is None:
        return False
    image, mul, tex = baked_image(mat, "AO"), nt.nodes.get(AO_MUL), nt.nodes.get(AO_TEX)
    socket = bsdf.inputs["Base Color"]
    on = bool(socket.links) and socket.links[0].from_node == mul
    source = base_source(mat)
    if image is None or source is None:
        if mul is None and tex is None:
            return False
        if on and source is not None:
            nt.links.new(source, socket)   # (the chain feeds the shader again)
        for node in (mul, tex):
            if node is not None:
                nt.nodes.remove(node)
        return True
    changed = mul is None
    if mul is None:
        mul = nt.nodes.new("ShaderNodeMix")
        mul.name, mul.label, mul[TAG] = AO_MUL, "AO (viewport)", "VIEW"
        mul.data_type, mul.blend_type, mul.location = 'RGBA', 'MULTIPLY', (bsdf.location.x - 220, bsdf.location.y + 330)
        mul.inputs[0].default_value = 1.0
    if tex is None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.name, tex.label, tex[TAG] = AO_TEX, "Baked AO", "VIEW"
        tex.location = (bsdf.location.x - 520, bsdf.location.y + 380)
    if tex.image != image:
        tex.image = image
        changed = True
    if not any(link.from_socket == source for link in mul.inputs[6].links):
        nt.links.new(source, mul.inputs[6])
        changed = True
    if not any(link.from_node == tex for link in mul.inputs[7].links):
        nt.links.new(tex.outputs["Color"], mul.inputs[7])
    if not on:
        nt.links.new(mul.outputs[2], socket)
        changed = True
    return changed


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
            {k: (l.from_node.name, l.from_socket.identifier) for k in _LINKED.get(node.type, ()) for l in node.inputs[k].links
             if TAG not in l.from_node.keys()})   # (names, not sockets: a socket outlives nothing, it is looked up again)


def restore_settings(node):
    props, values, links = _carry.pop(node.name, ({}, {}, {}))
    for key, value in props.items():
        setattr(node, key, value)
    for key, value in values.items():
        node.inputs[key].default_value = value
    for key, (from_name, identifier) in links.items():
        source = node.id_data.nodes.get(from_name)
        socket = next((o for o in source.outputs if o.identifier == identifier), None) if source is not None else None
        if socket is not None:
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


def signature(tree, ch_id, top=True):
    """What decides the chain's nodes and links; anything else (opacity, blend, fill, names) is only a value, except the
    blend modes that change the nodes: Replace (the image's alpha is not linked), and at the top level Color Burn / Dodge
    (one more Mix node)."""
    return repr([(l.uid, l.kind, entry_of(l, ch_id).image.name if uses_image(l) else "", bool(l.mask_stack), l.use_alpha,
                  *(("replace",) if replaces(l, ch_id) else ()), *(("two",) if top and two_step(l, ch_id) else ()),
                  *((signature(inside, ch_id, False),) if inside else ()),
                  *(("texture", entry_of(l, ch_id).texture.name) if has_texture(l, ch_id) else ()),
                  *(("tri",) + tuple(i.name for i in triplanar(l)) if has_texture(l, ch_id) and triplanar(l) else ()))
                 for l, inside in tree])


def set_values(nt, layer, ch_id):
    """Opacity, visibility, blend mode, fill value and names of a layer's nodes (no node or link changes)."""
    opv = nt.nodes.get(part(ch_id, layer.uid, "opv"))
    if opv is None:
        return
    e = entry_of(layer, ch_id)
    mix, fill = nt.nodes.get(part(ch_id, layer.uid, "mix")), nt.nodes.get(part(ch_id, layer.uid, "fill"))
    pre = nt.nodes.get(part(ch_id, layer.uid, "pre"))   # (Color Burn / Dodge at the top level: the blend, then the plain Mix)
    want = e.opacity if layer.visible else 0.0
    if abs(opv.inputs[1].default_value - want) > 1e-6:
        opv.inputs[1].default_value = want
    blend = node_mode(e.blend)
    if pre is not None:
        if pre.blend_type != blend:
            pre.blend_type = blend
        blend = 'MIX'
    if mix is not None and mix.blend_type != blend:
        mix.blend_type = blend
    if layer.kind == 'FILL' and not has_texture(layer, ch_id):   # (inside a folder a fill is a color node: both its Mix nodes read it)
        place = pre or mix
        target = fill.outputs[0] if fill is not None else place.inputs[7] if place is not None else None
        if target is not None:
            _set(target, fill_rgba(layer, ch_id))
    for key in ("map", "map1", "map2"):   # (the UV transform of a fill's texture: one Mapping node, three when tri-planar)
        mapping = nt.nodes.get(part(ch_id, layer.uid, key))
        if mapping is not None:
            for name, value in zip(("Location", "Rotation", "Scale"), fill_mapping(layer)):
                _set(mapping.inputs[name], value)
    points, power = nt.nodes.get(part(ch_id, layer.uid, "tp")), nt.nodes.get(part(ch_id, layer.uid, "tw"))
    tri = triplanar(layer) if points is not None else None
    if tri is not None:
        mul, add = tri_values(layer, tri[0])
        _set(points.inputs[1], tuple(float(v) for v in mul))
        _set(points.inputs[2], tuple(float(v) for v in add))
        _set(power.inputs[1], (layer.tri_sharpness,) * 3)
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
            if kind == 'COLORID':   # (colours of an ID map are not blended with their neighbours)
                tex.interpolation = 'Closest'
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
    """Feed every channel chain's mask multiply from its layer's mask chain (the chains are made apart); a mask that is
    switched off (Layer.use_mask) multiplies by 1."""
    nt = mat.node_tree
    for layer in mat.m3d_layers:
        top = mask_top(nt, layer)
        if top is None:
            continue
        for ch in CHANNELS:
            mul = nt.nodes.get(part(ch.id, layer.uid, "maskmul"))
            if mul is None:
                continue
            if layer.use_mask:
                if not any(l.from_socket == top for l in mul.inputs[1].links):
                    nt.links.new(top, mul.inputs[1])
            else:
                for link in list(mul.inputs[1].links):
                    nt.links.remove(link)
                _set(mul.inputs[1], 1.0)


def build_channel(mat, ch, tree, sig, base=None):
    """The frame with one chain for `ch`: Image Texture (or fill) -> Mix per layer, bottom to top, into the shader. The
    layers of a folder are chained the same way first, but over nothing instead of the channel's value: that chain
    carries the color and the coverage (how much of the pixel the layers cover), and the folder is one more layer of
    the chain below it, its image being that color and its alpha that coverage. `base`: the baked normal map the
    Normal chain goes on top of (see baked_normal_nodes)."""
    nt, bsdf = mat.node_tree, principled_of(mat)
    nodes, links = nt.nodes, nt.links
    y = bsdf.location.y - 700 - CHANNEL_INDEX[ch.id] * 900
    x_top = bsdf.location.x - 800
    frame = nodes.new("NodeFrame")
    frame.name, frame.label = "%s.%s" % (TAG, ch.id), ch.label + " Layers"
    frame[TAG], frame["m3d_sig"] = ch.id, sig
    columns, placed = len(list(walk(tree))), [0]
    new = node_factory(nodes, frame, ch.id)

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
            if replaces(layer, ch.id):
                # Replace: the image's alpha is read (an image node whose Alpha goes nowhere returns the color times its
                # alpha) but counts for nothing: alpha ^ 0 is 1
                one = new("ShaderNodeMath", part(ch.id, uid, "one"), x + 150, y_ - 160)
                one.operation = 'POWER'
                one.inputs[1].default_value = 0.0
                links.new(tex.outputs["Alpha"], one.inputs[0])
                links.new(one.outputs[0], opv.inputs[0])
            elif layer.use_alpha:
                links.new(tex.outputs["Alpha"], opv.inputs[0])
            else:
                opv.inputs[0].default_value = 1.0
        else:
            opv.inputs[0].default_value = 1.0
            tri = triplanar(layer) if has_texture(layer, ch.id) else None
            if tri is not None:
                color = triplanar_nodes(new, links, ch.id, uid, tri, entry_of(layer, ch.id).texture, x, y_)
            elif has_texture(layer, ch.id):   # a fill's texture: UV map -> Mapping (the layer's UV transform) -> image; opaque
                coord = new("ShaderNodeTexCoord", part(ch.id, uid, "coord"), x - 400, y_ + 250)
                mapping = new("ShaderNodeMapping", part(ch.id, uid, "map"), x - 200, y_ + 250)
                tex = new("ShaderNodeTexImage", part(ch.id, uid, "tex"), x, y_)
                tex.image = entry_of(layer, ch.id).texture
                links.new(coord.outputs["UV"], mapping.inputs["Vector"])
                links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
                color = tex.outputs["Color"]
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
        links.new(factor, mix.inputs[0])
        if below is None:
            mix.inputs[6].default_value = (*default_linear(ch), 1.0)
        else:
            links.new(below.outputs[2], mix.inputs[6])
        into = mix
        if two_step(layer, ch.id):   # Color Burn / Dodge: the blend at full strength, then the plain Mix by the factor
            into = mix_node(layer, "pre", x + 500, y_ + 150)
            into.inputs[0].default_value = 1.0
            links.new(into.outputs[2], mix.inputs[7])
            if below is None:
                into.inputs[6].default_value = (*default_linear(ch), 1.0)
            else:
                links.new(below.outputs[2], into.inputs[6])
        if src is not None:
            links.new(src, into.inputs[7])
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
        links.new(top if base is None else baked_normal_nodes(new, links, base, top, x_top - 300, y - 450), node.inputs["Color"])
    else:
        node = new("ShaderNodeBump", "%s.HEIGHT.bump" % TAG, bsdf.location.x - 300, y)
        links.new(top, node.inputs["Height"])


def triplanar_nodes(new, links, ch_id, uid, tri, image, x, y):
    """The nodes of a tri-planar fill texture (what triplanar_planes and texture_planes compute): the Position map -> points, the
    World Normal map -> weights; the texture read three times (the points' yz, xz and xy through the layer's Mapping) and mixed by
    the weights. -> the color socket. The values (Scale, Sharpness, the Mapping) are set by set_values."""
    def node(idname, key, dx, dy, **props):
        n = new(idname, part(ch_id, uid, key), x + dx, y + dy)
        for k, v in props.items():
            setattr(n, k, v)
        return n
    pos = node("ShaderNodeTexImage", "tpos", -1400, 500, image=tri[0])
    nrm = node("ShaderNodeTexImage", "tnrm", -1400, 200, image=tri[1])
    points = node("ShaderNodeVectorMath", "tp", -1150, 500, operation='MULTIPLY_ADD')
    links.new(pos.outputs["Color"], points.inputs[0])
    signed = node("ShaderNodeVectorMath", "tn", -1150, 200, operation='MULTIPLY_ADD')   # (the map stores n * 0.5 + 0.5)
    signed.inputs[1].default_value, signed.inputs[2].default_value = (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0)
    links.new(nrm.outputs["Color"], signed.inputs[0])
    size = node("ShaderNodeVectorMath", "ta", -1000, 200, operation='ABSOLUTE')
    links.new(signed.outputs[0], size.inputs[0])
    power = node("ShaderNodeVectorMath", "tw", -850, 200, operation='POWER')
    links.new(size.outputs[0], power.inputs[0])
    total = node("ShaderNodeVectorMath", "ts", -700, 100, operation='DOT_PRODUCT')
    total.inputs[1].default_value = (1.0, 1.0, 1.0)
    links.new(power.outputs[0], total.inputs[0])
    inverse = node("ShaderNodeMath", "ti", -550, 100, operation='DIVIDE')
    inverse.inputs[0].default_value = 1.0
    links.new(total.outputs["Value"], inverse.inputs[1])
    share = node("ShaderNodeVectorMath", "tsh", -400, 200, operation='SCALE')
    links.new(power.outputs[0], share.inputs[0])
    links.new(inverse.outputs[0], share.inputs["Scale"])
    weights = node("ShaderNodeSeparateXYZ", "tsw", -250, 200)
    links.new(share.outputs[0], weights.inputs[0])
    axes = node("ShaderNodeSeparateXYZ", "tpa", -1000, 500)
    links.new(points.outputs[0], axes.inputs[0])
    out = None
    for i, (a, b) in enumerate(TRI_AXES):
        suffix = str(i) if i else ""
        plane = node("ShaderNodeCombineXYZ", "tc" + suffix, -800, 700 - i * 250)
        links.new(axes.outputs[a], plane.inputs[0])
        links.new(axes.outputs[b], plane.inputs[1])
        mapping = node("ShaderNodeMapping", "map" + suffix, -600, 700 - i * 250)
        links.new(plane.outputs[0], mapping.inputs["Vector"])
        tex = node("ShaderNodeTexImage", "tex" + suffix, -350, 700 - i * 250, image=image)
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        scaled = node("ShaderNodeVectorMath", "tm" + suffix, -50, 600 - i * 200, operation='SCALE')
        links.new(tex.outputs["Color"], scaled.inputs[0])
        links.new(weights.outputs[i], scaled.inputs["Scale"])
        if out is None:
            out = scaled.outputs[0]
        else:
            add = node("ShaderNodeVectorMath", "tadd" + suffix, 100, 500 - i * 150, operation='ADD')
            links.new(out, add.inputs[0])
            links.new(scaled.outputs[0], add.inputs[1])
            out = add.outputs[0]
    return out


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
    base = baked_image(mat, "Normal") if ch_id == 'NORMAL' else None   # (the baked normal map is the base of the Normal channel)
    sig = signature(tree, ch_id) + (baked_signature(base) if base is not None else "")
    frame = nt.nodes.get("%s.%s" % (TAG, ch_id))
    if frame is not None and (tree or base is not None) and frame.get("m3d_sig") == sig:
        for layer in walk(tree):
            set_values(nt, layer, ch_id)
        return False
    ours = [n for n in nt.nodes if n.get(TAG) == ch_id]
    for node in ours:
        if node.type in _PROPS:
            _carry[node.name] = settings_of(node)
        nt.nodes.remove(node)
    if tree:
        build_channel(mat, CHANNEL_BY_ID[ch_id], tree, sig, base)
    elif base is not None:
        build_baked_normal(mat, base, sig)
    if ch_id in {'NORMAL', 'HEIGHT'}:
        link_normal(mat)
    return bool(ours or tree or base is not None)


def rebuild_all(mat):
    upgrade(mat)
    live = live_layers(mat)
    for layer in live:
        MK.ensure_caches(layer)
    try:
        changed = [rebuild_masks(mat)] + [rebuild(mat, ch.id) for ch in CHANNELS]
        changed.append(sync_ao(mat))
    finally:
        _carry.clear()   # (also after an error: nothing carried over goes on to another material or file)
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
MAPVIEW = "%s.mapview" % TAG   # the Image Texture node of Material.m3d_show_map (a baked map shown the same way)


def output_node(nt):
    outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    return next((n for n in outs if n.is_active_output), outs[0] if outs else None)


def maskview_off(mat):
    """Back to the shader: our Emission node goes and the link it replaced (remembered on the material) returns."""
    nt = mat.node_tree
    emit, state, out = nt.nodes.get(MASKVIEW), mat.get("m3d_maskview"), output_node(nt)
    for name in (MASKVIEW, MAPVIEW):
        if nt.nodes.get(name) is not None:
            nt.nodes.remove(nt.nodes[name])
    node = nt.nodes.get(state[0]) if state else None
    socket = next((s for s in node.outputs if s.identifier == state[1]), None) if node is not None else None
    if socket is not None and out is not None:
        nt.links.new(socket, out.inputs["Surface"])
    if "m3d_maskview" in mat.keys():
        del mat["m3d_maskview"]


def sync_maskview(mat):
    """Make the material match Material.m3d_show_mask: on, the Material Output shows an Emission node fed by the
    active layer's mask (white when it has none); the link it replaces is kept in the material's m3d_maskview. Material.m3d_show_map
    (the name of a baked map's image) does the same with that image instead of the mask, and Material.m3d_unlit with the Base Color
    (flat, before the viewport's AO multiply)."""
    nt = mat.node_tree
    out = output_node(nt) if nt is not None else None
    image = bpy.data.images.get(mat.m3d_show_map) if mat.m3d_show_map else None
    if nt is None or out is None or not (mat.m3d_show_mask or image is not None or mat.m3d_unlit):
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
    unlit = mat.m3d_unlit and not mat.m3d_show_mask and image is None   # (Unlit: the Base Color flat)
    top = mask_top(nt, layer) if layer is not None and image is None and not unlit else None
    color = emit.inputs["Color"]
    tex = nt.nodes.get(MAPVIEW)
    if image is None and tex is not None:
        nt.nodes.remove(tex)
    if image is not None:
        if tex is None:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.name, tex.label, tex[TAG] = MAPVIEW, "Show Map", "MAPVIEW"
            tex.location = (emit.location.x - 300, emit.location.y)
        if tex.image != image:
            tex.image = image
        if not any(l.from_node == tex for l in color.links):
            nt.links.new(tex.outputs["Color"], color)
    elif unlit:
        source = base_source(mat)
        if source is not None:
            if not any(l.from_socket == source for l in color.links):
                nt.links.new(source, color)
        else:
            for link in list(color.links):
                nt.links.remove(link)
            color.default_value = principled_of(mat).inputs["Base Color"].default_value
    elif top is not None:
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


def show_view(mat, mask=False, map_name=""):
    """What the material shows instead of its shader: the active layer's mask, a baked map (the name of its image), or nothing."""
    mat.m3d_show_mask, mat.m3d_show_map = mask, map_name


# -----------------------------------------------------------------------------
# Mask effects

def upgrade(mat):
    """Files from before mask stacks: a layer's mask image becomes a Paint effect (and Invert Mask an Invert filter),
    so the layer looks the same; a layer from before every channel had its own blend and opacity gets its one blend and
    opacity in every channel (Normal always mixed, so it keeps mixing). True when a layer was upgraded."""
    done = False
    for layer in mat.m3d_layers:
        if not layer.per_channel:
            blend, opacity = legacy_look(layer)
            with muted():
                for ch in CHANNELS:
                    e = entry_of(layer, ch.id)
                    e.blend, e.opacity = 'MIX' if ch.id == 'NORMAL' else blend, opacity
                layer.per_channel = True
            for key in ("blend", "opacity"):
                if key in layer.keys():
                    del layer[key]
            done = True
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
    it up; `replace`: every effect reads this mesh's maps (the texture set's, see m3d_texture.texture_set). A texture set also
    takes the mesh's baked Normal and AO maps for its shader (BAKED_PROPS); the nodes follow at the next rebuild."""
    import m3d_texture
    with muted():
        for layer in mat.m3d_layers:
            for e in layer.mask_stack:
                have = MK.map_images(e)
                for key in MK.needed_maps(e):
                    image = m3d_texture.map_image(ob, MK.MAP_LABELS[key])
                    if image is not None and (replace or have[key] is None):
                        assign_map(e, key, image)
        if len(mat.m3d_layers):
            maps = dict(m3d_texture.mesh_maps(ob))
            for label, prop in BAKED_PROPS.items():
                if getattr(mat, prop) != maps.get(label):
                    setattr(mat, prop, maps.get(label))


def use_baked_maps(context, obs):
    """The texture sets of the meshes `obs` use their baked maps (after a bake, a map picked from a file or cleared): the Normal map as
    the base normal and the AO map over the Base Color in the shader, the effects that read a map pick it up. The paint target is
    aimed again (new nodes change the list of paint slots)."""
    done = set()
    for ob in obs:
        for slot in ob.material_slots:
            mat = slot.material
            if mat is not None and mat not in done and len(mat.m3d_layers) and mat.node_tree is not None:
                done.add(mat)
                link_maps(mat, ob)
                rebuild_all(mat)
    active = getattr(context, "object", None) if context is not None else None
    if active is not None and active.type == 'MESH' and active.active_material in done:
        sync_target(context, active.active_material, True)


def prepare(context, mat):
    """Before the stack is flattened: bake the maps its mask effects still miss, bring the blur caches up to date."""
    ob = mesh_of(context)
    missing = {key for layer in mat.m3d_layers for _e, key in MK.missing_maps(layer)}
    if any(l.kind == 'FILL' and l.projection == 'TRIPLANAR' and triplanar(l) is None for l in mat.m3d_layers):
        missing |= {'POSITION', 'WORLDNORMAL'}   # (a tri-planar fill without its maps)
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
    """A new image for a layer's channel (`size`: its side, or (width, height)). `opaque`: the bottom layer's kind, filled
    with the channel's starting color (data channels without alpha, like a new paint slot); otherwise transparent, so
    only painted pixels show."""
    alpha = ch.id == 'BASE_COLOR' or not opaque
    width, height = (size, size) if isinstance(size, int) else size
    half = channel_depth(mat, ch.id) == 16
    image = bpy.data.images.new(image_name(mat, layer, ch.label), width, height, alpha=alpha, float_buffer=half, is_data=not ch.srgb)
    if half:
        image.use_half_precision = True   # (only for the float ones: setting it reloads the image)
    image.generated_color = (*ch.color[:3], 1.0 if opaque else 0.0)
    set_channel_space(image, ch)
    return image


def make_mask_image(mat, layer, size, white):
    """The image of a Paint effect: white shows the layer, black hides it."""
    image = bpy.data.images.new(image_name(mat, layer, "Mask"), size, size, alpha=False, is_data=True)
    image.generated_color = (1.0, 1.0, 1.0, 1.0) if white else (0.0, 0.0, 0.0, 1.0)
    return image


def copy_image(image, name, half=None):
    """A copy of an image; `half` True / False makes it a 16 bit float / 8 bit one (None: the same kind)."""
    w, h = image.size
    float_buffer = image.is_float if half is None else half
    new = bpy.data.images.new(name[:60], w, h, alpha=image.depth in {32, 64, 128}, float_buffer=float_buffer,
                              is_data=image.colorspace_settings.is_data)
    if float_buffer:
        new.use_half_precision = half is not False and (half or image.use_half_precision)
    new.colorspace_settings.name = image.colorspace_settings.name
    if "m3d_channel" in image.keys():
        new["m3d_channel"] = image["m3d_channel"]
    write_pixels(new, pixels_of(image, w))
    return new


def new_size(context, mat=None):
    """Side of a new image: the size chosen for the material's texture set, else the new slot size of the Texture settings (at the
    working size when the set is painted at one)."""
    size = mat.m3d_size if mat is not None and mat.m3d_size else int(context.scene.m3d_tex.resolution)
    return size // work_factor(mat)


SIZES = (64, 128, 256, 512, 1024, 2048, 4096)   # the sides a texture set can have (always square: the layer math works on squares)
DEPTH_CHANNELS = {ch.id for ch in CHANNELS if not ch.srgb}   # the channels that can be 16 bit float (the colors stay 8 bit sRGB:
# a float image stores linear light, which the layer math of the color channels does not read)


def set_size(context, mat):
    """Side of the material's texture set: its largest image, else the size chosen for it, else the new slot size."""
    return stack_size(mat) or new_size(context, mat)


def set_channel_off(context, mat, ch_id, off):
    """Remove a channel from the material's texture set (`off`) or add it again. The layers keep their images: the channel's
    chain is taken away (and painting, the views and Export leave it out) until it is added back, which builds it as it was."""
    names = [c for c in mat.m3d_off.split("|") if c and c != ch_id]
    if off:
        names.append(ch_id)
    mat.m3d_off = "|".join(c for c in (ch.id for ch in CHANNELS) if c in names)
    if off and mat.m3d_channel == ch_id:
        with muted():
            mat.m3d_channel = next((c.id for c in set_channels(mat)), 'BASE_COLOR')
    if off and mat.m3d_row_channel == ch_id:
        mat.m3d_row_channel = mat.m3d_channel
    refresh(context, mat)


def channel_images(mat, ch_id):
    """The images the layers of the stack hold for a channel (a frozen folder's too), each once."""
    return list(dict.fromkeys(e.image for l in mat.m3d_layers for e in [entry_of(l, ch_id)] if e.image is not None))


def set_depth(context, mat, ch_id, bits):
    """Store a channel's images as 8 bit or 16 bit float: every image of the channel in the stack is copied into the other kind
    (the pixels are the same, to what the kind keeps) and takes the old one's place and name; new images follow the setting.
    Returns how many images were converted."""
    half = bits == 16 and ch_id in DEPTH_CHANNELS
    names = [c for c in mat.m3d_depth.split("|") if c and c != ch_id]
    if half:
        names.append(ch_id)
    mat.m3d_depth = "|".join(names)
    done = {}
    for old in channel_images(mat, ch_id):
        if old.is_float == half and old.use_half_precision == half:
            continue
        done[old] = copy_image(old, old.name + "~", half)
    with muted():
        for layer in mat.m3d_layers:
            e = entry_of(layer, ch_id)
            if e.image in done:
                e.image = done[e.image]
    for node in mat.node_tree.nodes if mat.node_tree else ():   # (the chains' Image Texture nodes show the copies: the names stay the same)
        if node.type == 'TEX_IMAGE' and node.image in done:
            node.image = done[node.image]
    if mat.node_tree is not None and done:
        refresh_slots(mat)   # (the paint slots point at the copies, not at the images that go)
    for old, new in done.items():
        name = old.name
        release([old])
        leftover = bpy.data.images.get(name)
        if leftover is not None:
            leftover.name = name + " (old)"   # (something outside the stack still uses it: it stays)
        new.name = name
    refresh(context, mat)
    return len(done)


def set_images(mat):
    """The images of the texture set that hold pixels of their own (the blur caches are made from the masks)."""
    caches = {e.image for l in mat.m3d_layers for e in l.mask_stack if e.kind == 'BLUR'}
    return [img for img in dict.fromkeys(img for l in mat.m3d_layers for img in layer_images(l)) if img not in caches]


def resize_set(context, mat, size):
    """Scale every image of the texture set to size x size (at a working size: to that share of it, and their originals to the size):
    the channel images, the masks' paint images, frozen folders'. A generated image that was never painted is only told its new
    size. Returns how many images changed."""
    count, factor, old = 0, work_factor(mat), set_size(context, mat)
    work = size // factor
    for image in set_images(mat):
        if image.get(MK.FULL) is not None:   # (painted at a working size: the original is scaled, the working image made from it)
            px = pixels_of(image, old)
            store_working(image, MK.box_down(px, size) if size < old else MK.linear_up(px, size), work)
            count += 1
            continue
        if image_size(image) == (work, work):
            continue
        if image.source == 'GENERATED' and not image.has_data:
            image.generated_width = image.generated_height = work
        else:
            image.scale(work, work)
        count += 1
    mat.m3d_size = size
    refresh(context, mat)
    return count


def store_working(image, full_px, size):
    """Keep `full_px` (the pixels at full size) as the image's original (an image of its own, kept with the file) and make the
    image itself those pixels scaled down to `size`: what is painted on. full_pixels puts them together again."""
    side = full_px.shape[0]
    full = image.get(MK.FULL)
    if isinstance(full, bpy.types.Image) and tuple(full.size) != (side, side):
        full.scale(side, side)
    elif not isinstance(full, bpy.types.Image):
        full = bpy.data.images.new((image.name + " (full)")[:60], side, side, alpha=True, float_buffer=image.is_float,
                                   is_data=image.colorspace_settings.is_data)
        if image.is_float:
            full.use_half_precision = image.use_half_precision
        full.colorspace_settings.name = image.colorspace_settings.name
        full.use_fake_user = True   # (nothing else uses it: the file keeps it)
        image[MK.FULL] = full
    write_pixels(full, full_px)
    if image_size(image) != (size, size):
        image.scale(size, size)
    write_pixels(image, MK.box_down(full_px, size))


def put_pixels(image, px):
    """Write pixels made at full size into a layer image: as they are, or (an image smaller than them: painted at a working size)
    as its original and scaled down."""
    if px.shape[0] > image_size(image)[0]:
        store_working(image, px, image_size(image)[0])
    else:
        write_pixels(image, px)


WORK_ITEMS = (('1', "Full", "Paint at the texture set's size"),
              ('2', "1/2", "Paint at half the size (a quarter of the memory); Export and Bake write the full size"),
              ('4', "1/4", "Paint at a quarter of the size; Export and Bake write the full size"))


def set_working(context, mat, factor):
    """Paint the texture set at 1 / `factor` of its size: every image of it is made that size, its full size pixels kept as its
    original (store_working); what was painted at the old working size goes into the original first, so nothing is lost but the
    detail painted at the lower size. Back to Full the image is the original again, with what was painted (scaled up) where it was
    painted. Export, Bake and Flatten read the full size (pixels_of). Returns how many images changed."""
    full = set_size(context, mat)
    mat.m3d_size = full
    work, count = full // factor, 0
    for image in set_images(mat):
        if image.source == 'GENERATED' and not image.has_data:   # (never painted: only its size)
            image.generated_width = image.generated_height = work
            continue
        side, orig = image_size(image)[0], image.get(MK.FULL)
        px = pixels_of(image, full) if orig is not None or side >= full else MK.linear_up(pixels_of(image, side), full)
        if factor == 1:
            if side != full:
                image.scale(full, full)
            write_pixels(image, px)
            if orig is not None:
                del image[MK.FULL]
                if isinstance(orig, bpy.types.Image):
                    bpy.data.images.remove(orig)
        else:
            store_working(image, px, work)
        count += 1
    mat.m3d_work = str(factor)
    refresh(context, mat)
    return count


# The brush material: the channels one stroke paints at once (Scene.m3d_tex.brush, see m3d_texture.py). The paint code reads
# the list of their images from the window manager property TARGETS when a stroke starts (paint_targets_get in
# paint_image.cc): the first image is the one the brush paints anyway (the canvas), the rest are painted along with it
# through the same stroke: same texels, same opacity and falloff, undone with it. A list that does not name the canvas does
# nothing, so a stale one is harmless.
TARGETS = "m3d_paint_targets"
BRUSH_CHANNELS = ('BASE_COLOR', 'HEIGHT', 'ROUGHNESS', 'METALLIC', 'EMISSION')   # (Normal is painted alone: see target_set)


def brush_of(context):
    tex = getattr(context.scene, "m3d_tex", None)
    return tex.brush if tex is not None else None


def brush_channels(context):
    """The channels of the brush material that are on, in the order of CHANNELS (Base Color first)."""
    brush = brush_of(context)
    return [ch for ch in CHANNELS if brush is not None and ch.id in BRUSH_CHANNELS and getattr(brush, "use_" + ch.id.lower())]


def brush_value(brush, ch_id):
    """The linear value a stroke paints into channel `ch_id` of the brush material (not Base Color: that is the brush
    color): a grey for the scalar channels, the color of Emission."""
    value = getattr(brush, ch_id.lower())
    return (value, value, value) if ch_id in SCALARS else tuple(value)


def paint_only(context, ch_id):
    """The brush material paints channel `ch_id` alone (no channel of it when `ch_id` is one it has none for)."""
    brush = brush_of(context)
    if brush is not None:
        with muted():
            for cid in BRUSH_CHANNELS:
                setattr(brush, "use_" + cid.lower(), cid == ch_id)


def layer_size(context, layer):
    """(width, height) of the layer's images: a new one is made at that size (the paint code paints only images of the
    size of the canvas). A layer without images starts at the size of new slots."""
    for ch in CHANNELS:
        image = entry_of(layer, ch.id).image
        if image is not None:
            return image_size(image)
    return (new_size(context, layer.id_data),) * 2


def stroke_targets(context, mat, layer, create):
    """[(channel, image)] a stroke on a paint layer paints: the channels of the brush material that are on and that the
    layer has, Base Color first (the canvas). The images they lack are made when `create` (with the others' size)."""
    wanted = [ch for ch in brush_channels(context) if entry_of(layer, ch.id).use and not channel_off(mat, ch.id)]
    if create and any(entry_of(layer, ch.id).image is None for ch in wanted):
        size = layer_size(context, layer)
        with muted():
            for ch in wanted:
                if entry_of(layer, ch.id).image is None:
                    entry_of(layer, ch.id).image = make_channel_image(mat, layer, ch, size, opaque=mat.m3d_layer_index == 0)
        rebuild_all(mat)
    return [(ch, entry_of(layer, ch.id).image) for ch in wanted if entry_of(layer, ch.id).image is not None]


def target_set(context, mat, create):
    """(canvas, [(channel, image)]): the image strokes should go to, and the images one stroke paints at once (see
    stroke_targets; the canvas is the first of them). With the mask thumbnail selected (mask_active) strokes go to the active
    layer's Paint effect alone. A paint layer paints the channels of the brush material; when it has none of them the channel
    being shown (Material.m3d_channel) is painted alone, which is how Normal is painted. The canvas is None for the content of
    a fill layer or a folder, a mask without a Paint effect, a layer in a frozen folder (its layers are no paint slots: nothing
    can be painted), or a channel the layer does not have. The images are made here when `create`."""
    layer = active_layer(mat)
    if layer is None or in_frozen(layer):
        return None, []
    if mask_active(layer):
        effect = paint_effect(layer)
        return (effect.image if effect is not None else None), []
    if layer.kind != 'PAINT':
        return None, []
    targets = stroke_targets(context, mat, layer, create)
    if targets:
        return targets[0][1], targets
    ch = CHANNEL_BY_ID[mat.m3d_channel]
    e = entry_of(layer, ch.id)
    if not e.use:
        return None, []
    if e.image is None and create:
        with muted():
            e.image = make_channel_image(mat, layer, ch, layer_size(context, layer), opaque=mat.m3d_layer_index == 0)
        rebuild_all(mat)
    return e.image, []


def target_image(context, mat, create):
    """The image strokes go to (see target_set)."""
    return target_set(context, mat, create)[0]


def write_paint_targets(context, targets):
    """Tell the paint code which images a stroke paints (TARGETS): the image of each channel, with its value (Base Color
    has none: it gets the brush color). Without targets the property is removed."""
    wm = context.window_manager
    brush = brush_of(context)
    items = [{"image": image.name} if ch.id == 'BASE_COLOR' else
             {"image": image.name, "color": [float(v) for v in brush_value(brush, ch.id)]} for ch, image in targets]
    if items:
        wm[TARGETS] = items   # (even one: a canvas that is not Base Color needs its value, not the brush color)
    elif TARGETS in wm:
        del wm[TARGETS]


def sync_target(context, mat, create):
    """Point the material's paint slot at the paint target (see target_set) and tell the paint code what else to paint."""
    image, targets = target_set(context, mat, create)
    if image is None and len(mat.m3d_layers):
        image = ensure_scratch(mat)   # Nothing paintable here: strokes must not land on some other layer's image.
    images = list(mat.texture_paint_images)
    if image is not None and image in images:
        mat.paint_active_slot = images.index(image)
    write_paint_targets(context, targets)
    return image


def sync_list(context):
    """Write the images of a stroke for the active mesh's material only (no image or node is made: for a loaded file and
    for Undo / Redo, which bring back layers and toggles but not the window manager's property)."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    write_paint_targets(context, target_set(context, mat, False)[1] if mat is not None and len(mat.m3d_layers) else [])


def refresh(context, mat):
    """The layer data changed: rebuild the chains, then aim the brush."""
    ob = getattr(context, "object", None)
    if ob is not None and ob.type == 'MESH' and ob.active_material == mat:
        link_maps(mat, ob)
    rebuild_all(mat)
    if ob is not None and ob.type == 'MESH' and ob.active_material == mat:
        sync_target(context, mat, True)
    import m3d_texture
    m3d_texture.preview_dirty(mat.name)   # (the 2D view's Material View is made again on a timer)


def paint_channel(context, ob, ch):
    """Paint channel `ch` on the active layer, and nothing else: the layer gets the channel and, once, its image, and the
    brush material has it alone on. Returns the image."""
    mat = ob.active_material
    layer = active_layer(mat)
    if layer is None:
        return None
    if channel_off(mat, ch.id):
        raise RuntimeError("%s is not in this texture set: add it in Texture Set Settings" % ch.label)
    with muted():
        mat.m3d_channel = ch.id
        if in_frozen(layer):
            raise RuntimeError("The folder is frozen: unfreeze it to paint its layers")
        if layer.kind == 'FOLDER' and not mask_active(layer):
            raise RuntimeError("A folder cannot be painted: pick a layer inside it" + (", or its mask" if layer.mask_stack else ""))
        if layer.kind == 'FILL' and not mask_active(layer):
            raise RuntimeError("A Fill Layer cannot be painted: " + ("click its mask thumbnail to paint the mask, or "
                                                                     if layer.mask_stack else "") + "use Convert to Paint Layer")
        if layer.kind == 'PAINT':
            entry_of(layer, ch.id).use = True
            layer.paint_mask = False
    paint_only(context, ch.id)
    return sync_target(context, mat, True)


def stack_slots(mat):
    """{channel id: (slot index, image)}: where each channel with a painted image is painted, the active layer first."""
    images = list(mat.texture_paint_images)
    found = {}
    active = mat.m3d_layer_index
    order = [active] + [i for i in reversed(range(len(mat.m3d_layers))) if i != active]
    for ch in set_channels(mat):
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

def texture_planes(layer, ch, size):
    """Linear rgb of a fill's texture for a size x size image: the texture read at the center of each texel of the UV map
    through the layer's UV transform (fill_matrix), repeating, filtered as the chain's Image Texture node is (Closest, else
    Linear), the alpha not used. As the nodes show it, except that the Cubic and Smart filters are read as Linear."""
    image = entry_of(layer, ch.id).texture
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    w, h = image.size
    if not w or not h:   # (a file that is not there: the value stands in)
        return np.broadcast_to(np.array(fill_rgba(layer, ch.id)[:3], np.float32), (size, size, 3))
    px = px.reshape(h, w, 4)[..., :3]
    if ch.srgb:
        px = to_linear(px)
    m, loc = fill_matrix(layer)
    node = layer.id_data.node_tree.nodes.get(part(ch.id, layer.uid, "tex")) if layer.id_data.node_tree else None
    closest = node is not None and node.interpolation == 'Closest'
    tri = triplanar(layer)
    if tri is None:
        ys, xs = np.mgrid[0:size, 0:size]
        uv = np.stack(((xs + 0.5) / size, (ys + 0.5) / size), -1) @ m.T + loc
        return lookup(px, uv[..., 0] * w, uv[..., 1] * h, closest)   # (texel i is centered at i + 0.5)
    p, weights = triplanar_planes(layer, tri, size)
    out = np.zeros((size, size, 3), np.float32)
    for axis, (i, j) in enumerate(TRI_AXES):   # (the texture seen along x, y and z, mixed by how much the surface faces each way)
        uv = np.stack((p[..., i], p[..., j]), -1) @ m.T + loc
        out += lookup(px, uv[..., 0] * w, uv[..., 1] * h, closest) * weights[..., axis:axis + 1]
    return out


def lookup(px, fx, fy, closest=False):
    """An image's pixels `px` (h, w, n) read at the points (fx, fy) in pixels (texel i centered at i + 0.5), repeating, as an Image
    Texture node reads them: Closest, else Linear."""
    h, w = px.shape[:2]
    if closest:
        return px[np.floor(fy).astype(int) % h, np.floor(fx).astype(int) % w]
    fx, fy = fx - 0.5, fy - 0.5
    x0, y0 = np.floor(fx), np.floor(fy)
    ax, ay = (fx - x0)[..., None], (fy - y0)[..., None]
    x0, y0 = x0.astype(int), y0.astype(int)

    def at(y, x):
        return px[y % h, x % w]
    return ((at(y0, x0) * (1 - ax) + at(y0, x0 + 1) * ax) * (1 - ay) + (at(y0 + 1, x0) * (1 - ax) + at(y0 + 1, x0 + 1) * ax) * ay)


def fill_planes(layer, ch, size):
    """Linear rgb of a fill layer's channel for a size x size image: its value, or its texture."""
    if has_texture(layer, ch.id):
        return texture_planes(layer, ch, size).astype(np.float32)
    return np.broadcast_to(np.array(fill_rgba(layer, ch.id)[:3], np.float32), (size, size, 3))


def layer_planes(layer, ch, size):
    """(linear rgb, coverage) of a layer's channel: the image alpha x opacity x mask (0 when hidden) is the coverage. A
    folder is what its layers make together over nothing (or its frozen image: the same, within what the image stores)."""
    e = entry_of(layer, ch.id)
    if layer.kind == 'FOLDER' and not layer.frozen:
        rgb, alpha = stack_planes(children(layer), ch, size)
    elif layer.kind == 'FILL':
        rgb = fill_planes(layer, ch, size)
        alpha = np.ones((size, size), np.float32)
    else:
        px = pixels_of(e.image, size)
        rgb, alpha = px[..., :3], px[..., 3] if layer.use_alpha and not replaces(layer, ch.id) else np.ones((size, size), np.float32)
        if ch.srgb:
            rgb = to_linear(rgb)
    alpha = alpha * np.float32(e.opacity if layer.visible else 0.0)
    if layer.mask_stack and layer.use_mask:
        alpha = alpha * MK.stack_value(layer, size)
    return rgb, alpha


def stack_planes(layers, ch, size, rgb=None, alpha=None):
    """`layers` (bottom to top) composited over (rgb, alpha), over nothing when those are not given: (rgb, alpha)."""
    if rgb is None:
        rgb, alpha = np.zeros((size, size, 3), np.float32), np.zeros((size, size), np.float32)
    for layer in layers:
        if has_content(layer, ch.id):
            lrgb, la = layer_planes(layer, ch, size)
            rgb, alpha = over(rgb, alpha, lrgb, la, mode_of(layer, ch.id))
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
def flattened_material(obs, mat, size):
    """For exporters that read the material: the slots using `mat` (of the mesh `obs`, or of each in a list) hold a copy where
    the layer chains are replaced by one flattened image per channel. The layers and their nodes are not touched; everything
    temporary goes after."""
    temp = mat.copy()
    images = []
    slots = [s for o in ([obs] if isinstance(obs, bpy.types.Object) else obs) for s in o.material_slots if s.material == mat]
    try:
        nt = temp.node_tree
        maskview_off(temp)   # Show Mask replaced the shader's link: the exporter needs it back.
        for node in [n for n in nt.nodes if TAG in n.keys()]:
            nt.nodes.remove(node)
        bsdf = principled_of(temp)
        channels = content_channels(mat)
        if 'NORMAL' not in channels and baked_image(mat, "Normal") is not None:
            channels.append('NORMAL')   # (the baked normal map is the Normal of a set whose layers have none)
        for ch_id in channels:
            if ch_id == 'HEIGHT':
                continue   # glTF has no height map.
            ch = CHANNEL_BY_ID[ch_id]
            image = bpy.data.images.new("m3dFlat" + ch_id, size, size, alpha=False, is_data=not ch.srgb)
            write_pixels(image, flatten_normal(mat, size) if ch_id == 'NORMAL' else flatten_channel(mat, ch_id, size))
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

def unique_name(mat, base, skip=None):
    names = {l.name for l in mat.m3d_layers if skip is None or l.uid != skip.uid}
    return next(n for n in (base, *("%s %d" % (base, i) for i in range(2, 10000))) if n not in names)


def add_layer(mat, kind, name=None, base=False):
    """A new layer at the end of the stack (the caller moves it). Every channel mixes, except Height, which adds (Linear
    Dodge). `base`: the layer holds what the channels look like (the Base layer that migrating slots or Flatten make), so
    Height mixes too."""
    layer = mat.m3d_layers.add()
    with muted():
        layer.uid = uuid.uuid4().hex[:6]
        layer.name = name or unique_name(mat, {'PAINT': "Paint Layer", 'FILL': "Fill Layer", 'FOLDER': "Folder"}[kind])
        layer.kind = kind
        layer.per_channel = True
        for ch in CHANNELS:
            e = layer.channels.add()
            e.channel = ch.id
            e.use = kind == 'PAINT' or (kind == 'FILL' and ch.id == 'BASE_COLOR')
            e.color = (*default_linear(ch), 1.0)
            e.value = ch.color[0]
            # Height is 0.5 flat: Linear Light leaves 0.5 alone, raises above it and digs below (what Add does to a
            # signed height); the Base layer sets the height, so it mixes.
            e.blend = 'LINEAR_LIGHT' if ch.id == 'HEIGHT' and not base else 'MIX'
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
    layer = add_layer(mat, 'PAINT', "Base", base=True)
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
    paint_only(bpy.context, mat.m3d_channel)   # (and the brush material paints that channel alone, as the slots did)
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


def copy_layer(mat, uid, source=None):
    """A copy of one layer of `source` (default: of `mat`), with copies of its images, at the end of the stack of `mat` (the
    caller places it)."""
    source = source or mat
    new = add_layer(mat, layer_by_uid(source, uid).kind)   # Adding can move the collection: look the source up again.
    src = layer_by_uid(source, uid)
    with muted():
        new.name = unique_name(mat, src.name + (" Copy" if source == mat else ""), skip=new)
        new.visible, new.use_alpha, new.use_mask = src.visible, src.use_alpha, src.use_mask
        new.paint_mask, new.expanded, new.frozen = src.paint_mask, src.expanded, src.frozen
        new.uv_tiling, new.uv_rotation, new.uv_offset = src.uv_tiling, src.uv_rotation, src.uv_offset
        new.projection, new.tri_scale, new.tri_sharpness = src.projection, src.tri_scale, src.tri_sharpness
        for ch in CHANNELS:
            a, b = entry_of(src, ch.id), entry_of(new, ch.id)
            b.use, b.color, b.value, b.texture = a.use, a.color, a.value, a.texture
            b.blend, b.opacity = a.blend, a.opacity
            if a.image is not None:
                b.image = copy_image(a.image, image_name(mat, new, ch.label))
        copy_mask(mat, src, new)
    return new


def copy_mask(mat, src, dst):
    """Add copies of the mask effects of the layer `src` to the mask of `dst` (a layer of `mat`): Paint images are copied, the
    blur caches are made again, baked maps are shared."""
    for e in src.mask_stack:
        copy = dst.mask_stack.add()
        MK.copy_params(e, copy)
        copy.uid = MK.new_uid()
        copy.image2 = e.image2
        if e.kind == 'PAINT':
            copy.image = copy_image(e.image, image_name(mat, dst, "Mask"))
        elif e.kind != 'BLUR':
            copy.image = e.image
    dst.mask_index = src.mask_index


def clone_layers(mat, uid, anchor_uid, source=None):
    """Copy the layer `uid` of `source` (default: of `mat`; a folder with everything inside it) into `mat`, directly above
    the layer `anchor_uid` and in the folder that one is in (the top of the stack without an anchor). Images are copied.
    -> the uid of the copy"""
    source = source or mat
    top = layer_by_uid(source, uid)
    group = subtree(top)
    uids, parents = [l.uid for l in group], {l.uid: l.parent for l in group}
    copies = {u: copy_layer(mat, u, source).uid for u in uids}
    tree = read_tree(mat)
    for c in copies.values():
        tree[""].remove(c)
    for u in uids[:-1]:
        tree[copies[parents[u]]].append(copies[u])
    kids = next((k for k in tree.values() if anchor_uid and anchor_uid in k), tree[""])
    kids.insert(kids.index(anchor_uid) + 1 if anchor_uid in kids else len(kids), copies[uid])
    write_tree(mat, tree)
    return copies[uid]


def duplicate_layer(mat, index):
    """Copy a layer, or a folder with everything inside it, just above it (images are copied). Returns the index of the
    copy (a folder's copy is listed after its layers)."""
    top = mat.m3d_layers[index]
    return index_of(mat, clone_layers(mat, top.uid, top.uid))


def below_sibling(layer):
    """The layer directly under this one in the same folder (None: it is the lowest there)."""
    kids = kids_of(layer.id_data, layer.parent)
    k = next(i for i, l in enumerate(kids) if l.uid == layer.uid)
    return kids[k - 1] if k else None


def merge_down(mat, index, default_size):
    """Flatten layer `index` (a folder with its layers is one layer too) into the one below it in the same folder. Per
    channel the two are composited (the upper layer's blend mode over the lower layer) into the lower layer's image; its
    opacity and mask are baked into the pixels. Exact when the lower layer is opaque or the upper one uses Mix; the
    merged layer keeps the lower layer's blend mode of each channel."""
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
        full = size * work_factor(mat)   # (at a working size the layers are merged at full size: the originals keep the detail)
        with muted():
            for ch in chans:
                zero = (np.zeros((full, full, 3), np.float32), np.zeros((full, full), np.float32))
                rgb, alpha = layer_planes(low, ch, full) if has_content(low, ch.id) else zero
                top_rgb, top_alpha = layer_planes(top, ch, full) if has_content(top, ch.id) else zero
                rgb, alpha = over(rgb, alpha, top_rgb, top_alpha, mode_of(top, ch.id))
                e = entry_of(low, ch.id)
                if e.image is None:
                    e.image = make_channel_image(mat, low, ch, size, opaque=False)
                elif max(image_size(e.image)) != size:
                    e.image.scale(size, size)
                put_pixels(e.image, encode(ch, rgb, alpha))
                e.use = True
                if e.blend == 'PASSTHROUGH':   # (the lower layer showed nothing here: the pixels blend as the upper layer's did)
                    e.blend = entry_of(top, ch.id).blend
            for e in low.channels:
                e.opacity = 1.0   # (baked into the pixels)
            low.kind, low.visible, low.use_alpha = 'PAINT', True, True
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
    size = stack_size(mat) or default_size   # (at a working size: the full size, kept as the originals)
    flat = {c: flatten_channel(mat, c, size) for c in chans}
    old = stack_images(mat)
    with muted():
        mat.m3d_layers.clear()
        base = add_layer(mat, 'PAINT', "Base", base=True)
        for ch in CHANNELS:
            e = entry_of(base, ch.id)
            e.use = ch.id in flat
            if ch.id in flat:
                e.image = make_channel_image(mat, base, ch, size // work_factor(mat), opaque=True)
                put_pixels(e.image, flat[ch.id])
        mat.m3d_layer_index = 0
    rebuild_all(mat)
    release(old)


def convert_layer(mat, index, size):
    layer = mat.m3d_layers[index]
    with muted():
        for ch in CHANNELS:
            e = entry_of(layer, ch.id)
            if e.use:
                rgb = fill_planes(layer, ch, size)
                e.image = make_channel_image(mat, layer, ch, size, opaque=True)
                write_pixels(e.image, encode(ch, rgb))
                e.texture = None
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
            return "Put the active layer into a new folder (a folder blends, fades and masks its layers together). Ctrl+G over the layer list"
        return ("Add an empty folder above the active layer (move layers into it with Move Into Folder or the arrows); Ctrl+G over the "
                "layer list puts the active layer into a new one")

    def execute(self, context):
        mat = self.material(context)
        migrate(mat)
        activate(mat, add_folder(mat, anchor_of(mat), self.group))
        return _done(context, mat)


class M3D_OT_layer_duplicate(_ActiveLayerOp, Operator):
    """Duplicate the active layer, or the active folder with its layers (images are copied). Ctrl+D over the layer list"""
    bl_idname = "m3d.layer_duplicate"
    bl_label = "Duplicate Layer"

    def execute(self, context):
        mat = self.material(context)
        index = duplicate_layer(mat, mat.m3d_layer_index)
        with muted():
            mat.m3d_layer_index = index
        return _done(context, mat)


class M3D_OT_layer_remove(_ActiveLayerOp, Operator):
    """Delete the active layer, or the active folder with its layers, and their images (images used elsewhere stay). Delete over
    the layer list"""
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
        freeze_folder(mat, i, new_size(context, mat))
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
        merge_folder(mat, mat.m3d_layer_index, new_size(context, mat))
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
            e.image = make_mask_image(mat, layer, new_size(context, mat), white)
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
            layer.mask_index, layer.paint_mask = len(stack) - 1, True
        return _done(context, mat)


class M3D_OT_layer_mask_clear(_ActiveLayerOp, Operator):
    """Clear the active layer's mask: every effect goes, and a new Paint effect starts white (the layer shows everywhere) or
    black (hidden everywhere)"""
    bl_idname = "m3d.layer_mask_clear"
    bl_label = "Clear Mask"

    fill: EnumProperty(name="Start", default='WHITE', items=(
        ('WHITE', "White (Show All)", "The layer shows everywhere; paint black to hide it"),
        ('BLACK', "Black (Hide All)", "The layer is hidden; paint white to show it")))

    @classmethod
    def poll(cls, context):
        return super().poll(context) and bool(active_layer(mesh_of(context).active_material).mask_stack)

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        white = self.fill == 'WHITE'
        old = paint_effect(layer)
        size = max(image_size(old.image)) if old is not None and old.image is not None else new_size(context, mat)
        images = MK.owned_images(layer)
        with muted():
            layer.mask_stack.clear()
            e = add_effect(layer, 'PAINT', white=white)
            e.image = make_mask_image(mat, layer, size, white)
            layer.mask_index, layer.paint_mask = 0, True
        rebuild_all(mat)
        release(images)
        return _done(context, mat)


_mask_clip = {"mat": "", "uid": ""}   # the layer Copy Mask took the mask of: the name of its material and its uid


def clip_mask():
    """(material, layer) whose mask the mask clipboard holds, None when there is none (or the layer or its mask went since)."""
    mat = bpy.data.materials.get(_mask_clip["mat"])
    layer = layer_by_uid(mat, _mask_clip["uid"]) if mat is not None and _mask_clip["uid"] else None
    return (mat, layer) if layer is not None and layer.mask_stack else None


class M3D_OT_layer_mask_copy(_ActiveLayerOp, Operator):
    """Copy the active layer's mask (all its effects) to the mask clipboard: Paste Mask puts a copy on a layer, also in another
    material"""
    bl_idname = "m3d.layer_mask_copy"
    bl_label = "Copy Mask"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return super().poll(context) and bool(active_layer(mesh_of(context).active_material).mask_stack)

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        _mask_clip.update(mat=mat.name, uid=layer.uid)
        self.report({'INFO'}, "Copied the mask of %s: Paste Mask puts it on the active layer" % layer.name)
        return {'FINISHED'}


class M3D_OT_layer_mask_paste(_ActiveLayerOp, Operator):
    """Put a copy of the copied mask on the active layer, in place of its own mask (the copy has its own paint images)"""
    bl_idname = "m3d.layer_mask_paste"
    bl_label = "Paste Mask"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and clip_mask() is not None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        src_mat, src = clip_mask()
        if src.uid == layer.uid and src_mat == mat:
            self.report({'WARNING'}, "Pick another layer to paste the mask on")
            return {'CANCELLED'}
        images = MK.owned_images(layer)
        with muted():
            layer.mask_stack.clear()
            copy_mask(mat, src, layer)
            layer.use_mask = layer.paint_mask = True
        rebuild_all(mat)
        release(images)
        return _done(context, mat)


class M3D_OT_layer_paint_mask(_ActiveLayerOp, Operator):
    """Switch the active layer between its content and its mask: what strokes paint and Properties shows (a click on the
    layer's thumbnail or mask thumbnail does the same). A mask without a Paint effect gets one (white)"""
    bl_idname = "m3d.layer_paint_mask"
    bl_label = "Switch Layer / Mask"

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        to_mask = not mask_active(layer)
        if to_mask and paint_effect(layer) is None:
            e = add_effect(layer, 'PAINT')
            with muted():
                e.image = make_mask_image(mat, layer, new_size(context, mat), True)
                place_effect(layer)
        with muted():
            layer.paint_mask = to_mask
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
                e.image = make_mask_image(mat, layer, new_size(context, mat), white)
            layer.paint_mask = True   # (the mask is selected: Properties shows the new effect)
            for key, image in images.items():
                assign_map(e, key, image)
            if self.kind == 'COLORID':   # (the first colour of the ID map to start with)
                e.color = next(iter(MK.id_colors(e.image).values()), tuple(e.color))
            place_effect(layer)
        return _done(context, mat)


class M3D_OT_mask_effect_remove(_ActiveLayerOp, Operator):
    """Remove the selected mask effect (a Paint effect's image is deleted unless something else uses it)"""
    bl_idname = "m3d.mask_effect_remove"
    bl_label = "Remove Mask Effect"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'}, description="Effect of the list (-1: the selected one)")

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_effect(active_layer(mesh_of(context).active_material)) is not None

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        i = layer.mask_index if self.index < 0 else self.index
        if not 0 <= i < len(layer.mask_stack):
            return {'CANCELLED'}
        e = layer.mask_stack[i]
        images = [e.image] if e.kind in MK.OWNED and e.image is not None else []
        with muted():
            layer.mask_stack.remove(i)
            layer.mask_index = max(0, min(i, len(layer.mask_stack) - 1))
            if not layer.mask_stack:
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
        with muted():
            e = layer.mask_stack.add()
            # (after the add: growing a collection can move its items, so one taken before it would point at freed memory)
            src = layer.mask_stack[i]
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


class M3D_OT_mask_id_pick(_ActiveLayerOp, Operator):
    """Use this colour of the ID map for the selected Color ID effect"""
    bl_idname = "m3d.mask_id_pick"
    bl_label = "Pick ID Colour"

    name: StringProperty(name="Name", description="The material or mesh of the ID map")

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        e = active_effect(active_layer(mesh_of(context).active_material))
        return e is not None and e.kind == 'COLORID'

    def execute(self, context):
        mat = self.material(context)
        e = active_effect(active_layer(mat))
        color = MK.id_colors(e.image).get(self.name)
        if color is None:
            return {'CANCELLED'}
        e.color = color
        return _done(context, mat)


class M3D_OT_mask_rebake(_ActiveLayerOp, Operator):
    """Bake the maps the mask effects read again (Edges, Cavity, Top-down, Thickness, Noise in Object space), at the
    resolution of the Bake tab. Use it after the mesh or the bake settings changed"""
    bl_idname = "m3d.mask_rebake"
    bl_label = "Rebake Mesh Maps"
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
        merge_down(mat, mat.m3d_layer_index, new_size(context, mat))
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
        flatten_all(mat, new_size(context, mat))
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
        convert_layer(mat, mat.m3d_layer_index, new_size(context, mat))
        return _done(context, mat)


class M3D_OT_layer_fill_reset(_ActiveLayerOp, Operator):
    """Put the Tiling, Rotation and Offset of the active fill layer's textures back to their start"""
    bl_idname = "m3d.layer_fill_reset"
    bl_label = "Reset UV Transform"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and active_layer(mesh_of(context).active_material).kind == 'FILL'

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        with muted():
            layer.uv_tiling, layer.uv_rotation, layer.uv_offset = (1.0, 1.0), 0.0, (0.0, 0.0)
        return _done(context, mat)


# -----------------------------------------------------------------------------
# Picking parts of a row, the clipboard, a mask from an image, the right-click commands

class M3D_OT_layer_pick(_LayerOp, Operator):
    """Select a layer of the list with its content (its thumbnail: strokes paint the layer, Properties shows it); with `part`
    MASK with its mask (strokes paint the mask, Properties shows it), with EFFECT one of the effects of its mask"""
    bl_idname = "m3d.layer_pick"
    bl_label = "Select"
    bl_options = {'INTERNAL', 'UNDO'}

    part: EnumProperty(items=(('LAYER', "Layer", ""), ('MASK', "Mask", ""), ('EFFECT', "Effect", "")), default='LAYER',
                       options={'SKIP_SAVE'})
    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'}, description="Layer of the list (-1: the active one)")
    effect: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'}, description="Effect of the mask")
    action: EnumProperty(items=(('PICK', "Select", ""), ('SHOW', "Show Mask", ""), ('TOGGLE', "Mask On / Off", "")),
                         default='PICK', options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def description(cls, _context, props):
        if props.part == 'MASK':
            return ("Select the layer's mask: strokes paint it, Properties shows it. Alt+click also shows the mask on its own "
                    "(Show Mask), Shift+click switches it off and on (Use Mask), right-click opens the mask's commands")
        if props.part == 'EFFECT':
            return "Select this effect of the mask: Properties shows it"
        return "Select the layer: strokes paint it, Properties shows its settings"

    def invoke(self, context, event):
        if self.part == 'MASK' and self.action == 'PICK' and (event.alt or event.shift):
            self.action = 'SHOW' if event.alt else 'TOGGLE'
        return self.execute(context)

    def execute(self, context):
        mat = self.material(context)
        i = mat.m3d_layer_index if self.index < 0 else self.index
        if not 0 <= i < len(mat.m3d_layers):
            return {'CANCELLED'}
        layer = mat.m3d_layers[i]
        with muted():   # (one refresh below)
            mat.m3d_layer_index = i
            layer.paint_mask = self.part != 'LAYER' and bool(layer.mask_stack)
            if self.part == 'EFFECT' and 0 <= self.effect < len(layer.mask_stack):
                layer.mask_index = self.effect
            if self.action == 'TOGGLE' and layer.mask_stack:
                layer.use_mask = not layer.use_mask
        if self.action == 'SHOW':
            mat.m3d_show_mask = not mat.m3d_show_mask
        refresh(context, mat)
        return {'FINISHED'}


_clip = {"mat": "", "uid": "", "cut": False}   # the layer Copy / Cut took: the name of its material and its uid


def clip_layer():
    """(material, layer) the clipboard holds, None when there is none (or it was deleted since)."""
    mat = bpy.data.materials.get(_clip["mat"])
    layer = layer_by_uid(mat, _clip["uid"]) if mat is not None and _clip["uid"] else None
    return (mat, layer) if layer is not None else None


class _ClipOp(_ActiveLayerOp):
    """Copy and Cut: the active layer (a folder with its layers) goes to the layer clipboard."""
    bl_options = {'INTERNAL'}
    cut = False

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        _clip.update(mat=mat.name, uid=layer.uid, cut=self.cut)
        self.report({'INFO'}, "%s %s: Paste puts it above the active layer" % ("Cut" if self.cut else "Copied", layer.name))
        return {'FINISHED'}


class M3D_OT_layer_copy(_ClipOp, Operator):
    """Copy the active layer (a folder with its layers) to the layer clipboard: Paste adds a copy above the active layer, also
    in another material"""
    bl_idname = "m3d.layer_copy"
    bl_label = "Copy Layer"


class M3D_OT_layer_cut(_ClipOp, Operator):
    """Cut the active layer (a folder with its layers): Paste moves it above the active layer, also to another material"""
    bl_idname = "m3d.layer_cut"
    bl_label = "Cut Layer"
    cut = True


class M3D_OT_layer_paste(_LayerOp, Operator):
    """Paste the copied layer (a folder with its layers) above the active layer: a copy with its own images, or after Cut
    the layer itself"""
    bl_idname = "m3d.layer_paste"
    bl_label = "Paste Layer"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and clip_layer() is not None

    def execute(self, context):
        mat = self.material(context)
        src_mat, src = clip_layer()
        migrate(mat)
        anchor, uid = anchor_of(mat), src.uid
        if _clip["cut"] and src_mat == mat:   # a move
            if anchor in {l.uid for l in subtree(src)}:
                self.report({'WARNING'}, "Pick another layer to paste above")
                return {'CANCELLED'}
            place_above(mat, uid, anchor)
        else:
            uid = clone_layers(mat, uid, anchor, source=src_mat)
            if _clip["cut"]:   # (another material: the original goes)
                delete_layer(src_mat, index_of(src_mat, src.uid))
        if _clip["cut"]:
            _clip.update(mat="", uid="", cut=False)
        activate(mat, uid)
        return _done(context, mat)


class M3D_OT_layer_mask_image(_ActiveLayerOp, Operator):
    """Add a mask made from an image file: its brightness is the mask (white shows the layer, black hides it). It is a
    Paint effect, so it can be painted"""
    bl_idname = "m3d.layer_mask_image"
    bl_label = "Add Image Mask"

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_image: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        mat = self.material(context)
        layer = active_layer(mat)
        try:
            src = bpy.data.images.load(self.filepath, check_existing=False)
        except RuntimeError as err:
            self.report({'ERROR'}, "Can't read the image: %s" % str(err).strip())
            return {'CANCELLED'}
        try:
            w, h = src.size
            if not w or not h:
                self.report({'ERROR'}, "The image is empty")
                return {'CANCELLED'}
            px = np.empty(len(src.pixels), np.float32)
            src.pixels.foreach_get(px)
        finally:
            bpy.data.images.remove(src)
        image = bpy.data.images.new(image_name(mat, layer, "Mask"), w, h, alpha=False, is_data=True)
        px = px.reshape(h, w, 4)
        px[..., 3] = 1.0
        write_pixels(image, px)
        e = add_effect(layer, 'PAINT')
        with muted():
            e.image = image
            layer.paint_mask = True
            place_effect(layer)
        return _done(context, mat)


# What the right-click menu of the list runs on a layer: name -> (operator, its properties, invoke it: it asks first)
LAYER_ACTIONS = {
    'CUT': ("layer_cut", {}, False), 'COPY': ("layer_copy", {}, False), 'PASTE': ("layer_paste", {}, False),
    'DUPLICATE': ("layer_duplicate", {}, False), 'DELETE': ("layer_remove", {}, False),
    'GROUP': ("layer_folder_add", {"group": True}, False), 'MERGE_DOWN': ("layer_merge_down", {}, False),
    'FLATTEN': ("layer_flatten", {}, False), 'FREEZE': ("layer_freeze", {}, False), 'UNFREEZE': ("layer_unfreeze", {}, False),
    'SMART_MATERIAL': ("library_save", {"kind": 'MATERIAL'}, True), 'SMART_MASK': ("library_save", {"kind": 'MASK'}, True),
    'MASK_WHITE': ("layer_mask_add", {"fill": 'WHITE'}, False), 'MASK_BLACK': ("layer_mask_add", {"fill": 'BLACK'}, False),
    'MASK_IMAGE': ("layer_mask_image", {}, True), 'MASK_COLORID': ("mask_effect_add", {"kind": 'COLORID'}, False),
    'EFFECT': ("mask_effect_add", {}, False),
    'MASK_INVERT': ("layer_mask_invert", {}, False), 'MASK_TOGGLE': ("layer_pick", {"part": 'MASK', "action": 'TOGGLE'}, False),
    'MASK_CLEAR_WHITE': ("layer_mask_clear", {"fill": 'WHITE'}, False), 'MASK_CLEAR_BLACK': ("layer_mask_clear", {"fill": 'BLACK'}, False),
    'MASK_COPY': ("layer_mask_copy", {}, False), 'MASK_PASTE': ("layer_mask_paste", {}, False),
    'MASK_REMOVE': ("layer_mask_remove", {}, False), 'EFFECT_REMOVE': ("mask_effect_remove", {}, False),
}


def run_action(op, context, action, uid="", effect="", fill="", pick=-1):
    """Run LAYER_ACTIONS[action] on the layer `uid` (the active one without): that layer is selected first, and the effect of its
    mask `pick` (-1: the selection stays)."""
    mat = _LayerOp.material(context)
    target = layer_by_uid(mat, uid) if uid else None
    if target is not None and target != active_layer(mat):
        mat.m3d_layer_index = index_of(mat, uid)
    layer = active_layer(mat)
    if layer is not None and 0 <= pick < len(layer.mask_stack) and layer.mask_index != pick:
        layer.mask_index = pick
    name, props, invoke = LAYER_ACTIONS[action]
    props = dict(props)
    if action == 'EFFECT':
        props.update(kind=effect, fill=fill or 'WHITE')
    fn = getattr(bpy.ops.m3d, name)
    if not fn.poll():
        op.report({'WARNING'}, "%s is not possible here" % action.replace("_", " ").title())
        return {'CANCELLED'}
    return fn('INVOKE_DEFAULT' if invoke else 'EXEC_DEFAULT', **props)


class M3D_OT_layer_do(_LayerOp, Operator):
    """Run a command of the layer menu on a layer of the list: that layer is selected first (the right-click can be on a
    layer that is not the active one)"""
    bl_idname = "m3d.layer_do"
    bl_label = "Layer Command"
    bl_options = {'INTERNAL', 'UNDO'}

    action: EnumProperty(items=[(k, k.replace("_", " ").title(), "") for k in LAYER_ACTIONS], options={'SKIP_SAVE'})
    uid: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="The layer (empty: the active one)")
    effect: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="The kind of the effect to add (action EFFECT)")
    fill: StringProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="WHITE or BLACK: what a new Paint effect starts as")
    pick: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'}, description="The effect of the layer's mask to select first (-1: leave it)")

    def execute(self, context):
        return run_action(self, context, self.action, self.uid, self.effect, self.fill, self.pick)


class M3D_OT_layer_key(_LayerOp, Operator):
    """The keys over the layer list: Ctrl+C / X / V copy, cut and paste a layer, Ctrl+D duplicates, Ctrl+G groups, Delete
    deletes (only in the Layers tab of the Texture workspace)"""
    bl_idname = "m3d.layer_key"
    bl_label = "Layer Key"
    bl_options = {'INTERNAL', 'UNDO'}

    action: EnumProperty(items=[(k, k.replace("_", " ").title(), "") for k in ('CUT', 'COPY', 'PASTE', 'DUPLICATE', 'DELETE', 'GROUP')],
                         options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        import m3d_workspace as W
        area = context.area
        return (super().poll(context) and area is not None and area.type == 'PROPERTIES'
                and W.current_kind(context) == 'TEXTURE' and W.active_page(context) == "tex_layers")

    def execute(self, context):
        return run_action(self, context, self.action)


# -----------------------------------------------------------------------------
# Thumbnails of the list rows: a preview icon per layer thumbnail (content, mask), small and made on a timer
#
# Drawing only asks for an icon: the first time a thumbnail is a flat placeholder and its pixels are queued. A timer then
# reads the image (once, a few milliseconds each) and writes a THUMB x THUMB preview (2 x 2 samples per pixel, over a
# checker for what is transparent). A thumbnail is made again when what it shows changes (another image, a fill color)
# and when its image was painted: `refresh_thumbs` is told the names of the updated images (depsgraph_post, below).

THUMB = 64            # pixels on a side of a thumbnail
THUMB_TICK = 0.012    # seconds of thumbnail work per timer tick
THUMB_LIMIT = 400     # more previews than that are dropped (and made again when drawn)
_thumbs = {"coll": None, "made": {}, "todo": {}, "timer": False}   # made: key -> spec the pixels are of; todo: key -> spec


def thumb_collection():
    if _thumbs["coll"] is None:
        _thumbs["coll"] = bpy.utils.previews.new()
    return _thumbs["coll"]


def content_spec(layer, ch_id):
    """What the content thumbnail of a layer shows in a channel: ('IMAGE', image name, is a mask) the channel's image (a fill's
    texture), ('COLOR', rgb) a fill's value, or None (a folder, or the layer has nothing in that channel)."""
    if layer.kind == 'FOLDER':
        return None
    e = entry_of(layer, ch_id)
    if not e.use:
        return None
    if layer.kind == 'PAINT':
        return ('IMAGE', e.image.name, False) if e.image is not None else None
    if e.texture is not None:
        return ('IMAGE', e.texture.name, False)
    ch = CHANNEL_BY_ID[ch_id]
    rgb = np.asarray(fill_rgba(layer, ch_id)[:3], np.float32)
    return ('COLOR', tuple(round(float(v), 3) for v in (to_srgb(rgb) if ch.srgb else rgb)))


def mask_spec(layer):
    """The mask thumbnail: the image of the mask's Paint effect, None without one (the row shows the effect's icon)."""
    e = paint_effect(layer)
    return ('IMAGE', e.image.name, True) if e is not None and e.image is not None else None


def thumb_pixels(spec):
    """(THUMB, THUMB, 4) display colors of a thumbnail spec (rows from the bottom, like every image of Blender)."""
    n = THUMB
    if spec[0] == 'COLOR':
        out = np.ones((n, n, 4), np.float32)
        out[..., :3] = np.asarray(spec[1], np.float32)
        return out
    image = bpy.data.images.get(spec[1])
    if image is None:
        return np.full((n, n, 4), 0.25, np.float32)
    if image.source == 'GENERATED' and not image.has_data:   # (nothing painted: reading the pixels would make them)
        small = np.broadcast_to(np.asarray(image.generated_color, np.float32), (n, n, 4))
    else:
        w, h = image.size
        px = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)
        ys, xs = [((np.arange(2 * n) + 0.5) * side / (2 * n)).astype(int) for side in (h, w)]
        small = px[np.ix_(ys, xs)].reshape(n, 2, n, 2, 4).mean(axis=(1, 3))
        if image.is_float and not image.colorspace_settings.is_data:
            small = np.concatenate((to_srgb(small[..., :3]), small[..., 3:]), axis=-1)
    out = np.ones((n, n, 4), np.float32)
    if spec[2]:   # a mask: black and white
        out[..., :3] = small[..., :3]
        return out
    cell = (np.arange(n) // 8) % 2
    checker = np.where(cell[:, None] != cell[None, :], 0.55, 0.35).astype(np.float32)[..., None]
    a = small[..., 3:4]
    out[..., :3] = small[..., :3] * a + checker * (1.0 - a)
    return out


def make_thumb(key, spec):
    thumb = thumb_collection().get(key)
    if thumb is None:
        return
    thumb.image_pixels_float.foreach_set(np.ascontiguousarray(thumb_pixels(spec), np.float32).ravel())
    _thumbs["made"][key] = spec


def redraw_lists():
    wm = bpy.context.window_manager
    for win in wm.windows if wm else ():
        for area in win.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


def _thumb_tick():
    """Timer: make the queued thumbnails, until THUMB_TICK is used up; the rest next time."""
    start, todo = time.perf_counter(), _thumbs["todo"]
    while todo and time.perf_counter() - start < THUMB_TICK:
        key = next(iter(todo))
        make_thumb(key, todo.pop(key))
    redraw_lists()
    if todo:
        return 0.04
    _thumbs["timer"] = False
    if len(thumb_collection()) > THUMB_LIMIT:
        thumbs_clear()
    return None


def queue_thumb(key, spec):
    _thumbs["todo"][key] = spec
    if not _thumbs["timer"] and not bpy.app.background:
        _thumbs["timer"] = True
        bpy.app.timers.register(_thumb_tick, first_interval=0.02)


def thumb_icon(key, spec):
    """Icon id of thumbnail `key` showing `spec` (a flat placeholder until the timer has made the pixels; 0 for spec None)."""
    if spec is None:
        return 0
    coll = thumb_collection()
    thumb = coll.get(key)
    if thumb is None:
        thumb = coll.new(key)
        thumb.image_size = (THUMB, THUMB)
        thumb.image_pixels_float.foreach_set(np.full(THUMB * THUMB * 4, 0.25, np.float32))
        _thumbs["made"].pop(key, None)
    if _thumbs["made"].get(key) != spec and _thumbs["todo"].get(key) != spec:
        queue_thumb(key, spec)
    return thumb.icon_id


def content_thumb(mat, layer, ch_id):
    """(spec, icon id) of the layer's content thumbnail in a channel."""
    spec = content_spec(layer, ch_id)
    return spec, thumb_icon("c:%s:%s:%s" % (mat.name, layer.uid, ch_id), spec)


def mask_thumb(mat, layer):
    """(spec, icon id) of the layer's mask thumbnail."""
    spec = mask_spec(layer)
    return spec, thumb_icon("m:%s:%s" % (mat.name, layer.uid), spec)


def refresh_thumbs(names):
    """Images were painted or changed: make the thumbnails that show them again."""
    for key, spec in list(_thumbs["made"].items()):
        if spec[0] == 'IMAGE' and spec[1] in names:
            queue_thumb(key, spec)


def drain_thumbs():
    """Make every queued thumbnail now (what the timer does a few at a time)."""
    todo = _thumbs["todo"]
    while todo:
        key = next(iter(todo))
        make_thumb(key, todo.pop(key))


def thumbs_clear():
    """Forget every thumbnail (a new file; too many): the next draw makes the ones it needs."""
    if _thumbs["coll"] is not None:
        _thumbs["coll"].clear()
    _thumbs["made"].clear()
    _thumbs["todo"].clear()


# -----------------------------------------------------------------------------
# UI list of the stack (top layer first)

KIND_ICONS = {'PAINT': 'IMAGE_DATA', 'FILL': 'COLOR', 'FOLDER': 'FILE_FOLDER'}
ROW = 1.4           # height of a layer row in widget heights; its thumbnails are as wide (a preview is drawn at the size of its button from 1.5 up: icon sized below)
EFFECT_ROW = 1.0    # height of a row of the mask's effects
EFFECT_SHORT = {**BLEND_SHORT, 'LIGHTEN': "Max", 'DARKEN': "Min"}   # short names of the mask effects' blend modes (their labels differ)


def text_units(text, extra=12):
    """Widget widths a button showing `text` needs: the text and `extra` pixels at UI scale 1 (the padding; more for an arrow)."""
    import blf
    scale = bpy.context.preferences.system.ui_scale or 1.0
    blf.size(0, 11 * scale)
    return (blf.dimensions(0, text)[0] + extra * scale) / (20 * scale)


def look_text(owner, short, blend=True, selected=False):
    """What a row says of a blend mode and opacity: "Mult 50%", "Mult", "50%", only what is not the default ("" for Normal at 100%;
    the `selected` row always has the opacity). `blend` False: a filter, only its opacity."""
    words = [short[owner.blend]] if blend and owner.blend != 'MIX' else []
    if selected or owner.opacity < 0.9995:
        words.append("%d%%" % round(owner.opacity * 100))
    return " ".join(words)


LIST_MARGIN = 3.6   # widget widths of the editor a list row does not have (the panel margins, the arrows beside it, the scroll bar)


def split_factor(context, units, default):
    """The share of a list row its left side gets so that the part at the right is `units` widget widths wide, in a narrow
    editor as in a wide one (`default` without a region to measure)."""
    region = getattr(context, "region", None)
    unit = 20 * (bpy.context.preferences.system.ui_scale or 1.0)
    width = region.width / unit - LIST_MARGIN if region is not None else 0
    return min(max(1.0 - units / width, 0.4), 0.95) if width > units else default


def look_row(context, layout, owner, effect, selected, short=BLEND_SHORT, blend=True):
    """A list row that ends in the blend mode and opacity of `owner` (a layer's channel entry, a mask effect) as a short text
    (look_text): on the selected row a button that opens the blend modes and the opacity (m3d.layer_look), on the others a label,
    only where they are not Normal at 100%. The text takes the width it needs, the row returned (left of it) the rest, so the name
    in it is not cut off. `effect`: the owner is the selected mask effect; `blend` False: a filter (it has no blend mode)."""
    text = look_text(owner, short, blend, selected)
    if not text:
        return layout.row(align=True)
    split = layout.split(factor=split_factor(context, text_units(text, 16 if selected else 8), 0.7), align=True)
    row, look = split.row(align=True), split.row(align=True)
    look.alignment = 'RIGHT'
    if selected:
        look.operator("m3d.layer_look", text=text, translate=False).effect = effect
    else:
        look.label(text=text, translate=False)
    return row


class M3D_OT_layer_look(Operator):
    """Blend mode and opacity of the selected layer in the channel the list shows"""
    bl_idname = "m3d.layer_look"
    bl_label = "Blend Mode and Opacity"
    bl_options = {'INTERNAL'}

    effect: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'}, description="Of the selected mask effect")

    @classmethod
    def description(cls, _context, props):
        return "Blend mode and opacity of the selected mask effect" if props.effect else cls.__doc__

    def invoke(self, context, _event):
        return bpy.ops.wm.call_panel(name="M3D_PT_effect_look" if self.effect else "M3D_PT_layer_look", keep_open=True)


class _LookPanel:
    """The popup of m3d.layer_look (a header region draws no panels, so it shows nowhere else)."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 9

    @classmethod
    def poll(cls, context):
        return cls.owner(context) is not None

    def draw(self, context):
        owner = self.owner(context)
        layout = self.layout
        layout.label(text=self.title(context), translate=False)
        if getattr(owner, "kind", None) not in MK.FILTERS:   # (a filter has no blend mode)
            layout.prop(owner, "blend", text="")
        layout.prop(owner, "opacity_pct", text="Opacity", slider=True)

    @staticmethod
    def layer(context):
        ob = mesh_of(context)
        mat = ob.active_material if ob is not None else None
        return active_layer(mat) if mat is not None else None


class M3D_PT_layer_look(_LookPanel, Panel):
    bl_label = "Blend Mode"

    @classmethod
    def owner(cls, context):
        layer = cls.layer(context)
        return entry_of(layer, layer.id_data.m3d_row_channel) if layer is not None else None

    def title(self, context):
        return "%s: %s" % (self.layer(context).name, CHANNEL_BY_ID[self.layer(context).id_data.m3d_row_channel].label)


class M3D_PT_effect_look(_LookPanel, Panel):
    bl_label = "Effect Blend Mode"

    @classmethod
    def owner(cls, context):
        layer = cls.layer(context)
        return active_effect(layer) if layer is not None else None

    def title(self, context):
        return "Mask effect: " + self.owner(context).name


def thumb_button(layout, selected, **kw):
    """A thumbnail of a row (an m3d.layer_pick button): the selected one is framed (a grey button: it stands out from the blue of
    the selected row, a pressed one did not), the others are flat."""
    return layout.operator("m3d.layer_pick", text="", emboss=selected, **kw)


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

    def draw_item(self, context, layout, _data, item, _icon, _active_data, _active_propname, index):
        """One line: eye, folder arrow, content thumbnail, mask thumbnail, name (it takes the free width), then the blend mode and
        opacity of the channel picked in the panel header (see look_row: a button on the active layer that opens them, elsewhere a
        short text where they are not Normal at 100%). On the active layer the selected thumbnail (content or mask: what strokes paint and Properties
        shows) is framed. A column has the same width in every row (a stack with no folder or no mask has no arrow or mask column),
        so the names line up. The active layer shows the effects of its mask as thin rows under it."""
        mat = item.id_data
        ch_id = mat.m3d_row_channel
        active = index == mat.m3d_layer_index
        on_mask = active and mask_active(item)
        editable = not in_frozen(item)   # (a frozen folder's layers are kept, not editable)
        folders = any(l.kind == 'FOLDER' for l in mat.m3d_layers)
        masks = any(l.mask_stack for l in mat.m3d_layers)
        depth = depth_of(item)
        col = layout.column(align=True)
        line = col.row(align=True)
        line.enabled = editable
        line.scale_y = ROW
        row = look_row(context, line, entry_of(item, ch_id), False, active)
        if depth:
            row.separator(factor=2.0 * depth)
        folder = item.kind == 'FOLDER'
        row.prop(item, "visible", text="", icon='HIDE_OFF' if item.visible else 'HIDE_ON', emboss=False)
        if folder:
            row.prop(item, "expanded", text="", icon='TRIA_DOWN' if item.expanded else 'TRIA_RIGHT', emboss=False)
        elif folders:
            row.label(text="", icon='BLANK1')
        sub = row.row(align=True)
        sub.scale_x = ROW
        spec, icon = content_thumb(mat, item, ch_id)
        shown = active and not on_mask
        if folder:
            op = thumb_button(sub, shown, icon='FILE_FOLDER')
        elif spec is not None:
            op = thumb_button(sub, shown, icon_value=icon)
        else:   # (nothing in this channel)
            sub.active = False
            op = thumb_button(sub, shown, icon=KIND_ICONS[item.kind])
        op.index = index
        if item.mask_stack or masks:
            sub = row.row(align=True)
            sub.scale_x = ROW
            if item.mask_stack:
                sub.active = item.use_mask
                spec, icon = mask_thumb(mat, item)
                if spec is not None:
                    op = thumb_button(sub, on_mask, icon_value=icon)
                else:
                    op = thumb_button(sub, on_mask, icon=MK.KIND_BY_ID[item.mask_stack[len(item.mask_stack) - 1].kind].icon)
                op.part, op.index = 'MASK', index
            else:   # (the place of a mask thumbnail)
                sub.label(text="", icon='BLANK1')
        row.prop(item, "name", text="", emboss=False)
        if folder:
            op = row.operator("m3d.layer_unfreeze" if item.frozen else "m3d.layer_freeze", text="", icon='FREEZE',
                              emboss=item.frozen, depress=item.frozen)
            op.index = index
        if active and item.mask_stack:
            for i in reversed(range(len(item.mask_stack))):
                effect = item.mask_stack[i]
                selected = on_mask and i == item.mask_index
                line = col.row(align=True)
                line.enabled = editable
                line.scale_y = EFFECT_ROW
                sub = look_row(context, line, effect, True, selected, EFFECT_SHORT, effect.kind not in MK.FILTERS)
                if depth:
                    sub.separator(factor=2.0 * depth)
                for _blank in range(2 if folders else 1):   # (under the layer's eye and arrow: the effects are under its thumbnails)
                    sub.label(text="", icon='BLANK1')
                sub.prop(effect, "visible", text="", icon='HIDE_OFF' if effect.visible else 'HIDE_ON', emboss=False)
                name = sub.row(align=True)
                name.alignment = 'LEFT'   # (the text of a button is centered: this makes the button as wide as its text, at the left)
                op = name.operator("m3d.layer_pick", text=effect.name, icon=MK.KIND_BY_ID[effect.kind].icon, emboss=selected,
                                   depress=selected, translate=False)
                op.part, op.index, op.effect = 'EFFECT', index, i


class M3D_UL_mask_effects(UIList):
    def draw_item(self, context, layout, _data, item, _icon, active_data, _active_propname, index):
        """Eye, type icon and name, then the blend mode and opacity as in the layer list (buttons on the selected effect). The name
        is a button that selects the effect (as in the layer list): a right-click on it knows the effect, so the mask menu has Delete
        Effect (the Effect panel renames it)."""
        row = look_row(context, layout, item, True, index == active_data.mask_index, EFFECT_SHORT,
                       item.kind not in MK.FILTERS)
        row.prop(item, "visible", text="", icon='HIDE_OFF' if item.visible else 'HIDE_ON', emboss=False)
        name = row.row(align=True)
        name.alignment = 'LEFT'
        op = name.operator("m3d.layer_pick", text=item.name, icon=MK.KIND_BY_ID[item.kind].icon, emboss=False, translate=False)
        op.part, op.effect = 'EFFECT', index


# -----------------------------------------------------------------------------
# Menus of the Layers panel, and the right-click menu of the list (items of UI_MT_button_context_menu, for this list only: the list item
# menu opens only over the top widget height of a row, and a row is taller than that, with the effect rows under it)

_menu_target = {"uid": "", "pick": -1}   # the layer the menu in progress is for (set when it is drawn; "" is the active one, None
# the operators themselves, no layer command) and the effect of its mask the pointer was on (-1: none)
GENERATORS = ('EDGES', 'CAVITY', 'TOPDOWN', 'THICKNESS', 'NOISE')
FILTER_KINDS = ('BLUR', 'INVERT', 'SHARPEN')


def effect_entry(layout, text, kind, uid, fill='WHITE'):
    """One Add Effect item: the operator for the active layer (`uid` None), or the layer command for the layer `uid`."""
    icon = MK.KIND_BY_ID[kind].icon
    if uid is None:
        op = layout.operator("m3d.mask_effect_add", text=text, icon=icon)
        op.kind, op.fill = kind, fill
    else:
        op = layout.operator("m3d.layer_do", text=text, icon=icon)
        op.action, op.uid, op.effect, op.fill, op.pick = 'EFFECT', uid, kind, fill, _menu_target["pick"]


def action_entry(layout, text, action, uid, icon='NONE'):
    """One item that runs LAYER_ACTIONS[action]: its operator for the active layer (`uid` None), or the layer command for `uid`."""
    if uid is None:
        name, props, _invoke = LAYER_ACTIONS[action]
        op = layout.operator("m3d." + name, text=text, icon=icon)
        for key, value in props.items():
            setattr(op, key, value)
    else:
        op = layout.operator("m3d.layer_do", text=text, icon=icon)
        op.action, op.uid, op.pick = action, uid, _menu_target["pick"]


def draw_effect_items(layout, uid=None, pick=-1):
    """Add to the mask: Fill, Paint, Generator (a menu), Levels, Filter (a menu), Color Selection. The first effect of a layer without
    a mask makes the mask. `pick`: the effect of the mask the new one goes above (-1: the selected one)."""
    _menu_target.update(uid=uid, pick=pick)
    effect_entry(layout, "Add Fill", 'FILL', uid)
    effect_entry(layout, "Add Paint (White)", 'PAINT', uid, 'WHITE')
    effect_entry(layout, "Add Paint (Black)", 'PAINT', uid, 'BLACK')
    layout.menu("M3D_MT_mask_generator", icon='MOD_NOISE')
    effect_entry(layout, "Add Levels", 'LEVELS', uid)
    layout.menu("M3D_MT_mask_filter", icon='MOD_SMOOTH')
    effect_entry(layout, "Add Color Selection", 'COLORID', uid)


def draw_mask_items(layout, uid=None):
    """Add Mask: white, black, from an image."""
    if uid is None:
        layout.operator("m3d.layer_mask_add", text="White Mask", icon='ADD').fill = 'WHITE'
        layout.operator("m3d.layer_mask_add", text="Black Mask", icon='ADD').fill = 'BLACK'
        layout.operator("m3d.layer_mask_image", text="Image Mask...", icon='IMAGE_DATA')
        return
    for text, action, icon in (("White Mask", 'MASK_WHITE', 'ADD'), ("Black Mask", 'MASK_BLACK', 'ADD'),
                               ("Image Mask...", 'MASK_IMAGE', 'IMAGE_DATA')):
        action_entry(layout, text, action, uid, icon)


def draw_mask_menu(layout, uid=None, pick=-1):
    """The commands of a mask (the menu of its thumbnail, of its effect rows and of the Mask panel): the Add items, Delete Effect
    (on an effect), then Invert, Toggle, Clear (a menu), Copy, Paste, Create Smart Mask and Remove."""
    draw_effect_items(layout, uid, pick)
    if pick >= 0:
        action_entry(layout, "Delete Effect", 'EFFECT_REMOVE', uid, 'X')
    layout.separator()
    action_entry(layout, "Invert Mask", 'MASK_INVERT', uid, 'ARROW_LEFTRIGHT')
    action_entry(layout, "Toggle Mask", 'MASK_TOGGLE', uid, 'HIDE_OFF')
    layout.menu("M3D_MT_mask_clear", icon='LOOP_BACK')
    layout.separator()
    action_entry(layout, "Copy Mask", 'MASK_COPY', uid, 'COPYDOWN')
    action_entry(layout, "Paste Mask", 'MASK_PASTE', uid, 'PASTEFLIPDOWN')
    action_entry(layout, "Create Smart Mask", 'SMART_MASK', uid, 'MOD_MASK')
    layout.separator()
    action_entry(layout, "Remove Mask", 'MASK_REMOVE', uid, 'TRASH')


class M3D_MT_mask_generator(Menu):
    bl_label = "Add Generator"

    def draw(self, _context):
        for kind in GENERATORS:
            effect_entry(self.layout, MK.KIND_BY_ID[kind].label, kind, _menu_target["uid"])


class M3D_MT_mask_filter(Menu):
    bl_label = "Add Filter"

    def draw(self, _context):
        for kind in FILTER_KINDS:
            effect_entry(self.layout, MK.KIND_BY_ID[kind].label, kind, _menu_target["uid"])


class M3D_MT_mask_clear(Menu):
    bl_label = "Clear Mask"

    def draw(self, _context):
        action_entry(self.layout, "White (Show All)", 'MASK_CLEAR_WHITE', _menu_target["uid"])
        action_entry(self.layout, "Black (Hide All)", 'MASK_CLEAR_BLACK', _menu_target["uid"])


class M3D_MT_mask_more(Menu):
    """The commands of the mask: add an effect, invert, switch off, clear, copy, paste, create a smart mask, remove the mask"""
    bl_label = "Mask Commands"

    def draw(self, _context):
        draw_mask_menu(self.layout)


class M3D_MT_layer_effect_add(Menu):
    """Add an effect to the active layer's mask: a fill, paint, a generator, levels, a filter or a color selection (the first one
    makes the mask)"""
    bl_label = "Add Effect"

    def draw(self, _context):
        draw_effect_items(self.layout)


class M3D_MT_layer_mask_add(Menu):
    """Add a white, black or image mask to the active layer (white shows the layer, black hides it), or an effect to its mask"""
    bl_label = "Add Mask"

    def draw(self, _context):
        draw_mask_items(self.layout)
        self.layout.separator()
        draw_effect_items(self.layout)


class M3D_MT_layer_ctx_effect_add(Menu):
    bl_label = "Add Effect"

    def draw(self, _context):
        draw_effect_items(self.layout, _menu_target["uid"])


class M3D_MT_layer_ctx_mask_add(Menu):
    bl_label = "Add Mask"

    def draw(self, _context):
        draw_mask_items(self.layout, _menu_target["uid"])
        self.layout.separator()
        draw_effect_items(self.layout, _menu_target["uid"])


class M3D_MT_layer_more(Menu):
    """Merge Down, Flatten, Group (Ctrl+G), Move In / Out of a folder, Freeze, Convert, Cut / Copy / Paste (Ctrl+X / C / V); the
    keys work with the pointer over the layer list"""
    bl_label = "Layer Commands"

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mat = ob.active_material if ob is not None else None
        layer = active_layer(mat) if mat is not None and principled_of(mat) is not None else None
        layout.operator("m3d.layer_merge_down", icon='TRIA_DOWN_BAR')
        layout.operator("m3d.layer_flatten", icon='IMAGE_DATA')
        layout.separator()
        layout.operator("m3d.layer_folder_add", text="Group", icon='FILE_FOLDER').group = True
        layout.operator_menu_enum("m3d.layer_move_into", "folder", text="Move In", icon='TRIA_RIGHT')
        layout.operator("m3d.layer_move_out", text="Move Out", icon='TRIA_LEFT')
        layout.separator()
        frozen = layer is not None and frozen_root(layer) is not None
        layout.operator("m3d.layer_unfreeze" if frozen else "m3d.layer_freeze", icon='FREEZE')
        layout.operator("m3d.layer_merge_folder", icon='TRIA_DOWN_BAR')
        layout.operator("m3d.layer_convert", icon='IMAGE_DATA')
        layout.separator()
        layout.operator("m3d.layer_cut", text="Cut", icon='PASTEDOWN')
        layout.operator("m3d.layer_copy", text="Copy", icon='COPYDOWN')
        layout.operator("m3d.layer_paste", text="Paste", icon='PASTEFLIPDOWN')


def hovered(context, mat):
    """What a right-click in a list of layers or mask effects was on: (uid of the layer, is it its mask, index of the effect of the
    mask). The button under the pointer tells: a property of the layer, of one of its channels or effects (its data path), or a button
    of the row (its operator's layer, part and effect: the thumbnails). Empty uid: unknown (the active layer is meant)."""
    ptr = getattr(context, "button_pointer", None)
    path = ""
    if ptr is not None:
        try:
            path = ptr.path_from_id()
        except (ValueError, AttributeError, TypeError):
            path = ""
    op = getattr(context, "button_operator", None)
    match = re.search(r"m3d_layers\[(\d+)\]", path)
    index = int(match.group(1)) if match else getattr(op, "index", -1)
    uid = mat.m3d_layers[index].uid if isinstance(index, int) and 0 <= index < len(mat.m3d_layers) else ""
    effect = re.search(r"mask_stack\[(\d+)\]", path)
    if effect:
        return uid, True, int(effect.group(1))
    part = getattr(op, "part", 'LAYER')
    return uid, part in {'MASK', 'EFFECT'}, getattr(op, "effect", -1) if part == 'EFFECT' else -1


def hovered_layer(context, mat):
    """uid of the layer a right-click was on (empty: unknown, the active layer is meant)."""
    return hovered(context, mat)[0]


def draw_list_menu(self, context):
    """On a layer: Cut / Copy / Paste, Duplicate, Delete, Group, Add Effect / Mask, Create Smart Material / Mask, Merge Down, Flatten,
    Freeze. On the mask thumbnail, an effect row of the mask or in the Mask panel: the commands of the mask (draw_mask_menu). They
    are the commands of the layer the right-click was on (they select it first)."""
    ui_list = getattr(context, "ui_list", None)
    if ui_list is None or ui_list.bl_idname not in {"M3D_UL_layers", "M3D_UL_mask_effects"}:
        return
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    if mat is None or not len(mat.m3d_layers):
        return
    layout = self.layout
    uid, mask, effect = hovered(context, mat)
    layer = layer_by_uid(mat, uid) if uid else active_layer(mat)
    if layer is None:
        return
    if mask or ui_list.bl_idname == "M3D_UL_mask_effects":
        layout.separator()
        draw_mask_menu(layout, uid, effect)
        return
    _menu_target.update(uid=uid, pick=-1)

    def item(text, action, icon='NONE'):
        action_entry(layout, text, action, uid, icon)

    layout.separator()
    item("Cut", 'CUT', 'PASTEDOWN')
    item("Copy", 'COPY', 'COPYDOWN')
    item("Paste", 'PASTE', 'PASTEFLIPDOWN')
    layout.separator()
    item("Duplicate", 'DUPLICATE', 'DUPLICATE')
    item("Delete", 'DELETE', 'TRASH')
    item("Group", 'GROUP', 'FILE_FOLDER')
    layout.separator()
    layout.menu("M3D_MT_layer_ctx_effect_add", icon='SHADERFX')
    layout.menu("M3D_MT_layer_ctx_mask_add", icon='MOD_MASK')
    layout.separator()
    if layer.kind == 'FOLDER':
        item("Create Smart Material", 'SMART_MATERIAL', 'NODE_MATERIAL')
    if layer.mask_stack:
        item("Create Smart Mask", 'SMART_MASK', 'MOD_MASK')
    item("Merge Down", 'MERGE_DOWN', 'TRIA_DOWN_BAR')
    item("Flatten", 'FLATTEN', 'IMAGE_DATA')
    if layer.kind == 'FOLDER' or in_frozen(layer):
        frozen = frozen_root(layer) is not None
        item("Unfreeze" if frozen else "Freeze", 'UNFREEZE' if frozen else 'FREEZE', 'FREEZE')


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
    M3D_OT_layer_mask_clear,
    M3D_OT_layer_mask_copy,
    M3D_OT_layer_mask_paste,
    M3D_OT_layer_paint_mask,
    M3D_OT_mask_effect_add,
    M3D_OT_mask_effect_remove,
    M3D_OT_mask_effect_move,
    M3D_OT_mask_effect_duplicate,
    M3D_OT_mask_id_pick,
    M3D_OT_mask_rebake,
    M3D_OT_layer_merge_down,
    M3D_OT_layer_flatten,
    M3D_OT_layer_convert,
    M3D_OT_layer_fill_reset,
    M3D_OT_layer_pick,
    M3D_OT_layer_copy,
    M3D_OT_layer_cut,
    M3D_OT_layer_paste,
    M3D_OT_layer_mask_image,
    M3D_OT_layer_do,
    M3D_OT_layer_key,
    M3D_UL_layers,
    M3D_UL_mask_effects,
    M3D_OT_layer_look,
    M3D_PT_layer_look,
    M3D_PT_effect_look,
    M3D_MT_layer_effect_add,
    M3D_MT_layer_mask_add,
    M3D_MT_layer_ctx_effect_add,
    M3D_MT_layer_ctx_mask_add,
    M3D_MT_mask_generator,
    M3D_MT_mask_filter,
    M3D_MT_mask_clear,
    M3D_MT_mask_more,
    M3D_MT_layer_more,
)


@bpy.app.handlers.persistent
def _forget_carry(*_args):
    """load_pre / undo_pre / redo_pre: settings waiting for a chain belong to the data that is about to go."""
    _carry.clear()


@bpy.app.handlers.persistent
def load_post(*_args):
    """Files from before mask stacks and per-channel looks: upgrade their layers right away, so the panels and the nodes agree."""
    for mat in bpy.data.materials:
        if mat.node_tree is not None and any(l.mask is not None or not l.per_channel for l in mat.m3d_layers):
            rebuild_all(mat)
    import m3d_texture
    use_baked_maps(None, [ob for ob in bpy.data.objects if ob.type == 'MESH' and ob.material_slots and m3d_texture.mesh_maps(ob)])
    thumbs_clear()
    sync_list(bpy.context)


def _render_ao(rendering):
    """The AO multiply is for the viewport: a render (F12, an animation) is made without it, and has it again when it is done."""
    _rendering[0] = rendering
    for mat in bpy.data.materials:
        if mat.node_tree is not None and len(mat.m3d_layers) and mat.m3d_baked_ao is not None:
            sync_ao(mat)


@bpy.app.handlers.persistent
def render_pre(*_args):
    _render_ao(True)


@bpy.app.handlers.persistent
def render_end(*_args):
    _render_ao(False)


@bpy.app.handlers.persistent
def undo_post(*_args):
    """Undo and Redo bring back layers and brush material, not the window manager's list of what a stroke paints."""
    sync_list(bpy.context)


_pending = [False]
_changed_images = set()   # names of the images the depsgraph reported updated since the timer last ran


def _follow_strokes():
    """Timer: after something painted an image (a stroke ends with an image update): make the thumbnails of the images again,
    bring the Blur caches up to date."""
    _pending[0] = False
    names = set(_changed_images)
    _changed_images.clear()
    if names:
        refresh_thumbs(names)
        import m3d_texture
        for mat in bpy.data.materials:   # (a stroke changed an image of a texture set: its Material View is out of date)
            if len(mat.m3d_layers) and any(image.name in names for image in stack_images(mat)):
                m3d_texture.preview_dirty(mat.name)
    for mat in bpy.data.materials:
        if mat.node_tree is not None and any(e.kind == 'BLUR' for l in mat.m3d_layers for e in l.mask_stack):
            for layer in live_layers(mat):
                MK.refresh_blurs(layer)


@bpy.app.handlers.persistent
def depsgraph_post(_scene, depsgraph):
    if depsgraph.id_type_updated('IMAGE'):
        _changed_images.update(u.id.name for u in depsgraph.updates if isinstance(u.id, bpy.types.Image))
        if not _pending[0]:
            _pending[0] = True
            bpy.app.timers.register(_follow_strokes, first_interval=0.4)


MK._hook[0] = _changed


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    mat = bpy.types.Material
    mat.m3d_layers = CollectionProperty(type=M3D_Layer)
    mat.m3d_layer_index = IntProperty(name="Active Layer", default=0, min=0, update=_index_changed)
    mat.m3d_channel = EnumProperty(name="Channel", default='BASE_COLOR', items=CHANNEL_ITEMS, update=_changed,
                                   description="Channel shown on its own (C). It is painted too only when the brush "
                                   "material has no channel on, or when it is Normal")
    mat.m3d_show_mask = BoolProperty(name="Show Mask", default=False, update=_show_mask_changed,
                                     description="Show the active layer's mask in the 3D view instead of the material "
                                     "(white shows the layer, black hides it)")
    mat.m3d_show_map = StringProperty(name="Show Map", default="", update=_show_mask_changed,
                                      description="Show a baked map (the name of its image) in the 3D view instead of the material")
    mat.m3d_row_channel = EnumProperty(name="Show Channel", default='BASE_COLOR', items=CHANNEL_ITEMS,
                                       description="The channel the rows of the layer list show: its thumbnails, blend modes "
                                       "and opacities (what the layers do in the other channels is not changed)")
    mat.m3d_off = StringProperty(description="Channels removed from the texture set, separated by | (their layer images are kept)")
    mat.m3d_depth = StringProperty(description="Channels whose images are 16 bit float, separated by | (the others are 8 bit)")
    mat.m3d_size = IntProperty(name="Size", default=0, min=0, description="Side of the texture set's images (0: not chosen: new images "
                               "take the size of the Texture settings)")
    mat.m3d_baked_normal = PointerProperty(type=bpy.types.Image, name="Baked Normal", description="The baked normal map the shader of the "
                                           "texture set uses as its base normal (the mesh's Normal mesh map)")
    mat.m3d_work = EnumProperty(name="Working Size", default='1', items=WORK_ITEMS,
                                description="Paint the texture set's images at a share of its size: less memory and faster strokes; "
                                            "Export and Bake still write the full size (m3d.tex_working_size changes it)")
    mat.m3d_baked_position = PointerProperty(type=bpy.types.Image, name="Baked Position", description="The baked Position map "
                                             "tri-planar fills project with (link_maps)")
    mat.m3d_baked_worldnormal = PointerProperty(type=bpy.types.Image, name="Baked World Normal", description="The baked World Normal "
                                                "map tri-planar fills blend with (link_maps)")
    mat.m3d_baked_ao = PointerProperty(type=bpy.types.Image, name="Baked AO", description="The baked AO map that darkens the Base Color "
                                       "in the viewport (the mesh's AO mesh map)")
    mat.m3d_unlit = BoolProperty(name="Unlit", default=False, update=_show_mask_changed,
                                 description="Show the Base Color flat, without lighting (the viewport type Unlit)")
    bpy.types.UI_MT_button_context_menu.prepend(draw_list_menu)
    bpy.app.handlers.load_post.append(load_post)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        handlers.append(_forget_carry)
    bpy.app.handlers.undo_post.append(undo_post)
    bpy.app.handlers.redo_post.append(undo_post)
    bpy.app.handlers.depsgraph_update_post.append(depsgraph_post)
    bpy.app.handlers.render_pre.append(render_pre)
    for handlers in (bpy.app.handlers.render_post, bpy.app.handlers.render_cancel):
        handlers.append(render_end)


def unregister():
    for handlers in (bpy.app.handlers.render_cancel, bpy.app.handlers.render_post):
        handlers.remove(render_end)
    bpy.app.handlers.render_pre.remove(render_pre)
    bpy.app.handlers.depsgraph_update_post.remove(depsgraph_post)
    bpy.app.handlers.redo_post.remove(undo_post)
    bpy.app.handlers.undo_post.remove(undo_post)
    bpy.app.handlers.load_post.remove(load_post)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if _forget_carry in handlers:
            handlers.remove(_forget_carry)
    bpy.types.UI_MT_button_context_menu.remove(draw_list_menu)
    del bpy.types.Material.m3d_unlit, bpy.types.Material.m3d_baked_ao, bpy.types.Material.m3d_baked_normal
    del bpy.types.Material.m3d_baked_position, bpy.types.Material.m3d_baked_worldnormal, bpy.types.Material.m3d_work
    del bpy.types.Material.m3d_size, bpy.types.Material.m3d_depth, bpy.types.Material.m3d_off
    thumbs_clear()
    if _thumbs["coll"] is not None:
        bpy.utils.previews.remove(_thumbs["coll"])
        _thumbs["coll"] = None
    del bpy.types.Material.m3d_row_channel, bpy.types.Material.m3d_show_map, bpy.types.Material.m3d_show_mask, bpy.types.Material.m3d_channel, bpy.types.Material.m3d_layer_index
    del bpy.types.Material.m3d_layers
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
