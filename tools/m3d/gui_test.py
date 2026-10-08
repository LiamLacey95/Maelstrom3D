# SPDX-License-Identifier: GPL-2.0-or-later
"""
Interactive self-check for Maelstrom3D behaviour that needs a real window (gizmo drags, held keys).

    blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result-file>

Writes "FAILS: [...]" to <result-file> and quits.
"""

import os
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


def wait_until(cond, what, tries=15):
    """Step body: run again on the next tick until `cond()` holds (a redraw or a workspace switch is still pending)."""
    def body():
        GIZMO["tries"] = GIZMO.get("tries", 0) + 1
        if not cond() and GIZMO["tries"] < tries:
            steps.insert(0, fn)
        else:
            if not cond():
                fails.append("timed out waiting for " + what)
            GIZMO["tries"] = 0
    fn = body
    return body


def _single_view():
    _win, area, region = view3d()
    return len(area.spaces.active.region_quadviews) == 0 and region.width > area.width // 2 + 100


# The region rectangles come back to the full viewport on a redraw after the toggle, not with it: aiming at the
# gizmo before that would use the quarter-size region.
step(wait_until(_single_view, "the single view after the Space tap"))


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
    check(uv and not uv[0].spaces.active.show_region_ui, "UV Editor sidebar is closed (the dock has the UV tools)")


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
            if kind in {'SCULPT', 'UV', 'TEXTURE'}:
                want = {'SCULPT': 'SCULPT', 'UV': 'EDIT_MESH', 'TEXTURE': 'PAINT_TEXTURE'}[kind]
                check(bpy.context.mode == want, "%s: entered mode %s, wanted %s" % (key, bpy.context.mode, want))
            shelf = m3d_ui.shelf_key(bpy.context.window_manager, kind)
            check(shelf in m3d_ui.shelves_for(kind), "%s: shelf tab %s" % (key, shelf))
            GIZMO["center"] = (window().width // 2, window().height // 2)
        press.__name__, check_kind.__name__ = "press_" + key, "check_" + key
        yield press
        yield wait_until(lambda kind=kind: m3d_workspace.workspace_kind(window().workspace) == kind,
                         "%s to switch workspace" % key)
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


# ----------------------------------------------------------------------------------------------------
# Phase 1: Sculpt workspace with a real mesh: layout, brushes, buttons, keys, every tab.

import m3d_sculpt


def sculpt_dock():
    """(left tray, right dock) Properties editors of the Sculpt screen."""
    areas = sorted(props_areas(), key=lambda a: a.x)
    return areas[0], areas[-1]


def press(idname, _run='INVOKE_DEFAULT', _area=None, **props):
    """Click a dock button the way the panels draw it (`_button`: the operator, or m3d.call when it needs the
    viewport). Returns the result and the route taken."""
    area = _area or sculpt_dock()[1]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region,
                                   space_data=area.spaces.active):
        mod, name = idname.split(".")
        if m3d_ui.needs_view3d(idname) or not m3d_ui._poll(idname):
            return bpy.ops.m3d.call('INVOKE_DEFAULT', idname=idname, props=repr(props)), "call"
        return getattr(getattr(bpy.ops, mod), name)(_run, **props), "direct"


def press_ok(idname, _run='INVOKE_DEFAULT', **props):
    try:
        res, route = press(idname, _run, **props)
    except RuntimeError as err:
        fails.append("Sculpt button %s %s: %s" % (idname, props, str(err).strip()[:160]))
        return None
    check(res <= {'FINISHED', 'RUNNING_MODAL'}, "Sculpt button %s %s: %s (%s)" % (idname, props, res, route))
    return res


def active_tool_id():
    tool = bpy.context.workspace.tools.from_space_view3d_mode('SCULPT')
    return tool.idname if tool else None


@step
def sculpt_setup():
    # A clean scene with one UV sphere, then F2.
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='SPHERE')
        bpy.context.active_object.name = "Ball"
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('F2', 'PRESS', GIZMO["center"])
    event('F2', 'RELEASE', GIZMO["center"])


step(wait_until(lambda: window().workspace.name == "Sculpt" and bpy.context.mode == 'SCULPT', "F2 to enter Sculpt Mode"))


@step
def sculpt_f2_check():
    check(window().workspace.name == "Sculpt" and bpy.context.mode == 'SCULPT', "F2 did not enter Sculpt Mode")
    tray, dock = sculpt_dock()
    check(len(props_areas()) == 2 and tray.x < dock.x, "Sculpt has a left tray and a right dock")
    check(tray.spaces.active.context == dock.spaces.active.context == 'MODELING_TOOLKIT',
          "Sculpt docks open on pages (%s, %s)" % (tray.spaces.active.context, dock.spaces.active.context))
    check(not any(a.spaces.active.show_region_asset_shelf for a in window().screen.areas if a.type == 'VIEW_3D'),
          "asset shelf is hidden in Sculpt")
    with bpy.context.temp_override(window=window(), area=tray):
        check(m3d_workspace.side_of(bpy.context) == 'LEFT' and m3d_workspace.active_page(bpy.context) == "sculpt_brushes",
              "left tray shows the brush page")
    with bpy.context.temp_override(window=window(), area=dock):
        check(m3d_workspace.active_page(bpy.context) == "sculpt_geometry", "dock opens on Geometry")
    GIZMO["faces"] = len(bpy.context.active_object.data.polygons)
    check(not tracebacks(), "Python error drawing the Sculpt workspace")


@step
def sculpt_brush_buttons():
    # The tray grid: every brush activates and shows as the active one.
    for label, name in m3d_sculpt.BRUSHES:
        press_ok("brush.asset_activate", **m3d_sculpt.brush_props(name))
        check(m3d_sculpt.active_brush_id(bpy.context) == m3d_sculpt.BRUSH_ASSET + name, "brush %s not active" % name)
    # The brush keys, with the mouse over the viewport.
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Grab"))
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('ONE', 'PRESS', GIZMO["center"], shift=True)
    event('ONE', 'RELEASE', GIZMO["center"], shift=True)


@step
def sculpt_brush_keys():
    check(m3d_sculpt.active_brush_id(bpy.context).endswith("/Draw"), "Shift+1 did not pick Draw (%s)" %
          m3d_sculpt.active_brush_id(bpy.context))
    event('SEVEN', 'PRESS', GIZMO["center"], shift=True)
    event('SEVEN', 'RELEASE', GIZMO["center"], shift=True)


@step
def sculpt_brush_keys2():
    check(m3d_sculpt.active_brush_id(bpy.context).endswith("/Crease Sharp"), "Shift+7 did not pick Crease Sharp")
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Clay Strips"))
    sculpt = bpy.context.tool_settings.sculpt
    check(sculpt.brush is not None and "Clay" in sculpt.brush.name, "active brush after the tray click")


@step
def sculpt_geometry_quadriflow():
    area = sculpt_dock()[1]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
        res = bpy.ops.object.quadriflow_remesh('EXEC_DEFAULT', mode='FACES', target_faces=200)
    check('FINISHED' in res or 'RUNNING_MODAL' in res, "QuadriFlow button: %s" % res)


@step
def sculpt_geometry_quadriflow_wait():
    pass


@step
def sculpt_geometry_voxel():
    press_ok("sculpt.sample_detail_size", mode='VOXEL')  # The eyedropper starts a modal sample; Esc cancels it.
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])
    GIZMO["faces"] = len(bpy.context.active_object.data.polygons)
    bpy.context.active_object.data.remesh_voxel_size = 0.08
    area = sculpt_dock()[1]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
        res = bpy.ops.object.voxel_remesh('EXEC_DEFAULT')
    check('FINISHED' in res, "Voxel Remesh button: %s" % res)


@step
def sculpt_geometry_voxel_check():
    faces = len(bpy.context.active_object.data.polygons)
    check(faces != GIZMO["faces"] and bpy.context.mode == 'SCULPT', "Voxel Remesh did not remesh (%s -> %s)" % (GIZMO["faces"], faces))


@step
def sculpt_geometry_multires():
    ob = bpy.context.active_object
    area = sculpt_dock()[1]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
        check(bpy.ops.m3d.multires_subdivide(mode='CATMULL_CLARK') == {'FINISHED'}, "Multires Subdivide button")
        bpy.ops.m3d.multires_level(delta=-1)
        check(m3d_sculpt.multires_of(ob).sculpt_levels == 0, "Multires level button")
        bpy.ops.m3d.multires_level(delta=1)
        check(bpy.ops.m3d.multires_subdivide(mode='LINEAR') == {'FINISHED'}, "Multires Linear button")
    mod = m3d_sculpt.multires_of(ob)
    check(mod and mod.total_levels == 2, "Multires levels after two Subdivides")


@step
def sculpt_geometry_multires_edit():
    ob = bpy.context.active_object
    area = sculpt_dock()[1]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
        bpy.ops.m3d.multires_level(delta=-1)
        check(bpy.ops.m3d.multires_edit(action='DELETE_HIGHER') == {'FINISHED'}, "Delete Higher button")
    check(m3d_sculpt.multires_of(ob).total_levels == 1, "Delete Higher removed the top level")


@step
def sculpt_geometry_dyntopo():
    # The Dyntopo button is greyed (and cancels) while the mesh has Multires.
    check(bpy.context.active_object.use_dynamic_topology_sculpting is False, "dyntopo is off")
    ob = bpy.context.active_object
    mod = m3d_sculpt.multires_of(ob)
    bpy.ops.object.modifier_remove(modifier=mod.name)


@step
def sculpt_mask_ops():
    ob = bpy.context.active_object
    press_ok("paint.mask_flood_fill", mode='VALUE', value=1.0)
    check(ob.data.attributes.get(".sculpt_mask") is not None, "Mask > Fill made no mask")
    press_ok("paint.mask_flood_fill", mode='INVERT')
    for label, idname, icon, props in (*m3d_sculpt.MASK_FILTERS, *m3d_sculpt.MASK_CREATE, *m3d_sculpt.HIDE_MASKED):
        press_ok(idname, **props)
    press_ok("paint.mask_flood_fill", mode='VALUE', value=0.0)
    check(not tracebacks(), "Python error in the Mask buttons")


@step
def sculpt_face_set_ops():
    ob = bpy.context.active_object
    for label, idname, icon, props in (*m3d_sculpt.FACE_SET_INIT, *m3d_sculpt.FACE_SET_VISIBILITY):
        press_ok(idname, **props)
    press_ok("paint.mask_flood_fill", mode='VALUE', value=1.0)
    for label, idname, icon, props in m3d_sculpt.FACE_SET_CREATE[:2]:
        press_ok(idname, **props)
    press_ok("paint.mask_flood_fill", mode='VALUE', value=0.0)
    press_ok("sculpt.face_sets_init", mode='NORMALS', threshold=0.05)   # A sphere has one loose part: split by normals.
    check(ob.data.attributes.get(".sculpt_face_set") is not None, "Face Sets made no face sets")
    for label, idname, icon, props in m3d_sculpt.PIVOT_BUTTONS:
        press_ok(idname, **props)
    check(not tracebacks(), "Python error in the Face Sets buttons")


@step
def sculpt_tool_buttons():
    # Tool buttons set the tool (and its options); the work happens in the viewport.
    area = sculpt_dock()[1]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    groups = (m3d_sculpt.MESH_FILTERS, m3d_sculpt.MASK_TOOLS, m3d_sculpt.FACE_SET_EDIT, m3d_sculpt.TRIM_TOOLS,
              m3d_sculpt.COLOR_FILTERS)
    for group in groups:
        for label, tool, op, props in group:
            with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
                res = bpy.ops.m3d.sculpt_tool(tool=tool, op=op, props=repr(props), label=label)
            check('FINISHED' in res and active_tool_id() == tool, "tool button %s -> %s" % (label, active_tool_id()))
            if op:
                got = bpy.context.workspace.tools.from_space_view3d_mode('SCULPT').operator_properties(op)
                check(all(getattr(got, k) == v for k, v in props.items()), "tool options of %s" % label)
    check(m3d_sculpt.tool_is_active(bpy.context, "builtin.color_filter", "sculpt.color_filter", {"type": 'BLUE'}),
          "tool_is_active for the pressed look")
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Draw"))
    check(active_tool_id() not in {"builtin.color_filter"}, "picking a brush leaves the filter tool (%s)" % active_tool_id())


@step
def sculpt_deform_buttons():
    # Symmetrize runs; the paint page's color attribute button adds an attribute.
    press_ok("sculpt.symmetrize")
    ob = bpy.context.active_object
    check(not ob.data.color_attributes, "no color attribute yet")
    press_ok("geometry.color_attribute_add", 'EXEC_DEFAULT', name="Color", domain='POINT', data_type='BYTE_COLOR',
             color=(0.8, 0.8, 0.8, 1.0))
    check(ob.data.color_attributes.active_color is not None, "Add Color Attribute button")
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Paint Soft"))
    check(not tracebacks(), "Python error in the Deform / Paint buttons")


def _sculpt_tab_steps():
    for page in [t.page for t in m3d_workspace.DOCK_TABS['SCULPT']['RIGHT']] + ["sculpt_brushes"]:
        def show(page=page):
            tray, dock = sculpt_dock()
            area = tray if page == "sculpt_brushes" else dock
            area.spaces.active.context = 'MODELING_TOOLKIT'
            setattr(window().workspace, "m3d_page_" + ("left" if page == "sculpt_brushes" else "right"), page)
            area.tag_redraw()
            for a in window().screen.areas:
                a.tag_redraw()

        def check_draw(page=page):
            check(not tracebacks(), "Python error while drawing the Sculpt page %s" % page)
        show.__name__, check_draw.__name__ = "sculpt_show_" + page, "sculpt_drawn_" + page
        yield show
        yield check_draw


for _fn in _sculpt_tab_steps():
    step(_fn)


@step
def sculpt_shelves_and_popovers():
    # Every Sculpt shelf and the Status Line draw with the sphere in Sculpt Mode; the popovers and the hotbox open.
    for key in m3d_ui.shelves_for('SCULPT'):
        bpy.context.window_manager.m3d_shelf = key
        for a in window().screen.areas:
            a.tag_redraw()
        GIZMO.setdefault("shelves", []).append(key)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_menu(name="M3D_MT_hotbox")


@step
def sculpt_hotbox_close():
    check(not tracebacks(), "Python error while drawing the Sculpt shelves / hotbox")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_panel(name="M3D_PT_sculpt_shading")


@step
def sculpt_popover_close():
    check(not tracebacks(), "Python error while drawing the matcap popover")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_panel(name="M3D_PT_sculpt_automasking")


@step
def sculpt_automask_close():
    check(not tracebacks(), "Python error while drawing the Auto-Masking popover")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])
    bpy.context.window_manager.m3d_shelf = 'SCULPT_BRUSHES'


@step
def sculpt_done():
    sculpt_ws = window().workspace
    sculpt_ws.m3d_page_left = sculpt_ws.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')


# ----------------------------------------------------------------------------------------------------
# Phase 2: UV workspace with a real cube: layout, F3, every dock button, Status Line toggles, keys, every tab.

import m3d_uv


def uv_areas():
    """(Image Editor area, its WINDOW region) of the UV screen."""
    area = next(a for a in window().screen.areas if a.type == 'IMAGE_EDITOR')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def uv_dock():
    return next(a for a in props_areas())   # The UV screen has one Properties editor: the dock.


def uv_xy():
    _area, region = uv_areas()
    return region.x + region.width // 2, region.y + region.height // 2


def uv_press(idname, **props):
    """Click a UV dock button the way the panels draw it (`_button`: m3d.call into the editor call_target names, or
    the operator in place). Returns (result, editor); a result of FINISHED means the operator's poll passed there."""
    dock = uv_dock()
    region = next(r for r in dock.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=dock, region=region,
                                   space_data=dock.spaces.active):
        target = m3d_ui.call_target(bpy.context, idname)
        if target:
            return bpy.ops.m3d.call('INVOKE_DEFAULT', idname=idname, props=repr(props), editor=target), target
        mod, name = idname.split(".")
        return getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT', **props), target


def uv_press_ok(idname, editor='IMAGE_EDITOR', **props):
    try:
        res, target = uv_press(idname, **props)
    except RuntimeError as err:
        fails.append("UV button %s %s: %s" % (idname, props, str(err).strip()[:160]))
        return None
    check(res == {'FINISHED'} and target == editor, "UV button %s %s: %s via %s (wanted %s)" % (idname, props, res, target, editor))
    return res


def uv_press_table(table, **kw):
    for label, idname, icon, props in table:
        uv_press_ok(idname, editor='VIEW_3D' if idname == "uv.project_from_view" else 'IMAGE_EDITOR', **props)


def uv_bmesh():
    ob = bpy.context.edit_object
    bm = bmesh.from_edit_mesh(ob.data)
    return ob, bm, bm.loops.layers.uv.verify()


def uv_boxes():
    _ob, bm, uv = uv_bmesh()
    boxes = []
    for shell in m3d_uv.uv_shells(list(bm.faces), uv):
        pts = [loop[uv].uv for f in shell for loop in f.loops]
        boxes.append((min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts)))
    return boxes


def last_operator():
    ops = bpy.context.window_manager.operators
    return ops[-1].bl_idname if len(ops) else None


def esc():
    """Close a dialog an operator opened (some Blender operators show their options on invoke)."""
    event('ESC', 'PRESS', uv_xy())
    event('ESC', 'RELEASE', uv_xy())


@step
def uv_setup():
    # A clean scene with one cube, then F3.
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
        bpy.context.active_object.name = "Block"
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('F3', 'PRESS', GIZMO["center"])
    event('F3', 'RELEASE', GIZMO["center"])


# The workspace changes on the next event, and the mode with it.
step(wait_until(lambda: window().workspace.name == "UV" and bpy.context.mode == 'EDIT_MESH', "F3 to enter Edit Mode"))


@step
def uv_f3_check():
    check(window().workspace.name == "UV" and bpy.context.mode == 'EDIT_MESH', "F3 did not enter Edit Mode in the UV workspace")
    # The earlier dock tests moved this workspace's tabs: Reset Workspace brings the factory layout back to check it.
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.workspace_reset()


# Reset Workspace appends the factory UV workspace, switches to it on the next event, then removes the old one.
step(wait_until(lambda: [w.name for w in bpy.data.workspaces if w.name.startswith("UV")] == ["UV"]
                and window().workspace.name == "UV" and bpy.context.mode == 'EDIT_MESH', "Reset Workspace to finish"))


@step
def uv_layout_check():
    check(window().workspace.name == "UV" and len(m3d_workspace.workspace_screens('UV')) == 1, "Reset Workspace kept one UV workspace")
    check(bpy.context.mode == 'EDIT_MESH', "Edit Mode after Reset Workspace")
    screen = window().screen
    image, view = uv_areas()[0], next(a for a in screen.areas if a.type == 'VIEW_3D')
    check(image.x < view.x and image.width > view.width, "UV editor is left of the 3D view and larger (%d vs %d)" % (image.width, view.width))
    shading = view.spaces.active
    check(shading.shading.type == 'SOLID' and shading.overlay.show_edge_seams, "3D view is Solid with seams")
    check(len(props_areas()) == 1 and uv_dock().x > view.x, "one dock on the right")
    with bpy.context.temp_override(window=window(), area=uv_dock()):
        check(m3d_workspace.active_page(bpy.context) == "uv_unwrap" and uv_dock().spaces.active.context == 'MODELING_TOOLKIT',
              "dock opens on Unwrap")
    check(not image.spaces.active.show_region_ui, "UV editor sidebar closed")
    bpy.context.tool_settings.use_uv_select_sync = True
    check(not tracebacks(), "Python error drawing the UV workspace")


@step
def uv_select_all():
    area, region = uv_areas()
    view = next(a for a in window().screen.areas if a.type == 'VIEW_3D')
    with bpy.context.temp_override(window=window(), area=view, region=next(r for r in view.regions if r.type == 'WINDOW')):
        bpy.ops.mesh.select_all(action='SELECT')


@step
def uv_cut_unfold():
    _ob, bm, _uv = uv_bmesh()
    check(not any(e.seam for e in bm.edges), "the new cube has no seams")
    uv_press_ok("m3d.uv_cut")
    _ob, bm, _uv = uv_bmesh()
    check(all(e.seam for e in bm.edges), "Cut from the dock marked the selected edges")
    uv_press_ok("m3d.uv_unfold")
    check(len(uv_boxes()) == 6, "Unfold: six shells (%d)" % len(uv_boxes()))
    GIZMO["boxes"] = uv_boxes()


@step
def uv_optimize_layout():
    uv_press_ok("m3d.uv_optimize")
    uv_press_ok("m3d.uv_layout")
    boxes = uv_boxes()
    check(all(b[0] >= -1e-4 and b[1] >= -1e-4 and b[2] <= 1.0001 and b[3] <= 1.0001 for b in boxes), "Layout inside 0-1: %s" % boxes)
    check(boxes != GIZMO["boxes"], "Optimize / Layout changed the UVs")
    check(not tracebacks(), "Python error in Unfold / Optimize / Layout")


@step
def uv_auto():
    uv_press_ok("m3d.uv_auto")
    boxes = uv_boxes()
    check(len(boxes) == 6 and all(b[0] >= -1e-4 and b[2] <= 1.0001 for b in boxes), "Auto Unwrap from the dock: %s" % boxes)


@step
def uv_texel():
    s = bpy.context.scene.m3d_uv
    s.texture_size = '1024'
    uv_press_ok("m3d.uv_texel_density", mode='READ')
    read = s.density_read
    check(read > 0, "Read gave a density")
    s.density = 777.0
    uv_press_ok("m3d.uv_texel_density", mode='SET')
    uv_press_ok("m3d.uv_texel_density", mode='READ')
    check(abs(s.density_read - 777.0) < 0.5, "Set then Read: %s" % s.density_read)
    s.density = 100.0
    uv_press_ok("m3d.uv_texel_density", mode='MATCH')
    check(abs(s.density - 777.0) < 0.5, "Match picks up the shells' density (%s)" % s.density)
    check(not tracebacks(), "Python error in the texel density buttons")


@step
def uv_checker_distortion():
    ob = bpy.context.edit_object
    uv_press_ok("m3d.uv_checker")
    check(m3d_uv.checker_on(bpy.context) and ob.material_slots[0].material.name == m3d_uv.CHECKER, "Checker on from the dock")
    area, _region = uv_areas()
    uvedit = area.spaces.active.uv_editor
    uvedit.show_stretch = True
    uvedit.display_stretch_type = 'AREA'
    for a in window().screen.areas:
        a.tag_redraw()


@step
def uv_checker_distortion_check():
    check(not tracebacks(), "Python error drawing Checker / Distortion")
    area, _region = uv_areas()
    area.spaces.active.uv_editor.show_stretch = False
    uv_press_ok("m3d.uv_checker")
    check(not m3d_uv.checker_on(bpy.context), "Checker off from the dock")


@step
def uv_arrange_buttons():
    bpy.context.tool_settings.mesh_select_mode = (True, False, False)   # Select Pinned works in Vertex mode only.
    _ob, bm, uv = uv_bmesh()
    first = lambda: [tuple(loop[uv].uv) for loop in uv_bmesh()[1].faces[0].loops]
    before = first()
    uv_press_table(m3d_uv.UV_SELECT_PAGE)
    uv_press_ok("m3d.uv_flip", axis='U')
    check(first() != before, "Flip U moved the UVs")
    after_flip = first()
    uv_press_ok("m3d.uv_rotate", clockwise=True)
    check(first() != after_flip, "Rotate 90 turned the UVs")
    uv_press_ok("m3d.uv_rotate", clockwise=False)
    uv_press_ok("m3d.uv_flip", axis='U')
    check(all(abs(a - b) < 1e-4 for p, q in zip(first(), before) for a, b in zip(p, q)), "Flip twice and rotate back: same UVs")
    uv_press_ok("uv.pin")
    check(all(loop[uv_bmesh()[2]].pin_uv for f in uv_bmesh()[1].faces for loop in f.loops), "Pin pinned the selected UVs")
    uv_press_ok("uv.pin", clear=True)
    check(not any(loop[uv_bmesh()[2]].pin_uv for f in uv_bmesh()[1].faces for loop in f.loops), "Unpin cleared the pins")
    uv_press_table(m3d_uv.UVTK_TRANSFORM)
    uv_press_table(m3d_uv.UV_SHELVES)
    uv_press_table(m3d_uv.UV_PIN_PAGE)
    uv_press_table(m3d_uv.UVTK_CUT_SEW)
    check(not tracebacks(), "Python error in the Arrange / Pin / Cut buttons")


@step
def uv_create_buttons():
    uv_press_table([it for it in m3d_uv.UVTK_CREATE if it[1] != "uv.smart_project"])
    uv_press_ok("uv.smart_project")   # Opens its options: close them.
    esc()


@step
def uv_create_check():
    check(not window().modal_operators, "Smart Project's options closed (%s)" % [o.bl_idname for o in window().modal_operators])
    check(not tracebacks(), "Python error in the projection buttons")


@step
def uv_status_line_toggles():
    # The Status Line's controls are properties: flip each one (sync, select modes, shell select, Live Unwrap,
    # Distortion + type, texture size) and let the top bar draw every state.
    ts = bpy.context.tool_settings
    area, _region = uv_areas()
    uvedit = area.spaces.active.uv_editor
    GIZMO["toggles"] = [
        lambda: setattr(ts, "use_uv_select_sync", False),
        lambda: setattr(ts, "uv_select_mode", 'EDGE'),
        lambda: setattr(ts, "uv_select_mode", 'FACE'),
        lambda: setattr(ts, "uv_select_mode", 'VERTEX'),
        lambda: setattr(ts, "use_uv_select_island", True),
        lambda: setattr(uvedit, "use_live_unwrap", True),
        lambda: setattr(uvedit, "show_stretch", True),
        lambda: setattr(uvedit, "display_stretch_type", 'ANGLE'),
        lambda: setattr(bpy.context.scene.m3d_uv, "texture_size", '4096'),
        lambda: setattr(ts, "use_uv_select_sync", True),
    ]


def _toggle_step():
    GIZMO["toggles"].pop(0)()
    for a in window().screen.areas:
        a.tag_redraw()
    bpy.context.window_manager.m3d_shelf = 'UV'
    check(not tracebacks(), "Python error drawing the UV Status Line")


for _i in range(10):
    step(_toggle_step)


@step
def uv_status_line_done():
    ts = bpy.context.tool_settings
    area, _region = uv_areas()
    uvedit = area.spaces.active.uv_editor
    check(ts.use_uv_select_sync and ts.use_uv_select_island and uvedit.use_live_unwrap and uvedit.show_stretch
          and bpy.context.scene.m3d_uv.texture_size == '4096', "Status Line toggles stuck")
    ts.use_uv_select_island = False
    uvedit.use_live_unwrap = uvedit.show_stretch = False
    bpy.context.scene.m3d_uv.texture_size = '1024'
    for key in m3d_ui.shelves_for('UV'):
        bpy.context.window_manager.m3d_shelf = key
        for a in window().screen.areas:
            a.tag_redraw()
    bpy.context.window_manager.m3d_shelf = 'UV'


@step
def uv_shelf_buttons():
    # The shelf draws its buttons like the dock: the same routes, the same results.
    check(not tracebacks(), "Python error drawing the UV shelf")
    for item in m3d_uv.SHELF_UV:
        if item:
            uv_press_ok(item[0], **item[2])
    check(not tracebacks(), "Python error in the UV shelf buttons")


@step
def uv_keys_layout():
    GIZMO["op"] = None
    event('MOUSEMOVE', xy=uv_xy())
    event('P', 'PRESS', uv_xy(), alt=True)
    event('P', 'RELEASE', uv_xy(), alt=True)


@step
def uv_keys_unfold():
    check(last_operator() == "M3D_OT_uv_layout", "Alt+P ran Layout (last operator %s)" % last_operator())
    event('U', 'PRESS', uv_xy(), ctrl=True, shift=True)
    event('U', 'RELEASE', uv_xy(), ctrl=True, shift=True)


@step
def uv_keys_density():
    check(last_operator() == "M3D_OT_uv_unfold", "Ctrl+Shift+U ran Unfold (last operator %s)" % last_operator())
    event('T', 'PRESS', uv_xy(), shift=True)
    event('T', 'RELEASE', uv_xy(), shift=True)


@step
def uv_keys_checker():
    check(last_operator() == "M3D_OT_uv_texel_density", "Shift+T ran texel density (last operator %s)" % last_operator())
    event('C', 'PRESS', uv_xy(), alt=True)
    event('C', 'RELEASE', uv_xy(), alt=True)


@step
def uv_keys_sync():
    check(m3d_uv.checker_on(bpy.context), "Alt+C turned the checker on")
    GIZMO["sync"] = bpy.context.tool_settings.use_uv_select_sync
    event('S', 'PRESS', uv_xy(), alt=True)
    event('S', 'RELEASE', uv_xy(), alt=True)


@step
def uv_keys_done():
    check(bpy.context.tool_settings.use_uv_select_sync != GIZMO["sync"], "Alt+S toggled UV Sync")
    bpy.context.tool_settings.use_uv_select_sync = GIZMO["sync"]
    event('C', 'PRESS', uv_xy(), alt=True)
    event('C', 'RELEASE', uv_xy(), alt=True)


@step
def uv_keys_checker_off():
    check(not m3d_uv.checker_on(bpy.context), "Alt+C turned the checker off")
    check(not tracebacks(), "Python error from the UV keys")


@step
def uv_udim_image():
    # A UDIM image in the UV editor: tile buttons run in the editor, Pack to Tile works.
    area, _region = uv_areas()
    image = bpy.data.images.new("udim_test", 256, 256, tiled=True)
    area.spaces.active.image = image
    GIZMO["image"] = image
    uv_press_ok("image.tile_add")   # Opens its options: close them, then add with them.
    esc()


@step
def uv_udim_tiles():
    check(not window().modal_operators, "tile options closed")
    area, region = uv_areas()
    image = GIZMO["image"]
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
        check(bpy.ops.image.tile_add('EXEC_DEFAULT', number=1002, count=1, label="", fill=False) == {'FINISHED'}, "Add Tile")
        check(len(image.tiles) == 2, "image has two tiles (%d)" % len(image.tiles))
        image.tiles.active_index = 1
        check(bpy.ops.image.tile_fill('EXEC_DEFAULT') == {'FINISHED'}, "Fill Tile")
    uv_press_table(m3d_uv.UV_TILES)
    area.spaces.active.uv_editor.tile_grid_shape = (2, 1)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def uv_udim_tiles_drawn():
    check(not tracebacks(), "Python error drawing the UDIM tab with tiles")
    area, region = uv_areas()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
        check(bpy.ops.image.tile_remove() == {'FINISHED'}, "Remove Tile")
    area.spaces.active.image = None
    bpy.data.images.remove(GIZMO["image"])


def _uv_tab_steps():
    for object_mode in (False, True):
        for tab in m3d_workspace.DOCK_TABS['UV']['RIGHT']:
            def show(tab=tab, object_mode=object_mode):
                if object_mode and bpy.context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                uv_dock().spaces.active.context = tab.context
                window().workspace.m3d_page_right = tab.page
                for a in window().screen.areas:
                    a.tag_redraw()

            def check_draw(tab=tab, object_mode=object_mode):
                check(not tracebacks(), "Python error while drawing the UV page %s%s" % (tab.page, " (Object Mode)" if object_mode else ""))
            show.__name__, check_draw.__name__ = "uv_show_" + tab.page + str(object_mode), "uv_drawn_" + tab.page + str(object_mode)
            yield show
            yield check_draw


for _fn in _uv_tab_steps():
    step(_fn)


@step
def uv_done():
    window().workspace.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')
    check(not tracebacks(), "Python error in the UV workspace tests")


# ----------------------------------------------------------------------------------------------------
# Phase 3a: Texture workspace with a real cube: layout, F4, channels, brushes, keys, bake, export, every tab.

import os
import tempfile

import m3d_texture


def tex_areas():
    """(left tray, dock) Properties editors of the Texture screen."""
    areas = sorted(props_areas(), key=lambda a: a.x)
    return areas[0], areas[-1]


def tex_view():
    """(3D view area, its window region) of the Texture screen."""
    area = next(a for a in window().screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def tex_xy():
    _area, region = tex_view()
    return region.x + region.width // 2, region.y + region.height // 2


def tex_mat():
    return bpy.context.active_object.active_material


def tex_brush_size():
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    return ups.size if ups.use_unified_size else bpy.context.tool_settings.image_paint.brush.size


@step
def tex_setup():
    # A clean scene with one cube (it has UVs, no material), then F4.
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
        bpy.context.active_object.name = "Crate"
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('F4', 'PRESS', GIZMO["center"])
    event('F4', 'RELEASE', GIZMO["center"])


step(wait_until(lambda: window().workspace.name == "Texture" and bpy.context.mode == 'PAINT_TEXTURE', "F4 to enter Texture Paint Mode"))


@step
def tex_f4_check():
    check(window().workspace.name == "Texture" and bpy.context.mode == 'PAINT_TEXTURE', "F4 did not enter Texture Paint Mode")
    # The earlier dock tests moved this workspace's tabs: Reset Workspace brings the factory layout back to check it.
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.workspace_reset()


step(wait_until(lambda: [w.name for w in bpy.data.workspaces if w.name.startswith("Texture")] == ["Texture"]
                and window().workspace.name == "Texture" and bpy.context.mode == 'PAINT_TEXTURE', "Reset Workspace to finish"))


@step
def tex_layout_check():
    screen = window().screen
    check(len(props_areas()) == 2, "Texture has a tray and a dock")
    tray, dock = tex_areas()
    view, _region = tex_view()
    image = next(a for a in screen.areas if a.type == 'IMAGE_EDITOR')
    check(tray.x < view.x < image.x < dock.x, "Texture layout: tray, 3D view, paint view, dock (%d %d %d %d)" % (tray.x, view.x, image.x, dock.x))
    check(view.width > image.width, "the 3D view is wider than the paint view (%d vs %d)" % (view.width, image.width))
    check(view.spaces.active.shading.type == 'MATERIAL', "3D view is in Material Preview")
    check(image.spaces.active.mode == 'PAINT' and not image.spaces.active.show_region_ui, "paint view is in Paint mode, sidebar closed")
    check(not view.spaces.active.show_region_asset_shelf and view.spaces.active.show_region_tool_header, "asset shelf hidden, tool header shown")
    check(tray.spaces.active.context == dock.spaces.active.context == 'MODELING_TOOLKIT', "docks open on pages")
    with bpy.context.temp_override(window=window(), area=tray):
        check(m3d_workspace.side_of(bpy.context) == 'LEFT' and m3d_workspace.active_page(bpy.context) == "tex_brushes", "tray shows the brush page")
    with bpy.context.temp_override(window=window(), area=dock):
        check(m3d_workspace.active_page(bpy.context) == "tex_layers", "dock opens on Layers")
    check(m3d_ui.shelf_key(bpy.context.window_manager, 'TEXTURE') == 'TEXTURE_BRUSHES', "Paint shelf tab first")
    check(m3d_texture.missing(bpy.context) == ['MATERIAL'], "gate: this cube needs a material (%s)" % m3d_texture.missing(bpy.context))
    check(not tracebacks(), "Python error drawing the Texture workspace")
    press_ok("m3d.tex_add_material", _area=tex_areas()[1])


@step
def tex_channels():
    check(m3d_texture.missing(bpy.context) == [], "Add Material fixed the gate")
    bpy.context.scene.m3d_tex.resolution = '128'
    dock = tex_areas()[1]
    press_ok("m3d.tex_channel", _area=dock, channel='BASE_COLOR')
    press_ok("m3d.tex_channel", _area=dock, channel='ROUGHNESS')
    found = m3d_texture.channel_slots(tex_mat())
    check(set(found) == {'BASE_COLOR', 'ROUGHNESS'} and m3d_texture.active_channel(tex_mat()) == 'ROUGHNESS',
          "Base Color and Roughness added (%s)" % sorted(found))
    check(found['ROUGHNESS'][1].colorspace_settings.name == 'Non-Color' and found['BASE_COLOR'][1].colorspace_settings.name == 'sRGB',
          "color spaces")
    # Switch with the Status Line buttons (they are plain operator buttons in the top bar).
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_channel('INVOKE_DEFAULT', channel='BASE_COLOR') == {'FINISHED'}, "Status Line channel button")
    check(m3d_texture.active_channel(tex_mat()) == 'BASE_COLOR', "Base Color is active")
    event('MOUSEMOVE', xy=tex_xy())
    event('C', 'PRESS', tex_xy())
    event('C', 'RELEASE', tex_xy())


@step
def tex_c_key():
    check(m3d_texture.active_channel(tex_mat()) == 'ROUGHNESS', "C did not switch to the next channel (%s)" % m3d_texture.active_channel(tex_mat()))
    event('C', 'PRESS', tex_xy(), shift=True)
    event('C', 'RELEASE', tex_xy(), shift=True)


@step
def tex_shift_c_key():
    check(m3d_texture.active_channel(tex_mat()) == 'BASE_COLOR', "Shift+C did not switch to the previous channel (%s)" % m3d_texture.active_channel(tex_mat()))


@step
def tex_brush_buttons():
    # The tray grid: every brush activates and shows as the active one.
    tray = tex_areas()[0]
    for label, name in m3d_texture.BRUSHES:
        press_ok("brush.asset_activate", _area=tray, **m3d_texture.brush_props(name))
        check(m3d_sculpt.active_brush_id(bpy.context) == m3d_texture.BRUSH_ASSET + name, "texture brush %s not active (%s)" %
              (name, m3d_sculpt.active_brush_id(bpy.context)))
    press_ok("brush.asset_activate", _area=tray, **m3d_texture.brush_props("Paint Soft"))
    check(bpy.context.tool_settings.image_paint.brush is not None and bpy.context.tool_settings.image_paint.brush.name == "Paint Soft",
          "the brush after the tray click")
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.color, ups.secondary_color = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    GIZMO["size"] = tex_brush_size()
    event('MOUSEMOVE', xy=tex_xy())
    event('RIGHT_BRACKET', 'PRESS', tex_xy())
    event('RIGHT_BRACKET', 'RELEASE', tex_xy())


@step
def tex_size_keys():
    check(tex_brush_size() > GIZMO["size"], "] did not make the brush bigger (%s -> %s)" % (GIZMO["size"], tex_brush_size()))
    event('LEFT_BRACKET', 'PRESS', tex_xy())
    event('LEFT_BRACKET', 'RELEASE', tex_xy())


@step
def tex_size_keys2():
    check(abs(tex_brush_size() - GIZMO["size"]) < GIZMO["size"] * 0.05, "[ did not shrink the brush back (%s -> %s)" % (GIZMO["size"], tex_brush_size()))
    event('X', 'PRESS', tex_xy(), shift=True)
    event('X', 'RELEASE', tex_xy(), shift=True)


@step
def tex_swap_key():
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    check(tuple(round(c, 2) for c in ups.color) == (0.0, 0.0, 1.0), "Shift+X did not swap the colors (%s)" % (tuple(ups.color),))
    event('X', 'PRESS', tex_xy())
    event('X', 'RELEASE', tex_xy())


@step
def tex_plain_x():
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    check(tuple(round(c, 2) for c in ups.color) == (0.0, 0.0, 1.0), "plain X still swaps the colors (%s)" % (tuple(ups.color),))


@step
def tex_channel_view():
    dock = tex_areas()[1]
    space = tex_view()[0].spaces.active
    press_ok("m3d.tex_channel_view", _area=dock)
    check(m3d_texture.channel_view_on(space.shading), "Channel View did not show the channel flat")
    press_ok("m3d.tex_channel_view", _area=dock)
    check(space.shading.type == 'MATERIAL' and not m3d_texture.channel_view_on(space.shading), "Channel View did not restore the view")
    press_ok("m3d.tex_channel_view", _area=dock, channel='ROUGHNESS')
    check(m3d_texture.active_channel(tex_mat()) == 'ROUGHNESS' and m3d_texture.channel_view_on(space.shading),
          "Channel View of Roughness")
    press_ok("m3d.tex_channel_view", _area=dock)
    check(space.shading.type == 'MATERIAL', "back to Material Preview")
    # The Status Line's display buttons run through m3d.call in the 3D view.
    with bpy.context.temp_override(window=window(), screen=window().screen):
        view, region = tex_view()
        with bpy.context.temp_override(area=view, region=region, space_data=view.spaces.active):
            bpy.ops.wm.context_set_enum(data_path="space_data.shading.type", value='SOLID')
    check(space.shading.type == 'SOLID', "Solid display")
    space.shading.type = 'MATERIAL'


@step
def tex_bake_from_dock():
    ob = bpy.context.active_object
    dock = tex_areas()[1]
    s = ob.m3d_bake
    s.resolution, s.margin, s.samples = '128', 4, 4
    s.use_normal = s.use_ao = True
    s.use_curvature = s.use_position = s.use_thickness = False
    GIZMO["nodes"] = sorted(n.name for n in tex_mat().node_tree.nodes)
    GIZMO["engine"] = bpy.context.scene.render.engine
    press_ok("m3d.tex_bake", _area=dock)


@step
def tex_bake_check():
    ob = bpy.context.active_object
    check(bpy.context.scene.render.engine == GIZMO["engine"], "Cycles switched back after the bake (%s)" % bpy.context.scene.render.engine)
    check(bpy.context.mode == 'PAINT_TEXTURE', "Texture Paint Mode after the bake (%s)" % bpy.context.mode)
    check(all(bpy.data.images.get("Crate_" + n) is not None for n in ("Normal", "AO")), "baked maps exist")
    check(sorted(n.name for n in tex_mat().node_tree.nodes) == GIZMO["nodes"] and len(ob.material_slots) == 1, "material unchanged by the bake")
    check(not tracebacks(), "Python error while baking")
    # Export from the dock.
    GIZMO["out"] = tempfile.mkdtemp(prefix="m3d_gui_export_")
    tx = bpy.context.scene.m3d_tex
    tx.export_folder, tx.export_preset, tx.export_size = GIZMO["out"], 'UNREAL', 'SAME'
    press_ok("m3d.tex_export", _area=tex_areas()[1])


@step
def tex_export_check():
    files = sorted(os.listdir(GIZMO["out"]))
    check(files == ["T_Crate_BC.png", "T_Crate_ORM.png"], "export wrote the Unreal files (%s)" % files)
    saved, packed = m3d_texture.save_images()
    check(not m3d_texture.modified_images(), "Save All left nothing modified")
    press_ok("m3d.tex_save_all", _area=tex_areas()[1])
    check(not tracebacks(), "Python error while exporting")


def _texture_tab_steps():
    for object_mode in (False, True):
        for tab in (*m3d_workspace.DOCK_TABS['TEXTURE']['RIGHT'], *m3d_workspace.DOCK_TABS['TEXTURE']['LEFT']):
            def show(tab=tab, object_mode=object_mode):
                if object_mode and bpy.context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                if not object_mode and bpy.context.mode != 'PAINT_TEXTURE':
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                tray, dock = tex_areas()
                area = tray if tab.page == "tex_brushes" else dock
                area.spaces.active.context = 'MODELING_TOOLKIT'
                press_ok("m3d.dock_page", _area=area, tab=tab.id)
                for a in window().screen.areas:
                    a.tag_redraw()

            def check_draw(tab=tab, object_mode=object_mode):
                side = "left" if tab.page == "tex_brushes" else "right"
                check(getattr(window().workspace, "m3d_page_" + side) == tab.page, "dock tab %s did not open its page" % tab.id)
                check(not tracebacks(), "Python error while drawing the Texture page %s%s" % (tab.page, " (Object Mode)" if object_mode else ""))
            show.__name__, check_draw.__name__ = "tex_show_%s%s" % (tab.page, object_mode), "tex_drawn_%s%s" % (tab.page, object_mode)
            yield show
            yield check_draw


for _fn in _texture_tab_steps():
    step(_fn)


@step
def tex_shelves():
    # Every Texture shelf and the Status Line draw with the cube in Texture Paint Mode and in Object Mode.
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    for key in m3d_ui.shelves_for('TEXTURE'):
        bpy.context.window_manager.m3d_shelf = key
        for a in window().screen.areas:
            a.tag_redraw()


@step
def tex_shelves_check():
    check(not tracebacks(), "Python error while drawing the Texture shelves")
    bpy.context.window_manager.m3d_shelf = 'TEXTURE_BRUSHES'
    # Auto Unwrap fix: a mesh without UVs is unwrapped from the tray's button and stays in Texture Paint Mode.
    ob = bpy.context.active_object
    ob.data.uv_layers.remove(ob.data.uv_layers[0])
    check(m3d_texture.missing(bpy.context) == ['UV'], "no UVs gate the pages (%s)" % m3d_texture.missing(bpy.context))
    press_ok("m3d.tex_unwrap", _area=tex_areas()[0])


@step
def tex_unwrap_check():
    ob = bpy.context.active_object
    check(len(ob.data.uv_layers) == 1 and bpy.context.mode == 'PAINT_TEXTURE' and m3d_texture.missing(bpy.context) == [],
          "Auto Unwrap fixed the gate (%s, %s)" % (bpy.context.mode, m3d_texture.missing(bpy.context)))
    check(not tracebacks(), "Python error in the Auto Unwrap fix")


# ----------------------------------------------------------------------------------------------------
# Phase 3b: the layer stack in the Texture workspace: add, fill, mask, a real stroke, visibility, order, merge, export.

import numpy as np

import m3d_layers as LY


def px(image):
    a = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(a)
    return a.reshape(-1, 4)


def lay_mat():
    return bpy.context.active_object.active_material


def lay_names():
    return [l.name for l in lay_mat().m3d_layers]


def lay_image(index, channel='BASE_COLOR'):
    return LY.entry_of(lay_mat().m3d_layers[index], channel).image


def lay_show_tab():
    ws = window().workspace
    dock = tex_areas()[1]
    if bpy.context.mode != 'PAINT_TEXTURE':
        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    press_ok("m3d.dock_page", _area=dock, tab="tex_layers")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def lay_add_paint():
    check(bpy.context.mode == 'PAINT_TEXTURE', "layer tests start in Texture Paint Mode (%s)" % bpy.context.mode)
    lay_show_tab()
    GIZMO["slots"] = len(m3d_texture.channel_slots(lay_mat()))
    GIZMO["base_name"] = m3d_texture.channel_slots(lay_mat())['BASE_COLOR'][1].name
    press_ok("m3d.layer_add", _area=tex_areas()[1], kind='PAINT')


@step
def lay_add_paint_check():
    check(lay_names() == ["Base", "Paint Layer"], "Add Paint Layer from the dock: %s" % lay_names())
    check(lay_image(0).name == GIZMO["base_name"], "the old Base Color image is the Base layer's")
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.color = (1.0, 0.0, 0.0)
    press_ok("m3d.tex_channel", _area=tex_areas()[1], channel='BASE_COLOR')
    check(not tracebacks(), "Python error drawing the Layers tab with layers")


@step
def lay_stroke_setup():
    layer = lay_mat().m3d_layers[1]
    check(lay_image(1) is not None and lay_image(1) == lay_mat().texture_paint_images[lay_mat().paint_active_slot],
          "the brush targets the new layer's Base Color image")
    GIZMO["layer_before"], GIZMO["base_before"] = px(lay_image(1)).copy(), px(lay_image(0)).copy()
    view, region = tex_view()
    rv3d = view.spaces.active.region_3d
    p = location_3d_to_region_2d(region, rv3d, Vector((0, 0, 0)))
    check(p is not None, "the cube is in the 3D view")
    cx, cy = (int(region.x + p.x), int(region.y + p.y)) if p is not None else tex_xy()
    GIZMO["stroke"] = [(cx - 40 + i * 8, cy) for i in range(11)]
    event('MOUSEMOVE', xy=GIZMO["stroke"][0])


@step
def lay_stroke_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["stroke"][0])
    for xy in GIZMO["stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def lay_stroke_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["stroke"][-1])


@step
def lay_stroke_check():
    after_layer, after_base = px(lay_image(1)), px(lay_image(0))
    changed = np.abs(after_layer - GIZMO["layer_before"]).max()
    check(changed > 0.2, "the stroke painted the active layer's image (largest change %.3f)" % changed)
    check(np.array_equal(after_base, GIZMO["base_before"]), "...and left the base layer alone")
    check(after_layer[:, 3].max() > 0.5 and (after_layer[:, 3] < 0.01).any(), "...only where the brush went (the rest stays transparent)")
    check(not tracebacks(), "Python error during the stroke")
    GIZMO["stroked"] = after_layer.copy()
    press_ok("m3d.layer_add", _area=tex_areas()[1], kind='FILL')


@step
def lay_fill_check():
    m = lay_mat()
    check(lay_names() == ["Base", "Paint Layer", "Fill Layer"] and m.m3d_layers[2].kind == 'FILL' and m.m3d_layer_index == 2,
          "Add Fill Layer: %s" % lay_names())
    m.m3d_layers[2].channels[0].color = (0.1, 0.6, 0.2, 1.0)
    m.m3d_layers[2].blend, m.m3d_layers[2].opacity = 'OVERLAY', 0.5
    press_ok("m3d.layer_mask_add", _area=tex_areas()[1], fill='WHITE')


@step
def lay_mask_check():
    m = lay_mat()
    fill = m.m3d_layers[2]
    check(fill.mask is not None and m.texture_paint_images[m.paint_active_slot] == fill.mask, "Add Mask: the brush is on the mask")
    check(m3d_texture.active_channel(m) == 'BASE_COLOR', "the channel stays")
    check(not tracebacks(), "Python error drawing a fill layer with a mask")
    lay_show_tab()
    press_ok("m3d.layer_visible", _area=tex_areas()[1])


@step
def lay_visible_check():
    m = lay_mat()
    check(not m.m3d_layers[2].visible, "Show / Hide Layer hid the fill layer")
    opv = m.node_tree.nodes[LY.part('BASE_COLOR', m.m3d_layers[2].uid, "opv")]
    check(opv.inputs[1].default_value == 0.0, "a hidden layer has no effect on the shader")
    m.m3d_layers[2].visible = True
    check(opv.inputs[1].default_value == 0.5, "...and showing it again restores the opacity")
    press_ok("m3d.layer_move", _area=tex_areas()[1], delta=-1)


@step
def lay_move_check():
    m = lay_mat()
    check(lay_names() == ["Base", "Fill Layer", "Paint Layer"] and m.m3d_layer_index == 1, "Move Layer Down: %s" % lay_names())
    check(m.texture_paint_images[m.paint_active_slot] == m.m3d_layers[1].mask, "the brush follows the moved layer (its mask)")
    top = LY.principled_of(m).inputs["Base Color"].links[0].from_node
    check(top.name == LY.part('BASE_COLOR', m.m3d_layers[2].uid, "mix"), "the Paint Layer is on top of the Base Color chain")
    check(np.array_equal(px(lay_image(2)), GIZMO["stroked"]), "moving layers keeps their pixels")
    m.m3d_layer_index = 2
    check(m.texture_paint_images[m.paint_active_slot] == lay_image(2), "selecting a layer aims the brush at it")
    GIZMO["images"] = {i.name for i in bpy.data.images}
    GIZMO["fill_mask"] = m.m3d_layers[1].mask.name
    GIZMO["stroke_img"] = lay_image(2).name
    press_ok("m3d.layer_merge_down", _area=tex_areas()[1])


@step
def lay_merge_check():
    m = lay_mat()
    check(lay_names() == ["Base", "Fill Layer"] and m.m3d_layer_index == 1, "Merge Down: %s" % lay_names())
    low = m.m3d_layers[1]
    check(low.kind == 'PAINT' and low.mask is None and low.opacity == 1.0 and lay_image(1) is not None,
          "the fill layer became a paint layer without mask or opacity")
    check(GIZMO["stroke_img"] not in bpy.data.images and GIZMO["fill_mask"] not in bpy.data.images, "the merged layer's and the old mask images are gone")
    merged = px(lay_image(1))
    check(abs(merged[:, 3].min() - 0.5) < 0.02 and merged[:, 3].max() > 0.9 and np.ptp(merged[:, 0]) > 0.2,
          "the merged layer holds the half-opaque fill and the stroke (alpha %.2f-%.2f, red range %.2f)" % (
              merged[:, 3].min(), merged[:, 3].max(), np.ptp(merged[:, 0])))
    check(m.texture_paint_images[m.paint_active_slot] == lay_image(1), "the brush is on the merged layer")
    GIZMO["out2"] = tempfile.mkdtemp(prefix="m3d_gui_layers_")
    tx = bpy.context.scene.m3d_tex
    tx.export_folder, tx.export_preset, tx.export_size = GIZMO["out2"], 'UNREAL', 'SAME'
    press_ok("m3d.tex_export", _area=tex_areas()[1])


@step
def lay_export_check():
    files = sorted(os.listdir(GIZMO["out2"]))
    check(files == ["T_Crate_BC.png", "T_Crate_ORM.png"], "export of a stack wrote the Unreal files (%s)" % files)
    m = lay_mat()
    img = bpy.data.images.load(os.path.join(GIZMO["out2"], "T_Crate_BC.png"))
    img.colorspace_settings.name = 'Non-Color'
    file_px = px(img)[:, :3]
    want = LY.flatten_channel(m, 'BASE_COLOR', 128)[..., :3].reshape(-1, 3)
    check(file_px.shape == want.shape and np.abs(file_px - want).max() < 3 / 255,
          "the exported base color is the flattened stack (largest difference %.4f)" % np.abs(file_px - want).max())
    bpy.data.images.remove(img)
    check(lay_names() == ["Base", "Fill Layer"], "export left the layers alone")
    lay_show_tab()
    press_ok("m3d.layer_flatten", _area=tex_areas()[1])


@step
def lay_flatten_check():
    m = lay_mat()
    check(lay_names() == ["Base"] and LY.entry_of(m.m3d_layers[0], 'BASE_COLOR').image is not None, "Flatten: %s" % lay_names())
    check(not tracebacks(), "Python error while the layer stack was edited in the Texture workspace")
    lay_show_tab()


@step
def lay_fill_stroke_setup():
    press_ok("m3d.layer_add", _area=tex_areas()[1], kind='FILL')


@step
def lay_fill_stroke_aim():
    m = lay_mat()
    check(lay_names() == ["Base", "Fill Layer"] and m.m3d_layers[1].kind == 'FILL' and m.m3d_layers[1].mask is None,
          "a fill layer without a mask is active: %s" % lay_names())
    now = m.texture_paint_images[m.paint_active_slot]
    check(now.name == LY.SCRATCH and now not in LY.stack_images(m), "the brush is aimed at the scratch image, not at a layer image (%s)" % now.name)
    GIZMO["layer_pixels"] = {i.name: px(i).copy() for i in LY.stack_images(m)}
    GIZMO["scratch_before"] = px(now).copy()
    event('MOUSEMOVE', xy=GIZMO["stroke"][0])


@step
def lay_fill_stroke_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["stroke"][0])
    for xy in GIZMO["stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def lay_fill_stroke_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["stroke"][-1])


@step
def lay_fill_stroke_check():
    m = lay_mat()
    images = LY.stack_images(m)
    check({i.name for i in images} == set(GIZMO["layer_pixels"]) and all(np.array_equal(px(i), GIZMO["layer_pixels"][i.name]) for i in images),
          "a stroke with a fill layer active changed no layer image")
    scratch = bpy.data.images.get(LY.SCRATCH)
    check(scratch is not None and np.abs(px(scratch) - GIZMO["scratch_before"]).max() > 0.1, "...the stroke did happen: it went to the scratch image")
    check(m.texture_paint_images[m.paint_active_slot] == scratch, "the brush is still on the scratch image")
    check(not tracebacks(), "Python error during the stroke on a fill layer")


@step
def lay_done():
    check(not tracebacks(), "Python error drawing the Layers tab")


@step
def tex_done():
    ws = window().workspace
    ws.m3d_page_left = ws.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')
    check(not tracebacks(), "Python error in the Texture workspace tests")


# ----------------------------------------------------------------------------------------------------
# Phase 4: Rigging workspace with a real cylinder: layout, F5, Joint tool by clicks, Ctrl+E, Orient, mirror, bind, Weight Paint
# from the Status Line, flood, IK with pole, control shape, Driven Key, Test tab, Drivers editor, mode-aware tabs, every tab.

import math

import m3d_rig


def rig_dock():
    """(bone collections editor, dock) Properties editors of the Rigging screen."""
    areas = sorted(props_areas(), key=lambda a: a.x)
    return areas[0], areas[-1]


def rig_view():
    """(3D view area, its window region) of the Rigging screen."""
    area = next(a for a in window().screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def rig_xy(dx=0, dy=0):
    _area, region = rig_view()
    return region.x + region.width // 2 + dx, region.y + region.height // 2 + dy


def rig_obj():
    return bpy.data.objects.get("Armature")


def rig_status(idname, **props):
    """A Status Line button: the operator in the top bar's own context."""
    with bpy.context.temp_override(window=window(), screen=window().screen):
        return getattr(getattr(bpy.ops, idname.split(".")[0]), idname.split(".")[1])('INVOKE_DEFAULT', **props)


def rig_page():
    return window().workspace.m3d_page_right


def rig_click(xy):
    event('MOUSEMOVE', xy=xy)
    event('LEFTMOUSE', 'PRESS', xy)
    event('LEFTMOUSE', 'RELEASE', xy)


@step
def rig_setup():
    # A clean scene with a cylinder, then F5.
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.3, depth=2.0, location=(0, 0, 1.0), end_fill_type='NGON')
        body = bpy.context.active_object
        body.name = "Body"
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.subdivide(number_cuts=5)
        bpy.ops.object.mode_set(mode='OBJECT')
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('F5', 'PRESS', GIZMO["center"])
    event('F5', 'RELEASE', GIZMO["center"])


step(wait_until(lambda: window().workspace.name == "Rigging", "F5 to switch to Rigging"))


@step
def rig_f5_check():
    check(window().workspace.name == "Rigging" and bpy.context.mode == 'OBJECT', "F5 enters Rigging in Object Mode (%s)" % bpy.context.mode)
    # The earlier dock tests moved this workspace's tabs: Reset Workspace brings the factory layout back to check it.
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.workspace_reset()


step(wait_until(lambda: [w.name for w in bpy.data.workspaces if w.name.startswith("Rigging")] == ["Rigging"]
                and window().workspace.name == "Rigging", "Reset Workspace to finish"))


@step
def rig_layout_check():
    screen = window().screen
    left, dock = rig_dock()
    view, _region = rig_view()
    outliner = [a for a in screen.areas if a.type == 'OUTLINER']
    check(len(props_areas()) == 2 and len(outliner) == 1, "Rigging: Outliner and bone collections left, one dock right")
    check(outliner and outliner[0].x < view.x < dock.x and left.x < view.x and left.y < outliner[0].y, "Rigging layout: left column (Outliner over bone collections), viewport, dock")
    check(view.width > left.width * 4 and dock.width >= 600, "the viewport is the large one (%d vs %d, dock %d)" % (view.width, left.width, dock.width))
    bottom = m3d_rig.bottom_area(screen)
    check(bottom is not None and bottom.ui_type == 'TIMELINE' and bottom.height < 400, "Rigging: a short Timeline at the bottom (%s)" %
          ((bottom.ui_type, bottom.height) if bottom else None,))
    check(len([a for a in screen.areas if a.type == 'VIEW_3D']) == 1, "one viewport")
    check(outliner and outliner[0].spaces.active.use_filter_object_content, "the Outliner shows the object contents (bones)")
    check(left.spaces.active.context == dock.spaces.active.context == 'MODELING_TOOLKIT', "docks open on pages")
    with bpy.context.temp_override(window=window(), area=left):
        check(m3d_workspace.side_of(bpy.context) == 'LEFT' and m3d_workspace.active_page(bpy.context) == "rig_bones", "left page is the bone collections")
    with bpy.context.temp_override(window=window(), area=dock):
        check(m3d_workspace.active_page(bpy.context) == "rig_skeleton", "dock opens on Skeleton")
    check(m3d_ui.shelf_key(bpy.context.window_manager, 'RIG') == 'RIG_SKELETON', "Skeleton shelf tab first")
    check(view.spaces.active.overlay.show_xray_bone and view.spaces.active.shading.type == 'SOLID', "bones show through in the viewport")
    check(window().workspace.object_mode == 'OBJECT', "workspace enters Object Mode")
    check(not tracebacks(), "Python error drawing the Rigging workspace")
    check(m3d_rig.missing(bpy.context, ('RIG', 'EDIT')) == ['RIG', 'EDIT'], "no skeleton yet")


# --- Joint tool: three clicks make a two-bone chain
@step
def rig_joint_start():
    GIZMO["joint_points"] = [rig_xy(-80, 160), rig_xy(-80, 0), rig_xy(60, -150)]
    res = press_ok("m3d.rig_joint")
    check(res is not None, "Joint tool button")


@step
def rig_joint_click1():
    ob = rig_obj()
    check(ob is not None and ob.mode == 'EDIT' and ob.show_in_front, "the Joint tool made a skeleton and entered Edit Mode (%s)" %
          (ob and ob.mode))
    check(any(op.bl_idname == "M3D_OT_rig_joint" for op in window().modal_operators), "the Joint tool is running")
    rig_click(GIZMO["joint_points"][0])


@step
def rig_joint_click2():
    rig_click(GIZMO["joint_points"][1])


@step
def rig_joint_click3():
    check(len(rig_obj().data.edit_bones) == 1, "two joints make a bone")
    rig_click(GIZMO["joint_points"][2])


@step
def rig_joint_finish():
    check(len(rig_obj().data.edit_bones) == 2, "three joints make two bones (%d)" % len(rig_obj().data.edit_bones))
    event('RET', 'PRESS', GIZMO["joint_points"][2])
    event('RET', 'RELEASE', GIZMO["joint_points"][2])


@step
def rig_joint_check():
    ob = rig_obj()
    check(not window().modal_operators, "Enter finished the Joint tool")
    bones = list(ob.data.edit_bones)
    check(len(bones) == 2 and bones[1].parent == bones[0] and bones[1].use_connect and bones[0].parent is None, "a connected two-bone chain")
    from bpy_extras.view3d_utils import region_2d_to_location_3d
    view, region = rig_view()
    rv3d = view.spaces.active.region_3d
    # The first joint is on the view plane through the 3D cursor, the next ones on the plane through the previous joint.
    depth = bpy.context.scene.cursor.location
    first = region_2d_to_location_3d(region, rv3d, (GIZMO["joint_points"][0][0] - region.x, GIZMO["joint_points"][0][1] - region.y), depth)
    check((bones[0].head - first).length < 1e-3, "the first joint is where the first click was (%s vs %s)" % (tuple(bones[0].head), tuple(first)))
    second = region_2d_to_location_3d(region, rv3d, (GIZMO["joint_points"][1][0] - region.x, GIZMO["joint_points"][1][1] - region.y), first)
    check((bones[0].tail - second).length < 1e-3, "...and the second (%s vs %s)" % (tuple(bones[0].tail), tuple(second)))
    check(not tracebacks(), "Python error in the Joint tool")
    GIZMO["bones"] = [b.name for b in bones]


# --- Escape cancels
@step
def rig_joint_cancel_start():
    press_ok("m3d.rig_joint")


@step
def rig_joint_cancel_click():
    rig_click(rig_xy(150, 100))
    rig_click(rig_xy(250, 100))


@step
def rig_joint_cancel_esc():
    check(len(rig_obj().data.edit_bones) == 3, "a third bone while the tool runs")
    event('ESC', 'PRESS', rig_xy(250, 100))
    event('ESC', 'RELEASE', rig_xy(250, 100))


@step
def rig_joint_cancel_check():
    check(len(rig_obj().data.edit_bones) == 2 and not window().modal_operators, "Esc takes back the joints of this run")


# --- Ctrl+E extrudes a bone from the selected tip
@step
def rig_extrude_start():
    ob = rig_obj()
    arm = ob.data
    for eb in arm.edit_bones:
        eb.select = eb.select_head = eb.select_tail = False
    tip = arm.edit_bones[GIZMO["bones"][1]]
    tip.select = tip.select_tail = True
    arm.edit_bones.active = tip
    GIZMO["bone_count"] = len(arm.edit_bones)
    event('MOUSEMOVE', xy=rig_xy())
    event('E', 'PRESS', rig_xy(), ctrl=True)
    event('E', 'RELEASE', rig_xy(), ctrl=True)


@step
def rig_extrude_move():
    for i in range(1, 6):
        event('MOUSEMOVE', xy=rig_xy(i * 20, -i * 10))


@step
def rig_extrude_confirm():
    event('RET', 'PRESS', rig_xy(100, -50))
    event('RET', 'RELEASE', rig_xy(100, -50))


@step
def rig_extrude_check():
    arm = rig_obj().data
    check(len(arm.edit_bones) == GIZMO["bone_count"] + 1, "Ctrl+E extruded a bone (%d -> %d)" % (GIZMO["bone_count"], len(arm.edit_bones)))
    newest = [b for b in arm.edit_bones if b.name not in GIZMO["bones"]]
    check(newest and newest[0].parent is not None and newest[0].parent.name == GIZMO["bones"][1], "...from the tip of the selected bone")
    check(not window().modal_operators, "the extrude finished")
    check(not tracebacks(), "Python error while extruding")
    GIZMO["bones"] += [b.name for b in newest]


# --- Orient Joint from the Skeleton tab
@step
def rig_orient():
    s = bpy.context.scene.m3d_rig
    s.orient_axis, s.orient_dir = 'Z', '+Z'
    arm = rig_obj().data
    for eb in arm.edit_bones:
        eb.select = True
    press_ok("m3d.rig_orient")


@step
def rig_orient_check():
    arm = rig_obj().data
    for eb in arm.edit_bones:
        m = eb.matrix.to_3x3()
        x, y, z = m.col[0], m.col[1], m.col[2]
        best = math.sqrt(max(0.0, 1.0 - y.z * y.z))
        check(abs(z.z - best) < 1e-3 and abs(x.dot(y)) < 1e-3 and abs(z.dot(y)) < 1e-3, "Orient Joint: %s Z axis as close to +Z as possible (%.3f of %.3f)" % (eb.name, z.z, best))


# --- Names L/R and Mirror: move the chain to +X, name it by position, mirror it
@step
def rig_mirror():
    arm = rig_obj().data
    moved = [(eb.name, eb.head.copy(), eb.tail.copy()) for eb in arm.edit_bones]
    for name, head, tail in moved:
        eb = arm.edit_bones[name]
        eb.head, eb.tail = head + Vector((1, 0, 0)), tail + Vector((1, 0, 0))
        eb.select = eb.select_head = eb.select_tail = True
    press_ok("armature.autoside_names", type='XAXIS')


@step
def rig_mirror_names():
    arm = rig_obj().data
    check(all(m3d_rig.side_of_name(b.name) == "L" for b in arm.edit_bones), "Names L/R: bones on +X are .L (%s)" % [b.name for b in arm.edit_bones])
    GIZMO["left"] = sorted(b.name for b in arm.edit_bones)
    press_ok("armature.symmetrize", direction='POSITIVE_X')


@step
def rig_mirror_check():
    arm = rig_obj().data
    names = {b.name for b in arm.edit_bones}
    check(len(names) == len(GIZMO["left"]) * 2 and {bpy.utils.flip_name(n) for n in GIZMO["left"]} <= names, "Mirror: every .L bone has a .R bone (%s)" % sorted(names))
    check(not [b for b in arm.edit_bones if m3d_rig.side_of_name(b.name) == "R" and b.head.x > 0], "...on the -X side")
    check(not [m for _n, m in m3d_rig.name_issues(rig_obj()) if "mirror" in m.lower() or "side" in m.lower()],
          "the naming check finds no missing mirror: %s" % m3d_rig.name_issues(rig_obj()))


# --- Skeleton of our own inside the cylinder, then bind
@step
def rig_skeleton_inside():
    ob = rig_obj()
    arm = ob.data
    for eb in list(arm.edit_bones):
        arm.edit_bones.remove(eb)
    chain = m3d_rig.JointChain(ob.name, "Spine")
    for z in (0.1, 0.7, 1.3, 1.9):
        chain.add(Vector((0, 0, z)))
    bpy.ops.m3d.rig_mode('INVOKE_DEFAULT', mode='OBJECT')


step(wait_until(lambda: bpy.context.mode == 'OBJECT', "Object Mode"))


@step
def rig_bind():
    body = bpy.data.objects["Body"]
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.context.scene.m3d_rig.skin_method = 'AUTO'
    left, dock = rig_dock()
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    press_ok("m3d.dock_page", tab="rig_skin")
    press_ok("m3d.rig_bind")


@step
def rig_bind_check():
    body, ob = bpy.data.objects["Body"], rig_obj()
    check(m3d_rig.is_bound(body) and m3d_rig.armature_of(body) == ob, "Bind from the Skin tab")
    check([g.name for g in body.vertex_groups] == ["Spine", "Spine.001", "Spine.002"] and m3d_rig.unweighted(body, ob) == 0,
          "automatic weights on every vertex (%s)" % [g.name for g in body.vertex_groups])
    check(rig_page() == "rig_skin", "the Skin tab is open")
    check(not tracebacks(), "Python error while binding")


# --- Weight Paint from the Status Line
@step
def rig_weight_paint():
    rig_status("m3d.rig_mode", mode='WEIGHT_PAINT')


step(wait_until(lambda: bpy.context.mode == 'PAINT_WEIGHT', "Weight Paint Mode from the Status Line"))


@step
def rig_weight_paint_check():
    body, ob = bpy.data.objects["Body"], rig_obj()
    check(body.mode == 'WEIGHT_PAINT' and ob.mode == 'POSE' and bpy.context.active_object == body, "mesh paints, skeleton stays in Pose Mode (%s %s)" % (body.mode, ob.mode))
    check(ob.select_get() and body.select_get(), "both are selected")
    check(m3d_rig.mode_key(bpy.context.view_layer) == 'WEIGHT_PAINT', "mode key")


step(wait_until(lambda: rig_page() == "rig_skin", "the dock to stay on the Skin tab in Weight Paint Mode"))


@step
def rig_flood():
    body = bpy.data.objects["Body"]
    body.vertex_groups.active_index = 1
    ts = bpy.context.tool_settings
    ts.weight_paint.unified_paint_settings.use_unified_weight = True
    ts.weight_paint.unified_paint_settings.weight = 0.5
    for group in body.vertex_groups:
        group.lock_weight = False
    press_ok("paint.weight_set")


@step
def rig_flood_check():
    body = bpy.data.objects["Body"]
    gi = body.vertex_groups[1].index
    values = [next((g.weight for g in v.groups if g.group == gi), 0.0) for v in body.data.vertices]
    check(min(values) > 0.499 and max(values) < 0.501, "Flood set the active group to the brush weight (%.3f .. %.3f)" % (min(values), max(values)))
    check(not tracebacks(), "Python error while flooding")
    press_ok("object.vertex_group_normalize_all", group_select_mode='BONE_DEFORM', lock_active=False)


@step
def rig_normalize_check():
    body = bpy.data.objects["Body"]
    sums = [sum(g.weight for g in v.groups) for v in body.data.vertices]
    check(all(abs(s - 1.0) < 1e-3 for s in sums if s > 0), "Normalize All: weights add up to 1")


# --- Pose Mode from the Status Line opens the Controls tab; IK with a pole, control shape, locks
@step
def rig_pose_mode():
    rig_status("m3d.rig_mode", mode='POSE')


step(wait_until(lambda: bpy.context.mode == 'POSE' and rig_page() == "rig_controls", "Pose Mode to open the Controls & Constraints tab"))


@step
def rig_ik():
    ob = rig_obj()
    check(bpy.context.active_object == ob and ob.mode == 'POSE', "Pose button makes the skeleton active")
    ob.data.bones.active = ob.data.bones["Spine.001"]
    for pb in ob.pose.bones:
        pb.select = pb.name == "Spine.001"
    bpy.context.scene.m3d_rig.ik_chain = 2
    press_ok("m3d.rig_ik_pole")


@step
def rig_ik_check():
    pb = rig_obj().pose.bones["Spine.001"]
    cons = [c for c in pb.constraints if c.type == 'IK']
    check(cons and cons[0].target == rig_obj() and cons[0].subtarget == "IK_Spine.001" and cons[0].pole_subtarget == "Pole_Spine.001",
          "IK with Pole from the Controls tab")
    check(rig_obj().mode == 'POSE', "...and back in Pose Mode")
    check(not tracebacks(), "Python error while adding the IK")


@step
def rig_control_shape():
    ob = rig_obj()
    for pb in ob.pose.bones:
        pb.select = pb.name == "IK_Spine.001"
    ob.data.bones.active = ob.data.bones["IK_Spine.001"]
    s = bpy.context.scene.m3d_rig
    s.control_color = (0.1, 0.8, 0.3)
    press_ok("m3d.rig_control", shape='CIRCLE')
    press_ok("m3d.rig_lock", channels='ROTATION', lock=True)


@step
def rig_control_shape_check():
    pb = rig_obj().pose.bones["IK_Spine.001"]
    check(pb.custom_shape is not None and pb.custom_shape.name == "WGT-Circle" and pb.color.palette == 'CUSTOM', "control shape and color from the Controls tab")
    check(all(pb.lock_rotation) and not any(pb.lock_location), "Lock Rotate")
    check(bpy.data.collections.get("Widgets") is not None, "Widgets collection")
    check(not tracebacks(), "Python error with the control shape")


# --- Driven Key from the Drive tab
@step
def rig_driven_key():
    ob = rig_obj()
    s = bpy.context.scene.m3d_rig
    press_ok("m3d.dock_page", tab="rig_drive")
    ob.pose.bones["Spine"].rotation_mode = 'XYZ'
    s.dk_driver_object, s.dk_driver_bone, s.dk_driver_channel = ob, "Spine", 'ROT_X'
    s.dk_kind, s.dk_driven_object, s.dk_driven_bone, s.dk_driven_channel = 'BONE', ob, "Spine.002", 'SCL_Y'
    s.dk_interp = 'LINEAR'
    ob.pose.bones["Spine"].rotation_euler[0] = 0.0
    s.dk_value = 1.0
    press_ok("m3d.rig_driven_key", action='KEY')
    ob.pose.bones["Spine"].rotation_euler[0] = math.pi / 2
    s.dk_value = 2.0
    press_ok("m3d.rig_driven_key", action='KEY')
    ob.pose.bones["Spine"].rotation_euler[0] = math.pi / 4


@step
def rig_driven_key_check():
    ob = rig_obj()
    keys = m3d_rig.driven_keys(m3d_rig.driven_channel(bpy.context.scene.m3d_rig))
    check(len(keys) == 2 and abs(keys[1][1] - 2.0) < 1e-4, "Driven Key pairs: %s" % keys)
    check(abs(ob.pose.bones["Spine.002"].scale[1] - 1.5) < 1e-3, "a quarter turn of the driver gives the middle value (%s)" % ob.pose.bones["Spine.002"].scale[1])
    check(rig_page() == "rig_drive", "Drive tab picked")
    check(not tracebacks(), "Python error with the Driven Key")


# --- Test tab: reset pose
@step
def rig_reset():
    ob = rig_obj()
    ob.pose.bones["Spine.001"].rotation_mode = 'XYZ'
    ob.pose.bones["Spine.001"].rotation_euler = (0.3, 0.2, 0.1)
    ob.pose.bones["Spine"].rotation_euler[0] = 0.0
    press_ok("m3d.dock_page", tab="rig_test")
    press_ok("m3d.rig_reset_pose")


@step
def rig_reset_check():
    ob = rig_obj()
    check(all(abs(v) < 1e-6 for v in ob.pose.bones["Spine.001"].rotation_euler), "Reset Pose on the Test tab")
    check(not tracebacks(), "Python error on the Test tab")


# --- Drivers editor toggle (Status Line button and Drive tab button)
@step
def rig_drivers_open():
    check(m3d_rig.bottom_area(window().screen).ui_type == 'TIMELINE', "Timeline at first")
    rig_status("m3d.rig_drivers_editor")


@step
def rig_drivers_check():
    area = m3d_rig.bottom_area(window().screen)
    check(area is not None and area.ui_type == 'DRIVERS' and area.type == 'GRAPH_EDITOR' and area.spaces.active.mode == 'DRIVERS',
          "Status Line button: the bottom editor is the Drivers editor (%s)" % ((area.type, area.ui_type) if area else None,))
    check(m3d_rig.drivers_open(window().screen), "drivers_open")
    press_ok("m3d.rig_drivers_editor")


@step
def rig_drivers_back():
    area = m3d_rig.bottom_area(window().screen)
    check(area is not None and area.ui_type == 'TIMELINE', "...and again: back to the Timeline")
    check(not tracebacks(), "Python error with the Drivers editor")


# --- Tabs follow the mode, and keep the tab picked in a mode
@step
def rig_follow_edit():
    rig_status("m3d.rig_mode", mode='OBJECT')


step(wait_until(lambda: bpy.context.mode == 'OBJECT', "Object Mode"))


@step
def rig_follow_edit2():
    rig_status("m3d.rig_mode", mode='EDIT')


step(wait_until(lambda: bpy.context.mode == 'EDIT_ARMATURE' and rig_page() == "rig_skeleton", "Edit Mode to open the Skeleton tab"))


@step
def rig_follow_pose():
    rig_status("m3d.rig_mode", mode='POSE')


step(wait_until(lambda: bpy.context.mode == 'POSE' and rig_page() == "rig_test", "Pose Mode to bring back the Test tab picked there"))


@step
def rig_follow_pick():
    press_ok("m3d.dock_page", tab="rig_collections")
    rig_status("m3d.rig_mode", mode='OBJECT')


step(wait_until(lambda: bpy.context.mode == 'OBJECT', "Object Mode"))


@step
def rig_follow_pick2():
    check(rig_page() == "rig_collections", "leaving a mode keeps the tab")
    rig_status("m3d.rig_mode", mode='POSE')


step(wait_until(lambda: bpy.context.mode == 'POSE' and rig_page() == "rig_collections", "Pose Mode to bring back the last pick"))


@step
def rig_follow_all_settings():
    # On All Settings the dock is left alone.
    left, dock = rig_dock()
    dock.spaces.active.context = 'OBJECT'
    rig_status("m3d.rig_mode", mode='OBJECT')


step(wait_until(lambda: bpy.context.mode == 'OBJECT', "Object Mode"))


@step
def rig_follow_all_settings2():
    rig_status("m3d.rig_mode", mode='EDIT')


step(wait_until(lambda: bpy.context.mode == 'EDIT_ARMATURE', "Edit Mode"))


@step
def rig_follow_all_settings3():
    left, dock = rig_dock()
    check(dock.spaces.active.context == 'OBJECT', "a dock on All Settings is not switched")
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    rig_status("m3d.rig_mode", mode='OBJECT')


# --- Names marking menu opens with Shift+N in Edit Mode
@step
def rig_names_menu_open():
    rig_status("m3d.rig_mode", mode='EDIT')


step(wait_until(lambda: bpy.context.mode == 'EDIT_ARMATURE', "Edit Mode"))


@step
def rig_names_menu_key():
    event('MOUSEMOVE', xy=rig_xy())
    event('N', 'PRESS', rig_xy(), shift=True)
    event('N', 'RELEASE', rig_xy(), shift=True)


@step
def rig_names_menu_check():
    check(not tracebacks(), "Python error drawing the names menu")
    event('ESC', 'PRESS', rig_xy())
    event('ESC', 'RELEASE', rig_xy())


# --- Every tab draws, in Object, Edit, Pose and Weight Paint Mode
def _rig_tab_steps():
    for mode in ('OBJECT', 'EDIT', 'POSE', 'WEIGHT_PAINT'):
        for tab in (*m3d_workspace.DOCK_TABS['RIG']['RIGHT'], *m3d_workspace.DOCK_TABS['RIG']['LEFT']):
            def show(tab=tab, mode=mode):
                bpy.ops.m3d.rig_mode(mode=mode)
                left, dock = rig_dock()
                area = left if tab.page == "rig_bones" else dock
                area.spaces.active.context = 'MODELING_TOOLKIT'
                press_ok("m3d.dock_page", _area=area, tab=tab.id)
                for a in window().screen.areas:
                    a.tag_redraw()

            def check_draw(tab=tab, mode=mode):
                side = "left" if tab.page == "rig_bones" else "right"
                check(getattr(window().workspace, "m3d_page_" + side) == tab.page, "dock tab %s did not open its page" % tab.id)
                check(not tracebacks(), "Python error while drawing the Rigging page %s in %s" % (tab.page, mode))
            show.__name__, check_draw.__name__ = "rig_show_%s_%s" % (tab.page, mode), "rig_drawn_%s_%s" % (tab.page, mode)
            yield show
            yield check_draw


for _fn in _rig_tab_steps():
    step(_fn)


@step
def rig_shelves():
    # Every Rigging shelf and the Status Line draw in each mode.
    for mode in ('POSE', 'EDIT', 'OBJECT'):
        bpy.ops.m3d.rig_mode(mode=mode)
        for key in m3d_ui.shelves_for('RIG'):
            bpy.context.window_manager.m3d_shelf = key
            for a in window().screen.areas:
                a.tag_redraw()


@step
def rig_shelves_check():
    check(not tracebacks(), "Python error drawing the Rigging shelves / Status Line")
    bpy.context.window_manager.m3d_shelf = 'RIG_SKELETON'
    ws = window().workspace
    ws.m3d_page_left = ws.m3d_page_right = ""
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    bpy.ops.m3d.workspace(kind='MODEL')
    check(not tracebacks(), "Python error in the Rigging workspace tests")


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


# M3D_GUI_FROM=<step name> skips the steps before it (to iterate on one workspace; the full run is the one that counts).
_from = os.environ.get("M3D_GUI_FROM")
if _from:
    _names = [fn.__name__ for fn in steps]
    steps[:] = steps[_names.index(_from):]

bpy.app.timers.register(run_next, first_interval=2.0)
