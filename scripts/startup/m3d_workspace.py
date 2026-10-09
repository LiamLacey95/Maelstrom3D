# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Task workspaces for Maelstrom3D: workspace kinds, F1-F7 switching, per-kind dock tabs and pages,
Reset Workspace. Per-user choices (hidden tabs, Custom shelf) are in m3d_user.py.
"""

import os
from collections import namedtuple

import bpy
from bpy.types import Menu, Operator, Panel

import m3d_edit

# kind -> (workspace name, key, object mode on entry, menu set)
KINDS = {
    'MODEL': ("Modeling", 'F1', 'OBJECT', 'MODELING'),
    'SCULPT': ("Sculpt", 'F2', 'SCULPT', 'SCULPTING'),
    'UV': ("UV", 'F3', 'EDIT', 'UV'),
    'TEXTURE': ("Texture", 'F4', 'TEXTURE_PAINT', 'TEXTURING'),
    'RIG': ("Rigging", 'F5', 'OBJECT', 'RIGGING'),
    'ANIM': ("Animation", 'F6', 'POSE', 'ANIMATION'),
    'RENDER': ("Rendering", 'F7', 'OBJECT', 'RENDERING'),
}
# Workspace order in the startup file: the seven kinds, then the extras.
WORKSPACE_ORDER = [v[0] for v in KINDS.values()] + ["Shading", "Compositing", "Node Editor", "Script Editor"]

# Names in older startup files -> current names (an old factory startup is renamed on load).
WORKSPACE_NAMES = {"Maya Classic": "Modeling", "Classic": "Modeling", "Sculpting": "Sculpt", "UV Editing": "UV",
                   "3D Paint": "Texture", "Hypershade": "Shading"}
# Kind from the name when a file has no `m3d_kind`. Blender's spare Modeling workspace counts as Modeling, last.
_KIND_BY_NAME = {v[0]: k for k, v in KINDS.items()}
_KIND_BY_NAME.update({old: _KIND_BY_NAME[new] for old, new in WORKSPACE_NAMES.items() if new in _KIND_BY_NAME})
_KIND_BY_NAME["Modeling - Standard"] = 'MODEL'


def _base_name(name):
    """"Modeling.001" -> "Modeling"."""
    head, dot, tail = name.rpartition(".")
    return head if dot and tail.isdigit() else name


def workspace_kind(ws):
    """Kind of a workspace: its saved `m3d_kind`, else the one for its (current or older) name; None for
    other workspaces (Shading, Compositing, user-made ones)."""
    if ws is None:
        return None
    kind = ws.m3d_kind
    return kind if kind in KINDS else _KIND_BY_NAME.get(_base_name(ws.name))


def current_kind(context):
    """Kind that decides what the top bar and dock show. Other workspaces look like Modeling."""
    return workspace_kind(context.workspace) or 'MODEL'


# Modes whose menus a workspace's menu set already shows: the viewport header doesn't repeat them there.
KIND_MODES_IN_MENU_BAR = {'SCULPT': {'SCULPT'}, 'TEXTURE': {'TEXTURE_PAINT'}}


def menu_bar_has_mode(context):
    """True when the menu bar of this workspace has the menus of the active object's mode."""
    ob = context.active_object
    return ob is not None and ob.mode in KIND_MODES_IN_MENU_BAR.get(current_kind(context), ())


def find_workspace(kind):
    """The workspace for a kind: the one with the factory name, then ones with a saved kind, then older names."""
    def rank(ws):
        return (ws.name != KINDS[kind][0], ws.m3d_kind != kind, list(_KIND_BY_NAME).index(_base_name(ws.name))
                if _base_name(ws.name) in _KIND_BY_NAME else 0)
    found = [ws for ws in bpy.data.workspaces if workspace_kind(ws) == kind]
    return min(found, key=rank) if found else None


def workspace_screens(kind):
    ws = find_workspace(kind)
    return list(ws.screens) if ws else []


# Entry modes that need a mesh: the workspace enters them on the active object.
MESH_MODES = {'EDIT', 'SCULPT', 'TEXTURE_PAINT'}


def use_selected_mesh(context):
    """Entering a mesh mode with a light, camera or empty active would leave the workspace in Object Mode: make a
    selected mesh active instead (nothing selected or active: the workspace's tabs say what to do)."""
    ob = context.active_object
    if context.mode != 'OBJECT' or (ob is not None and ob.type == 'MESH'):
        return
    mesh = next((o for o in context.selected_objects if o.type == 'MESH'), None)
    if mesh is not None:
        context.view_layer.objects.active = mesh


class M3D_OT_workspace(Operator):
    """Switch to a task workspace (F1 Modeling ... F7 Rendering) and its menu set"""
    bl_idname = "m3d.workspace"
    bl_label = "Switch Workspace"

    kind: bpy.props.EnumProperty(items=[(k, v[0], "") for k, v in KINDS.items()])

    @classmethod
    def description(cls, _context, props):
        return "Switch to the %s workspace (%s)" % (KINDS[props.kind][0], KINDS[props.kind][1])

    def execute(self, context):
        ws = find_workspace(self.kind)
        if ws is None:
            self.report({'WARNING'}, "No %s workspace in this file" % KINDS[self.kind][0])
            return {'CANCELLED'}
        wm = context.window_manager
        win = context.window or (wm.windows[0] if wm.windows else None)
        if KINDS[self.kind][2] in MESH_MODES:
            use_selected_mesh(context)
        if win is not None:
            win.workspace = ws
        wm.m3d_menu_set = KINDS[self.kind][3]
        return {'FINISHED'}


# The menu set and shelf follow the window's workspace, however it was switched (menu, F-key, Shift+[ ]).
_state = {"kind": None}


def workspace_changed(wm, ws):
    """Menu set and shelf tab for the workspace `ws` (called when the window's workspace changes)."""
    from m3d_ui import restore_shelf
    kind = workspace_kind(ws) or 'MODEL'
    prev, _state["kind"] = _state["kind"], kind
    if prev is None or prev == kind:
        return
    wm.m3d_menu_set = KINDS[kind][3]
    restore_shelf(wm, prev, kind)


def _shelf_visibility_changed(_self, context):
    """Show Shelf was toggled: redraw so the top bar changes its height (screen_edit.cc reads the property)."""
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


def _follow_workspace():
    wm = bpy.context.window_manager
    if wm.windows:
        workspace_changed(wm, wm.windows[0].workspace)
        from m3d_rig import follow_mode
        follow_mode(wm)   # The Rigging dock follows the mode.
        from m3d_anim import follow
        follow(wm)        # The Animation workspace limits what redraws while playing.
        from m3d_render import follow as follow_render
        follow_render(wm)  # The Rendering workspace's Render View shows the Render Result.
    return 0.25


# -----------------------------------------------------------------------------
# Dock tabs and pages

# A dock tab shows a native Properties context, or a page: panels with bl_context "modeling_toolkit" whose
# page id is the active one for that workspace and side. `short_label` is drawn when the dock is too narrow for the labels.
Tab = namedtuple("Tab", "id label context page short_label", defaults=("",))
_CHANNEL_BOX = Tab("channel_box", "Channel Box / Layer Editor", 'CHANNEL_BOX', None, "Channel Box")
_TOOLKIT = Tab("modeling_toolkit", "Modeling Toolkit", 'MODELING_TOOLKIT', "modeling_toolkit", "Toolkit")
_TOOL = Tab("tool", "Tool Settings", 'TOOL', None, "Tool")

# kind -> side -> tabs (an empty side uses the right-hand tabs). Phases 1-6 replace the entries of their kind.
DOCK_TABS = {kind: {'RIGHT': (_CHANNEL_BOX, _TOOLKIT, _TOOL), 'LEFT': ()} for kind in KINDS}
# Sculpt: the brush tray on the left, task tabs on the right (pages: m3d_sculpt.py).
DOCK_TABS['SCULPT'] = {
    'RIGHT': tuple(Tab("sculpt_" + page, label, 'MODELING_TOOLKIT', "sculpt_" + page) for page, label in (
        ("geometry", "Geometry"), ("mask", "Mask"), ("face_sets", "Face Sets"), ("deform", "Deform"),
        ("paint", "Paint"), ("display", "Display"), ("objects", "Objects"))),
    'LEFT': (Tab("sculpt_brushes", "Brushes", 'MODELING_TOOLKIT', "sculpt_brushes"),),
}
# UV: the UV tools on the right (pages: m3d_uv.py); no left tray.
DOCK_TABS['UV'] = {
    'RIGHT': tuple(Tab("uv_" + page, label, 'MODELING_TOOLKIT', "uv_" + page) for page, label in (
        ("unwrap", "Unwrap"), ("arrange", "Arrange"), ("check", "Check"), ("create", "Create"), ("udim", "UDIM"))),
    'LEFT': (),
}
# Texture: the brush tray on the left, task tabs on the right (pages: m3d_texture.py).
DOCK_TABS['TEXTURE'] = {
    'RIGHT': tuple(Tab("tex_" + page, label, 'MODELING_TOOLKIT', "tex_" + page) for page, label in (
        ("layers", "Layers"), ("brush", "Brush"), ("shelf", "Shelf"), ("bake", "Bake"), ("export", "Export"),
        ("display", "Display"))),
    'LEFT': (Tab("tex_brushes", "Brushes", 'MODELING_TOOLKIT', "tex_brushes"),),
}
# Rigging: task tabs on the right, bone collections under the Outliner on the left (pages: m3d_rig.py).
DOCK_TABS['RIG'] = {
    'RIGHT': tuple(Tab("rig_" + page, label, 'MODELING_TOOLKIT', "rig_" + page, *short) for page, label, *short in (
        ("skeleton", "Skeleton"), ("controls", "Controls & Constraints", "Controls"), ("skin", "Skin"), ("drive", "Drive"),
        ("test", "Test"), ("collections", "Collections"))),
    'LEFT': (Tab("rig_bones", "Bones", 'MODELING_TOOLKIT', "rig_bones"),),
}
# Animation: Channel Box first, then the task tabs (pages: m3d_anim.py).
DOCK_TABS['ANIM'] = {
    'RIGHT': (Tab("channel_box", "Channel Box", 'CHANNEL_BOX', None),
              *(Tab("anim_" + page, label, 'MODELING_TOOLKIT', "anim_" + page, *short) for page, label, *short in (
                  ("pick", "Pick"), ("tween", "Tween & Poses", "Tween"), ("motion", "Motion"), ("layers", "Layers"),
                  ("playback", "Playback")))),
    'LEFT': (),
}
# Rendering: task tabs on the right (pages: m3d_render.py).
DOCK_TABS['RENDER'] = {
    'RIGHT': tuple(Tab("render_" + page, label, 'MODELING_TOOLKIT', "render_" + page, *short) for page, label, *short in (
        ("camera", "Camera"), ("lighting", "Lighting"), ("materials", "Materials"), ("render", "Render"),
        ("output", "Output"), ("passes", "Passes & Layers", "Passes"), ("advanced", "Advanced"))),
    'LEFT': (),
}
# The last tab of every row: the stock Properties tabs.
ALL_SETTINGS = {'MODEL': ("Attribute Editor", "Attributes")}
DOCK_CONTEXTS = {'CHANNEL_BOX', 'MODELING_TOOLKIT', 'TOOL'}


def side_of_area(area_x, area_width, window_width):
    return 'LEFT' if area_x + area_width / 2 < window_width / 2 else 'RIGHT'


def side_of(context):
    """LEFT when the Properties editor sits in the left half of the window (the left tray), else RIGHT."""
    area, win = context.area, context.window
    if area is None or win is None:
        return 'RIGHT'
    return side_of_area(area.x, area.width, win.width)


def dock_tabs(kind, side):
    """The tabs of a dock: the kind's own, then the ones the user made (m3d_user.user_tabs)."""
    from m3d_user import user_tabs
    tabs = DOCK_TABS.get(kind, DOCK_TABS['MODEL'])
    return (*(tabs[side] or tabs['RIGHT']),
            *(Tab(t["id"], t["label"], 'MODELING_TOOLKIT', t["id"]) for t in user_tabs(kind, side)))


def active_page(context):
    """Page shown in the Properties editor under the mouse: the one stored on the workspace for its side
    when the kind has it, else the kind's first page, else the Modeling Toolkit."""
    side = side_of(context)
    pages = [t.page for t in dock_tabs(current_kind(context), side) if t.page]
    stored = getattr(context.workspace, "m3d_page_" + side.lower(), "")
    return stored if stored in pages else pages[0] if pages else "modeling_toolkit"


class _PagePanel:
    """Panel of a dock page: shown in the page's own Properties editor tab only."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "modeling_toolkit"
    page = ""

    @classmethod
    def poll(cls, context):
        page, hidden = m3d_edit.panel_placement(context, cls)
        return active_page(context) == page and (m3d_edit.editing() or not hidden) and cls.page_poll(context)

    def draw_header_preset(self, context):
        if m3d_edit.editing():
            m3d_edit.draw_panel_controls(self.layout, context, type(self))

    @classmethod
    def page_poll(cls, _context):
        return True


def all_tab(kind):
    """The stock Properties tabs, as the last tab of the row."""
    label, short = ALL_SETTINGS.get(kind, ("All Settings", "Settings"))
    return Tab('OBJECT', label, 'OBJECT', None, short)


# Header pixels at UI scale 1: around a tab's label, the "more" button, the buttons beside the tabs (editor type, tab menu).
TAB_PAD, MORE_WIDTH, HEADER_RESERVED = 30, 24, 76
EDIT_RESERVED = 80   # the new / rename / delete tab buttons of the edit mode


def text_width(text, scale):
    """Width in pixels of a tab button showing `text`."""
    import blf
    blf.size(0, 11 * scale)
    return blf.dimensions(0, text)[0] + TAB_PAD * scale


def fit_tabs(tabs, active, avail, width, more):
    """Split `tabs` for a header `avail` pixels wide: ([(tab, label drawn)], [tabs for the overflow menu]).
    `width(label)` is a button's width, `more` the overflow button's. The short labels are used when the full ones
    don't fit. The active tab (an id) is always drawn: when it would be in the overflow it takes the last place."""
    for compact in (False, True):
        labels = [(t.short_label or t.label) if compact else t.label for t in tabs]
        w = [width(label) for label in labels]
        if sum(w) <= avail:
            return list(zip(tabs, labels)), []
    room = avail - more
    shown = []
    while len(shown) < len(w) and sum(w[:len(shown) + 1]) <= room:
        shown.append(len(shown))
    i = next((i for i, t in enumerate(tabs) if t.id == active), None)
    if i is not None and i not in shown:
        shown[-1:] = []
        while shown and sum(w[j] for j in shown) + w[i] > room:
            shown.pop()
        shown.append(i)
    return [(tabs[j], labels[j]) for j in shown], [t for j, t in enumerate(tabs) if j not in shown]


def split_dock_tabs(context):
    """(drawn tabs, overflow tabs, active tab id) of this dock's header: its width decides how many tabs fit."""
    from m3d_user import hidden_tabs
    kind, side = current_kind(context), side_of(context)
    space, hidden, page = context.area.spaces.active, hidden_tabs(kind), active_page(context)
    tabs = [t for t in dock_tabs(kind, side) if t.id not in hidden] + [all_tab(kind)]
    active = next((t.id for t in tabs if space.context == t.context and t.page in {None, page}), None)
    scale = context.preferences.system.ui_scale
    header = next(r for r in context.area.regions if r.type == 'HEADER')
    reserved = HEADER_RESERVED + (EDIT_RESERVED if m3d_edit.editing() else 0)
    shown, more = fit_tabs(tabs, active, header.width - reserved * scale,
                           lambda label: text_width(label, scale), MORE_WIDTH * scale)
    return shown, more, active


def tab_button(layout, tab, label, **props):
    op = layout.operator("m3d.dock_tab" if tab.id == 'OBJECT' else "m3d.dock_page", text=label, **props)
    op.tab = tab.id   # m3d.dock_tab: 'OBJECT' shows the Scene settings when nothing is active (no Object tab then)


def draw_dock_tabs(layout, context):
    """Dock header: the tabs of this workspace's kind (hidden ones left out) and All Settings, as many as fit
    (the rest are in the "more" menu), then the tab menu. False when the dock shows one of the stock tabs instead."""
    space = context.space_data
    kind, side = current_kind(context), side_of(context)
    if space.context not in {t.context for t in dock_tabs(kind, side)} | DOCK_CONTEXTS:
        return False
    shown, more, active = split_dock_tabs(context)
    row = layout.row(align=True)
    for tab, label in shown:
        tab_button(row, tab, label, depress=tab.id == active)
    if more:
        row.menu("M3D_MT_dock_more", text="»")
    row.menu("M3D_MT_dock_tabs", text="", icon='DOWNARROW_HLT')
    if m3d_edit.editing():
        user = active.startswith("user_") if active else False
        m3d_edit.draw_tab_controls(layout, context, active, user)
    return True


class M3D_OT_dock_page(Operator):
    """Show a tab of this dock"""
    bl_idname = "m3d.dock_page"
    bl_label = "Dock Tab"
    bl_options = {'INTERNAL'}

    tab: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return "Show this tab"

    def execute(self, context):
        space = context.space_data
        side = side_of(context)
        tab = next((t for t in dock_tabs(current_kind(context), side) if t.id == self.tab), None)
        if tab is None or space is None or space.type != 'PROPERTIES':
            return {'CANCELLED'}
        space.context = tab.context
        if tab.page:
            setattr(context.workspace, "m3d_page_" + side.lower(), tab.page)
        if side == 'RIGHT' and current_kind(context) == 'RIG':
            from m3d_rig import remember_tab
            remember_tab(context, tab.id)   # The Rigging dock opens on this tab whenever this mode is entered.
        return {'FINISHED'}


class M3D_OT_dock_tab_toggle(Operator):
    """Show or hide a dock tab for this kind of workspace"""
    bl_idname = "m3d.dock_tab_toggle"
    bl_label = "Show / Hide Tab"
    bl_options = {'INTERNAL'}

    tab: bpy.props.StringProperty()

    def execute(self, context):
        from m3d_user import toggle_tab
        toggle_tab(current_kind(context), self.tab)
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class M3D_MT_dock_more(Menu):
    """The dock tabs that don't fit in the header"""
    bl_label = "More Tabs"

    def draw(self, context):
        for tab in split_dock_tabs(context)[1]:
            tab_button(self.layout, tab, tab.label)


def draw_tab_toggles(layout, kind, tabs):
    """A checkbox row per tab: ticked tabs are shown, a click shows / hides it (the same for the whole kind)."""
    from m3d_user import hidden_tabs
    hidden = hidden_tabs(kind)
    for tab in tabs:
        layout.operator("m3d.dock_tab_toggle", text=tab.label,
                        icon='CHECKBOX_DEHLT' if tab.id in hidden else 'CHECKBOX_HLT').tab = tab.id


class M3D_MT_dock_tabs(Menu):
    """Dock tabs: show or hide them (Reset Workspace and the rest are in Workspace Settings, top right)"""
    bl_label = "Dock Tabs"

    def draw(self, context):
        self.layout.label(text="Tabs")
        draw_tab_toggles(self.layout, current_kind(context), dock_tabs(current_kind(context), side_of(context)))


class M3D_PT_workspace_settings(Panel):
    """Settings of this workspace: reset it, show or hide its dock tabs, shelf, entry mode, shortcuts, defaults"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Workspace Settings"
    bl_ui_units_x = 15

    def draw(self, context):
        layout, ws, wm = self.layout, context.workspace, context.window_manager
        kind = workspace_kind(ws)
        layout.operator("m3d.workspace_reset", icon='FILE_REFRESH')
        layout.separator()
        if kind is None:   # Shading, Compositing...: no task dock, so no tabs to choose.
            layout.label(text="Dock tabs: this workspace has none")
        else:
            sides = DOCK_TABS[kind]
            right = dock_tabs(kind, 'RIGHT')
            left = dock_tabs(kind, 'LEFT') if sides['LEFT'] else ()
            layout.label(text="Right dock tabs" if left else "Dock tabs")
            draw_tab_toggles(layout, kind, right)
            if left:
                layout.label(text="Left tray tabs")
                draw_tab_toggles(layout, kind, left)
            layout.operator("m3d.dock_layout_reset", icon='LOOP_BACK')
        layout.separator()
        layout.prop(ws, "m3d_show_shelf")
        editing = m3d_edit.editing()
        layout.operator("m3d.edit_mode", text="Editing" if editing else "Click to Edit", icon='MODIFIER_ON', depress=editing)
        layout.label(text="Drag shelf buttons, Ctrl+Alt+click a button for a key,")
        layout.label(text="panel headers move panels. Right-click > Add to Shelf")
        layout.separator()
        row = layout.row()
        row.label(text="Entry mode")
        row.prop(ws, "object_mode", text="")
        layout.separator()
        layout.operator("screen.userpref_show", text="Keyboard Shortcuts...", icon='KEYINGSET').section = 'KEYMAP'
        layout.operator("wm.save_homefile", text="Save Layouts as Default", icon='FILE_TICK')
        layout.label(text="All workspaces, for new files")


# -----------------------------------------------------------------------------
# Reset Workspace

def factory_file():
    """The factory layouts: a copy of the built-in startup file, installed by the build."""
    return os.path.join(bpy.utils.system_resource('DATAFILES'), "m3d_factory_layout.blend")


class M3D_OT_workspace_reset(Operator):
    """Replace this workspace by its factory layout (docks, shelves and tabs you changed are reset)"""
    bl_idname = "m3d.workspace_reset"
    bl_label = "Reset Workspace"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Reset Workspace", confirm_text="Reset",
            message="Replace \"%s\" by its factory layout?" % context.workspace.name)

    def execute(self, context):
        ws = context.workspace
        name = WORKSPACE_NAMES.get(_base_name(ws.name), _base_name(ws.name))
        path = factory_file()
        if not os.path.exists(path):
            self.report({'ERROR'}, "Factory layouts file not found: " + path)
            return {'CANCELLED'}
        with bpy.data.libraries.load(path) as (src, _dst):
            known = name in src.workspaces
        if not known:
            self.report({'WARNING'}, "\"%s\" has no factory layout" % ws.name)
            return {'CANCELLED'}
        before = {w.name for w in bpy.data.workspaces}
        try:
            bpy.ops.workspace.append_activate(idname=name, filepath=path)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        fresh = [w for w in bpy.data.workspaces if w.name not in before]
        if not fresh:
            return {'CANCELLED'}
        # The window switches to the appended workspace on the next event; then the old one can go.
        bpy.app.timers.register(lambda: _finish_reset(ws.name, fresh[0].name, name), first_interval=0.3)
        return {'FINISHED'}


def _finish_reset(old_name, new_name, name):
    old, new = bpy.data.workspaces.get(old_name), bpy.data.workspaces.get(new_name)
    win = bpy.context.window_manager.windows[0]
    if old is None or new is None:
        return None
    if win.workspace == old:
        return 0.3
    screens = list(old.screens)
    bpy.data.batch_remove({old})
    bpy.data.batch_remove({s for s in screens if s.users == 0})
    new.name = old_name
    for screen in new.screens:
        if screen.name != new.name and screen.name.startswith(_base_name(old_name)):
            screen.name = new.name
    from m3d_mode import m3d_startup_layout
    m3d_startup_layout(screens=list(new.screens))
    return None


classes = (
    M3D_OT_workspace,
    M3D_OT_dock_page,
    M3D_OT_dock_tab_toggle,
    M3D_MT_dock_more,
    M3D_MT_dock_tabs,
    M3D_PT_workspace_settings,
    M3D_OT_workspace_reset,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    ws = bpy.types.WorkSpace
    ws.m3d_kind = bpy.props.StringProperty(name="Kind", description="Maelstrom3D workspace kind (MODEL, SCULPT, ...)")
    ws.m3d_page_right = bpy.props.StringProperty(description="Active page of the right-hand dock")
    ws.m3d_page_left = bpy.props.StringProperty(description="Active page of the left tray")
    ws.m3d_show_shelf = bpy.props.BoolProperty(
        name="Show Shelf", default=True, update=_shelf_visibility_changed,
        description="Show the shelf tabs and the shelf under the Status Line (off: the viewport gets the space; "
                    "the Custom shelf is then in the left tray in Sculpt). The C top bar reads this property")
    bpy.app.timers.register(_follow_workspace, first_interval=0.5, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_follow_workspace):
        bpy.app.timers.unregister(_follow_workspace)
    ws = bpy.types.WorkSpace
    del ws.m3d_show_shelf, ws.m3d_page_left, ws.m3d_page_right, ws.m3d_kind
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
