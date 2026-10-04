# SPDX-License-Identifier: GPL-2.0-or-later
"""
Interactive self-check for Maelstrom3D behaviour that needs a real window (gizmo drags, held keys).

    blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result-file>

Writes "FAILS: [...]" to <result-file> and quits.
"""

import sys

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1]
fails = []
steps = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


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


@step
def hover_z_arrow():
    _win, area, region = view3d()
    rv3d = area.spaces.active.region_3d
    ob = bpy.context.active_object
    center = ob.matrix_world.translation
    p0 = location_3d_to_region_2d(region, rv3d, center)
    p1 = location_3d_to_region_2d(region, rv3d, center + Vector((0, 0, 1)))
    direction = (p1 - p0).normalized()
    GIZMO["start"] = to_window(region, p0 + direction * 45)
    GIZMO["end"] = to_window(region, p0 + direction * 120)
    GIZMO["faces"] = len(ob.data.polygons)
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
    consoles = [a.spaces.active.language for a in bpy.data.screens["Classic"].areas if a.type == 'CONSOLE']
    check(consoles == ['mel'], "command line is not MEL: %r" % consoles)


@step
def dock_tabs_object():
    # Draw every Maya dock tab (draw errors show up as tracebacks in Blender's output).
    GIZMO["dock"] = [a for a in bpy.data.screens["Classic"].areas if a.type == 'PROPERTIES'][0].spaces.active
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
    viewport_sidebars = [a.spaces.active.show_region_ui for a in bpy.data.screens["Classic"].areas
                         if a.type == 'VIEW_3D']
    check(not any(viewport_sidebars), "viewport sidebar open at startup")
    lenses = {a.spaces.active.lens for a in bpy.data.screens["Classic"].areas if a.type == 'VIEW_3D'}
    check(lenses == {70.0}, "viewport lens is not Maya's field of view: %r" % lenses)
    uv = [a for a in bpy.data.screens["UV Editing"].areas if a.type == 'IMAGE_EDITOR']
    check(uv and uv[0].spaces.active.show_region_ui, "UV Toolkit not docked in the UV Editor")


@step
def finish():
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
