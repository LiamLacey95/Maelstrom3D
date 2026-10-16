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


def use_bound_rig(context):
    """Entering Pose Mode with a bound mesh active (or selected) would leave the workspace in Object Mode: make its
    skeleton the active, selected object instead."""
    from m3d_rig import armature_of
    layer = context.view_layer
    ob = context.active_object
    if ob is not None and ob.type == 'ARMATURE':
        return
    meshes = [ob] if ob is not None else []
    rig = next((r for r in map(armature_of, meshes + list(context.selected_objects))
                if r is not None and r.name in layer.objects and r.visible_get()), None)
    if rig is None:
        return
    if ob is not None and ob.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in context.selected_objects:
        other.select_set(False)
    rig.select_set(True)
    layer.objects.active = rig


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
            ws = restore_workspace(KINDS[self.kind][0])   # (deleted: its factory layout comes back)
            if ws is None:
                self.report({'WARNING'}, "No %s workspace in this file" % KINDS[self.kind][0])
                return {'CANCELLED'}
            self.report({'INFO'}, "Restored %s (its factory layout)" % ws.name)
        wm = context.window_manager
        win = context.window or (wm.windows[0] if wm.windows else None)
        if KINDS[self.kind][2] in MESH_MODES:
            use_selected_mesh(context)
        elif KINDS[self.kind][2] == 'POSE':
            use_bound_rig(context)
        # A high poly is hidden (Sculpt shows it) before the window changes, so the redraw never draws the wrong one.
        import m3d_pair
        old = win.workspace if win is not None else context.workspace
        if win is not None and old != ws and m3d_pair.slow_switch(context, self.kind, ws):
            wait(win, old, "Opening %s..." % KINDS[self.kind][0])
        hold = m3d_pair.before_switch(context, old, ws)
        if win is not None:
            win.workspace = ws
            if hold:
                m3d_pair.hold_object_mode(ws)   # a huge mesh stays in Object Mode here (the note says so)
        wm.m3d_menu_set = KINDS[self.kind][3]
        return {'FINISHED'}


def wait(win, ws, text):
    """A switch that takes a moment: the wait cursor and `text` in the status bar now (the window is drawn once to show
    them), both gone once the switch is over (a timer runs after the next redraw)."""
    win.cursor_modal_set('WAIT')
    ws.status_text_set(text)
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except RuntimeError:
        pass   # (no window to draw: a script)
    name = ws.name

    def done():
        for w in bpy.context.window_manager.windows:
            w.cursor_modal_restore()
        old = bpy.data.workspaces.get(name)
        if old is not None:
            old.status_text_set(None)
    bpy.app.timers.register(done, first_interval=0.0)


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
        from m3d_pair import follow as follow_pair
        follow_pair(wm)    # A high poly is parked / shown when Sculpt is left / entered any other way.
        from m3d_texture import follow as follow_texture
        follow_texture(wm)  # The 2D view of the Texture workspace frames its image.
    return 0.25


# -----------------------------------------------------------------------------
# Dock tabs and pages

# A dock tab shows a native Properties context, or a page: panels with bl_context "modeling_toolkit" whose
# page id is the active one for that workspace and side. `short_label` is drawn when the dock is too narrow for the labels.
# `hidden`: a page the dock can show without a tab of its own (Texture's Bake page: the Bake Mesh Maps button opens it).
Tab = namedtuple("Tab", "id label context page short_label hidden", defaults=("", False))
_CHANNEL_BOX = Tab("channel_box", "Channel Box / Layer Editor", 'CHANNEL_BOX', None, "Channel Box")
_TOOLKIT = Tab("modeling_toolkit", "Modeling Toolkit", 'MODELING_TOOLKIT', "modeling_toolkit", "Toolkit")
_TOOL = Tab("tool", "Tool Settings", 'TOOL', None, "Tool")

# kind -> side -> tabs (an empty side uses the right-hand tabs). Phases 1-6 replace the entries of their kind.
DOCK_TABS = {kind: {'RIGHT': (_CHANNEL_BOX, _TOOLKIT, _TOOL), 'LEFT': ()} for kind in KINDS}
# Sculpt: the brush tray on the left, task tabs on the right (pages: m3d_sculpt.py).
DOCK_TABS['SCULPT'] = {
    'RIGHT': tuple(Tab("sculpt_" + page, label, 'MODELING_TOOLKIT', "sculpt_" + page) for page, label in (
        ("geometry", "Geometry"), ("objects", "Objects"), ("mask", "Mask"), ("face_sets", "Face Sets"),
        ("deform", "Deform"), ("paint", "Paint"), ("display", "Display"))),
    'LEFT': (Tab("sculpt_brushes", "Brushes", 'MODELING_TOOLKIT', "sculpt_brushes"),),
}
# UV: the UV tools on the right (pages: m3d_uv.py); no left tray.
DOCK_TABS['UV'] = {
    'RIGHT': tuple(Tab("uv_" + page, label, 'MODELING_TOOLKIT', "uv_" + page) for page, label in (
        ("unwrap", "Unwrap"), ("arrange", "Arrange"), ("check", "Check"), ("create", "Create"), ("udim", "UDIM"))),
    'LEFT': (),
}
# Texture: one Properties editor for each part of the layout (TEXTURE_ROLES, side_of): the tool strip, the Assets panel, the
# Texture Set List, the dock (Layers | Texture Set Settings, and the Bake page behind Bake Mesh Maps), Properties and the
# dock strip. Only the dock has tabs (pages: m3d_texture.py; the Assets page: m3d_library.py).
_TEX = lambda page, label, *rest: Tab("tex_" + page, label, 'MODELING_TOOLKIT', "tex_" + page, *rest)
DOCK_TABS['TEXTURE'] = {
    'RIGHT': (_TEX("layers", "Layers"), _TEX("settings", "Texture Set Settings", "Settings"), _TEX("bake", "Bake Mesh Maps", "Bake", True)),
    'LEFT': (),
    'TOOLS': (_TEX("tools", "Tools"),),
    'ASSETS': (_TEX("assets", "Assets"),),
    'SETS': (_TEX("sets", "Texture Sets"),),
    'PROPS': (_TEX("props", "Properties"),),
    'DOCKBAR': (_TEX("dockbar", "Dock"),),
}
# Files saved before that layout (a brush tray on the left, the dock with six tabs on the right) keep it until Reset Workspace.
DOCK_TABS['TEXTURE_OLD'] = {
    'RIGHT': tuple(_TEX(page, label) for page, label in (
        ("layers", "Layers"), ("brush", "Brush"), ("library", "Library"), ("bake", "Bake"), ("export", "Export"),
        ("display", "Display"))),
    'LEFT': (_TEX("brushes", "Brushes"),),
}
# Rigging: Channel Box first (the same tab as in Animation), the task tabs, bone collections under the Outliner on the left
# (pages: m3d_rig.py).
DOCK_TABS['RIG'] = {
    'RIGHT': (Tab("channel_box", "Channel Box", 'CHANNEL_BOX', None),
              *(Tab("rig_" + page, label, 'MODELING_TOOLKIT', "rig_" + page, *short) for page, label, *short in (
                  ("skeleton", "Skeleton"), ("controls", "Controls & Constraints", "Controls"), ("skin", "Skin"),
                  ("drive", "Drive"), ("test", "Test"), ("collections", "Collections")))),
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


# The Properties editors of the Texture layout, left to right and top to bottom (see texture_role). The dock keeps the name
# RIGHT: it is the one with tabs, and the page it shows is the workspace's m3d_page_right.
TEXTURE_ROLES = ('TOOLS', 'ASSETS', 'SETS', 'RIGHT', 'PROPS', 'DOCKBAR')
NARROW = 0.05   # an editor narrower than this share of the window is one of the strips (tool strip, dock strip)


def tabs_kind(context):
    """Key of DOCK_TABS for this workspace: the kind, except Texture in a file saved with the old layout (TEXTURE_OLD)."""
    kind = current_kind(context)
    if kind == 'TEXTURE' and getattr(context.workspace, "m3d_layout", 1) < 1:
        return 'TEXTURE_OLD'
    return kind


def texture_clean(context):
    """Is this the Texture workspace of the new layout (Workspace.m3d_layout 1)? Its 3D view and 2D view headers show only what texturing
    needs; the old layout and every other workspace keep Blender's headers."""
    return current_kind(context) == 'TEXTURE' and tabs_kind(context) == 'TEXTURE'


def texture_role(context):
    """Which Properties editor of the Texture layout the area is. Where it sits decides: the narrow ones at the window's edges
    are the tool strip (left) and the dock strip (right), the wide one on the left is Assets, and the wide ones on the right,
    from the top, are the Texture Set List, the dock and Properties (with fewer of them the top ones are missing)."""
    area, win, screen = context.area, context.window, context.screen
    width = max(win.width, 1)
    left = side_of_area(area.x, area.width, win.width) == 'LEFT'
    if area.width < NARROW * width:
        return 'TOOLS' if left else 'DOCKBAR'
    if left:
        return 'ASSETS'
    column = [area]
    if screen is not None:
        column = sorted((a for a in screen.areas if a.type == 'PROPERTIES' and a.width >= NARROW * width
                         and side_of_area(a.x, a.width, win.width) == 'RIGHT'), key=lambda a: -a.y)
    i = next((i for i, a in enumerate(column) if a == area), None)
    if i is None:
        return 'RIGHT'
    names = (('RIGHT',), ('RIGHT', 'PROPS'), ('SETS', 'RIGHT', 'PROPS'))[min(len(column), 3) - 1]
    return names[min(i, len(names) - 1)]


# --- Narrow windows: a window smaller than the layout was made for shrinks every editor alike; the trays and docks keep the
# size their panels fit in (pixels at UI scale 1) and the views give up the room. Done once for each window size and screen, so
# an editor the user drags narrower afterwards stays so.
MIN_SIZES = {
    'SCULPT': (('LEFT', 'W', 220), ('RIGHT', 'W', 300)),
    'TEXTURE': (('ASSETS', 'W', 200), ('SETS', 'W', 330), ('SETS', 'H', 165)),
    'RIG': (('LEFT', 'W', 220),),   # (the bone collection tree under the Outliner: names, eye, solo)
}
_fitted = {}   # window pointer -> (width, height, screen pointer) it was fitted for


def area_role(win, area):
    """The role of a Properties editor of the window's workspace, as side_of gives it (without a context)."""
    from types import SimpleNamespace
    if workspace_kind(win.workspace) == 'TEXTURE' and getattr(win.workspace, "m3d_layout", 1) >= 1:
        return texture_role(SimpleNamespace(area=area, window=win, screen=win.screen))
    return side_of_area(area.x, area.width, win.width)


def watch_window(context):
    """From the Status Line's draw: when the window got another size (or shows another workspace), fit_window a moment later
    (drawing may not change the screen)."""
    win = context.window
    if win is None or workspace_kind(context.workspace) not in MIN_SIZES:
        return
    key, now = win.as_pointer(), (win.width, win.height, win.screen.as_pointer())
    if _fitted.get(key) != now:
        _fitted[key] = now
        bpy.app.timers.register(lambda: fit_window(key), first_interval=0.1)


def fit_window(key):
    """Make the trays and docks of the window `key` (a pointer) at least as big as MIN_SIZES says, by moving the edge between
    each and the view next to it (screen.area_move moves the whole edge: the column of editors that share it moves along). A timer:
    area_move works only while the pointer is over no editor (outside the window, or on an edge between two), so it tries again
    a moment later until then."""
    win = next((w for w in bpy.context.window_manager.windows if w.as_pointer() == key), None)
    if win is None or _fitted.get(key) != (win.width, win.height, win.screen.as_pointer()):
        return None   # (gone, or another size: the next draw asks again)
    with bpy.context.temp_override(window=win, screen=win.screen):
        if not bpy.ops.screen.area_move.poll():
            return 0.25   # ponytail: polls until the pointer leaves the editors; a C path that ignores the pointer if this lags
        scale = bpy.context.preferences.system.ui_scale or 1.0
        for role, side, size in MIN_SIZES.get(workspace_kind(win.workspace), ()):
            area = next((a for a in win.screen.areas if a.type == 'PROPERTIES' and area_role(win, a) == role), None)
            need = int(size * scale) - (area.width if side == 'W' else area.height) if area is not None else 0
            if need <= 0:
                continue
            if side == 'H':   # (the bottom edge goes down)
                x, y, delta = area.x + area.width // 2, area.y - 1, -need
            elif area.x + area.width / 2 < win.width / 2:   # (a column on the left: its right edge goes right)
                x, y, delta = area.x + area.width, area.y + area.height // 2, need
            else:   # (on the right: its left edge goes left)
                x, y, delta = area.x - 1, area.y + area.height // 2, -need
            try:
                bpy.ops.screen.area_move(x=x, y=y, delta=delta)
            except RuntimeError:
                pass
    return None


def side_of(context):
    """LEFT when the Properties editor sits in the left half of the window (the left tray), else RIGHT; in the Texture layout
    the role of the editor (TEXTURE_ROLES)."""
    area, win = context.area, context.window
    if area is None or win is None:
        return 'RIGHT'
    if tabs_kind(context) == 'TEXTURE':
        return texture_role(context)
    return side_of_area(area.x, area.width, win.width)


_BASE_KIND = {'TEXTURE_OLD': 'TEXTURE'}   # the kind whose user tabs and hidden tabs a tab table belongs to


def dock_tabs(kind, side):
    """The tabs of a dock: the kind's own, then the ones the user made (m3d_user.user_tabs)."""
    from m3d_user import user_tabs
    tabs = DOCK_TABS.get(kind, DOCK_TABS['MODEL'])
    return (*(tabs.get(side) or tabs['RIGHT']),
            *(Tab(t["id"], t["label"], 'MODELING_TOOLKIT', t["id"]) for t in user_tabs(_BASE_KIND.get(kind, kind), side)))


def active_page(context):
    """Page shown in the Properties editor under the mouse: the one stored on the workspace for its side
    when the kind has it, else the kind's first page, else the Modeling Toolkit."""
    side = side_of(context)
    pages = [t.page for t in dock_tabs(tabs_kind(context), side) if t.page]
    stored = getattr(context.workspace, "m3d_page_" + side.lower(), "")
    return stored if stored in pages else pages[0] if pages else "modeling_toolkit"


# Tab table key -> function(context, active page) giving the pages whose panels the editor draws. A kind that has none draws the
# active page's panels (Texture: m3d_texture.py, where the Properties editor draws the pages of what is selected).
PAGE_SETS = {}


def pages_shown(context):
    page = active_page(context)
    spread = PAGE_SETS.get(tabs_kind(context))
    return spread(context, page) if spread is not None else {page}


class _PagePanel:
    """Panel of a dock page: shown in the page's own Properties editor tab only."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "modeling_toolkit"
    page = ""

    @classmethod
    def poll(cls, context):
        page, hidden = m3d_edit.panel_placement(context, cls)
        return page in pages_shown(context) and (m3d_edit.editing() or not hidden) and cls.page_poll(context)

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
    kind, side = tabs_kind(context), side_of(context)
    space, hidden, page = context.area.spaces.active, hidden_tabs(current_kind(context)), active_page(context)
    tabs = [t for t in dock_tabs(kind, side) if t.id not in hidden and not t.hidden]
    if kind != 'TEXTURE':   # (the Texture dock has two tabs and no stock settings behind them)
        tabs.append(all_tab(kind))
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


# (tabs key, side) -> function(layout, context) drawing a header of its own (Texture: the title or the buttons of an editor).
HEADERS = {}


def draw_tab_row(layout, context):
    """The dock's tabs (hidden ones left out) and All Settings, as many as fit (the rest are in the "more" menu), then the
    tab menu."""
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


def draw_dock_tabs(layout, context):
    """Dock header: the tabs of this workspace's kind (hidden ones left out) and All Settings, as many as fit
    (the rest are in the "more" menu), then the tab menu. False when the dock shows one of the stock tabs instead."""
    space = context.space_data
    kind, side = tabs_kind(context), side_of(context)
    all_settings = space.context not in {t.context for t in dock_tabs(kind, side)} | DOCK_CONTEXTS
    sync_nav_bar(context, all_settings)
    if all_settings:
        return False
    drawer = HEADERS.get((kind, side))
    if drawer is not None:
        drawer(layout, context)
    else:
        draw_tab_row(layout, context)
    return True


# Workspaces whose docks (both sides) show Blender's column of stock tabs (the navigation bar) only with All Settings: the
# dock's own tabs are in its header. Every task workspace; the extra ones (Shading...) keep Blender's.
NAV_BAR_ONLY_IN_ALL_SETTINGS = set(KINDS)
_nav_pending = set()   # areas (pointers) whose navigation bar is about to be shown or hidden


def sync_nav_bar(context, all_settings):
    """Show the dock's navigation bar while it shows All Settings, hide it otherwise (task workspaces). Called from the
    header's draw, which can't change regions: a timer toggles it right after."""
    area = context.area
    if not isinstance(area, bpy.types.Area) or workspace_kind(context.workspace) not in NAV_BAR_ONLY_IN_ALL_SETTINGS:
        return
    nav = next((r for r in area.regions if r.type == 'NAVIGATION_BAR'), None)
    key = area.as_pointer()
    if nav is None or (nav.width > 1) == all_settings or key in _nav_pending:
        return
    _nav_pending.add(key)
    bpy.app.timers.register(lambda: _toggle_nav_bar(key, all_settings), first_interval=0.0)


def _toggle_nav_bar(key, show):
    _nav_pending.discard(key)
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() == key:
                nav = next((r for r in area.regions if r.type == 'NAVIGATION_BAR'), None)
                if nav is not None and (nav.width > 1) != show:
                    with bpy.context.temp_override(window=win, area=area, region=nav):
                        bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
                return None
    return None


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
        tab = next((t for t in dock_tabs(tabs_kind(context), side) if t.id == self.tab), None)
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
        draw_tab_toggles(self.layout, current_kind(context),
                         [t for t in dock_tabs(tabs_kind(context), side_of(context)) if not t.hidden])


class M3D_PT_workspace_settings(Panel):
    """Workspace settings: reset this workspace, show or hide its dock tabs, shelf, entry mode, shortcuts, defaults"""
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
            key = tabs_kind(context)
            sides = DOCK_TABS[key]
            right = [t for t in dock_tabs(key, 'RIGHT') if not t.hidden]
            left = dock_tabs(key, 'LEFT') if sides['LEFT'] else ()
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
        if ws.object_mode in {'EDIT', 'TEXTURE_PAINT'}:
            row = layout.row()
            row.label(text="Face limit")
            row.prop(ws, "m3d_face_limit", text="")
        if kind == 'TEXTURE':
            import m3d_bakeq
            layout.separator()
            layout.prop(bpy.context.scene.m3d_tex, "bake_gpu")
            m3d_bakeq.check_gpu_soon()
            layout.label(text=m3d_bakeq.device_note(bpy.context), icon='INFO', translate=False)   # (a hint: the normal text colour)
        layout.separator()
        layout.operator("screen.userpref_show", text="Keyboard Shortcuts...", icon='KEYINGSET').section = 'KEYMAP'
        layout.operator("m3d.save_layouts_default", icon='FILE_TICK')
        layout.label(text="All workspaces, for new files")
        layout.operator("m3d.workspace_delete", icon='TRASH')


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
        try:
            fresh = append_factory(name)
        except RuntimeError as err:
            self.report({'ERROR'}, "Could not load the factory layout: " + str(err).strip().split(": ", 1)[-1])
            return {'CANCELLED'}
        if fresh is None:
            self.report({'WARNING'}, "\"%s\" has no factory layout" % ws.name)
            return {'CANCELLED'}
        # The window switches to the appended workspace on the next event; then the old one can go.
        bpy.app.timers.register(lambda: _finish_reset(ws.name, fresh.name, name), first_interval=0.3)
        return {'FINISHED'}


def append_factory(name):
    """Append the factory layout of the workspace `name` (the window shows it from the next event on): the new workspace,
    or None without the factory layouts file or that layout in it. RuntimeError when appending fails."""
    path = factory_file()
    if not os.path.exists(path):
        return None
    with bpy.data.libraries.load(path) as (src, _dst):
        if name not in src.workspaces:
            return None
    before = {w.name for w in bpy.data.workspaces}
    bpy.ops.workspace.append_activate(idname=name, filepath=path)
    return next((w for w in bpy.data.workspaces if w.name not in before), None)


def restore_workspace(name):
    """A task workspace the file lacks (it was deleted) from its factory layout, set up as at startup; None when it can't."""
    try:
        ws = append_factory(name)
    except RuntimeError:
        return None
    if ws is not None:
        from m3d_mode import m3d_startup_layout
        m3d_startup_layout(screens=list(ws.screens))
    return ws


class M3D_OT_workspace_delete(Operator):
    """Delete this workspace (a task workspace comes back from its factory layout with its F-key)"""
    bl_idname = "m3d.workspace_delete"
    bl_label = "Delete Workspace"

    @classmethod
    def poll(cls, context):
        return len(bpy.data.workspaces) > 1

    def invoke(self, context, event):
        ws = context.workspace
        kind = workspace_kind(ws)
        back = "%s brings back its factory layout" % KINDS[kind][1] if kind else "this can't be undone"
        return context.window_manager.invoke_confirm(self, event, title="Delete Workspace", confirm_text="Delete",
                                                     message="Delete \"%s\"? (%s)" % (ws.name, back))

    def execute(self, _context):
        return bpy.ops.workspace.delete()


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
    M3D_OT_workspace_delete,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    ws = bpy.types.WorkSpace
    ws.m3d_kind = bpy.props.StringProperty(name="Kind", description="Maelstrom3D workspace kind (MODEL, SCULPT, ...)")
    ws.m3d_page_right = bpy.props.StringProperty(description="Active page of the right-hand dock")
    ws.m3d_page_left = bpy.props.StringProperty(description="Active page of the left tray")
    ws.m3d_layout = bpy.props.IntProperty(
        name="Layout", default=0, min=0, max=9,
        description="Version of the workspace's layout (the Texture workspace: 0 is the brush tray with the six-tab dock, "
                    "1 the tool strip, Assets, Texture Sets, Layers, Properties and the dock strip; the Animation workspace: "
                    "1 one transport row, the Time Slider's). Reset Workspace brings the newest")
    ws.m3d_show_shelf = bpy.props.BoolProperty(
        name="Show Shelf", default=True, update=_shelf_visibility_changed,
        description="Show the shelf tabs and the shelf under the Status Line (off: the viewport gets the space; "
                    "the Custom shelf is then in the left tray in Sculpt). The C top bar reads this property")
    ws.m3d_face_limit = bpy.props.IntProperty(
        name="Face Limit", default=500_000, min=0, soft_max=5_000_000, step=10000,
        description="A mesh with more faces than this opens in Object Mode here, so a huge high poly is not rebuilt for "
                    "Edit Mode or painting (0: no limit)")
    bpy.app.timers.register(_follow_workspace, first_interval=0.5, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_follow_workspace):
        bpy.app.timers.unregister(_follow_workspace)
    ws = bpy.types.WorkSpace
    del ws.m3d_face_limit, ws.m3d_show_shelf, ws.m3d_layout, ws.m3d_page_left, ws.m3d_page_right, ws.m3d_kind
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
