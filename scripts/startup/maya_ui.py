# SPDX-FileCopyrightText: 2026 MayaBlender
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya-style interface for MayaBlender:
main menu bar with menu sets, status line, shelf tabs and viewport panel menus.

Menus are plain data (see `MENUS`) so `tools/maya/test_maya.py` can verify every command exists.
"""

import bpy
from bpy.types import Menu, Panel


# -----------------------------------------------------------------------------
# Menu entry helpers

def op(label, idname, icon='NONE', modes=None, **props):
    return {"kind": 'OP', "label": label, "idname": idname, "icon": icon, "modes": modes, "props": props}


def sub(label, menu, icon='NONE', modes=None):
    return {"kind": 'MENU', "label": label, "idname": menu, "icon": icon, "modes": modes}


def prop(label, path, modes=None):
    """Toggle a property given as a context path, e.g. `space_data.overlay.show_floor`."""
    return {"kind": 'PROP', "label": label, "path": path, "modes": modes}


def enum(label, idname, prop_name, icon='NONE', modes=None):
    return {"kind": 'ENUM', "label": label, "idname": idname, "prop": prop_name, "icon": icon, "modes": modes}


def modifier(label, type, icon='MODIFIER'):
    return op(label, "object.modifier_add", icon, type=type)


def constraint(label, type, icon='CONSTRAINT'):
    return op(label, "object.constraint_add_with_targets", icon, type=type)


def editor(label, ui_type, icon='NONE'):
    return op(label, "maya.open_editor", icon, ui_type=ui_type)


def shading(label, type, icon='NONE'):
    return op(label, "wm.context_set_enum", icon, data_path="space_data.shading.type", value=type)


SEP = {"kind": 'SEP', "modes": None}
EDIT = {'EDIT_MESH'}
OBJECT = {'OBJECT'}

# Operators that need a 3D Viewport context: from the top bar they run through `maya.call`.
_VIEW3D_PREFIXES = (
    "view3d.", "transform.", "wm.context_", "wm.tool_set_by_id", "screen.region_quadview",
    "mesh.loopcut_slide", "mesh.knife_tool", "mesh.bevel", "mesh.offset_edge_loops_slide",
    "mesh.duplicate_move", "object.duplicate_move", "uv.project_from_view", "mesh.dupli_extrude_cursor",
)


def needs_view3d(idname):
    return idname.startswith(_VIEW3D_PREFIXES)


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
        elif kind == 'ENUM':
            layout.operator_menu_enum(e["idname"], e["prop"], text=e["label"], icon=e["icon"])
        elif kind == 'PROP':
            owner, attr = _resolve(context, e["path"])
            if owner is not None:
                layout.prop(owner, attr, text=e["label"])
            elif not in_view3d:
                o = layout.operator("maya.call", text=e["label"])
                o.idname, o.props = "wm.context_toggle", repr({"data_path": e["path"]})
        elif not in_view3d and (needs_view3d(e["idname"]) or not _poll(e["idname"])):
            o = layout.operator("maya.call", text=e["label"], icon=e["icon"])
            o.idname, o.props, o.label = e["idname"], repr(e["props"]), e["label"]
        else:
            o = layout.operator(e["idname"], text=e["label"], icon=e["icon"])
            for k, v in e["props"].items():
                setattr(o, k, v)


# -----------------------------------------------------------------------------
# Main menu bar (always visible) and menu sets

POLY_PRIMITIVES = [
    op("Sphere", "maya.add_primitive", 'MESH_UVSPHERE', kind='SPHERE'),
    op("Cube", "maya.add_primitive", 'MESH_CUBE', kind='CUBE'),
    op("Cylinder", "maya.add_primitive", 'MESH_CYLINDER', kind='CYLINDER'),
    op("Cone", "maya.add_primitive", 'MESH_CONE', kind='CONE'),
    op("Torus", "maya.add_primitive", 'MESH_TORUS', kind='TORUS'),
    op("Plane", "maya.add_primitive", 'MESH_PLANE', kind='PLANE'),
    SEP,
    sub("More Primitives", "VIEW3D_MT_mesh_add", 'ADD'),
]

MENUS = {
    # Common menus.
    "MAYA_MT_file": ("File", [
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
    "MAYA_MT_edit": ("Edit", [
        op("Undo", "ed.undo", 'LOOP_BACK'),
        op("Redo", "ed.redo", 'LOOP_FORWARDS'),
        op("Repeat", "screen.repeat_last"),
        op("Undo History", "ed.undo_history"),
        SEP,
        op("Copy", "view3d.copybuffer", modes=OBJECT),
        op("Paste", "view3d.pastebuffer", modes=OBJECT),
        SEP,
        op("Delete", "object.delete", 'X', modes=OBJECT),
        op("Delete All History", "object.convert", modes=OBJECT, target='MESH'),
        op("Duplicate", "maya.duplicate", 'DUPLICATE', modes=OBJECT),
        op("Duplicate with Transform", "maya.duplicate", modes=OBJECT, with_transform=True),
        op("Duplicate Special (Instance)", "object.duplicate_move_linked", modes=OBJECT),
        op("Duplicate", "mesh.duplicate_move", 'DUPLICATE', modes=EDIT),
        SEP,
        op("Group", "maya.group", 'EMPTY_AXIS', modes=OBJECT),
        op("Ungroup", "maya.ungroup", modes=OBJECT),
        op("Parent", "object.parent_set", modes=OBJECT),
        op("Unparent", "object.parent_clear", modes=OBJECT, type='CLEAR_KEEP_TRANSFORM'),
        SEP,
        op("Search Command...", "wm.search_menu", 'VIEWZOOM'),
    ]),
    "MAYA_MT_create": ("Create", [
        sub("Polygon Primitives", "MAYA_MT_poly_primitives", 'MESH_CUBE'),
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
    "MAYA_MT_select": ("Select", [
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
        sub("Convert Selection", "MAYA_MT_convert_selection", modes=EDIT),
        SEP,
        op("Select Tool", "wm.tool_set_by_id", 'RESTRICT_SELECT_OFF', name="builtin.select_box"),
        op("Lasso Tool", "wm.tool_set_by_id", name="builtin.select_lasso"),
        op("Paint Selection Tool", "wm.tool_set_by_id", name="builtin.select_circle"),
        SEP,
        sub("More", "VIEW3D_MT_select_object", modes=OBJECT),
        sub("More", "VIEW3D_MT_select_edit_mesh", modes=EDIT),
    ]),
    "MAYA_MT_modify": ("Modify", [
        sub("Transformation Tools", "MAYA_MT_transform_tools"),
        op("Reset Transformations", "maya.reset_transformations", modes=OBJECT),
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
    "MAYA_MT_display": ("Display", [
        prop("Grid", "space_data.overlay.show_floor"),
        sub("Heads Up Display", "MAYA_MT_hud"),
        sub("UI Elements", "MAYA_MT_ui_elements"),
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
    "MAYA_MT_windows": ("Windows", [
        sub("Workspaces", "MAYA_MT_workspaces", 'WORKSPACE'),
        sub("General Editors", "MAYA_MT_general_editors", 'WINDOW'),
        sub("Settings/Preferences", "MAYA_MT_preferences", 'PREFERENCES'),
        SEP,
        editor("Outliner", 'OUTLINER', 'OUTLINER'),
        op("Attribute Editor", "maya.dock_tab", 'PROPERTIES', tab='OBJECT'),
        op("Channel Box / Layer Editor", "maya.dock_tab", 'ALIGN_JUSTIFY', tab='CHANNEL_BOX'),
        op("Modeling Toolkit", "maya.dock_tab", 'EDITMODE_HLT', tab='MODELING_TOOLKIT'),
        op("Tool Settings", "maya.dock_tab", 'TOOL_SETTINGS', tab='TOOL'),
        editor("Hypershade", 'ShaderNodeTree', 'NODE_MATERIAL'),
        editor("Graph Editor", 'FCURVES', 'GRAPH'),
        editor("Dope Sheet", 'DOPESHEET', 'ACTION'),
        editor("UV Editor", 'UV', 'UV'),
        editor("Script Editor", 'TEXT_EDITOR', 'TEXT'),
        SEP,
        op("Command Line: MEL", "maya.command_language", 'CONSOLE', language='mel'),
        op("Command Line: Python", "maya.command_language", 'CONSOLE', language='python'),
        op("Toggle Full Screen", "wm.window_fullscreen_toggle", 'FULLSCREEN_ENTER'),
    ]),
    "MAYA_MT_help": ("Help", [
        sub("Help", "TOPBAR_MT_help", 'HELP'),
        op("Hotkey Editor", "screen.userpref_show", 'KEYINGSET', section='KEYMAP'),
    ]),

    # Modeling menu set.
    "MAYA_MT_mesh": ("Mesh", [
        sub("Booleans", "MAYA_MT_booleans", 'MOD_BOOLEAN'),
        op("Combine", "object.join", 'AUTOMERGE_ON', modes=OBJECT),
        op("Separate", "maya.separate", modes=OBJECT),
        SEP,
        modifier("Mirror", 'MIRROR', 'MOD_MIRROR'),
        op("Smooth", "object.subdivision_set", 'MOD_SUBSURF', level=1, relative=False),
        modifier("Reduce", 'DECIMATE', 'MOD_DECIM'),
        modifier("Remesh", 'REMESH', 'MOD_REMESH'),
        modifier("Triangulate", 'TRIANGULATE', 'MOD_TRIANGULATE'),
        op("Quadrangulate", "mesh.tris_convert_to_quads", modes=EDIT),
        SEP,
        op("Fill Hole", "maya.fill_hole"),
        op("Cleanup (Merge by Distance)", "mesh.remove_doubles", modes=EDIT),
    ]),
    "MAYA_MT_edit_mesh": ("Edit Mesh", [
        op("Add Divisions", "mesh.subdivide"),
        op("Bevel", "mesh.bevel", 'MOD_BEVEL', offset_type='PERCENT'),
        op("Bridge", "mesh.bridge_edge_loops"),
        op("Collapse", "mesh.merge", type='COLLAPSE'),
        op("Connect", "maya.connect"),
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
    "MAYA_MT_mesh_tools": ("Mesh Tools", [
        op("Create Polygon", "mesh.edge_face_add"),
        op("Crease Tool", "transform.edge_crease"),
        op("Insert Edge Loop", "mesh.loopcut_slide", 'MOD_EDGESPLIT'),
        op("Multi-Cut", "mesh.knife_tool"),
        op("Offset Edge Loop", "mesh.offset_edge_loops_slide"),
        op("Quad Draw", "wm.tool_set_by_id", name="builtin.poly_build"),
        op("Slide Edge", "transform.edge_slide"),
        op("Target Weld", "mesh.merge", type='LAST'),
    ]),
    "MAYA_MT_mesh_display": ("Mesh Display", [
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
    "MAYA_MT_curves": ("Curves", [
        sub("Create Curve", "VIEW3D_MT_curve_add", 'CURVE_BEZCURVE'),
        op("Open/Close", "curve.cyclic_toggle", modes={'EDIT_CURVE'}),
        op("Reverse Direction", "curve.switch_direction", modes={'EDIT_CURVE'}),
        op("Smooth", "curve.smooth", modes={'EDIT_CURVE'}),
        op("Subdivide", "curve.subdivide", modes={'EDIT_CURVE'}),
        op("Draw Curve", "wm.tool_set_by_id", modes={'EDIT_CURVE'}, name="builtin.draw"),
    ]),
    "MAYA_MT_surfaces": ("Surfaces", [
        sub("NURBS Primitives", "VIEW3D_MT_surface_add", 'SURFACE_NSURFACE'),
        modifier("Revolve", 'SCREW', 'MOD_SCREW'),
        modifier("Extrude (Solidify)", 'SOLIDIFY', 'MOD_SOLIDIFY'),
    ]),
    "MAYA_MT_deform": ("Deform", [
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
    "MAYA_MT_uv": ("UV", [
        editor("UV Editor", 'UV', 'UV'),
        op("UV Editing Workspace", "wm.context_set_id", 'WORKSPACE', data_path="window.workspace", value="UV Editing"),
        op("Checker Map", "maya.uv_checker", 'TEXTURE'),
        SEP,
        op("Automatic", "uv.smart_project", modes=EDIT),
        op("Planar", "uv.project_from_view", modes=EDIT),
        op("Cylindrical", "uv.cylinder_project", modes=EDIT),
        op("Spherical", "uv.sphere_project", modes=EDIT),
        op("Unfold", "uv.unwrap", modes=EDIT),
        SEP,
        op("Cut", "maya.uv_cut", modes=EDIT),
        op("Sew", "maya.uv_sew", modes=EDIT),
        op("Unfold", "maya.uv_unfold", modes=EDIT),
        op("Layout", "uv.pack_islands", modes=EDIT, margin=0.01),
    ]),

    # Rigging menu set.
    "MAYA_MT_skeleton": ("Skeleton", [
        op("Create Joints", "object.armature_add", 'BONE_DATA'),
        op("Insert Joint", "armature.bone_primitive_add", modes={'EDIT_ARMATURE'}),
        op("Mirror Joints", "armature.symmetrize", modes={'EDIT_ARMATURE'}),
        enum("Orient Joint", "armature.calculate_roll", "type", modes={'EDIT_ARMATURE'}),
        op("Create IK Handle", "pose.ik_add", modes={'POSE'}),
        op("Pose Mode", "object.posemode_toggle", 'POSE_HLT'),
    ]),
    "MAYA_MT_skin": ("Skin", [
        op("Bind Skin", "object.parent_set", 'ARMATURE_DATA', modes=OBJECT, type='ARMATURE_AUTO'),
        op("Unbind Skin", "object.parent_clear", modes=OBJECT, type='CLEAR_KEEP_TRANSFORM'),
        op("Paint Skin Weights", "object.mode_set", 'WPAINT_HLT', mode='WEIGHT_PAINT'),
        op("Mirror Skin Weights", "object.vertex_group_mirror", modes={'WEIGHT_PAINT'}),
        op("Normalize Weights", "object.vertex_group_normalize_all", modes={'WEIGHT_PAINT'}),
    ]),
    "MAYA_MT_constrain": ("Constrain", [
        constraint("Parent", 'CHILD_OF'),
        constraint("Point", 'COPY_LOCATION'),
        constraint("Orient", 'COPY_ROTATION'),
        constraint("Scale", 'COPY_SCALE'),
        constraint("Aim", 'DAMPED_TRACK'),
        constraint("Geometry (Shrinkwrap)", 'SHRINKWRAP'),
        constraint("Motion Path (Follow Path)", 'FOLLOW_PATH'),
        constraint("Pole Vector (IK)", 'IK'),
        SEP,
        op("Remove Constraints", "object.constraints_clear"),
    ]),
    "MAYA_MT_control": ("Control", [
        op("Locator", "object.empty_add", 'EMPTY_AXIS', type='PLAIN_AXES'),
        op("Circle Control", "curve.primitive_bezier_circle_add", 'CURVE_BEZCIRCLE'),
        op("Lock and Hide Attributes", "maya.lock_transforms", 'LOCKED'),
    ]),

    # Animation menu set.
    "MAYA_MT_key": ("Key", [
        op("Set Key", "anim.keyframe_insert", 'KEY_HLT'),
        op("Key Translate", "anim.keyframe_insert_by_name", type='Location'),
        op("Key Rotate", "anim.keyframe_insert_by_name", type='Rotation'),
        op("Key Scale", "anim.keyframe_insert_by_name", type='Scaling'),
        op("Delete Keys", "anim.keyframe_delete_v3d", 'KEY_DEHLT'),
        SEP,
        prop("Auto Keyframe", "tool_settings.use_keyframe_insert_auto"),
        op("Bake Simulation", "nla.bake"),
        SEP,
        editor("Graph Editor", 'FCURVES', 'GRAPH'),
        editor("Dope Sheet", 'DOPESHEET', 'ACTION'),
    ]),
    "MAYA_MT_playback": ("Playback", [
        op("Play/Stop", "screen.animation_play", 'PLAY'),
        op("Go to Start", "screen.frame_jump", 'REW', end=False),
        op("Go to End", "screen.frame_jump", 'FF', end=True),
        op("Next Frame", "screen.frame_offset", 'FRAME_NEXT', delta=1),
        op("Previous Frame", "screen.frame_offset", 'FRAME_PREV', delta=-1),
        op("Next Key", "screen.keyframe_jump", 'NEXT_KEYFRAME', next=True),
        op("Previous Key", "screen.keyframe_jump", 'PREV_KEYFRAME', next=False),
    ]),
    "MAYA_MT_visualize": ("Visualize", [
        op("Create Motion Trail", "object.paths_calculate", modes=OBJECT),
        op("Delete Motion Trail", "object.paths_clear", modes=OBJECT),
        prop("Ghosting (Onion Skin)", "space_data.overlay.show_motion_paths"),
    ]),

    # FX menu set.
    "MAYA_MT_nparticles": ("nParticles", [
        op("Create Emitter", "object.particle_system_add", 'PARTICLES'),
        op("Quick Explode", "object.quick_explode", 'MOD_EXPLODE'),
    ]),
    "MAYA_MT_fluids": ("Fluids", [
        op("Smoke/Fire", "object.quick_smoke", 'MOD_FLUIDSIM'),
        op("Liquid", "object.quick_liquid", 'MOD_FLUIDSIM'),
    ]),
    "MAYA_MT_ncloth": ("nCloth", [
        modifier("Create nCloth", 'CLOTH', 'MOD_CLOTH'),
        modifier("Create Passive Collider", 'COLLISION', 'MOD_PHYSICS'),
        modifier("Soft Body", 'SOFT_BODY', 'MOD_SOFT'),
    ]),
    "MAYA_MT_fields": ("Fields/Solvers", [
        enum("Create Field", "object.effector_add", "type", 'FORCE_FORCE'),
        op("Rigid Body (Active)", "rigidbody.object_add", 'RIGID_BODY', type='ACTIVE'),
        op("Rigid Body (Passive)", "rigidbody.object_add", 'RIGID_BODY_CONSTRAINT', type='PASSIVE'),
    ]),

    # Rendering menu set.
    "MAYA_MT_lighting_shading": ("Lighting/Shading", [
        op("Assign New Material", "maya.assign_material", 'MATERIAL'),
        editor("Hypershade", 'ShaderNodeTree', 'NODE_MATERIAL'),
        sub("Lights", "VIEW3D_MT_light_add", 'LIGHT'),
    ]),
    "MAYA_MT_texturing": ("Texturing", [
        editor("UV Editor", 'UV', 'UV'),
        op("3D Paint Tool", "object.mode_set", 'TPAINT_HLT', mode='TEXTURE_PAINT'),
    ]),
    "MAYA_MT_render": ("Render", [
        op("Render Current Frame", "render.render", 'RENDER_STILL'),
        op("Render Sequence", "render.render", 'RENDER_ANIMATION', animation=True),
        op("IPR Render (Viewport)", "wm.context_set_enum", 'SHADING_RENDERED',
           data_path="space_data.shading.type", value='RENDERED'),
        op("Render View", "render.view_show", 'IMAGE'),
        SEP,
        prop("Render Engine", "scene.render.engine"),
    ]),

    # Sub menus.
    "MAYA_MT_poly_primitives": ("Polygon Primitives", POLY_PRIMITIVES),
    "MAYA_MT_booleans": ("Booleans", [
        op("Union", "maya.boolean", operation='UNION'),
        op("Difference", "maya.boolean", operation='DIFFERENCE'),
        op("Intersection", "maya.boolean", operation='INTERSECT'),
    ]),
    "MAYA_MT_convert_selection": ("Convert Selection", [
        op("To Vertices", "mesh.select_mode", 'VERTEXSEL', type='VERT', use_expand=True),
        op("To Edges", "mesh.select_mode", 'EDGESEL', type='EDGE', use_expand=True),
        op("To Faces", "mesh.select_mode", 'FACESEL', type='FACE', use_expand=True),
    ]),
    "MAYA_MT_transform_tools": ("Transformation Tools", [
        op("Move Tool", "wm.tool_set_by_id", 'EMPTY_ARROWS', name="builtin.move"),
        op("Rotate Tool", "wm.tool_set_by_id", 'ORIENTATION_GIMBAL', name="builtin.rotate"),
        op("Scale Tool", "wm.tool_set_by_id", 'FULLSCREEN_ENTER', name="builtin.scale"),
        op("Universal Manipulator", "wm.tool_set_by_id", name="builtin.transform"),
    ]),
    "MAYA_MT_hud": ("Heads Up Display", [
        prop("Poly Count", "space_data.overlay.show_stats"),
        prop("View Axis", "space_data.show_gizmo_navigate"),
        prop("Camera Names / Info", "space_data.overlay.show_text"),
    ]),
    "MAYA_MT_ui_elements": ("UI Elements", [
        prop("Shelf", "space_data.show_region_tool_header"),
        prop("Tool Box", "space_data.show_region_toolbar"),
        prop("Sidebar", "space_data.show_region_ui"),
        prop("Viewport Menu Bar", "space_data.show_region_header"),
        prop("Help Line", "screen.show_statusbar"),
    ]),
    "MAYA_MT_general_editors": ("General Editors", [
        editor("Outliner", 'OUTLINER', 'OUTLINER'),
        editor("Attribute Editor", 'PROPERTIES', 'PROPERTIES'),
        editor("Node Editor", 'GeometryNodeTree', 'NODETREE'),
        editor("Hypershade", 'ShaderNodeTree', 'NODE_MATERIAL'),
        editor("Graph Editor", 'FCURVES', 'GRAPH'),
        editor("Dope Sheet", 'DOPESHEET', 'ACTION'),
        editor("Trax Editor (NLA)", 'NLA_EDITOR', 'NLA'),
        editor("UV Editor", 'UV', 'UV'),
        editor("Script Editor", 'TEXT_EDITOR', 'TEXT'),
        editor("Command Line", 'CONSOLE', 'CONSOLE'),
        editor("Spreadsheet", 'SPREADSHEET', 'SPREADSHEET'),
        editor("File Browser", 'FILES', 'FILEBROWSER'),
    ]),
    "MAYA_MT_preferences": ("Settings/Preferences", [
        op("Preferences", "screen.userpref_show", 'PREFERENCES'),
        op("Hotkey Editor", "screen.userpref_show", section='KEYMAP'),
        op("Color Settings", "screen.userpref_show", section='THEMES'),
        op("Plug-in Manager", "screen.userpref_show", section='ADDONS'),
    ]),

    # Viewport panel menus.
    "MAYA_MT_panel_view": ("View", [
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
    "MAYA_MT_panel_shading": ("Shading", [
        shading("Wireframe", 'WIREFRAME', 'SHADING_WIRE'),
        shading("Smooth Shade All", 'SOLID', 'SHADING_SOLID'),
        shading("Textured", 'MATERIAL', 'SHADING_TEXTURE'),
        shading("Lighting (Rendered)", 'RENDERED', 'SHADING_RENDERED'),
        SEP,
        prop("Wireframe on Shaded", "space_data.overlay.show_wireframes"),
        prop("X-Ray", "space_data.shading.show_xray"),
        prop("Backface Culling", "space_data.shading.show_backface_culling"),
    ]),
    "MAYA_MT_panel_lighting": ("Lighting", [
        op("Use Default Lighting", "wm.context_set_enum", data_path="space_data.shading.light", value='STUDIO'),
        op("Use Flat Lighting", "wm.context_set_enum", data_path="space_data.shading.light", value='FLAT'),
        op("Use All Lights", "wm.context_set_enum", data_path="space_data.shading.type", value='MATERIAL'),
        SEP,
        prop("Shadows", "space_data.shading.show_shadows"),
        prop("Ambient Occlusion (Cavity)", "space_data.shading.show_cavity"),
    ]),
    "MAYA_MT_panel_show": ("Show", [
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
    "MAYA_MT_panel_renderer": ("Renderer", [
        prop("Render Engine", "scene.render.engine"),
        shading("Viewport (Solid)", 'SOLID', 'SHADING_SOLID'),
        shading("Viewport (Material Preview)", 'MATERIAL', 'SHADING_TEXTURE'),
        shading("Viewport (Rendered)", 'RENDERED', 'SHADING_RENDERED'),
    ]),
    "MAYA_MT_panel_panels": ("Panels", [
        op("Single / Four View", "screen.region_quadview", 'VIEW_PERSPECTIVE'),
        op("Tear Off Copy", "screen.area_dupli", 'WINDOW'),
        op("Maximize Panel", "screen.screen_full_area", 'FULLSCREEN_ENTER'),
        SEP,
        prop("Panel Type", "area.ui_type"),
    ]),
}

MENU_SETS = {
    'MODELING': ("Modeling", ["MAYA_MT_mesh", "MAYA_MT_edit_mesh", "MAYA_MT_mesh_tools", "MAYA_MT_mesh_display",
                              "MAYA_MT_curves", "MAYA_MT_surfaces", "MAYA_MT_deform", "MAYA_MT_uv"]),
    'RIGGING': ("Rigging", ["MAYA_MT_skeleton", "MAYA_MT_skin", "MAYA_MT_deform", "MAYA_MT_constrain",
                            "MAYA_MT_control"]),
    'ANIMATION': ("Animation", ["MAYA_MT_key", "MAYA_MT_playback", "MAYA_MT_visualize", "MAYA_MT_deform",
                                "MAYA_MT_constrain"]),
    'FX': ("FX", ["MAYA_MT_nparticles", "MAYA_MT_fluids", "MAYA_MT_ncloth", "MAYA_MT_fields"]),
    'RENDERING': ("Rendering", ["MAYA_MT_lighting_shading", "MAYA_MT_texturing", "MAYA_MT_render"]),
}

COMMON_MENUS = ["MAYA_MT_file", "MAYA_MT_edit", "MAYA_MT_create", "MAYA_MT_select", "MAYA_MT_modify",
                "MAYA_MT_display", "MAYA_MT_windows"]

PANEL_MENUS = ["MAYA_MT_panel_view", "MAYA_MT_panel_shading", "MAYA_MT_panel_lighting", "MAYA_MT_panel_show",
               "MAYA_MT_panel_renderer", "MAYA_MT_panel_panels"]


class MAYA_MT_workspaces(Menu):
    bl_label = "Workspaces"

    def draw(self, context):
        for ws in bpy.data.workspaces:
            o = self.layout.operator("wm.context_set_id", text=ws.name,
                                     icon='CHECKMARK' if ws == context.workspace else 'BLANK1')
            o.data_path, o.value = "window.workspace", ws.name


class MAYA_MT_blender_menus(Menu):
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
    """Maya main menu bar: menu set selector, common menus, menu set menus, Help."""
    wm = context.window_manager
    layout.prop(wm, "maya_menu_set", text="")
    for idname in COMMON_MENUS + MENU_SETS[wm.maya_menu_set][1] + ["MAYA_MT_help"]:
        layout.menu(idname)


def _call(layout, idname, icon, label, depress=False, **props):
    """Button that runs `idname` in the main 3D Viewport (the top bar has no viewport context)."""
    o = layout.operator("maya.call", text="", icon=icon, depress=depress)
    o.idname, o.props, o.label = idname, repr(props), label
    return o


def draw_status_line(layout, context):
    """Maya Status Line, left to right: file, selection mode and masks, snapping, symmetry,
    render, Hypershade, input box, sidebar buttons, workspace."""
    from maya_mode import _view3d_space
    ts = context.tool_settings
    space = _view3d_space(context)
    ob = context.active_object

    row = layout.row(align=True)
    row.operator("wm.read_homefile", text="", icon='FILE_NEW').app_template = ""
    row.operator("wm.open_mainfile", text="", icon='FILE_FOLDER')
    row.operator("wm.save_mainfile", text="", icon='FILE_TICK')

    # Selection mode: object / component.
    row = layout.row(align=True)
    _call(row, "object.mode_set", 'OBJECT_DATAMODE', "Select by Object", depress=context.mode == 'OBJECT',
          mode='OBJECT')
    _call(row, "object.mode_set", 'EDITMODE_HLT', "Select by Component", depress=context.mode == 'EDIT_MESH',
          mode='EDIT')
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

    # Symmetry (global, on the active mesh).
    if ob is not None and ob.type == 'MESH':
        layout.prop(ob.data, "use_mirror_x", text="", icon='MOD_MIRROR')

    # Render: render view, render current frame, IPR, render settings; Hypershade.
    row = layout.row(align=True)
    row.operator("render.view_show", text="", icon='IMAGE')
    row.operator("render.render", text="", icon='RENDER_STILL')
    _call(row, "wm.context_set_enum", 'SHADING_RENDERED', "IPR Render",
          data_path="space_data.shading.type", value='RENDERED')
    row.operator("maya.dock_tab", text="", icon='SCENE').tab = 'RENDER'
    row.operator("maya.open_editor", text="", icon='NODE_MATERIAL').ui_type = 'ShaderNodeTree'

    # Input box: rename the selected object.
    if ob is not None:
        sub = layout.row()
        sub.scale_x = 0.8
        sub.prop(ob, "name", text="", icon='GREASEPENCIL')

    # Sidebar buttons: Modeling Toolkit, Attribute Editor, Tool Settings, Channel Box / Layer Editor.
    row = layout.row(align=True)
    for tab, icon in (('MODELING_TOOLKIT', 'EDITMODE_HLT'), ('OBJECT', 'PROPERTIES'), ('TOOL', 'TOOL_SETTINGS'),
                      ('CHANNEL_BOX', 'ALIGN_JUSTIFY')):
        row.operator("maya.dock_tab", text="", icon=icon).tab = tab

    layout.separator()
    layout.label(text="Workspace:")
    layout.template_ID(context.window, "workspace", new="workspace.add", unlink="workspace.delete")


def draw_panel_toolbar(layout, context):
    """Maya panel toolbar: camera, grid, shading and display toggles under the panel menus."""
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


class VIEW3D_PT_maya_quick_layouts(Panel):
    """Maya Quick Layout buttons under the Tool Box"""
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
        col.operator("maya.open_editor", text="", icon='OUTLINER').ui_type = 'OUTLINER'


# Maya shelves: tab -> (idname, icon, props). Shown in the viewport's shelf row (tool header).
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
    ]),
    'POLY': ("Poly Modeling", [
        ("maya.add_primitive", 'MESH_UVSPHERE', {"kind": 'SPHERE'}),
        ("maya.add_primitive", 'MESH_CUBE', {"kind": 'CUBE'}),
        ("maya.add_primitive", 'MESH_CYLINDER', {"kind": 'CYLINDER'}),
        ("maya.add_primitive", 'MESH_CONE', {"kind": 'CONE'}),
        ("maya.add_primitive", 'MESH_TORUS', {"kind": 'TORUS'}),
        ("maya.add_primitive", 'MESH_PLANE', {"kind": 'PLANE'}),
        None,
        ("object.join", 'AUTOMERGE_ON', {}),
        ("maya.separate", 'MOD_EXPLODE', {}),
        ("maya.boolean", 'SELECT_EXTEND', {"operation": 'UNION'}),
        ("maya.boolean", 'SELECT_SUBTRACT', {"operation": 'DIFFERENCE'}),
        ("maya.boolean", 'SELECT_INTERSECT', {"operation": 'INTERSECT'}),
        ("object.subdivision_set", 'MOD_SUBSURF', {"level": 1, "relative": False}),
        ("object.modifier_add", 'MOD_MIRROR', {"type": 'MIRROR'}),
        None,
        ("view3d.edit_mesh_extrude_move_normal", 'FACESEL', {}),
        ("mesh.bridge_edge_loops", 'MOD_LATTICE', {}),
        ("mesh.bevel", 'MOD_BEVEL', {}),
        ("mesh.loopcut_slide", 'MOD_EDGESPLIT', {}),
        ("mesh.knife_tool", 'MOD_SIMPLEDEFORM', {}),
        ("maya.fill_hole", 'SNAP_FACE', {}),
        None,
        ("object.origin_set", 'PIVOT_BOUNDBOX', {"type": 'ORIGIN_GEOMETRY'}),
        ("object.transform_apply", 'FREEZE', {"location": True, "rotation": True, "scale": True}),
        ("object.convert", 'TRASH', {"target": 'MESH'}),
    ]),
    'SCULPT': ("Sculpting", [
        ("object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'}),
        ("object.mode_set", 'OBJECT_DATAMODE', {"mode": 'OBJECT'}),
        None,
        ("object.modifier_add", 'MOD_MULTIRES', {"type": 'MULTIRES'}),
        ("object.voxel_remesh", 'MOD_REMESH', {}),
    ]),
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
    ]),
    'ANIMATION': ("Animation", [
        ("anim.keyframe_insert", 'KEY_HLT', {}),
        ("anim.keyframe_insert_by_name", 'CON_LOCLIKE', {"type": 'Location'}),
        ("anim.keyframe_insert_by_name", 'CON_ROTLIKE', {"type": 'Rotation'}),
        ("anim.keyframe_insert_by_name", 'CON_SIZELIKE', {"type": 'Scaling'}),
        ("anim.keyframe_delete_v3d", 'KEY_DEHLT', {}),
        None,
        ("screen.animation_play", 'PLAY', {}),
        ("maya.open_editor", 'GRAPH', {"ui_type": 'FCURVES'}),
        ("maya.open_editor", 'ACTION', {"ui_type": 'DOPESHEET'}),
        ("object.paths_calculate", 'ANIM_DATA', {}),
    ]),
    'RENDERING': ("Rendering", [
        ("object.camera_add", 'CAMERA_DATA', {}),
        ("object.light_add", 'LIGHT_POINT', {"type": 'POINT'}),
        ("object.light_add", 'LIGHT_SPOT', {"type": 'SPOT'}),
        ("object.light_add", 'LIGHT_AREA', {"type": 'AREA'}),
        ("object.light_add", 'LIGHT_SUN', {"type": 'SUN'}),
        None,
        ("maya.assign_material", 'MATERIAL', {}),
        ("maya.open_editor", 'NODE_MATERIAL', {"ui_type": 'ShaderNodeTree'}),
        None,
        ("render.render", 'RENDER_STILL', {}),
        ("render.render", 'RENDER_ANIMATION', {"animation": True}),
    ]),
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
    ]),
}


def draw_shelf(layout, context):
    """Maya shelf: tab strip plus the active shelf's buttons."""
    wm = context.window_manager
    layout.prop(wm, "maya_shelf", expand=True)
    layout.separator()
    row = layout.row(align=True)
    for item in SHELVES[wm.maya_shelf][1]:
        if item is None:
            row.separator()
            continue
        idname, icon, props = item
        o = row.operator(idname, text="", icon=icon)
        for k, v in props.items():
            setattr(o, k, v)


def draw_panel_menus(layout, context):
    for idname in PANEL_MENUS:
        layout.menu(idname)
    if context.mode in {'OBJECT', 'EDIT_MESH'}:
        layout.menu("MAYA_MT_blender_menus", text="", icon='COLLAPSEMENU')
    layout.separator()
    draw_panel_toolbar(layout, context)


classes = (
    *(_make_menu(idname, label, entries) for idname, (label, entries) in MENUS.items()),
    MAYA_MT_workspaces,
    MAYA_MT_blender_menus,
    VIEW3D_PT_maya_quick_layouts,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.maya_menu_set = bpy.props.EnumProperty(
        name="Menu Set", description="Maya menu set: which menus the main menu bar shows",
        items=[(k, label, "") for k, (label, _) in MENU_SETS.items()])
    wm.maya_shelf = bpy.props.EnumProperty(
        name="Shelf", description="Maya shelf tab",
        items=[(k, label, "") for k, (label, _) in SHELVES.items()], default='POLY')


def unregister():
    del bpy.types.WindowManager.maya_shelf
    del bpy.types.WindowManager.maya_menu_set
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
