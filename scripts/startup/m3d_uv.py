# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
UV workspace (F3) for Maelstrom3D: the dock pages (Unwrap, Arrange, Check, Create, UDIM), the UV Status Line, the shelf,
the Cut / Sew / Unfold / Optimize / Layout workflow, texel density, Auto Unwrap, the checker map and the UV marking menus.

The layout is built by tools/m3d/build_startup.py (phase2_uv), the tabs are DOCK_TABS['UV'] in m3d_workspace.py, the
menus and shelf in m3d_ui.py. UV Editor operators (uv.*, m3d.uv_*) run in the UV Editor when a button outside it is
pressed (m3d.call with editor='IMAGE_EDITOR'). The sidebar UV Toolkit stays in UV Editors of other workspaces; the
UV workspace has the dock instead.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup
from mathutils import Vector

from m3d_mode import _button
from m3d_sculpt import grid, reason, split_props
from m3d_workspace import _PagePanel, current_kind

UV_TOOLKIT = "UV Toolkit"
CHECKER = "m3dUVChecker"


def _in_uv_editor(context):
    space = context.space_data
    return space is not None and space.type == 'IMAGE_EDITOR'


class M3D_OT_uv_cut(Operator):
    """Cut: split UVs along the selected edges (marks them as seams for Unfold)"""
    bl_idname = "m3d.uv_cut"
    bl_label = "Cut UVs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        if _in_uv_editor(context):
            bpy.ops.uv.mark_seam(clear=False)
        else:
            bpy.ops.mesh.mark_seam(clear=False)
        return {'FINISHED'}


class M3D_OT_uv_sew(Operator):
    """Sew: join UVs along the selected edges"""
    bl_idname = "m3d.uv_sew"
    bl_label = "Sew UVs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        if _in_uv_editor(context):
            bpy.ops.uv.mark_seam(clear=True)
            bpy.ops.uv.stitch('EXEC_DEFAULT')
        else:
            bpy.ops.mesh.mark_seam(clear=True)
        return {'FINISHED'}


class M3D_UVSettings(PropertyGroup):
    """Options of the UV tools (Scene.m3d_uv): what Unfold, Optimize, Layout, Auto Unwrap and texel density use."""
    method: EnumProperty(name="Method", default='ANGLE_BASED', items=(
        ('ANGLE_BASED', "Angle Based", "Fast, good for most shapes"),
        ('CONFORMAL', "Conformal", "Keeps shapes (angles) true, can stretch areas")))
    fill_holes: BoolProperty(name="Fill Holes", default=True,
                             description="Fill holes in the mesh while unfolding, so shells overlap less")
    iterations: IntProperty(name="Iterations", default=50, min=1, soft_max=500,
                            description="Relaxing passes of Optimize (slow on dense meshes)")
    margin: FloatProperty(name="Margin", default=0.01, min=0.0, max=1.0, precision=3,
                          description="Space between shells in Layout")
    rotate: EnumProperty(name="Rotation", default='CARDINAL', items=(
        ('OFF', "None", "Keep the shells as they are"),
        ('CARDINAL', "90 Degrees", "Turn shells in steps of 90 degrees"),
        ('AXIS_ALIGNED', "Axis Aligned", "Turn shells so their long side is straight"),
        ('ANY', "Any", "Turn shells to any angle for the tightest fit")))
    angle: FloatProperty(name="Seam Angle", subtype='ANGLE', default=math.radians(66.0), min=0.0, max=math.pi,
                         description="Auto Unwrap cuts at edges sharper than this")
    texture_size: EnumProperty(name="Texture Size", default='2048', description="Texture size for texel density",
                               items=[(str(n), "%d px" % n, "") for n in (256, 512, 1024, 2048, 4096, 8192)])
    density: FloatProperty(name="Target", default=512.0, min=0.001, soft_max=8192.0, precision=1,
                           description="Texel density to set, in pixels per unit")
    density_read: FloatProperty(name="Current", default=0.0, description="Texel density of the last Read")


def pack_options(s):
    """uv.pack_islands options from the Layout settings."""
    return {"margin": s.margin, "rotate": s.rotate != 'OFF', "rotate_method": 'ANY' if s.rotate == 'OFF' else s.rotate}


class M3D_OT_uv_unfold(Operator):
    """Unfold: flatten the selected UV shells along their cuts (method in the Unwrap tab), keeping pinned UVs"""
    bl_idname = "m3d.uv_unfold"
    bl_label = "Unfold"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        s = context.scene.m3d_uv
        bpy.ops.uv.unwrap(method=s.method, fill_holes=s.fill_holes, margin=0.001)
        return {'FINISHED'}


class M3D_OT_uv_optimize(Operator):
    """Optimize: relax the selected UV shells to reduce stretching (slow on dense meshes)"""
    bl_idname = "m3d.uv_optimize"
    bl_label = "Optimize"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        bpy.ops.uv.minimize_stretch('EXEC_DEFAULT', iterations=context.scene.m3d_uv.iterations)
        return {'FINISHED'}


class M3D_OT_uv_layout(Operator):
    """Layout: pack the selected UV shells into the 0-1 space (margin and rotation in the Unwrap tab)"""
    bl_idname = "m3d.uv_layout"
    bl_label = "Layout"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        bpy.ops.uv.pack_islands(**pack_options(context.scene.m3d_uv))
        return {'FINISHED'}


class M3D_OT_uv_auto(Operator):
    """Auto Unwrap: cut seams at sharp edges, unfold and lay the shells out (the whole mesh when nothing is selected)"""
    bl_idname = "m3d.uv_auto"
    bl_label = "Auto Unwrap"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        s, ts = context.scene.m3d_uv, context.tool_settings
        obs = [ob for ob in context.objects_in_mode_unique_data if ob.type == 'MESH']
        if not any(f.select for ob in obs for f in bmesh.from_edit_mesh(ob.data).faces):
            bpy.ops.mesh.select_all(action='SELECT')
        seams = 0
        for ob in obs:
            bm = bmesh.from_edit_mesh(ob.data)
            faces = {f for f in bm.faces if f.select}
            for e in bm.edges:
                if faces.isdisjoint(e.link_faces):
                    continue
                angle = e.calc_face_angle(None)   # None: boundary edge, which is a cut already
                e.seam = (angle is not None and angle > s.angle) or not faces.issuperset(e.link_faces)
                seams += e.seam
            bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        # UV selection follows the mesh selection in sync mode: switch it on while unwrapping.
        sync, ts.use_uv_select_sync = ts.use_uv_select_sync, True
        try:
            if seams:
                bpy.ops.m3d.uv_unfold()
                bpy.ops.m3d.uv_layout()
            else:   # A smooth closed shape has no sharp edge to cut at: project it instead.
                bpy.ops.uv.smart_project(angle_limit=s.angle, island_margin=s.margin)
        finally:
            ts.use_uv_select_sync = sync
        self.report({'INFO'}, "Auto Unwrap: %d seams" % seams if seams else "Auto Unwrap: no sharp edges, projected")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Texel density

def same_uv_edge(a, b, uv):
    """True when the loops `a` and `b` (of two faces sharing an edge) have the same UVs: one shell."""
    a0, a1 = a[uv].uv, a.link_loop_next[uv].uv
    b0, b1 = b[uv].uv, b.link_loop_next[uv].uv
    if b.vert != a.vert:
        b0, b1 = b1, b0
    return (a0 - b0).length < 1e-5 and (a1 - b1).length < 1e-5


def uv_shells(faces, uv):
    """`faces` grouped into UV shells: faces that share an edge with the same UVs on both sides."""
    todo, shells = set(faces), []
    while todo:
        stack = [todo.pop()]
        shell = list(stack)
        while stack:
            for loop in stack.pop().loops:
                other = loop.link_loop_radial_next
                while other != loop:
                    if other.face in todo and same_uv_edge(loop, other, uv):
                        todo.discard(other.face)
                        shell.append(other.face)
                        stack.append(other.face)
                    other = other.link_loop_radial_next
        shells.append(shell)
    return shells


def uv_area(face, uv):
    pts = [loop[uv].uv for loop in face.loops]
    return abs(sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def world_area(face, matrix):
    pts = [matrix @ v.co for v in face.verts]
    return sum((a.cross(b) for a, b in zip(pts, pts[1:] + pts[:1])), Vector()).length / 2


def texel_density(faces, uv, matrix, size):
    """Pixels per unit of a group of faces: sqrt(UV area / world area) x texture size (0 for a degenerate group)."""
    area = sum(world_area(f, matrix) for f in faces)
    return math.sqrt(sum(uv_area(f, uv) for f in faces) / area) * size if area > 1e-12 else 0.0


def scale_shell(faces, uv, factor):
    """Scale a shell about the centre of its UV bounds."""
    loops = [loop for f in faces for loop in f.loops]
    us = [loop[uv].uv for loop in loops]
    centre = Vector(((min(p.x for p in us) + max(p.x for p in us)) / 2, (min(p.y for p in us) + max(p.y for p in us)) / 2))
    for loop in loops:
        loop[uv].uv = centre + (loop[uv].uv - centre) * factor


def selected_shells(bm, sync):
    """(UV layer, shells with a selected face): the UV selection (mesh selection in sync mode); with nothing selected
    every visible face counts."""
    uv = bm.loops.layers.uv.active
    visible = [f for f in bm.faces if not f.hide]
    picked = [f for f in visible if f.select]
    layer = None if sync else bm.loops.layers.bool.get(".vs." + uv.name)
    if layer is not None:
        picked = [f for f in picked if all(loop[layer] for loop in f.loops)] or picked
    picked = set(picked or visible)
    return uv, [shell for shell in uv_shells(visible, uv) if picked.intersection(shell)]


class M3D_OT_uv_texel_density(Operator):
    """Texel density (pixels per unit at the texture size set in the Status Line): Read the selected shells, Set them
    to the target, or Match them to the active face's shell"""
    bl_idname = "m3d.uv_texel_density"
    bl_label = "Texel Density"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(
        ('READ', "Read", "Measure the selected shells"),
        ('SET', "Set", "Scale each selected shell about its centre to the target density"),
        ('MATCH', "Match", "Scale the selected shells to the density of the active face's shell")))

    @classmethod
    def description(cls, _context, props):
        return {'READ': "Measure the texel density of the selected shells (nothing selected: the whole mesh)",
                'SET': "Scale each selected shell about its centre to the target texel density",
                'MATCH': "Scale the selected shells to the density of the active face's shell "
                         "(no active face: their average)"}[props.mode]

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        s = context.scene.m3d_uv
        size, sync = int(s.texture_size), context.tool_settings.use_uv_select_sync
        found = []   # (object, UV layer, shell, density, UV area, world area)
        bms = {}
        for ob in context.objects_in_mode_unique_data:
            if ob.type != 'MESH' or not ob.data.uv_layers:
                continue
            bms[ob] = bm = bmesh.from_edit_mesh(ob.data)
            uv, shells = selected_shells(bm, sync)
            for shell in shells:
                found.append((ob, uv, shell, texel_density(shell, uv, ob.matrix_world, size),
                              sum(uv_area(f, uv) for f in shell), sum(world_area(f, ob.matrix_world) for f in shell)))
        if not found:
            self.report({'WARNING'}, "No UV map to measure")
            return {'CANCELLED'}
        total = math.sqrt(sum(f[4] for f in found) / max(sum(f[5] for f in found), 1e-12)) * size
        s.density_read = total
        if self.mode == 'READ':
            self.report({'INFO'}, "Texel density: %.1f px/unit (%d shells)" % (total, len(found)))
            return {'FINISHED'}
        target = s.density
        if self.mode == 'MATCH':
            edit = context.edit_object
            active = bms[edit].faces.active if edit in bms else None
            target = next((f[3] for f in found if active in f[2]), total)
            s.density = target
        for ob, uv, shell, density, _uv_a, _world_a in found:
            if density > 0:
                scale_shell(shell, uv, target / density)
        for ob, bm in bms.items():
            bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        s.density_read = target
        self.report({'INFO'}, "%d shells set to %.1f px/unit" % (len(found), target))
        return {'FINISHED'}


class M3D_OT_uv_rotate(Operator):
    """Rotate the selected UVs by 90 degrees"""
    bl_idname = "m3d.uv_rotate"
    bl_label = "Rotate UVs 90"
    bl_options = {'REGISTER', 'UNDO'}

    clockwise: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and _in_uv_editor(context)

    def execute(self, _context):
        bpy.ops.transform.rotate(value=-math.pi / 2 if self.clockwise else math.pi / 2)
        return {'FINISHED'}


class M3D_OT_uv_flip(Operator):
    """Flip: mirror the selected UVs in U or V"""
    bl_idname = "m3d.uv_flip"
    bl_label = "Flip UVs"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(items=(('U', "U", ""), ('V', "V", "")))

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and _in_uv_editor(context)

    def execute(self, _context):
        bpy.ops.transform.mirror(constraint_axis=(self.axis == 'U', self.axis == 'V', False))
        return {'FINISHED'}


def checker_material():
    mat = bpy.data.materials.get(CHECKER)
    if mat is None:
        mat = bpy.data.materials.new(CHECKER)
        mat.use_nodes = True
        image = bpy.data.images.new(CHECKER, 1024, 1024)
        image.generated_type = 'COLOR_GRID'
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        mat.node_tree.nodes.active = tex
    return mat


def set_checker(ob, on):
    """Put the checker map on every material slot of `ob` or give the meshes' own materials back. The slots stay,
    so the faces keep their material numbers. The own materials are kept on the object as ID references, which
    count as users: autosave and purging unused data can't drop them while the checker is on."""
    slots = ob.material_slots
    if on and CHECKER not in ob:
        saved = {str(i): s.material for i, s in enumerate(slots) if s.material is not None}
        saved["count"] = len(slots)
        ob[CHECKER] = saved
        checker = checker_material()
        if not slots:
            ob.data.materials.append(checker)
        for slot in slots:
            slot.material = checker
    elif not on and CHECKER in ob:
        saved = ob[CHECKER]
        if hasattr(saved, "get"):
            count = saved.get("count", 0)
            materials = [saved.get(str(i)) for i in range(count)]
        else:  # Files from before: a list of material names.
            materials = [bpy.data.materials.get(name) for name in saved]
        if materials:
            for slot, mat in zip(slots, materials):
                slot.material = mat
        else:
            ob.data.materials.clear()
        del ob[CHECKER]


def checker_on(context):
    ob = context.edit_object or context.active_object
    return ob is not None and CHECKER in ob


class M3D_OT_uv_checker(Operator):
    """Checker map: show a UV checker texture on the selected meshes (toggle)"""
    bl_idname = "m3d.uv_checker"
    bl_label = "Checker Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obs = {ob for ob in context.selected_objects if ob.type == 'MESH'}
        if context.edit_object:
            obs.add(context.edit_object)
        if not obs:
            self.report({'WARNING'}, "Select a mesh")
            return {'CANCELLED'}
        on = any(CHECKER not in ob for ob in obs)
        for ob in obs:
            set_checker(ob, on)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.color_type = 'TEXTURE' if on else 'MATERIAL'
        return {'FINISHED'}


_checker_obs = []


@bpy.app.handlers.persistent
def checker_save_pre(*_args):
    """Files never keep the checker: take it off before saving (and drop its material and image)."""
    _checker_obs[:] = [ob.name for ob in bpy.data.objects if CHECKER in ob]
    for name in _checker_obs:
        set_checker(bpy.data.objects[name], False)
    for collection in (bpy.data.materials, bpy.data.images):
        item = collection.get(CHECKER)
        if item is not None:
            collection.remove(item)


@bpy.app.handlers.persistent
def checker_save_post(*_args):
    for name in _checker_obs:
        if name in bpy.data.objects:
            set_checker(bpy.data.objects[name], True)
    _checker_obs.clear()


# UV Toolkit sections: (label, idname, icon, props).
UVTK_SELECT = (
    ("Shell", "uv.select_linked", 'UV_ISLANDSEL', {}),
    ("Grow", "uv.select_more", 'ADD', {}),
    ("Shrink", "uv.select_less", 'REMOVE', {}),
    ("Invert", "uv.select_all", 'SELECT_DIFFERENCE', {"action": 'INVERT'}),
    ("Overlapping", "uv.select_overlap", 'SELECT_INTERSECT', {}),
)
UVTK_PIN = (
    ("Pin", "uv.pin", 'PINNED', {}),
    ("Unpin", "uv.pin", 'UNPINNED', {"clear": True}),
)
UVTK_TRANSFORM = (
    ("Flip U", "m3d.uv_flip", 'MOD_MIRROR', {"axis": 'U'}),
    ("Flip V", "m3d.uv_flip", 'MOD_MIRROR', {"axis": 'V'}),
    ("Rotate 90 CW", "m3d.uv_rotate", 'LOOP_FORWARDS', {"clockwise": True}),
    ("Rotate 90 CCW", "m3d.uv_rotate", 'LOOP_BACK', {"clockwise": False}),
    ("Align U", "uv.align", 'ALIGN_CENTER', {"axis": 'ALIGN_X'}),
    ("Align V", "uv.align", 'ALIGN_MIDDLE', {"axis": 'ALIGN_Y'}),
    ("Straighten", "uv.align", 'IPO_LINEAR', {"axis": 'ALIGN_S'}),
    ("Snap Together", "uv.weld", 'AUTOMERGE_ON', {}),
)
UVTK_CREATE = (
    ("Automatic", "uv.smart_project", 'MOD_UVPROJECT', {}),
    ("Planar", "uv.project_from_view", 'MESH_PLANE', {}),
    ("Cylindrical", "uv.cylinder_project", 'MESH_CYLINDER', {}),
    ("Spherical", "uv.sphere_project", 'MESH_UVSPHERE', {}),
    ("Camera-Based", "uv.project_from_view", 'CAMERA_DATA', {"camera_bounds": True}),
    ("Cube (Box)", "uv.cube_project", 'MESH_CUBE', {}),
)
UVTK_CUT_SEW = (
    ("Cut", "m3d.uv_cut", 'SCULPTMODE_HLT', {}),
    ("Sew", "m3d.uv_sew", 'AUTOMERGE_ON', {}),
    ("Split", "uv.select_split", 'UNLINKED', {}),
    ("Merge", "uv.remove_doubles", 'AUTOMERGE_OFF', {}),
    ("Auto Seams (from shells)", "uv.seams_from_islands", 'UV_ISLANDSEL', {}),
)
UVTK_UNFOLD = (
    ("Unfold", "m3d.uv_unfold", 'UV', {}),
    ("Optimize", "m3d.uv_optimize", 'MOD_SMOOTH', {}),
    ("Layout", "m3d.uv_layout", 'STICKY_UVS_DISABLE', {}),
    ("Orient Shells", "uv.align_rotation", 'ORIENTATION_GIMBAL', {"method": 'AUTO'}),
    ("Match Texel Scale", "uv.average_islands_scale", 'FULLSCREEN_ENTER', {}),
)

UV_TOOLKIT_SECTIONS = (
    ("Selection", UVTK_SELECT), ("Pin", UVTK_PIN), ("Transform", UVTK_TRANSFORM), ("Create", UVTK_CREATE),
    ("Cut and Sew", UVTK_CUT_SEW), ("Unfold", UVTK_UNFOLD),
)


def _uv_buttons(layout, context, items):
    from m3d_mode import _buttons
    _buttons(layout, context, items)


# Dock pages: tables of (label, idname, icon, props) beside the Toolkit's.
UV_PIN_PAGE = (
    *UVTK_PIN,
    ("Invert Pins", "uv.pin", 'ARROW_LEFTRIGHT', {"invert": True}),
    ("Select Pinned", "uv.select_pinned", 'PINNED', {}),
)
UV_SELECT_PAGE = (*UVTK_SELECT, ("Pinned", "uv.select_pinned", 'PINNED', {}))
UV_SHELVES = UVTK_UNFOLD[3:]   # Orient Shells, Match Texel Scale
UV_TILES = (
    ("Pack to Active Tile", "uv.pack_islands", 'STICKY_UVS_DISABLE', {"udim_source": 'ACTIVE_UDIM', "margin": 0.01}),
    ("Pack to Closest Tile", "uv.pack_islands", 'STICKY_UVS_LOC', {"udim_source": 'CLOSEST_UDIM', "margin": 0.01}),
    ("Select Tile", "uv.select_tile", 'RESTRICT_SELECT_OFF', {}),
)


class _UVToolkitPanel:
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = UV_TOOLKIT

    @classmethod
    def poll(cls, context):
        return context.space_data.show_uvedit and current_kind(context) != 'UV'   # The UV workspace has the dock.


class IMAGE_PT_m3d_uvtk_selection(_UVToolkitPanel, Panel):
    bl_label = "Selection"

    def draw(self, context):
        layout = self.layout
        ts = context.tool_settings
        row = layout.row(align=True)
        row.prop(ts, "use_uv_select_sync", text="", icon='UV_SYNC_SELECT')
        row.prop(ts, "uv_select_mode", text="", expand=True)
        row.prop(ts, "use_uv_select_island", text="Shell", toggle=True)
        _uv_buttons(layout, context, UVTK_SELECT)


def _section_panel(idname, label, items, closed=False):
    def draw(self, context):
        _uv_buttons(self.layout, context, items)
    attrs = {"bl_label": label, "draw": draw}
    if closed:
        attrs["bl_options"] = {'DEFAULT_CLOSED'}
    return type(idname, (_UVToolkitPanel, Panel), attrs)


class IMAGE_PT_m3d_uvtk_display(_UVToolkitPanel, Panel):
    bl_label = "Display"

    def draw(self, context):
        layout = self.layout
        layout.operator("m3d.uv_checker", icon='TEXTURE')
        layout.prop(context.space_data.uv_editor, "show_stretch", text="Distortion")
        layout.prop(context.space_data.uv_editor, "show_faces", text="Shaded UVs")


class M3D_MT_uv_marking_menu(Menu):
    """UV Editor right-click marking menu: UV component modes"""
    bl_label = "UV Marking Menu"

    def draw(self, context):
        pie = self.layout.menu_pie()
        # Pie order: W, E, S, N, NW, NE, SW, SE.
        for label, mode, icon in (("UV", 'VERTEX', 'UV_VERTEXSEL'), ("Face", 'FACE', 'UV_FACESEL')):
            pie.operator("uv.select_mode", text=label, icon=icon).type = mode
        pie.operator("wm.context_toggle", text="UV Shell", icon='UV_ISLANDSEL').data_path = \
            "tool_settings.use_uv_select_island"
        pie.operator("uv.select_mode", text="Edge", icon='UV_EDGESEL').type = 'EDGE'
        pie.operator("uv.select_all", text="Select All", icon='SELECT_EXTEND').action = 'SELECT'
        pie.operator("object.mode_set", text="Object Mode", icon='OBJECT_DATAMODE').mode = 'OBJECT'
        pie.menu("IMAGE_MT_uvs_context_menu", text="More...", icon='COLLAPSEMENU')
        pie.operator("uv.select_linked", text="Select Shell", icon='UV_ISLANDSEL')


class M3D_MT_uv_tools(Menu):
    """UV Editor Shift+right-click marking menu: the UV workflow"""
    bl_label = "UV Tools"

    def draw(self, context):
        pie = self.layout.menu_pie()
        for label, idname, icon, props in (
            ("Cut", "m3d.uv_cut", 'SCULPTMODE_HLT', {}),
            ("Sew", "m3d.uv_sew", 'AUTOMERGE_ON', {}),
            ("Layout", "m3d.uv_layout", 'STICKY_UVS_DISABLE', {}),
            ("Unfold", "m3d.uv_unfold", 'UV', {}),
            ("Straighten", "uv.align", 'IPO_LINEAR', {"axis": 'ALIGN_S'}),
            ("Orient Shells", "uv.align_rotation", 'ORIENTATION_GIMBAL', {"method": 'AUTO'}),
            ("Optimize", "m3d.uv_optimize", 'MOD_SMOOTH', {}),
            ("Automatic", "uv.smart_project", 'MOD_UVPROJECT', {}),
        ):
            o = pie.operator(idname, text=label, icon=icon)
            for k, v in props.items():
                setattr(o, k, v)


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

def uv_space(context):
    """The UV Editor's space (the dock and the top bar have none of their own): the biggest Image Editor on screen."""
    areas = [a for a in context.screen.areas if a.type == 'IMAGE_EDITOR'] if context.screen else []
    return max(areas, key=lambda a: a.width * a.height).spaces.active if areas else None


def mesh_object(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'MESH' else None


def ready(context, need):
    """Can a page with this need be used: None always, 'EDIT' with a mesh in Edit Mode."""
    return need is None or (context.mode == 'EDIT_MESH' and mesh_object(context) is not None)


class _Page(_PagePanel):
    """Panel that needs `need` (see `ready`)."""
    need = 'EDIT'

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.need)


def _gate(page):
    """The panel a page shows instead of its own when there is nothing to work on: what to do next."""
    def draw(self, context):
        col = self.layout.column(align=True)
        if mesh_object(context) is None:
            col.label(text="Select a mesh to unwrap")
            _button(col, context, "Add Cube", "m3d.add_primitive", 'MESH_CUBE', {"kind": 'CUBE'})
        else:
            col.label(text="Enter Edit Mode to use these tools")
            _button(col, context, "Edit Mode", "object.mode_set", 'EDITMODE_HLT', {"mode": 'EDIT'})
    return type("PROPERTIES_PT_m3d_uv_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "UV", "bl_options": {'HIDE_HEADER'}, "page": "uv_" + page,
        "page_poll": classmethod(lambda cls, context: not ready(context, 'EDIT')), "draw": draw})


# --- Unwrap

class _Unwrap(_Page):
    page = "uv_unwrap"


class PROPERTIES_PT_m3d_uv_cut(_Unwrap, Panel):
    bl_label = "Cut and Sew"

    def draw(self, context):
        grid(self.layout, context, UVTK_CUT_SEW)


class PROPERTIES_PT_m3d_uv_unfold(_Unwrap, Panel):
    bl_label = "Unfold"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_uv
        layout.row().prop(s, "method", expand=True)
        layout.prop(s, "fill_holes")
        row = layout.row()
        row.scale_y = 1.4
        _button(row, context, "Unfold", "m3d.uv_unfold", 'UV', {})


class PROPERTIES_PT_m3d_uv_optimize(_Unwrap, Panel):
    bl_label = "Optimize"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        layout.prop(context.scene.m3d_uv, "iterations")
        _button(layout, context, "Optimize", "m3d.uv_optimize", 'MOD_SMOOTH', {})
        reason(layout, "Slow on dense meshes: select fewer shells")


class PROPERTIES_PT_m3d_uv_layout(_Unwrap, Panel):
    bl_label = "Layout"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_uv
        layout.prop(s, "margin")
        layout.prop(s, "rotate")
        row = layout.row()
        row.scale_y = 1.4
        _button(row, context, "Layout", "m3d.uv_layout", 'STICKY_UVS_DISABLE', {})


class PROPERTIES_PT_m3d_uv_pin(_Unwrap, Panel):
    bl_label = "Pin"

    def draw(self, context):
        grid(self.layout, context, UV_PIN_PAGE)


# --- Arrange

class _Arrange(_Page):
    page = "uv_arrange"


class PROPERTIES_PT_m3d_uv_select(_Arrange, Panel):
    bl_label = "Select"

    def draw(self, context):
        grid(self.layout, context, UV_SELECT_PAGE)


class PROPERTIES_PT_m3d_uv_transform(_Arrange, Panel):
    bl_label = "Transform"

    def draw(self, context):
        grid(self.layout, context, UVTK_TRANSFORM)


class PROPERTIES_PT_m3d_uv_shells(_Arrange, Panel):
    bl_label = "Shells"

    def draw(self, context):
        grid(self.layout, context, UV_SHELVES)


# --- Check

class _Check(_Page):
    page = "uv_check"


class PROPERTIES_PT_m3d_uv_checker(_Check, Panel):
    bl_label = "Checker"

    def draw(self, context):
        self.layout.operator("m3d.uv_checker", text="Checker Map", icon='TEXTURE', depress=checker_on(context))


class PROPERTIES_PT_m3d_uv_distortion(_Check, Panel):
    bl_label = "Distortion"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        space = uv_space(context)
        if space is None:
            reason(layout, "No UV Editor in this workspace")
            return
        uvedit = space.uv_editor
        layout.prop(uvedit, "show_stretch", text="Show Distortion", toggle=True)
        sub = layout.column()
        sub.active = uvedit.show_stretch
        sub.row().prop(uvedit, "display_stretch_type", expand=True)
        layout.prop(uvedit, "show_faces", text="Shaded UVs")


class PROPERTIES_PT_m3d_uv_density(_Check, Panel):
    bl_label = "Texel Density"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_uv
        layout.prop(s, "texture_size")
        layout.prop(s, "density")
        layout.label(text="Current: %.1f px/unit" % s.density_read if s.density_read else "Current: Read to measure")
        grid(layout, context, [(label, "m3d.uv_texel_density", icon, {"mode": mode}) for label, icon, mode in (
            ("Read", 'EYEDROPPER', 'READ'), ("Set", 'CHECKMARK', 'SET'), ("Match", 'FULLSCREEN_ENTER', 'MATCH'))],
            columns=3)
        layout.label(text="Match uses the active face's shell")


# --- Create

class _Create(_Page):
    page = "uv_create"


class PROPERTIES_PT_m3d_uv_auto(_Create, Panel):
    bl_label = "Auto Unwrap"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_uv
        layout.prop(s, "angle")
        layout.prop(s, "margin")
        row = layout.row()
        row.scale_y = 1.4
        _button(row, context, "Auto Unwrap", "m3d.uv_auto", 'MOD_UVPROJECT', {})
        reason(layout, "Cuts at sharp edges, unfolds, lays out")


class PROPERTIES_PT_m3d_uv_projections(_Create, Panel):
    bl_label = "Projections"

    def draw(self, context):
        grid(self.layout, context, UVTK_CREATE)
        self.layout.label(text="Planar and Camera-Based use the 3D view")


# --- UDIM

class _Udim(_Page):
    page = "uv_udim"
    need = None


class PROPERTIES_PT_m3d_uv_image(_Udim, Panel):
    bl_label = "Image"

    def draw(self, context):
        layout = self.layout
        space = uv_space(context)
        if space is None:
            reason(layout, "No UV Editor in this workspace")
            return
        layout.template_ID(space, "image")
        grid(layout, context, (("New Image", "image.new", 'FILE_NEW', {}),
                               ("New UDIM Image", "image.new", 'FILE_NEW', {"tiled": True})))


class PROPERTIES_PT_m3d_uv_tiles(_Udim, Panel):
    bl_label = "Tiles"

    @classmethod
    def page_poll(cls, context):
        space = uv_space(context)
        return space is not None and space.image is not None and space.image.source == 'TILED'

    def draw(self, context):
        layout = self.layout
        space = uv_space(context)
        image = space.image
        layout.template_list("IMAGE_UL_udim_tiles", "", image, "tiles", image.tiles, "active_index", rows=4)
        grid(layout, context, (("Add Tile", "image.tile_add", 'ADD', {}), ("Remove Tile", "image.tile_remove", 'REMOVE', {}),
                               ("Fill Tile", "image.tile_fill", 'COLOR', {})), columns=3)
        split_props(layout)
        layout.prop(space.uv_editor, "tile_grid_shape", text="Tile Grid")


class PROPERTIES_PT_m3d_uv_pack(_Udim, Panel):
    bl_label = "Pack to Tile"
    need = 'EDIT'

    def draw(self, context):
        grid(self.layout, context, UV_TILES, columns=1)


GATES = ("unwrap", "arrange", "check", "create")
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page) for page in GATES)


# -----------------------------------------------------------------------------
# Status Line

def draw_status_line(layout, context):
    """UV Status Line: file, modes, UV Sync, select mode and shell select, Live Unwrap, Distortion, Checker, texture size."""
    from m3d_ui import _call, draw_file_buttons, draw_workspace_picker
    draw_file_buttons(layout)
    row = layout.row(align=True)
    _call(row, "object.mode_set", 'OBJECT_DATAMODE', "Object Mode", depress=context.mode == 'OBJECT', mode='OBJECT')
    _call(row, "object.mode_set", 'EDITMODE_HLT', "Edit Mode", depress=context.mode == 'EDIT_MESH', mode='EDIT')
    ts, space = context.tool_settings, uv_space(context)
    if context.mode == 'EDIT_MESH':
        layout.prop(ts, "use_uv_select_sync", text="UV Sync", icon='UV_SYNC_SELECT', toggle=True)
        row = layout.row(align=True)
        if ts.use_uv_select_sync:
            row.template_edit_mode_selection()   # Synced: the mesh's own vertex / edge / face mode.
        else:
            row.prop(ts, "uv_select_mode", text="", expand=True)
        row.prop(ts, "use_uv_select_island", text="", icon='UV_ISLANDSEL', toggle=True)
    if space is not None:
        layout.prop(space.uv_editor, "use_live_unwrap", text="Live Unwrap", toggle=True)
        row = layout.row(align=True)
        row.prop(space.uv_editor, "show_stretch", text="Distortion", toggle=True)
        if space.uv_editor.show_stretch:
            row.prop(space.uv_editor, "display_stretch_type", text="")
    layout.operator("m3d.uv_checker", text="Checker", icon='TEXTURE', depress=checker_on(context))
    layout.prop(context.scene.m3d_uv, "texture_size", text="")
    draw_workspace_picker(layout, context)


# Shelf (items as in m3d_ui.SHELVES)
SHELF_UV = [
    ("m3d.uv_cut", 'SCULPTMODE_HLT', {}, "Cut"),
    ("m3d.uv_sew", 'AUTOMERGE_ON', {}, "Sew"),
    ("m3d.uv_unfold", 'UV', {}, "Unfold"),
    ("m3d.uv_optimize", 'MOD_SMOOTH', {}, "Optimize"),
    ("m3d.uv_layout", 'STICKY_UVS_DISABLE', {}, "Layout"),
    None,
    ("m3d.uv_auto", 'MOD_UVPROJECT', {}, "Auto Unwrap"),
]


classes = (
    M3D_UVSettings,
    M3D_OT_uv_cut,
    M3D_OT_uv_sew,
    M3D_OT_uv_unfold,
    M3D_OT_uv_optimize,
    M3D_OT_uv_layout,
    M3D_OT_uv_auto,
    M3D_OT_uv_texel_density,
    M3D_OT_uv_rotate,
    M3D_OT_uv_flip,
    M3D_OT_uv_checker,
    M3D_MT_uv_marking_menu,
    M3D_MT_uv_tools,
    IMAGE_PT_m3d_uvtk_selection,
    *(_section_panel("IMAGE_PT_m3d_uvtk_" + label.lower().replace(" ", "_"), label, items)
      for label, items in UV_TOOLKIT_SECTIONS[1:]),
    IMAGE_PT_m3d_uvtk_display,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_uv_cut,
    PROPERTIES_PT_m3d_uv_unfold,
    PROPERTIES_PT_m3d_uv_optimize,
    PROPERTIES_PT_m3d_uv_layout,
    PROPERTIES_PT_m3d_uv_pin,
    PROPERTIES_PT_m3d_uv_select,
    PROPERTIES_PT_m3d_uv_transform,
    PROPERTIES_PT_m3d_uv_shells,
    PROPERTIES_PT_m3d_uv_checker,
    PROPERTIES_PT_m3d_uv_distortion,
    PROPERTIES_PT_m3d_uv_density,
    PROPERTIES_PT_m3d_uv_auto,
    PROPERTIES_PT_m3d_uv_projections,
    PROPERTIES_PT_m3d_uv_image,
    PROPERTIES_PT_m3d_uv_tiles,
    PROPERTIES_PT_m3d_uv_pack,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_uv = PointerProperty(type=M3D_UVSettings)
    bpy.app.handlers.save_pre.append(checker_save_pre)
    bpy.app.handlers.save_post.append(checker_save_post)


def unregister():
    bpy.app.handlers.save_post.remove(checker_save_post)
    bpy.app.handlers.save_pre.remove(checker_save_pre)
    del bpy.types.Scene.m3d_uv
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
