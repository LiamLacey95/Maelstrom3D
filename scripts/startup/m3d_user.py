# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Personalization for Maelstrom3D: the Custom shelf ("Add to Shelf" in a button's right-click menu), the dock tabs
a user hides, and the dock layout (user tabs, moved and hidden panels; edited by m3d_edit.py). Everything lives in `m3d_user.json` in the user config folder; a missing or damaged
file never breaks the UI (it reads as empty).
"""

import json
import os

import bpy
from bpy.types import Operator


# -----------------------------------------------------------------------------
# JSON store

_cache = None


def _path(create=False):
    cfg = bpy.utils.user_resource('CONFIG', create=create)
    return os.path.join(cfg, "m3d_user.json") if cfg else ""


def data():
    """The settings dict, read once (damaged or missing file: empty)."""
    global _cache
    if _cache is None:
        _cache = {}
        try:
            with open(_path(), encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                _cache = loaded
        except (OSError, ValueError):
            pass
    return _cache


def save():
    path = _path(create=True)
    if not path:
        return False
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data(), fh, indent=1)
        os.replace(path + ".tmp", path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def reset_cache():
    global _cache
    _cache = None


def _section(name, kind):
    """`data()[name][kind]`, replaced by an empty list/dict when the file holds something else."""
    root = data()
    if not isinstance(root.get(name), dict):
        root[name] = {}
    default = [] if name == "shelf" else {}
    if not isinstance(root[name].get(kind), type(default)):
        root[name][kind] = default
    return root[name][kind]


# -----------------------------------------------------------------------------
# Hidden dock tabs

def hidden_tabs(kind):
    hidden = data().get("hidden_tabs")
    hidden = hidden.get(kind) if isinstance(hidden, dict) else None
    return {t for t in hidden if isinstance(t, str)} if isinstance(hidden, list) else set()


def toggle_tab(kind, tab):
    root = data()
    if not isinstance(root.get("hidden_tabs"), dict):
        root["hidden_tabs"] = {}
    hidden = hidden_tabs(kind) ^ {tab}
    root["hidden_tabs"][kind] = sorted(hidden)
    return save()


# -----------------------------------------------------------------------------
# Dock layout per workspace kind: user tabs, panels moved to another tab, hidden panels.
# data()["dock"][kind] = {"tabs": [{"id", "label", "side"}], "moves": {panel: page}, "hidden": [panel]}

def _dock(kind):
    root = data()
    if not isinstance(root.get("dock"), dict):
        root["dock"] = {}
    dock = root["dock"].get(kind)
    if not isinstance(dock, dict):
        dock = root["dock"][kind] = {}
    if not isinstance(dock.get("tabs"), list):
        dock["tabs"] = []
    dock["tabs"][:] = [t for t in dock["tabs"] if isinstance(t, dict) and isinstance(t.get("id"), str)
                       and isinstance(t.get("label"), str) and t.get("side") in {'LEFT', 'RIGHT'}]
    if not isinstance(dock.get("moves"), dict):
        dock["moves"] = {}
    if not isinstance(dock.get("hidden"), list):
        dock["hidden"] = []
    return dock


def user_tabs(kind, side=None):
    """The tabs the user made for this kind: [{"id", "label", "side"}], all or one side's."""
    return [t for t in _dock(kind)["tabs"] if side in {None, t["side"]}]


def add_user_tab(kind, side, label):
    """New dock tab (empty); returns its id. Ids are never reused, the page of a user tab is its id."""
    dock = _dock(kind)
    nums = [int(t["id"][5:]) for t in dock["tabs"] if t["id"][5:].isdigit()]
    tab = {"id": "user_%d" % (max(nums, default=0) + 1), "label": label.strip() or "New Tab", "side": side}
    dock["tabs"].append(tab)
    save()
    return tab["id"]


def rename_user_tab(kind, tab_id, label):
    for tab in _dock(kind)["tabs"]:
        if tab["id"] == tab_id and label.strip():
            tab["label"] = label.strip()
            return save()
    return False


def delete_user_tab(kind, tab_id):
    """Remove a user tab: the panels moved into it go back to their own tabs."""
    dock = _dock(kind)
    dock["tabs"][:] = [t for t in dock["tabs"] if t["id"] != tab_id]
    dock["moves"] = {k: v for k, v in dock["moves"].items() if v != tab_id}
    return save()


def panel_page(kind, panel, home):
    """The page a panel shows on: the one the user moved it to, else its own (`home`)."""
    page = _dock(kind)["moves"].get(panel)
    return page if isinstance(page, str) else home


def move_panel(kind, panel, page, home):
    moves = _dock(kind)["moves"]
    if page == home:
        moves.pop(panel, None)
    else:
        moves[panel] = page
    return save()


def panel_hidden(kind, panel):
    return panel in _dock(kind)["hidden"]


def toggle_panel_hidden(kind, panel):
    hidden = _dock(kind)["hidden"]
    if panel in hidden:
        hidden.remove(panel)
    else:
        hidden.append(panel)
    return save()


def reset_dock(kind):
    """Default dock for this kind: no user tabs, no moved or hidden panels, no hidden tabs."""
    root = data()
    for name in ("dock", "hidden_tabs"):
        if isinstance(root.get(name), dict):
            root[name].pop(kind, None)
    return save()


# -----------------------------------------------------------------------------
# Custom shelf: items are {"idname", "props", "icon", "label"}

def shelf_items(kind):
    items = _section("shelf", kind)
    items[:] = [i for i in items if isinstance(i, dict)]
    return items


def _op_exists(idname):
    mod, _, name = idname.partition(".")
    if not name:
        return False
    try:  # hasattr() on bpy.ops is always True: ask for the operator's type instead.
        getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except (AttributeError, KeyError):
        return False
    return True


def _item_ok(item):
    return (isinstance(item.get("idname"), str) and _op_exists(item["idname"]) and isinstance(item.get("props"), dict)
            and isinstance(item.get("icon", ""), str) and isinstance(item.get("label", ""), str))


def _json_value(value):
    """A property value as JSON data (None when it can't be stored)."""
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, set):
        return sorted(value)
    try:
        return [_json_value(v) for v in value]
    except TypeError:
        return None


def item_from_operator(op_props):
    """Shelf item for an operator button (`context.button_operator`): the properties set on the button."""
    ident = op_props.bl_rna.identifier
    mod, _, name = ident.partition("_OT_")
    idname = mod.lower() + "." + name
    if not name or not _op_exists(idname):
        return None
    props = {}
    for prop in op_props.bl_rna.properties:
        if prop.identifier != "rna_type" and op_props.is_property_set(prop.identifier):
            value = _json_value(getattr(op_props, prop.identifier))
            if value is not None:
                props[prop.identifier] = value
    label = props.get("label") if idname in {"m3d.tool", "m3d.call"} else None
    return {"idname": idname, "props": props, "icon": "",
            "label": label or getattr(getattr(bpy.ops, mod.lower()), name).get_rna_type().name}


def item_from_property(context):
    """Toggle button for a boolean property of the scene or the active object."""
    ptr, prop = getattr(context, "button_pointer", None), getattr(context, "button_prop", None)
    if ptr is None or prop is None or prop.type != 'BOOLEAN' or prop.is_readonly or prop.array_length:
        return None
    owner = {bpy.types.Scene: "scene", bpy.types.Object: "object"}.get(type(ptr.id_data))
    try:
        path = ptr.path_from_id(prop.identifier)
    except ValueError:
        return None
    if owner is None or not path:
        return None
    if owner == "object" and ptr.id_data != context.object:
        return None
    return {"idname": "wm.context_toggle", "props": {"data_path": "%s.%s" % (owner, path)}, "icon": "",
            "label": prop.name}


def item_from_context(context):
    op_props = getattr(context, "button_operator", None)
    if op_props is not None:
        return item_from_operator(op_props)
    return item_from_property(context)


def _kind(context):
    from m3d_workspace import current_kind
    return current_kind(context)


def _py_props(idname, props):
    """Stored JSON properties as Python values (flag enums are sets, vectors tuples)."""
    mod, _, name = idname.partition(".")
    rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
    out = {}
    for key, value in props.items():
        prop = rna.properties.get(key)
        if prop is None:
            continue
        if prop.type == 'ENUM' and prop.is_enum_flag and isinstance(value, list):
            value = set(value)
        elif getattr(prop, "array_length", 0) and isinstance(value, list):
            value = tuple(value)
        out[key] = value
    return out


_icons = None


def _icon_ok(icon):
    global _icons
    if _icons is None:
        _icons = set(bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items.keys())
    return icon in _icons


def draw_custom_shelf(layout, context, kind, edit, tray=False):
    """Custom shelf buttons. Editing in the top bar: fixed-width cells that the edit mode's drag picks up
    (m3d_edit.py); editing in the Sculpt tray: each button gets move left / remove / move right."""
    import m3d_edit
    from m3d_mode import _button
    items = shelf_items(kind)
    cells = edit and not tray
    row = layout.row(align=True)
    rec = None
    if cells:
        rec = m3d_edit.begin_shelf(context, 'CUSTOM', kind)
    else:
        row.scale_x = row.scale_y = 1.5
    if not items:
        text = "Right-click any button, Add to Shelf" + (" (or drag one onto this tab)" if cells else "")
        (m3d_edit.add_cell(rec, row, 12.0) if cells else row).label(text=text)
    drag = m3d_edit._drag
    for i, item in enumerate(items):
        if not _item_ok(item):
            continue
        icon = item.get("icon") or 'NONE'
        if not _icon_ok(icon):
            icon = 'NONE'
        text = "" if icon != 'NONE' else item.get("label", "")
        target = row
        if cells:
            width = m3d_edit.ICON_CELL if icon != 'NONE' else m3d_edit.text_units(rec, text)
            target = m3d_edit.add_cell(rec, row, width, ("C", i), icon=icon != 'NONE')
            target.active = drag["src"] != ("C", i)
            slot = drag["target"]
            target.alert = isinstance(slot, tuple) and slot[1] == i and drag["src"] is not None
        _button(target, context, text, item["idname"], icon, _py_props(item["idname"], item["props"]))
        if edit and tray:
            sub = row.row(align=True)
            sub.scale_x = 0.4
            for action, arrow in (('LEFT', 'TRIA_LEFT'), ('REMOVE', 'X'), ('RIGHT', 'TRIA_RIGHT')):
                o = sub.operator("m3d.shelf_edit", text="", icon=arrow)
                o.action, o.index = action, i
            row.separator(factor=0.5)
    if cells and items:   # Room at the end: drop here to move a button last.
        end = m3d_edit.add_cell(rec, row, m3d_edit.ICON_CELL)
        end.alert = drag["src"] is not None and drag["target"] == ("slot", len(items))
        end.label(text="", icon='ADD')


# -----------------------------------------------------------------------------
# Operators and the button context menu

class M3D_OT_shelf_add(Operator):
    """Add this button to the Custom shelf of the current workspace"""
    bl_idname = "m3d.shelf_add"
    bl_label = "Add to Shelf"
    bl_options = {'INTERNAL'}

    item: bpy.props.StringProperty()

    def execute(self, context):
        try:
            item = json.loads(self.item)
        except ValueError:
            return {'CANCELLED'}
        shelf_items(_kind(context)).append(item)
        if not save():
            self.report({'WARNING'}, "Could not save m3d_user.json; the button is kept until you quit")
        self.report({'INFO'}, "Added \"%s\" to the Custom shelf" % item.get("label", ""))
        return {'FINISHED'}


class M3D_OT_shelf_edit(Operator):
    """Move or remove a Custom shelf button"""
    bl_idname = "m3d.shelf_edit"
    bl_label = "Edit Shelf Button"
    bl_options = {'INTERNAL'}

    action: bpy.props.EnumProperty(items=(('LEFT', "Left", ""), ('RIGHT', "Right", ""), ('REMOVE', "Remove", "")))
    index: bpy.props.IntProperty()

    @classmethod
    def description(cls, _context, props):
        return {'LEFT': "Move left", 'RIGHT': "Move right", 'REMOVE': "Remove from the shelf"}[props.action]

    def execute(self, context):
        items = shelf_items(_kind(context))
        i = self.index
        if not 0 <= i < len(items):
            return {'CANCELLED'}
        if self.action == 'REMOVE':
            del items[i]
        else:
            j = i + (-1 if self.action == 'LEFT' else 1)
            if 0 <= j < len(items):
                items[i], items[j] = items[j], items[i]
        save()
        return {'FINISHED'}


def button_context_menu(self, context):
    item = item_from_context(context)
    if item is None:
        return
    self.layout.separator()
    self.layout.operator("m3d.shelf_add", icon='ADD').item = json.dumps(item)


classes = (M3D_OT_shelf_add, M3D_OT_shelf_edit)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.UI_MT_button_context_menu.append(button_context_menu)


def unregister():
    bpy.types.UI_MT_button_context_menu.remove(button_context_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
