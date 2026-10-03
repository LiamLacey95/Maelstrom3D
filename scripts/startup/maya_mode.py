# SPDX-FileCopyrightText: 2026 MayaBlender
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya-style tools for MayaBlender: Maya operators, marking menus and the right-hand dock
(Channel Box / Layer Editor and Modeling Toolkit tabs of the Attribute Editor area).
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


class MAYA_OT_dock_tab(Operator):
    """Show a tab of the right-hand dock (Channel Box, Attribute Editor, Modeling Toolkit)"""
    bl_idname = "maya.dock_tab"
    bl_label = "Dock Tab"

    tab: bpy.props.StringProperty(default='CHANNEL_BOX')
    toggle: bpy.props.BoolProperty(description="Ctrl+A: switch between Channel Box and Attribute Editor")

    def execute(self, context):
        docks = [a for a in context.screen.areas if a.type == 'PROPERTIES']
        if not docks:
            bpy.ops.maya.open_editor(ui_type='PROPERTIES')
            return {'FINISHED'}
        space = max(docks, key=lambda a: a.height).spaces.active
        tab = self.tab
        if self.toggle:
            tab = 'OBJECT' if space.context == 'CHANNEL_BOX' else 'CHANNEL_BOX'
        space.context = tab
        return {'FINISHED'}


class MAYA_OT_delete_components(Operator):
    """Maya Delete: faces are removed, edges and vertices are dissolved (the mesh stays closed)"""
    bl_idname = "maya.delete_components"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        vert, edge, face = context.tool_settings.mesh_select_mode
        if face:
            bpy.ops.mesh.delete(type='FACE')
        elif edge:
            bpy.ops.mesh.dissolve_edges()
        else:
            bpy.ops.mesh.dissolve_verts()
        return {'FINISHED'}


class MAYA_OT_connect(Operator):
    """Maya Connect: edges get a new edge loop through their midpoints, vertices get joined by an edge"""
    bl_idname = "maya.connect"
    bl_label = "Connect"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        if context.tool_settings.mesh_select_mode[1]:
            bpy.ops.mesh.subdivide_edgering(number_cuts=1)
        else:
            bpy.ops.mesh.vert_connect_path()
        return {'FINISHED'}


class MAYA_OT_fill_hole(Operator):
    """Maya Fill Hole: fill the selected border, or every hole of the selected meshes"""
    bl_idname = "maya.fill_hole"
    bl_label = "Fill Hole"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' or (context.active_object and context.active_object.type == 'MESH')

    def execute(self, context):
        if context.mode == 'EDIT_MESH':
            bpy.ops.mesh.fill()
            return {'FINISHED'}
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.fill_holes(sides=0)
        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


class MAYA_OT_snap_hold(Operator):
    """Maya hold-to-snap: X grid, C curve (edge), V point (vertex)"""
    bl_idname = "maya.snap_hold"
    bl_label = "Hold to Snap"
    bl_options = {'INTERNAL'}

    element: bpy.props.StringProperty(default='GRID')
    enable: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        ts = context.tool_settings
        ts.use_snap = self.enable
        if self.enable:
            ts.snap_elements = {self.element}
        return {'FINISHED'}


class MAYA_MT_convert_selection_pie(Menu):
    """Ctrl+right-click marking menu: convert the component selection"""
    bl_label = "Convert Selection"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        # Pie order: W, E, S, N, NW, NE, SW, SE.
        pie.operator("mesh.select_mode", text="To Vertices", icon='VERTEXSEL').type = 'VERT'
        pie.operator("mesh.select_mode", text="To Faces", icon='FACESEL').type = 'FACE'
        pie.operator("mesh.select_linked", text="To Shell", icon='MESH_DATA')
        pie.operator("mesh.select_mode", text="To Edges", icon='EDGESEL').type = 'EDGE'
        pie.operator("mesh.select_edge_loop_multi", text="To Edge Loop")
        pie.operator("mesh.select_edge_ring_multi", text="To Edge Ring")
        pie.operator("mesh.region_to_loop", text="To Border")
        pie.operator("mesh.select_more", text="Grow", icon='ADD')


class MAYA_MT_create_pie(Menu):
    """Shift+right-click marking menu in object mode: create polygon primitives"""
    bl_label = "Create"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        for kind, icon in (('SPHERE', 'MESH_UVSPHERE'), ('CUBE', 'MESH_CUBE'), ('CYLINDER', 'MESH_CYLINDER'),
                           ('PLANE', 'MESH_PLANE'), ('CONE', 'MESH_CONE'), ('TORUS', 'MESH_TORUS')):
            pie.operator("maya.add_primitive", text=kind.title(), icon=icon).kind = kind
        pie.operator("object.camera_add", text="Camera", icon='CAMERA_DATA')
        pie.menu("VIEW3D_MT_light_add", text="Lights", icon='LIGHT')


class _MayaDockPanel:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'


class PROPERTIES_PT_maya_channel_box(_MayaDockPanel, Panel):
    """Maya Channel Box: transform channels, visibility and inputs (modifiers)"""
    bl_context = "channel_box"
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


class PROPERTIES_PT_maya_layer_editor(_MayaDockPanel, Panel):
    """Maya Layer Editor: display layers are collections here"""
    bl_context = "channel_box"
    bl_label = "Layer Editor"

    def draw(self, context):
        layout = self.layout
        _button(layout, context, "Create Layer from Selected", "object.move_to_collection", 'COLLECTION_NEW',
                    {"collection_index": 0, "is_new": True, "new_collection_name": "layer1"})
        col = layout.column(align=True)
        for lc in context.view_layer.layer_collection.children:
            row = col.row(align=True)
            row.prop(lc, "exclude", text="", invert_checkbox=True)
            row.prop(lc, "hide_viewport", text="", emboss=False)
            row.prop(lc.collection, "hide_select", text="", emboss=False)
            row.label(text=lc.name)


def _button(layout, context, label, idname, icon, props, depress=False):
    """Operator button; viewport-only commands run in the 3D Viewport through `maya.call`."""
    from maya_ui import needs_view3d, _poll
    in_view3d = context.area is not None and context.area.type == 'VIEW_3D'
    if not in_view3d and (needs_view3d(idname) or not _poll(idname)):
        o = layout.operator("maya.call", text=label, icon=icon, depress=depress)
        o.idname, o.props, o.label = idname, repr(props), label
        return o
    o = layout.operator(idname, text=label, icon=icon, depress=depress)
    for k, v in props.items():
        setattr(o, k, v)
    return o


def _buttons(layout, context, items, columns=2):
    """Grid of Maya-style tool buttons: (label, idname, icon, props)."""
    grid = layout.grid_flow(columns=columns, even_columns=True, align=True)
    for label, idname, icon, props in items:
        _button(grid, context, label, idname, icon, props)


def _view3d_space(context):
    areas = [a for a in context.screen.areas if a.type == 'VIEW_3D']
    return max(areas, key=lambda a: a.width * a.height).spaces.active if areas else None


MTK_SELECT_TOOLS = (
    ("Marquee", "wm.tool_set_by_id", 'SELECT_SET', {"name": "builtin.select_box"}),
    ("Lasso", "wm.tool_set_by_id", 'MOD_CURVE', {"name": "builtin.select_lasso"}),
    ("Drag (Paint)", "wm.tool_set_by_id", 'BRUSH_DATA', {"name": "builtin.select_circle"}),
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
    ("Fill Hole", "maya.fill_hole", 'SNAP_FACE', {}),
)
MTK_COMPONENTS = (
    ("Extrude", "view3d.edit_mesh_extrude_move_normal", 'FACESEL', {}),
    ("Bevel", "mesh.bevel", 'MOD_BEVEL', {"offset_type": 'PERCENT'}),
    ("Bridge", "mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
    ("Connect", "maya.connect", 'MOD_EDGESPLIT', {}),
    ("Merge", "mesh.remove_doubles", 'AUTOMERGE_ON', {"threshold": 0.001}),
    ("Merge to Center", "mesh.merge", 'PIVOT_MEDIAN', {"type": 'CENTER'}),
    ("Collapse", "mesh.merge", 'FULLSCREEN_EXIT', {"type": 'COLLAPSE'}),
    ("Poke", "mesh.poke", 'DECORATE', {}),
    ("Detach", "mesh.split", 'MOD_EXPLODE', {}),
    ("Chamfer Vertex", "mesh.bevel", 'VERTEXSEL', {"affect": 'VERTICES', "offset_type": 'PERCENT'}),
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


class _MayaToolkitPanel(_MayaDockPanel):
    bl_context = "modeling_toolkit"


class PROPERTIES_PT_maya_mtk_selection(_MayaToolkitPanel, Panel):
    bl_label = "Selection"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        _button(row, context, "", "object.mode_set", 'OBJECT_DATAMODE', {"mode": 'OBJECT'},
                depress=context.mode == 'OBJECT')
        ob = context.active_object
        if ob is not None and ob.type == 'MESH':
            sel = tuple(context.tool_settings.mesh_select_mode) if context.mode == 'EDIT_MESH' else (False,) * 3
            for i, (mode, icon) in enumerate((('VERT', 'VERTEXSEL'), ('EDGE', 'EDGESEL'), ('FACE', 'FACESEL'))):
                _button(row, context, "", "object.mode_set_with_submode", icon,
                        {"mode": 'EDIT', "mesh_select_mode": {mode}}, depress=sel[i] and sum(sel) == 1)
            _button(row, context, "Multi", "object.mode_set_with_submode", 'MOD_WIREFRAME',
                    {"mode": 'EDIT', "mesh_select_mode": {'VERT', 'EDGE', 'FACE'}}, depress=sum(sel) > 1)
        _buttons(layout, context, MTK_SELECT_TOOLS)
        space = _view3d_space(context)
        if space is not None:
            layout.prop(space.shading, "show_xray", text="X-Ray (select through)")


class PROPERTIES_PT_maya_mtk_soft_selection(_MayaToolkitPanel, Panel):
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


class PROPERTIES_PT_maya_mtk_symmetry(_MayaToolkitPanel, Panel):
    bl_label = "Symmetry"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def draw(self, context):
        row = self.layout.row(align=True)
        mesh = context.active_object.data
        for axis in "xyz":
            row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)


class PROPERTIES_PT_maya_mtk_mesh(_MayaToolkitPanel, Panel):
    bl_label = "Mesh"

    def draw(self, context):
        _buttons(self.layout, context, MTK_MESH)


class PROPERTIES_PT_maya_mtk_components(_MayaToolkitPanel, Panel):
    bl_label = "Components"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        _buttons(self.layout, context, MTK_COMPONENTS)


class PROPERTIES_PT_maya_mtk_tools(_MayaToolkitPanel, Panel):
    bl_label = "Tools"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        _buttons(self.layout, context, MTK_TOOLS)


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
    MAYA_OT_dock_tab,
    MAYA_OT_delete_components,
    MAYA_OT_connect,
    MAYA_OT_fill_hole,
    MAYA_OT_snap_hold,
    MAYA_MT_marking_menu,
    MAYA_MT_poly_tools,
    MAYA_MT_convert_selection_pie,
    MAYA_MT_create_pie,
    PROPERTIES_PT_maya_channel_box,
    PROPERTIES_PT_maya_layer_editor,
    PROPERTIES_PT_maya_mtk_selection,
    PROPERTIES_PT_maya_mtk_soft_selection,
    PROPERTIES_PT_maya_mtk_symmetry,
    PROPERTIES_PT_maya_mtk_mesh,
    PROPERTIES_PT_maya_mtk_components,
    PROPERTIES_PT_maya_mtk_tools,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
