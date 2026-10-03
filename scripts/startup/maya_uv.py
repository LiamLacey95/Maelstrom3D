# SPDX-FileCopyrightText: 2026 MayaBlender
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya-style UV editing for MayaBlender: UV Toolkit panel, UV marking menus,
Cut / Sew / Unfold / Layout workflow and the checker map.
"""

import math

import bpy
from bpy.types import Menu, Operator, Panel

UV_TOOLKIT = "UV Toolkit"
CHECKER = "mayaUVChecker"


def _in_uv_editor(context):
    space = context.space_data
    return space is not None and space.type == 'IMAGE_EDITOR'


class MAYA_OT_uv_cut(Operator):
    """Maya Cut: split UVs along the selected edges (marks them as seams for Unfold)"""
    bl_idname = "maya.uv_cut"
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


class MAYA_OT_uv_sew(Operator):
    """Maya Sew: join UVs along the selected edges"""
    bl_idname = "maya.uv_sew"
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


class MAYA_OT_uv_unfold(Operator):
    """Maya Unfold: flatten the selected UV shells along their cuts, keeping pinned UVs"""
    bl_idname = "maya.uv_unfold"
    bl_label = "Unfold"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, _context):
        bpy.ops.uv.unwrap(method='MINIMUM_STRETCH', margin=0.001)
        return {'FINISHED'}


class MAYA_OT_uv_rotate(Operator):
    """Rotate the selected UVs by 90 degrees"""
    bl_idname = "maya.uv_rotate"
    bl_label = "Rotate UVs 90"
    bl_options = {'REGISTER', 'UNDO'}

    clockwise: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and _in_uv_editor(context)

    def execute(self, _context):
        bpy.ops.transform.rotate(value=-math.pi / 2 if self.clockwise else math.pi / 2)
        return {'FINISHED'}


class MAYA_OT_uv_flip(Operator):
    """Maya Flip: mirror the selected UVs in U or V"""
    bl_idname = "maya.uv_flip"
    bl_label = "Flip UVs"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(items=(('U', "U", ""), ('V', "V", "")))

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and _in_uv_editor(context)

    def execute(self, _context):
        bpy.ops.transform.mirror(constraint_axis=(self.axis == 'U', self.axis == 'V', False))
        return {'FINISHED'}


class MAYA_OT_uv_checker(Operator):
    """Maya checker map: show a UV checker texture on the selected meshes (toggle)"""
    bl_idname = "maya.uv_checker"
    bl_label = "Checker Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obs = {ob for ob in context.selected_objects if ob.type == 'MESH'}
        if context.edit_object:
            obs.add(context.edit_object)
        checker = self.checker_material()
        for ob in obs:
            slots = ob.data.materials
            if CHECKER in ob:
                slots.clear()  # Checker on: put the original materials back.
                for name in ob[CHECKER]:
                    slots.append(bpy.data.materials.get(name))
                del ob[CHECKER]
            else:
                ob[CHECKER] = [m.name if m else "" for m in slots]
                slots.clear()
                slots.append(checker)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.color_type = 'TEXTURE'
        return {'FINISHED'}

    @staticmethod
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
    ("Flip U", "maya.uv_flip", 'MOD_MIRROR', {"axis": 'U'}),
    ("Flip V", "maya.uv_flip", 'MOD_MIRROR', {"axis": 'V'}),
    ("Rotate 90 CW", "maya.uv_rotate", 'LOOP_FORWARDS', {"clockwise": True}),
    ("Rotate 90 CCW", "maya.uv_rotate", 'LOOP_BACK', {"clockwise": False}),
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
    ("Cut", "maya.uv_cut", 'SCULPTMODE_HLT', {}),
    ("Sew", "maya.uv_sew", 'AUTOMERGE_ON', {}),
    ("Split", "uv.select_split", 'UNLINKED', {}),
    ("Merge", "uv.remove_doubles", 'AUTOMERGE_OFF', {}),
    ("Auto Seams (from shells)", "uv.seams_from_islands", 'UV_ISLANDSEL', {}),
)
UVTK_UNFOLD = (
    ("Unfold", "maya.uv_unfold", 'UV', {}),
    ("Optimize", "uv.minimize_stretch", 'MOD_SMOOTH', {}),
    ("Layout", "uv.pack_islands", 'STICKY_UVS_DISABLE', {"margin": 0.01}),
    ("Orient Shells", "uv.align_rotation", 'ORIENTATION_GIMBAL', {"method": 'AUTO'}),
    ("Match Texel Scale", "uv.average_islands_scale", 'FULLSCREEN_ENTER', {}),
)

UV_TOOLKIT_SECTIONS = (
    ("Selection", UVTK_SELECT), ("Pin", UVTK_PIN), ("Transform", UVTK_TRANSFORM), ("Create", UVTK_CREATE),
    ("Cut and Sew", UVTK_CUT_SEW), ("Unfold", UVTK_UNFOLD),
)


def _uv_buttons(layout, context, items):
    from maya_mode import _buttons
    _buttons(layout, context, items)


class _UVToolkitPanel:
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = UV_TOOLKIT

    @classmethod
    def poll(cls, context):
        return context.space_data.show_uvedit


class IMAGE_PT_maya_uvtk_selection(_UVToolkitPanel, Panel):
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


class IMAGE_PT_maya_uvtk_display(_UVToolkitPanel, Panel):
    bl_label = "Display"

    def draw(self, context):
        layout = self.layout
        layout.operator("maya.uv_checker", icon='TEXTURE')
        layout.prop(context.space_data.uv_editor, "show_stretch", text="Distortion")
        layout.prop(context.space_data.uv_editor, "show_faces", text="Shaded UVs")


class MAYA_MT_uv_marking_menu(Menu):
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


class MAYA_MT_uv_tools(Menu):
    """UV Editor Shift+right-click marking menu: the UV workflow"""
    bl_label = "UV Tools"

    def draw(self, context):
        pie = self.layout.menu_pie()
        for label, idname, icon, props in (
            ("Cut", "maya.uv_cut", 'SCULPTMODE_HLT', {}),
            ("Sew", "maya.uv_sew", 'AUTOMERGE_ON', {}),
            ("Layout", "uv.pack_islands", 'STICKY_UVS_DISABLE', {"margin": 0.01}),
            ("Unfold", "maya.uv_unfold", 'UV', {}),
            ("Straighten", "uv.align", 'IPO_LINEAR', {"axis": 'ALIGN_S'}),
            ("Orient Shells", "uv.align_rotation", 'ORIENTATION_GIMBAL', {"method": 'AUTO'}),
            ("Optimize", "uv.minimize_stretch", 'MOD_SMOOTH', {}),
            ("Automatic", "uv.smart_project", 'MOD_UVPROJECT', {}),
        ):
            o = pie.operator(idname, text=label, icon=icon)
            for k, v in props.items():
                setattr(o, k, v)


_tab_tries = 0


def _select_uv_toolkit_tab():
    # Sidebar tabs only exist after the first redraw, so retry until they do.
    global _tab_tries
    pending = False
    for area in _uv_editor_areas():
        for region in area.regions:
            if region.type == 'UI':
                if region.is_property_readonly("active_panel_category"):
                    pending = True
                else:
                    region.active_panel_category = UV_TOOLKIT
    _tab_tries -= 1
    return 0.25 if pending and _tab_tries > 0 else None


def _uv_editor_areas():
    screen = bpy.data.screens.get("UV Editing")
    return [a for a in screen.areas if a.type == 'IMAGE_EDITOR'] if screen else []


@bpy.app.handlers.persistent
def show_uv_toolkit(*_args):
    """Dock the UV Toolkit on the right of the UV Editor, like Maya."""
    if bpy.app.background:
        return
    global _tab_tries
    for area in _uv_editor_areas():
        area.spaces.active.show_region_ui = True
    _tab_tries = 20
    bpy.app.timers.register(_select_uv_toolkit_tab, first_interval=0.25)


classes = (
    MAYA_OT_uv_cut,
    MAYA_OT_uv_sew,
    MAYA_OT_uv_unfold,
    MAYA_OT_uv_rotate,
    MAYA_OT_uv_flip,
    MAYA_OT_uv_checker,
    MAYA_MT_uv_marking_menu,
    MAYA_MT_uv_tools,
    IMAGE_PT_maya_uvtk_selection,
    *(_section_panel("IMAGE_PT_maya_uvtk_" + label.lower().replace(" ", "_"), label, items)
      for label, items in UV_TOOLKIT_SECTIONS[1:]),
    IMAGE_PT_maya_uvtk_display,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_factory_startup_post.append(show_uv_toolkit)


def unregister():
    bpy.app.handlers.load_factory_startup_post.remove(show_uv_toolkit)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
