# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya marking menus and the Maya hotkey operators that need Python:
hold Q/W/E/R/A/H/Shift+S + left click, Shift / Ctrl+Shift right click, manipulator Shift / Ctrl+Shift drags,
view undo ([ ]), nudge (Alt+arrows), pickwalk, last tool (Y), background cycle (Alt+B), soft select radius (B).
"""

import bpy
from bpy.types import Macro, Menu, Operator
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

class M3D_OT_key_marking_menu(Operator):
    """Hotkey: tap runs the tool or command, hold the key and left click for its marking menu"""
    bl_idname = "m3d.key_marking_menu"
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
            M3D_OT_key_marking_menu.last_menu = menu  # Read by tools/m3d/gui_test.py.
            return {'FINISHED'}
        return {'PASS_THROUGH'}


class M3D_MT_select_mm(Menu):
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


class M3D_MT_move_mm(Menu):
    """W + left click: move tool orientation and options"""
    bl_label = "Move Tool"

    def draw(self, context):
        _transform_mm(self.layout.menu_pie(), context, "Move Options", "translate")


class M3D_MT_rotate_mm(Menu):
    """E + left click: rotate tool orientation and options"""
    bl_label = "Rotate Tool"

    def draw(self, context):
        _transform_mm(self.layout.menu_pie(), context, "Rotate Options", "rotate")


class M3D_MT_scale_mm(Menu):
    """R + left click: scale tool orientation and options"""
    bl_label = "Scale Tool"

    def draw(self, context):
        _transform_mm(self.layout.menu_pie(), context, "Scale Options", "scale")


class M3D_MT_io_mm(Menu):
    """A + left click: inputs / outputs (history)"""
    bl_label = "History Operations"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        _op(pie, "object.convert", "Delete History", 'TRASH', target='MESH')
        _op(pie, "object.transform_apply", "Freeze Transformations", 'FREEZE',
            location=True, rotation=True, scale=True)
        _op(pie, "object.origin_set", "Center Pivot", 'PIVOT_BOUNDBOX', type='ORIGIN_GEOMETRY')
        _op(pie, "m3d.reset_transformations", "Reset Transformations", 'LOOP_BACK')
        _op(pie, "m3d.dock_tab", "Show Inputs (Attribute Editor)", 'MODIFIER', tab='MODIFIER')


class M3D_MT_menu_set_mm(Menu):
    """H + left click: menu sets"""
    bl_label = "Menu Sets"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        from m3d_ui import MENU_SETS
        for value, (label, _menus) in MENU_SETS.items():
            _op(pie, "wm.context_set_enum", label, data_path="window_manager.m3d_menu_set", value=value)


class M3D_MT_keyframe_mm(Menu):
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
        _op(pie, "m3d.open_editor", "Graph Editor", 'GRAPH', ui_type='FCURVES')
        _op(pie, "m3d.open_editor", "Dope Sheet", 'ACTION', ui_type='DOPESHEET')


# -----------------------------------------------------------------------------
# Right click variants

TANGENTS = (
    ('SPLINE', "Spline", 'IPO_BEZIER'), ('LINEAR', "Linear", 'IPO_LINEAR'), ('CLAMPED', "Clamped", 'HANDLE_AUTOCLAMPED'),
    ('FLAT', "Flat", 'IPO_CONSTANT'), ('STEPPED', "Stepped", 'IPO_CONSTANT'), ('PLATEAU', "Plateau", 'HANDLE_AUTOCLAMPED'),
)


class M3D_OT_set_tangents(Operator):
    """Tangents for the selected objects' keys (Spline, Linear, Clamped, Flat, Stepped, Plateau)"""
    bl_idname = "m3d.set_tangents"
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


class M3D_MT_tangent_mm(Menu):
    """Shift+S + middle click: key tangents"""
    bl_label = "Tangents"

    def draw(self, _context):
        pie = self.layout.menu_pie()
        for kind, label, icon in TANGENTS:
            _op(pie, "m3d.set_tangents", label, icon, kind=kind)


_last_hidden = []


class M3D_OT_hide_selection(Operator):
    """Ctrl+H: hide the selection (remembered for Ctrl+Shift+H)"""
    bl_idname = "m3d.hide_selection"
    bl_label = "Hide Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _last_hidden[:] = [ob.name for ob in context.selected_objects]
        for ob in context.selected_objects:
            ob.hide_set(True)
        return {'FINISHED'}


class M3D_OT_show_hidden(Operator):
    """Ctrl+Shift+H shows the last hidden objects; Shift+H shows hidden objects selected in the Outliner"""
    bl_idname = "m3d.show_hidden"
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


class M3D_MT_shift_rmb(Menu):
    """Shift+right click: create (nothing selected), polygon tools (object), component tools (components)"""
    bl_label = "Polygon Tools"

    def draw(self, context):
        pie = self.layout.menu_pie()
        if context.mode == 'EDIT_MESH':
            from m3d_mode import COMPONENT_TOOLS, _component_kind
            label, tools = COMPONENT_TOOLS[_component_kind(context)]
            # Common component items around the pie (W, E, S, N, NW, NE, SW, SE).
            _op(pie, "view3d.edit_mesh_extrude_move_normal", "Extrude", 'FACESEL')
            _op(pie, "mesh.remove_doubles", "Merge", 'AUTOMERGE_ON', threshold=0.001)
            box = pie.box().column(align=True)
            box.label(text=label)
            for item_label, idname, icon, props in tools:
                _op(box, idname, item_label, icon, **props)
            _op(pie, "mesh.knife_tool", "Multi-Cut", 'MOD_SIMPLEDEFORM')
            _op(pie, "m3d.connect", "Connect Components", 'MOD_EDGESPLIT')
            _op(pie, "m3d.delete_components", "Delete", 'X')
            _op(pie, "mesh.split", "Detach Components", 'MOD_EXPLODE')
            _op(pie, "transform.edge_crease", "Crease Tool", 'MOD_SMOOTH')
        elif context.selected_objects:
            _op(pie, "object.join", "Combine", 'AUTOMERGE_ON')
            _op(pie, "m3d.separate", "Separate", 'MOD_EXPLODE')
            box = pie.box().column(align=True)
            box.label(text="Polygon Tools")
            for item_label, idname, icon, props in POLY_OBJECT_TOOLS:
                _op(box, idname, item_label, icon, **props)
            _op(pie, "object.subdivision_set", "Smooth", 'MOD_SUBSURF', level=1, relative=False)
            _op(pie, "m3d.boolean", "Booleans: Union", 'SELECT_EXTEND', operation='UNION')
            _op(pie, "m3d.boolean", "Booleans: Difference", 'SELECT_SUBTRACT', operation='DIFFERENCE')
            _op(pie, "object.modifier_add", "Mirror", 'MOD_MIRROR', type='MIRROR')
            _op(pie, "m3d.fill_hole", "Fill Hole", 'SNAP_FACE')
        else:
            for kind, icon in (('SPHERE', 'MESH_UVSPHERE'), ('CUBE', 'MESH_CUBE'), ('CYLINDER', 'MESH_CYLINDER'),
                               ('PLANE', 'MESH_PLANE'), ('CONE', 'MESH_CONE'), ('TORUS', 'MESH_TORUS')):
                _op(pie, "m3d.add_primitive", kind.title(), icon, kind=kind)
            _op(pie, "object.camera_add", "Camera", 'CAMERA_DATA')
            pie.menu("VIEW3D_MT_light_add", text="Lights", icon='LIGHT')


POLY_OBJECT_TOOLS = (
    ("Triangulate", "object.modifier_add", 'MOD_TRIANGULATE', {"type": 'TRIANGULATE'}),
    ("Reduce", "object.modifier_add", 'MOD_DECIM', {"type": 'DECIMATE'}),
    ("Remesh", "object.modifier_add", 'MOD_REMESH', {"type": 'REMESH'}),
    ("Booleans: Intersection", "m3d.boolean", 'SELECT_INTERSECT', {"operation": 'INTERSECT'}),
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
    _op(layout, "m3d.group", "Group", 'EMPTY_AXIS')
    _op(layout, "m3d.assign_material", "Assign New Material", 'MATERIAL')
    layout.operator_menu_enum("m3d.assign_existing_material", "material", text="Assign Existing Material")
    layout.menu("M3D_MT_hplp", icon='MOD_MULTIRES')


class M3D_OT_assign_existing_material(Operator):
    """Assign an existing material to the selection"""
    bl_idname = "m3d.assign_existing_material"
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


class M3D_MT_transform_mm(Menu):
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


# The transform gizmo group (VIEW3D_GGT_xform_gizmo) creates its 19 gizmos in this order (gizmogroup_init in
# transform_gizmo_3d.cc), and a gizmo carries no hint of its transform: the arrows of Move and Scale are both
# arrow_3d (and the plane handles look alike), so the position in the group tells them apart.
# Entries: (transform, axes), axes being the constraint axes in the gizmo's orientation (C: centre handle).
_XFORM_GIZMOS = (
    ('trackball', ""),
    ('resize', "C"), ('resize', "X"), ('resize', "Y"), ('resize', "Z"),
    ('resize', "XY"), ('resize', "YZ"), ('resize', "ZX"),
    ('rotate', "X"), ('rotate', "Y"), ('rotate', "Z"), ('rotate', "C"),
    ('translate', "C"), ('translate', "X"), ('translate', "Y"), ('translate', "Z"),
    ('translate', "XY"), ('translate', "YZ"), ('translate', "ZX"),
)


def _gizmo_transform(context, gz):
    """(transform, axes) of a transform gizmo handle: 'translate', 'rotate', 'resize' or 'trackball'; None when
    `gz` is not one (another tool's gizmo, or the group changed)."""
    group = getattr(context, "gizmo_group", None)
    gizmos = list(group.gizmos) if group else []
    if gz is None or len(gizmos) != len(_XFORM_GIZMOS) or not group.name.endswith("Transform Gizmo"):
        return None
    return _XFORM_GIZMOS[gizmos.index(gz)]


def _gizmo_orientation(gz, axes):
    """Operator properties that make a transform follow a handle: its axes in the gizmo's orientation (the
    handle's matrix without the per-handle offset). The centre handle has no axis."""
    if axes == "C":
        return {}
    return {
        "orient_type": 'GLOBAL',
        "orient_matrix": (gz.matrix_world.to_3x3() @ gz.matrix_offset.to_3x3().inverted()).normalized(),
        "orient_matrix_type": 'GLOBAL',
        "constraint_axis": tuple(a in axes for a in "XYZ"),
    }


class M3D_OT_extrude_resize(Macro):
    """Extrude the selected components, then scale them"""
    bl_idname = "m3d.extrude_resize"
    bl_label = "Extrude and Scale"
    bl_options = {'REGISTER', 'UNDO'}


class M3D_OT_duplicate_resize(Macro):
    """Duplicate the selected objects, then scale them"""
    bl_idname = "m3d.duplicate_resize"
    bl_label = "Duplicate and Scale"
    bl_options = {'REGISTER', 'UNDO'}


class M3D_OT_extrude_rotate(Macro):
    """Extrude the selected components, then rotate them"""
    bl_idname = "m3d.extrude_rotate"
    bl_label = "Extrude and Rotate"
    bl_options = {'REGISTER', 'UNDO'}


class M3D_OT_duplicate_rotate(Macro):
    """Duplicate the selected objects, then rotate them"""
    bl_idname = "m3d.duplicate_rotate"
    bl_label = "Duplicate and Rotate"
    bl_options = {'REGISTER', 'UNDO'}


# Macro -> its two steps; each macro is one undo step (Move has the stock extrude_context_move / duplicate_move).
MACROS = (
    (M3D_OT_extrude_resize, "MESH_OT_extrude_context", "TRANSFORM_OT_resize"),
    (M3D_OT_duplicate_resize, "OBJECT_OT_duplicate", "TRANSFORM_OT_resize"),
    (M3D_OT_extrude_rotate, "MESH_OT_extrude_context", "TRANSFORM_OT_rotate"),
    (M3D_OT_duplicate_rotate, "OBJECT_OT_duplicate", "TRANSFORM_OT_rotate"),
)


class M3D_OT_gizmo_shift_drag(Operator):
    """Shift+drag on the manipulator: extrude components, duplicate objects, then move / rotate / scale them
    like the handle does"""
    bl_idname = "m3d.gizmo_shift_drag"
    bl_label = "Shift+Drag Manipulator"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def invoke(self, context, _event):
        gz = _highlighted_gizmo(context)
        kind, axes = _gizmo_transform(context, gz) or (None, "")
        # Scale (all handles) and the X / Y / Z rotation rings run the extrude / duplicate and then the same
        # transform as the handle; the view ring and the trackball (and Move) keep the extrude and move below.
        if kind == 'resize' or (kind == 'rotate' and axes != "C"):
            macro = getattr(bpy.ops.m3d, ("duplicate_" if context.mode == 'OBJECT' else "extrude_") + kind)
            return macro('INVOKE_DEFAULT', **{"TRANSFORM_OT_" + kind: _gizmo_orientation(gz, axes)})
        constraint = _drag_constraint(gz)
        translate = {} if constraint is None else {
            "orient_type": 'GLOBAL',
            # The transform gizmo keeps each axis direction in matrix_offset, so matrix_basis is always +Z.
            "orient_matrix": gz.matrix_world.to_3x3().normalized(),
            "orient_matrix_type": 'GLOBAL',
            "constraint_axis": constraint,
        }
        if context.mode == 'OBJECT':
            return bpy.ops.object.duplicate_move('INVOKE_DEFAULT', TRANSFORM_OT_translate=translate)
        if constraint is None:
            return bpy.ops.view3d.edit_mesh_extrude_move_normal('INVOKE_DEFAULT')
        return bpy.ops.mesh.extrude_context_move('INVOKE_DEFAULT', TRANSFORM_OT_translate=translate)


class M3D_OT_gizmo_slide(Operator):
    """Ctrl+Shift+drag on the manipulator: slide the components along their edges"""
    bl_idname = "m3d.gizmo_slide"
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


class M3D_OT_view_history(Operator):
    """[ / ]: undo / redo view changes"""
    bl_idname = "m3d.view_history"
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


class M3D_OT_last_tool(Operator):
    """Y: reactivate the last tool that was not Select / Move / Rotate / Scale"""
    bl_idname = "m3d.last_tool"
    bl_label = "Last Tool"

    def execute(self, context):
        tool = _last_tool["previous"] or _last_tool["current"]
        if tool is None or tool in _QWER:
            return {'CANCELLED'}
        bpy.ops.wm.tool_set_by_id(name=tool)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Nudge, pickwalk, background, soft select radius

class M3D_OT_cut(Operator):
    """Ctrl+X: copy the selected objects to the clipboard buffer and delete them"""
    bl_idname = "m3d.cut"
    bl_label = "Cut"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.selected_objects

    def execute(self, _context):
        bpy.ops.view3d.copybuffer()
        bpy.ops.object.delete(confirm=False)
        return {'FINISHED'}


class M3D_OT_nudge(Operator):
    """Alt+arrow: move the selection one pixel"""
    bl_idname = "m3d.nudge"
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


class M3D_OT_pickwalk(Operator):
    """Pickwalk: arrows walk up / down the hierarchy and left / right between siblings"""
    bl_idname = "m3d.pickwalk"
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


class M3D_OT_cycle_background(Operator):
    """Alt+B: cycle the viewport background (gradient, black, dark grey, light grey)"""
    bl_idname = "m3d.cycle_background"
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


class M3D_OT_soft_radius(Operator):
    """B: tap toggles soft selection, hold B and drag to change its radius"""
    bl_idname = "m3d.soft_radius"
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
    M3D_OT_key_marking_menu,
    M3D_MT_select_mm,
    M3D_MT_move_mm,
    M3D_MT_rotate_mm,
    M3D_MT_scale_mm,
    M3D_MT_io_mm,
    M3D_MT_menu_set_mm,
    M3D_MT_keyframe_mm,
    M3D_MT_shift_rmb,
    M3D_OT_assign_existing_material,
    M3D_MT_transform_mm,
    M3D_OT_extrude_resize,
    M3D_OT_duplicate_resize,
    M3D_OT_extrude_rotate,
    M3D_OT_duplicate_rotate,
    M3D_OT_gizmo_shift_drag,
    M3D_OT_gizmo_slide,
    M3D_OT_view_history,
    M3D_OT_last_tool,
    M3D_OT_cut,
    M3D_OT_set_tangents,
    M3D_MT_tangent_mm,
    M3D_OT_hide_selection,
    M3D_OT_show_hidden,
    M3D_OT_nudge,
    M3D_OT_pickwalk,
    M3D_OT_cycle_background,
    M3D_OT_soft_radius,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for macro, *steps in MACROS:
        for step in steps:
            macro.define(step)
    if not bpy.app.background:
        bpy.app.timers.register(_watch, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
