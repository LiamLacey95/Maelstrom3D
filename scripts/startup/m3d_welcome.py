# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
First run and discoverability for Maelstrom3D: the splash (New, Open, Recent, Recover; the keys to get started; Quick Setup
on the first run) that bl_operators/wm.py draws, and the key card by task (Help > Keyboard Shortcuts), read from the keymap.
"""

import bpy
from bpy.types import Operator

from m3d_help import DOCS, REPO, version_label

# The keys of the splash (test_m3d.py checks them against the keymap).
GETTING_STARTED = (
    ("F1-F7", "Task workspaces (Modeling ... Rendering)"),
    ("Alt+LMB / MMB / RMB", "Tumble / Track / Dolly"),
    ("Space (hold)", "Hotbox: every menu (tap: four views)"),
    ("RMB (hold)", "Marking menu: modes and the tools for the selection"),
    ("Tab", "Search every menu"),
)


def _line(layout):
    col = layout.column()
    col.separator()
    col.separator(type='LINE')
    col.separator()


def draw_splash(layout, context):
    """The splash (WM_MT_splash): start a scene, the keys to get started, the guide and "Show this at startup"."""
    layout.operator_context = 'EXEC_DEFAULT'
    layout.emboss = 'PULLDOWN_MENU'
    split = layout.split()
    col = split.column()
    col.label(text="Start")
    col.operator("wm.read_homefile", text="New Scene", icon='FILE_NEW').app_template = ""
    sub = col.column()
    sub.operator_context = 'INVOKE_DEFAULT'
    sub.operator("wm.open_mainfile", text="Open Scene...", icon='FILE_FOLDER')
    col.operator("wm.recover_last_session", text="Recover Last Session", icon='RECOVER_LAST')
    col = split.column()
    col.label(text="Recent Files")
    if col.template_recent_files(rows=4):
        sub = col.column()
        sub.operator_context = 'INVOKE_DEFAULT'
        sub.operator("wm.search_single_menu", text="More...", icon='VIEWZOOM').menu_idname = "TOPBAR_MT_file_open_recent"
    else:
        col.label(text="None yet")

    _line(layout)
    layout.label(text="Getting Started")
    for key, what in GETTING_STARTED:
        row = layout.split(factor=0.3)
        row.label(text=key, translate=False)
        row.label(text=what)

    _line(layout)
    split = layout.split()
    col = split.column()
    col.operator("wm.url_open", text="Maelstrom3D Guide", icon='HELP').url = DOCS + "MAELSTROM3D.md"
    sub = col.column()
    sub.operator_context = 'INVOKE_DEFAULT'
    sub.operator("m3d.key_card", text="Keyboard Shortcuts", icon='KEYINGSET')
    col = split.column()
    col.operator("wm.url_open", text="What's New", icon='URL').url = REPO + "/releases"
    sub = col.column()
    sub.operator_context = 'INVOKE_DEFAULT'
    sub.operator("m3d.report_bug", text="Report a Bug", icon='ERROR')
    layout.separator()
    row = layout.row()
    row.emboss = 'NORMAL'
    row.prop(context.preferences.view, "show_splash", text="Show this at startup")
    row.label(text=version_label(), translate=False)
    layout.separator()


def draw_quick_setup(layout, context):
    """The first run's splash (WM_MT_splash_quick_setup: no preferences saved yet): UI size, theme, the settings of the
    previous version. Continue saves the preferences and the splash shows its usual content."""
    prefs = context.preferences
    layout.operator_context = 'EXEC_DEFAULT'
    layout.label(text="Welcome to Maelstrom3D: Quick Setup")
    split = layout.split(factor=0.20)   # (left margin and content width, like Blender's own)
    split.label()
    col = split.split(factor=0.73).column()
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(prefs.view, "ui_scale", text="UI Size")
    label = bpy.types.USERPREF_MT_interface_theme_presets.bl_label
    col.column(heading="Theme").menu("USERPREF_MT_interface_theme_presets",
                                     text="Maelstrom3D" if label == "Presets" else label)
    old = bpy.types.PREFERENCES_OT_copy_prev.previous_version()
    if old and bpy.types.PREFERENCES_OT_copy_prev.poll(context):
        col.separator()
        col.operator("preferences.copy_prev", text="Import Settings From %d.%d" % tuple(old), icon='IMPORT')
    col.separator(factor=2)
    col.operator("wm.save_userpref", text="Continue")
    layout.separator(factor=2.0)


# -----------------------------------------------------------------------------
# Key card (Help > Keyboard Shortcuts): the keys by task, read from the keymap (so they follow your own keys)

def _key_card():
    """Task -> rows (label, keymap, operator, options[, True: a numbered row of keys, shown first-last]). Most rows are the
    status bar's hints (m3d_ui), so the card and the status bar name a key the same way. SHORTCUTS.md is written from it
    too (tools/m3d/shortcuts_doc.py)."""
    from m3d_ui import _HOTBOX, _MARKING_MENU, _SEARCH, _SELECT_HINTS, _VIEW_HINTS, KIND_MODE_HINTS, MODE_HINTS, STATUS_HINTS

    def brush_rows(kind):
        _mode, km_name, items, (range_idname, range_label) = STATUS_HINTS[kind]
        rows = [(label if isinstance(label, str) else "Paint", (km or [km_name])[0], idname, props)
                for label, idname, props, *km in items]
        return rows + [(range_label, km_name, range_idname, {}, True)]

    def mm(label, tool):
        return (label, "Object Mode", "m3d.key_marking_menu", {"tool": tool})

    hints = {h[2] for h in _SELECT_HINTS + _VIEW_HINTS}
    return (
        ("Everywhere", (
            ("Task workspaces", "Window", "m3d.workspace", {}, True),
            ("Search every menu", *_SEARCH[1:]),
            ("Hotbox / four views", *_HOTBOX[1:]),
            ("Undo", "Window", "ed.undo", {}),
            ("Redo", "Window", "ed.redo", {}),
            ("Save Scene", "Window", "wm.save_mainfile", {}),
            ("Open Scene", "Window", "wm.open_mainfile", {}),
            ("Maximize panel", "3D View", "screen.screen_full_area", {"use_hide_panels": True}),
        )),
        ("View and Select", (
            *_VIEW_HINTS,
            ("Frame selection", "3D View", "view3d.view_selected", {}),
            ("Frame all", "3D View", "m3d.key_marking_menu", {"command": "view3d.view_all"}),
            ("Wireframe ... Lighting", "3D View", "wm.context_set_enum",
             {"data_path": "space_data.shading.type"}, True),
            ("Isolate selection", "3D View", "view3d.localview", {}),
            *_SELECT_HINTS,
        )),
        ("Modeling", (
            mm("Select tool", "builtin.select_box"), mm("Move", "builtin.move"), mm("Rotate", "builtin.rotate"),
            mm("Scale", "builtin.scale"),
            _MARKING_MENU,
            ("Create / tools menu", "Object Mode", "wm.call_menu_pie", {"name": "M3D_MT_shift_rmb"}),
            ("Object / component", "Object Mode", "object.editmode_toggle", {}),
            ("Vertex / Edge / Face", "Object Mode", "object.mode_set_with_submode", {}, True),
            ("Smooth preview", "Object Mode", "m3d.smooth_preview", {}, True),
            ("Duplicate", "Object Mode", "m3d.duplicate", {"with_transform": False}),
            ("Group", "Object Mode", "m3d.group", {}),
            ("Extrude", "Mesh", "view3d.edit_mesh_extrude_move_normal", {}),
            ("Bevel", "Mesh", "mesh.bevel", {}),
            ("Hide selection", "Object Mode", "m3d.hide_selection", {}),
        )),
        ("Sculpt", brush_rows('SCULPT')),
        ("UV", (*(h for h in KIND_MODE_HINTS[('UV', 'EDIT_MESH')] if h[2] not in hints),
                ("Unfold", "UV Editor", "m3d.uv_unfold", {}), ("Layout", "UV Editor", "m3d.uv_layout", {}),
                ("Checker map", "UV Editor", "m3d.uv_checker", {}))),
        ("Texture", brush_rows('TEXTURE')),
        ("Rigging", (*(h for h in MODE_HINTS['EDIT_ARMATURE'] if h[2] not in hints),
                     ("Paint weights", "Weight Paint", "paint.weight_paint", {"mode": 'NORMAL'}),
                     ("Subtract weights", "Weight Paint", "paint.weight_paint", {"mode": 'INVERT'}))),
        ("Animation", (*(h for h in MODE_HINTS['POSE'] if h[2] not in hints),
                       *(("Key " + label, "Pose", "m3d.set_key", {"channels": channels})
                         for label, channels in (("move", 'LOCATION'), ("rotate", 'ROTATION'), ("scale", 'SCALE'))),
                       ("Previous key", "Frames", "screen.keyframe_jump", {"next": False}),
                       ("Next key", "Frames", "screen.keyframe_jump", {"next": True}),
                       ("Go to start", "Frames", "screen.frame_jump", {"end": False}))),
        ("Rendering", (*(h for h in KIND_MODE_HINTS[('RENDER', 'OBJECT')] if h[2] not in hints and h[2] != "wm.call_menu_pie"),
                       ("Render animation", "Screen Editing", "m3d.render", {"animation": True}))),
    )


# Blender's keys and what they are here (test_m3d.py checks the second column against the keymap).
IF_YOU_KNOW_BLENDER = (
    ("Tab: Edit Mode", "F8: object / component (F9-F11: vertex, edge, face); Tab searches every menu"),
    ("G / R / S: move / rotate / scale", "W / E / R (tools with a manipulator); S sets a key"),
    ("Space: play", "Alt+V plays; Space: tap for four views, hold for the hotbox"),
    ("Shift+A: add", "The Create menu, the shelf or Shift+RMB"),
    ("RMB: context menu", "RMB (hold): marking menu"),
    ("MMB: orbit", "Alt+LMB tumble, Alt+MMB track, Alt+RMB dolly"),
    ("F2: rename", "The name field in the Status Line; F2 is Sculpt"),
    ("F3: search", "Tab; F3 is the UV workspace"),
    ("Shift+D: duplicate", "Ctrl+D in place, Shift+D with the last transform"),
    ("H / Alt+H: hide / show", "Ctrl+H / Ctrl+Shift+H"),
    ("I: insert keyframe", "S: set key"),
    ("N: sidebar", "Ctrl+A: Channel Box / Attribute Editor (the dock)"),
    ("F12: render", "Shift+F12 (F12 in component mode: the UV workspace)"),
)

SHORT_KEYS = {'LEFTMOUSE': "LMB", 'MIDDLEMOUSE': "MMB", 'RIGHTMOUSE': "RMB"}


def kmi_text(kmi):
    """"Ctrl+Shift+E", "Alt+LMB", "RMB drag"."""
    from m3d_ui import event_name
    mods = "".join(m + "+" for m, on in (("Ctrl", kmi.ctrl), ("Shift", kmi.shift), ("Alt", kmi.alt)) if on)
    drag = " drag" if kmi.value == 'CLICK_DRAG' else ""
    return mods + SHORT_KEYS.get(kmi.type, event_name(kmi)) + drag


def row_key(context, row):
    """The key text of a key card row, "" when the keymap has none."""
    from m3d_ui import hint_item, key_items, plain_key
    label, km_name, idname, props, *numbered = row
    try:
        items = [k for k in key_items(context, km_name, idname, props) if plain_key(k)]
    except AttributeError:   # (no window manager: a test)
        return ""
    if not items:
        return ""
    if numbered:
        first, last = items[0], items[-1]
        return kmi_text(first) if first == last else "%s-%s" % (kmi_text(first), kmi_text(last).rpartition("+")[2])
    return kmi_text(hint_item(items))


def card(context):
    """[(task, [(key, label)])]: the key card as text, rows without a key left out."""
    found = []
    for task, rows in _key_card():
        keys = [(row_key(context, row), row[0]) for row in rows]
        found.append((task, [(key, label) for key, label in keys if key]))
    return found


class M3D_OT_key_card(Operator):
    """The keys by task (read from the keymap, so they follow your own keys) and what Blender's keys are here"""
    bl_idname = "m3d.key_card"
    bl_label = "Keyboard Shortcuts"

    page: bpy.props.EnumProperty(name="Page", items=(
        ('TASKS', "Keys by Task", "The keys of each task, read from the keymap"),
        ('BLENDER', "If You Know Blender", "Blender's keys and what they are here")))

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=1250)

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text="Keyboard Shortcuts", icon='KEYINGSET')
        row.prop(self, "page", expand=True)
        layout.separator()
        if self.page == 'TASKS':
            grid = layout.grid_flow(row_major=True, columns=5, even_columns=True)
            for task, rows in card(context):
                col = grid.column(align=True)
                col.label(text=task)
                for key, label in rows:
                    split = col.split(factor=0.35)
                    split.label(text=key, translate=False)
                    split.label(text=label)
                col.separator()
        else:
            for blender, here in IF_YOU_KNOW_BLENDER:
                split = layout.split(factor=0.3)
                split.label(text=blender)
                split.label(text=here)
        layout.separator()
        row = layout.row()
        row.operator("wm.url_open", text="Full List", icon='URL').url = DOCS + "SHORTCUTS.md"
        row.operator("screen.userpref_show", text="Hotkey Editor", icon='PREFERENCES').section = 'KEYMAP'

    def execute(self, _context):
        return {'FINISHED'}


classes = (
    M3D_OT_key_card,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
