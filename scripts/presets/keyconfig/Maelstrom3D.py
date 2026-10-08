# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Autodesk Maya style key-map: Industry Compatible plus Maya-specific hotkeys.

import os
import bpy

DIRNAME, FILENAME = os.path.split(__file__)
IDNAME = os.path.splitext(FILENAME)[0]

industry_compatible = bpy.utils.execfile(os.path.join(DIRNAME, "keymap_data", "industry_compatible_data.py"))


def _kmi(idname, type, value='PRESS', props=None, **mods):
    return (idname, {"type": type, "value": value, **mods}, {"properties": list(props.items())} if props else None)


def _shading(type, shading):
    return _kmi("wm.context_set_enum", type, props={"data_path": "space_data.shading.type", "value": shading})


def _pie(name, type, **mods):
    return _kmi("wm.call_menu_pie", type, props={"name": name}, **mods)


def _mm(type, menu, tool="", command="", menu_mmb="", **mods):
    """Tap: tool / command. Hold the key + left (or middle) click: marking menu."""
    return _kmi("m3d.key_marking_menu", type,
                props={"menu": menu, "menu_mmb": menu_mmb, "tool": tool, "command": command}, **mods)


_QWER_MM = (
    _mm('Q', "M3D_MT_select_mm", tool="builtin.select_box"),
    _mm('W', "M3D_MT_move_mm", tool="builtin.move"),
    _mm('E', "M3D_MT_rotate_mm", tool="builtin.rotate"),
    _mm('R', "M3D_MT_scale_mm", tool="builtin.scale"),
)
_UNIVERSAL = _kmi("wm.tool_set_by_id", 'T', props={"name": "builtin.transform"}, ctrl=True)
_PICKWALK = tuple(_kmi("m3d.pickwalk", k + '_ARROW', props={"direction": k}) for k in ('UP', 'DOWN', 'LEFT', 'RIGHT'))
_KEYS = (
    _mm('S', "M3D_MT_keyframe_mm", menu_mmb="M3D_MT_tangent_mm", shift=True),
    _kmi("m3d.hide_selection", 'H', ctrl=True),
    _kmi("m3d.show_hidden", 'H', props={"which": 'LAST'}, ctrl=True, shift=True),
    _kmi("m3d.show_hidden", 'H', props={"which": 'SELECTED'}, shift=True),
    _kmi("anim.keyframe_insert_by_name", 'W', props={"type": 'Location'}, ctrl=True, shift=True),
    _kmi("anim.keyframe_insert_by_name", 'E', props={"type": 'Rotation'}, ctrl=True, shift=True),
    _kmi("anim.keyframe_insert_by_name", 'R', props={"type": 'Scaling'}, ctrl=True, shift=True),
    _kmi("anim.keyframe_insert", 'I', alt=True),
)


def _smooth(type, level):
    return _kmi("m3d.smooth_preview", type, props={"level": level})


# Workspace kind -> key (F1-F7); mirrors KINDS in m3d_workspace.py (test_m3d.py checks it).
WORKSPACE_KEYS = (('MODEL', 'F1'), ('SCULPT', 'F2'), ('UV', 'F3'), ('TEXTURE', 'F4'), ('RIG', 'F5'), ('ANIM', 'F6'),
                  ('RENDER', 'F7'))

_SUBMODE = (('F9', 'VERT'), ('F10', 'EDGE'), ('F11', 'FACE'))

# Keymap name -> items. Each item replaces any existing item on the same key + modifiers.
OVERRIDES = {
    "Frames": [
        _kmi("screen.animation_play", 'V', alt=True),
        _kmi("screen.frame_jump", 'V', props={"end": False}, alt=True, shift=True),
        _kmi("screen.frame_offset", 'COMMA', props={"delta": -1}, alt=True, repeat=True),
        _kmi("screen.frame_offset", 'PERIOD', props={"delta": 1}, alt=True, repeat=True),
        _kmi("screen.keyframe_jump", 'COMMA', props={"next": False}, repeat=True),
        _kmi("screen.keyframe_jump", 'PERIOD', props={"next": True}, repeat=True),
        ("REMOVE", {"type": 'SPACE', "value": 'PRESS'}, None),
    ],
    "3D View": [
        _kmi("m3d.space_hotbox", 'SPACE'),
        _kmi("screen.screen_full_area", 'SPACE', props={"use_hide_panels": True}, ctrl=True),
        _kmi("view3d.localview", 'L', shift=True),
        _kmi("view3d.view_selected", 'F', props={"use_all_regions": True}, shift=True),
        _mm('A', "M3D_MT_io_mm", command="view3d.view_all"),
        _mm('H', "M3D_MT_menu_set_mm"),
        _pie("M3D_MT_transform_mm", 'RIGHTMOUSE', ctrl=True, shift=True),
        _kmi("m3d.view_history", 'LEFT_BRACKET', props={"step": -1}),
        _kmi("m3d.view_history", 'RIGHT_BRACKET', props={"step": 1}),
        *(_kmi("m3d.nudge", k + '_ARROW', props={"direction": k}, alt=True, repeat=True)
          for k in ('UP', 'DOWN', 'LEFT', 'RIGHT')),
        _kmi("m3d.last_tool", 'Y'),
        _kmi("screen.repeat_last", 'G', shift=True),
        _kmi("m3d.cycle_background", 'B', alt=True),
        _kmi("wm.context_toggle", 'ONE', props={"data_path": "space_data.show_object_viewport_curve"}, alt=True),
        _kmi("wm.context_toggle", 'TWO', props={"data_path": "space_data.show_object_viewport_mesh"}, alt=True),
        _kmi("wm.context_toggle", 'FOUR', props={"data_path": "space_data.show_object_viewport_empty"}, alt=True),
        _kmi("wm.context_toggle_enum", 'FIVE', props={"data_path": "space_data.shading.type",
                                                       "value_1": 'WIREFRAME', "value_2": 'SOLID'}, alt=True),
        _kmi("m3d.snap_hold", 'J', props={"element": 'INCREMENT', "enable": True}),
        _kmi("m3d.snap_hold", 'J', 'RELEASE', props={"element": 'INCREMENT', "enable": False}),
        _kmi("wm.context_scale_int", 'EQUAL', props={"data_path": "preferences.view.gizmo_size", "value": 1.15}, repeat=True),
        _kmi("wm.context_scale_int", 'MINUS', props={"data_path": "preferences.view.gizmo_size", "value": 0.87}, repeat=True),
        _kmi("wm.context_toggle", 'M', props={"data_path": "space_data.show_region_header"}, shift=True),
        _kmi("wm.context_toggle", 'M', props={"data_path": "space_data.show_region_tool_header"}, ctrl=True, shift=True),
        # F1-F7 switch workspaces (Window keymap), not views.
        *(("REMOVE", {"type": k, "value": 'PRESS'}, None) for k in ('F1', 'F2', 'F3', 'F4', 'F5')),
        _shading('FOUR', 'WIREFRAME'),
        _shading('FIVE', 'SOLID'),
        _shading('SIX', 'MATERIAL'),
        _shading('SEVEN', 'RENDERED'),
        _kmi("ed.undo", 'Z', repeat=True),
        _kmi("ed.redo", 'Z', shift=True, repeat=True),
        _kmi("m3d.dock_tab", 'A', props={"toggle": True}, ctrl=True),
        _kmi("view3d.localview", 'ONE', ctrl=True),
        # Hold X / C / V to snap to grid / curve / point.
        *(_kmi("m3d.snap_hold", k, v, props={"element": e, "enable": v == 'PRESS'})
          for k, e in (('X', 'GRID'), ('C', 'EDGE'), ('V', 'VERTEX')) for v in ('PRESS', 'RELEASE')),
        # , and . step between keys (Frames keymap), so drop the pivot / orientation pies.
        ("REMOVE", {"type": 'COMMA', "value": 'PRESS'}, None),
        ("REMOVE", {"type": 'PERIOD', "value": 'PRESS'}, None),
    ],
    # Shift+1 ... Shift+7 pick a brush (the names are m3d_sculpt.BRUSH_KEYS; test_m3d.py checks them).
    "Sculpt": [
        *(_kmi("brush.asset_activate", k, props={
            "asset_library_type": 'ESSENTIALS',
            "relative_asset_identifier": "brushes/essentials_brushes-mesh_sculpt.blend/Brush/" + name}, shift=True)
          for k, name in zip(('ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN'), (
              "Draw", "Clay Strips", "Smooth", "Grab", "Inflate/Deflate", "Pinch/Magnify", "Crease Sharp"))),
    ],
    "Window": [
        # F1-F7: task workspaces (kinds in m3d_workspace.py). The menu set dropdown still offers every set.
        *(_kmi("m3d.workspace", k, props={"kind": kind}) for kind, k in WORKSPACE_KEYS),
        _kmi("wm.link", 'R', ctrl=True),
        _kmi("ed.redo", 'Y', ctrl=True, repeat=True),
        _kmi("screen.workspace_cycle", 'LEFT_BRACKET', props={"direction": 'PREV'}, shift=True),
        _kmi("screen.workspace_cycle", 'RIGHT_BRACKET', props={"direction": 'NEXT'}, shift=True),
    ],
    # Shift+drag on the move manipulator extrudes (components only; objects keep box selection).
    "Generic Gizmo Drag": [
        _kmi("m3d.gizmo_shift_drag", 'LEFTMOUSE', 'CLICK_DRAG', shift=True),
        _kmi("m3d.gizmo_slide", 'LEFTMOUSE', 'CLICK_DRAG', ctrl=True, shift=True),
    ],
    "Generic Gizmo Maybe Drag": [
        _kmi("m3d.gizmo_shift_drag", 'LEFTMOUSE', 'CLICK_DRAG', shift=True),
        _kmi("m3d.gizmo_slide", 'LEFTMOUSE', 'CLICK_DRAG', ctrl=True, shift=True),
    ],
    "Image": [
        *(("REMOVE", {"type": k, "value": 'PRESS'}, None) for k in ('F1', 'F2', 'F3', 'F4')),  # Zoom ratios.
        _kmi("ed.undo", 'Z', repeat=True),
        _kmi("ed.redo", 'Z', shift=True, repeat=True),
    ],
    "UV Editor": [
        _pie("M3D_MT_uv_marking_menu", 'RIGHTMOUSE'),
        _pie("M3D_MT_uv_tools", 'RIGHTMOUSE', shift=True),
        _kmi("object.editmode_toggle", 'F8'),
        *(_kmi("uv.select_mode", k, props={"type": m})
          for k, m in (('F9', 'VERTEX'), ('F10', 'EDGE'), ('F11', 'FACE'), ('F12', 'VERTEX'))),
        _kmi("uv.select_more", 'PERIOD', shift=True, repeat=True),
        _kmi("uv.select_less", 'COMMA', shift=True, repeat=True),
    ],
    "Object Non-modal": [
        ("REMOVE", {"type": 'FOUR', "value": 'PRESS'}, None),
        ("REMOVE", {"type": 'FIVE', "value": 'PRESS'}, None),
    ],
    "Object Mode": [
        _pie("M3D_MT_marking_menu", 'RIGHTMOUSE'),
        _kmi("object.editmode_toggle", 'F8'),
        *(_kmi("object.mode_set_with_submode", k, props={"mode": 'EDIT', "mesh_select_mode": {m}})
          for k, m in _SUBMODE),
        _smooth('ONE', 'OFF'), _smooth('TWO', 'CAGE'), _smooth('THREE', 'SMOOTH'),
        _kmi("m3d.group", 'G', ctrl=True),
        _kmi("m3d.pivot_hold", 'D'),
        _kmi("m3d.duplicate", 'D', ctrl=True),
        _kmi("m3d.duplicate", 'D', props={"with_transform": True}, shift=True),
        _kmi("object.duplicate_move_linked", 'D', ctrl=True, shift=True),
        _kmi("object.hide_view_set", 'H', props={"unselected": True}, alt=True),
        _kmi("m3d.smooth_levels", 'PAGE_UP', props={"delta": 1}),
        _kmi("m3d.smooth_levels", 'PAGE_DOWN', props={"delta": -1}),
        _kmi("wm.context_toggle", 'INSERT', props={"data_path": "tool_settings.use_transform_data_origin"}),
        _pie("M3D_MT_shift_rmb", 'RIGHTMOUSE', shift=True),
        *_QWER_MM, *_PICKWALK, *_KEYS, _UNIVERSAL,
        _kmi("m3d.cut", 'X', ctrl=True),
        ("REMOVE", {"type": 'F1', "value": 'PRESS'}, None),
        _kmi("m3d.soft_radius", 'B'),
        ("REMOVE", {"type": 'LEFT_BRACKET', "value": 'PRESS'}, None),
        ("REMOVE", {"type": 'RIGHT_BRACKET', "value": 'PRESS'}, None),
        ("REMOVE", {"type": 'A', "value": 'PRESS', "ctrl": True}, None),
        ("REMOVE", {"type": 'C', "value": 'PRESS'}, None),
    ],
    "Mesh": [
        _pie("M3D_MT_marking_menu", 'RIGHTMOUSE'),
        _pie("M3D_MT_shift_rmb", 'RIGHTMOUSE', shift=True),
        *_QWER_MM, _UNIVERSAL,
        _kmi("m3d.soft_radius", 'B'),
        _kmi("wm.tool_set_by_id", 'Q', props={"name": "builtin.poly_build"}, ctrl=True, shift=True),
        _kmi("mesh.knife_tool", 'X', ctrl=True, shift=True),
        _kmi("transform.shrink_fatten", 'MIDDLEMOUSE', 'CLICK_DRAG', ctrl=True),
        _kmi("object.editmode_toggle", 'F8'),
        *(_kmi("mesh.select_mode", k, props={"type": m}) for k, m in _SUBMODE),
        _smooth('ONE', 'OFF'), _smooth('TWO', 'CAGE'), _smooth('THREE', 'SMOOTH'),
        _pie("M3D_MT_convert_selection_pie", 'RIGHTMOUSE', ctrl=True),
        # Ctrl+E / Ctrl+B run Extrude / Bevel right away (Industry Compatible only switches tools).
        _kmi("view3d.edit_mesh_extrude_move_normal", 'E', ctrl=True),
        _kmi("mesh.bevel", 'B', props={"offset_type": 'PERCENT'}, ctrl=True),
        _kmi("m3d.delete_components", 'DEL'),
        _kmi("m3d.delete_components", 'BACK_SPACE'),
        _kmi("mesh.select_more", 'PERIOD', shift=True, repeat=True),
        _kmi("mesh.select_less", 'COMMA', shift=True, repeat=True),
        _kmi("mesh.reveal", 'H', ctrl=True, shift=True),
        _kmi("mesh.hide", 'H', props={"unselected": True}, alt=True),
        _kmi("m3d.pivot_hold", 'D'),
        *(_kmi("mesh.select_mode", k, props={"type": m, "use_expand": True}, ctrl=True) for k, m in _SUBMODE),
        _kmi("m3d.smooth_levels", 'PAGE_UP', props={"delta": 1}),
        _kmi("m3d.smooth_levels", 'PAGE_DOWN', props={"delta": -1}),
        _kmi("m3d.workspace", 'F12', props={"kind": 'UV'}),
        ("REMOVE", {"type": 'A', "value": 'PRESS', "ctrl": True}, None),
        ("REMOVE", {"type": 'C', "value": 'PRESS'}, None),
    ],
}

_MODS = ("shift", "ctrl", "alt", "oskey", "any")


def _key(args):
    return (args["type"], args["value"], *(bool(args.get(m)) for m in _MODS))


def selection_modifiers(keyconfig_data):
    """Selection: Shift toggles, Ctrl deselects, Ctrl+Shift adds (click and drag)."""
    drag_modes = {(True, False): 'XOR', (False, True): 'SUB', (True, True): 'ADD'}
    click_props = {(False, True): [("deselect", True)], (True, True): [("extend", True)]}
    for _km_name, _km_args, km_content in keyconfig_data:
        for i, (idname, args, data) in enumerate(km_content["items"]):
            mods = (bool(args.get("shift")), bool(args.get("ctrl")))
            if args.get("alt") or not any(mods):
                continue
            if idname in {"view3d.select_box", "view3d.select_lasso", "uv.select_box", "uv.select_lasso"} and data and                     any(k == "mode" for k, _ in data.get("properties", ())):
                mode = drag_modes[mods]
                if mode == 'XOR' and idname.startswith("uv."):
                    mode = 'ADD'  # UV box/lasso select has no toggle mode.
                props = [(k, v) for k, v in data["properties"] if k != "mode"] + [("mode", mode)]
                km_content["items"][i] = (idname, args, {**data, "properties": props})
            elif idname in {"view3d.select", "uv.select"} and args["type"] == 'LEFTMOUSE' and mods in click_props:
                km_content["items"][i] = (idname, args, {"properties": click_props[mods]})
    return keyconfig_data


def apply_overrides(keyconfig_data, overrides):
    for km_name, _km_args, km_content in keyconfig_data:
        new_items = overrides.get(km_name)
        if not new_items:
            continue
        taken = {_key(args) for _, args, _ in new_items}
        km_content["items"][:] = [it for it in km_content["items"] if _key(it[1]) not in taken]
        km_content["items"].extend(it for it in new_items if it[0] != "REMOVE")
    return keyconfig_data


def load():
    from sys import platform
    from bl_keymap_utils.io import keyconfig_init_from_data

    prefs = bpy.context.preferences

    kc = bpy.context.window_manager.keyconfigs.new(IDNAME)
    params = industry_compatible.Params(use_mouse_emulate_3_button=prefs.inputs.use_mouse_emulate_3_button)
    keyconfig_data = apply_overrides(industry_compatible.generate_keymaps(params), OVERRIDES)
    keyconfig_data = selection_modifiers(keyconfig_data)

    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        keyconfig_data = keyconfig_data_oskey_from_ctrl_for_macos(keyconfig_data)

    keyconfig_init_from_data(kc, keyconfig_data)


if __name__ == "__main__":
    load()
