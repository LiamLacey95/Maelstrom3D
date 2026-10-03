# SPDX-FileCopyrightText: 2026 MayaBlender
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya-style UI for MayaBlender: marking menus, polygon shelf, Channel Box,
smooth mesh preview (1/2/3) and grouping (Ctrl+G).
"""

import bpy
from bpy.types import Menu, Operator, Panel
from mathutils import Vector

SMOOTH_MOD = "MayaSmoothPreview"


class MAYA_OT_smooth_preview(Operator):
    """Maya smooth mesh preview: 1 off, 2 cage + smooth, 3 smooth"""
    bl_idname = "maya.smooth_preview"
    bl_label = "Smooth Mesh Preview"
    bl_options = {'REGISTER', 'UNDO'}

    level: bpy.props.EnumProperty(items=(
        ('OFF', "Off", "Original mesh"),
        ('CAGE', "Cage + Smooth", "Smoothed mesh with original wire cage"),
        ('SMOOTH', "Smooth", "Smoothed mesh"),
    ))

    def execute(self, context):
        obs = {ob for ob in context.selected_objects if ob.type == 'MESH'}
        if context.edit_object:
            obs.add(context.edit_object)
        for ob in obs:
            mod = ob.modifiers.get(SMOOTH_MOD)
            if self.level == 'OFF':
                if mod:
                    ob.modifiers.remove(mod)
                ob.show_wire = False
                continue
            if mod is None:
                mod = ob.modifiers.new(SMOOTH_MOD, 'SUBSURF')
                mod.levels = 2
                mod.show_on_cage = False
            ob.show_wire = self.level == 'CAGE'
        return {'FINISHED'}


class MAYA_OT_group(Operator):
    """Maya Group: parent the selection under a new empty at its center"""
    bl_idname = "maya.group"
    bl_label = "Group"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def execute(self, context):
        obs = context.selected_objects
        group = bpy.data.objects.new("group1", None)
        context.collection.objects.link(group)
        group.location = sum((ob.matrix_world.translation for ob in obs), Vector()) / len(obs)
        context.view_layer.update()
        for ob in obs:
            world = ob.matrix_world.copy()
            ob.parent = group
            ob.matrix_world = world
            ob.select_set(False)
        group.select_set(True)
        context.view_layer.objects.active = group
        return {'FINISHED'}


class MAYA_OT_add_primitive(Operator):
    """Create a Maya-sized polygon primitive at the origin"""
    bl_idname = "maya.add_primitive"
    bl_label = "Polygon Primitive"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=(
        ('CUBE', "Cube", ""), ('SPHERE', "Sphere", ""), ('CYLINDER', "Cylinder", ""),
        ('CONE', "Cone", ""), ('PLANE', "Plane", ""), ('TORUS', "Torus", ""),
    ))

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        mesh = bpy.ops.mesh
        {
            'CUBE': lambda: mesh.primitive_cube_add(size=1, location=(0, 0, 0)),
            'SPHERE': lambda: mesh.primitive_uv_sphere_add(radius=1, segments=20, ring_count=20, location=(0, 0, 0)),
            'CYLINDER': lambda: mesh.primitive_cylinder_add(radius=1, depth=2, vertices=20, location=(0, 0, 0)),
            'CONE': lambda: mesh.primitive_cone_add(radius1=1, depth=2, vertices=20, location=(0, 0, 0)),
            'PLANE': lambda: mesh.primitive_plane_add(size=1, location=(0, 0, 0)),
            'TORUS': lambda: mesh.primitive_torus_add(major_radius=1, minor_radius=0.5, location=(0, 0, 0)),
        }[self.kind]()
        return {'FINISHED'}


def _submode(layout, text, mode, icon):
    op = layout.operator("object.mode_set_with_submode", text=text, icon=icon)
    op.mode = 'EDIT'
    op.mesh_select_mode = mode


class MAYA_MT_marking_menu(Menu):
    """Right-click marking menu (component modes)"""
    bl_label = "Marking Menu"

    def draw(self, context):
        pie = self.layout.menu_pie()
        ob = context.active_object
        is_mesh = ob is not None and ob.type == 'MESH'
        edit = context.mode == 'EDIT_MESH'
        # Pie order: W, E, S, N, NW, NE, SW, SE.
        if is_mesh:
            _submode(pie, "Vertex", {'VERT'}, 'VERTEXSEL')
        else:
            pie.separator()
        pie.operator("object.mode_set", text="Object Mode", icon='OBJECT_DATAMODE').mode = 'OBJECT'
        if is_mesh:
            _submode(pie, "Face", {'FACE'}, 'FACESEL')
            _submode(pie, "Edge", {'EDGE'}, 'EDGESEL')
            _submode(pie, "Multi", {'VERT', 'EDGE', 'FACE'}, 'MOD_WIREFRAME')
        else:
            pie.separator()
            pie.separator()
            pie.separator()
        if edit:
            pie.operator("mesh.select_all", text="Select All", icon='SELECT_EXTEND').action = 'SELECT'
            pie.menu("VIEW3D_MT_edit_mesh_context_menu", text="More...", icon='COLLAPSEMENU')
            pie.operator("mesh.select_all", text="Invert Selection", icon='SELECT_DIFFERENCE').action = 'INVERT'
        else:
            pie.operator("object.select_all", text="Select All", icon='SELECT_EXTEND').action = 'SELECT'
            pie.menu("VIEW3D_MT_object_context_menu", text="More...", icon='COLLAPSEMENU')
            pie.operator("maya.group", text="Group", icon='EMPTY_AXIS')


class MAYA_MT_poly_tools(Menu):
    """Shift+right-click polygon tools marking menu"""
    bl_label = "Polygon Tools"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        pie.operator("view3d.edit_mesh_extrude_move_normal", text="Extrude", icon='FACESEL')
        pie.operator("mesh.bevel", text="Bevel", icon='MOD_BEVEL')
        pie.operator("mesh.remove_doubles", text="Merge", icon='AUTOMERGE_ON')
        pie.operator("mesh.loopcut_slide", text="Insert Edge Loop", icon='MOD_EDGESPLIT')
        pie.operator("mesh.bridge_edge_loops", text="Bridge", icon='MOD_LATTICE')
        pie.operator("mesh.knife_tool", text="Multi-Cut", icon='MOD_SIMPLEDEFORM')
        pie.operator("mesh.fill", text="Fill Hole", icon='SNAP_FACE')
        pie.operator("mesh.dissolve_mode", text="Delete Edge/Vertex", icon='X')


class VIEW3D_PT_maya_channel_box(Panel):
    """Maya Channel Box: transform channels, visibility and inputs (modifiers)"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Channel Box"
    bl_label = "Channel Box"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        if ob is None:
            layout.label(text="Nothing selected")
            return
        layout.prop(ob, "name", text="")
        col = layout.column(align=True)
        for label, attr in (("Translate", "location"), ("Rotate", "rotation_euler"), ("Scale", "scale")):
            for i, axis in enumerate("XYZ"):
                col.prop(ob, attr, index=i, text=f"{label} {axis}")
        col.prop(ob, "hide_viewport", text="Visibility", invert_checkbox=True, toggle=True)

        if ob.data is not None:
            layout.label(text="SHAPES")
            layout.prop(ob.data, "name", text="")
        if ob.modifiers:
            layout.label(text="INPUTS")
            col = layout.column(align=True)
            for mod in ob.modifiers:
                row = col.row(align=True)
                row.prop(mod, "show_viewport", text="")
                row.label(text=mod.name)


SHELF = (
    ("maya.add_primitive", 'MESH_CUBE', {"kind": 'CUBE'}),
    ("maya.add_primitive", 'MESH_UVSPHERE', {"kind": 'SPHERE'}),
    ("maya.add_primitive", 'MESH_CYLINDER', {"kind": 'CYLINDER'}),
    ("maya.add_primitive", 'MESH_CONE', {"kind": 'CONE'}),
    ("maya.add_primitive", 'MESH_PLANE', {"kind": 'PLANE'}),
    ("maya.add_primitive", 'MESH_TORUS', {"kind": 'TORUS'}),
    None,
    ("object.join", 'AUTOMERGE_ON', {}),                                      # Combine.
    ("object.subdivision_set", 'MOD_SUBSURF', {"level": 1, "relative": False}),  # Smooth.
    None,
    ("object.origin_set", 'PIVOT_BOUNDBOX', {"type": 'ORIGIN_GEOMETRY'}),     # Center Pivot.
    ("object.transform_apply", 'FREEZE', {"location": True, "rotation": True, "scale": True}),
    ("object.convert", 'TRASH', {"target": 'MESH'}),                          # Delete History.
)


def draw_shelf(self, context):
    if context.region.alignment != 'RIGHT':
        return
    row = self.layout.row(align=True)
    for item in SHELF:
        if item is None:
            row.separator()
            continue
        idname, icon, props = item
        op = row.operator(idname, text="", icon=icon)
        for k, v in props.items():
            setattr(op, k, v)
    self.layout.separator(factor=2.0)


def _main_view3d_areas():
    for screen in bpy.data.screens:
        if screen.name in {"Layout", "Modeling"}:
            yield from (area for area in screen.areas if area.type == 'VIEW_3D')


_tab_tries = 0


def _select_channel_box_tab():
    # Sidebar tabs only exist after the first redraw, so retry until they do.
    global _tab_tries
    pending = False
    for area in _main_view3d_areas():
        for region in area.regions:
            if region.type == 'UI':
                if region.is_property_readonly("active_panel_category"):
                    pending = True
                else:
                    region.active_panel_category = "Channel Box"
    _tab_tries -= 1
    return 0.25 if pending and _tab_tries > 0 else None


@bpy.app.handlers.persistent
def show_channel_box(*_args):
    """Open the sidebar on the Channel Box tab in the main 3D views, like Maya's right-hand dock."""
    if bpy.app.background:
        return
    for area in _main_view3d_areas():
        area.spaces.active.show_region_ui = True
    global _tab_tries
    _tab_tries = 20
    bpy.app.timers.register(_select_channel_box_tab, first_interval=0.25)


classes = (
    MAYA_OT_smooth_preview,
    MAYA_OT_group,
    MAYA_OT_add_primitive,
    MAYA_MT_marking_menu,
    MAYA_MT_poly_tools,
    VIEW3D_PT_maya_channel_box,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_HT_upper_bar.prepend(draw_shelf)
    bpy.app.handlers.load_factory_startup_post.append(show_channel_box)


def unregister():
    bpy.app.handlers.load_factory_startup_post.remove(show_channel_box)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_shelf)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
