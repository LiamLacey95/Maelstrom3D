# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Sculpt workspace (F2) for Maelstrom3D: the brush tray (left), the dock pages (Geometry, Mask, Face Sets, Deform,
Paint, Display, Objects), the Sculpt Status Line, shelf items and the operators behind them.

The layout is built by tools/m3d/build_startup.py (phase1_sculpt), the tabs are DOCK_TABS['SCULPT'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py. Controls that stock Blender already draws (brush settings,
falloff, stroke, palette) are the stock panel classes, re-used on the dock pages.
"""

from ast import literal_eval

import bpy
from bpy.types import Operator, Panel
from bl_ui.properties_paint_common import (
    BrushSelectPanel, ColorPalettePanel, DisplayPanel, FalloffPanel, SmoothStrokePanel, StrokePanel,
    UnifiedPaintPanel, brush_settings, brush_settings_advanced, brush_texture_settings)

from m3d_mode import _button
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Brushes

BRUSH_ASSET = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"
# (label, asset name): the tray grid, the Sculpt shelf and the hotbox
BRUSHES = (
    ("Draw", "Draw"), ("Clay Strips", "Clay Strips"), ("Clay", "Clay"), ("Smooth", "Smooth"),
    ("Grab", "Grab"), ("Elastic Grab", "Elastic Grab"), ("Snake Hook", "Snake Hook"),
    ("Inflate/Deflate", "Inflate/Deflate"), ("Pinch/Magnify", "Pinch/Magnify"), ("Crease Sharp", "Crease Sharp"),
    ("Flatten/Contrast", "Flatten/Contrast"), ("Scrape/Fill", "Scrape/Fill"), ("Layer", "Layer"),
    ("Mask", "Mask"), ("Face Set Paint", "Face Set Paint"),
)
PAINT_BRUSHES = tuple((name, name) for name in ("Paint Soft", "Paint Hard", "Airbrush", "Paint Blend", "Blur", "Smear"))
# Shift+1 ... Shift+7 (the keymap file repeats the names; test_m3d.py checks them)
BRUSH_KEYS = ("Draw", "Clay Strips", "Smooth", "Grab", "Inflate/Deflate", "Pinch/Magnify", "Crease Sharp")


def brush_props(name):
    return {"asset_library_type": 'ESSENTIALS', "relative_asset_identifier": BRUSH_ASSET + name}


def brush_item(label, name):
    """Brush button for a shelf (the optional fourth entry is the button text)."""
    return ("brush.asset_activate", 'NONE', brush_props(name), label)


def active_brush_id(context):
    ts = context.tool_settings
    paint = ts.image_paint if context.mode == 'PAINT_TEXTURE' else ts.sculpt
    ref = paint.brush_asset_reference if paint else None
    return ref.relative_asset_identifier if ref else ""


def is_active(context, idname, props):
    """True for the button of the brush that is active (shelf and tray draw it pressed)."""
    return idname == "brush.asset_activate" and props.get("relative_asset_identifier") == active_brush_id(context)


def draw_brush_column(layout):
    """Hotbox section: pick a brush (the hotbox runs in the viewport, so the operator is called directly)."""
    layout.label(text="Brushes")
    for label, name in BRUSHES:
        o = layout.operator("brush.asset_activate", text=label)
        for key, value in brush_props(name).items():
            setattr(o, key, value)


# -----------------------------------------------------------------------------
# Helpers

def mesh_of(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'MESH' else None


def multires_of(ob):
    return next((m for m in ob.modifiers if m.type == 'MULTIRES'), None)


def ready(context, need):
    """Can a page with this need be used: None always, 'MESH' with an active mesh, 'SCULPT' also in Sculpt Mode."""
    if need is None:
        return True
    return mesh_of(context) is not None and (need == 'MESH' or context.mode == 'SCULPT')


def viewport(context):
    """The main 3D Viewport's space (docks and the top bar have none of their own)."""
    screen = context.screen
    areas = [a for a in screen.areas if a.type == 'VIEW_3D'] if screen else []
    return max(areas, key=lambda a: a.width * a.height).spaces.active if areas else None


def brush_mode(context):
    return UnifiedPaintPanel.get_brush_mode(context)


def active_tool(context):
    tools = context.workspace.tools if context.workspace else None
    return tools.from_space_view3d_mode('SCULPT') if tools else None


def tool_is_active(context, tool, op, props):
    cur = active_tool(context)
    if cur is None or cur.idname != tool:
        return False
    if not op:
        return True
    cur_props = cur.operator_properties(op)
    return all(getattr(cur_props, k, None) == v for k, v in props.items())


def reason(layout, text):
    layout.label(text=text, icon='INFO')


def grid(layout, context, items, columns=2, active=None):
    """Operator buttons: (label, idname, icon, props); `active(idname, props)` draws one pressed."""
    flow = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=True)
    for label, idname, icon, props in items:
        _button(flow, context, label, idname, icon, props,
                depress=bool(active and active(idname, props)))


def tools_grid(layout, context, items, columns=2):
    """Tool buttons: (label, tool id, operator, props). A click sets the tool; the work happens in the viewport."""
    flow = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=True)
    for label, tool, op, props in items:
        o = flow.operator("m3d.sculpt_tool", text=label, depress=tool_is_active(context, tool, op, props))
        o.tool, o.op, o.props, o.label = tool, op, repr(props), label


def split_props(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False


# -----------------------------------------------------------------------------
# Operators

class M3D_OT_sculpt_tool(Operator):
    """Pick a sculpt tool and its options; then use it in the 3D Viewport"""
    bl_idname = "m3d.sculpt_tool"
    bl_label = "Sculpt Tool"
    bl_options = {'INTERNAL'}

    tool: bpy.props.StringProperty()
    op: bpy.props.StringProperty(description="Operator whose options are set (empty: none)")
    props: bpy.props.StringProperty(default="{}")
    label: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return (props.label or props.tool) + ": pick the tool, then use it in the viewport"

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name=self.tool, space_type='VIEW_3D')
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        tool = active_tool(context)
        if self.op and tool is not None and tool.idname == self.tool:
            options = tool.operator_properties(self.op)
            for key, value in literal_eval(self.props).items():
                setattr(options, key, value)
        self.report({'INFO'}, "%s: use it in the viewport" % (self.label or self.tool))
        return {'FINISHED'}


class M3D_OT_multires_subdivide(Operator):
    """Add a Multires level (the Multires modifier is added first when the mesh has none)"""
    bl_idname = "m3d.multires_subdivide"
    bl_label = "Multires Subdivide"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=(
        ('CATMULL_CLARK', "Subdivide", "Smooth subdivision (Catmull-Clark)"),
        ('SIMPLE', "Simple", "Subdivide without smoothing the shape"),
        ('LINEAR', "Linear", "Subdivide the faces linearly, keeping corners sharp"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'CATMULL_CLARK': "Add a Multires level, smoothing the shape", 'SIMPLE': "Add a Multires level without "
                "smoothing the shape", 'LINEAR': "Add a Multires level, keeping corners sharp"}[props.mode]

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        if ob.use_dynamic_topology_sculpting:
            self.report({'WARNING'}, "Turn off Dyntopo to use Multires")
            return {'CANCELLED'}
        try:
            if multires_of(ob) is None:
                bpy.ops.object.modifier_add(type='MULTIRES')
            bpy.ops.object.multires_subdivide(modifier=multires_of(ob).name, mode=self.mode)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_multires_level(Operator):
    """Go one Multires level up or down (viewport and sculpt level)"""
    bl_idname = "m3d.multires_level"
    bl_label = "Multires Level"
    bl_options = {'REGISTER', 'UNDO'}

    delta: bpy.props.IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Show and sculpt the %s Multires level" % ("next" if props.delta > 0 else "previous")

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is not None

    def execute(self, context):
        mod = multires_of(mesh_of(context))
        level = max(0, min(mod.total_levels, mod.sculpt_levels + self.delta))
        mod.levels = mod.sculpt_levels = level
        return {'FINISHED'}


class M3D_OT_multires_edit(Operator):
    """Delete the higher Multires levels, Unsubdivide, or Apply Base"""
    bl_idname = "m3d.multires_edit"
    bl_label = "Multires Edit"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=(
        ('DELETE_HIGHER', "Delete Higher", "Delete the levels above the current one"),
        ('UNSUBDIVIDE', "Unsubdivide", "Rebuild a lower level from the highest one"),
        ('APPLY_BASE', "Apply Base", "Copy the sculpted shape to the base mesh and keep the detail"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'DELETE_HIGHER': "Delete the Multires levels above the current one",
                'UNSUBDIVIDE': "Rebuild a lower Multires level from the highest one",
                'APPLY_BASE': "Apply the sculpted shape to the base mesh and keep the detail"}[props.action]

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is not None

    def execute(self, context):
        name = multires_of(mesh_of(context)).name
        run = {'DELETE_HIGHER': bpy.ops.object.multires_higher_levels_delete,
               'UNSUBDIVIDE': bpy.ops.object.multires_unsubdivide,
               'APPLY_BASE': bpy.ops.object.multires_base_apply}[self.action]
        try:
            run(modifier=name)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


def _show_in_sculpt(context, ob):
    """Make `ob` the only selected, active object (and back in Sculpt Mode if that is where we were)."""
    was_sculpt = context.mode == 'SCULPT'
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in context.selected_objects:
        other.select_set(False)
    ob.hide_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if was_sculpt and ob.type == 'MESH':
        bpy.ops.object.mode_set(mode='SCULPT')


class M3D_OT_sculpt_object(Operator):
    """Objects tab: pick a mesh, show or hide it, solo it, or append a duplicate"""
    bl_idname = "m3d.sculpt_object"
    bl_label = "Sculpt Object"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=(
        ('SELECT', "Sculpt", "Make this the active mesh"),
        ('VISIBLE', "Show / Hide", "Show or hide this mesh in the viewport"),
        ('SOLO', "Solo", "Hide every other mesh (again: show them)"),
        ('DUPLICATE', "Duplicate", "Append a copy of this mesh and sculpt it"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'SELECT': "Make this the active mesh", 'VISIBLE': "Show or hide this mesh in the viewport",
                'SOLO': "Hide every other mesh; click again to show them",
                'DUPLICATE': "Append a copy of this mesh and sculpt it"}[props.action]

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or ob.type != 'MESH':
            return {'CANCELLED'}
        meshes = [o for o in context.view_layer.objects if o.type == 'MESH']
        if self.action == 'VISIBLE':
            if ob is context.active_object and not ob.hide_get() and context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')   # leave Sculpt Mode before the mesh goes away
            ob.hide_set(not ob.hide_get())
            return {'FINISHED'}
        _show_in_sculpt(context, ob)
        if self.action == 'SOLO':
            others = [o for o in meshes if o is not ob]
            hide = not all(o.hide_get() for o in others)
            for o in others:
                o.hide_set(hide)
        elif self.action == 'DUPLICATE':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.duplicate()
            bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}


class M3D_OT_sculpt_add_mesh(Operator):
    """Add a mesh at the origin and start sculpting it"""
    bl_idname = "m3d.sculpt_add_mesh"
    bl_label = "Add Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=(
        ('SPHERE', "Sphere", ""), ('CUBE', "Cube", ""), ('CYLINDER', "Cylinder", ""), ('PLANE', "Plane", ""),
    ))

    @classmethod
    def description(cls, _context, props):
        return "Add a %s and start sculpting it" % props.kind.lower()

    def execute(self, _context):
        bpy.ops.m3d.add_primitive(kind=self.kind)
        bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

class _Page(_PagePanel):
    """Panel that needs `need` (see `ready`)."""
    need = 'SCULPT'

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.need)


class _BrushPage(_PagePanel):
    """Panel for the active brush; the stock mixin classes (falloff, stroke ...) add their own poll."""
    @classmethod
    def page_poll(cls, context):
        stock = super(_PagePanel, cls)
        return ready(context, 'SCULPT') and brush_mode(context) is not None and (
            not hasattr(stock, "poll") or stock.poll(context))


def _gate(page, need):
    """The panel a page shows instead of its own when there is nothing to work on: what to do next."""
    def draw(self, context):
        col = self.layout.column(align=True)
        if mesh_of(context) is None:
            col.label(text="Select a mesh to sculpt")
            col.operator("m3d.sculpt_add_mesh", text="Add Sphere", icon='MESH_UVSPHERE').kind = 'SPHERE'
        else:
            col.label(text="Enter Sculpt Mode to use these tools")
            _button(col, context, "Sculpt Mode", "object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'})
    return type("PROPERTIES_PT_m3d_sc_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Sculpt", "bl_options": {'HIDE_HEADER'}, "page": "sculpt_" + page,
        "page_poll": classmethod(lambda cls, context: not ready(context, need)), "draw": draw})


# --- Left tray: brushes

class PROPERTIES_PT_m3d_sc_brush(_BrushPage, BrushSelectPanel, Panel):
    page = "sculpt_brushes"


class PROPERTIES_PT_m3d_sc_grid(_Page, Panel):
    page = "sculpt_brushes"
    bl_label = "Brushes"

    def draw(self, context):
        grid(self.layout, context, [(label, "brush.asset_activate", 'NONE', brush_props(name))
                                    for label, name in BRUSHES],
             active=lambda idname, props: is_active(context, idname, props))


class PROPERTIES_PT_m3d_sc_tuning(_Page, Panel):
    page = "sculpt_brushes"
    bl_label = "Size and Strength"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        mesh = mesh_of(context).data
        settings = UnifiedPaintPanel.paint_settings(context)
        brush = settings.brush if settings else None
        if brush is not None:
            caps = brush.sculpt_capabilities
            ups = settings.unified_paint_settings
            col = layout.column()
            owner = ups if ups.use_unified_size else brush
            size = "unprojected_size" if owner.use_locked_size == 'SCENE' else "size"
            UnifiedPaintPanel.prop_unified(col, context, brush, size, unified_name="use_unified_size", text="Size",
                                           pressure_name="use_pressure_size" if caps.has_size_pressure else None,
                                           slider=True)
            UnifiedPaintPanel.prop_unified(
                col, context, brush, "strength", unified_name="use_unified_strength",
                pressure_name="use_pressure_strength" if caps.has_strength_pressure else None, slider=True)
            if caps.has_direction:
                col.row().prop(brush, "direction", expand=True)
        else:
            layout.label(text="Pick a brush above")
        row = layout.row(align=True, heading="Mirror")
        for axis in "xyz":
            row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)


class PROPERTIES_PT_m3d_sc_more(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Brush Settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        split_props(self.layout)
        brush_settings(self.layout.column(), context, UnifiedPaintPanel.paint_settings(context).brush, popover=True)


class PROPERTIES_PT_m3d_sc_falloff(_BrushPage, FalloffPanel, Panel):
    page = "sculpt_brushes"


class PROPERTIES_PT_m3d_sc_stroke(_BrushPage, StrokePanel, Panel):
    page = "sculpt_brushes"


class PROPERTIES_PT_m3d_sc_stabilize(_BrushPage, SmoothStrokePanel, Panel):
    page = "sculpt_brushes"
    bl_parent_id = "PROPERTIES_PT_m3d_sc_stroke"


class PROPERTIES_PT_m3d_sc_texture(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Texture"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        brush = UnifiedPaintPanel.paint_settings(context).brush
        col = self.layout.column()
        col.template_ID_preview(brush.texture_slot, "texture", new="texture.new", rows=3, cols=8)
        brush_texture_settings(col, brush, context.sculpt_object)


class PROPERTIES_PT_m3d_sc_cursor(_BrushPage, DisplayPanel, Panel):
    page = "sculpt_brushes"
    bl_label = "Cursor"


class PROPERTIES_PT_m3d_sc_advanced(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Advanced"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        split_props(self.layout)
        settings = UnifiedPaintPanel.paint_settings(context)
        brush_settings_advanced(self.layout.column(), context, settings, settings.brush, self.is_popover)


# --- Geometry

class _Geometry(_Page):
    page = "sculpt_geometry"
    need = 'MESH'


class PROPERTIES_PT_m3d_sc_multires(_Geometry, Panel):
    bl_label = "Multires"

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mod = multires_of(ob)
        dyntopo = ob.use_dynamic_topology_sculpting
        if dyntopo:
            reason(layout, "Turn off Dyntopo to use Multires")
        col = layout.column()
        col.enabled = not dyntopo
        row = col.row(align=True)
        for label, mode in (("Subdivide", 'CATMULL_CLARK'), ("Simple", 'SIMPLE'), ("Linear", 'LINEAR')):
            row.operator("m3d.multires_subdivide", text=label).mode = mode
        if mod is None:
            col.label(text="The first Subdivide adds a Multires modifier")
            return
        split_props(col)
        col.label(text="Level %d of %d" % (mod.sculpt_levels, mod.total_levels))
        sub = col.column(align=True)
        sub.prop(mod, "levels", text="Viewport")
        sub.prop(mod, "sculpt_levels", text="Sculpt")
        sub.prop(mod, "render_levels", text="Render")
        col.separator()
        flow = col.grid_flow(columns=1, align=True)
        for action, label in (('DELETE_HIGHER', "Delete Higher"), ('UNSUBDIVIDE', "Unsubdivide"),
                              ('APPLY_BASE', "Apply Base")):
            flow.operator("m3d.multires_edit", text=label).action = action


class PROPERTIES_PT_m3d_sc_voxel(_Geometry, Panel):
    bl_label = "Voxel Remesh"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ob = mesh_of(context)
        mesh = ob.data
        if multires_of(ob) is not None:
            reason(layout, "Voxel Remesh does not work with Multires")
        elif ob.use_dynamic_topology_sculpting:
            reason(layout, "Turn off Dyntopo to use Voxel Remesh")
        col = layout.column()
        col.enabled = multires_of(ob) is None and not ob.use_dynamic_topology_sculpting
        row = col.row(align=True)
        row.prop(mesh, "remesh_voxel_size")
        _button(row, context, "", "sculpt.sample_detail_size", 'EYEDROPPER', {"mode": 'VOXEL'})
        col.prop(mesh, "remesh_voxel_adaptivity")
        col.prop(mesh, "use_remesh_fix_poles")
        sub = col.column(heading="Preserve", align=True)
        sub.prop(mesh, "use_remesh_preserve_volume", text="Volume")
        sub.prop(mesh, "use_remesh_preserve_attributes", text="Attributes")
        col.operator("object.voxel_remesh", text="Voxel Remesh", icon='MOD_REMESH')


class PROPERTIES_PT_m3d_sc_quadriflow(_Geometry, Panel):
    bl_label = "QuadriFlow"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ob = mesh_of(context)
        if multires_of(ob) is not None:
            reason(layout, "QuadriFlow does not work with Multires")
        elif ob.use_dynamic_topology_sculpting:
            reason(layout, "Turn off Dyntopo to use QuadriFlow")
        col = layout.column()
        col.enabled = multires_of(ob) is None and not ob.use_dynamic_topology_sculpting
        props = context.window_manager.operator_properties_last("object.quadriflow_remesh")
        col.prop(props, "mode")
        col.prop(props, {'RATIO': "target_ratio", 'EDGE': "target_edge_length", 'FACES': "target_faces"}[props.mode])
        col.prop(props, "use_mesh_symmetry")
        col.prop(props, "use_preserve_sharp")
        col.prop(props, "use_preserve_boundary")
        col.prop(props, "smooth_normals")
        col.label(text="Replaces the mesh (UVs and Face Sets are lost)", icon='INFO')
        col.operator_context = 'EXEC_DEFAULT'
        col.operator("object.quadriflow_remesh", text="QuadriFlow Remesh", icon='MOD_REMESH')


class PROPERTIES_PT_m3d_sc_dyntopo(_Geometry, Panel):
    bl_label = "Dyntopo"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ob = mesh_of(context)
        sculpt = context.tool_settings.sculpt
        if multires_of(ob) is not None:
            reason(layout, "Dyntopo does not work with Multires")
        elif context.mode != 'SCULPT':
            reason(layout, "Enter Sculpt Mode to use Dyntopo")
        on = ob.use_dynamic_topology_sculpting
        col = layout.column()
        col.enabled = multires_of(ob) is None and context.mode == 'SCULPT'
        _button(col, context, "Disable Dyntopo" if on else "Enable Dyntopo", "sculpt.dynamic_topology_toggle",
                'CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT', {}, depress=on)
        if not on:
            col.label(text="Turning it on removes UVs and Face Sets", icon='ERROR')
        sub = col.column()
        sub.active = on
        method = sculpt.detail_type_method
        if method in {'CONSTANT', 'MANUAL'}:
            row = sub.row(align=True)
            row.prop(sculpt, "constant_detail_resolution")
            _button(row, context, "", "sculpt.sample_detail_size", 'EYEDROPPER', {"mode": 'DYNTOPO'})
        elif method == 'BRUSH':
            sub.prop(sculpt, "detail_percent")
        else:
            sub.prop(sculpt, "detail_size")
        sub.prop(sculpt, "detail_refine_method", text="Refine Method")
        sub.prop(sculpt, "detail_type_method", text="Detailing")
        if method in {'CONSTANT', 'MANUAL'}:
            sub.operator("sculpt.detail_flood_fill")


# --- Mask

class _Mask(_Page):
    page = "sculpt_mask"


MASK_FILL = (
    ("Fill", "paint.mask_flood_fill", 'MOD_MASK', {"mode": 'VALUE', "value": 1.0}),
    ("Clear", "paint.mask_flood_fill", 'X', {"mode": 'VALUE', "value": 0.0}),
    ("Invert", "paint.mask_flood_fill", 'ARROW_LEFTRIGHT', {"mode": 'INVERT'}),
)
MASK_FILTERS = (
    ("Smooth", "sculpt.mask_filter", 'NONE', {"filter_type": 'SMOOTH'}),
    ("Sharpen", "sculpt.mask_filter", 'NONE', {"filter_type": 'SHARPEN'}),
    ("Grow", "sculpt.mask_filter", 'NONE', {"filter_type": 'GROW'}),
    ("Shrink", "sculpt.mask_filter", 'NONE', {"filter_type": 'SHRINK'}),
    ("Contrast +", "sculpt.mask_filter", 'NONE', {"filter_type": 'CONTRAST_INCREASE'}),
    ("Contrast -", "sculpt.mask_filter", 'NONE', {"filter_type": 'CONTRAST_DECREASE'}),
)
MASK_CREATE = (
    ("From Cavity", "sculpt.mask_from_cavity", 'NONE', {}),
    ("From Boundary", "sculpt.mask_from_boundary", 'NONE', {}),
)
MASK_TOOLS = (
    ("Box Mask", "builtin.box_mask", "", {}), ("Lasso Mask", "builtin.lasso_mask", "", {}),
    ("Line Mask", "builtin.line_mask", "", {}), ("Polyline Mask", "builtin.polyline_mask", "", {}),
    ("Mask by Color", "builtin.mask_by_color", "", {}),
)
HIDE_MASKED = (
    ("Hide Masked", "paint.hide_show_masked", 'HIDE_ON', {"action": 'HIDE'}),
    ("Show Masked", "paint.hide_show_masked", 'HIDE_OFF', {"action": 'SHOW'}),
    ("Show All", "paint.hide_show_all", 'RESTRICT_VIEW_OFF', {"action": 'SHOW'}),
)


class PROPERTIES_PT_m3d_sc_mask(_Mask, Panel):
    bl_label = "Mask"

    def draw(self, context):
        grid(self.layout, context, MASK_FILL, columns=3)
        self.layout.label(text="Expand: Shift+A over the mesh (Shift+W: face sets)")


class PROPERTIES_PT_m3d_sc_mask_filter(_Mask, Panel):
    bl_label = "Filter"

    def draw(self, context):
        grid(self.layout, context, MASK_FILTERS)


class PROPERTIES_PT_m3d_sc_mask_create(_Mask, Panel):
    bl_label = "Create Mask"

    def draw(self, context):
        grid(self.layout, context, MASK_CREATE)
        tools_grid(self.layout, context, MASK_TOOLS)


class PROPERTIES_PT_m3d_sc_mask_hide(_Mask, Panel):
    bl_label = "Hide"

    def draw(self, context):
        grid(self.layout, context, HIDE_MASKED, columns=3)


# --- Face Sets

class _FaceSets(_Page):
    page = "sculpt_face_sets"


FACE_SET_INIT = tuple((label, "sculpt.face_sets_init", 'NONE', {"mode": mode}) for label, mode in (
    ("Loose Parts", 'LOOSE_PARTS'), ("Materials", 'MATERIALS'), ("Normals", 'NORMALS'), ("UV Seams", 'UV_SEAMS'),
    ("Creases", 'CREASES'), ("Sharp Edges", 'SHARP_EDGES'), ("Bevel Weights", 'BEVEL_WEIGHT'),
    ("Face Set Boundaries", 'FACE_SET_BOUNDARIES')))
FACE_SET_CREATE = tuple((label, "sculpt.face_sets_create", 'NONE', {"mode": mode}) for label, mode in (
    ("From Mask", 'MASKED'), ("From Visible", 'VISIBLE'), ("From Selection", 'SELECTION')))
FACE_SET_EDIT = tuple((label, "builtin.face_set_edit", "sculpt.face_set_edit", {"mode": mode}) for label, mode in (
    ("Grow", 'GROW'), ("Shrink", 'SHRINK'), ("Fair Positions", 'FAIR_POSITIONS'), ("Fair Tangency", 'FAIR_TANGENCY'),
    ("Delete Geometry", 'DELETE_GEOMETRY')))
FACE_SET_VISIBILITY = (
    ("Show All", "paint.hide_show_all", 'RESTRICT_VIEW_OFF', {"action": 'SHOW'}),
    ("Randomize Colors", "sculpt.face_sets_randomize_colors", 'COLOR', {}),
)


class PROPERTIES_PT_m3d_sc_fs_init(_FaceSets, Panel):
    bl_label = "Initialize"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_INIT)


class PROPERTIES_PT_m3d_sc_fs_create(_FaceSets, Panel):
    bl_label = "Create"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_CREATE, columns=3)


class PROPERTIES_PT_m3d_sc_fs_edit(_FaceSets, Panel):
    bl_label = "Edit"

    def draw(self, context):
        tools_grid(self.layout, context, FACE_SET_EDIT)
        self.layout.label(text="Then click a face set in the viewport")


class PROPERTIES_PT_m3d_sc_fs_visibility(_FaceSets, Panel):
    bl_label = "Visibility"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_VISIBILITY)
        self.layout.label(text="Hide / show one set: H over it")


# --- Deform

class _Deform(_Page):
    page = "sculpt_deform"


MESH_FILTERS = tuple((label, "builtin.mesh_filter", "sculpt.mesh_filter", {"type": kind}) for label, kind in (
    ("Smooth", 'SMOOTH'), ("Inflate", 'INFLATE'), ("Relax", 'RELAX'), ("Surface Smooth", 'SURFACE_SMOOTH'),
    ("Sharpen", 'SHARPEN'), ("Enhance Details", 'ENHANCE_DETAILS'), ("Sphere", 'SPHERE'), ("Random", 'RANDOM'),
    ("Scale", 'SCALE')))
PIVOT_BUTTONS = tuple((label, "sculpt.set_pivot_position", 'PIVOT_CURSOR', {"mode": mode}) for label, mode in (
    ("Origin", 'ORIGIN'), ("Unmasked", 'UNMASKED'), ("Mask Border", 'BORDER')))
TRIM_TOOLS = (
    ("Box Trim", "builtin.box_trim", "", {}), ("Lasso Trim", "builtin.lasso_trim", "", {}),
    ("Line Trim", "builtin.line_trim", "", {}), ("Polyline Trim", "builtin.polyline_trim", "", {}),
    ("Line Project", "builtin.line_project", "", {}),
)


class PROPERTIES_PT_m3d_sc_filters(_Deform, Panel):
    bl_label = "Mesh Filters"

    def draw(self, context):
        layout = self.layout
        tools_grid(layout, context, MESH_FILTERS)
        if tool_is_active(context, "builtin.mesh_filter", "", {}):
            split_props(layout)
            props = active_tool(context).operator_properties("sculpt.mesh_filter")
            col = layout.column()
            col.prop(props, "strength")
            col.prop(props, "deform_axis")
        layout.label(text="Pick a filter, then drag in the viewport")


class PROPERTIES_PT_m3d_sc_symmetrize(_Deform, Panel):
    bl_label = "Symmetrize"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        layout.prop(context.tool_settings.sculpt, "symmetrize_direction", text="Direction")
        layout.prop(context.window_manager.operator_properties_last("sculpt.symmetrize"), "merge_tolerance")
        layout.operator("sculpt.symmetrize", icon='MOD_MIRROR')


class PROPERTIES_PT_m3d_sc_pivot(_Deform, Panel):
    bl_label = "Set Pivot"

    def draw(self, context):
        grid(self.layout, context, PIVOT_BUTTONS, columns=3)


class PROPERTIES_PT_m3d_sc_trim(_Deform, Panel):
    bl_label = "Trim"

    def draw(self, context):
        tools_grid(self.layout, context, TRIM_TOOLS)


# --- Paint

class _Paint(_Page):
    page = "sculpt_paint"


COLOR_FILTERS = tuple((label, "builtin.color_filter", "sculpt.color_filter", {"type": kind}) for label, kind in (
    ("Fill", 'FILL'), ("Hue", 'HUE'), ("Saturation", 'SATURATION'), ("Value", 'VALUE'), ("Brightness", 'BRIGHTNESS'),
    ("Contrast", 'CONTRAST'), ("Smooth", 'SMOOTH'), ("Red", 'RED'), ("Green", 'GREEN'), ("Blue", 'BLUE')))


class PROPERTIES_PT_m3d_sc_paint(_Paint, Panel):
    bl_label = "Color Brushes"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        mesh = mesh_of(context).data
        grid(layout, context, [(label, "brush.asset_activate", 'NONE', brush_props(name))
                               for label, name in PAINT_BRUSHES], columns=3,
             active=lambda idname, props: is_active(context, idname, props))
        if mesh.color_attributes.active_color is None:
            layout.label(text="This mesh has no color attribute", icon='ERROR')
            layout.operator_context = 'EXEC_DEFAULT'   # No options dialog: the defaults are what you want.
            _button(layout, context, "Add Color Attribute", "geometry.color_attribute_add", 'ADD',
                    {"name": "Color", "domain": 'POINT', "data_type": 'BYTE_COLOR', "color": (0.8, 0.8, 0.8, 1.0)})
        settings = UnifiedPaintPanel.paint_settings(context)
        brush = settings.brush if settings else None
        if brush is None or not brush.sculpt_capabilities.has_color:
            layout.label(text="Pick a color brush above")
        else:
            UnifiedPaintPanel.prop_unified_color_picker(layout, context, brush, "color")
            row = layout.row(align=True)
            UnifiedPaintPanel.prop_unified_color(row, context, brush, "color", text="")
            UnifiedPaintPanel.prop_unified_color(row, context, brush, "secondary_color", text="")
            row.operator("paint.brush_colors_flip", icon='FILE_REFRESH', text="")
            layout.prop(brush, "blend", text="Blend Mode")
        space = viewport(context)
        if space is not None:
            layout.prop(space.shading, "color_type", text="Viewport Color")


class PROPERTIES_PT_m3d_sc_palette(_BrushPage, ColorPalettePanel, Panel):
    page = "sculpt_paint"


class PROPERTIES_PT_m3d_sc_color_filter(_Paint, Panel):
    bl_label = "Color Filter"

    def draw(self, context):
        tools_grid(self.layout, context, COLOR_FILTERS)
        self.layout.label(text="Pick a filter, then drag in the viewport")


# --- Display

def draw_shading(layout, context):
    """Viewport look for sculpting: matcap / studio light, color, cavity (the Display tab and the matcap popover)."""
    space = viewport(context)
    if space is None:
        layout.label(text="No 3D Viewport in this workspace")
        return
    shading = space.shading
    layout.row().prop(shading, "type", expand=True)
    if shading.type != 'SOLID':
        reason(layout, "Lighting and cavity are for Solid shading")
        return
    split_props(layout)
    layout.row().prop(shading, "light", expand=True)
    if shading.light in {'STUDIO', 'MATCAP'}:
        layout.template_icon_view(shading, "studio_light", scale=3)
    layout.prop(shading, "color_type", text="Color")
    layout.prop(shading, "show_cavity")
    if shading.show_cavity:
        col = layout.column()
        col.prop(shading, "cavity_type", text="Type")
        col.prop(shading, "cavity_ridge_factor", text="Ridge")
        col.prop(shading, "cavity_valley_factor", text="Valley")


class _Display(_Page):
    page = "sculpt_display"
    need = None


class PROPERTIES_PT_m3d_sc_shading(_Display, Panel):
    bl_label = "Shading"

    def draw(self, context):
        draw_shading(self.layout, context)


class PROPERTIES_PT_m3d_sc_overlays(_Display, Panel):
    bl_label = "Overlays"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        space = viewport(context)
        if space is None:
            return
        overlay = space.overlay
        for flag, opacity, label in (("show_sculpt_mask", "sculpt_mode_mask_opacity", "Mask"),
                                     ("show_sculpt_face_sets", "sculpt_mode_face_sets_opacity", "Face Sets")):
            row = layout.row(align=True)
            row.prop(overlay, flag, text=label, toggle=True)
            sub = row.row(align=True)
            sub.active = getattr(overlay, flag)
            sub.prop(overlay, opacity, text="Opacity")
        row = layout.row(align=True)
        row.prop(overlay, "show_wireframes", text="Wireframe", toggle=True)
        sub = row.row(align=True)
        sub.active = overlay.show_wireframes
        sub.prop(overlay, "wireframe_opacity", text="Opacity")


class PROPERTIES_PT_m3d_sc_performance(_Display, Panel):
    bl_label = "Performance"

    @classmethod
    def page_poll(cls, context):
        return context.tool_settings.sculpt is not None

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        sculpt = context.tool_settings.sculpt
        col = layout.column(heading="Display", align=True)
        col.prop(sculpt, "show_low_resolution", text="Low Resolution While Navigating")
        col.prop(sculpt, "use_sculpt_delay_updates", text="Delay Updates While Stroking")
        col.prop(sculpt, "use_deform_only", text="Deform Only (no topology update)")


# --- Objects: the scene's meshes

class PROPERTIES_PT_m3d_sc_objects(_Page, Panel):
    page = "sculpt_objects"
    bl_label = "Meshes"
    need = None

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        for label, kind in (("Sphere", 'SPHERE'), ("Cube", 'CUBE'), ("Cylinder", 'CYLINDER')):
            row.operator("m3d.sculpt_add_mesh", text=label, icon='ADD').kind = kind
        meshes = [o for o in context.view_layer.objects if o.type == 'MESH']
        if not meshes:
            layout.label(text="No meshes in the scene")
        col = layout.column(align=True)
        for ob in meshes:
            hidden = ob.hide_get()
            others = [o for o in meshes if o is not ob]
            solo = bool(others) and all(o.hide_get() for o in others) and not hidden
            row = col.row(align=True)
            o = row.operator("m3d.sculpt_object", text="", icon='HIDE_ON' if hidden else 'HIDE_OFF')
            o.name, o.action = ob.name, 'VISIBLE'
            sub = row.row(align=True)
            o = sub.operator("m3d.sculpt_object", text="%s  (%s faces)" % (ob.name, format(len(ob.data.polygons), ",")),
                             depress=ob is context.active_object)
            o.name, o.action = ob.name, 'SELECT'
            sub.active = not hidden
            o = row.operator("m3d.sculpt_object", text="", icon='SOLO_ON' if solo else 'SOLO_OFF', depress=solo)
            o.name, o.action = ob.name, 'SOLO'
            o = row.operator("m3d.sculpt_object", text="", icon='DUPLICATE')
            o.name, o.action = ob.name, 'DUPLICATE'


GATES = {"sculpt_brushes": 'SCULPT', "sculpt_geometry": 'MESH', "sculpt_mask": 'SCULPT', "sculpt_face_sets": 'SCULPT',
         "sculpt_deform": 'SCULPT', "sculpt_paint": 'SCULPT'}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page[len("sculpt_"):], need) for page, need in GATES.items())


# -----------------------------------------------------------------------------
# Status Line and popovers

class M3D_PT_sculpt_automasking(Panel):
    """Auto-Masking: limit strokes to the part of the mesh under the cursor"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Auto-Masking"
    bl_ui_units_x = 13

    @classmethod
    def poll(cls, context):
        sculpt = context.tool_settings.sculpt
        return sculpt is not None and sculpt.brush is not None

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        am = context.tool_settings.sculpt.brush.mesh_automasking_settings
        col = layout.column(align=True)
        col.prop(am, "use_automasking_topology", text="Topology")
        col.prop(am, "use_automasking_face_sets", text="Face Sets")
        col.prop(am, "use_automasking_boundary_edges", text="Mesh Boundary")
        col.prop(am, "use_automasking_boundary_face_sets", text="Face Sets Boundary")
        if am.use_automasking_boundary_edges or am.use_automasking_boundary_face_sets:
            col.prop(am, "boundary_edges_propagation_steps", text="Steps")
        col = layout.column(align=True)
        col.prop(am, "use_automasking_cavity", text="Cavity")
        col.prop(am, "use_automasking_cavity_inverted", text="Cavity (inverted)")
        if am.use_automasking_cavity or am.use_automasking_cavity_inverted:
            col.prop(am, "cavity_factor", text="Factor")
            col.prop(am, "cavity_blur_steps", text="Blur")
        col = layout.column(align=True)
        col.prop(am, "use_automasking_view_normal", text="View Normal")
        if am.use_automasking_view_normal:
            col.prop(am, "use_automasking_view_occlusion", text="Occlusion")
            if not am.use_automasking_view_occlusion:
                col.prop(am, "view_normal_limit", text="Limit")
                col.prop(am, "view_normal_falloff", text="Falloff")
        col.prop(am, "use_automasking_start_normal", text="Area Normal")
        if am.use_automasking_start_normal:
            col.prop(am, "start_normal_limit", text="Limit")
            col.prop(am, "start_normal_falloff", text="Falloff")


class M3D_PT_sculpt_shading(Panel):
    """Matcap, studio light and cavity of the viewport"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Matcap"
    bl_ui_units_x = 13

    def draw(self, context):
        draw_shading(self.layout, context)


def draw_status_line(layout, context):
    """Sculpt Status Line: file, modes, face count and Multires level, Dyntopo, symmetry, Auto-Masking,
    Mask / Face Set overlays, matcap."""
    from m3d_ui import _call, draw_file_buttons, draw_workspace_picker
    draw_file_buttons(layout)
    row = layout.row(align=True)
    _call(row, "object.mode_set", 'OBJECT_DATAMODE', "Object Mode", depress=context.mode == 'OBJECT', mode='OBJECT')
    _call(row, "object.mode_set", 'SCULPTMODE_HLT', "Sculpt Mode", depress=context.mode == 'SCULPT', mode='SCULPT')
    ob = mesh_of(context)
    if ob is None:
        draw_workspace_picker(layout, context)
        return
    mesh, mod = ob.data, multires_of(ob)
    dyntopo = ob.use_dynamic_topology_sculpting
    # The mesh data is not updated while Dyntopo changes it, so no count then.
    layout.label(text="Dyntopo" if dyntopo else "%s faces" % format(len(mesh.polygons), ","))
    if mod is not None:
        layout.label(text="Lv %d/%d" % (mod.sculpt_levels, mod.total_levels))
    if context.mode == 'SCULPT':
        row = layout.row(align=True)
        row.enabled = mod is None
        _call(row, "sculpt.dynamic_topology_toggle", 'CHECKBOX_HLT' if dyntopo else 'CHECKBOX_DEHLT',
              "Dyntopo (needs no Multires modifier)" if mod is None else "Dyntopo is off while the mesh has Multires",
              depress=dyntopo)
    row = layout.row(align=True)
    for axis in "xyz":
        row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)
    if context.mode == 'SCULPT':
        layout.popover("M3D_PT_sculpt_automasking", text="Auto-Masking")
    space = viewport(context)
    if space is not None:
        row = layout.row(align=True)
        row.prop(space.overlay, "show_sculpt_mask", text="", icon='MOD_MASK')
        row.prop(space.overlay, "show_sculpt_face_sets", text="", icon='FACE_MAPS')
        layout.popover("M3D_PT_sculpt_shading", text="", icon='MATSPHERE')
    draw_workspace_picker(layout, context)


# -----------------------------------------------------------------------------
# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

def _voxel_size(row, context):
    ob = mesh_of(context)
    if ob is not None:
        sub = row.row()
        sub.scale_x = 2.0
        sub.prop(ob.data, "remesh_voxel_size", text="")


SHELF_BRUSHES = [
    ("object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'}),
    None,
    *(brush_item(label, name) for label, name in BRUSHES),
]
SHELF_REMESH = [
    ("object.voxel_remesh", 'MOD_REMESH', {}),
    _voxel_size,
    None,
    ("object.quadriflow_remesh", 'MESH_GRID', {}),
    None,
    ("m3d.multires_subdivide", 'ADD', {"mode": 'CATMULL_CLARK'}),
    ("m3d.multires_level", 'TRIA_RIGHT', {"delta": 1}),
    ("m3d.multires_level", 'TRIA_LEFT', {"delta": -1}),
    ("m3d.multires_edit", 'FREEZE', {"action": 'APPLY_BASE'}),
]
SHELF_MASK = [
    ("paint.mask_flood_fill", 'MOD_MASK', {"mode": 'VALUE', "value": 1.0}),
    ("paint.mask_flood_fill", 'X', {"mode": 'VALUE', "value": 0.0}),
    ("paint.mask_flood_fill", 'ARROW_LEFTRIGHT', {"mode": 'INVERT'}),
    None,
    ("sculpt.mask_filter", 'ADD', {"filter_type": 'GROW'}),
    ("sculpt.mask_filter", 'REMOVE', {"filter_type": 'SHRINK'}),
    ("sculpt.mask_filter", 'SHARPCURVE', {"filter_type": 'SHARPEN'}),
    None,
    ("sculpt.mask_from_cavity", 'MOD_WIREFRAME', {}),
    ("paint.hide_show_masked", 'HIDE_ON', {"action": 'HIDE'}),
]


classes = (
    M3D_OT_sculpt_tool,
    M3D_OT_multires_subdivide,
    M3D_OT_multires_level,
    M3D_OT_multires_edit,
    M3D_OT_sculpt_object,
    M3D_OT_sculpt_add_mesh,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_sc_brush,
    PROPERTIES_PT_m3d_sc_grid,
    PROPERTIES_PT_m3d_sc_tuning,
    PROPERTIES_PT_m3d_sc_more,
    PROPERTIES_PT_m3d_sc_falloff,
    PROPERTIES_PT_m3d_sc_stroke,
    PROPERTIES_PT_m3d_sc_stabilize,
    PROPERTIES_PT_m3d_sc_texture,
    PROPERTIES_PT_m3d_sc_cursor,
    PROPERTIES_PT_m3d_sc_advanced,
    PROPERTIES_PT_m3d_sc_multires,
    PROPERTIES_PT_m3d_sc_voxel,
    PROPERTIES_PT_m3d_sc_quadriflow,
    PROPERTIES_PT_m3d_sc_dyntopo,
    PROPERTIES_PT_m3d_sc_mask,
    PROPERTIES_PT_m3d_sc_mask_filter,
    PROPERTIES_PT_m3d_sc_mask_create,
    PROPERTIES_PT_m3d_sc_mask_hide,
    PROPERTIES_PT_m3d_sc_fs_init,
    PROPERTIES_PT_m3d_sc_fs_create,
    PROPERTIES_PT_m3d_sc_fs_edit,
    PROPERTIES_PT_m3d_sc_fs_visibility,
    PROPERTIES_PT_m3d_sc_filters,
    PROPERTIES_PT_m3d_sc_symmetrize,
    PROPERTIES_PT_m3d_sc_pivot,
    PROPERTIES_PT_m3d_sc_trim,
    PROPERTIES_PT_m3d_sc_paint,
    PROPERTIES_PT_m3d_sc_palette,
    PROPERTIES_PT_m3d_sc_color_filter,
    PROPERTIES_PT_m3d_sc_shading,
    PROPERTIES_PT_m3d_sc_overlays,
    PROPERTIES_PT_m3d_sc_performance,
    PROPERTIES_PT_m3d_sc_objects,
    M3D_PT_sculpt_automasking,
    M3D_PT_sculpt_shading,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
