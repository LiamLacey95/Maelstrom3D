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
        ("REMOVE", {"type": 'SPACE', "value": 'PRESS'}, None),
    ],
    "3D View": [
        _kmi("screen.region_quadview", 'SPACE'),
        _shading('FOUR', 'WIREFRAME'),
        _shading('FIVE', 'SOLID'),
        _shading('SIX', 'MATERIAL'),
        _shading('SEVEN', 'RENDERED'),
        _kmi("ed.undo", 'Z', repeat=True),
        _kmi("ed.redo", 'Z', shift=True, repeat=True),
        _kmi("wm.context_toggle", 'A', props={"data_path": "space_data.show_region_ui"}, ctrl=True),
        _kmi("view3d.localview", 'ONE', ctrl=True),
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
        _kmi("wm.context_toggle", 'D', props={"data_path": "tool_settings.use_transform_data_origin"}),
        _kmi("wm.context_toggle", 'D', 'RELEASE', props={"data_path": "tool_settings.use_transform_data_origin"}),
        _kmi("wm.context_toggle", 'INSERT', props={"data_path": "tool_settings.use_transform_data_origin"}),
        ("REMOVE", {"type": 'A', "value": 'PRESS', "ctrl": True}, None),
    ],
    "Mesh": [
        _pie("MAYA_MT_marking_menu", 'RIGHTMOUSE'),
        _pie("MAYA_MT_poly_tools", 'RIGHTMOUSE', shift=True),
        _kmi("object.editmode_toggle", 'F8'),
        *(_kmi("mesh.select_mode", k, props={"type": m}) for k, m in _SUBMODE),
        _smooth('ONE', 'OFF'), _smooth('TWO', 'CAGE'), _smooth('THREE', 'SMOOTH'),
        ("REMOVE", {"type": 'A', "value": 'PRESS', "ctrl": True}, None),
    ],
}

_MODS = ("shift", "ctrl", "alt", "oskey", "any")


def _key(args):
    return (args["type"], args["value"], *(bool(args.get(m)) for m in _MODS))


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

    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        keyconfig_data = keyconfig_data_oskey_from_ctrl_for_macos(keyconfig_data)

    keyconfig_init_from_data(kc, keyconfig_data)


if __name__ == "__main__":
    load()
