# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Live primitive inputs: a polygon primitive keeps its creation settings (size, subdivisions) on the object and the
Channel Box shows them under INPUTS. Changing one rebuilds the mesh in place (same Mesh datablock). Editing the mesh
(components, applied modifiers, sculpting) freezes the inputs: they no longer apply and Delete History clears them.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup

# Kind -> (label, the inputs it has, in Channel Box order).
KINDS = {
    'CUBE': ("Cube", ("width", "height", "depth", "sub_width", "sub_height", "sub_depth")),
    'SPHERE': ("Sphere", ("radius", "sub_axis", "sub_height")),
    'CYLINDER': ("Cylinder", ("radius", "height", "sub_axis", "sub_height", "sub_caps")),
    'CONE': ("Cone", ("radius", "height", "sub_axis", "sub_height", "sub_caps")),
    'PLANE': ("Plane", ("width", "height", "sub_width", "sub_height")),
    'TORUS': ("Torus", ("radius", "section_radius", "sub_axis", "sub_height")),
}
LABELS = {
    "width": "Width", "height": "Height", "depth": "Depth", "radius": "Radius", "section_radius": "Section Radius",
    "sub_width": "Subdivisions Width", "sub_height": "Subdivisions Height", "sub_depth": "Subdivisions Depth",
    "sub_axis": "Subdivisions Axis", "sub_caps": "Subdivisions Caps",
}
# Command-line attribute names (`setAttr pCube1.subdivisionsWidth 4`) -> input.
ATTRS = {
    "width": "width", "height": "height", "depth": "depth", "radius": "radius", "sectionRadius": "section_radius",
    "subdivisionsWidth": "sub_width", "subdivisionsHeight": "sub_height", "subdivisionsDepth": "sub_depth",
    "subdivisionsAxis": "sub_axis", "subdivisionsCaps": "sub_caps",
}
# What "Polygon Primitive" makes (the unit cube, a radius 1 sphere, ...).
DEFAULTS = {
    'CUBE': dict(width=1, height=1, depth=1, sub_width=1, sub_height=1, sub_depth=1),
    'SPHERE': dict(radius=1, sub_axis=20, sub_height=20),
    'CYLINDER': dict(radius=1, height=2, sub_axis=20, sub_height=1, sub_caps=1),
    'CONE': dict(radius=1, height=2, sub_axis=20, sub_height=1, sub_caps=1),
    'PLANE': dict(width=1, height=1, sub_width=1, sub_height=1),
    'TORUS': dict(radius=1, section_radius=0.5, sub_axis=48, sub_height=12),
}
SUB_MAX = 200   # Keeps a typo (or a slider drag) from freezing the app.

_quiet = False   # Set while several inputs change at once: one rebuild at the end.


def signature(mesh):
    """Counts and a hash of the positions and face corners: changes when the mesh is edited, not when it is rebuilt."""
    import hashlib

    import numpy as np
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    corners = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", corners)
    digest = hashlib.blake2b(co.tobytes(), digest_size=8)
    digest.update(corners.tobytes())
    return "%d:%d:%s" % (len(mesh.vertices), len(mesh.polygons), digest.hexdigest())


def _changed(self, _context):
    if not _quiet:
        rebuild(self.id_data)


def _length(name, description):
    return FloatProperty(name=name, description=description, default=1.0, min=0.001, soft_max=100.0,
                         subtype='DISTANCE', unit='LENGTH', update=_changed)


def _count(name, description, lowest=1):
    return IntProperty(name=name, description=description, default=1, min=lowest, max=SUB_MAX, update=_changed)


class M3D_Input(PropertyGroup):
    """Creation settings of a primitive (Channel Box > INPUTS)"""
    kind: EnumProperty(items=(('NONE', "None", "No inputs: the mesh is plain geometry"),
                              *((k, v[0], "") for k, v in KINDS.items())), default='NONE')
    width: _length("Width", "Size along X")
    height: _length("Height", "Size along Z (up); a plane's height runs along Y")
    depth: _length("Depth", "Size along Y")
    radius: _length("Radius", "Radius around the Z axis; a torus' radius is that of the ring")
    section_radius: _length("Section Radius", "Radius of the torus tube")
    sub_width: _count("Subdivisions Width", "Faces along X")
    sub_height: _count("Subdivisions Height", "Faces along Z (up); a plane's along Y; a sphere's and a torus' "
                       "around the tube from pole to pole")
    sub_depth: _count("Subdivisions Depth", "Faces along Y")
    sub_axis: _count("Subdivisions Axis", "Faces around the Z axis", 3)
    sub_caps: _count("Subdivisions Caps", "Rings across each cap: 0 leaves the end open, 1 is a single n-gon", 0)
    frozen: BoolProperty(name="Frozen", description="The mesh was edited: the inputs no longer apply")
    signature: StringProperty(options={'HIDDEN'})


# -----------------------------------------------------------------------------
# Builders: each fills an empty BMesh, with UVs on the "UVMap" layer, flat shaded.

def _tau(i, n):
    return 2.0 * math.pi * i / n


def _surface(bm, size, divs, sides):
    """Subdivided box surface, or a single grid when `sides` has one side. size/divs: per axis (x, y, z).
    sides: (fixed axis, at the max end, uv tile (column, row) or None for the whole 0..1 square)."""
    uv_layer = bm.loops.layers.uv.new("UVMap")
    verts = {}

    def vert(idx):
        if idx not in verts:
            verts[idx] = bm.verts.new([size[a] * (idx[a] / divs[a] - 0.5) for a in range(3)])
        return verts[idx]

    for fixed, at_max, tile in sides:
        a_axis, b_axis = {0: (1, 2), 1: (2, 0), 2: (0, 1)}[fixed]   # a x b points along +fixed
        for a in range(divs[a_axis]):
            for b in range(divs[b_axis]):
                corners = [(a, b), (a + 1, b), (a + 1, b + 1), (a, b + 1)]
                if not at_max:
                    corners.reverse()
                loops = []
                for ca, cb in corners:
                    idx = [0, 0, 0]
                    idx[fixed], idx[a_axis], idx[b_axis] = divs[fixed] if at_max else 0, ca, cb
                    loops.append((vert(tuple(idx)), ca / divs[a_axis], cb / divs[b_axis]))
                face = bm.faces.new([v for v, _u, _v in loops])
                for loop, (_vert, u, v) in zip(face.loops, loops):
                    if tile is None:
                        loop[uv_layer].uv = (u, v)
                    else:   # Cross layout, mirrored on the far sides so the picture reads from outside.
                        loop[uv_layer].uv = ((tile[0] + (u if at_max else 1 - u)) / 4, (tile[1] + v) / 3)


def _cube(bm, p):
    # Sides in the order +X -X +Y -Y +Z -Z, laid out as a cross: row 1 is -X -Y +X +Y, +Z above -Z below.
    tiles = {(0, True): (2, 1), (0, False): (0, 1), (1, True): (3, 1), (1, False): (1, 1),
             (2, True): (1, 2), (2, False): (1, 0)}
    _surface(bm, (p.width, p.depth, p.height), (p.sub_width, p.sub_depth, p.sub_height),
             [(axis, end, tiles[axis, end]) for axis in range(3) for end in (True, False)])


def _plane(bm, p):
    _surface(bm, (p.width, p.height, 0.0), (p.sub_width, p.sub_height, 1), [(2, True, None)])


def _sphere(bm, p):
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_uvsphere(bm, u_segments=p.sub_axis, v_segments=max(p.sub_height, 2), radius=p.radius,
                              calc_uvs=True)


def _revolve(bm, n, profile, ngon_bottom=False, ngon_top=False):
    """Surface of revolution around Z. profile: (radius, z) from the bottom up; radius 0 is a single point.
    Same-height steps (caps) get a flat disc UV, the rest wraps once around."""
    uv_layer = bm.loops.layers.uv.new("UVMap")
    rmax = max(r for r, _z in profile)
    zmin, zmax = min(z for _r, z in profile), max(z for _r, z in profile)
    rings = [[bm.verts.new((r * math.cos(_tau(i, n)), r * math.sin(_tau(i, n)), z)) for i in range(n)] if r else
             [bm.verts.new((0, 0, z))] for r, z in profile]

    def uv(k, i, cap):
        r, z = profile[k]
        if cap:
            return 0.5 + 0.5 * r / rmax * math.cos(_tau(i, n)), 0.5 + 0.5 * r / rmax * math.sin(_tau(i, n))
        return (i + (0.5 if r == 0 else 0)) / n, (z - zmin) / ((zmax - zmin) or 1)

    def add(verts, uvs):
        face = bm.faces.new(verts)
        for loop, co in zip(face.loops, uvs):
            loop[uv_layer].uv = co

    for k in range(len(profile) - 1):
        a, b, cap = rings[k], rings[k + 1], profile[k][1] == profile[k + 1][1]
        for i in range(n):
            j = (i + 1) % n
            if len(a) == 1:
                add([a[0], b[j], b[i]], [uv(k, i, cap), uv(k + 1, i + 1, cap), uv(k + 1, i, cap)])
            elif len(b) == 1:
                add([a[i], a[j], b[0]], [uv(k, i, cap), uv(k, i + 1, cap), uv(k + 1, i, cap)])
            else:
                add([a[i], a[j], b[j], b[i]],
                    [uv(k, i, cap), uv(k, i + 1, cap), uv(k + 1, i + 1, cap), uv(k + 1, i, cap)])
    last = len(profile) - 1
    if ngon_bottom:
        add(rings[0][::-1], [uv(0, i, True) for i in reversed(range(n))])
    if ngon_top:
        add(rings[last], [uv(last, i, True) for i in range(n)])


def _cap(r, z, rings):
    """Profile of a cap from its centre out to (not including) the rim: `rings` radial divisions."""
    return [(0.0, z)] + [(r * k / rings, z) for k in range(1, rings)]


def _cylinder(bm, p):
    r, h, caps = p.radius, p.height, p.sub_caps
    side = [(r, h * (j / p.sub_height - 0.5)) for j in range(p.sub_height + 1)]
    bottom = _cap(r, -h / 2, caps) if caps > 1 else []
    top = _cap(r, h / 2, caps)[::-1] if caps > 1 else []
    _revolve(bm, p.sub_axis, bottom + side + top, ngon_bottom=caps == 1, ngon_top=caps == 1)


def _cone(bm, p):
    r, h, caps = p.radius, p.height, p.sub_caps
    side = [(r * (1 - j / p.sub_height), h * (j / p.sub_height - 0.5)) for j in range(p.sub_height)] + [(0.0, h / 2)]
    bottom = _cap(r, -h / 2, caps) if caps > 1 else []
    _revolve(bm, p.sub_axis, bottom + side, ngon_bottom=caps == 1)


def _torus(bm, p):
    uv_layer = bm.loops.layers.uv.new("UVMap")
    n, m = p.sub_axis, max(p.sub_height, 3)
    verts = [[bm.verts.new(((p.radius + p.section_radius * math.cos(_tau(j, m))) * math.cos(_tau(i, n)),
                            (p.radius + p.section_radius * math.cos(_tau(j, m))) * math.sin(_tau(i, n)),
                            p.section_radius * math.sin(_tau(j, m)))) for j in range(m)] for i in range(n)]
    for i in range(n):
        for j in range(m):
            corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            face = bm.faces.new([verts[ci % n][cj % m] for ci, cj in corners])
            for loop, (ci, cj) in zip(face.loops, corners):
                loop[uv_layer].uv = (ci / n, cj / m)


BUILDERS = {'CUBE': _cube, 'SPHERE': _sphere, 'CYLINDER': _cylinder, 'CONE': _cone, 'PLANE': _plane, 'TORUS': _torus}


# -----------------------------------------------------------------------------
# Rebuild, freeze, clear

def is_frozen(ob):
    """True when the mesh was edited since the inputs built it (read only: safe to call while drawing)."""
    inp = ob.m3d_input
    return inp.frozen or (bool(inp.signature) and signature(ob.data) != inp.signature)


def rebuild(ob):
    """Rebuild the mesh from the inputs, in place. Returns False when there is nothing to build or the inputs are
    frozen (an edited mesh is marked frozen here and left alone)."""
    inp = ob.m3d_input
    if inp.kind == 'NONE' or ob.type != 'MESH' or inp.frozen or ob.mode != 'OBJECT':
        return False
    mesh = ob.data
    if is_frozen(ob):
        inp.frozen = True
        return False
    smooth = any(f.use_smooth for f in mesh.polygons)   # Shade Smooth survives a rebuild.
    bm = bmesh.new()
    BUILDERS[inp.kind](bm, inp)
    for f in bm.faces:
        f.smooth = smooth
        f.select_set(True)   # Like a new primitive: everything selected when Edit Mode opens.
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    inp.signature = signature(mesh)
    return True


def set_inputs(ob, **values):
    """Set several inputs (property names, see KINDS) with one rebuild."""
    global _quiet
    inp = ob.m3d_input
    _quiet = True
    try:
        for name, value in values.items():
            setattr(inp, name, int(value) if inp.bl_rna.properties[name].type == 'INT' else float(value))
    finally:
        _quiet = False
    rebuild(ob)


def attach(ob, kind, **values):
    """Make `ob` (a mesh) a live `kind` primitive with the default inputs, then `values` on top."""
    global _quiet
    inp = ob.m3d_input
    _quiet = True
    try:
        inp.kind, inp.frozen, inp.signature = kind, False, ""
    finally:
        _quiet = False
    set_inputs(ob, **{**DEFAULTS[kind], **values})


def clear(ob):
    """Delete History: the mesh stays as it is, the inputs go."""
    inp = ob.m3d_input
    inp.kind, inp.frozen, inp.signature = 'NONE', False, ""


class M3D_OT_delete_history(Operator):
    """Delete History: the primitive inputs of the selection are removed (the mesh stays as it is)"""
    bl_idname = "m3d.delete_history"
    bl_label = "Delete History"
    bl_options = {'REGISTER', 'UNDO'}

    modifiers: BoolProperty(name="Modifiers", description="Also apply the modifiers (convert to mesh)")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object is not None

    def execute(self, context):
        for ob in {*context.selected_objects, context.active_object}:
            clear(ob)
        if self.modifiers:
            bpy.ops.object.convert(target='MESH')
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Channel Box

def draw(layout, ob):
    """The "<Kind> inputs" block of the Channel Box: greyed when frozen or while editing components."""
    inp = ob.m3d_input
    if ob.type != 'MESH' or inp.kind == 'NONE':
        return
    header, body = layout.panel("m3d_primitive_inputs", default_closed=False)
    header.label(text="%s inputs" % KINDS[inp.kind][0])
    if body is None:
        return
    frozen = is_frozen(ob)
    if frozen:
        body.label(text="Mesh edited: inputs no longer apply", icon='INFO')
    elif ob.mode != 'OBJECT':
        body.label(text="Inputs apply in Object Mode", icon='INFO')
    col = body.column(align=True)
    col.enabled = not frozen and ob.mode == 'OBJECT'
    for name in KINDS[inp.kind][1]:
        col.prop(inp, name, text=LABELS[name])
    body.operator("m3d.delete_history", text="Delete History", icon='X')


classes = (M3D_Input, M3D_OT_delete_history)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.m3d_input = bpy.props.PointerProperty(type=M3D_Input)


def unregister():
    del bpy.types.Object.m3d_input
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
