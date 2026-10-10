# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Mask stack of a paint layer (Texture workspace, F4) for Maelstrom3D: the effect data, the node groups the shader
side is made of, and the numpy math that flattens a mask exactly like those nodes compute it.

A layer's mask is a stack of effects combined from the bottom up, starting from white (so an empty stack hides
nothing). Sources are Paint (an image you paint), Fill (a flat value) and the generators (Edges, Cavity, Top-down,
Thickness, Color ID, Noise: they read maps baked from the mesh, or noise); filters (Levels, Blur, Invert, Sharpen) change
everything below them. Every effect has a visible toggle, an opacity and (sources) a blend mode: the result below
and the effect's value go through one Mix node (factor = opacity), so with opacity 0 an effect does nothing.

The node side (m3d_layers.py builds the nodes from the stack) is one node group per effect type, made once per file;
a value edit only sets node values. The numpy side (`stack_value`) mirrors every node. The pieces that are not plain
math: the Noise Texture node is ported to numpy (Cycles' Perlin noise, bit for bit), and Blur is a numpy blur of
everything below it, kept in an image the nodes sample (see `refresh_blurs`).
"""

import uuid
from collections import namedtuple
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import PropertyGroup

# -----------------------------------------------------------------------------
# Pixels

LUMA = np.array([0.2126391, 0.7151691, 0.0721928], np.float32)   # The nodes' colour to value conversion
# (Rec.709 of the default colour config; measured against a Cycles bake, error 1e-7).


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


_muted = [0]


@contextmanager
def muted():
    """Property updates do nothing inside (operators edit many properties, then rebuild once)."""
    _muted[0] += 1
    try:
        yield
    finally:
        _muted[0] -= 1


# -----------------------------------------------------------------------------
# Effect types

Kind = namedtuple("Kind", "id label icon text maps")
# maps: the baked maps the effect reads (m3d_texture.MASK_MAPS), in the order of the effect's image / image2.
KINDS = (
    Kind('PAINT', "Paint", 'BRUSH_DATA', "Pixels you paint with the brush: white shows the layer, black hides it", ()),
    Kind('FILL', "Fill", 'COLOR', "One value over the whole mesh: white shows the layer, black hides it", ()),
    Kind('EDGES', "Edges", 'MOD_BEVEL', "White on convex edges (edge wear), read from the baked Curvature map", ('CURVATURE',)),
    Kind('CAVITY', "Cavity", 'MATSPHERE', "White in crevices (dirt), read from the baked ambient occlusion map", ('AO',)),
    Kind('TOPDOWN', "Top-down", 'ANCHOR_TOP', "White on surfaces that face a direction, fading with height (dust, snow)",
         ('WORLDNORMAL', 'POSITION')),
    Kind('THICKNESS', "Thickness", 'MOD_SOLIDIFY', "White where the mesh is thin, read from the baked Thickness map", ('THICKNESS',)),
    Kind('NOISE', "Noise", 'MOD_NOISE', "Procedural noise", ()),
    Kind('LEVELS', "Levels", 'IPO_EASE_IN_OUT', "Filter: set the black and white points and the midtones of everything below", ()),
    Kind('BLUR', "Blur", 'MOD_SMOOTH', "Filter: soften everything below", ()),
    Kind('INVERT', "Invert", 'ARROW_LEFTRIGHT', "Filter: swap black and white of everything below", ()),
    Kind('SHARPEN', "Sharpen", 'IMAGE_ZDEPTH', "Filter: make the steps between black and white of everything below steeper", ()),
    Kind('COLORID', "Color ID", 'COLOR', "White where the baked ID map has the picked colour: one material, or one mesh, of the high poly", ('ID',)),
)   # (a new kind goes last: the saved value of an enum is its place in the list)
KIND_BY_ID = {k.id: k for k in KINDS}
FILTERS = {'LEVELS', 'BLUR', 'INVERT', 'SHARPEN'}
GROUPED = {'EDGES', 'CAVITY', 'TOPDOWN', 'THICKNESS', 'NOISE', 'LEVELS', 'INVERT', 'SHARPEN', 'COLORID'}   # Kinds with a node group.
OWNED = {'PAINT', 'BLUR'}   # The effect's image is its own (paint pixels, the blur cache); the others read baked maps.

BLENDS = (('MIX', "Normal"), ('MULTIPLY', "Multiply"), ('ADD', "Add"), ('SUBTRACT', "Subtract"), ('LIGHTEN', "Max"),
          ('DARKEN', "Min"))   # Mix node blend types; every one is exact in numpy (BLEND_FUNCTIONS).
BLEND_FUNCTIONS = {
    'MIX': lambda b, s: s,
    'MULTIPLY': lambda b, s: b * s,
    'ADD': lambda b, s: b + s,
    'SUBTRACT': lambda b, s: b - s,
    'LIGHTEN': np.maximum,
    'DARKEN': np.minimum,
}
# kind -> (property, label): what the Mask panel shows for the selected effect
PARAM_UI = {
    'FILL': (("value", "Value"),),
    'EDGES': (("amount", "Amount"), ("softness", "Softness"), ("invert", "Invert")),
    'CAVITY': (("amount", "Amount"), ("contrast", "Contrast"), ("invert", "Invert")),
    'TOPDOWN': (("direction", "Direction"), ("offset", "Offset"), ("softness", "Softness"),
                ("height_falloff", "Height Falloff")),
    'THICKNESS': (("amount", "Amount"), ("contrast", "Contrast"), ("invert", "Invert")),
    'COLORID': (("color", "Color"), ("tolerance", "Tolerance")),
    'NOISE': (("space", "Space"), ("scale", "Scale"), ("detail", "Detail"), ("noise_contrast", "Contrast"),
              ("seed", "Seed")),
    'LEVELS': (("black_in", "Black In"), ("white_in", "White In"), ("gamma", "Gamma"), ("black_out", "Black Out"),
               ("white_out", "White Out")),
    'BLUR': (("amount", "Blur"),),
    'SHARPEN': (("amount", "Amount"),),
}
OVERRIDES = {'TOPDOWN': {"softness": 0.5}, 'BLUR': {"amount": 0.25}}   # Starting values that differ from the property defaults.

MAP_LABELS = {'CURVATURE': "Curvature", 'AO': "AO", 'POSITION': "Position", 'THICKNESS': "Thickness",
              'WORLDNORMAL': "WorldNormal", 'ID': "ID"}   # Baked maps: the image of mesh `Cube` is named Cube_<label>.

_hook = [None]   # Set by m3d_layers: the property update (rebuild the nodes, aim the brush).


def _changed(self, context):
    if _hook[0] is not None:
        _hook[0](self, context)


class M3D_MaskEffect(PropertyGroup):
    """One effect of a layer's mask stack."""
    uid: StringProperty(description="Names the effect's nodes")
    kind: EnumProperty(name="Type", default='PAINT', items=[(k.id, k.label, k.text) for k in KINDS])
    name: StringProperty(name="Name", default="Effect", update=_changed)
    visible: BoolProperty(name="Visible", default=True, update=_changed)
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_changed,
                           description="How strongly the effect applies (0: it does nothing)")
    blend: EnumProperty(name="Blend", default='MIX', items=[(k, label, "") for k, label in BLENDS], update=_changed,
                        description="How the effect combines with the result below it")
    image: PointerProperty(type=bpy.types.Image, update=_changed)    # Paint pixels, the blur cache, or the first baked map.
    image2: PointerProperty(type=bpy.types.Image, update=_changed)   # The second baked map (Top-down: Position).
    value: FloatProperty(name="Value", min=0.0, max=1.0, default=0.0, subtype='FACTOR', update=_changed,
                         description="0 hides the layer, 1 shows it")
    amount: FloatProperty(name="Amount", min=0.0, max=1.0, default=0.5, subtype='FACTOR', update=_changed,
                          description="Edges, Cavity, Thickness: how much of the map is picked up. Blur: how wide (a share "
                          "of the image). Sharpen: how steep")
    softness: FloatProperty(name="Softness", min=0.01, max=2.0, default=0.15, update=_changed,
                            description="How gradual the step between black and white is")
    contrast: FloatProperty(name="Contrast", min=0.0, max=1.0, default=0.5, subtype='FACTOR', update=_changed,
                            description="How sharp the step between black and white is")
    invert: BoolProperty(name="Invert", default=False, update=_changed, description="Swap black and white")
    color: FloatVectorProperty(name="Color", size=3, subtype='COLOR', min=0.0, max=1.0, default=(1.0, 0.0, 0.0), update=_changed,
                               description="The colour of the ID map that shows the layer")
    tolerance: FloatProperty(name="Tolerance", min=0.0, max=1.0, default=0.1, subtype='FACTOR', update=_changed,
                             description="How far from the colour a colour of the ID map may be and still count: it shows fully up to half of "
                             "this, and not at all beyond it")
    direction: FloatVectorProperty(name="Direction", size=3, subtype='DIRECTION', default=(0.0, 0.0, 1.0), update=_changed,
                                   description="Surfaces facing this world direction are white (default: up)")
    offset: FloatProperty(name="Offset", min=-1.0, max=1.0, default=0.0, update=_changed,
                          description="Higher: surfaces turned further from the direction are covered too")
    height_falloff: FloatProperty(name="Height Falloff", min=0.0, max=2.0, default=0.3, update=_changed,
                                  description="Fade out toward the bottom of the mesh (0: only the facing counts)")
    scale: FloatProperty(name="Scale", min=0.01, soft_max=100.0, default=6.0, update=_changed,
                         description="Size of the noise: larger is finer")
    detail: FloatProperty(name="Detail", min=0.0, max=8.0, default=3.0, update=_changed,
                          description="How many layers of finer noise are added")
    noise_contrast: FloatProperty(name="Contrast", min=0.0, soft_max=20.0, default=3.0, update=_changed,
                                  description="Spread the noise away from grey (1: as it is)")
    seed: IntProperty(name="Seed", min=0, soft_max=100, default=0, update=_changed,
                      description="Another pattern with the same settings")
    space: EnumProperty(name="Space", default='UV', update=_changed, items=(
        ('UV', "UV", "The noise follows the UV map (it breaks where UV islands meet)"),
        ('OBJECT', "Object", "The noise follows the mesh's 3D position (no breaks; needs the baked Position map)")))
    black_in: FloatProperty(name="Black In", min=0.0, max=1.0, default=0.0, subtype='FACTOR', update=_changed,
                            description="Input value that becomes the output black")
    white_in: FloatProperty(name="White In", min=0.0, max=1.0, default=1.0, subtype='FACTOR', update=_changed,
                            description="Input value that becomes the output white")
    gamma: FloatProperty(name="Gamma", min=0.1, max=10.0, default=1.0, update=_changed,
                         description="Midtones: above 1 brightens, below 1 darkens")
    black_out: FloatProperty(name="Black Out", min=0.0, max=1.0, default=0.0, subtype='FACTOR', update=_changed,
                             description="The darkest the result can be")
    white_out: FloatProperty(name="White Out", min=0.0, max=1.0, default=1.0, subtype='FACTOR', update=_changed,
                             description="The brightest the result can be")


PARAM_PROPS = ("value", "amount", "softness", "contrast", "invert", "direction", "offset", "height_falloff", "scale",
               "detail", "noise_contrast", "seed", "space", "black_in", "white_in", "gamma", "black_out", "white_out", "color",
               "tolerance")


def needed_maps(e):
    """The baked maps an effect reads, in the order of its image / image2."""
    if e.kind == 'NOISE':
        return ('POSITION',) if e.space == 'OBJECT' else ()
    return KIND_BY_ID[e.kind].maps


def map_images(e):
    return dict(zip(needed_maps(e), (e.image, e.image2)))


def missing_maps(layer):
    """[(effect, map key)] the stack needs and does not have."""
    return [(e, key) for e in layer.mask_stack for key, image in map_images(e).items() if image is None]


def id_colors(image):
    """{label: colour} of an ID map (the bake keeps them with the image), in the order they were baked."""
    ids = image.get("m3d_ids") if image is not None else None
    return {name: tuple(color) for name, color in ids.to_dict().items()} if ids else {}


def owned_images(layer):
    return [e.image for e in layer.mask_stack if e.kind in OWNED and e.image is not None]


def unique_name(layer, base):
    names = {e.name for e in layer.mask_stack}
    return next(n for n in (base, *("%s %d" % (base, i) for i in range(2, 10000))) if n not in names)


def params(e):
    """What the node group of an effect takes (socket name -> value); numpy reads the same numbers."""
    k = e.kind
    if k == 'EDGES':
        return {"Amount": e.amount, "Softness": e.softness, "Invert": float(e.invert)}
    if k in {'CAVITY', 'THICKNESS'}:
        return {"Amount": e.amount, "Contrast": e.contrast, "Invert": float(e.invert)}
    if k == 'TOPDOWN':
        d = np.array(e.direction, np.float32)
        length = float(np.sqrt((d * d).sum()))
        d = d / length if length > 1e-6 else np.array([0.0, 0.0, 1.0], np.float32)
        return {"Direction": tuple(float(x) for x in d), "Offset": e.offset, "Softness": e.softness,
                "Height Falloff": e.height_falloff}
    if k == 'NOISE':
        return {"Scale": e.scale, "Detail": e.detail, "Contrast": e.noise_contrast,
                "Seed Offset": (e.seed * 13.731, e.seed * 29.177, e.seed * 7.913)}
    if k == 'LEVELS':
        return {"Black In": e.black_in, "White In": max(e.white_in, e.black_in + 0.001), "Gamma": e.gamma,
                "Black Out": e.black_out, "White Out": e.white_out}
    if k == 'SHARPEN':
        return {"Amount": e.amount}
    if k == 'COLORID':
        return {"Color": tuple(float(x) for x in e.color), "Tolerance": max(e.tolerance, 0.001)}
    return {}


# -----------------------------------------------------------------------------
# Node groups: one per effect type, made when first needed and shared by every layer

VERSION = 1
_SOCKET = {'FLOAT': 'NodeSocketFloat', 'VECTOR': 'NodeSocketVector'}


class _Group:
    """The inside of a node group while it is made: the input sockets, math nodes chained by calls, one value out."""

    def __init__(self, name, sockets):
        self.tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        self.tree["m3d_mask"] = VERSION
        for label, kind in sockets:
            self.tree.interface.new_socket(name=label, in_out='INPUT', socket_type=_SOCKET[kind])
        self.tree.interface.new_socket(name="Value", in_out='OUTPUT', socket_type='NodeSocketFloat')
        self.inp = self.tree.nodes.new('NodeGroupInput')
        self.inp.location = (-250, 0)
        self.x = 0

    def __getitem__(self, label):
        return self.inp.outputs[label]

    def node(self, idname, **props):
        node = self.tree.nodes.new(idname)
        node.location = (self.x, 0)
        self.x += 220
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def feed(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, op, *args, clamp=False):
        node = self.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        for socket, value in zip(node.inputs, args):
            self.feed(socket, value)
        return node.outputs[0]

    def vec(self, op, *args):
        """Vector Math: a vector result, or the value of a dot product or a distance."""
        node = self.node('ShaderNodeVectorMath', operation=op)
        for socket, value in zip(node.inputs, args):
            self.feed(socket, value)
        return node.outputs["Value" if op in {'DOT_PRODUCT', 'DISTANCE'} else "Vector"]

    def finish(self, value):
        out = self.node('NodeGroupOutput')
        self.tree.links.new(value, out.inputs[0])
        return self.tree


def _edges():
    # (map - threshold) / softness, the threshold lowering as Amount rises; Invert flips (|v - 1| = 1 - v).
    g = _Group("m3d_mask.edges", (("Map", 'FLOAT'), ("Amount", 'FLOAT'), ("Softness", 'FLOAT'), ("Invert", 'FLOAT')))
    thr = g.math('MULTIPLY_ADD', g["Amount"], -0.45, 0.95)
    v = g.math('DIVIDE', g.math('SUBTRACT', g["Map"], thr), g["Softness"], clamp=True)
    return g.finish(g.math('ABSOLUTE', g.math('SUBTRACT', v, g["Invert"])))


def _dark_to_white(name):
    # (Amount - map) / width: white where the map is darker than Amount; Contrast narrows the width.
    g = _Group(name, (("Map", 'FLOAT'), ("Amount", 'FLOAT'), ("Contrast", 'FLOAT'), ("Invert", 'FLOAT')))
    width = g.math('MULTIPLY_ADD', g["Contrast"], -0.48, 0.5)
    v = g.math('DIVIDE', g.math('SUBTRACT', g["Amount"], g["Map"]), width, clamp=True)
    return g.finish(g.math('ABSOLUTE', g.math('SUBTRACT', v, g["Invert"])))


def _topdown():
    g = _Group("m3d_mask.topdown", (("Normal", 'VECTOR'), ("Position", 'VECTOR'), ("Direction", 'VECTOR'),
                                    ("Offset", 'FLOAT'), ("Softness", 'FLOAT'), ("Height Falloff", 'FLOAT')))
    normal = g.vec('MULTIPLY_ADD', g["Normal"], (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0))   # The map stores n * 0.5 + 0.5.
    facing = g.vec('DOT_PRODUCT', normal, g["Direction"])
    height = g.math('ADD', g.vec('DOT_PRODUCT', g.vec('SUBTRACT', g["Position"], (0.5, 0.5, 0.5)), g["Direction"]),
                    0.5, clamp=True)   # 0 at the bottom of the mesh's bounds, 1 at the top (along the direction)
    score = g.math('MULTIPLY_ADD', g.math('SUBTRACT', height, 1.0), g["Height Falloff"], facing)
    score = g.math('ADD', score, g["Offset"])
    return g.finish(g.math('DIVIDE', score, g["Softness"], clamp=True))


def _noise():
    g = _Group("m3d_mask.noise", (("Vector", 'VECTOR'), ("Scale", 'FLOAT'), ("Detail", 'FLOAT'), ("Contrast", 'FLOAT'),
                                  ("Seed Offset", 'VECTOR')))
    scaled = g.node('ShaderNodeVectorMath', operation='SCALE')
    g.tree.links.new(g["Vector"], scaled.inputs[0])
    g.tree.links.new(g["Scale"], scaled.inputs[3])
    co = g.vec('ADD', scaled.outputs[0], g["Seed Offset"])
    noise = g.node('ShaderNodeTexNoise', noise_dimensions='3D', noise_type='FBM', normalize=True)
    noise.inputs["Scale"].default_value = 1.0
    g.tree.links.new(co, noise.inputs["Vector"])
    g.tree.links.new(g["Detail"], noise.inputs["Detail"])
    spread = g.math('SUBTRACT', noise.outputs["Factor"], 0.5)
    return g.finish(g.math('MULTIPLY_ADD', spread, g["Contrast"], 0.5, clamp=True))


def _levels():
    g = _Group("m3d_mask.levels", (("Value", 'FLOAT'), ("Black In", 'FLOAT'), ("White In", 'FLOAT'), ("Gamma", 'FLOAT'),
                                   ("Black Out", 'FLOAT'), ("White Out", 'FLOAT')))
    t = g.node('ShaderNodeMapRange', clamp=True)
    for socket, label in (("Value", "Value"), ("From Min", "Black In"), ("From Max", "White In")):
        g.tree.links.new(g[label], t.inputs[socket])
    t2 = g.math('POWER', t.outputs["Result"], g.math('DIVIDE', 1.0, g["Gamma"]))
    out = g.node('ShaderNodeMapRange', clamp=True)
    g.tree.links.new(t2, out.inputs["Value"])
    g.tree.links.new(g["Black Out"], out.inputs["To Min"])
    g.tree.links.new(g["White Out"], out.inputs["To Max"])
    return g.finish(out.outputs["Result"])


def _invert():
    g = _Group("m3d_mask.invert", (("Value", 'FLOAT'),))
    return g.finish(g.math('SUBTRACT', 1.0, g["Value"], clamp=True))


def _sharpen():
    g = _Group("m3d_mask.sharpen", (("Value", 'FLOAT'), ("Amount", 'FLOAT')))
    gain = g.math('MULTIPLY_ADD', g["Amount"], 9.0, 1.0)
    return g.finish(g.math('MULTIPLY_ADD', g.math('SUBTRACT', g["Value"], 0.5), gain, 0.5, clamp=True))


def _colorid():
    # (Tolerance - distance to the picked colour) / (Tolerance / 2): white at the colour, black from Tolerance away from it.
    g = _Group("m3d_mask.colorid", (("Map", 'VECTOR'), ("Color", 'VECTOR'), ("Tolerance", 'FLOAT')))
    distance = g.vec('DISTANCE', g["Map"], g["Color"])
    return g.finish(g.math('DIVIDE', g.math('SUBTRACT', g["Tolerance"], distance), g.math('MULTIPLY', g["Tolerance"], 0.5), clamp=True))


GROUPS = {'EDGES': _edges, 'CAVITY': lambda: _dark_to_white("m3d_mask.cavity"),
          'THICKNESS': lambda: _dark_to_white("m3d_mask.thickness"), 'TOPDOWN': _topdown, 'NOISE': _noise,
          'LEVELS': _levels, 'INVERT': _invert, 'SHARPEN': _sharpen, 'COLORID': _colorid}


def group_of(kind):
    """The node group of an effect type (made on first use; a file keeps it with the layers that use it)."""
    name = "m3d_mask." + kind.lower()
    return bpy.data.node_groups.get(name) or GROUPS[kind]()


# -----------------------------------------------------------------------------
# Numpy: what the nodes compute

def sample(image, size, rgb=False):
    """A baked map or paint image at `size`: its luminance, or the colors (zeros when there is no image)."""
    if image is None:
        return np.zeros((size, size, 3) if rgb else (size, size), np.float32)
    px = pixels_of(image, size)[..., :3]
    return px if rgb else px @ LUMA


def _clamp(a):
    return np.clip(a, 0.0, 1.0).astype(np.float32)


def _f(x):
    return np.float32(x)


def _rot(x, k):
    return (x << np.uint32(k)) | (x >> np.uint32(32 - k))


def _hash3(x, y, z):
    """Jenkins lookup3 of three integers (Cycles' hash_uint3)."""
    base = np.uint32(0xdeadbeef + (3 << 2) + 13)
    with np.errstate(over='ignore'):
        a, b, c = x + base, y + base, z + base
        c ^= b
        c -= _rot(b, 14)
        a ^= c
        a -= _rot(c, 11)
        b ^= a
        b -= _rot(a, 25)
        c ^= b
        c -= _rot(b, 16)
        a ^= c
        a -= _rot(c, 4)
        b ^= a
        b -= _rot(a, 14)
        c ^= b
        c -= _rot(b, 24)
    return c


def _grad3(h, x, y, z):
    h = h & np.uint32(15)
    u = np.where(h < 8, x, y)
    v = np.where(h < 4, y, np.where((h == 12) | (h == 14), x, z))
    return np.where(h & 1, -u, u) + np.where(h & 2, -v, v)


def _perlin3(x, y, z):
    """Cycles' perlin_3d on float32 arrays."""
    fx, fy, fz = np.floor(x), np.floor(y), np.floor(z)
    ix, iy, iz = (a.astype(np.int32).view(np.uint32) for a in (fx, fy, fz))
    x, y, z = x - fx, y - fy, z - fz
    u, v, w = (t * t * t * (t * (t * _f(6) - _f(15)) + _f(10)) for t in (x, y, z))
    one = np.uint32(1)

    def corner(dx, dy, dz):
        return _grad3(_hash3(ix + (one if dx else 0), iy + (one if dy else 0), iz + (one if dz else 0)),
                      x - dx, y - dy, z - dz)

    def lerp(a, b, t):
        return a * (1 - t) + b * t

    z0 = lerp(lerp(corner(0, 0, 0), corner(1, 0, 0), u), lerp(corner(0, 1, 0), corner(1, 1, 0), u), v)
    z1 = lerp(lerp(corner(0, 0, 1), corner(1, 0, 1), u), lerp(corner(0, 1, 1), corner(1, 1, 1), u), v)
    return lerp(z0, z1, w)


def _snoise3(p):
    p = np.fmod(p, _f(100000)) + _f(0.5) * (np.abs(p) >= 1000000.0)
    return _f(0.9820) * _perlin3(p[..., 0], p[..., 1], p[..., 2])


def noise_fbm(p, detail, roughness=0.5, lacunarity=2.0):
    """The Noise Texture node's Factor (3D, fractal Brownian motion, normalized) at float32 points `p` (..., 3)."""
    fscale, amp, maxamp, total = _f(1), _f(1), _f(0), np.zeros(p.shape[:-1], np.float32)
    for _i in range(int(detail) + 1):
        total = total + _snoise3(fscale * p) * amp
        maxamp = maxamp + amp
        amp, fscale = amp * _f(roughness), fscale * _f(lacunarity)
    rmd = _f(detail - np.floor(detail))
    if rmd != 0:
        more = total + _snoise3(fscale * p) * amp
        a, b = _f(0.5) * total / maxamp + _f(0.5), _f(0.5) * more / (maxamp + amp) + _f(0.5)
        return a * (1 - rmd) + b * rmd
    return _f(0.5) * total / maxamp + _f(0.5)


def object_coords(image, size):
    """Object space position of every texel, from the baked Position map and the bounds / matrix stored with it."""
    rgb = pixels_of(image, size)[..., :3]
    bounds, inverse = image.get("m3d_bounds"), image.get("m3d_inv")
    if bounds is None or inverse is None:
        return rgb
    lo, hi = np.array(bounds[:3], np.float32), np.array(bounds[3:], np.float32)
    m = np.array(inverse, np.float32).reshape(4, 4)
    return ((lo + rgb * (hi - lo)) @ m[:3, :3].T + m[:3, 3]).astype(np.float32)


def noise_value(e, size):
    p = params(e)
    if e.space == 'OBJECT':
        co = object_coords(e.image, size) if e.image is not None else np.zeros((size, size, 3), np.float32)
    else:
        u = (np.arange(size, dtype=np.float32) + _f(0.5)) / _f(size)   # UV at the texel centers: (u, v, 0)
        co = np.zeros((size, size, 3), np.float32)
        co[..., 0], co[..., 1] = u[None, :], u[:, None]
    co = (co * _f(p["Scale"]) + np.array(p["Seed Offset"], np.float32)).astype(np.float32)
    return _clamp((noise_fbm(co, np.float32(p["Detail"])) - _f(0.5)) * _f(p["Contrast"]) + _f(0.5))


def box_blur(a, r, axis):
    """Mean over 2r + 1 texels along `axis` (the edge texel repeats past the border)."""
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis, dtype=np.float64)
    c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
    hi, lo = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis), np.take(c, np.arange(n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def blur(a, amount):
    """A soft blur (three box passes ~ a Gaussian) whose width is `amount` x 4% of the image width."""
    sigma = amount * 0.04 * a.shape[0]
    r = max(int(round((np.sqrt(4 * sigma * sigma + 1) - 1) / 2)), 1 if amount > 0 else 0)
    for _i in range(3 if r else 0):
        a = box_blur(box_blur(a, r, 0), r, 1)
    return a


def generator_value(e, size):
    """A source or generator's value: (size, size) float32, before opacity and blend."""
    k, p = e.kind, params(e)
    if k == 'PAINT':
        return sample(e.image, size)
    if k == 'FILL':
        return np.full((size, size), e.value, np.float32)
    if k == 'EDGES':
        thr = _f(p["Amount"]) * _f(-0.45) + _f(0.95)
        v = _clamp((sample(e.image, size) - thr) / _f(p["Softness"]))
        return np.abs(v - _f(p["Invert"]))
    if k in {'CAVITY', 'THICKNESS'}:
        width = _f(p["Contrast"]) * _f(-0.48) + _f(0.5)
        v = _clamp((_f(p["Amount"]) - sample(e.image, size)) / width)
        return np.abs(v - _f(p["Invert"]))
    if k == 'TOPDOWN':
        d = [_f(x) for x in p["Direction"]]
        n = sample(e.image, size, rgb=True) * _f(2) + _f(-1)
        facing = n[..., 0] * d[0] + n[..., 1] * d[1] + n[..., 2] * d[2]
        q = sample(e.image2, size, rgb=True) - _f(0.5)
        height = _clamp(q[..., 0] * d[0] + q[..., 1] * d[1] + q[..., 2] * d[2] + _f(0.5))
        score = (height - _f(1)) * _f(p["Height Falloff"]) + facing + _f(p["Offset"])
        return _clamp(score / _f(p["Softness"]))
    if k == 'COLORID':
        distance = np.sqrt(((sample(e.image, size, rgb=True) - np.array(p["Color"], np.float32)) ** 2).sum(axis=-1))
        tolerance = _f(p["Tolerance"])
        return _clamp((tolerance - distance) / (tolerance * _f(0.5)))
    if k == 'NOISE':
        return noise_value(e, size)
    raise KeyError(k)


def filter_value(e, below, size):
    """What a filter makes of the result below it (before opacity)."""
    k, p = e.kind, params(e)
    if k == 'INVERT':
        return _clamp(_f(1) - below)
    if k == 'SHARPEN':
        gain = _f(p["Amount"]) * _f(9) + _f(1)
        return _clamp((below - _f(0.5)) * gain + _f(0.5))
    if k == 'LEVELS':
        bi, wi = _f(p["Black In"]), _f(p["White In"])
        t = _clamp((below - bi) / (wi - bi))
        t = np.power(t, _f(1) / _f(p["Gamma"])).astype(np.float32)
        bo, wo = _f(p["Black Out"]), _f(p["White Out"])
        return np.clip(bo + t * (wo - bo), min(bo, wo), max(bo, wo)).astype(np.float32)
    if k == 'BLUR':
        return sample(e.image, size)   # The cache: refresh_blurs keeps it equal to blur(everything below).
    raise KeyError(k)


def stack_value(layer, size, upto=None):
    """The layer's mask (size, size): the stack from the bottom up, starting from white."""
    m = np.ones((size, size), np.float32)
    for e in list(layer.mask_stack)[:upto]:
        o = _f(e.opacity if e.visible else 0.0)
        if e.kind in FILTERS:
            target = filter_value(e, m, size)
        else:
            target = BLEND_FUNCTIONS[e.blend](m, generator_value(e, size))
        m = _clamp(m + o * (target - m))
    return m


# -----------------------------------------------------------------------------
# Blur caches: a Blur effect blurs the stack below it, which the nodes cannot do per pixel, so numpy does it and
# keeps the result in an image (float, one per Blur effect) that the nodes just sample. The image is made again when
# anything below the effect changes (a value, a baked map, brush strokes on a Paint effect below it); the layer
# stack calls `refresh_blurs` whenever it is rebuilt, flattened or exported.

def cache_size(layer, index):
    sides = [max(image_size(e.image)) for e in list(layer.mask_stack)[:index] if e.image is not None and e.kind != 'BLUR']
    return int(min(max(max(sides, default=256), 64), 1024))


def ensure_caches(layer):
    """Give every Blur effect its cache image. True when one was made."""
    made = False
    for i, e in enumerate(layer.mask_stack):
        if e.kind == 'BLUR' and e.image is None:
            size = cache_size(layer, i)
            name = "%s_%s_%s" % (layer.id_data.name, layer.name, e.name)
            image = bpy.data.images.new(name[:60], size, size, alpha=False, float_buffer=True, is_data=True)
            image.use_half_precision = False
            image.generated_color = (1.0, 1.0, 1.0, 1.0)
            with muted():
                e.image = image
            made = True
    return made


def _digest(e):
    """Everything about an effect that changes what it computes (paint pixels included)."""
    values = []
    for name in PARAM_PROPS:
        v = getattr(e, name)
        values += [round(float(x), 6) for x in v] if hasattr(v, "__len__") and not isinstance(v, str) else [v]
    if e.kind == 'PAINT' and e.image is not None:
        px = np.empty(len(e.image.pixels), np.float32)
        e.image.pixels.foreach_get(px)
        image = [e.image.name, float(px.sum(dtype=np.float64))]
    elif e.kind == 'BLUR':
        image = [e.image.get("m3d_fp") if e.image is not None else None]
    else:
        image = [(i.name, i.get("m3d_stamp")) if i is not None else None for i in (e.image, e.image2)]
    return repr((e.kind, e.visible, round(e.opacity, 6), e.blend, values, image))


def refresh_blurs(layer, force=False):
    """Make each Blur effect's cache hold the blur of the stack below it (only when that changed). True when any did."""
    changed, keys = False, []
    last = max((i for i, e in enumerate(layer.mask_stack) if e.kind == 'BLUR'), default=-1)
    for i, e in enumerate(layer.mask_stack):
        if i > last:
            break
        if e.kind == 'BLUR' and e.image is not None:
            fp = repr(keys + [round(e.amount, 6), e.image.name])
            if force or e.image.get("m3d_fp") != fp:
                size = cache_size(layer, i)
                if tuple(e.image.size) != (size, size):
                    e.image.scale(size, size)
                out = np.ones((size, size, 4), np.float32)
                out[..., :3] = blur(stack_value(layer, size, i), e.amount)[..., None]
                write_pixels(e.image, out)
                e.image["m3d_fp"] = fp
                changed = True
        keys.append(_digest(e))
    return changed


def copy_params(src, dst):
    """Copy an effect's settings (not its uid or images)."""
    for prop in src.bl_rna.properties:
        if prop.identifier not in {"rna_type", "uid", "image", "image2"}:
            setattr(dst, prop.identifier, getattr(src, prop.identifier))


def new_uid():
    return uuid.uuid4().hex[:6]


def register():
    pass   # M3D_MaskEffect is registered by m3d_layers (the layer's property needs it first).


def unregister():
    pass
