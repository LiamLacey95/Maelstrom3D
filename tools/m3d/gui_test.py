# SPDX-License-Identifier: GPL-2.0-or-later
"""
Interactive self-check for Maelstrom3D behaviour that needs a real window (gizmo drags, held keys).

    blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result-file>

Writes "FAILS: [...]" to <result-file> and quits.
"""

import sys

import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector

import m3d_mode
import m3d_ui
import m3d_user
import m3d_workspace

OUT = sys.argv[sys.argv.index("--") + 1]
fails = []
steps = []


class Tee:
    """Keeps a copy of everything written to a stream: Python errors in UI drawing print there."""
    def __init__(self, stream):
        self.stream, self.buf = stream, []

    def write(self, text):
        self.buf.append(text)
        return self.stream.write(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


stderr_tee = sys.stderr = Tee(sys.stderr)
sys.stdout = Tee(sys.stdout)


def check(cond, msg):
    if not cond:
        fails.append(msg)


def workspace_screen(kind):
    return m3d_workspace.workspace_screens(kind)[0]


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return win, area, region


def to_window(region, co):
    return int(region.x + co.x), int(region.y + co.y)


def event(type, value='NOTHING', xy=None, **mods):
    win, _area, _region = view3d()
    x, y = xy if xy else (win.width // 2, win.height // 2)
    win.event_simulate(type=type, value=value, x=x, y=y, **mods)


def step(fn):
    steps.append(fn)
    return fn


@step
def setup():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
        bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'FACE'})
        bpy.ops.wm.tool_set_by_id(name="builtin.move")
        bpy.ops.view3d.view_all(center=True)


GIZMO = {}


def aim_x_arrow():
    """Point GIZMO start/end along the manipulator's X arrow (selection centre, or the object origin)."""
    _win, area, region = view3d()
    rv3d = area.spaces.active.region_3d
    ob = bpy.context.active_object
    center = ob.matrix_world.translation
    if ob.mode == 'EDIT':
        verts = [v.co for v in bmesh.from_edit_mesh(ob.data).verts if v.select]
        center = ob.matrix_world @ (sum(verts, Vector()) / len(verts))
    p0 = location_3d_to_region_2d(region, rv3d, center)
    p1 = location_3d_to_region_2d(region, rv3d, center + Vector((1, 0, 0)))
    direction = (p1 - p0).normalized()
    GIZMO["start"] = to_window(region, p0 + direction * 45)
    GIZMO["end"] = to_window(region, p0 + direction * 120)


@step
def hover_x_arrow():
    aim_x_arrow()
    GIZMO["faces"] = len(bpy.context.active_object.data.polygons)
    event('MOUSEMOVE', xy=GIZMO["start"])


@step
def hover_again():
    x, y = GIZMO["start"]
    event('MOUSEMOVE', xy=(x + 1, y))
    event('MOUSEMOVE', xy=(x, y))


@step
def plain_drag():
    drag(shift=False)


@step
def plain_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["end"])


@step
def hover_back():
    aim_x_arrow()   # The plain drag moved the manipulator.
    event('MOUSEMOVE', xy=GIZMO["start"])


@step
def hover_back2():
    x, y = GIZMO["start"]
    event('MOUSEMOVE', xy=(x + 1, y))
    event('MOUSEMOVE', xy=(x, y))


def drag(shift):
    if shift:
        event('LEFT_SHIFT', 'PRESS', GIZMO["start"], shift=True)
    event('LEFTMOUSE', 'PRESS', GIZMO["start"], shift=shift)
    x0, y0 = GIZMO["start"]
    x1, y1 = GIZMO["end"]
    for i in range(1, 11):
        event('MOUSEMOVE', xy=(x0 + (x1 - x0) * i // 10, y0 + (y1 - y0) * i // 10), shift=shift)


@step
def shift_drag():
    drag(shift=True)


@step
def shift_drag_more():
    x0, y0 = GIZMO["start"]
    x1, y1 = GIZMO["end"]
    for i in range(1, 6):
        event('MOUSEMOVE', xy=(x1 + (x1 - x0) * i // 5, y1 + (y1 - y0) * i // 5), shift=True)
    GIZMO["end"] = (2 * x1 - x0, 2 * y1 - y0)


@step
def release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["end"], shift=True)
    event('LEFT_SHIFT', 'RELEASE', GIZMO["end"])


@step
def check_extrude():
    ob = bpy.context.active_object
    ob.update_from_editmode()
    ops = [o.bl_idname for o in bpy.context.window_manager.operators]
    check(len(ob.data.polygons) > GIZMO["faces"],
          "shift-drag on gizmo did not extrude (ops: %s, gizmo %s, tool %s)" % (
              ops[-3:], GIZMO, bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH').idname))
    # Dragging the X arrow must extrude along X (it used to always follow Z).
    translate = [o for o in bpy.context.window_manager.operators if o.bl_idname == "MESH_OT_extrude_context_move"]
    axis = Matrix(translate[-1].properties.TRANSFORM_OT_translate.orient_matrix).col[2] if translate else None
    check(axis is not None and abs(axis.x) > 0.99, "shift-drag on X arrow did not extrude along X (axis %s)" % (axis,))
    hud = hud_region()
    check(hud is None or hud.height <= 1, "options box opened for Shift+drag extrude")


@step
def pivot_press():
    bpy.ops.object.mode_set(mode='OBJECT')
    event('MOUSEMOVE', xy=GIZMO["start"])
    event('D', 'PRESS', GIZMO["start"])


@step
def pivot_held():
    check(bpy.context.tool_settings.use_transform_data_origin, "D press did not enter pivot mode")
    event('D', 'RELEASE', GIZMO["start"])


@step
def pivot_released():
    check(not bpy.context.tool_settings.use_transform_data_origin, "D release did not leave pivot mode")
    win, area, _region = view3d()
    GIZMO["quad"] = len(area.spaces.active.region_quadviews)
    event('SPACE', 'PRESS', GIZMO["start"])
    event('SPACE', 'RELEASE', GIZMO["start"])


@step
def space_tap():
    _win, area, _region = view3d()
    check(len(area.spaces.active.region_quadviews) != GIZMO["quad"], "Space tap did not toggle four view")
    event('SPACE', 'PRESS', GIZMO["start"])   # Back to a single view for the next drags.
    event('SPACE', 'RELEASE', GIZMO["start"])


@step
def object_shift_drag_setup():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.tool_set_by_id(name="builtin.move")
    GIZMO["objects"] = len(bpy.data.objects)
    aim_x_arrow()
    event('MOUSEMOVE', xy=GIZMO["start"])


@step
def object_shift_drag_hover():
    x, y = GIZMO["start"]
    event('MOUSEMOVE', xy=(x + 1, y))
    event('MOUSEMOVE', xy=(x, y))


@step
def object_shift_drag():
    drag(shift=True)


@step
def object_shift_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["end"], shift=True)
    event('LEFT_SHIFT', 'RELEASE', GIZMO["end"])


@step
def object_shift_check():
    check(len(bpy.data.objects) == GIZMO["objects"] + 1, "shift-drag on gizmo in object mode did not duplicate "
          "(mode %s, ops %s, sel %s)" % (bpy.context.mode, [o.bl_idname for o in bpy.context.window_manager.operators][-3:],
                                       [o.name for o in bpy.context.selected_objects]))
    event('W', 'PRESS', GIZMO["start"])
    event('LEFTMOUSE', 'PRESS', GIZMO["start"])


@step
def w_marking_menu():
    import m3d_marking
    check(m3d_marking.M3D_OT_key_marking_menu.last_menu == "M3D_MT_move_mm", "W + left click marking menu")
    event('LEFTMOUSE', 'RELEASE', GIZMO["start"])
    event('W', 'RELEASE', GIZMO["start"])
    event('ESC', 'PRESS', GIZMO["start"])
    GIZMO["soft"] = bpy.context.tool_settings.use_proportional_edit_objects
    event('B', 'PRESS', GIZMO["start"])
    event('B', 'RELEASE', GIZMO["start"])


@step
def b_tap():
    check(bpy.context.tool_settings.use_proportional_edit_objects != GIZMO["soft"], "B tap did not toggle soft select")
    _win, area, _region = view3d()
    GIZMO["distance"] = area.spaces.active.region_3d.view_distance
    area.spaces.active.region_3d.view_distance *= 2


@step
def view_changed():
    pass  # Let the view watcher record the zoom.


@step
def view_undo():
    event('LEFT_BRACKET', 'PRESS', GIZMO["start"])


@step
def view_undone():
    _win, area, _region = view3d()
    import m3d_marking
    check(abs(area.spaces.active.region_3d.view_distance - GIZMO["distance"]) < 1e-4,
          "[ did not undo the view change (now %s, was %s, history %s)" % (
              area.spaces.active.region_3d.view_distance, GIZMO["distance"],
              {k: (len(v["stack"]), v["index"]) for k, v in m3d_marking._view_history.items()}))
    consoles = [a.spaces.active.language for a in workspace_screen('MODEL').areas if a.type == 'CONSOLE']
    check(consoles == ['mel'], "command line is not MEL: %r" % consoles)


@step
def dock_tabs_object():
    # Draw every Maya dock tab (draw errors show up as tracebacks in Blender's output).
    GIZMO["dock"] = [a for a in workspace_screen('MODEL').areas if a.type == 'PROPERTIES'][0].spaces.active
    GIZMO["dock"].context = 'MODELING_TOOLKIT'


@step
def dock_tabs_edit():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='EDIT')


@step
def dock_tabs_tool():
    GIZMO["dock"].context = 'TOOL'


@step
def dock_tabs_back():
    GIZMO["dock"].context = 'CHANNEL_BOX'
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')


@step
def startup_panels():
    viewport_sidebars = [a.spaces.active.show_region_ui for a in workspace_screen('MODEL').areas
                         if a.type == 'VIEW_3D']
    check(not any(viewport_sidebars), "viewport sidebar open at startup")
    lenses = {a.spaces.active.lens for a in workspace_screen('MODEL').areas if a.type == 'VIEW_3D'}
    check(lenses == {70.0}, "viewport lens is not Maya's field of view: %r" % lenses)
    uv = [a for a in workspace_screen('UV').areas if a.type == 'IMAGE_EDITOR']
    check(uv and uv[0].spaces.active.show_region_ui, "UV Toolkit not docked in the UV Editor")


def hud_region():
    return next((r for r in view3d()[1].regions if r.type == 'HUD'), None)


@step
def options_box_shortcut():
    # A shortcut (quick command) never opens the options box.
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
    km = bpy.context.window_manager.keyconfigs.user.keymaps["Mesh"]
    km.keymap_items.new("mesh.subdivide", 'F19', 'PRESS')
    kmi = km.keymap_items.new("m3d.tool", 'F18', 'PRESS')
    kmi.properties.idname = "mesh.bevel"
    kmi.properties.props = "{'offset_type': 'PERCENT'}"
    bpy.context.window_manager.keyconfigs.update()
    GIZMO["cursor"] = (region.x + region.width * 2 // 3, region.y + region.height * 2 // 3)
    event('MOUSEMOVE', xy=GIZMO["cursor"])
    event('F19', 'PRESS', GIZMO["cursor"])
    event('F19', 'RELEASE', GIZMO["cursor"])


@step
def options_box_toolkit():
    hud = hud_region()
    check(hud is None or hud.height <= 1, "options box opened for a shortcut (%s)" % (hud and hud.height,))
    ob = bpy.context.active_object
    ob.update_from_editmode()
    GIZMO["faces"] = len(ob.data.polygons)
    # A Modeling Toolkit button (here Bevel through m3d.tool) applies on the click and opens the box there.
    event('F18', 'PRESS', GIZMO["cursor"])
    event('F18', 'RELEASE', GIZMO["cursor"])


@step
def options_box_check():
    hud = hud_region()
    x, y = GIZMO["cursor"]
    check(hud is not None and hud.height > 60, "options box not open (%s)" % (hud and (hud.width, hud.height),))
    check(hud is not None and abs(hud.x - x) < 80 and hud.y < y < hud.y + hud.height + 80,
          "options box not at the cursor (box %s, cursor %s)" % (hud and (hud.x, hud.y, hud.height), (x, y)))
    ob = bpy.context.active_object
    ob.update_from_editmode()
    check(len(ob.data.polygons) > GIZMO["faces"], "toolkit Bevel did not apply on the click")
    check("m3d_options_box" not in bpy.context.window_manager, "options box flag left set")
    km = bpy.context.window_manager.keyconfigs.user.keymaps["Mesh"]
    for key in ('F19', 'F18'):
        km.keymap_items.remove(next(k for k in km.keymap_items if k.type == key))


# ----------------------------------------------------------------------------------------------------
# Phase 0: F1-F7, tab order, docks of every kind, left tray, Add to Shelf.

def window():
    return bpy.context.window_manager.windows[0]


def props_areas():
    return [a for a in window().screen.areas if a.type == 'PROPERTIES']


def tracebacks():
    return "Traceback" in "".join(stderr_tee.buf)


@step
def fkeys_setup():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.m3d.add_primitive(kind='CUBE')
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])


def _fkey_steps():
    for kind, (wname, key, mode, mset) in m3d_workspace.KINDS.items():
        def press(key=key):
            event(key, 'PRESS', GIZMO["center"])
            event(key, 'RELEASE', GIZMO["center"])

        def check_kind(kind=kind, key=key, mode=mode, mset=mset, wname=wname):
            ws = window().workspace
            check(m3d_workspace.workspace_kind(ws) == kind and ws.name == wname,
                  "%s did not switch to %s (now %s)" % (key, wname, ws.name))
            check(bpy.context.window_manager.m3d_menu_set == mset, "%s: menu set is %s" % (key, bpy.context.window_manager.m3d_menu_set))
            check(ws.object_mode == mode, "%s: workspace mode %s" % (key, ws.object_mode))
            if kind in {'SCULPT', 'UV'}:
                want = {'SCULPT': 'SCULPT', 'UV': 'EDIT_MESH'}[kind]
                check(bpy.context.mode == want, "%s: entered mode %s, wanted %s" % (key, bpy.context.mode, want))
            shelf = m3d_ui.shelf_key(bpy.context.window_manager, kind)
            check(shelf in m3d_ui.shelves_for(kind), "%s: shelf tab %s" % (key, shelf))
            GIZMO["center"] = (window().width // 2, window().height // 2)
        press.__name__, check_kind.__name__ = "press_" + key, "check_" + key
        yield press
        yield check_kind


for _fn in _fkey_steps():
    step(_fn)


@step
def cycle_order_start():
    GIZMO["seen"] = []
    bpy.ops.screen.workspace_cycle('INVOKE_DEFAULT', direction='NEXT')


def _cycle_step():
    GIZMO["seen"].append(window().workspace.name)
    bpy.ops.screen.workspace_cycle('INVOKE_DEFAULT', direction='NEXT')


for _i in range(len(m3d_workspace.WORKSPACE_ORDER) - 1):
    # The window is on Rendering (F7) first: the cycle goes through Shading ... Script Editor, Modeling ...
    step(_cycle_step)


@step
def cycle_order_check():
    GIZMO["seen"].append(window().workspace.name)
    order = m3d_workspace.WORKSPACE_ORDER
    start = order.index("Rendering")
    want = [order[(start + 1 + i) % len(order)] for i in range(len(order))]
    check(GIZMO["seen"][:len(order)] == want, "workspace tab order %s, wanted %s" % (GIZMO["seen"], want))
    bpy.ops.m3d.workspace(kind='MODEL')


def _dock_steps():
    for kind in m3d_workspace.KINDS:
        def switch(kind=kind):
            bpy.ops.m3d.workspace(kind=kind)

        def draw_tabs(kind=kind):
            check(m3d_workspace.workspace_kind(window().workspace) == kind, "dock test on %s" % kind)
            GIZMO["tabs"] = list(m3d_workspace.dock_tabs(kind, 'RIGHT'))
            for area in props_areas():
                GIZMO["tab_area"] = area

        def next_tab(kind=kind):
            if not GIZMO["tabs"]:
                return
            tab = GIZMO["tabs"].pop(0)
            area = GIZMO["tab_area"]
            area.spaces.active.context = tab.context
            if tab.page:
                window().workspace.m3d_page_right = tab.page
            area.tag_redraw()
            check(not tracebacks(), "Python error while drawing the %s dock tab %s" % (kind, tab.id))

        def all_settings():
            area = GIZMO["tab_area"]
            area.spaces.active.context = 'OBJECT'
            area.tag_redraw()

        def back(kind=kind):
            area = GIZMO["tab_area"]
            area.spaces.active.context = 'CHANNEL_BOX'
            area.tag_redraw()
            check(not tracebacks(), "Python error while drawing the %s dock / top bar" % kind)
        for fn, label in ((switch, "switch"), (draw_tabs, "tabs")):
            fn.__name__ = "dock_%s_%s" % (kind, label)
            yield fn
        for _ in m3d_workspace.DOCK_TABS[kind]['RIGHT']:
            next_tab.__name__ = "dock_%s_tab" % kind
            yield next_tab
        all_settings.__name__, back.__name__ = "dock_%s_all" % kind, "dock_%s_back" % kind
        yield all_settings
        yield back


for _fn in _dock_steps():
    step(_fn)


@step
def tab_menu_open():
    # The dock's tab menu draws (and Reset Workspace is in it).
    bpy.ops.m3d.workspace(kind='MODEL')


@step
def tab_menu_open2():
    area = props_areas()[0]
    region = next(r for r in area.regions if r.type == 'HEADER')
    with bpy.context.temp_override(window=window(), area=area, region=region):
        bpy.ops.wm.call_menu(name="M3D_MT_dock_tabs")


@step
def tab_menu_close():
    check(not tracebacks(), "Python error while drawing the dock tab menu")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])


@step
def left_tray_setup():
    # An Outliner on the left becomes a Properties editor: the left tray (side LEFT) with its own page.
    left = min((a for a in window().screen.areas if a.type == 'OUTLINER'), key=lambda a: a.x)
    GIZMO["left"] = left
    GIZMO["saved_tabs"] = m3d_workspace.DOCK_TABS['MODEL']
    GIZMO["left_cls"] = type("LeftPage", (m3d_workspace._PagePanel, bpy.types.Panel),
                             {"bl_label": "Left page", "page": "left_page",
                              "draw": lambda self, context: self.layout.label(text="left tray")})
    bpy.utils.register_class(GIZMO["left_cls"])
    m3d_workspace.DOCK_TABS['MODEL'] = {
        'RIGHT': GIZMO["saved_tabs"]['RIGHT'],
        'LEFT': (m3d_workspace.Tab("left_page", "Left Page", 'MODELING_TOOLKIT', "left_page"),)}
    left.ui_type = 'PROPERTIES'


@step
def left_tray_context():
    left = GIZMO["left"]
    left.spaces.active.context = 'MODELING_TOOLKIT'
    window().workspace.m3d_page_left = "left_page"
    left.tag_redraw()


@step
def left_tray_check():
    left, right = GIZMO["left"], max(props_areas(), key=lambda a: a.x)
    with bpy.context.temp_override(window=window(), area=left):
        check(m3d_workspace.side_of(bpy.context) == 'LEFT', "left Properties editor is not side LEFT")
        check(m3d_workspace.active_page(bpy.context) == "left_page", "left tray page")
        check(GIZMO["left_cls"].poll(bpy.context), "left page panel hidden in the left tray")
        check(not m3d_mode.PROPERTIES_PT_m3d_mtk_selection.poll(bpy.context), "toolkit panel shown in the left tray")
    with bpy.context.temp_override(window=window(), area=right):
        check(m3d_workspace.side_of(bpy.context) == 'RIGHT', "dock is not side RIGHT")
        check(not GIZMO["left_cls"].poll(bpy.context), "left page panel shown in the right dock")
        check(m3d_mode.PROPERTIES_PT_m3d_mtk_selection.poll(bpy.context), "toolkit panel hidden in the right dock")
    check(not tracebacks(), "Python error while drawing the left tray")
    bpy.utils.unregister_class(GIZMO["left_cls"])
    m3d_workspace.DOCK_TABS['MODEL'] = GIZMO["saved_tabs"]
    window().workspace.m3d_page_left = ""
    left.spaces.active.context = 'CHANNEL_BOX'
    left.ui_type = 'OUTLINER'


@step
def custom_shelf_setup():
    # Point the store at a temp folder, add a button to the Sculpt Custom shelf and draw it with Edit Shelf on.
    import os, tempfile
    GIZMO["cfg"] = tempfile.mkdtemp(prefix="m3d_gui_")
    m3d_user._path = lambda create=False: os.path.join(GIZMO["cfg"], "m3d_user.json")
    m3d_user.reset_cache()
    bpy.ops.m3d.workspace(kind='SCULPT')


@step
def custom_shelf_add():
    import json
    bpy.ops.m3d.shelf_add(item=json.dumps({"idname": "m3d.add_primitive", "props": {"kind": 'SPHERE'},
                                           "icon": "MESH_UVSPHERE", "label": "Sphere"}))
    bpy.ops.m3d.shelf_add(item=json.dumps({"idname": "mesh.bevel", "props": {"offset_type": 'PERCENT'},
                                           "icon": "", "label": "Bevel"}))
    bpy.context.window_manager.m3d_shelf_edit = True
    for area in window().screen.areas:
        area.tag_redraw()


@step
def custom_shelf_check():
    check(len(m3d_user.shelf_items('SCULPT')) == 2, "custom shelf items")
    check(not tracebacks(), "Python error while drawing the Custom shelf")
    bpy.context.window_manager.m3d_shelf_edit = False


@step
def add_to_shelf_menu():
    # Right-click a Status Line button: the Add to Shelf item sees that button's operator.
    bpy.ops.m3d.workspace(kind='MODEL')
    GIZMO["seen_item"] = []

    def recorder(self, context):
        GIZMO["seen_item"].append(m3d_user.item_from_context(context))
    GIZMO["recorder"] = recorder
    bpy.types.UI_MT_button_context_menu.append(recorder)


@step
def add_to_shelf_click():
    xy = (14, window().height - 38)  # The first Status Line button (the top bar is not in screen.areas).
    event('MOUSEMOVE', xy=xy)
    event('RIGHTMOUSE', 'PRESS', xy)
    event('RIGHTMOUSE', 'RELEASE', xy)


@step
def add_to_shelf_check():
    seen = [i for i in GIZMO["seen_item"] if i]
    check(seen and seen[-1]["idname"] == "wm.read_homefile", "Add to Shelf did not see the button's operator: %r" % (
        GIZMO["seen_item"],))
    bpy.types.UI_MT_button_context_menu.remove(GIZMO["recorder"])
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])


@step
def reset_workspace():
    # Sculpt: scramble then reset to the factory layout (a new workspace replaces it).
    bpy.ops.m3d.workspace(kind='SCULPT')


@step
def reset_workspace_run():
    GIZMO["areas_before"] = len(window().screen.areas)
    for area in window().screen.areas:
        if area.type == 'VIEW_3D':
            area.ui_type = 'OUTLINER'
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.workspace_reset()


@step
def reset_workspace_wait():
    pass


@step
def reset_workspace_wait2():
    pass


@step
def reset_workspace_check():
    ws = window().workspace
    check(m3d_workspace.workspace_kind(ws) == 'SCULPT' and ws.name == "Sculpt", "reset workspace name %s" % ws.name)
    check(len(m3d_workspace.workspace_screens('SCULPT')) == 1, "reset left screens: %s" % [s.name for s in bpy.data.screens])
    check(any(a.type == 'VIEW_3D' for a in window().screen.areas), "reset did not restore the 3D viewport")
    check(len([w for w in bpy.data.workspaces if w.name.startswith("Sculpt")]) == 1, "duplicate Sculpt workspace")
    check(not tracebacks(), "Python error during Reset Workspace")
    bpy.ops.m3d.workspace(kind='MODEL')


@step
def phase0_done():
    import shutil
    shutil.rmtree(GIZMO["cfg"], ignore_errors=True)
    check(bpy.data.workspaces["Modeling"] == window().workspace, "ended on Modeling")


@step
def finish():
    errors = "".join(stderr_tee.buf + sys.stdout.buf)
    check("Traceback" not in errors, "Python traceback in the output: " + errors[errors.find("Traceback"):][:600])
    with open(OUT, "w") as fh:
        fh.write("FAILS: %r\n" % (fails or "none"))
    bpy.ops.wm.quit_blender()


def run_next():
    fn = steps.pop(0)
    try:
        fn()
    except Exception as err:  # Report and quit rather than leave a window hanging.
        fails.append("%s: %r" % (fn.__name__, err))
        steps[:] = [finish]
    return 0.4 if steps else None


bpy.app.timers.register(run_next, first_interval=2.0)
