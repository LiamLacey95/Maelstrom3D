# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
classic-style interface for Maelstrom3D:
main menu bar with menu sets, status line, shelf tabs and viewport panel menus.

Menus are plain data (see `MENUS`) so `tools/m3d/test_m3d.py` can verify every command exists.
"""

import bpy
from bpy.types import Menu, Panel

import m3d_anim
import m3d_render
import m3d_retopo
import m3d_rig
import m3d_sculpt
import m3d_texture
import m3d_uv
from m3d_uv import UVTK_CREATE, UVTK_CUT_SEW, UVTK_PIN, UVTK_SELECT, UVTK_UNFOLD
from m3d_workspace import KINDS, current_kind


# -----------------------------------------------------------------------------
# Menu entry helpers

def op(label, idname, icon='NONE', modes=None, **props):
    return {"kind": 'OP', "label": label, "idname": idname, "icon": icon, "modes": modes, "props": props}


def sub(label, menu, icon='NONE', modes=None):
    return {"kind": 'MENU', "label": label, "idname": menu, "icon": icon, "modes": modes}


def prop(label, path, modes=None):
    """Toggle a property given as a context path, e.g. `space_data.overlay.show_floor`."""
    return {"kind": 'PROP', "label": label, "path": path, "modes": modes}


def stock(idname):
    """Contents of one of Blender's menus drawn in place (a menu bar menu that is Blender's own)."""
    return {"kind": 'STOCK', "label": idname, "idname": idname, "modes": None}


def ops(items):
    """(label, idname, icon, props) tuples as menu entries."""
    return [op(label, idname, icon, **props) for label, idname, icon, props in items]


def enum(label, idname, prop_name, icon='NONE', modes=None):
    return {"kind": 'ENUM', "label": label, "idname": idname, "prop": prop_name, "icon": icon, "modes": modes}


def modifier(label, type, icon='MODIFIER'):
    return op(label, "object.modifier_add", icon, type=type)


def constraint(label, type, icon='CONSTRAINT'):
    return op(label, "object.constraint_add_with_targets", icon, type=type)


def editor(label, ui_type, icon='NONE'):
    return op(label, "m3d.open_editor", icon, ui_type=ui_type)


def shading(label, type, icon='NONE'):
    return op(label, "wm.context_set_enum", icon, data_path="space_data.shading.type", value=type)


SEP = {"kind": 'SEP', "modes": None}
EDIT = {'EDIT_MESH'}
OBJECT = {'OBJECT'}
EDIT_ARM = {'EDIT_ARMATURE'}
POSE = {'POSE'}

# Operators that need a 3D Viewport context: from the top bar they run through `m3d.call`.
_VIEW3D_PREFIXES = (
    "view3d.", "transform.", "wm.context_", "wm.tool_set_by_id", "screen.region_quadview",
    "mesh.loopcut_slide", "mesh.knife_tool", "mesh.bevel", "mesh.offset_edge_loops_slide",
    "mesh.duplicate_move", "object.duplicate_move", "uv.project_from_view", "mesh.dupli_extrude_cursor",
    "armature.", "pose.", "paint.weight",
)


def needs_view3d(idname):
    return idname.startswith(_VIEW3D_PREFIXES)


# Operators that need the UV Editor: drawn anywhere else they run there through `m3d.call` (when the screen has one).
_UV_EDITOR_PREFIXES = ("uv.", "m3d.uv_", "image.tile_", "image.new")


def is_uv_editor(area):
    """An Image Editor in UV mode (the Texture workspace's one is in Paint mode and is not a target for UV tools)."""
    return area.type == 'IMAGE_EDITOR' and area.spaces.active.mode == 'UV'


def call_target(context, idname):
    """The editor ('VIEW_3D' or 'IMAGE_EDITOR') an operator drawn here has to run in through `m3d.call`, or None
    when it can run in place."""
    area = context.area.type if context.area is not None else None
    has_uv_editor = context.screen is not None and any(is_uv_editor(a) for a in context.screen.areas)
    if idname.startswith(_UV_EDITOR_PREFIXES) and not needs_view3d(idname) and has_uv_editor:
        return None if area == 'IMAGE_EDITOR' else 'IMAGE_EDITOR'
    return 'VIEW_3D' if area != 'VIEW_3D' and (needs_view3d(idname) or not _poll(idname)) else None


def _resolve(context, path):
    owner_path, _, attr = path.rpartition(".")
    owner = context
    for part in owner_path.split("."):
        owner = getattr(owner, part, None)
        if owner is None:
            return None, attr
    return owner, attr


def _poll(idname):
    mod, name = idname.split(".")
    return getattr(getattr(bpy.ops, mod), name).poll()


def draw_entries(layout, context, entries):
    in_view3d = context.area is not None and context.area.type == 'VIEW_3D'
    for e in entries:
        if e["modes"] and context.mode not in e["modes"]:
            continue
        kind = e["kind"]
        if kind == 'SEP':
            layout.separator()
        elif kind == 'MENU':
            layout.menu(e["idname"], text=e["label"], icon=e["icon"])
        elif kind == 'STOCK':
            layout.menu_contents(e["idname"])
        elif kind == 'ENUM':
            layout.operator_menu_enum(e["idname"], e["prop"], text=e["label"], icon=e["icon"])
        elif kind == 'PROP':
            owner, attr = _resolve(context, e["path"])
            if owner is not None:
                layout.prop(owner, attr, text=e["label"])
            elif not in_view3d:
                o = layout.operator("m3d.call", text=e["label"])
                o.idname, o.props = "wm.context_toggle", repr({"data_path": e["path"]})
        else:
            target = call_target(context, e["idname"])
            if target:
                o = layout.operator("m3d.call", text=e["label"], icon=e["icon"])
                o.idname, o.props, o.label, o.editor = e["idname"], repr(e["props"]), e["label"], target
            else:
                o = layout.operator(e["idname"], text=e["label"], icon=e["icon"])
                for k, v in e["props"].items():
                    setattr(o, k, v)


# -----------------------------------------------------------------------------
# Main menu bar (always visible) and menu sets

POLY_PRIMITIVES = [
    op("Sphere", "m3d.add_primitive", 'MESH_UVSPHERE', kind='SPHERE'),
    op("Cube", "m3d.add_primitive", 'MESH_CUBE', kind='CUBE'),
    op("Cylinder", "m3d.add_primitive", 'MESH_CYLINDER', kind='CYLINDER'),
    op("Cone", "m3d.add_primitive", 'MESH_CONE', kind='CONE'),
    op("Torus", "m3d.add_primitive", 'MESH_TORUS', kind='TORUS'),
    op("Plane", "m3d.add_primitive", 'MESH_PLANE', kind='PLANE'),
    SEP,
    sub("More Primitives", "VIEW3D_MT_mesh_add", 'ADD'),
]

MENUS = {
    # Common menus.
    "M3D_MT_file": ("File", [
        op("New Scene", "wm.read_homefile", 'FILE_NEW', app_template=""),
        op("Open Scene...", "wm.open_mainfile", 'FILE_FOLDER'),
        sub("Recent Files", "TOPBAR_MT_file_open_recent"),
        SEP,
        op("Save Scene", "wm.save_mainfile", 'FILE_TICK'),
        op("Save Scene As...", "wm.save_as_mainfile"),
        op("Increment and Save", "wm.save_mainfile", incremental=True),
        SEP,
        op("Import...", "wm.append", 'IMPORT'),
        op("Create Reference...", "wm.link", 'LINK_BLEND'),
        sub("Import Other Formats", "TOPBAR_MT_file_import"),
        sub("Export", "TOPBAR_MT_file_export", 'EXPORT'),
        SEP,
        sub("External Data", "TOPBAR_MT_file_external_data"),
        sub("Clean Up", "TOPBAR_MT_file_cleanup"),
        SEP,
        op("Exit", "wm.quit_blender", 'QUIT'),
    ]),
    "M3D_MT_edit": ("Edit", [
        op("Undo", "ed.undo", 'LOOP_BACK'),
        op("Redo", "ed.redo", 'LOOP_FORWARDS'),
        op("Repeat", "screen.repeat_last"),
        op("Undo History", "ed.undo_history"),
        SEP,
        op("Copy", "view3d.copybuffer", modes=OBJECT),
        op("Paste", "view3d.pastebuffer", modes=OBJECT),
        SEP,
        op("Delete", "object.delete", 'X', modes=OBJECT),
        op("Delete All History", "m3d.delete_history", modes=OBJECT, modifiers=True),
        op("Duplicate", "m3d.duplicate", 'DUPLICATE', modes=OBJECT),
        op("Duplicate with Transform", "m3d.duplicate", modes=OBJECT, with_transform=True),
        op("Duplicate Special (Instance)", "object.duplicate_move_linked", modes=OBJECT),
        op("Duplicate", "mesh.duplicate_move", 'DUPLICATE', modes=EDIT),
        SEP,
        op("Group", "m3d.group", 'EMPTY_AXIS', modes=OBJECT),
        op("Ungroup", "m3d.ungroup", modes=OBJECT),
        op("Parent", "object.parent_set", modes=OBJECT),
        op("Unparent", "object.parent_clear", modes=OBJECT, type='CLEAR_KEEP_TRANSFORM'),
        SEP,
        op("Search Command...", "wm.search_menu", 'VIEWZOOM'),
    ]),
    "M3D_MT_create": ("Create", [
        sub("Polygon Primitives", "M3D_MT_poly_primitives", 'MESH_CUBE'),
        sub("NURBS Primitives", "VIEW3D_MT_surface_add", 'SURFACE_NSURFACE'),
        sub("Curve Tools", "VIEW3D_MT_curve_add", 'CURVE_BEZCURVE'),
        SEP,
        sub("Lights", "VIEW3D_MT_light_add", 'LIGHT'),
        op("Camera", "object.camera_add", 'CAMERA_DATA'),
        SEP,
        op("Type", "object.text_add", 'OUTLINER_OB_FONT'),
        sub("Image Plane", "VIEW3D_MT_image_add", 'IMAGE_DATA'),
        op("Locator", "object.empty_add", 'EMPTY_AXIS', type='PLAIN_AXES'),
        op("Empty Group", "object.empty_add", 'OUTLINER_OB_EMPTY', type='PLAIN_AXES'),
        SEP,
        op("Measure Tool", "wm.tool_set_by_id", 'DRIVER_DISTANCE', name="builtin.measure"),
        sub("Sets (Collections)", "OBJECT_MT_move_to_collection", 'OUTLINER_COLLECTION', modes=OBJECT),
        SEP,
        sub("Everything", "VIEW3D_MT_add", 'ADD'),
    ]),
    "M3D_MT_select": ("Select", [
        op("Object/Component", "object.editmode_toggle"),
        SEP,
        op("All", "object.select_all", modes=OBJECT, action='SELECT'),
        op("Deselect All", "object.select_all", modes=OBJECT, action='DESELECT'),
        op("Hierarchy", "object.select_grouped", modes=OBJECT, type='CHILDREN_RECURSIVE', extend=True),
        op("Inverse", "object.select_all", modes=OBJECT, action='INVERT'),
        enum("Similar", "object.select_grouped", "type", modes=OBJECT),
        enum("All by Type", "object.select_by_type", "type", modes=OBJECT),
        enum("Linked", "object.select_linked", "type", modes=OBJECT),
        op("All", "mesh.select_all", modes=EDIT, action='SELECT'),
        op("Deselect All", "mesh.select_all", modes=EDIT, action='DESELECT'),
        op("Inverse", "mesh.select_all", modes=EDIT, action='INVERT'),
        op("Grow", "mesh.select_more", modes=EDIT),
        op("Shrink", "mesh.select_less", modes=EDIT),
        op("Select Edge Loop", "mesh.select_edge_loop_multi", modes=EDIT),
        op("Select Edge Ring", "mesh.select_edge_ring_multi", modes=EDIT),
        op("Select Border Edge Loop", "mesh.region_to_loop", modes=EDIT),
        op("Select Shortest Edge Path", "mesh.shortest_path_select", modes=EDIT),
        enum("Similar", "mesh.select_similar", "type", modes=EDIT),
        op("Select Non-Manifold", "mesh.select_non_manifold", modes=EDIT),
        op("Select Random", "mesh.select_random", modes=EDIT),
        sub("Convert Selection", "M3D_MT_convert_selection", modes=EDIT),
        SEP,
        op("Select Tool", "wm.tool_set_by_id", 'RESTRICT_SELECT_OFF', name="builtin.select_box"),
        op("Lasso Tool", "wm.tool_set_by_id", name="builtin.select_lasso"),
        op("Paint Selection Tool", "wm.tool_set_by_id", name="builtin.select_circle"),
        SEP,
        sub("More", "VIEW3D_MT_select_object", modes=OBJECT),
        sub("More", "VIEW3D_MT_select_edit_mesh", modes=EDIT),
    ]),
    "M3D_MT_modify": ("Modify", [
        sub("Transformation Tools", "M3D_MT_transform_tools"),
        op("Reset Transformations", "m3d.reset_transformations", modes=OBJECT),
        op("Freeze Transformations", "object.transform_apply", 'FREEZE', modes=OBJECT,
           location=True, rotation=True, scale=True),
        op("Center Pivot", "object.origin_set", 'PIVOT_BOUNDBOX', modes=OBJECT, type='ORIGIN_GEOMETRY'),
        op("Reset Pivot", "wm.context_set_enum", 'PIVOT_MEDIAN',
           data_path="tool_settings.transform_pivot_point", value='MEDIAN_POINT'),
        sub("Snap Align", "VIEW3D_MT_snap", 'SNAP_ON'),
        SEP,
        enum("Convert", "object.convert", "target", modes=OBJECT),
        op("Search and Replace Names...", "wm.batch_rename", 'SORTALPHA'),
        SEP,
        sub("More", "VIEW3D_MT_object", modes=OBJECT),
        sub("More", "VIEW3D_MT_edit_mesh", modes=EDIT),
    ]),
    "M3D_MT_display": ("Display", [
        prop("Grid", "space_data.overlay.show_floor"),
        sub("Heads Up Display", "M3D_MT_hud"),
        sub("UI Elements", "M3D_MT_ui_elements"),
        SEP,
        op("Hide Selection", "object.hide_view_set", modes=OBJECT, unselected=False),
        op("Hide Unselected", "object.hide_view_set", modes=OBJECT, unselected=True),
        op("Show All", "object.hide_view_clear", modes=OBJECT),
        op("Hide Selection", "mesh.hide", modes=EDIT, unselected=False),
        op("Show All", "mesh.reveal", modes=EDIT),
        SEP,
        op("Frame All", "view3d.view_all", 'VIEW_ZOOM', center=False),
        op("Frame Selection", "view3d.view_selected", 'ZOOM_SELECTED'),
        SEP,
        prop("Backface Culling", "space_data.shading.show_backface_culling"),
        prop("Wireframe on Shaded", "space_data.overlay.show_wireframes"),
        prop("X-Ray", "space_data.shading.show_xray"),
    ]),
    "M3D_MT_windows": ("Windows", [
        sub("Workspaces", "M3D_MT_workspaces", 'WORKSPACE'),
        sub("General Editors", "M3D_MT_general_editors", 'WINDOW'),
        sub("Settings/Preferences", "M3D_MT_preferences", 'PREFERENCES'),
        SEP,
        editor("Outliner", 'OUTLINER', 'OUTLINER'),
        op("Attribute Editor", "m3d.dock_tab", 'PROPERTIES', tab='OBJECT'),
        op("Channel Box / Layer Editor", "m3d.dock_tab", 'ALIGN_JUSTIFY', tab='CHANNEL_BOX'),
        op("Modeling Toolkit", "m3d.dock_tab", 'EDITMODE_HLT', tab='MODELING_TOOLKIT'),
        op("Tool Settings", "m3d.dock_tab", 'TOOL_SETTINGS', tab='TOOL'),
        editor("Shader Editor", 'ShaderNodeTree', 'NODE_MATERIAL'),
        editor("Graph Editor", 'FCURVES', 'GRAPH'),
        editor("Dope Sheet", 'DOPESHEET', 'ACTION'),
        editor("UV Editor", 'UV', 'UV'),
        editor("Script Editor", 'TEXT_EDITOR', 'TEXT'),
        SEP,
        op("Command Line: MEL", "m3d.command_language", 'CONSOLE', language='mel'),
        op("Command Line: Python", "m3d.command_language", 'CONSOLE', language='python'),
        op("Toggle Full Screen", "wm.window_fullscreen_toggle", 'FULLSCREEN_ENTER'),
    ]),
    "M3D_MT_help": ("Help", [
        sub("Help", "TOPBAR_MT_help", 'HELP'),
        op("Hotkey Editor", "screen.userpref_show", 'KEYINGSET', section='KEYMAP'),
    ]),

    # Modeling menu set.
    "M3D_MT_mesh": ("Mesh", [
        sub("Booleans", "M3D_MT_booleans", 'MOD_BOOLEAN'),
        op("Combine", "object.join", 'AUTOMERGE_ON', modes=OBJECT),
        op("Separate", "m3d.separate", modes=OBJECT),
        SEP,
        modifier("Mirror", 'MIRROR', 'MOD_MIRROR'),
        op("Smooth", "object.subdivision_set", 'MOD_SUBSURF', level=1, relative=False),
        modifier("Reduce", 'DECIMATE', 'MOD_DECIM'),
        modifier("Remesh", 'REMESH', 'MOD_REMESH'),
        modifier("Triangulate", 'TRIANGULATE', 'MOD_TRIANGULATE'),
        op("Quadrangulate", "mesh.tris_convert_to_quads", modes=EDIT),
        SEP,
        op("Fill Hole", "m3d.fill_hole"),
        op("Cleanup (Merge by Distance)", "mesh.remove_doubles", modes=EDIT),
    ]),
    "M3D_MT_edit_mesh": ("Edit Mesh", [
        op("Add Divisions", "mesh.subdivide"),
        op("Bevel", "mesh.bevel", 'MOD_BEVEL', offset_type='PERCENT'),
        op("Bridge", "mesh.bridge_edge_loops"),
        op("Collapse", "mesh.merge", type='COLLAPSE'),
        op("Connect", "m3d.connect"),
        op("Detach", "mesh.split"),
        op("Extrude", "view3d.edit_mesh_extrude_move_normal", 'FACESEL'),
        op("Merge", "mesh.remove_doubles", 'AUTOMERGE_ON', threshold=0.001),
        op("Merge to Center", "mesh.merge", type='CENTER'),
        op("Symmetrize", "mesh.symmetrize"),
        op("Average Vertices", "mesh.vertices_smooth"),
        op("Chamfer Vertices", "mesh.bevel", affect='VERTICES'),
        SEP,
        op("Delete Edge/Vertex", "mesh.dissolve_mode"),
        op("Flip Triangle Edge", "mesh.edge_rotate"),
        op("Poke", "mesh.poke"),
        op("Duplicate", "mesh.duplicate_move", 'DUPLICATE'),
        op("Extract", "mesh.separate", type='SELECTED'),
        op("Spin", "mesh.spin"),
        SEP,
        sub("Vertex", "VIEW3D_MT_edit_mesh_vertices", 'VERTEXSEL'),
        sub("Edge", "VIEW3D_MT_edit_mesh_edges", 'EDGESEL'),
        sub("Face", "VIEW3D_MT_edit_mesh_faces", 'FACESEL'),
    ]),
    "M3D_MT_mesh_tools": ("Mesh Tools", [
        op("Create Polygon", "mesh.edge_face_add"),
        op("Crease Tool", "transform.edge_crease"),
        op("Insert Edge Loop", "mesh.loopcut_slide", 'MOD_EDGESPLIT'),
        op("Multi-Cut", "mesh.knife_tool"),
        op("Offset Edge Loop", "mesh.offset_edge_loops_slide"),
        op("Quad Draw", "wm.tool_set_by_id", name="builtin.poly_build"),
        op("Slide Edge", "transform.edge_slide"),
        op("Target Weld", "m3d.target_weld"),
    ]),
    "M3D_MT_mesh_display": ("Mesh Display", [
        op("Reverse", "mesh.flip_normals", modes=EDIT),
        op("Conform", "mesh.normals_make_consistent", modes=EDIT),
        op("Set to Face", "mesh.set_normals_from_faces", modes=EDIT),
        op("Soften Edge", "mesh.mark_sharp", modes=EDIT, clear=True),
        op("Harden Edge", "mesh.mark_sharp", modes=EDIT),
        op("Soften/Harden by Angle", "object.shade_smooth_by_angle", modes=OBJECT),
        op("Smooth Shading", "object.shade_smooth", modes=OBJECT),
        op("Flat Shading", "object.shade_flat", modes=OBJECT),
        SEP,
        prop("Face Normals", "space_data.overlay.show_face_normals"),
        prop("Vertex Normals", "space_data.overlay.show_vertex_normals"),
        prop("Backface Culling", "space_data.shading.show_backface_culling"),
    ]),
    "M3D_MT_curves": ("Curves", [
        sub("Create Curve", "VIEW3D_MT_curve_add", 'CURVE_BEZCURVE'),
        op("Open/Close", "curve.cyclic_toggle", modes={'EDIT_CURVE'}),
        op("Reverse Direction", "curve.switch_direction", modes={'EDIT_CURVE'}),
        op("Smooth", "curve.smooth", modes={'EDIT_CURVE'}),
        op("Subdivide", "curve.subdivide", modes={'EDIT_CURVE'}),
        op("Draw Curve", "wm.tool_set_by_id", modes={'EDIT_CURVE'}, name="builtin.draw"),
    ]),
    "M3D_MT_surfaces": ("Surfaces", [
        sub("NURBS Primitives", "VIEW3D_MT_surface_add", 'SURFACE_NSURFACE'),
        modifier("Revolve", 'SCREW', 'MOD_SCREW'),
        modifier("Extrude (Solidify)", 'SOLIDIFY', 'MOD_SOLIDIFY'),
    ]),
    "M3D_MT_deform": ("Deform", [
        op("Blend Shape", "object.shape_key_add", 'SHAPEKEY_DATA', from_mix=False),
        modifier("Lattice", 'LATTICE', 'MOD_LATTICE'),
        modifier("Wrap", 'SURFACE_DEFORM', 'MOD_MESHDEFORM'),
        modifier("Shrink Wrap", 'SHRINKWRAP', 'MOD_SHRINKWRAP'),
        modifier("Delta Mush", 'CORRECTIVE_SMOOTH', 'MOD_SMOOTH'),
        modifier("Curve Warp", 'CURVE', 'MOD_CURVE'),
        modifier("Nonlinear (Bend/Twist/Taper)", 'SIMPLE_DEFORM', 'MOD_SIMPLEDEFORM'),
        modifier("Texture Deformer", 'DISPLACE', 'MOD_DISPLACE'),
        modifier("Wave", 'WAVE', 'MOD_WAVE'),
        modifier("Cluster (Hook)", 'HOOK', 'HOOK'),
        prop("Soft Selection", "tool_settings.use_proportional_edit_objects", modes=OBJECT),
        prop("Soft Selection", "tool_settings.use_proportional_edit", modes=EDIT),
    ]),
    "M3D_MT_uv": ("UV", [
        editor("UV Editor", 'UV', 'UV'),
        op("UV Workspace", "m3d.workspace", 'WORKSPACE', kind='UV'),
        op("Checker Map", "m3d.uv_checker", 'TEXTURE'),
        SEP,
        op("Automatic", "uv.smart_project", modes=EDIT),
        op("Planar", "uv.project_from_view", modes=EDIT),
        op("Cylindrical", "uv.cylinder_project", modes=EDIT),
        op("Spherical", "uv.sphere_project", modes=EDIT),
        op("Unfold", "uv.unwrap", modes=EDIT),
        SEP,
        op("Cut", "m3d.uv_cut", modes=EDIT),
        op("Sew", "m3d.uv_sew", modes=EDIT),
        op("Unfold", "m3d.uv_unfold", modes=EDIT),
        op("Optimize", "m3d.uv_optimize", modes=EDIT),
        op("Layout", "m3d.uv_layout", modes=EDIT),
        op("Auto Unwrap", "m3d.uv_auto", modes=EDIT),
    ]),

    # Sculpting menu set (Blender's own Sculpt, Mask and Face Sets menus).
    "M3D_MT_sculpt": ("Sculpt", [stock("VIEW3D_MT_sculpt")]),
    "M3D_MT_mask": ("Mask", [stock("VIEW3D_MT_mask")]),
    "M3D_MT_face_sets": ("Face Sets", [stock("VIEW3D_MT_face_sets")]),
    "M3D_MT_remesh": ("Remesh", [
        op("Voxel Remesh", "object.voxel_remesh", 'MOD_REMESH', modes={'SCULPT', 'OBJECT'}),
        op("QuadriFlow Remesh", "object.quadriflow_remesh", 'MOD_REMESH'),
        modifier("Multires", 'MULTIRES', 'MOD_MULTIRES'),
        SEP,
        op("Dynamic Topology", "sculpt.dynamic_topology_toggle", 'MOD_DYNAMICPAINT', modes={'SCULPT'}),
        op("Symmetrize", "sculpt.symmetrize", 'MOD_MIRROR', modes={'SCULPT'}),
        op("Sample Detail Size", "sculpt.sample_detail_size", 'EYEDROPPER', modes={'SCULPT'}),
    ]),

    # UV menu set (the UV Toolkit's tools).
    "M3D_MT_uv_edit": ("UV Edit", [*ops(UVTK_CUT_SEW), SEP, *ops(UVTK_UNFOLD), SEP, *ops(UVTK_PIN)]),
    "M3D_MT_uv_select": ("UV Select", ops(UVTK_SELECT)),
    "M3D_MT_uv_create": ("UV Create", ops(UVTK_CREATE)),

    # Texturing menu set.
    "M3D_MT_paint": ("Paint", [
        op("Texture Paint Mode", "object.mode_set", 'TPAINT_HLT', mode='TEXTURE_PAINT'),
        op("Object Mode", "object.mode_set", 'OBJECT_DATAMODE', mode='OBJECT'),
        SEP,
        *(op(label, "brush.asset_activate", modes={'PAINT_TEXTURE'}, **m3d_texture.brush_props(name))
          for label, name in m3d_texture.BRUSHES),
        SEP,
        op("Swap Colors", "paint.brush_colors_flip", 'ARROW_LEFTRIGHT'),
        op("Face Mask", "wm.context_toggle", 'FACESEL', modes={'PAINT_TEXTURE'}, data_path="object.data.use_paint_mask"),
        op("Project Image", "paint.project_image", 'IMAGE_DATA'),
        op("Add Simple UVs", "paint.add_simple_uvs", 'UV'),
    ]),
    "M3D_MT_layers": ("Layers", [
        op("Add Paint Layer", "m3d.layer_add", 'IMAGE_DATA', kind='PAINT'),
        op("Add Fill Layer", "m3d.layer_add", 'COLOR', kind='FILL'),
        op("Duplicate Layer", "m3d.layer_duplicate", 'DUPLICATE'),
        op("Delete Layer", "m3d.layer_remove", 'TRASH'),
        op("Move Layer Up", "m3d.layer_move", 'TRIA_UP', delta=1),
        op("Move Layer Down", "m3d.layer_move", 'TRIA_DOWN', delta=-1),
        op("Show / Hide Layer", "m3d.layer_visible", 'HIDE_OFF'),
        SEP,
        op("New Folder", "m3d.layer_folder_add", 'FILE_FOLDER'),
        op("Group Active Layer", "m3d.layer_folder_add", 'FILE_FOLDER', group=True),
        op("Move Into Folder", "m3d.layer_move_into", 'TRIA_RIGHT'),
        op("Move Out of Folder", "m3d.layer_move_out", 'TRIA_LEFT'),
        op("Freeze Folder", "m3d.layer_freeze", 'FREEZE'),
        op("Unfreeze Folder", "m3d.layer_unfreeze", 'FREEZE'),
        op("Merge Folder", "m3d.layer_merge_folder", 'TRIA_DOWN_BAR'),
        SEP,
        op("Add Mask", "m3d.layer_mask_add", 'MOD_MASK'),
        op("Invert Mask", "m3d.layer_mask_invert", 'ARROW_LEFTRIGHT'),
        op("Remove Mask", "m3d.layer_mask_remove", 'X'),
        op("Paint Mask", "m3d.layer_paint_mask", 'BRUSH_DATA'),
        SEP,
        op("Merge Down", "m3d.layer_merge_down", 'TRIA_DOWN_BAR'),
        op("Flatten", "m3d.layer_flatten", 'IMAGE_DATA'),
        op("Convert to Paint Layer", "m3d.layer_convert", 'IMAGE_DATA'),
        SEP,
        *(op("Paint " + ch.label, "m3d.tex_channel", 'ADD', channel=ch.id) for ch in m3d_texture.CHANNELS),
        SEP,
        op("Next Channel", "m3d.tex_channel_cycle", 'TRIA_RIGHT', delta=1),
        op("Previous Channel", "m3d.tex_channel_cycle", 'TRIA_LEFT', delta=-1),
        SEP,
        op("Add Material", "m3d.tex_add_material", 'MATERIAL'),
        op("Auto Unwrap", "m3d.tex_unwrap", 'MOD_UVPROJECT'),
        op("New Image", "image.new", 'FILE_NEW'),
    ]),
    "M3D_MT_bake": ("Bake", [
        op("Bake Maps", "m3d.tex_bake", 'RENDER_STILL'),
        op("Bake All Groups", "m3d.bg_bake_all", 'RENDER_ANIMATION'),
        op("Auto-Pair by Name", "m3d.hp_auto_pair", 'LINKED'),
        op("Use Selected as High Poly", "m3d.tex_bake_pick", 'EYEDROPPER'),
    ]),
    "M3D_MT_export": ("Export", [
        op("Export Textures", "m3d.tex_export", 'EXPORT'),
        op("Save All Images", "m3d.tex_save_all", 'FILE_TICK'),
        sub("Export Scene", "TOPBAR_MT_file_export", 'EXPORT'),
    ]),

    # Rigging menu set.
    "M3D_MT_skeleton": ("Skeleton", [
        op("Joint Tool", "m3d.rig_joint", 'BONE_DATA'),
        op("Create Joints", "object.armature_add", 'BONE_DATA'),
        op("Insert Joint", "armature.bone_primitive_add", modes=EDIT_ARM),
        op("Extrude Joint", "armature.extrude_move", 'EXPORT', modes=EDIT_ARM),
        op("Mirror Joints", "armature.symmetrize", 'MOD_MIRROR', modes=EDIT_ARM, direction='POSITIVE_X'),
        op("Orient Joint", "m3d.rig_orient", 'ORIENTATION_GIMBAL', modes=EDIT_ARM),
        enum("Roll Joint To", "armature.calculate_roll", "type", modes=EDIT_ARM),
        SEP,
        op("Name Sides (.L / .R)", "armature.autoside_names", modes=EDIT_ARM, type='XAXIS'),
        op("Flip Names", "armature.flip_names", modes=EDIT_ARM),
        op("Select Problem Names", "m3d.rig_name_check", 'ERROR'),
        SEP,
        op("Create IK Handle", "pose.ik_add", modes=POSE),
        op("Pose Mode", "object.posemode_toggle", 'POSE_HLT'),
        op("Edit Mode (Skeleton)", "m3d.rig_mode", 'EDITMODE_HLT', mode='EDIT'),
        op("Object Mode", "m3d.rig_mode", 'OBJECT_DATAMODE', mode='OBJECT'),
    ]),
    "M3D_MT_skin": ("Skin", [
        op("Bind Skin", "m3d.rig_bind", 'ARMATURE_DATA', modes=OBJECT),
        op("Unbind Skin", "m3d.rig_unbind", 'UNLINKED', modes=OBJECT),
        op("Paint Skin Weights", "m3d.rig_mode", 'WPAINT_HLT', mode='WEIGHT_PAINT'),
        op("Mirror Skin Weights", "m3d.rig_mirror_weights", 'MOD_MIRROR', direction='POSITIVE_X'),
        op("Normalize Weights", "object.vertex_group_normalize_all", modes={'PAINT_WEIGHT'}),
        op("Limit Influences", "object.vertex_group_limit_total", modes={'PAINT_WEIGHT'}, group_select_mode='BONE_DEFORM'),
        op("Clean Weights", "object.vertex_group_clean", modes={'PAINT_WEIGHT'}, group_select_mode='BONE_DEFORM'),
        op("Copy Skin Weights", "m3d.rig_transfer_weights", 'MOD_DATA_TRANSFER'),
    ]),
    "M3D_MT_constrain": ("Constrain", [
        constraint("Parent", 'CHILD_OF'),
        constraint("Point", 'COPY_LOCATION'),
        constraint("Orient", 'COPY_ROTATION'),
        constraint("Scale", 'COPY_SCALE'),
        constraint("Aim", 'DAMPED_TRACK'),
        constraint("Geometry (Shrinkwrap)", 'SHRINKWRAP'),
        constraint("Motion Path (Follow Path)", 'FOLLOW_PATH'),
        constraint("Pole Vector (IK)", 'IK'),
        op("IK with Pole Target", "m3d.rig_ik_pole", 'CON_KINEMATIC', modes=POSE),
        SEP,
        op("Remove Constraints", "object.constraints_clear"),
    ]),
    "M3D_MT_control": ("Control", [
        op("Locator", "object.empty_add", 'EMPTY_AXIS', type='PLAIN_AXES'),
        op("Circle Control", "curve.primitive_bezier_circle_add", 'CURVE_BEZCIRCLE'),
        op("Lock and Hide Attributes", "m3d.lock_transforms", 'LOCKED'),
        SEP,
        *(op("Control Shape: " + label, "m3d.rig_control", icon, shape=shape)
          for shape, (label, icon, _build) in m3d_rig.SHAPES.items()),
        op("Remove Control Shape", "m3d.rig_control", 'X', shape='NONE'),
        SEP,
        op("Drivers Editor", "m3d.rig_drivers_editor", 'DRIVER'),
    ]),

    # Animation menu set.
    "M3D_MT_key": ("Key", [
        op("Set Key", "anim.keyframe_insert", 'KEY_HLT'),
        op("Key Translate", "anim.keyframe_insert_by_name", type='Location'),
        op("Key Rotate", "anim.keyframe_insert_by_name", type='Rotation'),
        op("Key Scale", "anim.keyframe_insert_by_name", type='Scaling'),
        op("Delete Keys", "anim.keyframe_delete_v3d", 'KEY_DEHLT'),
        op("Breakdown Key", "m3d.anim_key_type", 'KEYTYPE_BREAKDOWN_VEC', key_type='BREAKDOWN'),
        SEP,
        op("Tween", "m3d.tween", 'ARROW_LEFTRIGHT', interactive=True),
        op("Euler Filter", "m3d.anim_euler_filter", 'DRIVER_ROTATIONAL_DIFFERENCE'),
        op("Blocking Preset", "m3d.anim_preset", preset='BLOCKING'),
        op("Polish Preset", "m3d.anim_preset", preset='POLISH'),
        op("Playblast", "m3d.playblast", 'RENDER_ANIMATION'),
        SEP,
        prop("Auto Keyframe", "tool_settings.use_keyframe_insert_auto"),
        op("Bake Simulation", "nla.bake"),
        SEP,
        editor("Graph Editor", 'FCURVES', 'GRAPH'),
        editor("Dope Sheet", 'DOPESHEET', 'ACTION'),
    ]),
    "M3D_MT_playback": ("Playback", [
        op("Play/Stop", "screen.animation_play", 'PLAY'),
        op("Go to Start", "screen.frame_jump", 'REW', end=False),
        op("Go to End", "screen.frame_jump", 'FF', end=True),
        op("Next Frame", "screen.frame_offset", 'FRAME_NEXT', delta=1),
        op("Previous Frame", "screen.frame_offset", 'FRAME_PREV', delta=-1),
        op("Next Key", "screen.keyframe_jump", 'NEXT_KEYFRAME', next=True),
        op("Previous Key", "screen.keyframe_jump", 'PREV_KEYFRAME', next=False),
    ]),
    "M3D_MT_visualize": ("Visualize", [
        op("Create Motion Trail", "object.paths_calculate", modes=OBJECT),
        op("Delete Motion Trail", "object.paths_clear", modes=OBJECT),
        prop("Ghosting (Onion Skin)", "space_data.overlay.show_motion_paths"),
    ]),

    # FX menu set.
    "M3D_MT_nparticles": ("nParticles", [
        op("Create Emitter", "object.particle_system_add", 'PARTICLES'),
        op("Quick Explode", "object.quick_explode", 'MOD_EXPLODE'),
    ]),
    "M3D_MT_fluids": ("Fluids", [
        op("Smoke/Fire", "object.quick_smoke", 'MOD_FLUIDSIM'),
        op("Liquid", "object.quick_liquid", 'MOD_FLUIDSIM'),
    ]),
    "M3D_MT_ncloth": ("nCloth", [
        modifier("Create nCloth", 'CLOTH', 'MOD_CLOTH'),
        modifier("Create Passive Collider", 'COLLISION', 'MOD_PHYSICS'),
        modifier("Soft Body", 'SOFT_BODY', 'MOD_SOFT'),
    ]),
    "M3D_MT_fields": ("Fields/Solvers", [
        enum("Create Field", "object.effector_add", "type", 'FORCE_FORCE'),
        op("Rigid Body (Active)", "rigidbody.object_add", 'RIGID_BODY', type='ACTIVE'),
        op("Rigid Body (Passive)", "rigidbody.object_add", 'RIGID_BODY_CONSTRAINT', type='PASSIVE'),
    ]),

    # Rendering menu set.
    "M3D_MT_lighting_shading": ("Lighting/Shading", [
        op("Assign New Material", "m3d.assign_material", 'MATERIAL'),
        editor("Shader Editor", 'ShaderNodeTree', 'NODE_MATERIAL'),
        sub("Lights", "VIEW3D_MT_light_add", 'LIGHT'),
        op("HDRI Sky", "m3d.hdri_setup", 'WORLD'),
        op("Back to Previous World", "m3d.hdri_clear", 'LOOP_BACK'),
    ]),
    "M3D_MT_texturing": ("Texturing", [
        editor("UV Editor", 'UV', 'UV'),
        op("Texture Paint Tool", "object.mode_set", 'TPAINT_HLT', mode='TEXTURE_PAINT'),
    ]),
    "M3D_MT_render": ("Render", [
        op("Render Current Frame", "m3d.render", 'RENDER_STILL'),
        op("Render Sequence", "m3d.render", 'RENDER_ANIMATION', animation=True),
        op("IPR Render (Viewport)", "m3d.render_ipr", 'SHADING_RENDERED'),
        op("Render View", "m3d.render_view", 'IMAGE'),
        SEP,
        op("Camera from View", "m3d.render_camera_from_view", 'CAMERA_DATA', mode='NEW'),
        op("Draft Quality", "m3d.render_preset", preset='DRAFT'),
        op("Medium Quality", "m3d.render_preset", preset='MEDIUM'),
        op("Final Quality", "m3d.render_preset", preset='FINAL'),
        SEP,
        prop("Render Engine", "scene.render.engine"),
    ]),

    # Sub menus.
    "M3D_MT_poly_primitives": ("Polygon Primitives", POLY_PRIMITIVES),
    "M3D_MT_booleans": ("Booleans", [
        op("Union", "m3d.boolean", operation='UNION'),
        op("Difference", "m3d.boolean", operation='DIFFERENCE'),
        op("Intersection", "m3d.boolean", operation='INTERSECT'),
    ]),
    "M3D_MT_convert_selection": ("Convert Selection", [
        op("To Vertices", "mesh.select_mode", 'VERTEXSEL', type='VERT', use_expand=True),
        op("To Edges", "mesh.select_mode", 'EDGESEL', type='EDGE', use_expand=True),
        op("To Faces", "mesh.select_mode", 'FACESEL', type='FACE', use_expand=True),
    ]),
    "M3D_MT_transform_tools": ("Transformation Tools", [
        op("Move Tool", "wm.tool_set_by_id", 'EMPTY_ARROWS', name="builtin.move"),
        op("Rotate Tool", "wm.tool_set_by_id", 'ORIENTATION_GIMBAL', name="builtin.rotate"),
        op("Scale Tool", "wm.tool_set_by_id", 'FULLSCREEN_ENTER', name="builtin.scale"),
        op("Universal Manipulator", "wm.tool_set_by_id", name="builtin.transform"),
    ]),
    "M3D_MT_hud": ("Heads Up Display", [
        prop("Poly Count", "space_data.overlay.show_stats"),
        prop("View Axis", "space_data.show_gizmo_navigate"),
        prop("Camera Names / Info", "space_data.overlay.show_text"),
    ]),
    "M3D_MT_ui_elements": ("UI Elements", [
        prop("Shelf", "space_data.show_region_tool_header"),
        prop("Tool Box", "space_data.show_region_toolbar"),
        prop("Sidebar", "space_data.show_region_ui"),
        prop("Viewport Menu Bar", "space_data.show_region_header"),
        prop("Help Line", "screen.show_statusbar"),
    ]),
    "M3D_MT_general_editors": ("General Editors", [
        editor("Outliner", 'OUTLINER', 'OUTLINER'),
        editor("Attribute Editor", 'PROPERTIES', 'PROPERTIES'),
        editor("Node Editor", 'GeometryNodeTree', 'NODETREE'),
        editor("Shader Editor", 'ShaderNodeTree', 'NODE_MATERIAL'),
        editor("Graph Editor", 'FCURVES', 'GRAPH'),
        editor("Dope Sheet", 'DOPESHEET', 'ACTION'),
        editor("Trax Editor (NLA)", 'NLA_EDITOR', 'NLA'),
        editor("UV Editor", 'UV', 'UV'),
        editor("Script Editor", 'TEXT_EDITOR', 'TEXT'),
        editor("Command Line", 'CONSOLE', 'CONSOLE'),
        editor("Spreadsheet", 'SPREADSHEET', 'SPREADSHEET'),
        editor("File Browser", 'FILES', 'FILEBROWSER'),
    ]),
    "M3D_MT_preferences": ("Settings/Preferences", [
        op("Preferences", "screen.userpref_show", 'PREFERENCES'),
        op("Hotkey Editor", "screen.userpref_show", section='KEYMAP'),
        op("Color Settings", "screen.userpref_show", section='THEMES'),
        op("Plug-in Manager", "screen.userpref_show", section='ADDONS'),
    ]),

    # Viewport panel menus.
    "M3D_MT_panel_view": ("View", [
        op("Frame All", "view3d.view_all", center=False),
        op("Frame Selection", "view3d.view_selected"),
        op("Default Home", "view3d.view_all", center=True),
        SEP,
        op("Look Through Selected", "view3d.object_as_camera"),
        op("Align Camera to View", "view3d.camera_to_view"),
        op("Orthographic/Perspective", "view3d.view_persportho"),
        SEP,
        op("Top", "view3d.view_axis", type='TOP'),
        op("Front", "view3d.view_axis", type='FRONT'),
        op("Side", "view3d.view_axis", type='RIGHT'),
        op("Camera", "view3d.view_camera"),
        SEP,
        sub("Image Plane", "VIEW3D_MT_image_add", 'IMAGE_DATA'),
        sub("More", "VIEW3D_MT_view"),
    ]),
    "M3D_MT_panel_shading": ("Shading", [
        shading("Wireframe", 'WIREFRAME', 'SHADING_WIRE'),
        shading("Smooth Shade All", 'SOLID', 'SHADING_SOLID'),
        shading("Textured", 'MATERIAL', 'SHADING_TEXTURE'),
        shading("Lighting (Rendered)", 'RENDERED', 'SHADING_RENDERED'),
        SEP,
        prop("Wireframe on Shaded", "space_data.overlay.show_wireframes"),
        prop("X-Ray", "space_data.shading.show_xray"),
        prop("Backface Culling", "space_data.shading.show_backface_culling"),
    ]),
    "M3D_MT_panel_lighting": ("Lighting", [
        op("Use Default Lighting", "wm.context_set_enum", data_path="space_data.shading.light", value='STUDIO'),
        op("Use Flat Lighting", "wm.context_set_enum", data_path="space_data.shading.light", value='FLAT'),
        op("Use All Lights", "wm.context_set_enum", data_path="space_data.shading.type", value='MATERIAL'),
        SEP,
        prop("Shadows", "space_data.shading.show_shadows"),
        prop("Ambient Occlusion (Cavity)", "space_data.shading.show_cavity"),
    ]),
    "M3D_MT_panel_show": ("Show", [
        prop("All Overlays", "space_data.overlay.show_overlays"),
        SEP,
        prop("Grid", "space_data.overlay.show_floor"),
        prop("Polygons", "space_data.show_object_viewport_mesh"),
        prop("NURBS Curves", "space_data.show_object_viewport_curve"),
        prop("Cameras", "space_data.show_object_viewport_camera"),
        prop("Lights", "space_data.show_object_viewport_light"),
        prop("Locators", "space_data.show_object_viewport_empty"),
        prop("Joints", "space_data.show_object_viewport_armature"),
        prop("Manipulators", "space_data.show_gizmo"),
        prop("Selection Highlighting", "space_data.overlay.show_outline_selected"),
        SEP,
        op("Isolate Select", "view3d.localview"),
    ]),
    "M3D_MT_panel_renderer": ("Renderer", [
        prop("Render Engine", "scene.render.engine"),
        shading("Viewport (Solid)", 'SOLID', 'SHADING_SOLID'),
        shading("Viewport (Material Preview)", 'MATERIAL', 'SHADING_TEXTURE'),
        shading("Viewport (Rendered)", 'RENDERED', 'SHADING_RENDERED'),
    ]),
    "M3D_MT_panel_panels": ("Panels", [
        op("Single / Four View", "screen.region_quadview", 'VIEW_PERSPECTIVE'),
        op("Tear Off Copy", "screen.area_dupli", 'WINDOW'),
        op("Maximize Panel", "screen.screen_full_area", 'FULLSCREEN_ENTER'),
        SEP,
        prop("Panel Type", "area.ui_type"),
    ]),
}

MENU_SETS = {
    'MODELING': ("Modeling", ["M3D_MT_mesh", "M3D_MT_edit_mesh", "M3D_MT_mesh_tools", "M3D_MT_mesh_display",
                              "M3D_MT_curves", "M3D_MT_surfaces", "M3D_MT_deform", "M3D_MT_uv"]),
    'SCULPTING': ("Sculpting", ["M3D_MT_sculpt", "M3D_MT_mask", "M3D_MT_face_sets", "M3D_MT_remesh"]),
    'UV': ("UV", ["M3D_MT_uv_edit", "M3D_MT_uv_select", "M3D_MT_uv_create"]),
    'TEXTURING': ("Texturing", ["M3D_MT_paint", "M3D_MT_layers", "M3D_MT_bake", "M3D_MT_export"]),
    'RIGGING': ("Rigging", ["M3D_MT_skeleton", "M3D_MT_skin", "M3D_MT_deform", "M3D_MT_constrain",
                            "M3D_MT_control"]),
    'ANIMATION': ("Animation", ["M3D_MT_key", "M3D_MT_playback", "M3D_MT_visualize", "M3D_MT_deform",
                                "M3D_MT_constrain"]),
    'FX': ("FX", ["M3D_MT_nparticles", "M3D_MT_fluids", "M3D_MT_ncloth", "M3D_MT_fields"]),
    'RENDERING': ("Rendering", ["M3D_MT_lighting_shading", "M3D_MT_texturing", "M3D_MT_render"]),
}
# Saved enum values: the first five keep the numbers they had before the new sets were added.
_MENU_SET_NUMBERS = {'MODELING': 0, 'RIGGING': 1, 'ANIMATION': 2, 'FX': 3, 'RENDERING': 4,
                     'SCULPTING': 5, 'UV': 6, 'TEXTURING': 7}

COMMON_MENUS = ["M3D_MT_file", "M3D_MT_edit", "M3D_MT_create", "M3D_MT_select", "M3D_MT_modify",
                "M3D_MT_display", "M3D_MT_windows"]

PANEL_MENUS = ["M3D_MT_panel_view", "M3D_MT_panel_shading", "M3D_MT_panel_lighting", "M3D_MT_panel_show",
               "M3D_MT_panel_renderer", "M3D_MT_panel_panels"]


class M3D_MT_workspaces(Menu):
    bl_label = "Workspaces"

    def draw(self, context):
        from m3d_workspace import WORKSPACE_ORDER
        # The factory order, then the others (the tab order itself is not available to Python).
        rank = {name: i for i, name in enumerate(WORKSPACE_ORDER)}
        for ws in sorted(bpy.data.workspaces, key=lambda w: rank.get(w.name, len(rank))):
            o = self.layout.operator("wm.context_set_id", text=ws.name,
                                     icon='CHECKMARK' if ws == context.workspace else 'BLANK1')
            o.data_path, o.value = "window.workspace", ws.name


class M3D_MT_blender_menus(Menu):
    """Blender's original viewport menus"""
    bl_label = "Blender Menus"

    def draw(self, context):
        bpy.types.VIEW3D_MT_editor_menus.draw_blender(self, context)


def _make_menu(idname, label, entries):
    def draw(self, context):
        draw_entries(self.layout, context, entries)
    return type(idname, (Menu,), {"bl_idname": idname, "bl_label": label, "draw": draw})


# -----------------------------------------------------------------------------
# Header drawing (called from bl_ui/space_topbar.py and bl_ui/space_view3d.py)

def draw_menu_bar(layout, context):
    """Main menu bar: menu set selector, common menus, menu set menus, Help."""
    wm = context.window_manager
    layout.prop(wm, "m3d_menu_set", text="")
    for idname in COMMON_MENUS + MENU_SETS[wm.m3d_menu_set][1] + ["M3D_MT_help"]:
        layout.menu(idname)


def _call(layout, idname, icon, label, depress=False, **props):
    """Button that runs `idname` in the main 3D Viewport (the top bar has no viewport context)."""
    o = layout.operator("m3d.call", text="", icon=icon, depress=depress)
    o.idname, o.props, o.label = idname, repr(props), label
    return o


def draw_status_line_model(layout, context):
    """Modeling Status Line, left to right: file, selection mode and masks, snapping, symmetry,
    render, shader editor, input box, sidebar buttons, workspace."""
    from m3d_mode import _view3d_space
    ts = context.tool_settings
    space = _view3d_space(context)
    ob = context.active_object

    draw_file_buttons(layout)

    # Selection mode: object / component.
    row = layout.row(align=True)
    _call(row, "object.mode_set", 'OBJECT_DATAMODE', "Select by Object", depress=context.mode == 'OBJECT',
          mode='OBJECT')
    _call(row, "object.mode_set", 'EDITMODE_HLT', "Select by Component", depress=context.mode == 'EDIT_MESH',
          mode='EDIT')
    if ob is not None:
        # Other modes (sculpt, paint, pose...) live here; Maya has no mode menu in the viewport.
        row.operator_menu_enum("object.mode_set", "mode", text="", icon='DOWNARROW_HLT')
    # Selection masks: which object types can be selected.
    if space is not None:
        row = layout.row(align=True)
        for prop, icon in (("show_object_select_mesh", 'MESH_DATA'), ("show_object_select_curve", 'CURVE_DATA'),
                           ("show_object_select_light", 'LIGHT'), ("show_object_select_camera", 'CAMERA_DATA'),
                           ("show_object_select_empty", 'EMPTY_DATA'), ("show_object_select_armature", 'BONE_DATA')):
            row.prop(space, prop, text="", icon=icon)

    # Snapping: grid, curve, point, view plane / live surface.
    row = layout.row(align=True)
    for item in ('GRID', 'EDGE', 'VERTEX', 'FACE'):
        row.prop_enum(ts, "snap_elements", item, text="")
    row.prop(ts, "use_snap", text="", icon='SNAP_ON' if ts.use_snap else 'SNAP_OFF')
    m3d_retopo.draw_live(layout, context)

    # Symmetry (global, on the active mesh).
    if ob is not None and ob.type == 'MESH':
        layout.prop(ob.data, "use_mirror_x", text="", icon='MOD_MIRROR')

    # Render: render view, render current frame, IPR, render settings; shader editor.
    row = layout.row(align=True)
    row.operator("render.view_show", text="", icon='IMAGE')
    row.operator("render.render", text="", icon='RENDER_STILL')
    _call(row, "wm.context_set_enum", 'SHADING_RENDERED', "IPR Render",
          data_path="space_data.shading.type", value='RENDERED')
    row.operator("m3d.dock_tab", text="", icon='SCENE').tab = 'RENDER'
    row.operator("m3d.open_editor", text="", icon='NODE_MATERIAL').ui_type = 'ShaderNodeTree'

    # Input box: rename the selected object.
    if ob is not None:
        sub = layout.row()
        sub.scale_x = 0.8
        sub.prop(ob, "name", text="", icon='GREASEPENCIL')

    # Sidebar buttons: Modeling Toolkit, Attribute Editor, Tool Settings, Channel Box / Layer Editor.
    row = layout.row(align=True)
    for tab, icon in (('MODELING_TOOLKIT', 'EDITMODE_HLT'), ('OBJECT', 'PROPERTIES'), ('TOOL', 'TOOL_SETTINGS'),
                      ('CHANNEL_BOX', 'ALIGN_JUSTIFY')):
        row.operator("m3d.dock_tab", text="", icon=icon).tab = tab

    draw_workspace_picker(layout, context)


def draw_file_buttons(layout):
    row = layout.row(align=True)
    row.operator("wm.read_homefile", text="", icon='FILE_NEW').app_template = ""
    row.operator("wm.open_mainfile", text="", icon='FILE_FOLDER')
    row.operator("wm.save_mainfile", text="", icon='FILE_TICK')


def draw_workspace_picker(layout, context):
    layout.separator_spacer()
    layout.label(text="Workspace:")
    layout.template_ID(context.window, "workspace", new="workspace.add", unlink="workspace.delete")
    layout.popover("M3D_PT_workspace_settings", text="Settings", icon='PREFERENCES')


def draw_status_line_sculpt(layout, context):
    m3d_sculpt.draw_status_line(layout, context)


def draw_status_line_uv(layout, context):
    m3d_uv.draw_status_line(layout, context)


def draw_status_line_texture(layout, context):
    m3d_texture.draw_status_line(layout, context)


def draw_status_line_rig(layout, context):
    m3d_rig.draw_status_line(layout, context)


def draw_status_line_anim(layout, context):
    m3d_anim.draw_status_line(layout, context)


def draw_status_line_render(layout, context):
    m3d_render.draw_status_line(layout, context)


STATUS_LINES = {'MODEL': draw_status_line_model, 'SCULPT': draw_status_line_sculpt, 'UV': draw_status_line_uv,
                'TEXTURE': draw_status_line_texture, 'RIG': draw_status_line_rig, 'ANIM': draw_status_line_anim,
                'RENDER': draw_status_line_render}


def draw_status_line(layout, context):
    """Status Line of the workspace's kind."""
    STATUS_LINES[current_kind(context)](layout, context)


NODE_TAB_CONTEXTS = {'OBJECT', 'DATA', 'MODIFIER', 'MATERIAL', 'CONSTRAINT', 'PHYSICS', 'PARTICLES',
                     'SHADERFX', 'BONE', 'BONE_CONSTRAINT'}


def draw_node_tabs(layout, context):
    """Dock header: the workspace kind's tabs as text (m3d_workspace.DOCK_TABS), and in All Settings
    (the Attribute Editor) its node tabs: transform node, shape node, inputs (modifiers), material."""
    from m3d_workspace import draw_dock_tabs
    space = context.space_data
    if draw_dock_tabs(layout, context):
        return True
    ob = context.active_object
    if ob is None or space.context not in NODE_TAB_CONTEXTS:
        return False
    tabs = [("OBJECT", ob.name, 'OBJECT_DATAMODE')]
    if ob.data is not None:
        tabs.append(("DATA", ob.data.name, 'MESH_DATA' if ob.type == 'MESH' else 'OBJECT_DATA'))
    if ob.type == 'MESH':
        tabs.append(("MODIFIER", ob.modifiers[-1].name if ob.modifiers else "inputs", 'MODIFIER'))
    if ob.active_material is not None:
        tabs.append(("MATERIAL", ob.active_material.name, 'MATERIAL'))
    row = layout.row(align=True)
    for tab, label, icon in tabs:
        o = row.operator("wm.context_set_enum", text=label, icon=icon, depress=space.context == tab)
        o.data_path, o.value = "space_data.context", tab
    return True


def draw_panel_toolbar(layout, context):
    """Panel toolbar: camera, grid, shading and display toggles under the panel menus."""
    space = context.space_data
    shading, overlay = space.shading, space.overlay
    row = layout.row(align=True)
    row.operator("view3d.view_camera", text="", icon='CAMERA_DATA')
    row.prop(overlay, "show_floor", text="", icon='GRID')
    row = layout.row(align=True)
    for value, icon in (('WIREFRAME', 'SHADING_WIRE'), ('SOLID', 'SHADING_SOLID'), ('MATERIAL', 'SHADING_TEXTURE'),
                        ('RENDERED', 'SHADING_RENDERED')):
        row.prop_enum(shading, "type", value, text="", icon=icon)
    row = layout.row(align=True)
    row.prop(overlay, "show_wireframes", text="", icon='MOD_WIREFRAME')
    if shading.type == 'SOLID':
        row.prop(shading, "show_shadows", text="", icon='LIGHT_SUN')
        row.prop(shading, "show_cavity", text="", icon='SHADING_BBOX')
    row.prop(shading, "show_xray", text="", icon='XRAY')
    row.operator("view3d.localview", text="", icon='HIDE_OFF')


class VIEW3D_PT_m3d_quick_layouts(Panel):
    """Quick Layout buttons under the Tool Box"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_label = "Quick Layouts"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.4
        col.separator(factor=2.0)
        col.operator("screen.region_quadview", text="", icon='MESH_PLANE' if context.space_data.region_quadviews
                     else 'VIEW_PERSPECTIVE')
        col.operator("screen.screen_full_area", text="", icon='FULLSCREEN_ENTER')
        col.operator("m3d.open_editor", text="", icon='OUTLINER').ui_type = 'OUTLINER'


# Maya shelves: tab -> (idname, icon, props). Shown in the viewport's shelf row (tool header).
_MODEL = frozenset({'MODEL'})
_SCULPT = frozenset({'SCULPT'})
_UV = frozenset({'UV'})
_TEXTURE = frozenset({'TEXTURE'})
_RIG = frozenset({'RIG'})
_ANIM = frozenset({'ANIM'})
_RENDER = frozenset({'RENDER'})
# Shelf tab key -> (label, buttons, kinds of workspace that show the tab). A button is (idname, icon, props) or
# (idname, icon, props, text); None is a gap; a function draws its own widgets into the row.
SHELVES = {
    'CURVES': ("Curves / Surfaces", [
        ("curve.primitive_bezier_curve_add", 'CURVE_BEZCURVE', {}),
        ("curve.primitive_bezier_circle_add", 'CURVE_BEZCIRCLE', {}),
        ("curve.primitive_nurbs_curve_add", 'CURVE_NCURVE', {}),
        ("curve.primitive_nurbs_path_add", 'CURVE_PATH', {}),
        None,
        ("surface.primitive_nurbs_surface_sphere_add", 'SURFACE_NSPHERE', {}),
        ("surface.primitive_nurbs_surface_cylinder_add", 'SURFACE_NCYLINDER', {}),
        ("surface.primitive_nurbs_surface_torus_add", 'SURFACE_NTORUS', {}),
        ("surface.primitive_nurbs_surface_surface_add", 'SURFACE_NSURFACE', {}),
        None,
        ("object.modifier_add", 'MOD_SCREW', {"type": 'SCREW'}),
    ], _MODEL),
    'POLY': ("Poly Modeling", [
        ("m3d.add_primitive", 'MESH_UVSPHERE', {"kind": 'SPHERE'}),
        ("m3d.add_primitive", 'MESH_CUBE', {"kind": 'CUBE'}),
        ("m3d.add_primitive", 'MESH_CYLINDER', {"kind": 'CYLINDER'}),
        ("m3d.add_primitive", 'MESH_CONE', {"kind": 'CONE'}),
        ("m3d.add_primitive", 'MESH_TORUS', {"kind": 'TORUS'}),
        ("m3d.add_primitive", 'MESH_PLANE', {"kind": 'PLANE'}),
        None,
        ("object.join", 'AUTOMERGE_ON', {}),
        ("m3d.separate", 'MOD_EXPLODE', {}),
        ("m3d.boolean", 'SELECT_EXTEND', {"operation": 'UNION'}),
        ("m3d.boolean", 'SELECT_SUBTRACT', {"operation": 'DIFFERENCE'}),
        ("m3d.boolean", 'SELECT_INTERSECT', {"operation": 'INTERSECT'}),
        ("object.subdivision_set", 'MOD_SUBSURF', {"level": 1, "relative": False}),
        ("object.modifier_add", 'MOD_MIRROR', {"type": 'MIRROR'}),
        None,
        ("view3d.edit_mesh_extrude_move_normal", 'FACESEL', {}),
        ("mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
        ("mesh.bevel", 'MOD_BEVEL', {}),
        ("mesh.loopcut_slide", 'MOD_EDGESPLIT', {}),
        ("mesh.knife_tool", 'MOD_SIMPLEDEFORM', {}),
        ("m3d.fill_hole", 'SNAP_FACE', {}),
        None,
        ("object.origin_set", 'PIVOT_BOUNDBOX', {"type": 'ORIGIN_GEOMETRY'}),
        ("object.transform_apply", 'FREEZE', {"location": True, "rotation": True, "scale": True}),
        ("object.convert", 'TRASH', {"target": 'MESH'}),
    ], _MODEL),
    'SCULPT': ("Sculpting", [
        ("object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'}),
        ("object.mode_set", 'OBJECT_DATAMODE', {"mode": 'OBJECT'}),
        None,
        ("object.modifier_add", 'MOD_MULTIRES', {"type": 'MULTIRES'}),
        ("object.voxel_remesh", 'MOD_REMESH', {}),
    ], _MODEL),
    'RIGGING': ("Rigging", [
        ("object.armature_add", 'BONE_DATA', {}),
        ("object.parent_set", 'ARMATURE_DATA', {"type": 'ARMATURE_AUTO'}),
        ("object.mode_set", 'WPAINT_HLT', {"mode": 'WEIGHT_PAINT'}),
        ("object.posemode_toggle", 'POSE_HLT', {}),
        None,
        ("object.constraint_add_with_targets", 'CON_CHILDOF', {"type": 'CHILD_OF'}),
        ("object.constraint_add_with_targets", 'CON_LOCLIKE', {"type": 'COPY_LOCATION'}),
        ("object.constraint_add_with_targets", 'CON_ROTLIKE', {"type": 'COPY_ROTATION'}),
        ("object.constraint_add_with_targets", 'CON_TRACKTO', {"type": 'DAMPED_TRACK'}),
        None,
        ("object.empty_add", 'EMPTY_AXIS', {"type": 'PLAIN_AXES'}),
    ], _MODEL),
    'ANIMATION': ("Animation", [
        ("anim.keyframe_insert", 'KEY_HLT', {}),
        ("anim.keyframe_insert_by_name", 'CON_LOCLIKE', {"type": 'Location'}),
        ("anim.keyframe_insert_by_name", 'CON_ROTLIKE', {"type": 'Rotation'}),
        ("anim.keyframe_insert_by_name", 'CON_SIZELIKE', {"type": 'Scaling'}),
        ("anim.keyframe_delete_v3d", 'KEY_DEHLT', {}),
        None,
        ("screen.animation_play", 'PLAY', {}),
        ("m3d.open_editor", 'GRAPH', {"ui_type": 'FCURVES'}),
        ("m3d.open_editor", 'ACTION', {"ui_type": 'DOPESHEET'}),
        ("object.paths_calculate", 'ANIM_DATA', {}),
    ], _MODEL),
    'RENDERING': ("Rendering", [
        ("object.camera_add", 'CAMERA_DATA', {}),
        ("object.light_add", 'LIGHT_POINT', {"type": 'POINT'}),
        ("object.light_add", 'LIGHT_SPOT', {"type": 'SPOT'}),
        ("object.light_add", 'LIGHT_AREA', {"type": 'AREA'}),
        ("object.light_add", 'LIGHT_SUN', {"type": 'SUN'}),
        None,
        ("m3d.assign_material", 'MATERIAL', {}),
        ("m3d.open_editor", 'NODE_MATERIAL', {"ui_type": 'ShaderNodeTree'}),
        None,
        ("render.render", 'RENDER_STILL', {}),
        ("render.render", 'RENDER_ANIMATION', {"animation": True}),
    ], _MODEL),
    'FX': ("FX", [
        ("object.particle_system_add", 'PARTICLES', {}),
        ("object.quick_smoke", 'MOD_FLUIDSIM', {}),
        ("object.quick_liquid", 'MOD_FLUID', {}),
        ("object.quick_explode", 'MOD_EXPLODE', {}),
        None,
        ("object.modifier_add", 'MOD_CLOTH', {"type": 'CLOTH'}),
        ("object.modifier_add", 'MOD_PHYSICS', {"type": 'COLLISION'}),
        ("object.effector_add", 'FORCE_FORCE', {"type": 'FORCE'}),
        ("object.effector_add", 'FORCE_TURBULENCE', {"type": 'TURBULENCE'}),
        ("rigidbody.object_add", 'RIGID_BODY', {"type": 'ACTIVE'}),
    ], _MODEL),
    'SCULPT_BRUSHES': ("Sculpt", m3d_sculpt.SHELF_BRUSHES, _SCULPT),
    'SCULPT_REMESH': ("Remesh", m3d_sculpt.SHELF_REMESH, _SCULPT),
    'SCULPT_MASK': ("Mask", m3d_sculpt.SHELF_MASK, _SCULPT),
    'UV': ("UV", m3d_uv.SHELF_UV, _UV),
    'TEXTURE_BRUSHES': ("Paint", m3d_texture.SHELF_BRUSHES, _TEXTURE),
    'TEXTURE_CHANNELS': ("Channels", m3d_texture.SHELF_CHANNELS, _TEXTURE),
    'TEXTURE_OUTPUT': ("Bake / Export", m3d_texture.SHELF_OUTPUT, _TEXTURE),
    'RIG_SKELETON': ("Skeleton", m3d_rig.SHELF_SKELETON, _RIG),
    'RIG_CONTROLS': ("Controls", m3d_rig.SHELF_CONTROLS, _RIG),
    'RIG_SKIN': ("Skin", m3d_rig.SHELF_SKIN, _RIG),
    'ANIM_ANIMATE': ("Animate", m3d_anim.SHELF_ANIMATE, _ANIM),
    'ANIM_POSES': ("Poses", m3d_anim.SHELF_POSES, _ANIM),
    'RENDER_LIGHTS': ("Lights", m3d_render.SHELF_LIGHTS, _RENDER),
    'RENDER_RENDER': ("Render", m3d_render.SHELF_RENDER, _RENDER),
    # Buttons added by the user (m3d_user.py); every kind has its own.
    'CUSTOM': ("Custom", [], frozenset(KINDS)),
}


def shelves_for(kind):
    return [key for key, (_label, _items, kinds) in SHELVES.items() if kind in kinds]


def shelf_key(wm, kind):
    """The shelf tab shown: the picked one if this kind has it, else the kind's first."""
    keys = shelves_for(kind)
    return wm.m3d_shelf if wm.m3d_shelf in keys else keys[0]


_shelf_memory = {}


def restore_shelf(wm, prev_kind, kind):
    """Workspace kind changed: remember the shelf tab of the old kind, bring back the new kind's."""
    _shelf_memory[prev_kind] = wm.m3d_shelf
    keys = shelves_for(kind)
    want = _shelf_memory.get(kind)
    wm.m3d_shelf = want if want in keys else 'POLY' if 'POLY' in keys else keys[0]


def draw_shelf(layout, context):
    """Shelf: the active shelf's buttons, large large (the tabs are the row above)."""
    import m3d_edit
    from m3d_mode import _button
    wm, kind = context.window_manager, current_kind(context)
    key = shelf_key(wm, kind)
    edit = m3d_edit.editing()
    if key == 'CUSTOM':
        from m3d_user import draw_custom_shelf
        draw_custom_shelf(layout, context, kind, edit)
        return
    row = layout.row(align=True)
    if edit:
        # Fixed-width cells, so the edit mode's drag can tell which button is where.
        rec = m3d_edit.begin_shelf(context, key, kind)
    else:
        row.scale_x = row.scale_y = 1.5
    for i, item in enumerate(SHELVES[key][1]):
        if item is None:
            if edit:
                m3d_edit.add_gap(rec, row)
            else:
                row.separator(factor=0.5)
        elif callable(item):
            if edit:
                cell = m3d_edit.add_cell(rec, row, m3d_edit.CALL_CELL)
                cell.label(text="")   # An empty cell takes no room, and the widget may draw nothing.
                item(cell, context)
            else:
                item(row, context)
        else:
            idname, icon, props, *text = item
            label = text[0] if text else ""
            target = row
            if edit:
                width = m3d_edit.text_units(rec, label) if label and icon == 'NONE' else m3d_edit.ICON_CELL
                target = m3d_edit.add_cell(rec, row, width, ("B", key, i), icon=width == m3d_edit.ICON_CELL)
            _button(target, context, label, idname, icon, props,
                    depress=m3d_sculpt.is_active(context, idname, props))


class TOPBAR_HT_m3d_status_line(bpy.types.Header):
    """Status Line: the second row of the top bar"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'TOOL_HEADER'

    def draw(self, context):
        draw_status_line(self.layout, context)


class TOPBAR_HT_m3d_shelf_tabs(bpy.types.Header):
    """Shelf tabs: the third row of the top bar"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'FOOTER'

    def draw(self, context):
        import m3d_edit
        wm, kind = context.window_manager, current_kind(context)
        row = self.layout.row(align=True)
        edit = m3d_edit.editing()
        for key in shelves_for(kind):
            if edit and key == 'CUSTOM':
                continue
            row.prop_enum(wm, "m3d_shelf", key)
        if edit:
            # The Custom tab is the drop target of a button dragged from another shelf: a cell at the right end.
            m3d_edit.begin_tabs(context, kind)
            self.layout.separator_spacer()
            cell = self.layout.row(align=True)
            cell.ui_units_x = m3d_edit.TABS_CUSTOM_CELL
            cell.alert = m3d_edit._drag["target"] == "tab"
            cell.prop_enum(wm, "m3d_shelf", 'CUSTOM', text="Custom (drop here)")


class TOPBAR_HT_m3d_shelf(bpy.types.Header):
    """Shelf buttons: the bottom row of the top bar"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        draw_shelf(self.layout, context)


def draw_panel_menus(layout, context):
    for idname in PANEL_MENUS:
        layout.menu(idname)
    if context.mode in {'OBJECT', 'EDIT_MESH'}:
        layout.menu("M3D_MT_blender_menus", text="", icon='COLLAPSEMENU')
    layout.separator()
    draw_panel_toolbar(layout, context)


classes = (
    *(_make_menu(idname, label, entries) for idname, (label, entries) in MENUS.items()),
    M3D_MT_workspaces,
    M3D_MT_blender_menus,
    VIEW3D_PT_m3d_quick_layouts,
    TOPBAR_HT_m3d_status_line,
    TOPBAR_HT_m3d_shelf_tabs,
    TOPBAR_HT_m3d_shelf,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.m3d_menu_set = bpy.props.EnumProperty(
        name="Menu Set", description="Menu set: which menus the main menu bar shows",
        items=[(k, label, "", 'NONE', _MENU_SET_NUMBERS[k]) for k, (label, _) in MENU_SETS.items()])
    wm.m3d_shelf = bpy.props.EnumProperty(
        name="Shelf", description="Shelf tab",
        items=[(k, label, "") for k, (label, _items, _kinds) in SHELVES.items()], default='POLY')


def unregister():
    del bpy.types.WindowManager.m3d_shelf
    del bpy.types.WindowManager.m3d_menu_set
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
