# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
classic-style tools for Maelstrom3D: Maya operators, marking menus and the right-hand dock
(Channel Box / Layer Editor and Modeling Toolkit tabs of the Attribute Editor area).
"""

import bpy
from bpy.types import Menu, Operator, Panel
from mathutils import Vector

SMOOTH_MOD = "SmoothPreview"


class M3D_OT_smooth_preview(Operator):
    """Smooth mesh preview: 1 off, 2 cage + smooth, 3 smooth"""
    bl_idname = "m3d.smooth_preview"
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


class M3D_OT_group(Operator):
    """Group: parent the selection under a new empty at its center"""
    bl_idname = "m3d.group"
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


class M3D_OT_add_primitive(Operator):
    """Create a standard-size polygon primitive at the origin"""
    bl_idname = "m3d.add_primitive"
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


class M3D_OT_call(Operator):
    """Run an operator in the 3D Viewport (used by top bar menus)"""
    bl_idname = "m3d.call"
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


# Modeling Toolkit tools that are picked or dragged in the viewport: no options box, run as usual.
INTERACTIVE_TOOLS = {"mesh.knife_tool", "wm.tool_set_by_id", "mesh.loopcut_slide", "mesh.offset_edge_loops_slide",
                     "transform.edge_slide", "transform.vert_slide", "transform.edge_crease", "mesh.rip_move"}
# Tools that are modal when invoked: run them straight away so the options box opens on the click.
EXEC_TOOLS = {"mesh.bevel", "mesh.inset", "mesh.extrude_region_shrink_fatten", "mesh.extrude_edges_move",
              "mesh.extrude_vertices_move", "mesh.duplicate_move"}
# Starting values while the user has never changed them (Blender's are 0, which does nothing).
FIRST_VALUES = {"mesh.bevel": {"offset_pct": 25.0}, "mesh.inset": {"thickness": 0.1}}


def _box_xy(context, event, area, region):
    """Window position for the options box: the click, or next to the selection when run from the dock."""
    if region.x <= event.mouse_x < region.x + region.width and region.y <= event.mouse_y < region.y + region.height:
        return event.mouse_x, event.mouse_y
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector
    ob = context.active_object
    center = ob.matrix_world.translation if ob is not None else None
    if ob is not None and ob.mode == 'EDIT' and ob.type == 'MESH':
        import bmesh
        verts = [v.co for v in bmesh.from_edit_mesh(ob.data).verts if v.select]
        if verts:
            center = ob.matrix_world @ (sum(verts, Vector()) / len(verts))
    p = location_3d_to_region_2d(region, area.spaces.active.region_3d, center) if center is not None else None
    if p is None:
        return region.x + region.width // 2, region.y + region.height // 2
    return region.x + int(p.x) + 40, region.y + int(p.y)


class M3D_OT_tool(Operator):
    """Modeling Toolkit tool: runs on the click and opens its options box next to it"""
    bl_idname = "m3d.tool"
    bl_label = "Modeling Toolkit Tool"
    bl_options = {'INTERNAL'}

    idname: bpy.props.StringProperty()
    props: bpy.props.StringProperty(default="{}")
    label: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return props.label or props.idname

    def invoke(self, context, event):
        from ast import literal_eval
        if context.area is not None and context.area.type == 'VIEW_3D':
            area = context.area
        else:
            areas = [a for a in context.screen.areas if a.type == 'VIEW_3D']
            if not areas:
                self.report({'WARNING'}, "No 3D Viewport in this workspace")
                return {'CANCELLED'}
            area = max(areas, key=lambda a: a.width * a.height)
        region = context.region if context.region is not None and context.region.type == 'WINDOW' and \
            context.area == area else next(r for r in area.regions if r.type == 'WINDOW')
        props = literal_eval(self.props)
        wm = context.window_manager
        last = wm.operator_properties_last(self.idname)
        for key, value in FIRST_VALUES.get(self.idname, {}).items():
            if key not in props and getattr(last, key) == last.bl_rna.properties[key].default:
                props[key] = value
        mod, name = self.idname.split(".")
        mode = 'EXEC_DEFAULT' if self.idname in EXEC_TOOLS else 'INVOKE_DEFAULT'
        # The C options box opens only while this is set (see interface_region_hud.cc).
        wm["m3d_options_box"] = _box_xy(context, event, area, region)
        try:
            with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                getattr(getattr(bpy.ops, mod), name)(mode, True, **props)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            del wm["m3d_options_box"]
        return {'FINISHED'}


def tool_button(layout, context, label, idname, icon, props):
    """Toolkit button: picked/dragged tools run as usual, the rest through `m3d.tool` (options box)."""
    if idname in INTERACTIVE_TOOLS:
        return _button(layout, context, label, idname, icon, props)
    o = layout.operator("m3d.tool", text=label, icon=icon)
    o.idname, o.props, o.label = idname, repr(props), label
    return o


class M3D_OT_open_editor(Operator):
    """Open an editor in a new window (Windows menu)"""
    bl_idname = "m3d.open_editor"
    bl_label = "Open Editor Window"

    ui_type: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return "Open " + props.ui_type + " window"

    def execute(self, context):
        bpy.ops.wm.window_new()
        context.window_manager.windows[-1].screen.areas[0].ui_type = self.ui_type
        return {'FINISHED'}


class M3D_OT_ungroup(Operator):
    """Ungroup: remove the selected group nodes, keeping their children in place"""
    bl_idname = "m3d.ungroup"
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


class M3D_OT_reset_transformations(Operator):
    """Reset Transformations: zero translate/rotate, unit scale"""
    bl_idname = "m3d.reset_transformations"
    bl_label = "Reset Transformations"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for ob in context.selected_objects:
            ob.location = (0, 0, 0)
            ob.rotation_euler = (0, 0, 0)
            ob.scale = (1, 1, 1)
        return {'FINISHED'}


class M3D_OT_boolean(Operator):
    """Boolean: select the base object first, the tool object last (A then B gives A - B)"""
    bl_idname = "m3d.boolean"
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


class M3D_OT_separate(Operator):
    """Separate: split a combined mesh into its separate shells"""
    bl_idname = "m3d.separate"
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


class M3D_OT_assign_material(Operator):
    """Assign New Material: give the selection a new shader"""
    bl_idname = "m3d.assign_material"
    bl_label = "Assign New Material"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mat = bpy.data.materials.new("standardSurface1")
        for ob in context.selected_objects:
            if ob.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
                ob.data.materials.clear()
                ob.data.materials.append(mat)
        return {'FINISHED'}


class M3D_OT_lock_transforms(Operator):
    """Lock and Hide: lock translate, rotate and scale of the selection"""
    bl_idname = "m3d.lock_transforms"
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


# Everything Maya offers for a component selection: (label, idname, icon, props).
COMPONENT_TOOLS = {
    'VERT': ("Vertex Tools", (
        ("Extrude Vertex", "mesh.extrude_vertices_move", 'VERTEXSEL', {}),
        ("Chamfer Vertex", "mesh.bevel", 'MOD_BEVEL', {"affect": 'VERTICES', "offset_type": 'PERCENT'}),
        ("Connect", "m3d.connect", 'MOD_EDGESPLIT', {}),
        ("Merge", "mesh.remove_doubles", 'AUTOMERGE_ON', {"threshold": 0.001}),
        ("Merge to Center", "mesh.merge", 'PIVOT_MEDIAN', {"type": 'CENTER'}),
        ("Target Weld", "m3d.target_weld", 'AUTOMERGE_OFF', {}),
        ("Average Vertices", "mesh.vertices_smooth", 'MOD_SMOOTH', {}),
        ("Slide", "transform.vert_slide", 'ARROW_LEFTRIGHT', {}),
        ("Detach (Rip)", "mesh.rip_move", 'MOD_EXPLODE', {}),
        ("Create Polygon", "mesh.edge_face_add", 'SNAP_FACE', {}),
        ("Delete Vertex", "mesh.dissolve_verts", 'X', {}),
    )),
    'EDGE': ("Edge Tools", (
        ("Extrude Edge", "mesh.extrude_edges_move", 'EDGESEL', {}),
        ("Bevel", "mesh.bevel", 'MOD_BEVEL', {"offset_type": 'PERCENT'}),
        ("Bridge", "mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
        ("Connect", "m3d.connect", 'MOD_EDGESPLIT', {}),
        ("Insert Edge Loop", "mesh.loopcut_slide", 'MOD_EDGESPLIT', {}),
        ("Offset Edge Loop", "mesh.offset_edge_loops_slide", 'SNAP_EDGE', {}),
        ("Slide Edge", "transform.edge_slide", 'ARROW_LEFTRIGHT', {}),
        ("Collapse", "mesh.merge", 'FULLSCREEN_EXIT', {"type": 'COLLAPSE'}),
        ("Merge to Center", "mesh.merge", 'PIVOT_MEDIAN', {"type": 'CENTER'}),
        ("Fill Hole", "m3d.fill_hole", 'SNAP_FACE', {}),
        ("Spin Edge", "mesh.edge_rotate", 'FILE_REFRESH', {}),
        ("Crease", "transform.edge_crease", 'MOD_SMOOTH', {}),
        ("Soften Edge", "mesh.mark_sharp", 'SHADING_SOLID', {"clear": True}),
        ("Harden Edge", "mesh.mark_sharp", 'SHADING_WIRE', {}),
        ("Cut UVs (Mark Seam)", "mesh.mark_seam", 'UV', {}),
        ("Detach", "mesh.edge_split", 'MOD_EXPLODE', {}),
        ("Delete Edge", "mesh.dissolve_edges", 'X', {}),
    )),
    'FACE': ("Face Tools", (
        ("Extrude Face", "mesh.extrude_region_shrink_fatten", 'FACESEL', {}),
        ("Extrude Offset (Inset)", "mesh.inset", 'MOD_SOLIDIFY', {}),
        ("Bevel", "mesh.bevel", 'MOD_BEVEL', {"offset_type": 'PERCENT'}),
        ("Bridge", "mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
        ("Poke", "mesh.poke", 'DECORATE', {}),
        ("Wedge (Spin)", "mesh.spin", 'MOD_SCREW', {}),
        ("Add Divisions", "mesh.subdivide", 'MOD_SUBSURF', {}),
        ("Triangulate", "mesh.quads_convert_to_tris", 'MOD_TRIANGULATE', {}),
        ("Quadrangulate", "mesh.tris_convert_to_quads", 'MESH_GRID', {}),
        ("Merge to Center", "mesh.merge", 'PIVOT_MEDIAN', {"type": 'CENTER'}),
        ("Duplicate", "mesh.duplicate_move", 'DUPLICATE', {}),
        ("Extract", "mesh.separate", 'MOD_EXPLODE', {"type": 'SELECTED'}),
        ("Detach", "mesh.split", 'UNLINKED', {}),
        ("Flip Normal", "mesh.flip_normals", 'NORMALS_FACE', {}),
        ("Planar UV", "uv.project_from_view", 'UV', {}),
        ("Delete Face", "mesh.delete", 'X', {"type": 'FACE'}),
    )),
}


def _component_kind(context):
    """Face > edge > vertex, from the active select mode (Maya shows the tools for what is selected)."""
    vert, edge, face = context.tool_settings.mesh_select_mode
    return 'FACE' if face else 'EDGE' if edge else 'VERT'


class M3D_MT_marking_menu(Menu):
    """Right-click marking menu: component modes, plus every tool for the selected component type"""
    bl_label = "Marking Menu"

    def draw(self, context):
        pie = self.layout.menu_pie()
        ob = context.active_object
        is_mesh = ob is not None and ob.type == 'MESH'
        edit = context.mode == 'EDIT_MESH'
        # Pie order: W, E, S, N, NW, NE, SW, SE.
        if is_mesh:
            _submode(pie, "Vertex", {'VERT'}, 'VERTEXSEL')
            _submode(pie, "Face", {'FACE'}, 'FACESEL')
        else:
            pie.separator()
            pie.separator()
        if edit:
            label, tools = COMPONENT_TOOLS[_component_kind(context)]
            box = pie.box().column(align=True)
            box.label(text=label)
            for label, idname, icon, props in tools:
                tool_button(box, context, label, idname, icon, props)
        else:
            from m3d_marking import draw_object_list
            draw_object_list(pie.box().column(align=True))
        if is_mesh:
            _submode(pie, "Edge", {'EDGE'}, 'EDGESEL')
            _submode(pie, "Multi", {'VERT', 'EDGE', 'FACE'}, 'MOD_WIREFRAME')
        else:
            pie.separator()
            pie.separator()
        pie.operator("object.mode_set", text="Object Mode", icon='OBJECT_DATAMODE').mode = 'OBJECT'
        if edit:
            pie.menu("VIEW3D_MT_edit_mesh_context_menu", text="More...", icon='COLLAPSEMENU')
            col = pie.column(align=True)
            col.operator("mesh.select_all", text="Select All", icon='SELECT_EXTEND').action = 'SELECT'
            col.operator("mesh.select_all", text="Invert Selection", icon='SELECT_DIFFERENCE').action = 'INVERT'
        else:
            pie.menu("VIEW3D_MT_object_context_menu", text="More...", icon='COLLAPSEMENU')
            pie.operator("object.select_all", text="Select All", icon='SELECT_EXTEND').action = 'SELECT'


class M3D_OT_dock_tab(Operator):
    """Show a tab of the right-hand dock (Channel Box, Attribute Editor, Modeling Toolkit)"""
    bl_idname = "m3d.dock_tab"
    bl_label = "Dock Tab"

    tab: bpy.props.StringProperty(default='CHANNEL_BOX')
    toggle: bpy.props.BoolProperty(description="Ctrl+A: switch between Channel Box and Attribute Editor")

    def execute(self, context):
        docks = [a for a in context.screen.areas if a.type == 'PROPERTIES']
        if not docks:
            bpy.ops.m3d.open_editor(ui_type='PROPERTIES')
            return {'FINISHED'}
        space = max(docks, key=lambda a: a.height).spaces.active
        tab = self.tab
        if self.toggle:
            tab = 'OBJECT' if space.context == 'CHANNEL_BOX' else 'CHANNEL_BOX'
        space.context = tab
        return {'FINISHED'}


class M3D_OT_target_weld(Operator):
    """Target Weld: merge the selected vertices onto the last one selected"""
    bl_idname = "m3d.target_weld"
    bl_label = "Target Weld"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        import bmesh
        bm = bmesh.from_edit_mesh(context.edit_object.data)
        if not isinstance(bm.select_history.active, bmesh.types.BMVert):
            self.report({'WARNING'}, "Click the vertices to weld, the target last")
            return {'CANCELLED'}
        bpy.ops.mesh.merge(type='LAST')
        return {'FINISHED'}


class M3D_OT_delete_components(Operator):
    """Delete: faces are removed, edges and vertices are dissolved (the mesh stays closed)"""
    bl_idname = "m3d.delete_components"
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


class M3D_OT_connect(Operator):
    """Connect: edges get a new edge loop through their midpoints, vertices get joined by an edge"""
    bl_idname = "m3d.connect"
    bl_label = "Connect"
    bl_options = {'REGISTER', 'UNDO'}

    divisions: bpy.props.IntProperty(name="Divisions", description="Edge loops added across the selected edges",
                                     default=1, min=1, max=64)
    smoothness: bpy.props.FloatProperty(name="Smoothness", default=0.0, min=0.0, max=1.0, subtype='FACTOR')

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        if context.tool_settings.mesh_select_mode[1]:
            self.layout.prop(self, "divisions")
            self.layout.prop(self, "smoothness")

    def execute(self, context):
        if context.tool_settings.mesh_select_mode[1]:
            bpy.ops.mesh.subdivide_edgering(number_cuts=self.divisions, smoothness=self.smoothness)
        else:
            bpy.ops.mesh.vert_connect_path()
        return {'FINISHED'}


class M3D_OT_fill_hole(Operator):
    """Fill Hole: fill the selected border, or every hole of the selected meshes"""
    bl_idname = "m3d.fill_hole"
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


class M3D_OT_snap_hold(Operator):
    """Hold-to-snap: X grid, C curve (edge), V point (vertex)"""
    bl_idname = "m3d.snap_hold"
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


class M3D_MT_convert_selection_pie(Menu):
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


class M3D_OT_pivot_hold(Operator):
    """D (hold): edit the pivot. Objects move their origin only; components move a custom pivot"""
    bl_idname = "m3d.pivot_hold"
    bl_label = "Edit Pivot (hold)"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        ts = context.tool_settings
        self.key = event.type
        self.edit = context.mode == 'EDIT_MESH'
        if self.edit:
            self.prev_tool = context.workspace.tools.from_space_view3d_mode(context.mode).idname
            if ts.transform_pivot_point != 'CURSOR':
                bpy.ops.view3d.snap_cursor_to_selected()
                ts.transform_pivot_point = 'CURSOR'
            bpy.ops.wm.tool_set_by_id(name="builtin.cursor")
        else:
            ts.use_transform_data_origin = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != self.key or event.value != 'RELEASE':
            return {'PASS_THROUGH'}
        if self.edit:
            bpy.ops.wm.tool_set_by_id(name=self.prev_tool, space_type='VIEW_3D')
        else:
            context.tool_settings.use_transform_data_origin = False
        return {'FINISHED'}


class M3D_OT_duplicate(Operator):
    """Duplicate: Ctrl+D copies in place, Shift+D also repeats the last duplicate's move/rotate/scale"""
    bl_idname = "m3d.duplicate"
    bl_label = "Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    with_transform: bpy.props.BoolProperty(name="With Transform")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def execute(self, context):
        sources = list(context.selected_objects)
        bpy.ops.object.duplicate()
        for src, new in zip(sources, context.selected_objects):
            prev = bpy.data.objects.get(src.get("m3d_duplicate_of", ""))
            if self.with_transform and prev is not None:
                new.matrix_world = src.matrix_world @ prev.matrix_world.inverted() @ src.matrix_world
            new["m3d_duplicate_of"] = src.name
        return {'FINISHED'}


class M3D_OT_smooth_levels(Operator):
    """Page Up / Page Down: more or fewer smooth mesh preview divisions"""
    bl_idname = "m3d.smooth_levels"
    bl_label = "Smooth Preview Divisions"
    bl_options = {'REGISTER', 'UNDO'}

    delta: bpy.props.IntProperty(default=1)

    def execute(self, context):
        for ob in context.selected_objects or [context.active_object]:
            mod = ob and ob.modifiers.get(SMOOTH_MOD)
            if mod:
                mod.levels = max(0, min(6, mod.levels + self.delta))
        return {'FINISHED'}


class M3D_MT_hotbox(Menu):
    """Hotbox: every menu in one place"""
    bl_label = "Hotbox"

    def draw(self, context):
        from m3d_ui import COMMON_MENUS, MENU_SETS, MENUS
        row = self.layout.row()
        col = row.column()
        col.label(text="Common")
        for idname in COMMON_MENUS + ["M3D_MT_help"]:
            col.menu(idname)
        for _key, (label, menus) in MENU_SETS.items():
            col = row.column()
            col.label(text=label)
            for idname in menus:
                col.menu(idname, text=MENUS[idname][0])
        col = row.column()
        col.label(text="Panels")
        col.operator("screen.region_quadview", text="Four View / Single", icon='VIEW_PERSPECTIVE')
        col.operator("screen.screen_full_area", text="Maximize Panel", icon='FULLSCREEN_ENTER')
        col.menu("M3D_MT_workspaces")


class M3D_OT_space_hotbox(Operator):
    """Space: tap toggles four views, hold shows the hotbox"""
    bl_idname = "m3d.space_hotbox"
    bl_label = "Hotbox / Four View"
    bl_options = {'INTERNAL'}

    HOLD_SECONDS = 0.2

    def invoke(self, context, _event):
        self.area, self.region = context.area, context.region
        self.timer = context.window_manager.event_timer_add(self.HOLD_SECONDS, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'SPACE' and event.value == 'RELEASE':
            self.finish(context)
            with context.temp_override(area=self.area, region=self.region):
                bpy.ops.screen.region_quadview()
            return {'FINISHED'}
        if event.type == 'TIMER':
            self.finish(context)
            with context.temp_override(area=self.area, region=self.region):
                bpy.ops.wm.call_menu(name="M3D_MT_hotbox")
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def finish(self, context):
        context.window_manager.event_timer_remove(self.timer)


class _DockPanel:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'


class PROPERTIES_PT_m3d_channel_box(_DockPanel, Panel):
    """Channel Box: transform channels, visibility and inputs (modifiers)"""
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
        for label, attr, lock in (("Translate", "location", "lock_location"),
                                  ("Rotate", "rotation_euler", "lock_rotation"), ("Scale", "scale", "lock_scale")):
            for i, axis in enumerate("XYZ"):
                row = col.row(align=True)
                sub = row.row(align=True)
                sub.active = not getattr(ob, lock)[i]
                sub.prop(ob, attr, index=i, text=f"{label} {axis}")
                row.prop(ob, lock, index=i, text="", emboss=False, icon='DECORATE_UNLOCKED')
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


class PROPERTIES_PT_m3d_layer_editor(_DockPanel, Panel):
    """Layer Editor: display layers are collections here"""
    bl_context = "channel_box"
    bl_label = "Layer Editor"

    def draw(self, context):
        layout = self.layout
        _button(layout, context, "Create Layer from Selected", "object.move_to_collection", 'COLLECTION_NEW',
                    {"is_new": True, "new_collection_name": "layer1"})
        col = layout.column(align=True)
        for lc in context.view_layer.layer_collection.children:
            row = col.row(align=True)
            sub = row.row(align=True)
            sub.scale_x = 0.5
            sub.prop(lc, "hide_viewport", text="V", toggle=True, invert_checkbox=True)
            sub.prop(lc.collection, "hide_select", text="R", toggle=True)
            row.prop(lc.collection, "name", text="")


def _button(layout, context, label, idname, icon, props, depress=False):
    """Operator button; viewport-only commands run in the 3D Viewport through `m3d.call`."""
    from m3d_ui import needs_view3d, _poll
    in_view3d = context.area is not None and context.area.type == 'VIEW_3D'
    if not in_view3d and (needs_view3d(idname) or not _poll(idname)):
        o = layout.operator("m3d.call", text=label, icon=icon, depress=depress)
        o.idname, o.props, o.label = idname, repr(props), label
        return o
    o = layout.operator(idname, text=label, icon=icon, depress=depress)
    for k, v in props.items():
        setattr(o, k, v)
    return o


def _buttons(layout, context, items, columns=2, options_box=False):
    """Grid of classic-style tool buttons: (label, idname, icon, props). Toolkit tools open the options box."""
    grid = layout.grid_flow(columns=columns, even_columns=True, align=True)
    for label, idname, icon, props in items:
        (tool_button if options_box else _button)(grid, context, label, idname, icon, props)


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
    ("Separate", "m3d.separate", 'MOD_EXPLODE', {}),
    ("Smooth", "object.subdivision_set", 'MOD_SUBSURF', {"level": 1, "relative": False}),
    ("Mirror", "object.modifier_add", 'MOD_MIRROR', {"type": 'MIRROR'}),
    ("Union", "m3d.boolean", 'SELECT_EXTEND', {"operation": 'UNION'}),
    ("Difference", "m3d.boolean", 'SELECT_SUBTRACT', {"operation": 'DIFFERENCE'}),
    ("Intersection", "m3d.boolean", 'SELECT_INTERSECT', {"operation": 'INTERSECT'}),
    ("Fill Hole", "m3d.fill_hole", 'SNAP_FACE', {}),
)
MTK_COMPONENTS = (
    ("Extrude", "mesh.extrude_region_shrink_fatten", 'FACESEL', {}),
    ("Bevel", "mesh.bevel", 'MOD_BEVEL', {"offset_type": 'PERCENT'}),
    ("Bridge", "mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
    ("Connect", "m3d.connect", 'MOD_EDGESPLIT', {}),
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
    ("Target Weld", "m3d.target_weld", 'AUTOMERGE_OFF', {}),
    ("Create Polygon", "mesh.edge_face_add", 'SNAP_FACE', {}),
    ("Crease", "transform.edge_crease", 'MOD_SMOOTH', {}),
)


class _ToolkitPanel(_DockPanel):
    bl_context = "modeling_toolkit"


class PROPERTIES_PT_m3d_mtk_selection(_ToolkitPanel, Panel):
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


class PROPERTIES_PT_m3d_mtk_soft_selection(_ToolkitPanel, Panel):
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


class PROPERTIES_PT_m3d_mtk_symmetry(_ToolkitPanel, Panel):
    bl_label = "Symmetry"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def draw(self, context):
        row = self.layout.row(align=True)
        mesh = context.active_object.data
        for axis in "xyz":
            row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)


class PROPERTIES_PT_m3d_mtk_mesh(_ToolkitPanel, Panel):
    bl_label = "Mesh"

    def draw(self, context):
        _buttons(self.layout, context, MTK_MESH, options_box=True)


class PROPERTIES_PT_m3d_mtk_components(_ToolkitPanel, Panel):
    bl_label = "Components"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        _buttons(self.layout, context, MTK_COMPONENTS, options_box=True)


class PROPERTIES_PT_m3d_mtk_tools(_ToolkitPanel, Panel):
    bl_label = "Tools"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        _buttons(self.layout, context, MTK_TOOLS, options_box=True)


@bpy.app.handlers.persistent
def m3d_startup_scene(*_args):
    """New scene like Maya's: the default camera is "persp" and nothing shows in the viewport."""
    camera = bpy.data.objects.get("Camera")
    if camera is not None:
        camera.name = "persp"
    for ob in bpy.data.objects:
        if ob.type in {'CAMERA', 'LIGHT'}:
            ob.hide_set(True)


@bpy.app.handlers.persistent
def m3d_preferences(*_args):
    """First run / factory preferences: classic UI defaults (solid tool and dock strips, no splash,
    no Blender navigation buttons, Segoe UI like Maya on Windows)."""
    import os
    prefs = bpy.context.preferences
    prefs.system.use_region_overlap = False
    prefs.view.show_splash = False
    prefs.view.show_navigate_ui = False
    segoe = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeui.ttf")
    if not prefs.view.font_path_ui and os.path.exists(segoe):
        prefs.view.font_path_ui = segoe


class M3D_OT_command_language(Operator):
    """Command line: switch between MEL and Python"""
    bl_idname = "m3d.command_language"
    bl_label = "Command Line Language"

    language: bpy.props.EnumProperty(items=(('mel', "MEL", ""), ('python', "Python", "")))

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == 'CONSOLE':
                area.spaces.active.language = self.language
                with context.temp_override(area=area, region=area.regions[-1]):
                    bpy.ops.console.banner()
        return {'FINISHED'}


classes = (
    M3D_OT_smooth_preview,
    M3D_OT_group,
    M3D_OT_add_primitive,
    M3D_OT_call,
    M3D_OT_tool,
    M3D_OT_open_editor,
    M3D_OT_ungroup,
    M3D_OT_reset_transformations,
    M3D_OT_boolean,
    M3D_OT_separate,
    M3D_OT_assign_material,
    M3D_OT_lock_transforms,
    M3D_OT_dock_tab,
    M3D_OT_command_language,
    M3D_OT_target_weld,
    M3D_OT_delete_components,
    M3D_OT_connect,
    M3D_OT_fill_hole,
    M3D_OT_snap_hold,
    M3D_OT_pivot_hold,
    M3D_OT_duplicate,
    M3D_OT_smooth_levels,
    M3D_OT_space_hotbox,
    M3D_MT_hotbox,
    M3D_MT_marking_menu,
    M3D_MT_convert_selection_pie,
    PROPERTIES_PT_m3d_channel_box,
    PROPERTIES_PT_m3d_layer_editor,
    PROPERTIES_PT_m3d_mtk_selection,
    PROPERTIES_PT_m3d_mtk_soft_selection,
    PROPERTIES_PT_m3d_mtk_symmetry,
    PROPERTIES_PT_m3d_mtk_mesh,
    PROPERTIES_PT_m3d_mtk_components,
    PROPERTIES_PT_m3d_mtk_tools,
)


# Workspace names in the built-in startup file -> current names.
WORKSPACE_NAMES = {"Maya Classic": "Classic", "Hypershade": "Shading"}


@bpy.app.handlers.persistent
def m3d_workspace_names(*_args):
    for old, new in WORKSPACE_NAMES.items():
        for collection in (bpy.data.workspaces, bpy.data.screens):
            item = collection.get(old)
            if item is not None:
                item.name = new


@bpy.app.handlers.persistent
def m3d_startup_layout(*_args):
    """Factory startup: viewport sidebar closed (panels live in the dock), Outliner shows objects only
    (like Maya's DAG view), command lines use MEL."""
    if bpy.app.background:
        return  # No UI to set up (changing regions without a window leaks).
    for screen in bpy.data.screens:
        for area in screen.areas:
            space = area.spaces.active
            if area.type == 'VIEW_3D':
                space.show_region_ui = False
                space.show_region_tool_header = screen.name in {"Sculpting", "3D Paint"}
                # Maya's default 35 mm camera on a 36 mm film back: Blender's viewport lens assumes a 72 mm
                # sensor, so the matching field of view is 70 mm.
                space.lens = 70.0
                space.overlay.show_text = False  # Maya HUD (m3d_hud.py) shows the camera name instead.
            elif area.type == 'OUTLINER':
                space.use_filter_object_content = False
                space.use_filter_collection = False  # Flat object list, like Maya's Outliner.
            elif area.type == 'CONSOLE':
                space.language = 'mel'
    bpy.app.timers.register(_timeline_controls_below, first_interval=0.3)


def _timeline_controls_below():
    """Maya: the time slider sits above its playback / range controls, so flip the timeline header down."""
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'DOPESHEET_EDITOR' and area.spaces.active.mode == 'TIMELINE':
            header = next((r for r in area.regions if r.type == 'HEADER'), None)
            if header is not None and header.alignment == 'TOP':
                with bpy.context.temp_override(window=win, area=area, region=header):
                    bpy.ops.screen.region_flip()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_factory_startup_post.append(m3d_workspace_names)
    bpy.app.handlers.load_factory_startup_post.append(m3d_startup_layout)
    bpy.app.handlers.load_factory_startup_post.append(m3d_startup_scene)
    bpy.app.handlers.load_factory_preferences_post.append(m3d_preferences)


def unregister():
    bpy.app.handlers.load_factory_startup_post.remove(m3d_workspace_names)
    bpy.app.handlers.load_factory_startup_post.remove(m3d_startup_layout)
    bpy.app.handlers.load_factory_startup_post.remove(m3d_startup_scene)
    bpy.app.handlers.load_factory_preferences_post.remove(m3d_preferences)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
