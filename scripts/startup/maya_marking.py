# SPDX-FileCopyrightText: 2026 MayaBlender
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya marking menus and the Maya hotkey operators that need Python:
hold Q/W/E/R/A/H/Shift+S + left click, Shift / Ctrl+Shift right click, manipulator Shift / Ctrl+Shift drags,
view undo ([ ]), nudge (Alt+arrows), pickwalk, last tool (Y), background cycle (Alt+B), soft select radius (B).
"""

import bpy
from bpy.types import Menu, Operator
from mathutils import Vector


def _op(layout, idname, text, icon='NONE', **props):
    o = layout.operator(idname, text=text, icon=icon)
    for k, v in props.items():
        setattr(o, k, v)
    return o


def _orient(layout, text, value, icon='NONE'):
    _op(layout, "wm.context_set_enum", text, icon,
        data_path="scene.transform_orientation_slots[0].type", value=value)


# -----------------------------------------------------------------------------
# Hold key + left click marking menus

class MAYA_OT_key_marking_menu(Operator):
    """Maya hotkey: tap runs the tool or command, hold the key and left click for its marking menu"""
    bl_idname = "maya.key_marking_menu"
    bl_label = "Hotkey Marking Menu"
    bl_options = {'INTERNAL'}

    last_menu = ""

    menu: bpy.props.StringProperty()
    menu_mmb: bpy.props.StringProperty(description="Marking menu for hold key + middle click")
    tool: bpy.props.StringProperty(description="Tool to activate on press")
    command: bpy.props.StringProperty(description="Operator to run on press")

    @classmethod
    def description(cls, _context, props):
        return f"Tap: {props.tool or props.command or 'nothing'}. Hold + left click: marking menu"

    def invoke(self, context, event):
        if event.is_repeat:
            return {'CANCELLED'}
        if self.tool:
            bpy.ops.wm.tool_set_by_id(name=self.tool)
        elif self.command:
            mod, name = self.command.split(".")
            getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT')
        self.key = event.type
        self.area, self.region = context.area, context.region
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == self.key and event.value == 'RELEASE':
            return {'FINISHED', 'PASS_THROUGH'}
        menu = {'LEFTMOUSE': self.menu, 'MIDDLEMOUSE': self.menu_mmb}.get(event.type) if event.value == 'PRESS' \
            else None
        if menu:
            with context.temp_override(area=self.area, region=self.region):
                bpy.ops.wm.call_menu_pie(name=menu)
            MAYA_OT_key_marking_menu.last_menu = menu  # Read by tools/maya/gui_test.py.
            return {'FINISHED'}
        return {'PASS_THROUGH'}


class MAYA_MT_select_mm(Menu):
    """Q + left click: selection tools"""
    bl_label = "Select Tool"

    def draw(self, context):
        pie = self.layout.menu_pie()
        _op(pie, "wm.tool_set_by_id", "Lasso", 'MOD_CURVE', name="builtin.select_lasso")
        _op(pie, "wm.tool_set_by_id", "Paint Select", 'BRUSH_DATA', name="builtin.select_circle")
        _op(pie, "wm.tool_set_by_id", "Marquee", 'SELECT_SET', name="builtin.select_box")
        _op(pie, "wm.tool_set_by_id", "Tweak", 'RESTRICT_SELECT_OFF', name="builtin.select")
        pie.prop(context.space_data.shading, "show_xray", text="Camera Based Off (X-Ray)")
        soft = "use_proportional_edit" if context.mode == 'EDIT_MESH' else "use_proportional_edit_objects"
        pie.prop(context.tool_settings, soft, text="Soft Select")
        _op(pie, "object.select_all" if context.mode == 'OBJECT' else "mesh.select_all", "Clear Selection",
            'X', action='DESELECT')
        pie.prop(context.space_data.overlay, "show_outline_selected", text="Highlight Selection")


def _transform_mm(pie, context, tool_label, snap_prop):
    ts = context.tool_settings
    _orient(pie, "World", 'GLOBAL', 'ORIENTATION_GLOBAL')
    _orient(pie, "Object", 'LOCAL', 'ORIENTATION_LOCAL')
    _orient(pie, "Component", 'NORMAL', 'ORIENTATION_NORMAL')
    _orient(pie, "Parent", 'PARENT', 'ORIENTATION_PARENT')
    col = pie.column(align=True)
    col.label(text=tool_label)
    col.prop(ts, "use_snap", text="Snap")
    col.prop(ts, "use_snap_" + snap_prop, text="Snap " + snap_prop.title())
    col.prop(ts, "use_transform_correct_face_attributes", text="Preserve UVs")
    col.prop(ts, "use_transform_data_origin", text="Edit Pivot")
    _orient(pie, "View", 'VIEW', 'ORIENTATION_VIEW')
    _orient(pie, "Gimbal", 'GIMBAL', 'ORIENTATION_GIMBAL')
    _orient(pie, "Custom (Cursor)", 'CURSOR', 'ORIENTATION_CURSOR')


class MAYA_MT_move_mm(Menu):
    """W + left click: move tool orientation and options"""
    bl_label = "Move Tool"

    def draw(self, context):
        _transform_mm(self.layout.menu_pie(), context, "Move Options", "translate")


class MAYA_MT_rotate_mm(Menu):
    """E + left click: rotate tool orientation and options"""
    bl_label = "Rotate Tool"

    def draw(self, context):
        _transform_mm(self.layout.menu_pie(), context, "Rotate Options", "rotate")


class MAYA_MT_scale_mm(Menu):
    """R + left click: scale tool orientation and options"""
    bl_label = "Scale Tool"

    def draw(self, context):
        _transform_mm(self.layout.menu_pie(), context, "Scale Options", "scale")


class MAYA_MT_io_mm(Menu):
    """A + left click: inputs / outputs (history)"""
    bl_label = "History Operations"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        _op(pie, "object.convert", "Delete History", 'TRASH', target='MESH')
        _op(pie, "object.transform_apply", "Freeze Transformations", 'FREEZE',
            location=True, rotation=True, scale=True)
        _op(pie, "object.origin_set", "Center Pivot", 'PIVOT_BOUNDBOX', type='ORIGIN_GEOMETRY')
        _op(pie, "maya.reset_transformations", "Reset Transformations", 'LOOP_BACK')
        _op(pie, "maya.dock_tab", "Show Inputs (Attribute Editor)", 'MODIFIER', tab='MODIFIER')


class MAYA_MT_menu_set_mm(Menu):
    """H + left click: menu sets"""
    bl_label = "Menu Sets"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        for value, label in (('MODELING', "Modeling"), ('RIGGING', "Rigging"), ('ANIMATION', "Animation"),
                             ('FX', "FX"), ('RENDERING', "Rendering")):
            _op(pie, "wm.context_set_enum", label, data_path="window_manager.maya_menu_set", value=value)


class MAYA_MT_keyframe_mm(Menu):
    """Shift+S + left click: keyframe marking menu"""
    bl_label = "Keyframe"

    def draw(self, context):
        pie = self.layout.menu_pie()
        _op(pie, "anim.keyframe_insert", "Set Key", 'KEY_HLT')
        _op(pie, "anim.keyframe_delete_v3d", "Delete Key", 'KEY_DEHLT')
        _op(pie, "anim.keyframe_insert_by_name", "Key Rotate", 'CON_ROTLIKE', type='Rotation')
        _op(pie, "anim.keyframe_insert_by_name", "Key Translate", 'CON_LOCLIKE', type='Location')
        _op(pie, "anim.keyframe_insert_by_name", "Key Scale", 'CON_SIZELIKE', type='Scaling')
        pie.prop(context.tool_settings, "use_keyframe_insert_auto", text="Auto Key")
        _op(pie, "maya.open_editor", "Graph Editor", 'GRAPH', ui_type='FCURVES')
        _op(pie, "maya.open_editor", "Dope Sheet", 'ACTION', ui_type='DOPESHEET')


# -----------------------------------------------------------------------------
# Right click variants

TANGENTS = (
    ('SPLINE', "Spline", 'IPO_BEZIER'), ('LINEAR', "Linear", 'IPO_LINEAR'), ('CLAMPED', "Clamped", 'HANDLE_AUTOCLAMPED'),
    ('FLAT', "Flat", 'IPO_CONSTANT'), ('STEPPED', "Stepped", 'IPO_CONSTANT'), ('PLATEAU', "Plateau", 'HANDLE_AUTOCLAMPED'),
)


class MAYA_OT_set_tangents(Operator):
    """Maya tangents for the selected objects' keys (Spline, Linear, Clamped, Flat, Stepped, Plateau)"""
    bl_idname = "maya.set_tangents"
    bl_label = "Set Tangents"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=[(k, label, "") for k, label, _icon in TANGENTS])

    def execute(self, context):
        from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
        interpolation = {'LINEAR': 'LINEAR', 'STEPPED': 'CONSTANT'}.get(self.kind, 'BEZIER')
        handle = {'SPLINE': 'AUTO', 'FLAT': 'ALIGNED'}.get(self.kind, 'AUTO_CLAMPED')
        for ob in context.selected_objects:
            bag = ob.animation_data and animdata_get_channelbag_for_assigned_slot(ob.animation_data)
            for fcurve in (bag.fcurves if bag else ()):
                for key in fcurve.keyframe_points:
                    key.interpolation = interpolation
                    key.handle_left_type = key.handle_right_type = handle
                    if self.kind == 'FLAT':
                        key.handle_left.y = key.handle_right.y = key.co.y
                fcurve.update()
        return {'FINISHED'}


class MAYA_MT_tangent_mm(Menu):
    """Shift+S + middle click: key tangents"""
    bl_label = "Tangents"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        for kind, label, icon in TANGENTS:
            _op(pie, "maya.set_tangents", label, icon, kind=kind)


_last_hidden = []


class MAYA_OT_hide_selection(Operator):
    """Maya Ctrl+H: hide the selection (remembered for Ctrl+Shift+H)"""
    bl_idname = "maya.hide_selection"
    bl_label = "Hide Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _last_hidden[:] = [ob.name for ob in context.selected_objects]
        for ob in context.selected_objects:
            ob.hide_set(True)
        return {'FINISHED'}


class MAYA_OT_show_hidden(Operator):
    """Maya Ctrl+Shift+H shows the last hidden objects; Shift+H shows hidden objects selected in the Outliner"""
    bl_idname = "maya.show_hidden"
    bl_label = "Show Hidden"
    bl_options = {'REGISTER', 'UNDO'}

    which: bpy.props.EnumProperty(items=(('LAST', "Last Hidden", ""), ('SELECTED', "Selection", "")))

    def execute(self, context):
        if self.which == 'LAST':
            obs = [context.view_layer.objects.get(name) for name in _last_hidden]
        else:
            obs = [ob for ob in context.view_layer.objects if ob.select_get()]
        for ob in filter(None, obs):
            ob.hide_set(False)
            ob.select_set(True)
        return {'FINISHED'}


class MAYA_MT_shift_rmb(Menu):
    """Shift+right click: create (nothing selected), polygon tools (object), component tools (components)"""
    bl_label = "Polygon Tools"

    def draw(self, context):
        pie = self.layout.menu_pie()
        if context.mode == 'EDIT_MESH':
            from maya_mode import COMPONENT_TOOLS, _component_kind
            label, tools = COMPONENT_TOOLS[_component_kind(context)]
            # Common component items around the pie (W, E, S, N, NW, NE, SW, SE).
            _op(pie, "view3d.edit_mesh_extrude_move_normal", "Extrude", 'FACESEL')
            _op(pie, "mesh.remove_doubles", "Merge", 'AUTOMERGE_ON', threshold=0.001)
            box = pie.box().column(align=True)
            box.label(text=label)
            for item_label, idname, icon, props in tools:
                _op(box, idname, item_label, icon, **props)
            _op(pie, "mesh.knife_tool", "Multi-Cut", 'MOD_SIMPLEDEFORM')
            _op(pie, "maya.connect", "Connect Components", 'MOD_EDGESPLIT')
            _op(pie, "maya.delete_components", "Delete", 'X')
            _op(pie, "mesh.split", "Detach Components", 'MOD_EXPLODE')
            _op(pie, "transform.edge_crease", "Crease Tool", 'MOD_SMOOTH')
        elif context.selected_objects:
            _op(pie, "object.join", "Combine", 'AUTOMERGE_ON')
            _op(pie, "maya.separate", "Separate", 'MOD_EXPLODE')
            box = pie.box().column(align=True)
            box.label(text="Polygon Tools")
            for item_label, idname, icon, props in POLY_OBJECT_TOOLS:
                _op(box, idname, item_label, icon, **props)
            _op(pie, "object.subdivision_set", "Smooth", 'MOD_SUBSURF', level=1, relative=False)
            _op(pie, "maya.boolean", "Booleans: Union", 'SELECT_EXTEND', operation='UNION')
            _op(pie, "maya.boolean", "Booleans: Difference", 'SELECT_SUBTRACT', operation='DIFFERENCE')
            _op(pie, "object.modifier_add", "Mirror", 'MOD_MIRROR', type='MIRROR')
            _op(pie, "maya.fill_hole", "Fill Hole", 'SNAP_FACE')
        else:
            for kind, icon in (('SPHERE', 'MESH_UVSPHERE'), ('CUBE', 'MESH_CUBE'), ('CYLINDER', 'MESH_CYLINDER'),
                               ('PLANE', 'MESH_PLANE'), ('CONE', 'MESH_CONE'), ('TORUS', 'MESH_TORUS')):
                _op(pie, "maya.add_primitive", kind.title(), icon, kind=kind)
            _op(pie, "object.camera_add", "Camera", 'CAMERA_DATA')
            pie.menu("VIEW3D_MT_light_add", text="Lights", icon='LIGHT')


POLY_OBJECT_TOOLS = (
    ("Triangulate", "object.modifier_add", 'MOD_TRIANGULATE', {"type": 'TRIANGULATE'}),
    ("Reduce", "object.modifier_add", 'MOD_DECIM', {"type": 'DECIMATE'}),
    ("Remesh", "object.modifier_add", 'MOD_REMESH', {"type": 'REMESH'}),
    ("Booleans: Intersection", "maya.boolean", 'SELECT_INTERSECT', {"operation": 'INTERSECT'}),
    ("Smooth Shading", "object.shade_smooth", 'SHADING_SOLID', {}),
    ("Soften/Harden by Angle", "object.shade_smooth_by_angle", 'MOD_SMOOTH', {}),
    ("Center Pivot", "object.origin_set", 'PIVOT_BOUNDBOX', {"type": 'ORIGIN_GEOMETRY'}),
    ("Freeze Transformations", "object.transform_apply", 'FREEZE',
     {"location": True, "rotation": True, "scale": True}),
    ("Delete History", "object.convert", 'TRASH', {"target": 'MESH'}),
)


def draw_object_list(layout):
    """Lower half of Maya's object marking menu: selection and material items."""
    _op(layout, "object.select_all", "Select All", 'SELECT_EXTEND', action='SELECT')
    _op(layout, "object.select_all", "Deselect All", 'SELECT_SET', action='DESELECT')
    _op(layout, "object.select_grouped", "Select Hierarchy", 'OUTLINER', type='CHILDREN_RECURSIVE', extend=True)
    _op(layout, "object.select_all", "Invert Selection", 'SELECT_DIFFERENCE', action='INVERT')
    layout.operator_menu_enum("object.select_grouped", "type", text="Select Similar")
    layout.separator()
    _op(layout, "maya.group", "Group", 'EMPTY_AXIS')
    _op(layout, "maya.assign_material", "Assign New Material", 'MATERIAL')
    layout.operator_menu_enum("maya.assign_existing_material", "material", text="Assign Existing Material")


class MAYA_OT_assign_existing_material(Operator):
    """Assign an existing material to the selection"""
    bl_idname = "maya.assign_existing_material"
    bl_label = "Assign Existing Material"
    bl_options = {'REGISTER', 'UNDO'}

    material: bpy.props.EnumProperty(items=lambda _s, _c: [(m.name, m.name, "") for m in bpy.data.materials]
                                     or [("", "(no materials)", "")])

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        for ob in context.selected_objects:
            if mat and ob.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
                ob.data.materials.clear()
                ob.data.materials.append(mat)
        return {'FINISHED'}


class MAYA_MT_transform_mm(Menu):
    """Ctrl+Shift+right click: transform options (symmetry, soft select, selection)"""
    bl_label = "Transform Options"

    def draw(self, context):
        pie = self.layout.menu_pie()
        ts = context.tool_settings
        ob = context.active_object
        mesh = ob.data if ob is not None and ob.type == 'MESH' else None
        if mesh is not None:
            pie.prop(mesh, "use_mirror_x", text="Symmetry X")
        else:
            pie.separator()
        soft = "use_proportional_edit" if context.mode == 'EDIT_MESH' else "use_proportional_edit_objects"
        pie.prop(ts, soft, text="Soft Select")
        pie.prop(ts, "use_transform_correct_face_attributes", text="Preserve UVs")
        pie.prop(context.space_data.shading, "show_xray", text="Camera Based Off (X-Ray)")
        if mesh is not None:
            pie.prop(mesh, "use_mirror_y", text="Symmetry Y")
            pie.prop(mesh, "use_mirror_z", text="Symmetry Z")
        else:
            pie.separator()
            pie.separator()
        _op(pie, "wm.tool_set_by_id", "Tweak Mode", 'RESTRICT_SELECT_OFF', name="builtin.select")
        pie.prop(ts, "use_snap", text="Snapping")


# -----------------------------------------------------------------------------
# Manipulator drags

def _highlighted_gizmo(context):
    group = getattr(context, "gizmo_group", None)
    return next((g for g in group.gizmos if g.is_highlight), None) if group else None


def _drag_constraint(gz):
    idname = getattr(gz, "bl_idname", "") if gz else ""
    if "arrow" in idname:
        return (False, False, True)
    if "primitive" in idname:
        return (True, True, False)
    return None


class MAYA_OT_gizmo_shift_drag(Operator):
    """Maya Shift+drag on the manipulator: extrude components, duplicate objects"""
    bl_idname = "maya.gizmo_shift_drag"
    bl_label = "Shift+Drag Manipulator"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def invoke(self, context, _event):
        gz = _highlighted_gizmo(context)
        constraint = _drag_constraint(gz)
        translate = {} if constraint is None else {
            "orient_type": 'GLOBAL',
            "orient_matrix": gz.matrix_basis.to_3x3().normalized(),
            "orient_matrix_type": 'GLOBAL',
            "constraint_axis": constraint,
        }
        if context.mode == 'OBJECT':
            return bpy.ops.object.duplicate_move('INVOKE_DEFAULT', TRANSFORM_OT_translate=translate)
        if constraint is None:
            return bpy.ops.view3d.edit_mesh_extrude_move_normal('INVOKE_DEFAULT')
        return bpy.ops.mesh.extrude_context_move('INVOKE_DEFAULT', TRANSFORM_OT_translate=translate)


class MAYA_OT_gizmo_slide(Operator):
    """Maya Ctrl+Shift+drag on the manipulator: slide the components along their edges"""
    bl_idname = "maya.gizmo_slide"
    bl_label = "Slide Components"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, _event):
        if context.tool_settings.mesh_select_mode[0]:
            return bpy.ops.transform.vert_slide('INVOKE_DEFAULT')
        return bpy.ops.transform.edge_slide('INVOKE_DEFAULT')


# -----------------------------------------------------------------------------
# View undo, last tool (watched by a light timer)

VIEW_HISTORY_MAX = 50
_view_history = {}   # area pointer -> {"stack": [...], "index": int}
_last_tool = {"current": None, "previous": None}
_QWER = {"builtin.select", "builtin.select_box", "builtin.select_circle", "builtin.select_lasso",
         "builtin.move", "builtin.rotate", "builtin.scale", "builtin.transform"}


def _watch():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            rv3d = area.spaces.active.region_3d
            state = (tuple(rv3d.view_location), tuple(rv3d.view_rotation), rv3d.view_distance,
                     rv3d.view_perspective)
            hist = _view_history.setdefault(area.as_pointer(), {"stack": [], "index": -1})
            if hist["index"] >= 0 and hist["stack"][hist["index"]] == state:
                continue
            del hist["stack"][hist["index"] + 1:]
            hist["stack"].append(state)
            del hist["stack"][:-VIEW_HISTORY_MAX]
            hist["index"] = len(hist["stack"]) - 1
        workspace = win.workspace
        tool = workspace.tools.from_space_view3d_mode(bpy.context.mode, create=False) if workspace else None
        idname = tool.idname if tool else None
        if idname and idname != _last_tool["current"]:
            if _last_tool["current"] not in _QWER and _last_tool["current"]:
                _last_tool["previous"] = _last_tool["current"]
            _last_tool["current"] = idname
    return 0.3


class MAYA_OT_view_history(Operator):
    """Maya [ / ]: undo / redo view changes"""
    bl_idname = "maya.view_history"
    bl_label = "Undo View Change"

    step: bpy.props.IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        hist = _view_history.get(context.area.as_pointer())
        if not hist:
            return {'CANCELLED'}
        index = max(0, min(len(hist["stack"]) - 1, hist["index"] + self.step))
        location, rotation, distance, perspective = hist["stack"][index]
        hist["index"] = index
        rv3d = context.region_data
        rv3d.view_location, rv3d.view_rotation, rv3d.view_distance = location, rotation, distance
        rv3d.view_perspective = perspective
        return {'FINISHED'}


class MAYA_OT_last_tool(Operator):
    """Maya Y: reactivate the last tool that was not Select / Move / Rotate / Scale"""
    bl_idname = "maya.last_tool"
    bl_label = "Last Tool"

    def execute(self, context):
        tool = _last_tool["previous"] or _last_tool["current"]
        if tool is None or tool in _QWER:
            return {'CANCELLED'}
        bpy.ops.wm.tool_set_by_id(name=tool)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Nudge, pickwalk, background, soft select radius

class MAYA_OT_cut(Operator):
    """Maya Ctrl+X: copy the selected objects to the clipboard buffer and delete them"""
    bl_idname = "maya.cut"
    bl_label = "Cut"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def execute(self, _context):
        bpy.ops.view3d.copybuffer()
        bpy.ops.object.delete(confirm=False)
        return {'FINISHED'}


class MAYA_OT_nudge(Operator):
    """Maya Alt+arrow: move the selection one pixel"""
    bl_idname = "maya.nudge"
    bl_label = "Nudge"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(items=[(d, d.title(), "") for d in ('UP', 'DOWN', 'LEFT', 'RIGHT')])

    def execute(self, context):
        from bpy_extras.view3d_utils import region_2d_to_location_3d, location_3d_to_region_2d
        region, rv3d = context.region, context.region_data
        ob = context.active_object
        if ob is None or rv3d is None:
            return {'CANCELLED'}
        origin = ob.matrix_world.translation
        p = location_3d_to_region_2d(region, rv3d, origin) or Vector((region.width / 2, region.height / 2))
        step = {'UP': (0, 1), 'DOWN': (0, -1), 'LEFT': (-1, 0), 'RIGHT': (1, 0)}[self.direction]
        delta = region_2d_to_location_3d(region, rv3d, p + Vector(step), origin) - origin
        bpy.ops.transform.translate(value=delta)
        return {'FINISHED'}


class MAYA_OT_pickwalk(Operator):
    """Maya pickwalk: arrows walk up / down the hierarchy and left / right between siblings"""
    bl_idname = "maya.pickwalk"
    bl_label = "Pickwalk"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(items=[(d, d.title(), "") for d in ('UP', 'DOWN', 'LEFT', 'RIGHT')])

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object is not None

    def execute(self, context):
        ob = context.active_object
        if self.direction == 'UP':
            target = ob.parent
        elif self.direction == 'DOWN':
            target = ob.children[0] if ob.children else None
        else:
            siblings = sorted(ob.parent.children if ob.parent else
                              [o for o in context.scene.objects if o.parent is None], key=lambda o: o.name)
            i = siblings.index(ob) + (1 if self.direction == 'RIGHT' else -1)
            target = siblings[i % len(siblings)]
        if target is None:
            return {'CANCELLED'}
        ob.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        return {'FINISHED'}


BACKGROUNDS = (None, (0.0, 0.0, 0.0), (0.24, 0.24, 0.24), (0.63, 0.63, 0.63))


class MAYA_OT_cycle_background(Operator):
    """Maya Alt+B: cycle the viewport background (gradient, black, dark grey, light grey)"""
    bl_idname = "maya.cycle_background"
    bl_label = "Cycle Background"

    def execute(self, context):
        shading = context.space_data.shading
        if shading.background_type == 'THEME':
            index = 0
        else:
            color = tuple(round(c, 2) for c in shading.background_color)
            index = next((i for i, c in enumerate(BACKGROUNDS) if c == color), 0)
        nxt = BACKGROUNDS[(index + 1) % len(BACKGROUNDS)]
        if nxt is None:
            shading.background_type = 'THEME'
        else:
            shading.background_type = 'VIEWPORT'
            shading.background_color = nxt
        return {'FINISHED'}


class MAYA_OT_soft_radius(Operator):
    """Maya B: tap toggles soft selection, hold B and drag to change its radius"""
    bl_idname = "maya.soft_radius"
    bl_label = "Soft Select Radius"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self.key, self.dragged, self.start_x = event.type, False, None
        self.prop = "use_proportional_edit" if context.mode == 'EDIT_MESH' else "use_proportional_edit_objects"
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        ts = context.tool_settings
        if event.type == self.key and event.value == 'RELEASE':
            if not self.dragged:
                setattr(ts, self.prop, not getattr(ts, self.prop))
            context.area.header_text_set(None)
            return {'FINISHED'}
        if event.type == 'LEFTMOUSE':
            self.start_x = event.mouse_x if event.value == 'PRESS' else None
            self.start_size = ts.proportional_size
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and self.start_x is not None:
            self.dragged = True
            setattr(ts, self.prop, True)
            ts.proportional_size = max(0.001, self.start_size * (1.0 + (event.mouse_x - self.start_x) / 200.0))
            context.area.header_text_set("Soft Select radius: %.3f" % ts.proportional_size)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


classes = (
    MAYA_OT_key_marking_menu,
    MAYA_MT_select_mm,
    MAYA_MT_move_mm,
    MAYA_MT_rotate_mm,
    MAYA_MT_scale_mm,
    MAYA_MT_io_mm,
    MAYA_MT_menu_set_mm,
    MAYA_MT_keyframe_mm,
    MAYA_MT_shift_rmb,
    MAYA_OT_assign_existing_material,
    MAYA_MT_transform_mm,
    MAYA_OT_gizmo_shift_drag,
    MAYA_OT_gizmo_slide,
    MAYA_OT_view_history,
    MAYA_OT_last_tool,
    MAYA_OT_cut,
    MAYA_OT_set_tangents,
    MAYA_MT_tangent_mm,
    MAYA_OT_hide_selection,
    MAYA_OT_show_hidden,
    MAYA_OT_nudge,
    MAYA_OT_pickwalk,
    MAYA_OT_cycle_background,
    MAYA_OT_soft_radius,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background:
        bpy.app.timers.register(_watch, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
