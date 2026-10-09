# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Edit the interface (Workspace Settings > "Click to Edit"): while on,
- shelf buttons are dragged to reorder the Custom shelf, onto the Custom tab to copy a button there, or off the
  shelf to remove it (the Sculpt tray's Custom panel has arrows instead),
- Ctrl+Alt+click any button, then press a key: the key becomes the button's shortcut (user keymap),
- dock page panels get a "move to tab" menu and a hide eye in their headers, and the dock header can make, rename
  and delete user tabs (the data is in m3d_user.py: the dock section of m3d_user.json).

Python can't make widgets draggable or ask for the button under the cursor, so a window modal operator (it sees events
before the buttons) does the drag and swallows the Ctrl+Alt click, the shelf draws itself in fixed-width cells whose
rectangles it records (`_geom`), and keymap items in "User Interface" (where the hovered button is the active one) ask
Blender's own "Copy Python Command" / "Copy Data Path" for the button under the cursor while Ctrl+Alt is held.
Edit mode is a module flag: global, off at start, never saved in a file.
"""

import ast
import re

import bpy
from bpy.types import Operator, Panel

# -----------------------------------------------------------------------------
# State

_state = {"on": False, "running": False}
_geom = {}                              # "shelf" / "tabs": where the top bar rows drew their buttons last
_drag = {"src": None, "target": None}   # shelf drag in progress: src ("C", i) / ("B", key, i), target ("slot", n) / "tab" / "out"
_hover = None                           # the button under the cursor the last time Ctrl+Alt was down
_capture = None                         # hotkey assignment waiting for a key / for Enter on a conflict
_prompt = {"text": ""}


def editing():
    return _state["on"]


def set_editing(on):
    _state["on"] = bool(on)
    if not on:
        _drag.update(src=None, target=None)
        _end_capture()
    refresh_ui()


def refresh_ui():
    """Redraw everything, the global top bar rows included (a property update with a scene notifier does it:
    Python can't tag those regions)."""
    ts = bpy.context.scene.tool_settings
    ts.use_snap = ts.use_snap
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            area.tag_redraw()


# -----------------------------------------------------------------------------
# Shelf geometry: the shelf draws fixed-width cells in edit mode, so a mouse position maps to a button

SHELF_X0 = 0.2            # left edge of the first cell, in units (a unit is a button's width: U.widget_unit)
SHELF_SEPARATOR = 0.2     # width of a gap between button groups, in units
ICON_CELL, CALL_CELL = 2.0, 4.0
TABS_CUSTOM_CELL = 8.0    # the Custom tab in edit mode: a cell at the right end of the tab row
TABS_RIGHT_MARGIN = 0.1


def unit_px(context):
    """U.widget_unit: the width of one layout unit in pixels (20 at the default scale)."""
    system = context.preferences.system
    return round(18 * system.dpi / 72) + 2 * system.pixel_size


def begin_shelf(context, key, kind):
    """Start recording the cells of the shelf being drawn (the shelf region is the one drawing)."""
    r = context.region
    unit = unit_px(context)
    rec = {"rect": (r.x, r.y, r.width, r.height), "unit": unit, "x": SHELF_X0 * unit, "cells": [], "key": key,
           "kind": kind, "ws": context.workspace.name}
    _geom["shelf"] = rec
    return rec


def add_cell(rec, row, units, ref=None, icon=False):
    """A sub-row of fixed width `units` in `row`; `ref` says what it holds (None: nothing to grab). An icon-only
    button doesn't stretch, so `icon` widens it with scale_x."""
    sub = row.row(align=True)
    sub.ui_units_x = units
    sub.scale_y = 1.5
    if icon:
        sub.scale_x = units
    rec["cells"].append((rec["x"], units * rec["unit"], ref))
    rec["x"] += units * rec["unit"]
    return sub


def add_gap(rec, row):
    row.separator(factor=0.5)   # as wide as SHELF_SEPARATOR (an empty cell would take no room)
    rec["x"] += SHELF_SEPARATOR * rec["unit"]


def text_units(rec, text):
    """Cell width for a button with text (the text may be clipped when the estimate is short)."""
    from m3d_workspace import text_width
    return max(ICON_CELL, text_width(text, 1.0) / rec["unit"] + 0.3)


def begin_tabs(context, kind):
    r = context.region
    unit = unit_px(context)
    width = TABS_CUSTOM_CELL * unit
    left = r.width - (TABS_RIGHT_MARGIN * unit) - width
    _geom["tabs"] = {"rect": (r.x, r.y, r.width, r.height), "custom": (left, r.width), "kind": kind,
                     "ws": context.workspace.name, "width": TABS_CUSTOM_CELL}


def _inside(rect, x, y):
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def _fresh(rec, context):
    """The record is for what the window shows now (the shelf row of another workspace may be gone)."""
    ws = context.workspace
    return rec is not None and ws is not None and rec["ws"] == ws.name and ws.m3d_show_shelf


def shelf_hit(rec, x, y):
    """The `ref` of the shelf cell under window position (x, y), None when it is not on a button."""
    if rec is None or not _inside(rec["rect"], x, y):
        return None
    rel = x - rec["rect"][0]
    return next((ref for x0, w, ref in rec["cells"] if ref is not None and x0 <= rel < x0 + w), None)


def drop_slot(rec, x, count):
    """Where a Custom button dropped at window x goes: the index of the first Custom button whose middle is right of x
    (`count` when none is)."""
    rel = x - rec["rect"][0]
    mids = [x0 + w / 2 for x0, w, ref in rec["cells"] if ref is not None and ref[0] == "C"]
    return sum(1 for m in mids if m < rel) if count else 0


def on_custom_tab(rec, x, y):
    if rec is None or not _inside(rec["rect"], x, y):
        return False
    left, right = rec["custom"]
    return left <= x - rec["rect"][0] < right


def target_at(x, y, context, src):
    """What a drag released (or moving) at (x, y) would do: ("slot", n), "tab" or "out"."""
    shelf, tabs = _geom.get("shelf"), _geom.get("tabs")
    if tabs is not None and _fresh(tabs, context) and on_custom_tab(tabs, x, y):
        return "tab"
    if shelf is not None and _fresh(shelf, context) and _inside(shelf["rect"], x, y):
        if src[0] == "C":
            from m3d_user import shelf_items
            return ("slot", drop_slot(shelf, x, len(shelf_items(shelf["kind"]))))
        return "here"
    return "out"


# -----------------------------------------------------------------------------
# Shelf edits (the data side of the drag)

def reorder_custom(kind, index, slot):
    """Move Custom item `index` to the place before the item that is at `slot` now. True when the order changed."""
    from m3d_user import save, shelf_items
    items = shelf_items(kind)
    if not 0 <= index < len(items) or not 0 <= slot <= len(items):
        return False
    dst = slot - 1 if slot > index else slot
    if dst == index:
        return False
    items.insert(dst, items.pop(index))
    save()
    return True


def remove_custom(kind, index):
    from m3d_user import save, shelf_items
    items = shelf_items(kind)
    if not 0 <= index < len(items):
        return False
    del items[index]
    save()
    return True


def builtin_item(key, index):
    """Custom shelf item for button `index` of built-in shelf `key` (None for gaps and widgets that aren't buttons)."""
    from m3d_ui import SHELVES
    from m3d_user import _item_ok, _json_value, _op_exists
    entries = SHELVES[key][1] if key in SHELVES else []
    if not 0 <= index < len(entries) or entries[index] is None or callable(entries[index]):
        return None
    idname, icon, props, *text = entries[index]
    if not _op_exists(idname):
        return None
    mod, _, name = idname.partition(".")
    label = text[0] if text else props.get("label") if idname in {"m3d.tool", "m3d.call"} else None
    item = {"idname": idname, "props": {k: _json_value(v) for k, v in props.items() if _json_value(v) is not None},
            "icon": icon if icon != 'NONE' else "",
            "label": label or getattr(getattr(bpy.ops, mod), name).get_rna_type().name}
    return item if _item_ok(item) else None


def copy_to_custom(kind, key, index):
    from m3d_user import save, shelf_items
    item = builtin_item(key, index)
    if item is None:
        return False
    shelf_items(kind).append(item)
    save()
    return True


def finish_drag(kind, src, target):
    """Apply a drop: returns what happened ('reorder', 'remove', 'copy' or None)."""
    if src[0] == "C":
        if target == "out":
            return "remove" if remove_custom(kind, src[1]) else None
        if isinstance(target, tuple):
            return "reorder" if reorder_custom(kind, src[1], target[1]) else None
        return None
    if target == "tab":
        return "copy" if copy_to_custom(kind, src[1], src[2]) else None
    return None


# -----------------------------------------------------------------------------
# Hotkeys: the button under the cursor and the user keymap

KEYMAP_BY_AREA = {'VIEW_3D': "3D View", 'IMAGE_EDITOR': "Image", 'NODE_EDITOR': "Node Editor",
                  'DOPESHEET_EDITOR': "Dopesheet", 'GRAPH_EDITOR': "Graph Editor", 'OUTLINER': "Outliner",
                  'SEQUENCE_EDITOR': "Sequencer", 'TEXT_EDITOR': "Text", 'CLIP_EDITOR': "Clip",
                  'FILE_BROWSER': "File Browser"}
_SPACE_PATH = re.compile(r'^screens\["(?:[^"\\]|\\.)*"\]\.areas\[(\d+)\]\.spaces\[\d+\]\.(.+)$')
_SCREEN_PATH = re.compile(r'^screens\["((?:[^"\\]|\\.)*)"\]')


def parse_command(text):
    """('mod.name', {kwargs}) from "bpy.ops.mod.name(a=1, b='X')" (Blender's Copy Python Command), else None."""
    try:
        call = ast.parse(text.strip(), mode='eval').body
        if not isinstance(call, ast.Call) or call.args:
            return None
        parts = []
        node = call.func
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        parts.reverse()
        if not isinstance(node, ast.Name) or node.id != "bpy" or len(parts) != 3 or parts[0] != "ops":
            return None
        return "%s.%s" % (parts[1], parts[2]), {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    except (SyntaxError, ValueError, TypeError, AttributeError):
        return None


def _json_props(idname, props):
    """Properties from a Python command as stored data (the shelf's format)."""
    from m3d_user import _json_value
    return {k: v for k, v in ((k, _json_value(v)) for k, v in props.items()) if v is not None}


def _op_label(idname, props):
    """What the prompt calls a button: the operator's name and its enum choices ("Polygon Primitive: Sphere");
    m3d.call buttons are named after the command they run."""
    from m3d_user import _op_exists
    if idname in {"m3d.call", "m3d.tool"} and props.get("label"):
        return props["label"]
    if idname == "m3d.call" and props.get("idname"):
        try:
            return _op_label(props["idname"], ast.literal_eval(props.get("props", "{}")))
        except (ValueError, SyntaxError):
            return props["idname"]
    if not _op_exists(idname):
        return idname
    mod, _, name = idname.partition(".")
    rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
    extra = []
    for key, value in props.items():
        prop = rna.properties.get(key)
        try:
            if prop is not None and prop.type == 'ENUM' and not prop.is_enum_flag and isinstance(value, str):
                extra.append(prop.enum_items[value].name)
        except (KeyError, TypeError):
            pass
    return rna.name + (": " + ", ".join(extra) if extra else "")


def item_from_command(text, area_type):
    """Hotkey target for the command a button runs: {"idname", "props", "label", "keymap"} or None."""
    from m3d_user import _op_exists
    parsed = parse_command(text)
    if parsed is None or not _op_exists(parsed[0]):
        return None
    idname, props = parsed
    return {"idname": idname, "props": _json_props(idname, props), "label": _op_label(idname, props),
            "keymap": KEYMAP_BY_AREA.get(area_type, "Window")}


def item_from_path(text, area_type):
    """Hotkey target for a boolean property button (from Copy Data Path with the full path): toggles it with
    wm.context_toggle, the path given from the context the key is pressed in (scene, tool settings, the editor's space)."""
    text = text.strip()
    if not text.startswith("bpy.data."):
        return None
    path = text[len("bpy.data."):]
    owner_path, _, ident = path.rpartition(".")
    try:
        owner = bpy.data.path_resolve(owner_path) if owner_path else None
        prop = owner.bl_rna.properties[ident]
    except (ValueError, KeyError, AttributeError):
        return None
    if prop.type != 'BOOLEAN' or prop.is_readonly or prop.array_length:
        return None
    keymap = KEYMAP_BY_AREA.get(area_type, "Window")
    m = _SPACE_PATH.match(path)
    if m:
        screen = _SCREEN_PATH.match(path).group(1).replace('\\"', '"')
        area = bpy.data.screens[screen].areas[int(m.group(1))]
        keymap = KEYMAP_BY_AREA.get(area.type)
        if keymap is None:
            return None
        data_path = "space_data." + m.group(2)
    elif path.startswith("scenes["):
        rest = path.partition("].")[2]
        data_path = rest if rest.startswith("tool_settings.") else "scene." + rest
    else:
        return None
    return {"idname": "wm.context_toggle", "props": {"data_path": data_path}, "label": prop.name, "keymap": keymap}


def probe(context, event):
    """Look at the button under the cursor (the active button of the region keymap items run in) through Blender's
    copy operators, keeping the clipboard as it was. Sets `_hover`."""
    global _hover
    wm = context.window_manager
    old = wm.clipboard
    item = None
    area = context.area.type if context.area else ""
    try:
        wm.clipboard = ""
        for op, find in ((lambda: bpy.ops.ui.copy_python_command_button(), item_from_command),
                         (lambda: bpy.ops.ui.copy_data_path_button(full_path=True), item_from_path)):
            try:
                op()
            except RuntimeError:
                continue
            item = find(wm.clipboard, area)
            if item:
                break
            wm.clipboard = ""
    finally:
        wm.clipboard = old
    _hover = {"item": item, "pos": (event.mouse_x, event.mouse_y)} if item else None
    return _hover


def hover_at(x, y):
    """The probed button when the cursor is where it was probed (a stale probe is ignored)."""
    if _hover and abs(_hover["pos"][0] - x) <= 3 and abs(_hover["pos"][1] - y) <= 3:
        return _hover["item"]
    return None


MODIFIER_KEYS = {'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT', 'LEFT_SHIFT', 'RIGHT_SHIFT', 'OSKEY', 'CAPS_LOCK',
                 'APP', 'GRLESS'}
_NOT_KEYS = ('TIMER', 'NDOF', 'XR', 'WINDOW', 'ACTIONZONE', 'EYEDROP', 'TRACKPAD', 'TEXTINPUT', 'BUTTON', 'MOUSE',
             'INBETWEEN', 'CURSOR', 'NONE', 'ANY', 'EVT', 'PEN', 'ERASER', 'WHEEL', 'PRINT_SCREEN')


def is_key(event_type):
    return (event_type not in MODIFIER_KEYS and not event_type.endswith("MOUSE")
            and not event_type.startswith(_NOT_KEYS))


def key_label(spec):
    names = [n for n, on in (("Ctrl", spec["ctrl"]), ("Alt", spec["alt"]), ("Shift", spec["shift"]),
                             ("Cmd", spec["oskey"])) if on]
    key = bpy.types.KeyMapItem.bl_rna.properties["type"].enum_items[spec["type"]].name
    return "+".join(names + [key])


def key_spec(event):
    return {"type": event.type, "shift": bool(event.shift), "ctrl": bool(event.ctrl), "alt": bool(event.alt),
            "oskey": bool(event.oskey)}


def _same_props(kmi, props):
    from m3d_user import _py_props
    try:
        want = _py_props(kmi.idname, props)
    except (AttributeError, KeyError):
        return False
    for key, value in want.items():
        have = getattr(kmi.properties, key, None)
        if isinstance(have, (str, bool, int, float, set)) or have is None:
            same = have == value
        else:
            same = tuple(have) == tuple(value)
        if not same:
            return False
    return True


def user_keymap(name):
    return bpy.context.window_manager.keyconfigs.user.keymaps.get(name)


def conflicts(item, spec):
    """Active items of the target keymap that use the same key and modifiers, other than the button's own:
    [(operator name, ...)]."""
    km = user_keymap(item["keymap"])
    out = []
    for kmi in km.keymap_items if km else ():
        if (kmi.active and kmi.type == spec["type"] and kmi.value in {'PRESS', 'ANY'} and kmi.key_modifier == 'NONE'
                and (kmi.any or (bool(kmi.shift), bool(kmi.ctrl), bool(kmi.alt), bool(kmi.oskey))
                    == (spec["shift"], spec["ctrl"], spec["alt"], spec["oskey"]))):
            if kmi.idname == item["idname"] and _same_props(kmi, item["props"]):
                continue
            out.append(kmi.name or kmi.idname)
    return out


def assign_key(item, spec):
    """Give the button's command the key in the user keymap: its existing item there is changed, else one is
    added (first, so it wins over a default that uses the same key). Returns the keymap item."""
    from m3d_user import _py_props
    km = user_keymap(item["keymap"])
    if km is None:
        return None
    kmi = next((k for k in km.keymap_items if k.idname == item["idname"] and _same_props(k, item["props"])
                and k.type not in {'NONE'} and k.value in {'PRESS', 'ANY'}), None)
    if kmi is None:
        kmi = km.keymap_items.new(item["idname"], spec["type"], 'PRESS', head=True)
        for key, value in _py_props(item["idname"], item["props"]).items():
            try:
                setattr(kmi.properties, key, value)
            except (TypeError, AttributeError):
                pass
    kmi.type, kmi.value, kmi.active = spec["type"], 'PRESS', True
    kmi.any, kmi.key_modifier = False, 'NONE'
    kmi.shift, kmi.ctrl, kmi.alt, kmi.oskey = (int(spec[k]) for k in ("shift", "ctrl", "alt", "oskey"))
    return kmi


# The prompt while waiting for a key: the status bar, and large text in the 3D Viewport.

_handle = None


def _draw_prompt():
    import blf
    text = _prompt["text"]
    if not text:
        return
    region = bpy.context.region
    scale = bpy.context.preferences.system.ui_scale
    blf.size(0, 20 * scale)
    w, h = blf.dimensions(0, text)
    blf.enable(0, blf.SHADOW)
    blf.shadow(0, 5, 0.0, 0.0, 0.0, 1.0)
    blf.color(0, 1.0, 0.85, 0.3, 1.0)
    blf.position(0, (region.width - w) / 2, region.height - 80 * scale - h, 0)
    blf.draw(0, text)
    blf.disable(0, blf.SHADOW)


def set_prompt(context, text):
    _prompt["text"] = text
    context.workspace.status_text_set(text or None)
    refresh_ui()


def _end_capture():
    global _capture
    if _capture is not None:
        _capture = None
        _prompt["text"] = ""
        for win in bpy.context.window_manager.windows:
            win.workspace.status_text_set(None)
            win.cursor_modal_restore()


def begin_capture(context, item):
    global _capture
    _capture = {"item": item, "state": "KEY", "spec": None}
    if context.window is not None:
        context.window.cursor_modal_set('CROSSHAIR')
    set_prompt(context, "Press a key for %s... Esc cancels" % item["label"])


def capture_event(context, event):
    """Handle an event while a hotkey assignment waits; returns the operator return set."""
    global _capture
    cap = _capture
    if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER'} or event.type in MODIFIER_KEYS:
        return {'PASS_THROUGH'} if event.type != 'TIMER' else {'RUNNING_MODAL'}
    if event.value != 'PRESS':
        return {'RUNNING_MODAL'}
    if event.type == 'ESC':
        _end_capture()
        refresh_ui()
        return {'RUNNING_MODAL'}
    if cap["state"] == 'KEY':
        if not is_key(event.type):
            return {'RUNNING_MODAL'}
        spec = key_spec(event)
        clash = conflicts(cap["item"], spec)
        if clash:
            cap["state"], cap["spec"] = 'CONFIRM', spec
            set_prompt(context, "%s is already used by %s. Enter assigns it anyway, Esc cancels" % (
                key_label(spec), ", ".join(dict.fromkeys(clash))))
            return {'RUNNING_MODAL'}
        finish_capture(context, cap["item"], spec)
    elif event.type in {'RET', 'NUMPAD_ENTER'}:
        finish_capture(context, cap["item"], cap["spec"])
    return {'RUNNING_MODAL'}


def finish_capture(context, item, spec):
    kmi = assign_key(item, spec)
    _end_capture()
    refresh_ui()
    if kmi is None:
        _report(context, 'WARNING', "No keymap \"%s\" to put the shortcut in" % item["keymap"])
    else:
        _report(context, 'INFO', "%s is now the shortcut of %s (%s keymap, see Preferences > Keymap)" % (
            key_label(spec), item["label"], item["keymap"]))


def _report(context, level, text):
    """Reports need an operator; the modal sets this when it runs."""
    op = _state.get("op")
    if op is not None:
        op.report({level}, text)
    else:
        print("m3d:", text)


# -----------------------------------------------------------------------------
# Operators

class M3D_OT_edit_mode(Operator):
    """Edit the interface: drag shelf buttons, Ctrl+Alt+click a button to give it a shortcut, move panels between tabs"""
    bl_idname = "m3d.edit_mode"
    bl_label = "Edit Interface"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        set_editing(not _state["on"])
        if _state["on"] and not _state["running"]:
            # The modal starts from a timer: this operator may run in a popover that closes under it.
            bpy.app.timers.register(_start_modal, first_interval=0.0)
        return {'FINISHED'}


def _start_modal():
    wm = bpy.context.window_manager
    if _state["on"] and not _state["running"] and wm.windows:
        with bpy.context.temp_override(window=wm.windows[0]):
            bpy.ops.m3d.edit_ui('INVOKE_DEFAULT')


class M3D_OT_edit_ui(Operator):
    """Window-wide event handler of the edit mode (started by Click to Edit)"""
    bl_idname = "m3d.edit_ui"
    bl_label = "Edit Interface Events"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        if _state["running"]:
            return {'CANCELLED'}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        self._swallow = False   # the matching release of a press this operator took
        wm.modal_handler_add(self)
        _state["running"], _state["op"] = True, self
        return {'RUNNING_MODAL'}

    def _stop(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        _state["running"], _state["op"] = False, None
        _end_capture()
        _drag.update(src=None, target=None)
        refresh_ui()
        return {'FINISHED'}

    def cancel(self, context):
        self._stop(context)

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:   # Stay alive: a failing event must not leave edit mode on with nothing listening.
            import traceback
            traceback.print_exc()
            _end_capture()
            _drag.update(src=None, target=None)
            return {'PASS_THROUGH'}

    def _modal(self, context, event):
        if not _state["on"]:
            return self._stop(context)
        if _capture is not None:
            if event.type == 'LEFTMOUSE':
                self._swallow = self._swallow and event.value != 'RELEASE'
                return {'RUNNING_MODAL'}
            return capture_event(context, event)
        if _drag["src"] is not None:
            return self._drag_event(context, event)
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self._swallow:
            self._swallow = False
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            x, y = event.mouse_x, event.mouse_y
            if event.ctrl and event.alt and not event.shift:
                item = hover_at(x, y)
                if item is not None:
                    self._swallow = True
                    begin_capture(context, item)
                    return {'RUNNING_MODAL'}
            elif not (event.ctrl or event.alt or event.shift):
                shelf = _geom.get("shelf")
                ref = shelf_hit(shelf, x, y) if _fresh(shelf, context) else None
                if ref is not None:
                    self._swallow = True
                    _drag.update(src=ref, target=None, kind=shelf["kind"], start=(x, y))
                    return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def _drag_event(self, context, event):
        x, y = event.mouse_x, event.mouse_y
        if event.type == 'ESC':
            _drag.update(src=None, target=None)
            refresh_ui()
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            target = target_at(x, y, context, _drag["src"])
            if target != _drag["target"]:
                _drag["target"] = target
                refresh_ui()
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            src, kind = _drag["src"], _drag["kind"]
            moved = abs(x - _drag["start"][0]) + abs(y - _drag["start"][1]) > 4   # A click without moving changes nothing.
            result = finish_drag(kind, src, target_at(x, y, context, src)) if moved else None
            _drag.update(src=None, target=None)
            self._swallow = False
            refresh_ui()
            if result:
                self.report({'INFO'}, {"reorder": "Moved the button", "remove": "Removed the button from the Custom shelf",
                                       "copy": "Copied the button to the Custom shelf"}[result])
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'} if event.type != 'TIMER' else {'PASS_THROUGH'}


class M3D_OT_edit_probe(Operator):
    """Remember the button under the cursor (a Ctrl+Alt+click then gives it a shortcut)"""
    bl_idname = "m3d.edit_probe"
    bl_label = "Find Button"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, _context):
        return _state["on"]

    def invoke(self, context, event):
        probe(context, event)
        return {'PASS_THROUGH'}


# -----------------------------------------------------------------------------
# Dock panels and tabs

def panel_root(cls):
    """The panel that decides where `cls` shows: itself, or the top of its parent chain."""
    seen = 0
    while getattr(cls, "bl_parent_id", "") and seen < 8:
        parent = bpy.types.Panel.bl_rna_get_subclass_py(cls.bl_parent_id)
        if parent is None:
            break
        cls, seen = parent, seen + 1
    return cls


def panel_placement(context, cls):
    """(page the panel shows on, hidden by the user) for this workspace's kind."""
    from m3d_user import panel_hidden, panel_page
    from m3d_workspace import current_kind
    kind, root = current_kind(context), panel_root(cls)
    return panel_page(kind, root.__name__, root.page), panel_hidden(kind, root.__name__)


_tab_items = []


def _move_items(self, context):
    """Tabs of this dock that a panel can move to."""
    from m3d_workspace import current_kind, dock_tabs, side_of
    _tab_items[:] = [(t.page, t.label, "") for t in dock_tabs(current_kind(context), side_of(context)) if t.page]
    return _tab_items


class M3D_OT_panel_move(Operator):
    """Move this panel to another tab of the dock"""
    bl_idname = "m3d.panel_move"
    bl_label = "Move to Tab"
    bl_options = {'INTERNAL'}

    panel: bpy.props.StringProperty()
    tab: bpy.props.EnumProperty(name="Tab", items=_move_items)

    def execute(self, context):
        from m3d_user import move_panel
        from m3d_workspace import current_kind
        cls = getattr(bpy.types, self.panel, None)
        if cls is None or not hasattr(cls, "page"):
            return {'CANCELLED'}
        move_panel(current_kind(context), self.panel, self.tab, cls.page)
        _redraw_docks(context)
        return {'FINISHED'}


class M3D_OT_panel_hide(Operator):
    """Hide this panel (it stays visible, dimmed, while editing, so it can be shown again)"""
    bl_idname = "m3d.panel_hide"
    bl_label = "Hide Panel"
    bl_options = {'INTERNAL'}

    panel: bpy.props.StringProperty()

    def execute(self, context):
        from m3d_user import toggle_panel_hidden
        from m3d_workspace import current_kind
        toggle_panel_hidden(current_kind(context), self.panel)
        _redraw_docks(context)
        return {'FINISHED'}


def _redraw_docks(context):
    for area in context.screen.areas:
        if area.type == 'PROPERTIES':
            area.tag_redraw()


def draw_panel_controls(layout, context, cls):
    """Panel header while editing: where the panel moves to, and the eye."""
    if getattr(cls, "bl_parent_id", ""):
        return
    _page, hidden = panel_placement(context, cls)
    row = layout.row(align=True)
    row.operator_menu_enum("m3d.panel_move", "tab", text="", icon='ARROW_LEFTRIGHT').panel = cls.__name__
    row.operator("m3d.panel_hide", text="", icon='HIDE_ON' if hidden else 'HIDE_OFF').panel = cls.__name__


class _TabName:
    name: bpy.props.StringProperty(name="Name", default="New Tab")

    def _current(self, context):
        from m3d_workspace import current_kind, side_of
        return current_kind(context), side_of(context)


class M3D_OT_user_tab_add(_TabName, Operator):
    """Make a new, empty tab in this dock; move panels into it with the menu in their headers"""
    bl_idname = "m3d.user_tab_add"
    bl_label = "New Dock Tab"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, confirm_text="Create")

    def execute(self, context):
        from m3d_user import add_user_tab
        kind, side = self._current(context)
        tab = add_user_tab(kind, side, self.name)
        if context.space_data is not None and context.space_data.type == 'PROPERTIES':
            context.space_data.context = 'MODELING_TOOLKIT'
        setattr(context.workspace, "m3d_page_" + side.lower(), tab)
        _redraw_docks(context)
        return {'FINISHED'}


class M3D_OT_user_tab_rename(_TabName, Operator):
    """Rename this tab"""
    bl_idname = "m3d.user_tab_rename"
    bl_label = "Rename Dock Tab"
    bl_options = {'INTERNAL'}

    tab: bpy.props.StringProperty()

    def invoke(self, context, _event):
        from m3d_user import user_tabs
        kind, _side = self._current(context)
        self.name = next((t["label"] for t in user_tabs(kind) if t["id"] == self.tab), self.name)
        return context.window_manager.invoke_props_dialog(self, confirm_text="Rename")

    def execute(self, context):
        from m3d_user import rename_user_tab
        rename_user_tab(self._current(context)[0], self.tab, self.name)
        _redraw_docks(context)
        return {'FINISHED'}


class M3D_OT_user_tab_delete(Operator):
    """Delete this tab; its panels go back to their own tabs"""
    bl_idname = "m3d.user_tab_delete"
    bl_label = "Delete Dock Tab"
    bl_options = {'INTERNAL'}

    tab: bpy.props.StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Delete Tab", confirm_text="Delete", message="Delete this tab? Its panels go back to their own tabs.")

    def execute(self, context):
        from m3d_user import delete_user_tab
        from m3d_workspace import current_kind
        delete_user_tab(current_kind(context), self.tab)
        _redraw_docks(context)
        return {'FINISHED'}


class M3D_OT_dock_layout_reset(Operator):
    """Restore this workspace kind's dock to the defaults: no user tabs, panels back on their own tabs and shown, all tabs shown"""
    bl_idname = "m3d.dock_layout_reset"
    bl_label = "Reset Dock Layout"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Reset Dock Layout", confirm_text="Reset",
            message="Remove your tabs and put the panels and tabs of this dock back to the defaults?")

    def execute(self, context):
        from m3d_user import reset_dock
        from m3d_workspace import current_kind
        reset_dock(current_kind(context))
        _redraw_docks(context)
        return {'FINISHED'}


class PROPERTIES_PT_m3d_user_tab_hint(Panel):
    """Shows in an empty user tab while editing"""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "modeling_toolkit"
    bl_label = "Empty Tab"

    @classmethod
    def poll(cls, context):
        from m3d_user import _dock
        from m3d_workspace import active_page, current_kind
        page = active_page(context)
        return (_state["on"] and page.startswith("user_")
                and page not in _dock(current_kind(context))["moves"].values())

    def draw(self, context):
        self.layout.label(text="Use the arrows in a panel header")
        self.layout.label(text="to move the panel into this tab.")


def draw_tab_controls(layout, context, tab_id, user):
    """Dock header while editing: a new-tab button, and rename / delete for the shown user tab."""
    row = layout.row(align=True)
    row.operator("m3d.user_tab_add", text="", icon='ADD')
    if user:
        row.operator("m3d.user_tab_rename", text="", icon='GREASEPENCIL').tab = tab_id
        row.operator("m3d.user_tab_delete", text="", icon='X').tab = tab_id


# -----------------------------------------------------------------------------

def add_probe_keys():
    """The probe runs while Ctrl+Alt is down (edit mode only): when it is pressed and whenever the mouse moves.
    The add-on key configuration is new after loading the factory settings, so this runs again then."""
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new("User Interface", space_type='EMPTY', region_type='WINDOW')
    if any(k.idname == "m3d.edit_probe" for k in km.keymap_items):
        return
    for key, value, mods in (('LEFT_ALT', 'PRESS', {"ctrl": True}), ('LEFT_CTRL', 'PRESS', {"alt": True}),
                             ('MOUSEMOVE', 'ANY', {"ctrl": True, "alt": True})):
        km.keymap_items.new("m3d.edit_probe", key, value, **mods)


def _load_post(*_args):
    """Modal operators don't survive loading a file: edit mode is off in the new one."""
    add_probe_keys()
    _state.update(on=False, running=False, op=None)
    _geom.clear()
    _drag.update(src=None, target=None)
    global _capture, _hover
    _capture = _hover = None
    _prompt["text"] = ""


classes = (M3D_OT_edit_mode, M3D_OT_edit_ui, M3D_OT_edit_probe, M3D_OT_panel_move, M3D_OT_panel_hide,
           M3D_OT_user_tab_add, M3D_OT_user_tab_rename, M3D_OT_user_tab_delete, M3D_OT_dock_layout_reset,
           PROPERTIES_PT_m3d_user_tab_hint)


def register():
    global _handle
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_load_post)
    bpy.app.handlers.load_factory_startup_post.append(_load_post)
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw_prompt, (), 'WINDOW', 'POST_PIXEL')
    add_probe_keys()


def unregister():
    global _handle
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.get("User Interface") if kc is not None else None
    for kmi in [k for k in km.keymap_items if k.idname == "m3d.edit_probe"] if km else ():
        km.keymap_items.remove(kmi)
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.load_factory_startup_post):
        if _load_post in handlers:
            handlers.remove(_load_post)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
