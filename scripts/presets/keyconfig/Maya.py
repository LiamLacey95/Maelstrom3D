# SPDX-FileCopyrightText: 2026 MayaBlender
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


def _smooth(type, level):
    return _kmi("maya.smooth_preview", type, props={"level": level})


_SUBMODE = (('F9', 'VERT'), ('F10', 'EDGE'), ('F11', 'FACE'))

# Keymap name -> items. Each item replaces any existing item on the same key + modifiers.
MAYA_OVERRIDES = {
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
        _kmi("maya.space_hotbox", 'SPACE'),
        _kmi("screen.screen_full_area", 'SPACE', props={"use_hide_panels": True}, ctrl=True),
        _kmi("view3d.localview", 'L', shift=True),
        _kmi("maya.snap_hold", 'J', props={"element": 'INCREMENT', "enable": True}),
        _kmi("maya.snap_hold", 'J', 'RELEASE', props={"element": 'INCREMENT', "enable": False}),
        _kmi("wm.context_scale_int", 'EQUAL', props={"data_path": "preferences.view.gizmo_size", "value": 1.15}, repeat=True),
        _kmi("wm.context_scale_int", 'MINUS', props={"data_path": "preferences.view.gizmo_size", "value": 0.87}, repeat=True),
        _kmi("wm.context_toggle", 'M', props={"data_path": "space_data.show_region_header"}, shift=True),
        _kmi("wm.context_toggle", 'M', props={"data_path": "space_data.show_region_tool_header"}, ctrl=True, shift=True),
        # F2-F5 switch Maya menu sets (Window keymap), not views.
        *(("REMOVE", {"type": k, "value": 'PRESS'}, None) for k in ('F2', 'F3', 'F4', 'F5')),
        _shading('FOUR', 'WIREFRAME'),
        _shading('FIVE', 'SOLID'),
        _shading('SIX', 'MATERIAL'),
        _shading('SEVEN', 'RENDERED'),
        _kmi("ed.undo", 'Z', repeat=True),
        _kmi("ed.redo", 'Z', shift=True, repeat=True),
        _kmi("maya.dock_tab", 'A', props={"toggle": True}, ctrl=True),
        _kmi("view3d.localview", 'ONE', ctrl=True),
        # Hold X / C / V to snap to grid / curve / point.
        *(_kmi("maya.snap_hold", k, v, props={"element": e, "enable": v == 'PRESS'})
          for k, e in (('X', 'GRID'), ('C', 'EDGE'), ('V', 'VERTEX')) for v in ('PRESS', 'RELEASE')),
        # , and . step between keys (Frames keymap), so drop the pivot / orientation pies.
        ("REMOVE", {"type": 'COMMA', "value": 'PRESS'}, None),
        ("REMOVE", {"type": 'PERIOD', "value": 'PRESS'}, None),
    ],
    "Window": [
        *(_kmi("wm.context_set_enum", k, props={"data_path": "window_manager.maya_menu_set", "value": v})
          for k, v in (('F2', 'ANIMATION'), ('F3', 'MODELING'), ('F4', 'RIGGING'), ('F5', 'FX'), ('F6', 'RENDERING'))),
        _kmi("wm.link", 'R', ctrl=True),
    ],
    # Shift+drag on the move manipulator extrudes (components only; objects keep box selection).
    "Generic Gizmo Drag": [_kmi("maya.gizmo_extrude", 'LEFTMOUSE', 'CLICK_DRAG', shift=True)],
    "Generic Gizmo Maybe Drag": [_kmi("maya.gizmo_extrude", 'LEFTMOUSE', 'CLICK_DRAG', shift=True)],
    "Image": [
        _kmi("ed.undo", 'Z', repeat=True),
        _kmi("ed.redo", 'Z', shift=True, repeat=True),
    ],
    "UV Editor": [
        _pie("MAYA_MT_uv_marking_menu", 'RIGHTMOUSE'),
        _pie("MAYA_MT_uv_tools", 'RIGHTMOUSE', shift=True),
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
        _pie("MAYA_MT_marking_menu", 'RIGHTMOUSE'),
        _kmi("object.editmode_toggle", 'F8'),
        *(_kmi("object.mode_set_with_submode", k, props={"mode": 'EDIT', "mesh_select_mode": {m}})
          for k, m in _SUBMODE),
        _smooth('ONE', 'OFF'), _smooth('TWO', 'CAGE'), _smooth('THREE', 'SMOOTH'),
        _kmi("maya.group", 'G', ctrl=True),
        _kmi("maya.pivot_hold", 'D'),
        _kmi("maya.duplicate", 'D', ctrl=True),
        _kmi("maya.duplicate", 'D', props={"with_transform": True}, shift=True),
        _kmi("object.duplicate_move_linked", 'D', ctrl=True, shift=True),
        _kmi("object.hide_view_set", 'H', props={"unselected": True}, alt=True),
        _kmi("maya.smooth_levels", 'PAGE_UP', props={"delta": 1}),
        _kmi("maya.smooth_levels", 'PAGE_DOWN', props={"delta": -1}),
        _kmi("wm.context_toggle", 'INSERT', props={"data_path": "tool_settings.use_transform_data_origin"}),
        _pie("MAYA_MT_create_pie", 'RIGHTMOUSE', shift=True),
        # Pickwalk up / down the hierarchy.
        _kmi("object.select_hierarchy", 'UP_ARROW', props={"direction": 'PARENT', "extend": False}),
        _kmi("object.select_hierarchy", 'DOWN_ARROW', props={"direction": 'CHILD', "extend": False}),
        _kmi("object.hide_view_clear", 'H', ctrl=True, shift=True),
        ("REMOVE", {"type": 'A', "value": 'PRESS', "ctrl": True}, None),
        ("REMOVE", {"type": 'C', "value": 'PRESS'}, None),
    ],
    "Mesh": [
        _pie("MAYA_MT_marking_menu", 'RIGHTMOUSE'),
        _pie("MAYA_MT_poly_tools", 'RIGHTMOUSE', shift=True),
        _kmi("object.editmode_toggle", 'F8'),
        *(_kmi("mesh.select_mode", k, props={"type": m}) for k, m in _SUBMODE),
        _smooth('ONE', 'OFF'), _smooth('TWO', 'CAGE'), _smooth('THREE', 'SMOOTH'),
        _pie("MAYA_MT_convert_selection_pie", 'RIGHTMOUSE', ctrl=True),
        # Ctrl+E / Ctrl+B run Extrude / Bevel right away (Industry Compatible only switches tools).
        _kmi("view3d.edit_mesh_extrude_move_normal", 'E', ctrl=True),
        _kmi("mesh.bevel", 'B', props={"offset_type": 'PERCENT'}, ctrl=True),
        _kmi("maya.delete_components", 'DEL'),
        _kmi("maya.delete_components", 'BACK_SPACE'),
        _kmi("mesh.select_more", 'PERIOD', shift=True, repeat=True),
        _kmi("mesh.select_less", 'COMMA', shift=True, repeat=True),
        _kmi("mesh.reveal", 'H', ctrl=True, shift=True),
        _kmi("mesh.hide", 'H', props={"unselected": True}, alt=True),
        _kmi("maya.pivot_hold", 'D'),
        *(_kmi("mesh.select_mode", k, props={"type": m, "use_expand": True}, ctrl=True) for k, m in _SUBMODE),
        _kmi("maya.smooth_levels", 'PAGE_UP', props={"delta": 1}),
        _kmi("maya.smooth_levels", 'PAGE_DOWN', props={"delta": -1}),
        _kmi("wm.context_set_id", 'F12', props={"data_path": "window.workspace", "value": "UV Editing"}),
        ("REMOVE", {"type": 'A', "value": 'PRESS', "ctrl": True}, None),
        ("REMOVE", {"type": 'C', "value": 'PRESS'}, None),
    ],
}

_MODS = ("shift", "ctrl", "alt", "oskey", "any")


def _key(args):
    return (args["type"], args["value"], *(bool(args.get(m)) for m in _MODS))


def maya_selection_modifiers(keyconfig_data):
    """Maya selection: Shift toggles, Ctrl deselects, Ctrl+Shift adds (click and drag)."""
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
    keyconfig_data = apply_overrides(industry_compatible.generate_keymaps(params), MAYA_OVERRIDES)
    keyconfig_data = maya_selection_modifiers(keyconfig_data)

    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        keyconfig_data = keyconfig_data_oskey_from_ctrl_for_macos(keyconfig_data)

    keyconfig_init_from_data(kc, keyconfig_data)


if __name__ == "__main__":
    load()
