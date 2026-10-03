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

    @classmethod
    def description(cls, _context, props):
        return "Polygon " + props.kind.title()


class MAYA_OT_call(Operator):
    """Run an operator in the 3D Viewport (used by top bar menus)"""
    bl_idname = "maya.call"
    bl_label = "Run in Viewport"
    bl_options = {'INTERNAL'}

    idname: bpy.props.StringProperty()
    props: bpy.props.StringProperty(default="{}")
    label: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return props.label or props.idname

    def invoke(self, context, _event):
        from ast import literal_eval
        areas = [a for a in context.screen.areas if a.type == 'VIEW_3D']
        if not areas:
            self.report({'WARNING'}, "No 3D Viewport in this workspace")
            return {'CANCELLED'}
        area = max(areas, key=lambda a: a.width * a.height)
        region = next(r for r in area.regions if r.type == 'WINDOW')
        mod, name = self.idname.split(".")
        try:
            with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT', **literal_eval(self.props))
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


class MAYA_OT_open_editor(Operator):
    """Open an editor in a new window (Maya Windows menu)"""
    bl_idname = "maya.open_editor"
    bl_label = "Open Editor Window"

    ui_type: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return "Open " + props.ui_type + " window"

    def execute(self, context):
        bpy.ops.wm.window_new()
        context.window_manager.windows[-1].screen.areas[0].ui_type = self.ui_type
        return {'FINISHED'}


class MAYA_OT_ungroup(Operator):
    """Maya Ungroup: remove the selected group nodes, keeping their children in place"""
    bl_idname = "maya.ungroup"
    bl_label = "Ungroup"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(ob.type == 'EMPTY' and ob.children for ob in context.selected_objects)

    def execute(self, context):
        for group in [ob for ob in context.selected_objects if ob.type == 'EMPTY' and ob.children]:
            for child in group.children:
                world = child.matrix_world.copy()
                child.parent = group.parent
                child.matrix_world = world
                child.select_set(True)
            bpy.data.objects.remove(group)
        return {'FINISHED'}


class MAYA_OT_reset_transformations(Operator):
    """Maya Reset Transformations: zero translate/rotate, unit scale"""
    bl_idname = "maya.reset_transformations"
    bl_label = "Reset Transformations"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for ob in context.selected_objects:
            ob.location = (0, 0, 0)
            ob.rotation_euler = (0, 0, 0)
            ob.scale = (1, 1, 1)
        return {'FINISHED'}


class MAYA_OT_boolean(Operator):
    """Maya Boolean: select the base object first, the tool object last (A then B gives A - B)"""
    bl_idname = "maya.boolean"
    bl_label = "Boolean"
    bl_options = {'REGISTER', 'UNDO'}

    operation: bpy.props.EnumProperty(items=(
        ('UNION', "Union", ""), ('DIFFERENCE', "Difference", ""), ('INTERSECT', "Intersection", ""),
    ))

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob and ob.type == 'MESH' and len(context.selected_objects) > 1

    def execute(self, context):
        tool = context.active_object
        for base in context.selected_objects:
            if base is tool or base.type != 'MESH':
                continue
            mod = base.modifiers.new(tool.name, 'BOOLEAN')
            mod.operation, mod.object = self.operation, tool
        tool.display_type = 'WIRE'
        tool.hide_render = True
        tool.select_set(False)
        return {'FINISHED'}


class MAYA_OT_separate(Operator):
    """Maya Separate: split a combined mesh into its separate shells"""
    bl_idname = "maya.separate"
    bl_label = "Separate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object and context.active_object.type == 'MESH'

    def execute(self, _context):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


class MAYA_OT_assign_material(Operator):
    """Maya Assign New Material: give the selection a new shader"""
    bl_idname = "maya.assign_material"
    bl_label = "Assign New Material"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mat = bpy.data.materials.new("standardSurface1")
        for ob in context.selected_objects:
            if ob.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
                ob.data.materials.clear()
                ob.data.materials.append(mat)
        return {'FINISHED'}


class MAYA_OT_lock_transforms(Operator):
    """Maya Lock and Hide: lock translate, rotate and scale of the selection"""
    bl_idname = "maya.lock_transforms"
    bl_label = "Lock Transforms"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for ob in context.selected_objects:
            ob.lock_location = ob.lock_rotation = ob.lock_scale = (True, True, True)
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


CHANNEL_BOX = "Channel Box / Layer Editor"


class VIEW3D_PT_maya_channel_box(Panel):
    """Maya Channel Box: transform channels, visibility and inputs (modifiers)"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CHANNEL_BOX
    bl_label = "Channel Box"

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


class VIEW3D_PT_maya_layer_editor(Panel):
    """Maya Layer Editor: display layers are collections here"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CHANNEL_BOX
    bl_label = "Layer Editor"

    def draw(self, context):
        layout = self.layout
        o = layout.operator("object.move_to_collection", text="Create Layer from Selected", icon='COLLECTION_NEW')
        o.collection_index, o.is_new, o.new_collection_name = 0, True, "layer1"
        col = layout.column(align=True)
        for lc in context.view_layer.layer_collection.children:
            row = col.row(align=True)
            row.prop(lc, "exclude", text="", invert_checkbox=True)
            row.prop(lc, "hide_viewport", text="", emboss=False)
            row.prop(lc.collection, "hide_select", text="", emboss=False)
            row.label(text=lc.name)


def _buttons(layout, items, columns=2):
    """Grid of Maya-style tool buttons: (label, idname, icon, props)."""
    grid = layout.grid_flow(columns=columns, even_columns=True, align=True)
    for label, idname, icon, props in items:
        o = grid.operator(idname, text=label, icon=icon)
        for k, v in props.items():
            setattr(o, k, v)


MTK_SELECT_TOOLS = (
    ("Marquee", "wm.tool_set_by_id", 'SELECT_SET', {"name": "builtin.select_box"}),
    ("Lasso", "wm.tool_set_by_id", 'MOD_CURVE', {"name": "builtin.select_lasso"}),
    ("Paint", "wm.tool_set_by_id", 'BRUSH_DATA', {"name": "builtin.select_circle"}),
    ("Tweak", "wm.tool_set_by_id", 'RESTRICT_SELECT_OFF', {"name": "builtin.select"}),
)
MTK_MESH = (
    ("Combine", "object.join", 'AUTOMERGE_ON', {}),
    ("Separate", "maya.separate", 'MOD_EXPLODE', {}),
    ("Smooth", "object.subdivision_set", 'MOD_SUBSURF', {"level": 1, "relative": False}),
    ("Mirror", "object.modifier_add", 'MOD_MIRROR', {"type": 'MIRROR'}),
    ("Union", "maya.boolean", 'SELECT_EXTEND', {"operation": 'UNION'}),
    ("Difference", "maya.boolean", 'SELECT_SUBTRACT', {"operation": 'DIFFERENCE'}),
    ("Intersection", "maya.boolean", 'SELECT_INTERSECT', {"operation": 'INTERSECT'}),
    ("Fill Hole", "mesh.fill", 'SNAP_FACE', {}),
)
MTK_COMPONENTS = (
    ("Extrude", "view3d.edit_mesh_extrude_move_normal", 'FACESEL', {}),
    ("Bevel", "mesh.bevel", 'MOD_BEVEL', {}),
    ("Bridge", "mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
    ("Connect", "mesh.vert_connect_path", 'MOD_EDGESPLIT', {}),
    ("Merge", "mesh.remove_doubles", 'AUTOMERGE_ON', {}),
    ("Merge to Center", "mesh.merge", 'PIVOT_MEDIAN', {"type": 'CENTER'}),
    ("Collapse", "mesh.merge", 'FULLSCREEN_EXIT', {"type": 'COLLAPSE'}),
    ("Poke", "mesh.poke", 'DECORATE', {}),
    ("Detach", "mesh.split", 'MOD_EXPLODE', {}),
    ("Chamfer Vertex", "mesh.bevel", 'VERTEXSEL', {"affect": 'VERTICES'}),
    ("Delete Edge/Vertex", "mesh.dissolve_mode", 'X', {}),
    ("Flip", "mesh.flip_normals", 'NORMALS_FACE', {}),
)
MTK_TOOLS = (
    ("Multi-Cut", "mesh.knife_tool", 'MOD_SIMPLEDEFORM', {}),
    ("Quad Draw", "wm.tool_set_by_id", 'GREASEPENCIL', {"name": "builtin.poly_build"}),
    ("Insert Edge Loop", "mesh.loopcut_slide", 'MOD_EDGESPLIT', {}),
    ("Offset Edge Loop", "mesh.offset_edge_loops_slide", 'SNAP_EDGE', {}),
    ("Slide", "transform.edge_slide", 'ARROW_LEFTRIGHT', {}),
    ("Target Weld", "mesh.merge", 'AUTOMERGE_OFF', {"type": 'LAST'}),
    ("Create Polygon", "mesh.edge_face_add", 'SNAP_FACE', {}),
    ("Crease", "transform.edge_crease", 'MOD_SMOOTH', {}),
)


class _MayaToolkitPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Modeling Toolkit"


class VIEW3D_PT_maya_mtk_selection(_MayaToolkitPanel, Panel):
    bl_label = "Selection"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("object.mode_set", text="", icon='OBJECT_DATAMODE',
                     depress=context.mode == 'OBJECT').mode = 'OBJECT'
        ob = context.active_object
        if ob is not None and ob.type == 'MESH':
            sel = tuple(context.tool_settings.mesh_select_mode) if context.mode == 'EDIT_MESH' else (False,) * 3
            for i, (_label, mode, icon) in enumerate((("Vertex", 'VERT', 'VERTEXSEL'), ("Edge", 'EDGE', 'EDGESEL'),
                                                     ("Face", 'FACE', 'FACESEL'))):
                o = row.operator("object.mode_set_with_submode", text="", icon=icon,
                                 depress=sel[i] and sum(sel) == 1)
                o.mode, o.mesh_select_mode = 'EDIT', {mode}
            o = row.operator("object.mode_set_with_submode", text="Multi", icon='MOD_WIREFRAME', depress=sum(sel) > 1)
            o.mode, o.mesh_select_mode = 'EDIT', {'VERT', 'EDGE', 'FACE'}
        _buttons(layout, MTK_SELECT_TOOLS)
        layout.prop(context.space_data.shading, "show_xray", text="X-Ray (select through)")


class VIEW3D_PT_maya_mtk_soft_selection(_MayaToolkitPanel, Panel):
    bl_label = "Soft Selection"

    def draw_header(self, context):
        prop = "use_proportional_edit" if context.mode == 'EDIT_MESH' else "use_proportional_edit_objects"
        self.layout.prop(context.tool_settings, prop, text="")

    def draw(self, context):
        ts = context.tool_settings
        col = self.layout.column()
        col.prop(ts, "proportional_size", text="Falloff Radius")
        col.prop(ts, "proportional_edit_falloff", text="Falloff Curve")
        if context.mode == 'EDIT_MESH':
            col.prop(ts, "use_proportional_connected", text="Falloff Mode: Surface")


class VIEW3D_PT_maya_mtk_symmetry(_MayaToolkitPanel, Panel):
    bl_label = "Symmetry"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def draw(self, context):
        row = self.layout.row(align=True)
        mesh = context.active_object.data
        for axis in "xyz":
            row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)


class VIEW3D_PT_maya_mtk_mesh(_MayaToolkitPanel, Panel):
    bl_label = "Mesh"

    def draw(self, _context):
        _buttons(self.layout, MTK_MESH)


class VIEW3D_PT_maya_mtk_components(_MayaToolkitPanel, Panel):
    bl_label = "Components"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, _context):
        _buttons(self.layout, MTK_COMPONENTS)


class VIEW3D_PT_maya_mtk_tools(_MayaToolkitPanel, Panel):
    bl_label = "Tools"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, _context):
        _buttons(self.layout, MTK_TOOLS)


class _MayaAttributePanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Attribute Editor"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None


class VIEW3D_PT_maya_ae_transform(_MayaAttributePanel, Panel):
    bl_label = "Transform Attributes"

    @classmethod
    def poll(cls, _context):
        return True  # Keep the tab visible with nothing selected, like Maya.

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        if ob is None:
            layout.label(text="Nothing selected")
            return
        row = layout.row(align=True)
        row.prop(ob, "name", text="transform")
        row.operator("maya.open_editor", text="", icon='WINDOW').ui_type = 'PROPERTIES'
        col = layout.column()
        col.prop(ob, "location", text="Translate")
        col.prop(ob, "rotation_euler", text="Rotate")
        col.prop(ob, "rotation_mode", text="Rotate Order")
        col.prop(ob, "scale", text="Scale")
        col.prop(ob, "hide_viewport", text="Visibility", invert_checkbox=True)


class VIEW3D_PT_maya_ae_display(_MayaAttributePanel, Panel):
    bl_label = "Display"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        ob = context.active_object
        col = self.layout.column()
        col.prop(ob, "display_type", text="Display As")
        col.prop(ob, "show_wire", text="Wireframe on Shaded")
        col.prop(ob, "show_in_front", text="Always Draw on Top")
        col.prop(ob, "show_axis", text="Display Local Axis")
        col.prop(ob, "show_name", text="Display Name")
        col.prop(ob, "color", text="Wireframe Color")


class VIEW3D_PT_maya_ae_shape(_MayaAttributePanel, Panel):
    bl_label = "Shape"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def draw(self, context):
        ob = context.active_object
        mesh = ob.data
        col = self.layout.column()
        col.prop(mesh, "name", text="mesh")
        col.label(text=f"Vertices: {len(mesh.vertices)}   Edges: {len(mesh.edges)}   Faces: {len(mesh.polygons)}")
        for mod in ob.modifiers:
            row = col.row(align=True)
            row.prop(mod, "show_viewport", text="")
            row.prop(mod, "name", text="")


class VIEW3D_PT_maya_ae_material(_MayaAttributePanel, Panel):
    bl_label = "Material"

    def draw(self, context):
        layout = self.layout
        mat = context.active_object.active_material
        if mat is None:
            layout.operator("maya.assign_material", icon='MATERIAL')
            return
        layout.prop(mat, "name", text="shader")
        bsdf = mat.node_tree and next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            layout.prop(mat, "diffuse_color", text="Color")
        else:
            col = layout.column()
            for name, label in (("Base Color", "Base Color"), ("Metallic", "Metalness"),
                                ("Roughness", "Specular Roughness"), ("Emission Color", "Emission Color"),
                                ("Emission Strength", "Emission Weight"), ("Alpha", "Opacity")):
                sock = bsdf.inputs.get(name)
                if sock is not None:
                    col.prop(sock, "default_value", text=label)
        layout.operator("maya.open_editor", text="Open Hypershade", icon='NODE_MATERIAL').ui_type = 'ShaderNodeTree'


def _main_view3d_areas():
    for screen in bpy.data.screens:
        if screen.name in {"Maya Classic", "Modeling - Standard"}:
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
                    region.active_panel_category = CHANNEL_BOX
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
    MAYA_OT_call,
    MAYA_OT_open_editor,
    MAYA_OT_ungroup,
    MAYA_OT_reset_transformations,
    MAYA_OT_boolean,
    MAYA_OT_separate,
    MAYA_OT_assign_material,
    MAYA_OT_lock_transforms,
    MAYA_MT_marking_menu,
    MAYA_MT_poly_tools,
    VIEW3D_PT_maya_channel_box,
    VIEW3D_PT_maya_layer_editor,
    VIEW3D_PT_maya_ae_transform,
    VIEW3D_PT_maya_ae_display,
    VIEW3D_PT_maya_ae_shape,
    VIEW3D_PT_maya_ae_material,
    VIEW3D_PT_maya_mtk_selection,
    VIEW3D_PT_maya_mtk_soft_selection,
    VIEW3D_PT_maya_mtk_symmetry,
    VIEW3D_PT_maya_mtk_mesh,
    VIEW3D_PT_maya_mtk_components,
    VIEW3D_PT_maya_mtk_tools,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_factory_startup_post.append(show_channel_box)


def unregister():
    bpy.app.handlers.load_factory_startup_post.remove(show_channel_box)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
