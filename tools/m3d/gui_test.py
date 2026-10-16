# SPDX-License-Identifier: GPL-2.0-or-later
"""
Interactive self-check for Maelstrom3D behaviour that needs a real window (gizmo drags, held keys).

    blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result-file>

Writes "FAILS: [...]" to <result-file> and quits.
"""

import math
import os
import sys

import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector

import m3d_bakeq as QB
import m3d_bakeview as BVW
import m3d_edit
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


def restore_window():
    """A window started behind the apps in use can come up minimized, and a minimized window draws nothing (every picture is black):
    show it again without taking the focus. Windows only."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32, pid = ctypes.windll.user32, os.getpid()

        def show(hwnd, _param):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
            return True
        user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(show), 0)
    except Exception as err:   # (a picture of a minimized window shows it)
        print("restore_window:", err)


@step
def setup():
    restore_window()
    check(bpy.context.scene.render.filepath == m3d_render.DEFAULT_OUTPUT, "a new file renders into //render/, not /tmp/ (%r)"
          % bpy.context.scene.render.filepath)
    lb_sandbox()   # (the Library tab: temporary folders and no thumbnails for the tests of the other phases, see lb_setup)
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


# ----------------------------------------------------------------------------------------------------
# Alt+RMB zoom: drag right zooms in, left zooms out, in the 3D view and the 2D editors (factory preferences).

ZOOM = {}
ZOOM_EDITORS = ('IMAGE_EDITOR', 'FCURVES', 'ShaderNodeTree')   # The 2D ones take over the Outliner.


def _zoom_area():
    return ZOOM["area"]


def _zoom_region():
    return next(r for r in _zoom_area().regions if r.type == 'WINDOW')


def _zoom_measure():
    """Grows when the view zooms in."""
    space = _zoom_area().spaces.active
    if space.type == 'VIEW_3D':
        return 1.0 / space.region_3d.view_distance
    if space.type == 'IMAGE_EDITOR':
        return space.zoom[0]
    region = _zoom_region()
    return 1.0 / (region.view2d.region_to_view(region.width, 0)[0] - region.view2d.region_to_view(0, 0)[0])


def _zoom_drag(sign):
    x, y = ZOOM["xy"]
    event('LEFT_ALT', 'PRESS', ZOOM["xy"], alt=True)
    event('RIGHTMOUSE', 'PRESS', ZOOM["xy"], alt=True)
    for i in range(1, 11):
        event('MOUSEMOVE', xy=(x + sign * ZOOM["dx"] * i // 10, y), alt=True)


def _zoom_release(sign):
    xy = (ZOOM["xy"][0] + sign * ZOOM["dx"], ZOOM["xy"][1])
    event('RIGHTMOUSE', 'RELEASE', xy, alt=True)
    event('LEFT_ALT', 'RELEASE', xy)


def _zoom_steps():
    for editor in ('VIEW_3D', *ZOOM_EDITORS):
        def start(editor=editor):
            ZOOM["editor"] = editor
            if editor == 'VIEW_3D':
                ZOOM["area"] = view3d()[1]
            else:
                if "outliner" not in ZOOM:
                    ZOOM["outliner"] = max((a for a in window().screen.areas if a.type == 'OUTLINER'),
                                           key=lambda a: a.width * a.height)
                ZOOM["area"] = ZOOM["outliner"]
                ZOOM["area"].ui_type = editor

        def settle():
            pass   # The 2D editor draws once before its view is sized.

        def hover():
            region = _zoom_region()
            ZOOM["xy"] = (region.x + region.width // 2, region.y + region.height // 2)
            ZOOM["dx"] = min(80, region.width // 4)
            ZOOM["start"] = _zoom_measure()
            event('MOUSEMOVE', xy=ZOOM["xy"])

        def drag_right():
            _zoom_drag(1)

        def release_right():
            _zoom_release(1)

        def zoomed_in():
            ZOOM["in"] = _zoom_measure()
            check(ZOOM["in"] > ZOOM["start"], "Alt+RMB drag right did not zoom in (%s: %s -> %s)" % (
                ZOOM["editor"], ZOOM["start"], ZOOM["in"]))

        def drag_left():
            _zoom_drag(-1)

        def release_left():
            _zoom_release(-1)

        def zoomed_out():
            check(_zoom_measure() < ZOOM["in"], "Alt+RMB drag left did not zoom out (%s: %s -> %s)" % (
                ZOOM["editor"], ZOOM["in"], _zoom_measure()))

        wait_right = wait_until(lambda: _zoom_measure() > ZOOM["start"], "Alt+RMB drag right to zoom")
        wait_left = wait_until(lambda: _zoom_measure() < ZOOM["in"], "Alt+RMB drag left to zoom")
        for fn in (start, settle, hover, drag_right, wait_right, release_right, zoomed_in, drag_left, wait_left, release_left,
                   zoomed_out):
            fn.__name__ = "zoom_%s_%s" % (editor.lower(), fn.__name__)
            yield fn


for _fn in _zoom_steps():
    step(_fn)


@step
def zoom_done():
    ZOOM["outliner"].ui_type = 'OUTLINER'
    check(not tracebacks(), "Python error in the zoom tests")


# ----------------------------------------------------------------------------------------------------
# Shift+drag on the Scale manipulator: extrude (components) / duplicate (objects), then scale along the handle.

SCALE = {}


def _scale_extent():
    """Bounding box size of the selected vertices (components) or of the active object's scale (objects)."""
    ob = bpy.context.active_object
    if ob.mode != 'EDIT':
        return tuple(ob.scale)
    verts = [v.co for v in bmesh.from_edit_mesh(ob.data).verts if v.select]
    return tuple(max(v[i] for v in verts) - min(v[i] for v in verts) for i in range(3))


def _aim_center():
    """GIZMO start/end for the centre handle: out from the centre along the direction farthest from all three axes."""
    _win, area, region = view3d()
    rv3d = area.spaces.active.region_3d
    ob = bpy.context.active_object
    center = ob.matrix_world.translation
    p0 = location_3d_to_region_2d(region, rv3d, center)
    axes = [(location_3d_to_region_2d(region, rv3d, center + Vector(a)) - p0).normalized()
            for a in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    best = max((Vector((math.cos(t * math.pi / 8), math.sin(t * math.pi / 8))) for t in range(16)),
               key=lambda d: min(math.acos(max(-1.0, min(1.0, d.dot(a)))) for a in axes + [-a for a in axes]))
    GIZMO["start"] = to_window(region, p0 + best * SCALE["center_radius"])
    GIZMO["end"] = to_window(region, p0 + best * 110)


def _aim_ring():
    """GIZMO start/end on the Z rotation ring (a point 45 degrees round it in the XY plane), dragged round it."""
    _win, area, region = view3d()
    rv3d = area.spaces.active.region_3d
    ob = bpy.context.active_object
    center = ob.matrix_world.translation
    p0 = location_3d_to_region_2d(region, rv3d, center)
    right = rv3d.view_matrix.inverted().col[0].xyz
    px_per_unit = (location_3d_to_region_2d(region, rv3d, center + right) - p0).length
    radius = SCALE["ring_px"] / px_per_unit
    on_ring = center + Vector((math.cos(math.pi / 4), math.sin(math.pi / 4), 0)) * radius
    v = location_3d_to_region_2d(region, rv3d, on_ring) - p0
    turned = Matrix.Rotation(math.radians(35), 2) @ v
    GIZMO["start"] = to_window(region, p0 + v)
    GIZMO["end"] = to_window(region, p0 + turned)


def _scale_cases():
    """(name, mode, handle, check): every case starts from a fresh selected cube."""
    def x_grows(before, after, _op):
        check(after[0] > before[0] * 1.5, "X handle did not scale along X (%s -> %s)" % (before, after))
        check(abs(after[1] - before[1]) < 1e-3 and abs(after[2] - before[2]) < 1e-3,
              "X handle changed Y or Z (%s -> %s)" % (before, after))

    def all_grow(before, after, _op):
        check(all(a > b * 1.3 for a, b in zip(after, before)), "centre handle did not scale uniformly (%s -> %s)" % (before, after))
        check(abs(after[0] / before[0] - after[1] / before[1]) < 0.05 and abs(after[1] / before[1] - after[2] / before[2]) < 0.05,
              "centre handle scale is not uniform (%s -> %s)" % (before, after))

    def turned(before, after, _op):
        ob = bpy.context.active_object
        if ob.mode == 'EDIT':
            verts = [v.co for v in bmesh.from_edit_mesh(ob.data).verts if v.select]
            check(any(abs(abs(v.x) - abs(v.y)) > 0.02 for v in verts), "Z ring did not rotate the new faces")
            check(all(abs(abs(v.z) - before[2] / 2) < 1e-3 for v in verts), "Z ring moved the new faces off the Z axis")
        else:
            rot = tuple(ob.rotation_euler)
            check(abs(rot[2]) > 0.1 and abs(rot[0]) < 1e-3 and abs(rot[1]) < 1e-3, "Z ring did not rotate the copy (%s)" % (rot,))

    return (("edit_x", 'EDIT', "x", x_grows), ("edit_center", 'EDIT', "center", all_grow),
            ("object_x", 'OBJECT', "x", x_grows), ("edit_ring_z", 'EDIT', "ring_z", turned),
            ("object_ring_z", 'OBJECT', "ring_z", turned))


def _scale_steps():
    for name, mode, handle, verify in _scale_cases():
        def setup(mode=mode, handle=handle):
            win, area, region = view3d()
            with bpy.context.temp_override(window=win, area=area, region=region):
                if bpy.context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                for ob in list(bpy.data.objects):
                    bpy.data.objects.remove(ob)
                bpy.ops.m3d.add_primitive(kind='CUBE')
                if mode == 'EDIT':
                    bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'FACE'})
                    bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.wm.tool_set_by_id(name="builtin.rotate" if handle.startswith("ring") else "builtin.scale")
                bpy.ops.view3d.view_all(center=True)
                bpy.ops.ed.undo_push(message="Scale test start")   # Python calls push no undo steps of their own.

        def hover(handle=handle):
            SCALE["center_radius"] = 8
            SCALE["ring_px"] = 75
            {"x": aim_x_arrow, "center": _aim_center, "ring_z": _aim_ring}[handle]()
            ob = bpy.context.active_object
            SCALE["faces"] = len(ob.data.polygons) if ob.mode == 'EDIT' else len(bpy.data.objects)
            SCALE["before"] = _scale_extent()
            event('MOUSEMOVE', xy=GIZMO["start"])

        def hover_again():
            x, y = GIZMO["start"]
            event('MOUSEMOVE', xy=(x + 1, y))
            event('MOUSEMOVE', xy=(x, y))

        def drag_it():
            drag(shift=True)

        def drag_more():
            shift_drag_more()   # The transform follows the moves that come after it started.

        def release_it():
            event('LEFTMOUSE', 'RELEASE', GIZMO["end"], shift=True)
            event('LEFT_SHIFT', 'RELEASE', GIZMO["end"])

        def checked(mode=mode, verify=verify, name=name):
            ob = bpy.context.active_object
            if ob.mode == 'EDIT':
                ob.update_from_editmode()
            count = len(ob.data.polygons) if mode == 'EDIT' else len(bpy.data.objects)
            check(count > SCALE["faces"], "Scale %s: shift-drag did not %s (ops %s)" % (
                name, "extrude" if mode == 'EDIT' else "duplicate",
                [o.bl_idname for o in bpy.context.window_manager.operators][-3:]))
            ops = [o.bl_idname for o in bpy.context.window_manager.operators]
            wanted = "M3D_OT_%s_%s" % ("extrude" if mode == 'EDIT' else "duplicate", "rotate" if "ring" in name else "resize")
            check(ops and ops[-1] == wanted, "Scale %s: last operator is %s, not %s" % (name, ops[-3:], wanted))
            if ops and ops[-1] == wanted:
                verify(SCALE["before"], _scale_extent(), bpy.context.window_manager.operators[-1])
            if name == "edit_x":
                bpy.ops.ed.undo()   # Extrude and scale are one undo step.
                faces = len(bmesh.from_edit_mesh(bpy.context.edit_object.data).faces)
                check(faces == SCALE["faces"], "extrude + scale took more than one undo (%d faces left)" % faces)

        started = wait_until(lambda: any(o.bl_idname.startswith("M3D_OT_") for o in window().modal_operators),
                             "Shift+drag to start the transform")
        for fn in (setup, hover, hover_again, drag_it, started, drag_more, release_it, checked):
            fn.__name__ = "scale_%s_%s" % (name, "started" if fn is started else fn.__name__)
            yield fn


for _fn in _scale_steps():
    step(_fn)


@step
def scale_done():
    bpy.ops.wm.tool_set_by_id(name="builtin.move")


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


# --- Primitive inputs: shelf cube, change Subdivisions Width, undo, edit a face (inputs freeze).
@step
def inputs_shelf_cube():
    check(any(it and not callable(it) and it[0] == "m3d.add_primitive" and it[2].get("kind") == 'CUBE'
              for _label, items, _kinds in m3d_ui.SHELVES.values() for it in items), "a shelf button makes the cube")
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.m3d.add_primitive('INVOKE_DEFAULT', kind='CUBE')   # What the shelf button runs.
        bpy.ops.ed.undo_push(message="Polygon Cube")
    ob = bpy.context.active_object
    check(ob.m3d_input.kind == 'CUBE' and len(ob.data.vertices) == 8, "shelf cube has Cube inputs")
    next(a for a in window().screen.areas if a.type == 'PROPERTIES').spaces.active.context = 'CHANNEL_BOX'
    for a in window().screen.areas:
        a.tag_redraw()


@step
def inputs_edit_width():
    check(not tracebacks(), "Python error drawing the Cube inputs in the Channel Box")
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        # The property edit of the Channel Box field (data path set, then one undo step as a button edit does).
        bpy.ops.wm.context_set_int(data_path="active_object.m3d_input.sub_width", value=4)
        bpy.ops.ed.undo_push(message="Subdivisions Width")
    ob = bpy.context.active_object
    check(ob.m3d_input.sub_width == 4 and len(ob.data.vertices) == 20 and len(ob.data.polygons) == 18,
          "Subdivisions Width 4 rebuilt the cube: %d verts" % len(ob.data.vertices))


@step
def inputs_undo():
    bpy.ops.ed.undo()


@step
def inputs_undone():
    ob = bpy.context.active_object
    check(ob.m3d_input.sub_width == 1 and len(ob.data.vertices) == 8 and not ob.m3d_input.frozen,
          "undo restored the input and the mesh (%d, %d verts)" % (ob.m3d_input.sub_width, len(ob.data.vertices)))
    bpy.ops.ed.redo()


@step
def inputs_redone():
    ob = bpy.context.active_object
    check(ob.m3d_input.sub_width == 4 and len(ob.data.vertices) == 20, "redo brought the rebuilt mesh back")
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'FACE'})
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        bm.faces[0].select_set(True)
        bmesh.update_edit_mesh(ob.data)
        bpy.ops.transform.translate(value=(0, 0, 0.3))
        bpy.ops.object.mode_set(mode='OBJECT')
    for a in window().screen.areas:
        a.tag_redraw()


@step
def inputs_frozen():
    import m3d_inputs
    ob = bpy.context.active_object
    check(m3d_inputs.is_frozen(ob), "editing a face freezes the inputs")
    ob.m3d_input.sub_width = 6
    check(ob.m3d_input.frozen and len(ob.data.vertices) == 20, "a frozen cube does not rebuild")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def inputs_frozen_drawn():
    check(not tracebacks(), "Python error drawing frozen inputs in the Channel Box")
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.delete_history()
    check(bpy.context.active_object.m3d_input.kind == 'NONE', "Delete History from the Channel Box")


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
            # As the dock's All Settings tab does: the Object tab is only listed once the editor has an active object
            # in its context (right after a workspace switch it may not have been drawn yet), else Scene.
            area = GIZMO["tab_area"]
            m3d_mode.set_dock_context(area.spaces.active, 'OBJECT')
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
    # The dock's tab menu draws.
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


# Dock tab overflow: a narrow dock draws the tabs that fit, the "more" menu has the rest, and a tab picked there
# is shown at once (the active tab is always drawn).

def _dock_of(side):
    areas = sorted(props_areas(), key=lambda a: a.x)
    return areas[0] if side == 'LEFT' else areas[-1]


def _dock_header(area):
    return next(r for r in area.regions if r.type == 'HEADER')


def _dock_split(side):
    area = _dock_of(side)
    with bpy.context.temp_override(window=window(), area=area, region=_dock_header(area)):
        return m3d_workspace.split_dock_tabs(bpy.context)


def _resize_steps(name, side, width):
    """Steps: drag the dock's inner edge until the dock is `width()` px wide."""
    edge = {}

    def aim():
        area, want = _dock_of(side), width()
        mid = area.y + area.height // 2
        # Moving an edge needs the mouse on it (no active region): put it there with a simulated event.
        if side == 'LEFT':
            edge["xy"], edge["delta"] = (area.x + area.width, mid), want - area.width
        else:
            edge["xy"], edge["delta"] = (area.x - 1, mid), area.width - want
        event('MOUSEMOVE', xy=edge["xy"])

    def move():
        with bpy.context.temp_override(window=window(), screen=window().screen):
            bpy.ops.screen.area_move(x=edge["xy"][0], y=edge["xy"][1], delta=edge["delta"])
    aim.__name__, move.__name__ = name + "_aim", name + "_move"
    return [aim, move, wait_until(lambda: abs(_dock_of(side).width - width()) <= 2, name + " dock resize")]


def _overflow_steps():
    for kind, side, narrow in (('MODEL', 'RIGHT', 260), ('RIG', 'RIGHT', 230), ('SCULPT', 'LEFT', 190),
                               ('ANIM', 'RIGHT', 300)):
        name, ctx = "overflow_" + kind, {}

        def switch(kind=kind):
            bpy.ops.m3d.workspace(kind=kind)

        def remember(side=side, ctx=ctx):
            ctx["full"] = _dock_of(side).width

        def check_narrow(kind=kind, side=side, ctx=ctx):
            area = _dock_of(side)
            shown, more, active = _dock_split(side)
            shown_ids, more_ids = [t.id for t, _label in shown], [t.id for t in more]
            check(more_ids, "%s dock at %d px has no overflow" % (kind, area.width))
            check(shown_ids and not set(shown_ids) & set(more_ids), "%s dock tabs drawn twice or none" % kind)
            check(active is None or active in shown_ids, "%s: the active tab %s is not drawn" % (kind, active))
            scale = bpy.context.preferences.system.ui_scale
            ctx["shown_w"] = sum(m3d_workspace.text_width(label, scale) for _t, label in shown)
            used = ctx["shown_w"] + (m3d_workspace.MORE_WIDTH + m3d_workspace.HEADER_RESERVED) * scale
            check(used <= _dock_header(area).width, "%s: tabs need %d px in a %d px header" % (kind, used, area.width))
            check(not tracebacks(), "Python error drawing the narrow %s dock" % kind)
            ctx["more"] = more[0]

        def click_more(side=side, ctx=ctx):
            area = _dock_of(side)
            header = _dock_header(area)
            ctx["xy"] = (area.x + 48 + int(ctx["shown_w"]) + m3d_workspace.MORE_WIDTH // 2, header.y + header.height // 2)
            event('MOUSEMOVE', xy=ctx["xy"])
            event('LEFTMOUSE', 'PRESS', ctx["xy"])
            event('LEFTMOUSE', 'RELEASE', ctx["xy"])

        def pick_first(ctx=ctx):
            xy = (ctx["xy"][0], ctx["xy"][1] - 30)   # The menu opens under the button: its first row.
            event('MOUSEMOVE', xy=xy)
            event('LEFTMOUSE', 'PRESS', xy)
            event('LEFTMOUSE', 'RELEASE', xy)

        def picked(kind=kind, side=side, ctx=ctx):
            tab, context = ctx["more"], _dock_of(side).spaces.active.context
            if tab.id == 'OBJECT':   # All Settings: the stock tabs (the Scene's when nothing is active)
                check(context in {'OBJECT', 'SCENE'}, "%s: the more menu opened %s, not All Settings" % (kind, context))
            else:
                check(context == tab.context, "%s: the more menu did not open %s (%s)" % (kind, tab.id, context))
                if tab.page:
                    check(getattr(window().workspace, "m3d_page_" + side.lower()) == tab.page, "%s: page of %s" % (kind, tab.id))
                shown, _more, active = _dock_split(side)
                check(active == tab.id and shown[-1][0].id == tab.id, "%s: picked tab %s is not drawn last" % (kind, tab.id))
            check(not tracebacks(), "Python error picking a tab from the %s more menu" % kind)
            area = _dock_of(side)   # Back to the first tab.
            with bpy.context.temp_override(window=window(), area=area, region=_dock_header(area)):
                bpy.ops.m3d.dock_page(tab=m3d_workspace.dock_tabs(kind, side)[0].id)

        def restored(kind=kind, side=side, ctx=ctx):
            check(_dock_of(side).width >= ctx["full"] - 2, "%s dock was not widened again" % kind)
            check(kind != 'MODEL' or not _dock_split(side)[1], "Modeling dock at its normal width has an overflow")

        for fn in (switch, remember, check_narrow, click_more, pick_first, picked, restored):
            fn.__name__ = "%s_%s" % (name, fn.__name__)
        yield switch
        yield wait_until(lambda kind=kind: m3d_workspace.workspace_kind(window().workspace) == kind, name + " workspace")
        yield remember
        yield from _resize_steps(name + "_narrow", side, lambda narrow=narrow: narrow)
        yield check_narrow
        yield click_more
        yield pick_first
        yield picked
        yield from _resize_steps(name + "_full", side, lambda ctx=ctx: ctx["full"])
        yield restored


for _fn in _overflow_steps():
    step(_fn)


@step
def overflow_done():
    check(not tracebacks(), "Python error in the dock overflow tests")
    bpy.ops.m3d.workspace(kind='MODEL')


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
    m3d_edit._state["on"] = True   # (the tray's Custom panel then draws its arrows)
    for area in window().screen.areas:
        area.tag_redraw()


@step
def custom_shelf_check():
    check(len(m3d_user.shelf_items('SCULPT')) == 2, "custom shelf items")
    check(not tracebacks(), "Python error while drawing the Custom shelf")
    m3d_edit._state["on"] = False


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
    event('ESC', 'PRESS', GIZMO.get("center"))
    event('ESC', 'RELEASE', GIZMO.get("center"))


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


# Workspace Settings: the gear button at the right end of the Status Line (a popover; the rows are clicked at
# fixed offsets from the window's top right: Reset Workspace, then the tabs of the dock).
WS_SETTINGS_X, WS_SETTINGS_Y = 24, 38           # the gear button, from the right / top edge (UI scale 1)
WS_ROWS = {"reset": 78, "tab0": 138, "tab1": 164, "tab2": 189}   # rows of the popover, from the top edge
WS_ROWS_X = 163                                  # their middle, from the right edge


def ws_event(type, value='NOTHING', xy=None):
    """Like event(), without needing a 3D viewport (the layout may be scrambled)."""
    win = window()
    x, y = xy or (win.width // 2, win.height // 2)
    win.event_simulate(type=type, value=value, x=x, y=y)


def ws_click(xy):
    ws_event('MOUSEMOVE', xy=xy)
    ws_event('LEFTMOUSE', 'PRESS', xy)
    ws_event('LEFTMOUSE', 'RELEASE', xy)


def ws_open():
    """Click Settings (a fresh popover: ESC closes one that is still open)."""
    win = window()
    ws_event('ESC', 'PRESS')
    ws_click((win.width - WS_SETTINGS_X, win.height - WS_SETTINGS_Y))


def ws_row(name):
    win = window()
    ws_click((win.width - WS_ROWS_X, win.height - WS_ROWS[name]))


def _ws_toggle_steps():
    # Modeling: its third tab (Tool Settings); Sculpt: its first (Geometry). Click it hidden, then shown again.
    for kind, row, tab in (('MODEL', "tab2", "tool"), ('SCULPT', "tab0", "sculpt_geometry")):
        def switch(kind=kind):
            bpy.ops.m3d.workspace(kind=kind)

        def open_(kind=kind):
            check(window().workspace.name == m3d_workspace.KINDS[kind][0], "Workspace Settings test is in %s" % kind)
            ws_open()

        def hide(row=row):
            ws_row(row)

        def hidden(kind=kind, tab=tab):
            check(m3d_user.hidden_tabs(kind) == {tab}, "%s: Settings popover did not hide tab %s (%s)" % (kind, tab, m3d_user.hidden_tabs(kind)))
            check(not tracebacks(), "Python error in the Workspace Settings popover (%s)" % kind)
            ws_open()

        def show(row=row):
            ws_row(row)

        def shown(kind=kind):
            check(m3d_user.hidden_tabs(kind) == set(), "%s: Settings popover did not show the tab again" % kind)
            ws_event('ESC', 'PRESS')
        for fn in (switch, open_, hide, hidden, show, shown):
            fn.__name__ = "ws_%s_%s" % (kind, fn.__name__)
            yield fn


for _fn in _ws_toggle_steps():
    step(_fn)


@step
def ws_reset_setup():
    # Sculpt: scramble the layout, then Reset Workspace from the popover (the confirm dialog takes Enter).
    bpy.ops.m3d.workspace(kind='SCULPT')
    for area in window().screen.areas:
        if area.type == 'VIEW_3D':
            area.ui_type = 'OUTLINER'


@step
def ws_reset_open():
    ws_open()


@step
def ws_reset_click():
    ws_row("reset")


@step
def ws_reset_confirm():
    ws_event('RET', 'PRESS')
    ws_event('RET', 'RELEASE')


step(wait_until(lambda: [w.name for w in bpy.data.workspaces if w.name.startswith("Sculpt")] == ["Sculpt"]
                and window().workspace.name == "Sculpt" and any(a.type == 'VIEW_3D' for a in window().screen.areas),
                "Reset Workspace from the Settings popover to finish"))


@step
def ws_reset_check():
    check(len(m3d_workspace.workspace_screens('SCULPT')) == 1, "Settings reset left screens: %s" % [s.name for s in bpy.data.screens])
    check(not tracebacks(), "Python error resetting from the Settings popover")
    bpy.ops.m3d.workspace(kind='MODEL')


# ----------------------------------------------------------------------------------------------------
# Edit the interface (m3d_edit.py): Click to Edit in the Settings popover, shelf drags, a shortcut from a Ctrl+Alt+click,
# panels and user tabs in a dock, and everything back to normal when it is off.

import m3d_edit

WS_ROWS["edit"] = 274   # Modeling's Settings popover: Click to Edit


def e_event(type, value='NOTHING', xy=None, **mods):
    window().event_simulate(type=type, value=value, x=xy[0], y=xy[1], **mods)


def e_shelf_xy(ref, dx=0):
    rec = m3d_edit._geom["shelf"]
    x0, w, _ref = next(c for c in rec["cells"] if c[2] == ref)
    return int(rec["rect"][0] + x0 + w / 2 + dx), int(rec["rect"][1] + rec["rect"][3] / 2)


def e_tab_xy():
    rec = m3d_edit._geom["tabs"]
    return int(rec["rect"][0] + sum(rec["custom"]) / 2), int(rec["rect"][1] + rec["rect"][3] / 2)


def e_shelf_ready(key):
    rec = m3d_edit._geom.get("shelf")
    return rec is not None and rec["key"] == key and rec["ws"] == window().workspace.name and "tabs" in m3d_edit._geom


def e_custom_labels():
    m3d_user.reset_cache()
    return "".join(i["label"] for i in m3d_user.shelf_items('MODEL'))


def e_objects():
    return len(bpy.data.objects)


def e_screenshot(path):
    for area in window().screen.areas:
        area.tag_redraw()
    bpy.ops.screen.screenshot(filepath=path)


@step
def edit_setup():
    bpy.ops.m3d.workspace(kind='MODEL')
    m3d_edit.set_editing(False)
    m3d_user.shelf_items('MODEL').clear()
    m3d_user.shelf_items('MODEL').extend(
        {"idname": "m3d.add_primitive", "props": {"kind": kind}, "icon": icon, "label": label}
        for label, kind, icon in (("A", 'SPHERE', 'MESH_UVSPHERE'), ("B", 'CUBE', 'MESH_CUBE'), ("C", 'CYLINDER', 'MESH_CYLINDER')))
    m3d_user.save()
    bpy.context.window_manager.m3d_shelf = 'POLY'
    GIZMO["edit_objects"] = e_objects()
    check(not m3d_edit.editing(), "edit mode starts off")


@step
def edit_open_popover():
    ws_open()


@step
def edit_toggle_click():
    ws_row("edit")


step(wait_until(lambda: m3d_edit.editing() and m3d_edit._state["running"], "Click to Edit to turn edit mode on"))


@step
def edit_close_popover():
    ws_event('ESC', 'PRESS')
    bpy.context.window_manager.m3d_shelf = 'POLY'
    m3d_edit.refresh_ui()


step(wait_until(lambda: e_shelf_ready('POLY'), "the shelf cells in edit mode"))


@step
def edit_shelf_probe_check():
    check(not tracebacks(), "Python error drawing the shelf in edit mode")
    rec = m3d_edit._geom["shelf"]
    check(len([c for c in rec["cells"] if c[2]]) == 24, "edit-mode shelf has a cell per button (Create High Poly and Auto-Pair are on the Poly shelf): %d" % len(rec["cells"]))


# A click on a shelf button without a drag does nothing while editing (the press and release are taken).
@step
def edit_click_nothing():
    xy = e_shelf_xy(("B", 'POLY', 0))
    e_event('MOUSEMOVE', xy=xy)
    e_event('LEFTMOUSE', 'PRESS', xy)
    e_event('LEFTMOUSE', 'RELEASE', xy)


@step
def edit_click_nothing_check():
    check(e_objects() == GIZMO["edit_objects"], "a click on a shelf button while editing ran it")
    check(m3d_edit._drag["src"] is None, "a click left a drag behind")


# Ctrl+Alt+click a built-in shelf button (Sphere), press Ctrl+Alt+Shift+J: that key adds a sphere.
def _hover_steps(ref, name):
    def hover():
        xy = e_shelf_xy(ref)
        GIZMO["hk_xy"] = xy
        e_event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        e_event('MOUSEMOVE', xy=xy)
        e_event('LEFT_CTRL', 'PRESS', xy, ctrl=True)
        e_event('LEFT_ALT', 'PRESS', xy, ctrl=True, alt=True)
        e_event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]), ctrl=True, alt=True)
        e_event('MOUSEMOVE', xy=xy, ctrl=True, alt=True)

    def click():
        xy = GIZMO["hk_xy"]
        e_event('LEFTMOUSE', 'PRESS', xy, ctrl=True, alt=True)
        e_event('LEFTMOUSE', 'RELEASE', xy, ctrl=True, alt=True)
        e_event('LEFT_ALT', 'RELEASE', xy, ctrl=True)
        e_event('LEFT_CTRL', 'RELEASE', xy)
    hover.__name__, click.__name__ = "edit_%s_hover" % name, "edit_%s_click" % name
    return hover, click


_hover, _click = _hover_steps(("B", 'POLY', 0), "sphere_key")
step(_hover)
step(wait_until(lambda: m3d_edit._hover is not None and m3d_edit._hover["item"]["idname"] == "m3d.add_primitive",
                "the probe to find the button under the cursor"))
step(_click)
step(wait_until(lambda: m3d_edit._capture is not None, "Ctrl+Alt+click to wait for a key"))


@step
def edit_sphere_key_prompt():
    check(e_objects() == GIZMO["edit_objects"], "the Ctrl+Alt+click also ran the button")
    check(m3d_edit._capture["item"]["props"] == {"kind": 'SPHERE'} and m3d_edit._capture["item"]["keymap"] == "Window",
          "capture target: %r" % (m3d_edit._capture["item"],))
    check("Press a key for" in m3d_edit._prompt["text"] and "Esc cancels" in m3d_edit._prompt["text"], "prompt text %r" % m3d_edit._prompt["text"])
    check(not tracebacks(), "Python error waiting for the shortcut key")


@step
def edit_sphere_key_shot():
    e_screenshot("F:/AI/m3d_item3_key.png")


@step
def edit_sphere_key_press():
    xy = GIZMO["hk_xy"]
    e_event('LEFT_CTRL', 'PRESS', xy, ctrl=True)
    e_event('LEFT_ALT', 'PRESS', xy, ctrl=True, alt=True)
    e_event('LEFT_SHIFT', 'PRESS', xy, ctrl=True, alt=True, shift=True)
    e_event('J', 'PRESS', xy, ctrl=True, alt=True, shift=True)
    e_event('J', 'RELEASE', xy, ctrl=True, alt=True, shift=True)
    e_event('LEFT_SHIFT', 'RELEASE', xy, ctrl=True, alt=True)
    e_event('LEFT_ALT', 'RELEASE', xy, ctrl=True)
    e_event('LEFT_CTRL', 'RELEASE', xy)


step(wait_until(lambda: m3d_edit._capture is None, "the shortcut to be assigned"))


@step
def edit_sphere_key_check():
    items = [k for k in bpy.context.window_manager.keyconfigs.user.keymaps["Window"].keymap_items
             if k.idname == "m3d.add_primitive" and k.type == 'J']
    check(len(items) == 1 and items[0].properties.kind == 'SPHERE' and (items[0].ctrl, items[0].alt, items[0].shift) == (1, 1, 1),
          "the shortcut is in the user keymap: %s" % [(k.type, k.properties.kind) for k in items])
    check(e_objects() == GIZMO["edit_objects"], "assigning the key ran the button")
    check(not tracebacks(), "Python error assigning the shortcut")


@step
def edit_sphere_key_use():
    _win, area, region = view3d()
    xy = (region.x + region.width // 2, region.y + region.height // 2)
    e_event('MOUSEMOVE', xy=xy)
    e_event('J', 'PRESS', xy, ctrl=True, alt=True, shift=True)
    e_event('J', 'RELEASE', xy, ctrl=True, alt=True, shift=True)


step(wait_until(lambda: e_objects() == GIZMO["edit_objects"] + 1, "the new shortcut to add a sphere"))


@step
def edit_sphere_key_used():
    GIZMO["edit_objects"] = e_objects()


# A key that is taken asks first (Esc cancels, nothing is assigned).
_hover, _click = _hover_steps(("B", 'POLY', 1), "cube_key")
step(_hover)
step(wait_until(lambda: m3d_edit._hover is not None and m3d_edit._hover["item"]["props"] == {"kind": 'CUBE'}, "the probe to find the Cube button"))
step(_click)
step(wait_until(lambda: m3d_edit._capture is not None, "Ctrl+Alt+click on Cube to wait for a key"))


@step
def edit_conflict_key():
    xy = GIZMO["hk_xy"]
    e_event('F1', 'PRESS', xy)
    e_event('F1', 'RELEASE', xy)


step(wait_until(lambda: m3d_edit._capture is not None and m3d_edit._capture["state"] == 'CONFIRM', "the conflict question"))


@step
def edit_conflict_check():
    check("Switch Workspace" in m3d_edit._prompt["text"] and "F1" in m3d_edit._prompt["text"], "conflict prompt: %r" % m3d_edit._prompt["text"])
    check(window().workspace.name == "Modeling", "F1 switched the workspace while the shortcut was being assigned")


@step
def edit_conflict_cancel():
    xy = GIZMO["hk_xy"]
    e_event('ESC', 'PRESS', xy)
    e_event('ESC', 'RELEASE', xy)


step(wait_until(lambda: m3d_edit._capture is None, "Esc to cancel the shortcut"))


@step
def edit_conflict_cancelled():
    cube = [k for k in bpy.context.window_manager.keyconfigs.user.keymaps["Window"].keymap_items
            if k.idname == "m3d.add_primitive" and k.properties.kind == 'CUBE' and k.type == 'F1']
    check(not cube, "a cancelled shortcut was assigned")
    km = bpy.context.window_manager.keyconfigs.user.keymaps["Window"]
    for k in [k for k in km.keymap_items if k.idname == "m3d.add_primitive" and k.type == 'J']:
        km.keymap_items.remove(k)   # (the user keymap is the real one: leave it as it was)
    check(not tracebacks(), "Python error in the shortcut conflict")


# Drag a built-in button (Cube) onto the Custom tab: it is copied to this workspace's Custom shelf.
@step
def edit_copy_press():
    xy = e_shelf_xy(("B", 'POLY', 1))
    e_event('MOUSEMOVE', xy=xy)
    e_event('LEFTMOUSE', 'PRESS', xy)


step(wait_until(lambda: m3d_edit._drag["src"] == ("B", 'POLY', 1), "the press on a shelf button to start a drag"))


@step
def edit_copy_move():
    x, y = e_shelf_xy(("B", 'POLY', 1))
    tx, ty = e_tab_xy()
    for t in (0.25, 0.5, 0.75, 1.0):
        e_event('MOUSEMOVE', xy=(int(x + (tx - x) * t), int(y + (ty - y) * t)))


step(wait_until(lambda: m3d_edit._drag["target"] == "tab", "the drag to find the Custom tab"))


@step
def edit_copy_release():
    e_event('LEFTMOUSE', 'RELEASE', e_tab_xy())


step(wait_until(lambda: m3d_edit._drag["src"] is None, "the drop"))


@step
def edit_copy_check():
    m3d_user.reset_cache()
    items = m3d_user.shelf_items('MODEL')
    check(len(items) == 4 and items[-1]["idname"] == "m3d.add_primitive" and items[-1]["props"] == {"kind": 'CUBE'},
          "dragging a button onto the Custom tab did not copy it: %s" % [i["label"] for i in items])
    check(e_objects() == GIZMO["edit_objects"], "the drag ran the button")
    check(not tracebacks(), "Python error copying a shelf button")
    bpy.context.window_manager.m3d_shelf = 'CUSTOM'
    m3d_edit.refresh_ui()


# Custom shelf: drag the first button (A) to the end, then drag one off the shelf.
step(wait_until(lambda: e_shelf_ready('CUSTOM') and len([c for c in m3d_edit._geom["shelf"]["cells"] if c[2]]) == 4, "the Custom shelf cells"))


@step
def edit_reorder_press():
    GIZMO["edit_labels"] = e_custom_labels()
    xy = e_shelf_xy(("C", 0))
    e_event('MOUSEMOVE', xy=xy)
    e_event('LEFTMOUSE', 'PRESS', xy)


step(wait_until(lambda: m3d_edit._drag["src"] == ("C", 0), "the press on a Custom button to start a drag"))


@step
def edit_reorder_move():
    x, y = e_shelf_xy(("C", 0))
    tx, ty = e_shelf_xy(("C", 3), dx=12)
    for t in (0.25, 0.5, 0.75, 1.0):
        e_event('MOUSEMOVE', xy=(int(x + (tx - x) * t), ty))


step(wait_until(lambda: m3d_edit._drag["target"] == ("slot", 4), "the drag to find the end slot"))


@step
def edit_reorder_release():
    e_event('LEFTMOUSE', 'RELEASE', e_shelf_xy(("C", 3), dx=12))


step(wait_until(lambda: m3d_edit._drag["src"] is None, "the drop"))


@step
def edit_reorder_check():
    want = GIZMO["edit_labels"][1:] + GIZMO["edit_labels"][0]
    check(e_custom_labels() == want, "dragging the first Custom button to the end gave %s, not %s" % (e_custom_labels(), want))
    check(e_objects() == GIZMO["edit_objects"] and not tracebacks(), "reorder ran a button or raised")


@step
def edit_remove_press():
    GIZMO["edit_labels"] = e_custom_labels()
    xy = e_shelf_xy(("C", 1))
    e_event('MOUSEMOVE', xy=xy)
    e_event('LEFTMOUSE', 'PRESS', xy)


step(wait_until(lambda: m3d_edit._drag["src"] == ("C", 1), "the press on a Custom button to start a remove drag"))


@step
def edit_remove_move():
    _win, _area, region = view3d()
    x, y = e_shelf_xy(("C", 1))
    tx, ty = region.x + region.width // 2, region.y + region.height // 2
    for t in (0.3, 0.6, 1.0):
        e_event('MOUSEMOVE', xy=(int(x + (tx - x) * t), int(y + (ty - y) * t)))


step(wait_until(lambda: m3d_edit._drag["target"] == "out", "the drag to leave the shelf"))


@step
def edit_remove_release():
    _win, _area, region = view3d()
    e_event('LEFTMOUSE', 'RELEASE', (region.x + region.width // 2, region.y + region.height // 2))


step(wait_until(lambda: m3d_edit._drag["src"] is None, "the drop off the shelf"))


@step
def edit_remove_check():
    labels = GIZMO["edit_labels"]
    check(e_custom_labels() == labels[0] + labels[2:], "dragging a Custom button off the shelf gave %s from %s" % (e_custom_labels(), labels))
    check(e_objects() == GIZMO["edit_objects"] and not tracebacks(), "remove ran a button or raised")


@step
def edit_escape_press():
    GIZMO["edit_labels"] = e_custom_labels()
    xy = e_shelf_xy(("C", 0))
    e_event('MOUSEMOVE', xy=xy)
    e_event('LEFTMOUSE', 'PRESS', xy)


step(wait_until(lambda: m3d_edit._drag["src"] == ("C", 0), "the press for the Esc drag"))


@step
def edit_escape_run():
    _win, _area, region = view3d()
    xy = (region.x + region.width // 2, region.y + region.height // 2)
    e_event('MOUSEMOVE', xy=xy)
    e_event('ESC', 'PRESS', xy)
    e_event('LEFTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: m3d_edit._drag["src"] is None, "Esc to cancel the drag"))


@step
def edit_escape_check():
    check(e_custom_labels() == GIZMO["edit_labels"], "Esc during a drag changed the shelf: %s" % e_custom_labels())
    bpy.context.window_manager.m3d_shelf = 'POLY'


# Panels: a user tab, a panel moved into it, another hidden; the dock shows them (and the controls while editing).
def e_dock():
    return next(a for a in window().screen.areas if a.type == 'PROPERTIES' and a.x > window().width // 2)


def e_dock_override():
    area = e_dock()
    return dict(window=window(), area=area, region=next(r for r in area.regions if r.type == 'WINDOW'),
                space_data=area.spaces.active, workspace=window().workspace)


def e_poll(cls):
    with bpy.context.temp_override(**e_dock_override()):
        return cls.poll(bpy.context)


@step
def edit_panels_setup():
    dock = e_dock()
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    window().workspace.m3d_page_right = "modeling_toolkit"
    GIZMO["edit_mesh_panel"] = m3d_mode.PROPERTIES_PT_m3d_mtk_mesh
    check(e_poll(GIZMO["edit_mesh_panel"]), "the Mesh panel shows on the toolkit page")
    with bpy.context.temp_override(**e_dock_override()):
        bpy.ops.m3d.user_tab_add('EXEC_DEFAULT', name="Mine")
    check([t["label"] for t in m3d_user.user_tabs('MODEL')] == ["Mine"], "user tab created")
    check(window().workspace.m3d_page_right == "user_1", "the new tab is shown")


@step
def edit_panels_empty_hint():
    check(e_poll(m3d_edit.PROPERTIES_PT_m3d_user_tab_hint), "an empty user tab shows its hint while editing")
    check(not e_poll(GIZMO["edit_mesh_panel"]), "the Mesh panel is not on the new tab yet")
    with bpy.context.temp_override(**e_dock_override()):
        bpy.ops.m3d.panel_move(panel="PROPERTIES_PT_m3d_mtk_mesh", tab="user_1")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def edit_panels_moved():
    check(e_poll(GIZMO["edit_mesh_panel"]), "the moved panel shows on the user tab")
    check(not e_poll(m3d_edit.PROPERTIES_PT_m3d_user_tab_hint), "the hint is gone once the tab has a panel")
    check(not e_poll(m3d_mode.PROPERTIES_PT_m3d_mtk_selection), "other panels stay on their page")
    check(not tracebacks(), "Python error drawing a dock with a user tab")
    e_dock().spaces.active.context = 'MODELING_TOOLKIT'
    window().workspace.m3d_page_right = "modeling_toolkit"


@step
def edit_panels_home_page():
    check(not e_poll(GIZMO["edit_mesh_panel"]) and e_poll(m3d_mode.PROPERTIES_PT_m3d_mtk_selection), "the toolkit page lost the panel")
    with bpy.context.temp_override(**e_dock_override()):
        bpy.ops.m3d.panel_hide(panel="PROPERTIES_PT_m3d_mtk_selection")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def edit_panels_hidden():
    check(e_poll(m3d_mode.PROPERTIES_PT_m3d_mtk_selection), "a hidden panel is listed while editing")
    window().workspace.m3d_page_right = "modeling_toolkit"
    for a in window().screen.areas:
        a.tag_redraw()


@step
def edit_shot():
    e_screenshot("F:/AI/m3d_item3_edit.png")


@step
def edit_panels_check_draw():
    check(not tracebacks(), "Python error drawing the dock panels and tabs while editing")


# Edit mode off from the popover: panels, shelf and clicks behave as before.
@step
def edit_off_open():
    ws_open()


@step
def edit_off_click():
    WS_ROWS["edit"] += 25 * len(m3d_user.user_tabs('MODEL'))   # (a user tab is one more row in the popover)
    ws_row("edit")
    WS_ROWS["edit"] = 274


step(wait_until(lambda: not m3d_edit.editing() and not m3d_edit._state["running"], "Editing to turn edit mode off"))


@step
def edit_off_close():
    ws_event('ESC', 'PRESS')
    bpy.context.window_manager.m3d_shelf = 'POLY'
    window().workspace.m3d_page_right = "modeling_toolkit"
    m3d_edit.refresh_ui()


@step
def edit_off_hidden():
    check(not e_poll(m3d_mode.PROPERTIES_PT_m3d_mtk_selection), "a hidden panel stays hidden once edit mode is off")
    check(not e_poll(m3d_edit.PROPERTIES_PT_m3d_user_tab_hint), "no hint outside edit mode")
    check(not tracebacks(), "Python error leaving edit mode")
    GIZMO["edit_objects"] = e_objects()
    xy = e_shelf_xy(("B", 'POLY', 0))
    GIZMO["hk_xy"] = xy
    e_event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    e_event('MOUSEMOVE', xy=xy)


@step
def edit_off_click_button():
    xy = GIZMO["hk_xy"]
    e_event('LEFTMOUSE', 'PRESS', xy)
    e_event('LEFTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: e_objects() == GIZMO["edit_objects"] + 1, "a shelf click to add a sphere again (edit mode is off)"))


@step
def edit_off_ctrl_alt():
    xy = GIZMO["hk_xy"]
    m3d_edit._hover = None
    e_event('LEFT_CTRL', 'PRESS', xy, ctrl=True)
    e_event('LEFT_ALT', 'PRESS', xy, ctrl=True, alt=True)
    e_event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]), ctrl=True, alt=True)
    e_event('LEFT_ALT', 'RELEASE', xy, ctrl=True)
    e_event('LEFT_CTRL', 'RELEASE', xy)


@step
def edit_cleanup():
    check(m3d_edit._hover is None and m3d_edit._capture is None, "Ctrl+Alt probes the button outside edit mode")
    m3d_user.reset_dock('MODEL')
    m3d_user.shelf_items('MODEL').clear()
    m3d_user.save()
    window().workspace.m3d_page_right = ""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    check(not tracebacks(), "Python error in the edit mode tests")


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


def topbar_px():
    """Pixels between the window's top and the editors under the top bar (the top bar is a global area, so it is
    not in screen.areas)."""
    return window().height - max(a.y + a.height for a in window().screen.areas)


def viewport_px():
    return max(a.height for a in window().screen.areas if a.type == 'VIEW_3D')


@step
def topbar_model_record():
    # Modeling shows all four top bar rows (the reference for the Show Shelf checks).
    check(window().workspace.name == "Modeling" and window().workspace.m3d_show_shelf, "Show Shelf test starts in Modeling")
    GIZMO["topbar_model"], GIZMO["viewport_model"] = topbar_px(), viewport_px()
    check(GIZMO["topbar_model"] > 0, "Modeling top bar height %s" % GIZMO["topbar_model"])


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
    # Sculpt has no shelf: the top bar is the menu bar and the Status Line, the viewport got the rest.
    ratio = topbar_px() / GIZMO["topbar_model"]
    check(not window().workspace.m3d_show_shelf and 0.38 < ratio < 0.52,
          "Sculpt top bar is two rows: %s px of %s px in Modeling" % (topbar_px(), GIZMO["topbar_model"]))
    print("M3D topbar px: Modeling %s, Sculpt %s; 3D view %s -> %s" % (
        GIZMO["topbar_model"], topbar_px(), GIZMO["viewport_model"], viewport_px()))
    check(viewport_px() > GIZMO["viewport_model"], "Sculpt viewport (%s) is taller than Modeling's (%s)" % (
        viewport_px(), GIZMO["viewport_model"]))
    # The brush tray: a thumbnail per brush (a real icon id in a window), the Custom panel, the Show Shelf toggle.
    icons = m3d_sculpt.brush_icons(m3d_sculpt.BRUSH_ASSET, [n for _l, n in m3d_sculpt.BRUSHES])
    check(len(icons) == len(m3d_sculpt.BRUSHES) and all(i > 0 for i in icons.values()), "brush tile icons %s" % icons)
    with bpy.context.temp_override(window=window(), area=tray, region=next(r for r in tray.regions if r.type == 'WINDOW')):
        check(m3d_sculpt.PROPERTIES_PT_m3d_sc_custom.poll(bpy.context), "Custom panel is in the Sculpt tray")


def nav_width(area):
    """Width of a Properties editor's navigation bar (its column of stock tabs): 1 or less when hidden."""
    return next((r.width for r in area.regions if r.type == 'NAVIGATION_BAR'), 0)


@step
def sculpt_layout_check():
    # The Sculpt layout: no tool settings row over the viewport, no Outliner (the dock is the whole right edge), no
    # navigation bar beside the pages; All Settings brings the navigation bar back.
    view = next(a for a in window().screen.areas if a.type == 'VIEW_3D')
    check(not view.spaces.active.show_region_tool_header, "Sculpt has no tool settings row")
    check(not any(a.type == 'OUTLINER' for a in window().screen.areas), "Sculpt has no Outliner")
    tray, dock = sculpt_dock()
    check(dock.height > 0.9 * view.height, "the dock is the height of the viewport (%s, %s)" % (dock.height, view.height))
    check(nav_width(tray) <= 1 and nav_width(dock) <= 1, "no navigation bar beside the Sculpt pages (%s, %s)" % (nav_width(tray), nav_width(dock)))
    toolbar = next(r for r in view.regions if r.type == 'TOOLS')
    check(toolbar.width > 10, "the toolbar still shows")
    dock.spaces.active.context = 'OBJECT'   # What the All Settings tab shows.
    dock.tag_redraw()


step(wait_until(lambda: nav_width(sculpt_dock()[1]) > 1, "the navigation bar with All Settings"))


@step
def sculpt_nav_back():
    check(not tracebacks(), "Python error with All Settings in the Sculpt dock")
    dock = sculpt_dock()[1]
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    dock.tag_redraw()


step(wait_until(lambda: nav_width(sculpt_dock()[1]) <= 1, "the navigation bar to go again on a page"))


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
def sculpt_tile_click():
    # A tile picks its brush (the tile is the operator's button; the click itself is in the screenshot check).
    press_ok("m3d.brush_pick", identifier=m3d_sculpt.BRUSH_ASSET + "Snake Hook")
    check(m3d_sculpt.active_brush_id(bpy.context) == m3d_sculpt.BRUSH_ASSET + "Snake Hook", "brush tile did not pick Snake Hook")
    check(not tracebacks(), "Python error drawing the brush tiles")


@step
def shelf_f1():
    # F1: back to Modeling, with its four rows.
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('F1', 'PRESS', GIZMO["center"])
    event('F1', 'RELEASE', GIZMO["center"])


step(wait_until(lambda: window().workspace.name == "Modeling" and topbar_px() > 0.9 * GIZMO["topbar_model"],
                "F1 to bring the four top bar rows back"))


@step
def shelf_f1_check():
    check(abs(topbar_px() - GIZMO["topbar_model"]) <= 2, "F1: top bar is four rows again (%s, was %s)" % (
        topbar_px(), GIZMO["topbar_model"]))
    check(viewport_px() == GIZMO["viewport_model"], "F1: viewport back to %s (is %s)" % (GIZMO["viewport_model"], viewport_px()))
    check(not tracebacks(), "Python error switching back to Modeling")
    window().workspace.m3d_show_shelf = False   # What the Show Shelf checkbox in Workspace Settings sets.


step(wait_until(lambda: topbar_px() < 0.6 * GIZMO["topbar_model"], "Show Shelf off to give the rows back"))


@step
def shelf_off_check():
    ratio = topbar_px() / GIZMO["topbar_model"]
    check(0.38 < ratio < 0.52, "Modeling with Show Shelf off has two rows (%s of %s)" % (topbar_px(), GIZMO["topbar_model"]))
    check(viewport_px() > GIZMO["viewport_model"], "Modeling viewport grows with Show Shelf off")
    check(not tracebacks(), "Python error with the shelf hidden")
    window().workspace.m3d_show_shelf = True


step(wait_until(lambda: topbar_px() > 0.9 * GIZMO["topbar_model"], "Show Shelf on to bring the rows back"))


@step
def shelf_on_check():
    check(abs(topbar_px() - GIZMO["topbar_model"]) <= 2 and viewport_px() == GIZMO["viewport_model"],
          "Show Shelf back on: top bar %s viewport %s" % (topbar_px(), viewport_px()))
    check(not tracebacks(), "Python error showing the shelf again")
    bpy.ops.m3d.workspace(kind='SCULPT')


step(wait_until(lambda: window().workspace.name == "Sculpt" and topbar_px() < 0.6 * GIZMO["topbar_model"],
                "Sculpt to come back for the cleanup"))


@step
def sculpt_done():
    sculpt_ws = window().workspace
    sculpt_ws.m3d_page_left = sculpt_ws.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')


# ----------------------------------------------------------------------------------------------------
# Phase 1b: the Sculpt Ctrl gestures (mask / hide), Add / Subtract, Lazy Mouse, stroke and alpha tiles, matcaps,
# with real mouse and key events on a fine sphere.

import numpy as np


def sg_context():
    win, area, region = view3d()
    return area.spaces.active.region_3d, region


def sg_project(co):
    """Window position (x, y) of a world point."""
    rv3d, region = sg_context()
    p = location_3d_to_region_2d(region, rv3d, Vector(co))
    return (int(region.x + p.x), int(region.y + p.y))


def sg_verts():
    """Arrays over the vertices of the active mesh: window positions, facing (1 toward the camera, -1 away), the
    sculpt mask (0 when there is none), hidden."""
    ob = bpy.context.active_object
    me = ob.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    nor = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("normal", nor)
    co, nor = co.reshape(n, 3), nor.reshape(n, 3)
    rv3d, _region = sg_context()
    eye = np.array(rv3d.view_matrix.inverted().translation)
    to_eye = eye - co
    to_eye /= np.linalg.norm(to_eye, axis=1)[:, None]
    mask = np.zeros(n, np.float32)
    attr = me.attributes.get(".sculpt_mask")
    if attr is not None:
        attr.data.foreach_get("value", mask)
    hidden = np.zeros(n, bool)
    attr = me.attributes.get(".hide_vert")
    if attr is not None:
        attr.data.foreach_get("value", hidden)
    return {"co": co, "px": np.array([sg_project(c) for c in co]), "facing": (nor * to_eye).sum(axis=1),
            "mask": mask, "hidden": hidden}


def sg_path_distance(px, a, b):
    """Distance in pixels from each of the points `px` to the segment a-b."""
    a, b = np.array(a, float), np.array(b, float)
    t = np.clip(((px - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
    return np.linalg.norm(px - (a + t[:, None] * (b - a)), axis=1)


SG_KEYS = (('LEFT_CTRL', 'ctrl'), ('LEFT_SHIFT', 'shift'), ('LEFT_ALT', 'alt'))


def sg_press(xy, **mods):
    """Move there, hold the modifier keys (real key events: the keymap reads the modifier state) and press the left button."""
    xy = pt(xy)
    event('MOUSEMOVE', xy=xy, **mods)
    held = {}
    for key, name in SG_KEYS:
        if mods.get(name):
            held[name] = True
            event(key, 'PRESS', xy, **held)
    event('LEFTMOUSE', 'PRESS', xy, **mods)


def sg_move(a, b, steps=10, **mods):
    for i in range(1, steps + 1):
        event('MOUSEMOVE', xy=pt((a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)), **mods)


def sg_release(xy, **mods):
    xy = pt(xy)
    event('LEFTMOUSE', 'RELEASE', xy, **mods)
    held = {name: True for _key, name in SG_KEYS if mods.get(name)}
    for key, name in reversed(SG_KEYS):
        if name in held:
            del held[name]
            event(key, 'RELEASE', xy, **held)


def sg_click(xy, **mods):
    sg_press(xy, **mods)
    sg_release(xy, **mods)


def sg_geometry():
    """Window positions that matter: the sphere's centre, its radius in pixels, a point of empty space on the left of
    the viewport, and the right edge of the region."""
    rv3d, region = sg_context()
    center = sg_project((0, 0, 0))
    right = rv3d.view_rotation @ Vector((1, 0, 0))
    radius = abs(sg_project(right)[0] - center[0])
    return {"c": center, "r": radius, "empty": (region.x + 50, region.y + region.height // 2)}


def pt(xy):
    return (int(round(xy[0])), int(round(xy[1])))


def sg_wait(cond, what):
    return wait_until(cond, what)


SG = GIZMO.setdefault("sg", {})


@step
def sg_setup():
    # The alpha library goes to a temporary folder, a clean scene with one fine sphere, then F2.
    import tempfile
    SG["alphas"] = tempfile.mkdtemp(prefix="m3d_alphas_")
    m3d_sculpt.alpha_dir = lambda create=False: SG["alphas"]
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=64, ring_count=32)
        bpy.context.active_object.name = "Fine"
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])
    event('F2', 'PRESS', GIZMO["center"])
    event('F2', 'RELEASE', GIZMO["center"])


step(wait_until(lambda: window().workspace.name == "Sculpt" and bpy.context.mode == 'SCULPT', "F2 to enter Sculpt Mode (gestures)"))


@step
def sg_prepare():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.view3d.view_all(center=True)
    area.spaces.active.region_3d.view_distance *= 2.2   # room for empty space around the sphere
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Draw"))
    brush = bpy.context.tool_settings.sculpt.brush
    brush.size, brush.strength, brush.direction = 60, 1.0, 'ADD'
    ups = bpy.context.tool_settings.sculpt.unified_paint_settings
    ups.use_unified_size = ups.use_unified_strength = False
    SG["brush_size"] = brush.size
    for a in window().screen.areas:
        a.tag_redraw()
    event('MOUSEMOVE', xy=GIZMO["center"])


@step
def sg_ready():
    SG.update(sg_geometry())
    SG["base"] = sg_verts()
    check(60 < SG["r"] < 600, "sphere radius on screen %s" % SG["r"])
    check(SG["base"]["mask"].max() == 0 and not SG["base"]["hidden"].any(), "a new sphere has no mask and nothing hidden")
    SG["path"] = ((SG["c"][0] - 0.5 * SG["r"], SG["c"][1] + 0.1 * SG["r"]), (SG["c"][0] + 0.5 * SG["r"], SG["c"][1] + 0.1 * SG["r"]))
    # The tool must be a brush for the Sculpt keymap's strokes to apply.
    check(active_tool_id() == "builtin.brush", "the brush tool is active (%s)" % active_tool_id())


# --- Ctrl+drag on the mesh paints mask; the geometry stays as it was

@step
def sg_mask_drag():
    a, b = SG["path"]
    sg_press(a, ctrl=True)
    sg_move(a, b, ctrl=True)


@step
def sg_mask_release():
    sg_release(SG["path"][1], ctrl=True)


step(wait_until(lambda: sg_verts()["mask"].max() > 0, "Ctrl+drag on the mesh to paint mask"))


@step
def sg_mask_check():
    v = sg_verts()
    a, b = SG["path"]
    dist = sg_path_distance(v["px"], a, b)
    near = (dist < 0.2 * SG["brush_size"]) & (v["facing"] > 0.3)
    far = dist > 2.2 * SG["brush_size"]
    check(near.sum() > 3 and v["mask"][near].mean() > 0.5, "Ctrl+drag masks along the stroke (%d verts, mean %.2f)" % (
        near.sum(), v["mask"][near].mean() if near.any() else -1))
    check(v["mask"][far].max() < 0.01, "Ctrl+drag leaves the far side unmasked (max %.2f)" % v["mask"][far].max())
    check(np.abs(v["co"] - SG["base"]["co"]).max() < 1e-4, "Ctrl+drag does not move the geometry")
    check(not tracebacks(), "Python error in the Ctrl+drag gesture")
    SG["masked"] = v["mask"].sum()
    check(not any("sculpt_ctrl" in o.bl_idname.lower() for o in window().modal_operators), "the gesture operator has finished")


# --- Ctrl+Alt+drag along the same path erases it

@step
def sg_unmask_drag():
    a, b = SG["path"]
    sg_press(a, ctrl=True, alt=True)
    sg_move(a, b, ctrl=True, alt=True)


@step
def sg_unmask_release():
    sg_release(SG["path"][1], ctrl=True, alt=True)


step(wait_until(lambda: sg_verts()["mask"].sum() < 0.5 * SG["masked"], "Ctrl+Alt+drag to erase the mask"))


@step
def sg_unmask_check():
    v = sg_verts()
    dist = sg_path_distance(v["px"], *SG["path"])
    near = (dist < 0.2 * SG["brush_size"]) & (v["facing"] > 0.3)
    check(v["mask"][near].mean() < 0.15, "Ctrl+Alt+drag erases the mask along the stroke (mean %.2f)" % v["mask"][near].mean())
    check(not tracebacks(), "Python error in the Ctrl+Alt+drag gesture")


# --- Ctrl+click on empty space inverts the mask

@step
def sg_invert_setup():
    a, b = SG["path"]
    sg_press(a, ctrl=True)
    sg_move(a, b, ctrl=True)


@step
def sg_invert_setup2():
    sg_release(SG["path"][1], ctrl=True)


step(wait_until(lambda: sg_verts()["mask"].max() > 0, "the mask to invert"))


@step
def sg_invert_click():
    SG["before"] = sg_verts()["mask"].copy()
    sg_click(SG["empty"], ctrl=True)


step(wait_until(lambda: abs(sg_verts()["mask"] - (1 - SG["before"])).max() < 1e-3, "Ctrl+click on empty space to invert"))


@step
def sg_invert_check():
    v = sg_verts()
    check(abs(v["mask"] - (1 - SG["before"])).max() < 1e-3, "Ctrl+click on empty space inverted the mask")
    check(not tracebacks(), "Python error in the Ctrl+click gesture")
    press_ok("paint.mask_flood_fill", mode='VALUE', value=0.0)


# --- Ctrl+drag on empty space clears the mask (a click there inverts it)

def sg_box_mask():
    """Mask the right half of the sphere with the box gesture (a mask to clear, or to smooth)."""
    c, r = SG["c"], SG["r"]
    SG["box"] = ((c[0] + 1.35 * r, c[1] + 1.35 * r), (c[0], c[1] - 1.35 * r))
    win, area, region = view3d()
    (x0, y0), (x1, y1) = SG["box"]
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.paint.mask_box_gesture(xmin=int(min(x0, x1) - region.x), xmax=int(max(x0, x1) - region.x),
                                       ymin=int(min(y0, y1) - region.y), ymax=int(max(y0, y1) - region.y),
                                       mode='VALUE', value=1.0, use_front_faces_only=True)


@step
def sg_clear_setup():
    sg_box_mask()
    check(sg_verts()["mask"].max() > 0, "(a box mask to clear)")


@step
def sg_clear_drag():
    a = SG["empty"]
    SG["clear"] = (a, (a[0] + 60, a[1] - 40))
    sg_press(a, ctrl=True)
    sg_move(*SG["clear"], ctrl=True)


@step
def sg_clear_release():
    sg_release(SG["clear"][1], ctrl=True)


step(wait_until(lambda: sg_verts()["mask"].max() == 0, "Ctrl+drag on empty space to clear the mask"))


@step
def sg_clear_check():
    check(not tracebacks(), "Python error in the clear mask gesture")


# --- Ctrl+click on the mesh smooths the mask, Ctrl+Alt+click sharpens it

@step
def sg_smooth_setup():
    sg_box_mask()


step(wait_until(lambda: sg_verts()["mask"].max() > 0, "the box mask for the smooth test"))


@step
def sg_smooth_click():
    m = sg_verts()["mask"]
    SG["hard"] = ((m > 0.02) & (m < 0.98)).sum()
    SG["click"] = (int(SG["c"][0] + 0.1 * SG["r"]), int(SG["c"][1]))
    sg_click(SG["click"], ctrl=True)


step(wait_until(lambda: ((sg_verts()["mask"] > 0.02) & (sg_verts()["mask"] < 0.98)).sum() > SG["hard"],
                "Ctrl+click on the mesh to smooth the mask"))


@step
def sg_sharpen_click():
    SG["soft"] = sg_verts()["mask"].copy()
    sg_click(SG["click"], ctrl=True, alt=True)


step(wait_until(lambda: np.abs(sg_verts()["mask"] - SG["soft"]).max() > 1e-3, "Ctrl+Alt+click on the mesh to sharpen the mask"))


@step
def sg_filter_check():
    check(not tracebacks(), "Python error in the Ctrl+click gestures on the mesh")
    press_ok("paint.mask_flood_fill", mode='VALUE', value=0.0)


# --- Ctrl+Shift: hide outside / inside a rectangle, show all, isolate a face set

@step
def sg_hide_drag():
    sg_press(SG["box"][0], ctrl=True, shift=True)
    sg_move(*SG["box"], ctrl=True, shift=True)


@step
def sg_hide_release():
    sg_release(SG["box"][1], ctrl=True, shift=True)


step(wait_until(lambda: sg_verts()["hidden"].any(), "Ctrl+Shift+drag to hide outside the rectangle"))


@step
def sg_hide_check():
    v = sg_verts()
    cx = SG["c"][0]
    inside = v["px"][:, 0] > cx + 12
    outside = v["px"][:, 0] < cx - 12
    check(v["hidden"][outside].all(), "Ctrl+Shift+drag hides everything outside the rectangle")
    check(not v["hidden"][inside].any(), "Ctrl+Shift+drag keeps the inside (%d hidden)" % v["hidden"][inside].sum())
    check(not tracebacks(), "Python error in the Ctrl+Shift+drag gesture")


@step
def sg_show_click():
    sg_click(SG["empty"], ctrl=True, shift=True)


step(wait_until(lambda: not sg_verts()["hidden"].any(), "Ctrl+Shift+click on empty space to show all"))


@step
def sg_hide_inside_drag():
    sg_press(SG["box"][0], ctrl=True, shift=True, alt=True)
    sg_move(*SG["box"], ctrl=True, shift=True, alt=True)


@step
def sg_hide_inside_release():
    sg_release(SG["box"][1], ctrl=True, shift=True, alt=True)


step(wait_until(lambda: sg_verts()["hidden"].any(), "Ctrl+Shift+Alt+drag to hide inside the rectangle"))


@step
def sg_hide_inside_check():
    v = sg_verts()
    cx = SG["c"][0]
    inside = v["px"][:, 0] > cx + 12
    outside = v["px"][:, 0] < cx - 12
    check(v["hidden"][inside].all() and not v["hidden"][outside].any(), "Ctrl+Shift+Alt+drag hides inside the rectangle only")
    sg_click(SG["empty"], ctrl=True, shift=True)


step(wait_until(lambda: not sg_verts()["hidden"].any(), "show all after the inside hide"))


@step
def sg_faceset_setup():
    # Two face sets: the right half (masked by a box) and the rest.
    sg_box_mask()


step(wait_until(lambda: sg_verts()["mask"].max() > 0, "the mask for the face sets"))


@step
def sg_faceset_make():
    press_ok("sculpt.face_sets_create", mode='MASKED')
    press_ok("paint.mask_flood_fill", mode='VALUE', value=0.0)
    SG["click"] = (int(SG["c"][0] + 0.3 * SG["r"]), int(SG["c"][1]))


@step
def sg_isolate_click():
    check(bpy.context.active_object.data.attributes.get(".sculpt_face_set") is not None, "face sets exist")
    sg_click(SG["click"], ctrl=True, shift=True)


step(wait_until(lambda: sg_verts()["hidden"].any(), "Ctrl+Shift+click on the mesh to isolate its face set"))


@step
def sg_isolate_check():
    me = bpy.context.active_object.data
    fs = np.zeros(len(me.polygons), np.int32)
    me.attributes[".sculpt_face_set"].data.foreach_get("value", fs)
    hide = np.zeros(len(me.polygons), bool)
    attr = me.attributes.get(".hide_poly")
    if attr is not None:
        attr.data.foreach_get("value", hide)
    visible = fs[~hide]
    check(hide.any() and len(set(visible)) == 1, "Ctrl+Shift+click on the mesh shows only its face set (sets visible: %s)" % sorted(set(visible)))
    check(not tracebacks(), "Python error isolating a face set")
    sg_click(SG["empty"], ctrl=True, shift=True)


step(wait_until(lambda: not sg_verts()["hidden"].any(), "show all after the isolate"))


# --- A plain drag still sculpts, Shift+drag smooths, Alt+drag still orbits

@step
def sg_plain_drag():
    SG["before"] = sg_verts()["co"].copy()
    a, b = SG["path"]
    sg_press(a)
    sg_move(a, b)


@step
def sg_plain_release():
    sg_release(SG["path"][1])


step(wait_until(lambda: np.abs(sg_verts()["co"] - SG["before"]).max() > 1e-3, "a plain drag to sculpt"))


@step
def sg_plain_check():
    v = sg_verts()
    moved = np.linalg.norm(v["co"] - SG["before"], axis=1)
    check(moved.max() > 0.01, "a plain drag sculpts (moved %.3f)" % moved.max())
    check(np.linalg.norm(v["co"], axis=1).max() > np.linalg.norm(SG["before"], axis=1).max() + 0.005,
          "Add moves the surface outward")
    check(v["mask"].max() == 0, "a plain drag does not mask")
    SG["bump"] = np.linalg.norm(v["co"], axis=1).max()
    SG["smooth_from"] = v["co"].copy()


@step
def sg_shift_drag():
    a, b = SG["path"]
    sg_press(a, shift=True)
    sg_move(a, b, shift=True)
    sg_move(b, a, shift=True)
    sg_move(a, b, shift=True)


@step
def sg_shift_release():
    sg_release(SG["path"][1], shift=True)


step(wait_until(lambda: np.linalg.norm(sg_verts()["co"], axis=1).max() < SG["bump"] - 1e-3, "Shift+drag to smooth the bump"))


@step
def sg_shift_check():
    check(np.linalg.norm(sg_verts()["co"], axis=1).max() < SG["bump"], "Shift+drag smooths (the bump got lower)")
    check(not tracebacks(), "Python error in the plain / Shift strokes")


@step
def sg_orbit():
    rv3d, _region = sg_context()
    SG["rot"] = rv3d.view_rotation.copy()
    SG["before"] = sg_verts()["co"].copy()
    a = SG["empty"]
    b = (a[0] + 80, a[1] + 40)
    SG["orbit"] = (a, b)
    sg_press(a, alt=True)
    sg_move(a, b, alt=True)


@step
def sg_orbit_release():
    sg_release(SG["orbit"][1], alt=True)


step(wait_until(lambda: sg_context()[0].view_rotation != SG["rot"], "Alt+drag to orbit (Maya navigation)"))


@step
def sg_orbit_check():
    check(np.abs(sg_verts()["co"] - SG["before"]).max() < 1e-4, "Alt+drag orbits without sculpting")
    rv3d, _region = sg_context()
    rv3d.view_rotation = SG["rot"]
    SG["before"] = sg_verts()["co"].copy()
    SG["lowest"] = np.linalg.norm(SG["before"], axis=1)


# --- N switches Add / Subtract; a Subtract stroke goes inward

@step
def sg_direction_key():
    event('MOUSEMOVE', xy=SG["c"])
    event('N', 'PRESS', SG["c"])
    event('N', 'RELEASE', SG["c"])


step(wait_until(lambda: bpy.context.tool_settings.sculpt.brush.direction == 'SUBTRACT', "N to switch the brush to Subtract"))


@step
def sg_subtract_drag():
    a, b = SG["path"]
    sg_press(a)
    sg_move(a, b)


@step
def sg_subtract_release():
    sg_release(SG["path"][1])


step(wait_until(lambda: np.linalg.norm(sg_verts()["co"], axis=1).min() < SG["lowest"].min() - 1e-3, "a Subtract stroke to go inward"))


@step
def sg_subtract_check():
    inward = np.linalg.norm(sg_verts()["co"], axis=1) - SG["lowest"]
    check(inward.min() < -0.005, "Subtract moves the surface inward (%.3f)" % inward.min())
    event('N', 'PRESS', SG["c"])
    event('N', 'RELEASE', SG["c"])


step(wait_until(lambda: bpy.context.tool_settings.sculpt.brush.direction == 'ADD', "N to switch the brush back to Add"))


# --- Lazy Mouse (L toggles it), Status Line wiring, stroke and alpha tiles, matcap picks

@step
def sg_lazy():
    brush = bpy.context.tool_settings.sculpt.brush
    check(not brush.use_smooth_stroke, "Lazy Mouse starts off")
    event('MOUSEMOVE', xy=SG["c"])
    event('L', 'PRESS', SG["c"])
    event('L', 'RELEASE', SG["c"])


step(wait_until(lambda: bpy.context.tool_settings.sculpt.brush.use_smooth_stroke, "L to turn Lazy Mouse on"))


@step
def sg_lazy_stroke():
    SG["before"] = sg_verts()["co"].copy()
    bpy.context.tool_settings.sculpt.brush.smooth_stroke_radius = 40
    a, b = SG["path"]
    sg_press(a)
    sg_move(a, b, steps=20)


@step
def sg_lazy_release():
    sg_release(SG["path"][1])


step(wait_until(lambda: np.abs(sg_verts()["co"] - SG["before"]).max() > 1e-3, "a Lazy Mouse stroke to sculpt"))


@step
def sg_lazy_check():
    check(not tracebacks(), "Python error in a Lazy Mouse stroke")
    bpy.context.tool_settings.sculpt.brush.use_smooth_stroke = False


@step
def sg_tiles():
    brush = bpy.context.tool_settings.sculpt.brush
    for kind, _label, _desc in m3d_sculpt.STROKES:
        press_ok("m3d.stroke_pick", stroke=kind)
        check(brush.stroke_method == kind, "stroke tile %s -> %s" % (kind, brush.stroke_method))
    press_ok("m3d.stroke_pick", stroke='SPACE')
    for name in m3d_sculpt.STARTER_ALPHAS:
        press_ok("m3d.alpha_pick", name=name)
        check(brush.texture is not None and brush.texture.name == name and brush.texture.library is not None
              and brush.texture_slot.map_mode == 'AREA_PLANE', "alpha tile %s" % name)
    press_ok("m3d.alpha_pick", name="Star")
    SG["before"] = sg_verts()["co"].copy()
    a, b = SG["path"]
    sg_press(a)
    sg_move(a, b)


@step
def sg_tiles_release():
    sg_release(SG["path"][1])


step(wait_until(lambda: np.abs(sg_verts()["co"] - SG["before"]).max() > 1e-3, "a stroke with an alpha to sculpt"))


@step
def sg_matcap():
    check(not tracebacks(), "Python error in a stroke with an alpha")
    press_ok("m3d.alpha_pick", name="")
    check(bpy.context.tool_settings.sculpt.brush.texture is None, "None alpha tile")
    shading = view3d()[1].spaces.active.shading
    lights = m3d_sculpt.studio_lights(bpy.context, 'MATCAP')
    check(len(lights) >= 10, "matcap list (%d)" % len(lights))
    for sl in (lights[3], lights[0]):
        press_ok("m3d.light_pick", name=sl.name, kind='MATCAP')
        check(shading.light == 'MATCAP' and shading.studio_light == sl.name, "matcap tile %s -> %s" % (sl.name, shading.studio_light))
    press_ok("m3d.light_pick", name=m3d_sculpt.studio_lights(bpy.context, 'STUDIO')[0].name, kind='STUDIO')
    check(shading.light == 'STUDIO', "studio light tile")


@step
def sg_color_brush():
    # A color brush shows its colors in the Status Line (the header has no brush tool).
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Paint Soft"))
    for a in window().screen.areas:
        a.tag_redraw()


@step
def sg_color_brush_check():
    check(not tracebacks(), "Python error drawing the Status Line with a color brush")
    check(bpy.context.tool_settings.sculpt.brush.sculpt_capabilities.has_color, "the color brush is active")
    press_ok("brush.asset_activate", **m3d_sculpt.brush_props("Draw"))
    for a in window().screen.areas:
        a.tag_redraw()


@step
def sg_popovers():
    # The new Status Line popovers draw with the sphere in Sculpt Mode.
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_panel(name="M3D_PT_sculpt_brush")


@step
def sg_popover_remesh():
    check(not tracebacks(), "Python error drawing the Brush popover")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_panel(name="M3D_PT_sculpt_remesh")


@step
def sg_popover_matcap():
    check(not tracebacks(), "Python error drawing the Remesh popover")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_panel(name="M3D_PT_sculpt_shading")


@step
def sg_popover_done():
    check(not tracebacks(), "Python error drawing the Matcap popover")
    event('ESC', 'PRESS', GIZMO["center"])
    event('ESC', 'RELEASE', GIZMO["center"])


@step
def sg_done():
    import shutil
    check(not tracebacks(), "Python error in the Sculpt gesture tests")
    shutil.rmtree(SG["alphas"], ignore_errors=True)
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


def tex_roles():
    """{role: area} of the Properties editors of the Texture screen: tools (the tool strip), assets, sets (the Texture Set List), dock
    (Layers | Texture Set Settings), props (Properties) and dockbar (the dock strip): left to right, top to bottom."""
    areas = sorted(props_areas(), key=lambda a: (a.x, -a.y))
    return dict(zip(("tools", "assets", "sets", "dock", "props", "dockbar"), areas))


def tex_areas():
    """(Assets, Layers dock) Properties editors of the Texture screen: any of the editors can run a button's operator; Assets stands in
    for the brush tray the old layout had."""
    roles = tex_roles()
    return roles["assets"], roles["dock"]


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
    check(len(props_areas()) == 6, "Texture has six Properties editors: tool strip, Assets, Texture Sets, Layers dock, Properties, dock strip (%d)" % len(props_areas()))
    check(not [a for a in screen.areas if a.type == 'OUTLINER'], "the Outliner is not in the Texture workspace")
    roles = tex_roles()
    view, _region = tex_view()
    image = next(a for a in screen.areas if a.type == 'IMAGE_EDITOR')
    width = max(a.x + a.width for a in screen.areas)
    check(window().workspace.m3d_layout == 1, "the Texture workspace has the new layout (Workspace.m3d_layout)")
    check(roles["tools"].x < roles["assets"].x < view.x < image.x < roles["dock"].x < roles["dockbar"].x,
          "Texture layout left to right: tool strip, Assets, 3D view, 2D view, the column, dock strip")
    check(roles["tools"].width < 0.035 * width and roles["dockbar"].width < 0.035 * width, "the strips are narrow (%d and %d of %d px)" % (roles["tools"].width, roles["dockbar"].width, width))
    check(0.10 * width < roles["assets"].width < 0.15 * width, "Assets is 10-15%% of the window (%d of %d px)" % (roles["assets"].width, width))
    column_h = roles["sets"].height + roles["dock"].height + roles["props"].height
    check(roles["sets"].y > roles["dock"].y > roles["props"].y and roles["sets"].x == roles["dock"].x == roles["props"].x,
          "the right column: Texture Sets over the dock over Properties")
    check(0.10 < roles["sets"].height / column_h < 0.20 and 0.42 < roles["dock"].height / column_h < 0.55 and 0.30 < roles["props"].height / column_h < 0.42,
          "the column is split about 14 / 47 / 36 (%.2f %.2f %.2f)" % tuple(roles[r].height / column_h for r in ("sets", "dock", "props")))
    check(0.14 < roles["dock"].width / width < 0.20, "the column is about 17%% of the window wide (%.3f)" % (roles["dock"].width / width))
    check(view.width > 0.45 * (view.width + image.width) and image.width > 0.35 * (view.width + image.width),
          "the 3D view and the 2D view share the middle about equally (%d, %d)" % (view.width, image.width))
    check(view.spaces.active.shading.type == 'MATERIAL', "3D view is in Material Preview")
    check(image.spaces.active.mode == 'PAINT' and not image.spaces.active.show_region_ui, "paint view is in Paint mode, sidebar closed")
    for area in (view, image):
        check(not area.spaces.active.show_region_toolbar and not area.spaces.active.show_region_tool_header and not area.spaces.active.show_region_asset_shelf,
              "%s: Blender's tool column, tool header and asset shelf are hidden" % area.type)
    check(all(a.spaces.active.context == 'MODELING_TOOLKIT' for a in props_areas()), "every editor shows pages")
    check(not roles["tools"].spaces.active.show_region_header and not roles["dockbar"].spaces.active.show_region_header, "the strips have no header")
    for role, area in roles.items():
        nav = next(r for r in area.regions if r.type == 'NAVIGATION_BAR')
        check(nav.width <= 1, "%s: no column of stock tabs" % role)
    for role, want in (("tools", 'TOOLS'), ("assets", 'ASSETS'), ("sets", 'SETS'), ("dock", 'RIGHT'), ("props", 'PROPS'), ("dockbar", 'DOCKBAR')):
        with bpy.context.temp_override(window=window(), area=roles[role]):
            check(m3d_workspace.side_of(bpy.context) == want, "the %s editor knows its role (%s)" % (role, m3d_workspace.side_of(bpy.context)))
    with bpy.context.temp_override(window=window(), area=roles["dock"]):
        check(m3d_workspace.active_page(bpy.context) == "tex_layers", "the dock opens on Layers")
    check(not window().workspace.m3d_show_shelf and topbar_px() < GIZMO["topbar_model"], "no shelf rows in the top bar (%d px, Modeling %d)" % (topbar_px(), GIZMO["topbar_model"]))
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
    # The channel buttons of Texture Set Settings (plain operator buttons).
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_channel('INVOKE_DEFAULT', channel='BASE_COLOR') == {'FINISHED'}, "channel button")
    check(m3d_texture.active_channel(tex_mat()) == 'BASE_COLOR', "Base Color is active")
    event('MOUSEMOVE', xy=tex_xy())
    event('C', 'PRESS', tex_xy())
    event('C', 'RELEASE', tex_xy())


def tex_mode3d():
    return m3d_texture.view_mode_3d(bpy.context, tex_view()[0].spaces.active)


@step
def tex_c_key():
    check(tex_mode3d() == "CHANNEL:BASE_COLOR" and m3d_texture.channel_view_on(tex_view()[0].spaces.active.shading),
          "C did not show the first channel on its own (%s)" % tex_mode3d())
    event('C', 'PRESS', tex_xy())
    event('C', 'RELEASE', tex_xy())


@step
def tex_c_key2():
    check(tex_mode3d() == "CHANNEL:ROUGHNESS" and m3d_texture.active_channel(tex_mat()) == 'ROUGHNESS',
          "C did not show the next channel (%s, %s)" % (tex_mode3d(), m3d_texture.active_channel(tex_mat())))
    event('C', 'PRESS', tex_xy(), shift=True)
    event('C', 'RELEASE', tex_xy(), shift=True)


@step
def tex_shift_c_key():
    check(tex_mode3d() == "CHANNEL:BASE_COLOR", "Shift+C did not show the previous channel (%s)" % tex_mode3d())
    event('C', 'PRESS', tex_xy(), shift=True)
    event('C', 'RELEASE', tex_xy(), shift=True)


@step
def tex_shift_c_key2():
    check(tex_mode3d() == 'MATERIAL' and not m3d_texture.channel_view_on(tex_view()[0].spaces.active.shading),
          "Shift+C from the first channel did not go back to the material (%s)" % tex_mode3d())


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
    event('X', 'PRESS', tex_xy())
    event('X', 'RELEASE', tex_xy())


@step
def tex_swap_key():
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    check(tuple(round(c, 2) for c in ups.color) == (0.0, 0.0, 1.0), "X did not swap the colors (%s)" % (tuple(ups.color),))
    event('X', 'PRESS', tex_xy())
    event('X', 'RELEASE', tex_xy())


@step
def tex_plain_x():
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    check(tuple(round(c, 2) for c in ups.color) == (1.0, 0.0, 0.0), "X again swapped them back (%s)" % (tuple(ups.color),))


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


step(wait_until(lambda: not QB.running(), "the bake of the dock to finish (it is a queue of jobs: the window goes on)", 400))


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
    tx.export_padding = 'NONE'   # (the files are compared with the painted pixels: the padding has its own tests)
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
    dock_pages = [t for t in m3d_workspace.DOCK_TABS['TEXTURE']['RIGHT']]
    for object_mode in (False, True):
        for tab in dock_pages:
            def show(tab=tab, object_mode=object_mode):
                if object_mode and bpy.context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                if not object_mode and bpy.context.mode != 'PAINT_TEXTURE':
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                dock = tex_areas()[1]
                dock.spaces.active.context = 'MODELING_TOOLKIT'
                press_ok("m3d.dock_page", _area=dock, tab=tab.id)
                for a in window().screen.areas:
                    a.tag_redraw()

            def check_draw(tab=tab, object_mode=object_mode):
                check(window().workspace.m3d_page_right == tab.page, "dock tab %s did not open its page" % tab.id)
                check(not tracebacks(), "Python error while drawing the Texture page %s%s" % (tab.page, " (Object Mode)" if object_mode else ""))
            show.__name__, check_draw.__name__ = "tex_show_%s%s" % (tab.page, object_mode), "tex_drawn_%s%s" % (tab.page, object_mode)
            yield show
            yield check_draw
        def others(object_mode=object_mode):
            # the other editors draw in this mode too (the tool strip, Assets in every category, the sets, Properties, the dock strip)
            for category in ('MATERIALS', 'SMART_MATERIALS', 'SMART_MASKS', 'BRUSHES', 'ALPHAS', 'ENVIRONMENTS', 'MINE'):
                bpy.context.scene.m3d_library.category = category
                for a in window().screen.areas:
                    a.tag_redraw()
        def others_check(object_mode=object_mode):
            check(not tracebacks(), "Python error while drawing the Texture editors%s" % (" (Object Mode)" if object_mode else ""))
        others.__name__, others_check.__name__ = "tex_others_%s" % object_mode, "tex_others_drawn_%s" % object_mode
        yield others
        yield others_check
    def restore():
        window().workspace.m3d_page_right = "tex_layers"
        bpy.context.scene.m3d_library.category = 'MATERIALS'
        if bpy.context.mode != 'PAINT_TEXTURE':
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    yield restore


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
    LY.set_look(m.m3d_layers[2], blend='OVERLAY', opacity=0.5)
    press_ok("m3d.layer_mask_add", _area=tex_areas()[1], fill='WHITE')


@step
def lay_mask_check():
    m = lay_mat()
    fill = m.m3d_layers[2]
    check(LY.paint_effect(fill) is not None and m.texture_paint_images[m.paint_active_slot] == LY.paint_effect(fill).image, "Add Mask: the brush is on the mask")
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
    check(m.texture_paint_images[m.paint_active_slot] == LY.paint_effect(m.m3d_layers[1]).image, "the brush follows the moved layer (its mask)")
    top = LY.base_source(m).node   # (past the AO multiply the baked AO map puts in front of the shader)
    check(top.name == LY.part('BASE_COLOR', m.m3d_layers[2].uid, "mix"), "the Paint Layer is on top of the Base Color chain")
    check(np.array_equal(px(lay_image(2)), GIZMO["stroked"]), "moving layers keeps their pixels")
    m.m3d_layer_index = 2
    check(m.texture_paint_images[m.paint_active_slot] == lay_image(2), "selecting a layer aims the brush at it")
    GIZMO["images"] = {i.name for i in bpy.data.images}
    GIZMO["fill_mask"] = LY.paint_effect(m.m3d_layers[1]).image.name
    GIZMO["stroke_img"] = lay_image(2).name
    press_ok("m3d.layer_merge_down", _area=tex_areas()[1])


@step
def lay_merge_check():
    m = lay_mat()
    check(lay_names() == ["Base", "Fill Layer"] and m.m3d_layer_index == 1, "Merge Down: %s" % lay_names())
    low = m.m3d_layers[1]
    check(low.kind == 'PAINT' and not low.mask_stack and LY.opacity_of(low, 'BASE_COLOR') == 1.0 and lay_image(1) is not None,
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
    tx.export_padding = 'NONE'
    press_ok("m3d.tex_export", _area=tex_areas()[1])


@step
def lay_export_check():
    files = sorted(os.listdir(GIZMO["out2"]))
    m = lay_mat()
    # (the set has the baked normal map of the bake in the dock: it is the base of the Normal, so the Normal is written, as the 3D view shows it)
    check(LY.baked_image(m, "Normal") is not None, "the texture set has its baked normal map")
    check(files == ["T_Crate_BC.png", "T_Crate_N.png", "T_Crate_ORM.png"], "export of a stack wrote the Unreal files (%s)" % files)
    img = bpy.data.images.load(os.path.join(GIZMO["out2"], "T_Crate_N.png"))
    img.colorspace_settings.name = 'Non-Color'
    file_n = px(img)[:, :3]
    want_n = LY.flatten_normal(m, 128)[..., :3].reshape(-1, 3).copy()
    want_n[:, 1] = 1.0 - want_n[:, 1]   # (the Unreal normal map is DirectX)
    check(file_n.shape == want_n.shape and np.abs(file_n - want_n).max() < 3 / 255,
          "the exported normal is the baked normal under the layers' (largest difference %.4f)" % np.abs(file_n - want_n).max())
    bpy.data.images.remove(img)
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
    check(lay_names() == ["Base", "Fill Layer"] and m.m3d_layers[1].kind == 'FILL' and not m.m3d_layers[1].mask_stack,
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


# ----------------------------------------------------------------------------------------------------
# Multi-channel painting: one stroke paints every channel of the brush material at once (Base Color with the brush color, the
# others with their own value), the Eraser erases them all, one Ctrl+Z takes the whole stroke back.

MC = {}


def mc_layer():
    m = lay_mat()
    return m.m3d_layers[m.m3d_layer_index]


def mc_image(ch):
    return LY.entry_of(mc_layer(), ch).image


def mc_brush():
    return bpy.context.scene.m3d_tex.brush


def mc_shots():
    """{channel: pixels} of the active layer's images."""
    return {ch.id: px(mc_image(ch.id)).copy() for ch in LY.CHANNELS if mc_image(ch.id) is not None}


def mc_list():
    """[(image name, color or None)] the paint code is told to paint."""
    items = bpy.context.window_manager.get(LY.TARGETS)
    return [(i["image"], tuple(i["color"].to_list()) if "color" in i else None) for i in items] if items is not None else []


def mc_points(x0=-40, x1=40, dy=0, n=11):
    """A horizontal stroke through the cube's centre, in window coordinates."""
    view, region = tex_view()
    p = location_3d_to_region_2d(region, view.spaces.active.region_3d, Vector((0, 0, 0)))
    cx, cy = (int(region.x + p.x), int(region.y + p.y)) if p is not None else tex_xy()
    return [(cx + x0 + (x1 - x0) * i // (n - 1), cy + dy) for i in range(n)]


def mc_press(points):
    event('MOUSEMOVE', xy=points[0])
    event('LEFTMOUSE', 'PRESS', points[0])
    for xy in points[1:]:
        event('MOUSEMOVE', xy=xy)


def mc_release(points):
    event('LEFTMOUSE', 'RELEASE', points[-1])


def mc_chord(key, shift=False):
    """Ctrl+key (Ctrl+Shift+key) over the 3D view."""
    xy = MC["points"][0]
    event('LEFT_CTRL', 'PRESS', xy, ctrl=True)
    if shift:
        event('LEFT_SHIFT', 'PRESS', xy, ctrl=True, shift=True)
    event(key, 'PRESS', xy, ctrl=True, shift=shift)
    event(key, 'RELEASE', xy, ctrl=True, shift=shift)
    if shift:
        event('LEFT_SHIFT', 'RELEASE', xy, ctrl=True)
    event('LEFT_CTRL', 'RELEASE', xy)


def mc_push(message):
    """The undo step a button press makes after it changed a property (a change from Python makes none): Undo must not go
    back past the property."""
    bpy.ops.ed.undo_push(message=message)


def mc_equal(a, b):
    return a.keys() == b.keys() and all(np.array_equal(a[k], b[k]) for k in a)


def mc_undo_until(name, target, tries=4):
    """A step that presses Ctrl+Z until the layer's images are `target()`: a tool button between two strokes is an undo step too."""
    count = [0]

    def body():
        if mc_equal(mc_shots(), target()):
            return
        count[0] += 1
        if count[0] > tries:
            fails.append("%s: Ctrl+Z did not bring the layer back (%s)" % (name, mc_diff(mc_shots(), target())))
            return
        mc_chord('Z')
        steps.insert(0, body)
    body.__name__ = name
    return body


def mc_diff(a, b):
    """Which channels differ, and on how many texels (for the messages)."""
    return {k: int((np.abs(a[k] - b[k]).max(axis=1) > 0).sum()) for k in a if k in b and not np.array_equal(a[k], b[k])}


def mc_expect(tag, before, after, want, skip=()):
    """The stroke between `before` and `after` painted every channel of `want` ({channel: stored rgb}) on the same texels as the
    first one, with its value; the other channels and everything outside the stroke are as they were. Returns the texels."""
    canvas = next(iter(want))
    changed = np.abs(after[canvas] - before[canvas]).max(axis=1) > 0.0
    check(changed.sum() > 40, "%s: the stroke painted the canvas (%d texels)" % (tag, changed.sum()))
    solid = after[canvas][:, 3] > 0.25
    for ch, rgb in want.items():
        img = after[ch]
        check(np.array_equal(np.abs(img - before[ch]).max(axis=1) > 0.0, changed), "%s: %s changed the texels of %s" % (tag, ch, canvas))
        check(np.abs(img[changed][:, 3] - after[canvas][changed][:, 3]).max() <= 1.5 / 255,
              "%s: %s has the alpha of the stroke (largest difference %.4f)" % (tag, ch, np.abs(img[changed][:, 3] - after[canvas][changed][:, 3]).max()))
        if solid.any():
            err = np.abs(img[solid][:, :3] - np.asarray(rgb, np.float32)).max()
            check(err <= 4 / 255, "%s: %s holds %s (largest difference %.4f)" % (tag, ch, tuple(round(float(v), 3) for v in rgb), err))
        check(np.array_equal(img[~changed], before[ch][~changed]), "%s: %s is as before outside the stroke" % (tag, ch))
    for ch in after:
        if ch not in want and ch not in skip:
            check(np.array_equal(after[ch], before[ch]), "%s: %s is not painted and did not change" % (tag, ch))
    return changed


@step
def mc_setup():
    lay_show_tab()
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='PAINT')
    press_ok("m3d.layer_add", _area=tex_areas()[1], kind='PAINT')
    bpy.context.tool_settings.image_paint.unified_paint_settings.color = (1.0, 0.0, 0.0)
    b = mc_brush()
    b.roughness, b.metallic, b.height = 0.2, 1.0, 0.8
    b.use_roughness = b.use_metallic = b.use_height = True
    mc_push("Brush material")


@step
def mc_setup_check():
    m, layer, b = lay_mat(), mc_layer(), mc_brush()
    check(layer.kind == 'PAINT' and m.m3d_layer_index == len(m.m3d_layers) - 1, "multi-channel tests start on a new paint layer (%s)" % lay_names())
    check(b.use_base_color and b.use_roughness and b.use_metallic and b.use_height and not b.use_emission, "the brush material has four channels on")
    names = [mc_image(c).name for c in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'HEIGHT')]
    items = mc_list()
    check([n for n, _c in items] == names and items[0][1] is None, "the list of what a stroke paints: Base Color first, without a color (%s)" % items)
    got = {n: c for n, c in items}
    check(all(np.allclose(got[mc_image(c).name], (v,) * 3, atol=1e-6) for c, v in (('ROUGHNESS', 0.2), ('METALLIC', 1.0), ('HEIGHT', 0.8))),
          "...the others with their values (%s)" % items)
    check({tuple(mc_image(c).size) for c in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'HEIGHT')} == {(128, 128)}, "the four images have the same size")
    check(mc_image('EMISSION') is None and mc_image('NORMAL') is None, "channels that are off have no image")
    check(m.texture_paint_images[m.paint_active_slot] == mc_image('BASE_COLOR'), "the canvas (the active slot) is the Base Color image")
    MC["before"], MC["points"] = mc_shots(), mc_points()
    check(not tracebacks(), "Python error setting up the brush material")
    event('MOUSEMOVE', xy=MC["points"][0])


@step
def mc_stroke_press():
    mc_press(MC["points"])


@step
def mc_stroke_release():
    mc_release(MC["points"])


@step
def mc_stroke_check():
    after = mc_shots()
    MC["after"] = after
    MC["changed"] = mc_expect("mc stroke", MC["before"], after,
                              {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(not tracebacks(), "Python error during the multi-channel stroke")
    mc_chord('Z')


@step
def mc_undo_check():
    check(mc_equal(mc_shots(), MC["before"]), "one Ctrl+Z took the stroke back in all four channels")
    check(not tracebacks(), "Python error in Undo of the multi-channel stroke")
    check(mc_list() and len(mc_list()) == 4, "Undo left the list of what a stroke paints (%s)" % mc_list())
    mc_chord('Z', shift=True)


@step
def mc_redo_check():
    check(mc_equal(mc_shots(), MC["after"]), "Ctrl+Shift+Z brought the stroke back in all four channels")
    check(not tracebacks(), "Python error in Redo of the multi-channel stroke")
    # The Eraser: the right half of the stroke, in all four channels.
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='ERASER')
    MC["before_erase"] = mc_shots()
    MC["erase_points"] = mc_points(0, 40, n=6)


@step
def mc_eraser_press():
    mc_press(MC["erase_points"])


@step
def mc_eraser_release():
    mc_release(MC["erase_points"])


@step
def mc_eraser_check():
    before, after = MC["before_erase"], mc_shots()
    erased = before['BASE_COLOR'][:, 3] - after['BASE_COLOR'][:, 3] > 0.05
    check(erased.sum() > 10, "the Eraser erased the canvas (%d texels)" % erased.sum())
    for ch in before:
        a = before[ch][:, 3] - after[ch][:, 3]
        check(np.array_equal(a > 0.05, erased) and np.abs(a - (before['BASE_COLOR'][:, 3] - after['BASE_COLOR'][:, 3])).max() <= 1.5 / 255,
              "the Eraser took the alpha of %s down on the same texels, by the same amount" % ch)
        check(np.array_equal(after[ch][a <= 0], before[ch][a <= 0]), "...and left the rest of %s alone" % ch)
    check(not tracebacks(), "Python error while erasing")
    mc_chord('Z')


@step
def mc_eraser_undo_check():
    check(mc_equal(mc_shots(), MC["before_erase"]), "one Ctrl+Z took the erasing back in all four channels")
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='PAINT')
    mc_brush().use_roughness = False   # A channel that is off is not touched.
    mc_push("Roughness off")
    MC["before_off"], MC["off_points"] = mc_shots(), mc_points(-40, 40, dy=-24)
    event('MOUSEMOVE', xy=MC["off_points"][0])


@step
def mc_off_press():
    mc_press(MC["off_points"])


@step
def mc_off_release():
    mc_release(MC["off_points"])


@step
def mc_off_check():
    before, after = MC["before_off"], mc_shots()
    mc_expect("mc roughness off", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(np.array_equal(after['ROUGHNESS'], before['ROUGHNESS']), "Roughness is off: the stroke did not touch it")
    check(len(mc_list()) == 3, "the list lost Roughness (%s)" % mc_list())
    mc_chord('Z')


@step
def mc_off_undo_check():
    check(mc_equal(mc_shots(), MC["before_off"]), "Undo of a stroke with Roughness off")
    # Base Color off: the canvas is the first channel that is on (Metallic), painted with its own value, not the brush color.
    b = mc_brush()
    b.use_base_color = False
    mc_push("Base Color off")
    m = lay_mat()
    check(m.texture_paint_images[m.paint_active_slot] == mc_image('METALLIC'), "Base Color off: the canvas is the Metallic image")
    items = mc_list()
    check(len(items) == 2 and items[0][0] == mc_image('METALLIC').name and items[0][1] == (1.0, 1.0, 1.0), "...with its value in the list (%s)" % items)
    MC["before_canvas"], MC["canvas_points"] = mc_shots(), mc_points(-40, 40, dy=24)
    event('MOUSEMOVE', xy=MC["canvas_points"][0])


@step
def mc_canvas_press():
    mc_press(MC["canvas_points"])


@step
def mc_canvas_release():
    mc_release(MC["canvas_points"])


@step
def mc_canvas_check():
    before, after = MC["before_canvas"], mc_shots()
    mc_expect("mc canvas not Base Color", before, after, {'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(np.array_equal(after['BASE_COLOR'], before['BASE_COLOR']) and np.array_equal(after['ROUGHNESS'], before['ROUGHNESS']),
          "Base Color and Roughness are off: not touched")
    check(not tracebacks(), "Python error painting with a canvas that is not Base Color")
    mc_chord('Z')


@step
def mc_canvas_undo_check():
    check(mc_equal(mc_shots(), MC["before_canvas"]), "Undo of a stroke whose canvas is not Base Color")
    b = mc_brush()
    b.use_base_color = b.use_roughness = True
    mc_push("Base Color and Roughness on")
    # A long stroke across the cube's edges, with seam bleed: every channel has the same texels (the bleed included).
    bpy.context.tool_settings.image_paint.seam_bleed = 3
    MC["before_seam"], MC["seam_points"] = mc_shots(), mc_points(-110, 110, dy=-50, n=16)
    event('MOUSEMOVE', xy=MC["seam_points"][0])


@step
def mc_seam_press():
    mc_press(MC["seam_points"])


@step
def mc_seam_release():
    mc_release(MC["seam_points"])


@step
def mc_seam_check():
    before, after = MC["before_seam"], mc_shots()
    mc_expect("mc seam bleed", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(not tracebacks(), "Python error painting across seams with bleed")
    mc_chord('Z')


@step
def mc_seam_undo_check():
    check(mc_equal(mc_shots(), MC["before_seam"]), "Undo of a stroke across seams")
    bpy.context.tool_settings.image_paint.seam_bleed = 2
    # Symmetry: the mirrored texels change in every channel too.
    bpy.context.active_object.data.use_mirror_x = True
    mc_push("Symmetry")
    MC["before_mirror"], MC["mirror_points"] = mc_shots(), mc_points(-40, 40, dy=40)
    event('MOUSEMOVE', xy=MC["mirror_points"][0])


@step
def mc_mirror_press():
    mc_press(MC["mirror_points"])


@step
def mc_mirror_release():
    mc_release(MC["mirror_points"])


@step
def mc_mirror_check():
    before, after = MC["before_mirror"], mc_shots()
    mc_expect("mc symmetry", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(not tracebacks(), "Python error painting with symmetry")
    bpy.context.active_object.data.use_mirror_x = False
    mc_chord('Z')


@step
def mc_mirror_undo_check():
    check(mc_equal(mc_shots(), MC["before_mirror"]), "Undo of a stroke with symmetry")


@step
def mc_fill_setup():
    # Polygon Fill: the Fill brush on the face under the cursor fills every channel; one undo takes it back.
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='POLYFILL')
    MC["before_fill"], MC["fill_xy"] = mc_shots(), mc_points()[5]
    event('MOUSEMOVE', xy=MC["fill_xy"])


@step
def mc_fill_press():
    event('LEFTMOUSE', 'PRESS', MC["fill_xy"])


@step
def mc_fill_release():
    event('LEFTMOUSE', 'RELEASE', MC["fill_xy"])


@step
def mc_fill_check():
    before, after = MC["before_fill"], mc_shots()
    changed = mc_expect("mc polygon fill", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(changed.sum() > 500, "the fill covered a polygon of the cube (%d texels)" % changed.sum())
    check(not tracebacks(), "Python error filling")
    mc_chord('Z')


@step
def mc_fill_undo_check():
    check(mc_equal(mc_shots(), MC["before_fill"]), "one Ctrl+Z took the fill back in all four channels")
    # Smudge lifts color from the canvas: it changes the canvas only (the other channels need their own smear, not done yet).
    # Put paint under it first: a plain stroke.
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='PAINT')
    MC["smudge_points"] = mc_points(-60, 60, dy=0, n=13)
    event('MOUSEMOVE', xy=MC["points"][0])


@step
def mc_smudge_paint_press():
    mc_press(MC["points"])


@step
def mc_smudge_paint_release():
    mc_release(MC["points"])


@step
def mc_smudge_setup():
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='SMUDGE')
    MC["before_smudge"] = mc_shots()
    event('MOUSEMOVE', xy=MC["smudge_points"][0])


@step
def mc_smudge_press():
    mc_press(MC["smudge_points"])


@step
def mc_smudge_release():
    mc_release(MC["smudge_points"])


@step
def mc_smudge_check():
    before, after = MC["before_smudge"], mc_shots()
    check(not np.array_equal(after['BASE_COLOR'], before['BASE_COLOR']), "Smudge moved the Base Color")
    check(all(np.array_equal(after[ch], before[ch]) for ch in ('ROUGHNESS', 'METALLIC', 'HEIGHT')),
          "...and only that: Smudge works on the canvas channel (the other three are as they were)")
    check(not tracebacks(), "Python error smudging")
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='PAINT')
    mc_chord('Z')


@step
def mc_smudge_undo_check():
    check(mc_equal(mc_shots(), MC["before_smudge"]), "Undo of the smudge")
    mc_chord('Z')   # ...and the stroke under it


step(mc_undo_until("mc_smudge_all_undone", lambda: MC["after"]))


@step
def mc_float_setup():
    check(mc_equal(mc_shots(), MC["after"]), "(the layer is as the first stroke left it: %s)" % mc_diff(mc_shots(), MC["after"]))
    # A float image among byte images (same size): it is painted too, with the value in the float image.
    m = lay_mat()
    height = mc_image('HEIGHT')
    flt = bpy.data.images.new("MCFloat", 128, 128, alpha=True, float_buffer=True, is_data=True)
    flt.colorspace_settings.name = 'Non-Color'   # (before the pixels: choosing the color space blanks a generated image)
    data = px(height).copy()
    data[:, :3] *= data[:, 3:4]   # (a float image holds premultiplied colors)
    flt.pixels.foreach_set(data.ravel())
    flt.update()
    flt["m3d_channel"] = 'HEIGHT'
    with LY.muted():
        LY.entry_of(mc_layer(), 'HEIGHT').image = flt
    LY.rebuild_all(m)
    LY.sync_target(bpy.context, m, True)
    mc_push("Float Height")
    MC["flt"], MC["old_height"] = flt, height
    MC["before_float"], MC["float_points"] = mc_shots(), mc_points(-40, 40, dy=-10)
    event('MOUSEMOVE', xy=MC["float_points"][0])


@step
def mc_float_press():
    mc_press(MC["float_points"])


@step
def mc_float_release():
    mc_release(MC["float_points"])


@step
def mc_float_check():
    before, after = MC["before_float"], mc_shots()
    changed = mc_expect("mc float", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'METALLIC': (1.0,) * 3}, skip=('HEIGHT',))
    flt, a = after['HEIGHT'], after['HEIGHT'][:, 3]
    check(np.abs(a - after['BASE_COLOR'][:, 3]).max() <= 1.5 / 255, "the float image has the alpha of the stroke (largest difference %.4f; before: alpha %.2f-%.2f)" % (
        np.abs(a - after['BASE_COLOR'][:, 3]).max(), before['HEIGHT'][:, 3].min(), before['HEIGHT'][:, 3].max()))
    solid = a > 0.25
    check(solid.any() and np.abs(flt[solid, :3] / a[solid, None] - 0.8).max() < 2e-3,
          "...with the value (premultiplied by the stroke's alpha: %.4f)" % (np.abs(flt[solid, :3] / a[solid, None] - 0.8).max() if solid.any() else -1))
    check(np.array_equal(flt[~changed & (a == 0)], before['HEIGHT'][~changed & (a == 0)]), "...and nothing outside it")
    check(not tracebacks(), "Python error painting a float image along with byte images")
    mc_chord('Z')


@step
def mc_float_undo_check():
    check(mc_equal(mc_shots(), MC["before_float"]), "Undo restores the float image with the others")
    # Back to a byte Height image.
    with LY.muted():
        LY.entry_of(mc_layer(), 'HEIGHT').image = MC["old_height"]
    LY.rebuild_all(lay_mat())
    LY.sync_target(bpy.context, lay_mat(), True)
    bpy.data.images.remove(MC["flt"])
    mc_push("Byte Height")
    # An image of another size is not painted (and says so); the others are.
    m = lay_mat()
    small_ = bpy.data.images.new("MCHalf", 64, 64, alpha=True, is_data=True)
    small_.colorspace_settings.name = 'Non-Color'
    small_["m3d_channel"] = 'METALLIC'
    with LY.muted():
        MC["old_metal"] = LY.entry_of(mc_layer(), 'METALLIC').image
        LY.entry_of(mc_layer(), 'METALLIC').image = small_
    LY.rebuild_all(m)
    LY.sync_target(bpy.context, m, True)
    mc_push("Half-size Metallic")
    MC["before_size"], MC["size_points"] = mc_shots(), mc_points(-40, 40, dy=-10)
    event('MOUSEMOVE', xy=MC["size_points"][0])


@step
def mc_size_press():
    mc_press(MC["size_points"])


@step
def mc_size_release():
    mc_release(MC["size_points"])


@step
def mc_size_check():
    before, after = MC["before_size"], mc_shots()
    mc_expect("mc size", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'HEIGHT': (0.8,) * 3})
    check(np.array_equal(after['METALLIC'], before['METALLIC']), "an image of another size is not painted (the others are)")
    check(not tracebacks(), "Python error with an image of another size")
    mc_chord('Z')


@step
def mc_size_undo_check():
    check(mc_equal(mc_shots(), MC["before_size"]), "Undo of a stroke that skipped an image")
    with LY.muted():
        LY.entry_of(mc_layer(), 'METALLIC').image = MC["old_metal"]
    LY.rebuild_all(lay_mat())
    LY.sync_target(bpy.context, lay_mat(), True)
    bpy.data.images.remove(bpy.data.images["MCHalf"])
    mc_push("Metallic back")
    # A list that does not name the canvas does nothing: only the canvas is painted, and no warning.
    wm = bpy.context.window_manager
    wm[LY.TARGETS] = [{"image": "Elsewhere", "color": [0.5, 0.5, 0.5]}, {"image": mc_image('ROUGHNESS').name, "color": [0.5, 0.5, 0.5]}]
    MC["before_stale"], MC["stale_points"] = mc_shots(), mc_points(-40, 40, dy=-10)
    event('MOUSEMOVE', xy=MC["stale_points"][0])


@step
def mc_stale_press():
    mc_press(MC["stale_points"])


@step
def mc_stale_release():
    mc_release(MC["stale_points"])


@step
def mc_stale_check():
    before, after = MC["before_stale"], mc_shots()
    mc_expect("mc stale list", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0)})
    check(not tracebacks(), "Python error with a list that does not name the canvas")
    mc_chord('Z')


@step
def mc_stale_undo_check():
    check(mc_equal(mc_shots(), MC["before_stale"]), "Undo of a stroke with a list that did not name the canvas")
    LY.sync_target(bpy.context, lay_mat(), True)   # (the list is the right one again)
    check(len(mc_list()) == 4, "the list is back (%s)" % mc_list())


# --- The same in the 2D view (Image Editor in Paint mode): the canvas is the image shown there.

def mc_2d_area():
    area = next(a for a in window().screen.areas if a.type == 'IMAGE_EDITOR')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def mc_2d_points(u0=0.25, u1=0.75, v=0.5, n=11):
    """A stroke along the 2D view at height v of the image, in window coordinates."""
    area, region = mc_2d_area()
    out = []
    for i in range(n):
        rx, ry = region.view2d.view_to_region(u0 + (u1 - u0) * i / (n - 1), v, clip=False)
        out.append((int(region.x + rx), int(region.y + ry)))
    return out


@step
def mc_2d_setup():
    area, region = mc_2d_area()
    space = area.spaces.active
    space.image = mc_image('BASE_COLOR')
    space.mode = 'PAINT'
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=space):
        bpy.ops.image.view_all(fit_view=True)
    mc_push("2D view")


@step
def mc_2d_aim():
    MC["before_2d"], MC["points_2d"] = mc_shots(), mc_2d_points()
    check(window().screen.areas and mc_2d_area()[0].spaces.active.image == mc_image('BASE_COLOR'), "the 2D view shows the Base Color image")
    xy = MC["points_2d"][0]
    event('MOUSEMOVE', xy=xy)


@step
def mc_2d_press():
    mc_press(MC["points_2d"])


@step
def mc_2d_release():
    mc_release(MC["points_2d"])


@step
def mc_2d_check():
    before, after = MC["before_2d"], mc_shots()
    mc_expect("mc 2D view", before, after, {'BASE_COLOR': (1.0, 0.0, 0.0), 'ROUGHNESS': (0.2,) * 3, 'METALLIC': (1.0,) * 3, 'HEIGHT': (0.8,) * 3})
    check(not tracebacks(), "Python error painting in the 2D view")
    MC["after_2d"] = after
    mc_chord('Z')


@step
def mc_2d_undo_check():
    check(mc_equal(mc_shots(), MC["before_2d"]), "one Ctrl+Z took the 2D stroke back in all four channels")
    mc_chord('Z', shift=True)


@step
def mc_2d_redo_check():
    check(mc_equal(mc_shots(), MC["after_2d"]), "Ctrl+Shift+Z brought the 2D stroke back in all four channels")
    # The Eraser in the 2D view.
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='ERASER')
    MC["before_erase_2d"], MC["erase_points_2d"] = mc_shots(), mc_2d_points(0.5, 0.75)
    event('MOUSEMOVE', xy=MC["erase_points_2d"][0])


@step
def mc_2d_eraser_press():
    mc_press(MC["erase_points_2d"])


@step
def mc_2d_eraser_release():
    mc_release(MC["erase_points_2d"])


@step
def mc_2d_eraser_check():
    before, after = MC["before_erase_2d"], mc_shots()
    erased = before['BASE_COLOR'][:, 3] - after['BASE_COLOR'][:, 3] > 0.05
    check(erased.sum() > 10, "the Eraser erased in the 2D view (%d texels)" % erased.sum())
    for ch in before:
        a = before[ch][:, 3] - after[ch][:, 3]
        check(np.array_equal(a > 0.05, erased), "the Eraser took the alpha of %s down on the same texels in the 2D view" % ch)
    check(not tracebacks(), "Python error erasing in the 2D view")
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='PAINT')
    mc_chord('Z')
    mc_chord('Z')


@step
def mc_2d_done_check():
    check(mc_equal(mc_shots(), MC["before_2d"]), "two Ctrl+Z took the 2D eraser and the stroke back")


# --- Time: the same stroke with one channel and with five, 2K images (the stroke operator runs it in one go).

def mc_stroke_time(points, size):
    view, region = tex_view()
    elements = []
    for i, (x, y) in enumerate(points):
        rx, ry = x - region.x, y - region.y
        elements.append({"name": "", "mouse_event": (rx, ry), "mouse": (rx, ry), "is_start": i == 0, "location": (0.0, 0.0, 0.0),
                         "pressure": 1.0, "size": size, "time": i * 0.01, "x_tilt": 0.0, "y_tilt": 0.0})
    with bpy.context.temp_override(window=window(), screen=window().screen, area=view, region=region, space_data=view.spaces.active):
        t0 = time.perf_counter()
        res = bpy.ops.paint.image_paint(stroke=elements)
        return time.perf_counter() - t0, res


@step
def mc_perf_setup():
    bpy.context.scene.m3d_tex.resolution = '2048'
    b = mc_brush()
    with LY.muted():
        b.use_base_color, b.use_roughness, b.use_metallic, b.use_height, b.use_emission = True, False, False, False, False
    MC["perf_layers"] = len(lay_mat().m3d_layers)
    press_ok("m3d.layer_add", _area=tex_areas()[1], kind='PAINT')


@step
def mc_perf_one():
    MC["perf_size"] = 60.0
    MC["perf_points"] = mc_points(-120, 120, dy=0, n=40)
    check(tuple(mc_image('BASE_COLOR').size) == (2048, 2048), "the perf layer has 2K images (%s)" % (tuple(mc_image('BASE_COLOR').size),))
    one = [mc_stroke_time(MC["perf_points"], MC["perf_size"])[0] for _ in range(3)]
    MC["t1"] = sorted(one)[1]
    b = mc_brush()
    b.use_roughness = b.use_metallic = b.use_height = b.use_emission = True   # Five channels (the images are made here)


@step
def mc_perf_five():
    check(len(mc_list()) == 5, "five channels on the perf layer (%s)" % len(mc_list()))
    five = [mc_stroke_time(MC["perf_points"], MC["perf_size"])[0] for _ in range(3)]
    MC["t5"] = sorted(five)[1]
    print("MC_TIMING 1 channel %.3f s, 5 channels %.3f s, ratio %.2f (2048 px images, 40 dabs of 60 px, median of 3)" % (MC["t1"], MC["t5"], MC["t5"] / MC["t1"]))
    check(MC["t5"] < 5.0 * MC["t1"] + 0.05, "five channels cost less than five times one (%.3f s and %.3f s)" % (MC["t1"], MC["t5"]))
    check(not tracebacks(), "Python error timing strokes")


@step
def mc_cleanup():
    # Back to the state the next tests expect: the layers as they were, the brush material at its start, 128 px slots.
    for _ in range(2):
        press_ok("m3d.layer_remove", _area=tex_areas()[1])
    b = mc_brush()
    with LY.muted():
        b.use_base_color, b.use_roughness, b.use_metallic, b.use_height, b.use_emission = True, False, False, False, False
        b.roughness, b.metallic, b.height = 0.5, 0.0, 0.5
    bpy.context.scene.m3d_tex.resolution = '128'
    lay_mat().m3d_channel = 'BASE_COLOR'
    LY.sync_target(bpy.context, lay_mat(), True)
    for image in [i for i in bpy.data.images if i.name.startswith("MC")]:
        bpy.data.images.remove(image)
    mc_push("Multi-channel tests done")


@step
def mc_done():
    check(lay_names() == ["Base", "Fill Layer"] and not mc_list(), "the multi-channel tests left the layers as they were (%s, %s)" % (lay_names(), mc_list()))
    check(not tracebacks(), "Python error in the multi-channel tests")


# ----------------------------------------------------------------------------------------------------
# Phase 7a: mask effects in the Texture workspace: the Add menu by key presses, generators baked from the cube, a stroke on
# the Paint effect, order, Show Mask.

import m3d_masks as MK


def mk_layer():
    m = lay_mat()
    return m.m3d_layers[m.m3d_layer_index]


def mk_menu():
    """Open the Add Mask Effect menu in the dock the way its button does (a real popup that takes key presses)."""
    dock = tex_areas()[1]
    region = next(r for r in dock.regions if r.type == 'WINDOW')
    event('MOUSEMOVE', xy=GIZMO["mk_xy"])
    with bpy.context.temp_override(window=window(), screen=window().screen, area=dock, region=region,
                                   space_data=dock.spaces.active):
        bpy.ops.wm.call_menu(name="M3D_MT_mask_add")


def mk_key(key):
    event(key, 'PRESS', GIZMO["mk_xy"])
    event(key, 'RELEASE', GIZMO["mk_xy"])


def mk_mask():
    return MK.stack_value(mk_layer(), 128)


def mk_state(mat):
    nt = mat.node_tree
    return (sorted(n.name for n in nt.nodes),
            sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in nt.links))


@step
def mk_setup():
    lay_show_tab()
    m = lay_mat()
    ob = bpy.context.active_object
    ob.m3d_bake.resolution, ob.m3d_bake.samples = '64', 4
    m.m3d_layer_index = len(m.m3d_layers) - 1
    layer = mk_layer()
    check(layer.kind == 'FILL' and not layer.mask_stack, "mask tests start on a Fill Layer without a mask (%s)" % lay_names())
    layer.channels[0].color, layer.visible = (0.1, 0.6, 0.2, 1.0), False
    LY.set_look(layer, blend='MIX', opacity=1.0)
    GIZMO["mk_base"] = LY.composite(m, 'BASE_COLOR', 128)   # What the base layer alone looks like.
    layer.visible = True
    dock = tex_areas()[1]
    GIZMO["mk_xy"] = (dock.x + dock.width // 2, dock.y + dock.height // 2)
    GIZMO["mk_images"] = {i.name for i in bpy.data.images}


@step
def mk_open_fill():
    mk_menu()


@step
def mk_key_fill():
    mk_key('A')   # (the access key of Add Fill: the first letter of the first word)


step(wait_until(lambda: len(mk_layer().mask_stack) >= 1, "Fill from the Add menu (A key)"))


@step
def mk_fill_check():
    layer = mk_layer()
    check([e.kind for e in layer.mask_stack] == ['FILL'] and layer.mask_stack[0].value == 0.0 and layer.mask_index == 0,
          "Add Fill in the Add menu added a black Fill effect: %s" % [e.kind for e in layer.mask_stack])
    check(np.abs(LY.composite(lay_mat(), 'BASE_COLOR', 128) - GIZMO["mk_base"]).max() < 1e-5, "a black Fill hides the layer: the result is the base layer alone")
    layer.mask_stack[0].value = 1.0
    shown = LY.composite(lay_mat(), 'BASE_COLOR', 128)
    check(np.abs(shown - np.array((0.1, 0.6, 0.2), np.float32)).max() < 1e-4, "a white Fill shows the layer: the result is its color (%s)" % shown[0, 0])
    layer.mask_stack[0].value = 0.0
    check(not tracebacks(), "Python error drawing the Mask panel with a Fill effect")
    mk_menu()


@step
def mk_key_generator():
    mk_key('G')   # (Add Generator opens its menu)


@step
def mk_key_edges():
    mk_key('E')


step(wait_until(lambda: len(mk_layer().mask_stack) >= 2, "Edges from the Add Generator menu (E key, bakes the Curvature map)", tries=60))


@step
def mk_edges_check():
    layer = mk_layer()
    ob = bpy.context.active_object
    edges = layer.mask_stack[1]
    check([e.kind for e in layer.mask_stack] == ['FILL', 'EDGES'] and edges.blend == 'MULTIPLY', "E added an Edges effect above the Fill: %s" % [e.kind for e in layer.mask_stack])
    curv = bpy.data.images.get("Crate_Curvature")
    check(edges.image == curv and curv is not None and tuple(curv.size) == (64, 64) and curv.get("m3d_map") == 64,
          "the Curvature map was baked at the Bake tab's resolution and the effect reads it")
    check(bpy.context.mode == 'PAINT_TEXTURE' and not tracebacks(), "baking from the menu left Texture Paint Mode on (%s)" % bpy.context.mode)
    check(not [m for m in bpy.data.materials if m.name.startswith("m3dBake")] and ob.active_material == lay_mat(), "the bake left no temporary material")
    GIZMO["mk_stamp"] = curv["m3d_stamp"]
    edges.blend, edges.amount = 'ADD', 0.3
    mk_menu()


@step
def mk_key_levels():
    mk_key('L')


step(wait_until(lambda: len(mk_layer().mask_stack) >= 3, "Levels from the Add menu (L key)"))


@step
def mk_levels_check():
    layer = mk_layer()
    check([e.kind for e in layer.mask_stack] == ['FILL', 'EDGES', 'LEVELS'], "L added a Levels filter on top: %s" % [e.kind for e in layer.mask_stack])
    layer.mask_stack[2].black_out = 0.5   # The mask can no longer go below 0.5 above this point.
    layer.mask_stack[0].value = 1.0
    check(mk_mask().min() >= 0.5 - 1e-6, "Levels keeps the mask at 0.5 or more (%.3f)" % mk_mask().min())
    mk_menu()


@step
def mk_key_paint():
    mk_key('P')


step(wait_until(lambda: len(mk_layer().mask_stack) >= 4, "Paint from the Add menu (P key)"))


@step
def mk_paint_check():
    m = lay_mat()
    layer = mk_layer()
    paint = layer.mask_stack[3]
    check([e.kind for e in layer.mask_stack] == ['FILL', 'EDGES', 'LEVELS', 'PAINT'] and paint.blend == 'MULTIPLY' and layer.paint_mask,
          "P added a white Paint effect that multiplies, and selected the mask: %s" % [(e.kind, e.blend) for e in layer.mask_stack])
    check(m.texture_paint_images[m.paint_active_slot] == paint.image, "the brush is aimed at the Paint effect's image")
    check(px(paint.image)[:, :3].min() == 1.0, "a new Paint effect is white")
    check(np.abs(mk_mask() - mk_mask().max()).max() < 1e-6, "...so it changes nothing yet")
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.color = (0.0, 0.0, 0.0)
    GIZMO["mk_before"] = LY.composite(m, 'BASE_COLOR', 128).copy()
    GIZMO["mk_paint_before"] = px(paint.image).copy()
    GIZMO["mk_layer_pixels"] = {i.name: px(i).copy() for i in LY.stack_images(m) if i != paint.image}
    GIZMO["mk_depsgraph"] = []
    bpy.app.handlers.depsgraph_update_post.append(mk_probe)
    event('MOUSEMOVE', xy=GIZMO["stroke"][0])


def mk_probe(*args):
    GIZMO["mk_depsgraph"].append([u.id.name for u in args[-1].updates if isinstance(u.id, bpy.types.Image)])


@step
def mk_stroke_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["stroke"][0])
    for xy in GIZMO["stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def mk_stroke_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["stroke"][-1])


@step
def mk_stroke_check():
    m = lay_mat()
    layer = mk_layer()
    paint = layer.mask_stack[3]
    now = px(paint.image)
    check(now[:, :3].min() < 0.3 and np.abs(now - GIZMO["mk_paint_before"]).max() > 0.5, "the stroke painted the Paint effect black (min %.3f)" % now[:, :3].min())
    check(all(np.array_equal(px(i), GIZMO["mk_layer_pixels"][i.name]) for i in LY.stack_images(m) if i.name in GIZMO["mk_layer_pixels"])
          and not [i for i in LY.stack_images(m) if i.name not in GIZMO["mk_layer_pixels"] and i != paint.image],
          "...and no other layer, mask or map image")
    after = LY.composite(m, 'BASE_COLOR', 128)
    mask = mk_mask()
    changed = np.abs(after - GIZMO["mk_before"]).max(axis=-1) > 1e-4
    check(changed.any() and changed.mean() < 0.5, "the result changes only where the stroke went (%.1f%% of the texels)" % (100 * changed.mean()))
    hidden = mask < 1e-3
    check(hidden.any() and np.abs(after - GIZMO["mk_base"])[hidden].max() < 1e-3, "where the mask is black the layer is gone: the base shows")
    check((mask[~changed] > 0.99).all(), "...and the rest still shows the layer")
    check(bpy.app.handlers.depsgraph_update_post.count(mk_probe) == 1, "probe")
    bpy.app.handlers.depsgraph_update_post.remove(mk_probe)
    print("depsgraph updates with an Image during the stroke:", sum(1 for u in GIZMO["mk_depsgraph"] if u))
    check(not tracebacks(), "Python error during the stroke on a Paint effect")
    GIZMO["mk_stroked"] = (after.copy(), mask.copy())
    press_ok("m3d.mask_effect_move", _area=tex_areas()[1], delta=-1)


@step
def mk_order_check():
    layer = mk_layer()
    check([e.kind for e in layer.mask_stack] == ['FILL', 'EDGES', 'PAINT', 'LEVELS'] and layer.mask_index == 2,
          "Move Down put the Paint effect below Levels: %s" % [e.kind for e in layer.mask_stack])
    after, before = LY.composite(lay_mat(), 'BASE_COLOR', 128), GIZMO["mk_stroked"][0]
    mask = mk_mask()
    stroke = GIZMO["mk_stroked"][1] < 1e-3
    check(stroke.any() and np.abs(mask[stroke] - 0.5).max() < 2e-3, "now Levels lifts the stroke to 0.5 (%.3f)" % mask[stroke].mean())
    check(np.abs(after - before)[stroke].max() > 0.05, "the order changes the result under the stroke")
    m = lay_mat()
    check(m.texture_paint_images[m.paint_active_slot] == layer.mask_stack[2].image, "the brush stays on the Paint effect")
    top = LY.mask_top(m.node_tree, layer)
    check(top is not None and top.node == LY.mask_node(m.node_tree, layer, "mix", layer.mask_stack[3]), "the nodes follow the order (Levels is on top)")
    GIZMO["mk_state"] = mk_state(m)
    m.m3d_show_mask = True
    for a in window().screen.areas:
        a.tag_redraw()


@step
def mk_show_check():
    m = lay_mat()
    emit = m.node_tree.nodes.get(LY.MASKVIEW)
    out = next(n for n in m.node_tree.nodes if n.type == 'OUTPUT_MATERIAL')
    check(emit is not None and out.inputs["Surface"].links[0].from_node == emit
          and emit.inputs["Color"].links[0].from_socket == LY.mask_top(m.node_tree, mk_layer()), "Show Mask on: the viewport shows the layer's mask")
    check(not tracebacks(), "Python error with Show Mask on")
    m.m3d_show_mask = False
    for a in window().screen.areas:
        a.tag_redraw()


@step
def mk_show_off_check():
    m = lay_mat()
    check(mk_state(m) == GIZMO["mk_state"] and LY.MASKVIEW not in m.node_tree.nodes, "Show Mask off: the material is exactly as it was")
    paint_name = mk_layer().mask_stack[2].image.name
    GIZMO["mk_paint_name"] = paint_name
    press_ok("m3d.mask_effect_remove", _area=tex_areas()[1])


@step
def mk_remove_check():
    layer = mk_layer()
    check([e.kind for e in layer.mask_stack] == ['FILL', 'EDGES', 'LEVELS'] and GIZMO["mk_paint_name"] not in bpy.data.images
          and layer.paint_mask and LY.target_image(bpy.context, lay_mat(), False) is None,
          "Remove deleted the Paint effect and its image (the mask stays selected, with nothing to paint): %s" % [e.kind for e in layer.mask_stack])
    check(bpy.data.images["Crate_Curvature"].get("m3d_stamp") == GIZMO["mk_stamp"], "the baked map was kept, not baked again")
    check(not tracebacks(), "Python error in the mask effect tests")
    lay_show_tab()
    mk_menu()


@step
def mk_key_paint2():
    mk_key('P')


step(wait_until(lambda: len(mk_layer().mask_stack) >= 4, "a second Paint effect (P key)"))


@step
def mk_add_blur():
    press_ok("m3d.mask_effect_add", _area=tex_areas()[1], kind='BLUR')   # (B in the menu belongs to Paint (Black))


step(wait_until(lambda: len(mk_layer().mask_stack) >= 5, "Blur from the Add menu (B key)"))


@step
def mk_blur_setup():
    layer = mk_layer()
    check([e.kind for e in layer.mask_stack] == ['FILL', 'EDGES', 'LEVELS', 'PAINT', 'BLUR'] and layer.mask_index == 4,
          "P and B added a Paint effect and a Blur filter: %s" % [e.kind for e in layer.mask_stack])
    blur = layer.mask_stack[4]
    check(blur.image is not None and blur.image.is_float and blur.image.get("m3d_fp"), "the Blur effect has its cache image")
    m = lay_mat()
    check(m.texture_paint_images[m.paint_active_slot] == layer.mask_stack[3].image, "the brush is on the Paint effect below the Blur")
    GIZMO["mk_cache"] = px(blur.image).copy()
    GIZMO["mk_stroke2"] = [(x, y + 25) for x, y in GIZMO["stroke"]]
    event('MOUSEMOVE', xy=GIZMO["mk_stroke2"][0])


@step
def mk_blur_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["mk_stroke2"][0])
    for xy in GIZMO["mk_stroke2"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def mk_blur_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["mk_stroke2"][-1])


step(wait_until(lambda: np.abs(px(mk_layer().mask_stack[4].image) - GIZMO["mk_cache"]).max() > 0.01, "the Blur cache to follow the stroke", tries=20))


@step
def mk_blur_check():
    layer = mk_layer()
    paint, blur = layer.mask_stack[3], layer.mask_stack[4]
    check(px(paint.image)[:, :3].min() < 0.3, "the second stroke painted the Paint effect")
    want = MK.blur(MK.stack_value(layer, 128, 4), blur.amount)
    got = px(blur.image).reshape(128, 128, 4)[..., 0]
    check(tuple(blur.image.size) == (128, 128) and np.abs(got - want).max() < 1e-5, "the Blur cache is the blur of the stack below it (error %.6f)" % np.abs(got - want).max())
    check(not tracebacks(), "Python error while the Blur cache followed a stroke")


# ----------------------------------------------------------------------------------------------------
# Phase 7b: layer folders in the Texture workspace: three layers, New Folder, two layers moved in with the dock's operators,
# the folder closed and opened, its opacity, Freeze (fewer nodes, the same look), a real stroke with a frozen layer active (it
# goes to the scratch image), Unfreeze, a stroke on a layer in the folder, Move Out, Move Into Folder from its list, Delete Folder.

from types import SimpleNamespace


def fo_shape(parent=""):
    return " ".join(l.name + ("[%s]" % fo_shape(l.uid) if l.kind == 'FOLDER' else "") for l in LY.kids_of(lay_mat(), parent))


def fo_layer(name):
    return next(l for l in lay_mat().m3d_layers if l.name == name)


def fo_select(name):
    m = lay_mat()
    m.m3d_layer_index = next(i for i, l in enumerate(m.m3d_layers) if l.name == name)


def fo_fill(image, rgba):
    w, h = image.size
    LY.write_pixels(image, np.tile(np.array(rgba, np.float32), (w * h, 1)))


def fo_look():
    return LY.composite(lay_mat(), 'BASE_COLOR', 128)


def fo_images():
    return {i.name: px(i).copy() for i in LY.stack_images(lay_mat())}


@step
def fo_setup():
    lay_show_tab()
    m = lay_mat()
    with LY.muted():
        m.m3d_layers.clear()
        m.m3d_layer_index = 0
        m.m3d_channel = 'BASE_COLOR'
        m.m3d_show_mask = False
    LY.rebuild_all(m)
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.color = (1.0, 0.0, 0.0)   # (the earlier tests left the brush on black)
    press_ok("brush.asset_activate", _area=tex_areas()[0], **m3d_texture.brush_props("Paint Soft"))
    for _i in range(3):
        press_ok("m3d.layer_add", _area=tex_areas()[1], kind='PAINT')


@step
def fo_new_folder():
    m = lay_mat()
    check(len(m.m3d_layers) == 3 and all(l.kind == 'PAINT' for l in m.m3d_layers), "three paint layers: %s" % lay_names())

    for layer, name, rgba in zip(m.m3d_layers, "ABC", ((0.8, 0.2, 0.15, 1.0), (0.2, 0.7, 0.3, 0.6), (0.2, 0.3, 0.9, 0.5))):
        layer.name = name
        fo_fill(LY.entry_of(layer, 'BASE_COLOR').image, rgba)
    GIZMO["fo_flat"] = fo_look()
    press_ok("m3d.layer_folder_add", _area=tex_areas()[1])


@step
def fo_move_in():
    m = lay_mat()
    folder = fo_layer("Folder")
    check(fo_shape() == "A B C Folder[]" and folder.kind == 'FOLDER' and LY.active_layer(m).name == "Folder", "New Folder: %s" % fo_shape())
    check(np.abs(fo_look() - GIZMO["fo_flat"]).max() < 1e-6, "an empty folder changes nothing")
    GIZMO["fo_uid"] = folder.uid
    for name in ("B", "C"):
        fo_select(name)
        press_ok("m3d.layer_move_into", _run='EXEC_DEFAULT', _area=tex_areas()[1], folder=GIZMO["fo_uid"])


@step
def fo_moved_check():
    m = lay_mat()
    check(fo_shape() == "A Folder[B C]" and [l.name for l in m.m3d_layers] == ["A", "B", "C", "Folder"], "Move Into Folder twice: %s" % fo_shape())
    check(np.abs(fo_look() - GIZMO["fo_flat"]).max() < 1e-5, "a folder of normal layers looks like the layers on their own")
    check(not tracebacks(), "Python error drawing the Layers tab with a folder")
    GIZMO["fo_live_look"], GIZMO["fo_live_nodes"] = fo_look(), len(m.node_tree.nodes)
    fo_select("C")
    fo_layer("Folder").expanded = False
    for a in window().screen.areas:
        a.tag_redraw()


@step
def fo_collapsed():
    m = lay_mat()
    flags = LY.M3D_UL_layers.filter_items(SimpleNamespace(bitflag_filter_item=1 << 30), None, m, "m3d_layers")[0]
    check(LY.active_layer(m).name == "Folder" and flags == [1 << 30, 0, 0, 1 << 30], "closing the folder hides its layers in the list and selects it (%s)" % flags)
    check(not tracebacks(), "Python error drawing the Layers tab with a closed folder")
    fo_layer("Folder").expanded = True
    for a in window().screen.areas:
        a.tag_redraw()


@step
def fo_opacity():
    m = lay_mat()
    check(fo_layer("Folder").expanded and not tracebacks(), "opening the folder again")
    LY.set_look(fo_layer("Folder"), opacity=0.5)
    opv = m.node_tree.nodes[LY.part('BASE_COLOR', fo_layer("Folder").uid, "opv")]
    check(abs(opv.inputs[1].default_value - 0.5) < 1e-6, "the folder's opacity is on its node")
    a = LY.composite(m, 'BASE_COLOR', 128)
    check(np.abs(a - GIZMO["fo_live_look"]).max() > 0.01, "the folder's opacity changes the look")
    GIZMO["fo_look"], GIZMO["fo_nodes"] = a, len(m.node_tree.nodes)
    fo_select("Folder")
    press_ok("m3d.layer_freeze", _area=tex_areas()[1])


@step
def fo_frozen():
    m = lay_mat()
    folder = fo_layer("Folder")
    check(folder.frozen and LY.entry_of(folder, 'BASE_COLOR').image is not None and LY.active_layer(m).name == "Folder", "Freeze Folder from the dock")
    check(len(m.node_tree.nodes) < GIZMO["fo_nodes"], "the node count dropped (%d -> %d)" % (GIZMO["fo_nodes"], len(m.node_tree.nodes)))
    check(np.abs(fo_look() - GIZMO["fo_look"]).max() < 0.012, "the look is the same (largest difference %.5f)" % np.abs(fo_look() - GIZMO["fo_look"]).max())
    check(not LY.has_content(fo_layer("B"), 'ROUGHNESS') and all(not n.name.startswith("m3d_layer.BASE_COLOR.%s" % fo_layer("B").uid) for n in m.node_tree.nodes),
          "the frozen layers have no nodes")
    check(not tracebacks(), "Python error drawing a frozen folder")
    fo_select("B")


@step
def fo_frozen_aim():
    m = lay_mat()
    now = m.texture_paint_images[m.paint_active_slot]
    check(LY.active_layer(m).name == "B" and LY.in_frozen(LY.active_layer(m)), "a layer in the frozen folder is active")
    check(now.name == LY.SCRATCH and now not in LY.stack_images(m), "the brush is aimed at the scratch image, not at a frozen layer (%s)" % now.name)
    GIZMO["fo_pixels"], GIZMO["fo_scratch"] = fo_images(), px(now).copy()
    event('MOUSEMOVE', xy=GIZMO["stroke"][0])


@step
def fo_frozen_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["stroke"][0])
    for xy in GIZMO["stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def fo_frozen_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["stroke"][-1])


@step
def fo_frozen_stroke_check():
    m = lay_mat()
    images = fo_images()
    check(set(images) == set(GIZMO["fo_pixels"]) and all(np.array_equal(images[n], GIZMO["fo_pixels"][n]) for n in images),
          "a stroke with a frozen layer active changed no layer image (children and frozen images included)")
    scratch = bpy.data.images.get(LY.SCRATCH)
    check(scratch is not None and np.abs(px(scratch) - GIZMO["fo_scratch"]).max() > 0.1, "...the stroke did happen: it went to the scratch image")
    check(np.abs(fo_look() - GIZMO["fo_look"]).max() < 0.012, "...and the look did not change")
    check(not tracebacks(), "Python error during the stroke on a frozen layer")
    press_ok("m3d.layer_unfreeze", _area=tex_areas()[1])


@step
def fo_unfrozen():
    m = lay_mat()
    check(not fo_layer("Folder").frozen and not LY.in_frozen(fo_layer("B")) and len(m.node_tree.nodes) == GIZMO["fo_nodes"],
          "Unfreeze (with a frozen layer active): the folder is live again, the nodes are back (%d)" % len(m.node_tree.nodes))
    check(np.abs(fo_look() - GIZMO["fo_look"]).max() < 1e-6, "...the same look")
    check(not [i for i in bpy.data.images if i.name.endswith("Frozen")], "...the frozen images are gone")
    check(m.texture_paint_images[m.paint_active_slot] == lay_image_of("B"), "the brush is on layer B again")
    GIZMO["fo_pixels"] = fo_images()
    event('MOUSEMOVE', xy=GIZMO["stroke"][0])


def lay_image_of(name):
    return LY.entry_of(fo_layer(name), 'BASE_COLOR').image


@step
def fo_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["stroke"][0])
    for xy in GIZMO["stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def fo_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["stroke"][-1])


@step
def fo_stroke_check():
    images = fo_images()
    b = lay_image_of("B")
    check(np.abs(images[b.name] - GIZMO["fo_pixels"][b.name]).max() > 0.1, "the stroke painted layer B inside the folder")
    check(all(np.array_equal(images[n], GIZMO["fo_pixels"][n]) for n in images if n != b.name), "...and no other image")
    check(np.abs(fo_look() - GIZMO["fo_look"]).max() > 0.01, "...and the look follows it")
    check(not tracebacks(), "Python error during the stroke on a layer in a folder")
    press_ok("m3d.layer_move_out", _area=tex_areas()[1])


@step
def fo_out_check():
    check(fo_shape() == "A Folder[C] B", "Move Out of Folder: %s" % fo_shape())
    dock = tex_areas()[1]   # Move Into Folder from the Layers menu is a search list of the folders: typing a name and Enter picks it.
    region = next(r for r in dock.regions if r.type == 'WINDOW')
    event('MOUSEMOVE', xy=GIZMO["mk_xy"])
    with bpy.context.temp_override(window=window(), screen=window().screen, area=dock, region=region, space_data=dock.spaces.active):
        res = bpy.ops.m3d.layer_move_into('INVOKE_DEFAULT')
    check(res <= {'FINISHED', 'RUNNING_MODAL'}, "Move Into Folder opens its search list (%s)" % res)


@step
def fo_menu_type():
    for key in "FOLD":
        event(key, 'PRESS', GIZMO["mk_xy"], unicode=key.lower())
        event(key, 'RELEASE', GIZMO["mk_xy"])


@step
def fo_menu_key():
    event('RET', 'PRESS', GIZMO["mk_xy"])
    event('RET', 'RELEASE', GIZMO["mk_xy"])


@step
def fo_menu_check():
    if fo_shape() != "A Folder[C B]":   # (the list is still open)
        event('ESC', 'PRESS', GIZMO["mk_xy"])
        event('ESC', 'RELEASE', GIZMO["mk_xy"])
    check(fo_shape() == "A Folder[C B]", "the folder list moved the layer to the top of the folder: %s" % fo_shape())
    check(not tracebacks(), "Python error in the folder list")
    GIZMO["fo_doomed"] = [lay_image_of("B").name, lay_image_of("C").name]
    fo_select("Folder")
    press_ok("m3d.layer_remove", _area=tex_areas()[1])


@step
def fo_delete_check():
    check(fo_shape() == "A", "Delete Folder removed the folder and its layers: %s" % fo_shape())
    check(not [n for n in GIZMO["fo_doomed"] if n in bpy.data.images], "...and their images")
    check(not tracebacks(), "Python error while the folders were edited in the Texture workspace")


# ----------------------------------------------------------------------------------------------------
# Phase 7c: the Library tab in the Texture workspace: thumbnails that fill in over time (a step at a time on a timer), a material
# tile (folder, new look, undo), a mask preset (replace, add on top), Save to Library, Mine, rename, delete, a brush tile and an alpha
# with a real stroke; screenshots of the tab and of a material on a mesh.

import shutil
import time

import m3d_library as LIB


def lb_dock():
    return tex_areas()[1]


def lb_show(category):
    """Open a category of the Assets panel (it is a column of its own: no tab to pick)."""
    bpy.context.scene.m3d_library.category = category
    for a in window().screen.areas:
        a.tag_redraw()


def lb_mat():
    return bpy.context.active_object.active_material


def lb_layer(name):
    return next(l for l in lb_mat().m3d_layers if l.name == name)


def lb_folder(name):
    return next(l for l in lb_mat().m3d_layers if l.name == name and l.kind == 'FOLDER')


def lb_select(layer):
    lb_mat().m3d_layer_index = LY.index_of(lb_mat(), layer.uid)


def lb_look():
    return LY.composite(lb_mat(), 'BASE_COLOR', 64).copy()


def lb_sandbox():
    """The thumbnails, your items and the alphas of this run go to temporary folders (never the real user folder); every step
    of the thumbnail generator is timed. Done once, by the first step: the other phases draw every dock tab, the Library tab
    too, with the thumbnails switched off; `lb_setup` switches them on."""
    if "lb_saved" in GIZMO:
        return
    GIZMO["lb_dir"] = tempfile.mkdtemp(prefix="m3d_lib_gui_")
    GIZMO["lb_alphas"] = tempfile.mkdtemp(prefix="m3d_lib_alphas_")
    GIZMO["lb_saved"] = (LIB.library_dir, LIB.step, m3d_sculpt.alpha_dir)
    LIB.library_dir = lambda create=False: GIZMO["lb_dir"]
    m3d_sculpt.alpha_dir = lambda create=False: GIZMO["lb_alphas"]
    GIZMO["lb_times"] = []
    real_step = LIB.step

    def timed_step():
        t0 = time.time()
        try:
            return real_step()
        finally:
            GIZMO["lb_times"].append(time.time() - t0)
    LIB.step = timed_step
    LIB._user["entries"] = None
    LIB._gen.update(running=False, done=True, stage=None, failed=set(), shipped=False)   # (shipped: the thumbnails that come with the program are not used here: this run makes its own)


@step
def lb_setup():
    lb_sandbox()
    m3d_sculpt.alpha_dir = lambda create=False: GIZMO["lb_alphas"]   # (the Sculpt phase put a folder of its own there)
    if bpy.app.timers.is_registered(LIB._tick):
        bpy.app.timers.unregister(LIB._tick)
    LIB._gen.update(running=False, done=False, stage=None, failed=set(), shipped=False)
    if bpy.context.active_object is None or bpy.context.active_object.type != 'MESH':
        win, area, region = view3d()
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.m3d.add_primitive(kind='CUBE')
    if window().workspace.name != "Texture":
        bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: window().workspace.name == "Texture", "the Texture workspace", tries=20))


@step
def lb_setup_mesh():
    ob = bpy.context.active_object
    if ob.active_material is None:
        press_ok("m3d.tex_add_material", _area=lb_dock())
    if bpy.context.mode != 'PAINT_TEXTURE':
        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    ob.m3d_bake.resolution, ob.m3d_bake.samples, ob.m3d_bake.margin = '128', 4, 4
    bpy.context.scene.m3d_tex.resolution = '128'
    LIB._gen["shipped"] = False   # (these steps make the thumbnails: the ones that come with the program are put back in lb_done)
    LIB.icons().clear()
    check(LIB.pending() and not os.listdir(GIZMO["lb_dir"]), "no thumbnail exists yet")
    check("tex_assets" in {t.page for t in m3d_workspace.DOCK_TABS['TEXTURE']['ASSETS']} and "tex_library" not in {t.id for t in m3d_workspace.DOCK_TABS['TEXTURE']['RIGHT']},
          "the library is the Assets panel, not a tab of the dock")
    lb_show('MATERIALS')


step(wait_until(lambda: LIB._gen["running"], "the Library tab to start making thumbnails", tries=10))


@step
def lb_placeholders():
    with bpy.context.temp_override(window=window(), area=tex_roles()["assets"]):
        check(m3d_workspace.pages_shown(bpy.context) == {"tex_assets"}, "Assets shows the library page")
    check(LIB.pending() or LIB._gen["stage"] is not None, "the thumbnails are still being made: the tiles show placeholders meanwhile")
    check(any(k.startswith("ph:") for k in LIB.icons().keys()), "placeholder icons were drawn")
    check(not tracebacks(), "Python error drawing the Library tab")


step(wait_until(lambda: not LIB.pending() and not LIB._gen["running"], "the thumbnails to be made", tries=140))


@step
def lb_thumbs_check():
    times = GIZMO["lb_times"]
    check(not LIB._gen["failed"], "no thumbnail failed: %s" % LIB._gen["failed"])
    check(all(os.path.isfile(LIB.thumb_path(e)) for e in LIB.entries()), "every starter item has its thumbnail in the user folder")
    check(len(times) >= 28 and max(times) < 3.0, "thumbnails come one small step at a time (%d steps, the longest %.2f s)" % (len(times), max(times)))
    check(bpy.data.scenes.get(LIB.RIG) is None and len(bpy.data.scenes) == 1, "the preview scene is gone")
    check(len([k for k in LIB.icons().keys() if k.startswith("t:")]) >= len([e for e in LIB.STARTERS if LIB.is_plain(e)]),
          "the Materials tiles use the thumbnails")
    print("library thumbnails: %d steps, %.1f s in all, longest step %.2f s" % (len(times), sum(times), max(times)))
    check(not tracebacks(), "Python error while the thumbnails were made")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def lb_shot_tab():
    e_screenshot("F:/AI/m3d_item7c.png")


# --- A material tile: the operator of the button. A folder of fill layers, a new look, one undo step.
@step
def lb_apply_material():
    m = lb_mat()
    GIZMO["lb_before"], GIZMO["lb_layers"] = lb_look(), len(m.m3d_layers)
    res = press_ok("m3d.library_apply", _area=lb_dock(), item="starter:painted_metal")
    check(res == {'RUNNING_MODAL'} and len(lb_mat().m3d_layers) == GIZMO["lb_layers"],
          "the Painted Metal tile asks first: the mesh has no high poly, its maps would come from the mesh itself (%s)" % res)


@step
def lb_apply_confirm():
    ws_event('RET', 'PRESS')   # (Bake from the Mesh)
    ws_event('RET', 'RELEASE')


@step
def lb_material_check():
    m = lb_mat()
    folder = LY.active_layer(m)
    check(folder.name == "Painted Metal" and folder.kind == 'FOLDER' and m.m3d_layers[-1].uid == folder.uid
          and [l.name for l in LY.children(folder)] == ["Bare Metal", "Paint", "Dirt"], "a folder named after the item with its layers: %s" % [l.name for l in m.m3d_layers])
    check([e.kind for e in lb_layer("Paint").mask_stack] == ["EDGES", "NOISE", "INVERT"] and lb_layer("Dirt").mask_stack[0].kind == 'CAVITY', "...the masks use the generators")
    check(np.abs(lb_look() - GIZMO["lb_before"]).max() > 0.01, "the material changed")
    check(all(not MK.missing_maps(l) for l in m.m3d_layers) and LY.rebuild_all(m) is False, "the maps were baked and the nodes are in step")
    check(not tracebacks(), "Python error applying a material")
    press_ok("m3d.dock_page", _area=lb_dock(), tab="tex_layers")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def lb_layers_tab_check():
    check(not tracebacks(), "Python error drawing the Layers tab with the applied folder")
    lb_show('MATERIALS')


# --- Undo and redo of a tile (Object Mode: Texture Paint Mode keeps its own undo steps)
@step
def lb_undo_setup():
    bpy.ops.object.mode_set(mode='OBJECT')
    GIZMO["lb_names"] = [l.name for l in lb_mat().m3d_layers]
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo_push(message="Before the tile")   # (the test's own operator calls push no steps: Undo needs one to go back to)
        bpy.ops.m3d.library_apply('EXEC_DEFAULT', True, item="starter:copper")


@step
def lb_undo():
    check(lb_mat().m3d_layers[-1].name == "Copper" and len(lb_mat().m3d_layers) == len(GIZMO["lb_names"]) + 3, "a second tile: the Copper folder is on top")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo()


@step
def lb_undo_check():
    check([l.name for l in lb_mat().m3d_layers] == GIZMO["lb_names"], "Undo takes the whole folder away in one step: %s" % [l.name for l in lb_mat().m3d_layers])
    check(LY.rebuild_all(lb_mat()) is False and not tracebacks(), "...with the nodes in step")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.redo()


@step
def lb_redo_check():
    check(lb_mat().m3d_layers[-1].name == "Copper" and len(lb_mat().m3d_layers) == len(GIZMO["lb_names"]) + 3, "Redo brings it back")
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    lb_select(lb_folder("Copper"))
    press_ok("m3d.layer_remove", _area=lb_dock())


# --- A mask preset on a layer: replace, then add on top
@step
def lb_mask_setup():
    press_ok("m3d.layer_add", _area=lb_dock(), kind='FILL')
    LY.active_layer(lb_mat()).name = "Target"
    lb_show('SMART_MASKS')
    res = press_ok("m3d.library_apply", _area=lb_dock(), item="starter:edge_wear", mode='REPLACE')
    check(res == {'FINISHED'}, "the Edge Wear tile applies")


@step
def lb_mask_check():
    layer = lb_layer("Target")
    check([e.kind for e in layer.mask_stack] == ["EDGES", "NOISE"] and layer.mask_stack[0].blend == 'MIX', "Edge Wear is the layer's mask: %s" % [e.kind for e in layer.mask_stack])
    check(LY.rebuild_all(lb_mat()) is False and not tracebacks(), "...with the nodes in step")
    press_ok("m3d.library_apply", _area=lb_dock(), item="starter:dirt_in_cavities", mode='ADD')


@step
def lb_mask_add_check():
    layer = lb_layer("Target")
    check([e.kind for e in layer.mask_stack] == ["EDGES", "NOISE", "CAVITY", "NOISE"] and layer.mask_stack[2].blend == 'MULTIPLY',
          "Add on Top: Dirt in Cavities goes above, combined with it: %s" % [e.kind for e in layer.mask_stack])
    press_ok("m3d.library_apply", _area=lb_dock(), item="starter:large_patches", mode='REPLACE')


@step
def lb_mask_replace_check():
    check([e.kind for e in lb_layer("Target").mask_stack] == ["NOISE", "LEVELS"], "Replace: only the new preset is left")
    check(not tracebacks(), "Python error applying mask presets")


# --- Save to Library: the mask of the layer, the folder; they are in Mine and get thumbnails; rename; delete
@step
def lb_save():
    check(press_ok("m3d.library_save", 'EXEC_DEFAULT', _area=lb_dock(), kind='MASK', name="GUI Patches") == {'FINISHED'}, "Save the layer's mask to the library")
    lb_select(lb_folder("Painted Metal"))
    check(press_ok("m3d.library_save", 'EXEC_DEFAULT', _area=lb_dock(), kind='MATERIAL', name="GUI Metal") == {'FINISHED'}, "Save the folder to the library")
    lb_show('MINE')


@step
def lb_mine_check():
    refs = [e.ref for e in LIB.user_entries()]
    check(refs == ["user:gui_metal", "user:gui_patches"], "both are under Mine: %s" % refs)
    check(not LIB._gen["done"], "new items wait for a thumbnail")
    for a in window().screen.areas:
        a.tag_redraw()


step(wait_until(lambda: not LIB.pending() and not LIB._gen["running"], "the thumbnails of your items", tries=80))


@step
def lb_mine_thumbs():
    check(all(os.path.isfile(LIB.thumb_path(e)) for e in LIB.user_entries()), "your items got their thumbnails: %s" % LIB.pending())
    check(not LIB._gen["failed"] and not tracebacks(), "Python error making the thumbnails of your items")
    check(press_ok("m3d.library_rename", 'EXEC_DEFAULT', _area=lb_dock(), item="user:gui_metal", name="Worn Red") == {'FINISHED'}
          and LIB.find_entry("user:gui_metal").item["name"] == "Worn Red", "Rename")
    check(press_ok("m3d.library_apply", _area=lb_dock(), item="user:gui_metal") == {'FINISHED'} and LY.active_layer(lb_mat()).name == "Worn Red",
          "your material applies from Mine (a folder named after it)")
    press_ok("m3d.library_apply", _area=lb_dock(), item="user:gui_patches", mode='ADD')
    for a in window().screen.areas:
        a.tag_redraw()


@step
def lb_delete():
    check(not tracebacks(), "Python error drawing Mine and applying your items")
    for ref in ("user:gui_metal", "user:gui_patches"):
        check(press_ok("m3d.library_delete", 'EXEC_DEFAULT', _area=lb_dock(), item=ref) == {'FINISHED'}, "Delete " + ref)
    check(LIB.user_entries() == [] and os.listdir(os.path.join(GIZMO["lb_dir"], "user")) == [], "your items are gone from the folder")
    for a in window().screen.areas:
        a.tag_redraw()


# --- A brush tile and an alpha: the alpha is the brush's Texture Mask; a real stroke with it paints less than one without
@step
def lb_brush_tile():
    lb_show('BRUSHES')
    check(press_ok("m3d.brush_pick", _area=lb_dock(), identifier=m3d_texture.BRUSH_ASSET + "Paint Hard") == {'FINISHED'}
          and m3d_sculpt.active_brush_id(bpy.context) == m3d_texture.BRUSH_ASSET + "Paint Hard", "a brush tile picks its brush")
    lb_show('ALPHAS')
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.color = (1.0, 0.0, 0.0)
    ups.use_unified_size, ups.size = True, 60
    press_ok("m3d.layer_add", _area=lb_dock(), kind='PAINT')
    LY.active_layer(lb_mat()).name = "Plain"
    press_ok("m3d.tex_channel", _area=lb_dock(), channel='BASE_COLOR')
    view, region = tex_view()
    p = location_3d_to_region_2d(region, view.spaces.active.region_3d, Vector((0, 0, 0)))
    cx, cy = (int(region.x + p.x), int(region.y + p.y)) if p is not None else tex_xy()
    GIZMO["lb_stroke"] = [(cx - 40 + i * 8, cy) for i in range(11)]
    GIZMO["lb_plain"] = px(LY.entry_of(LY.active_layer(lb_mat()), 'BASE_COLOR').image).copy()
    event('MOUSEMOVE', xy=GIZMO["lb_stroke"][0])


@step
def lb_plain_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["lb_stroke"][0])
    for xy in GIZMO["lb_stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def lb_plain_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["lb_stroke"][-1])


@step
def lb_alpha_setup():
    image = LY.entry_of(LY.active_layer(lb_mat()), 'BASE_COLOR').image
    GIZMO["lb_plain_cover"] = float(px(image)[:, 3].sum())
    check(GIZMO["lb_plain_cover"] > 50, "a stroke without an alpha painted (coverage %.0f)" % GIZMO["lb_plain_cover"])
    check(press_ok("m3d.alpha_pick", _area=lb_dock(), name="Clouds") == {'FINISHED'}
          and bpy.context.tool_settings.image_paint.brush.mask_texture.name == "Clouds", "an alpha tile sets the brush's Texture Mask")
    press_ok("m3d.layer_add", _area=lb_dock(), kind='PAINT')
    LY.active_layer(lb_mat()).name = "Stamped"
    press_ok("m3d.tex_channel", _area=lb_dock(), channel='BASE_COLOR')
    event('MOUSEMOVE', xy=GIZMO["lb_stroke"][0])


@step
def lb_alpha_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["lb_stroke"][0])
    for xy in GIZMO["lb_stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def lb_alpha_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["lb_stroke"][-1])


@step
def lb_alpha_check():
    image = LY.entry_of(LY.active_layer(lb_mat()), 'BASE_COLOR').image
    cover = float(px(image)[:, 3].sum())
    check(LY.active_layer(lb_mat()).name == "Stamped" and 0 < cover < 0.85 * GIZMO["lb_plain_cover"],
          "the same stroke with the alpha paints less (coverage %.0f against %.0f without)" % (cover, GIZMO["lb_plain_cover"]))
    check(press_ok("m3d.alpha_pick", _area=lb_dock(), name="") == {'FINISHED'} and bpy.context.tool_settings.image_paint.brush.mask_texture is None, "None clears the alpha")
    check(not tracebacks(), "Python error with the brush and alpha tiles")


# --- A starter material on a mesh with edges and cavities: the screenshot of the result
@step
def lb_monkey():
    win, area, region = view3d()
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    with bpy.context.temp_override(window=win, area=tex_view()[0], region=tex_view()[1]):
        bpy.ops.mesh.primitive_monkey_add()
        bpy.ops.object.shade_smooth()
        bpy.ops.object.modifier_add(type='SUBSURF')
        bpy.context.active_object.modifiers[0].levels = 2
        bpy.ops.object.modifier_apply(modifier="Subdivision")
    press_ok("m3d.tex_unwrap", _area=lb_dock())
    press_ok("m3d.tex_add_material", _area=lb_dock())
    ob = bpy.context.active_object
    ob.m3d_bake.resolution, ob.m3d_bake.samples, ob.m3d_bake.margin = '512', 16, 8
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    lb_show('MATERIALS')
    check(press_ok("m3d.library_apply", _area=lb_dock(), item="starter:painted_metal") == {'RUNNING_MODAL'}, "Painted Metal on Suzanne asks first")
    from mathutils import Euler
    tex_view()[0].spaces.active.region_3d.view_rotation = Euler((math.radians(78), 0.0, math.radians(32))).to_quaternion()   # (from the front, a little from the side and above)
    with bpy.context.temp_override(window=win, area=tex_view()[0], region=tex_view()[1]):
        bpy.ops.view3d.view_all(center=True)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def lb_monkey_confirm():
    ws_event('RET', 'PRESS')   # (Bake from the Mesh)
    ws_event('RET', 'RELEASE')


@step
def lb_monkey_look():
    check(lb_mat().m3d_layers and lb_mat().m3d_layers[-1].name == "Painted Metal", "...and applies when asked")
    check(not tracebacks(), "Python error applying a material to Suzanne")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def lb_shot_applied():
    e_screenshot("F:/AI/m3d_item7c_applied.png")


# ----------------------------------------------------------------------------------------------------
# Phase 3c: the redesigned Texture workspace: the tool strip and the keys 1-6, the Polygon Fill click, the display mode keys in the
# 3D and 2D views, D / L / S / Alt+Q, Ctrl+RMB / Ctrl+LMB / Shift+RMB drags, an Assets tile, the Texture Set List, Bake Mesh Maps and
# Back to Painting, the view layout buttons, the dock strip. (After the Library tests: it needs their temporary library folders.)

def tex3_xy2d():
    area = next(a for a in window().screen.areas if a.type == 'IMAGE_EDITOR')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return region.x + region.width // 2, region.y + region.height // 2


def tex3_space2d():
    return next(a for a in window().screen.areas if a.type == 'IMAGE_EDITOR').spaces.active


def tex3_px(image):
    a = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(a)
    return a.reshape(-1, 4)


def tex3_key(key, xy=None, **mods):
    xy = xy or tex_xy()
    event('MOUSEMOVE', xy=xy)
    event(key, 'PRESS', xy, **mods)
    event(key, 'RELEASE', xy, **mods)


@step
def tex3_setup():
    # A clean scene with a new cube in the Texture workspace (a material, a Base Color and a Roughness slot, two baked maps).
    if window().workspace.name != "Texture":
        bpy.ops.m3d.workspace(kind='TEXTURE')
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
    bpy.context.active_object.name = "Crate3"
    bpy.ops.m3d.tex_add_material()
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    bpy.context.scene.m3d_tex.resolution = '128'
    bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
    bpy.ops.m3d.tex_channel(channel='ROUGHNESS')
    bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
    for label in ("Normal", "AO"):
        image = bpy.data.images.new("Crate3_" + label, 16, 16)
        image["m3d_bake"] = label
    window().workspace.m3d_page_right = "tex_layers"
    bpy.context.scene.m3d_library.category = 'MATERIALS'
    tex_view()[0].spaces.active.shading.type = 'MATERIAL'
    for a in window().screen.areas:
        a.tag_redraw()


step(wait_until(lambda: window().workspace.name == "Texture" and bpy.context.mode == 'PAINT_TEXTURE', "the Texture workspace for the new tests", tries=20))


@step
def tex3_tools():
    strip = tex_roles()["tools"]
    check(not tracebacks(), "Python error drawing the tool strip")
    for tool, brush in (('ERASER', "Erase Hard"), ('SMUDGE', "Smear"), ('CLONE', "Clone"), ('POLYFILL', "Fill"), ('PROJECTION', "Paint Hard"), ('PAINT', None)):
        check(press_ok("m3d.tex_tool", _area=strip, tool=tool) == {'FINISHED'}, "a click on the %s button" % tool)
        check(m3d_texture.tool_of(bpy.context) == tool and (brush is None or m3d_texture.brush_name(bpy.context) == brush),
              "%s: the tool and its brush (%s, %s)" % (tool, m3d_texture.tool_of(bpy.context), m3d_texture.brush_name(bpy.context)))
    check(not bpy.context.object.data.use_paint_mask and not m3d_texture.stencil_on(m3d_texture.image_brush(bpy.context)), "back on Paint: no face masking, no stencil")


def _tool_key_steps():
    for key, tool in (('TWO', 'ERASER'), ('THREE', 'PROJECTION'), ('FOUR', 'POLYFILL'), ('FIVE', 'SMUDGE'), ('SIX', 'CLONE'), ('ONE', 'PAINT')):
        def press(key=key):
            tex3_key(key)

        def verify(key=key, tool=tool):
            check(m3d_texture.tool_of(bpy.context) == tool, "%s did not pick the %s tool (%s)" % (key, tool, m3d_texture.tool_of(bpy.context)))
            check(not tracebacks(), "Python error after %s" % key)
        press.__name__, verify.__name__ = "tex3_press_" + key, "tex3_verify_" + key
        yield press
        yield verify


for _fn in _tool_key_steps():
    step(_fn)


@step
def tex3_keys_2d():
    tex3_key('TWO', tex3_xy2d())   # the tool keys work over the 2D view too


@step
def tex3_keys_2d_check():
    check(m3d_texture.tool_of(bpy.context) == 'ERASER', "2 over the 2D view picked the Eraser (%s)" % m3d_texture.tool_of(bpy.context))
    tex3_key('ONE', tex3_xy2d())


@step
def tex3_keys_2d_check2():
    check(m3d_texture.tool_of(bpy.context) == 'PAINT', "1 over the 2D view picked Paint (%s)" % m3d_texture.tool_of(bpy.context))
    check(not tracebacks(), "Python error in the tool keys over the 2D view")


@step
def tex3_fill_setup():
    ob = bpy.context.active_object
    image = m3d_texture.channel_slots(ob.active_material)['BASE_COLOR'][1]
    GIZMO["fill_image"] = image.name
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.color, ups.secondary_color = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    bpy.context.scene.m3d_tex.fill_mode = 'MESH'
    check(m3d_texture.channel_slots(ob.active_material)['BASE_COLOR'][1] == image and m3d_texture.active_channel(ob.active_material) == 'BASE_COLOR', "Base Color is the paint target")
    GIZMO["fill_before"] = int(((tex3_px(image)[:, 0] > 0.9) & (tex3_px(image)[:, 1] < 0.1)).sum())
    tex3_key('FOUR')


@step
def tex3_fill_click():
    check(m3d_texture.tool_of(bpy.context) == 'POLYFILL', "4 picked Polygon Fill")
    event('MOUSEMOVE', xy=tex_xy())
    event('LEFTMOUSE', 'PRESS', tex_xy())


@step
def tex3_fill_release():
    event('LEFTMOUSE', 'RELEASE', tex_xy())


@step
def tex3_fill_check():
    image = bpy.data.images[GIZMO["fill_image"]]
    red = int(((tex3_px(image)[:, 0] > 0.9) & (tex3_px(image)[:, 1] < 0.1)).sum())
    check(red > GIZMO["fill_before"] + 200, "a click with Polygon Fill (Mesh) filled the mesh's UV area with the brush color (%d red pixels, %d before)" % (red, GIZMO["fill_before"]))
    check(not tracebacks(), "Python error in the Polygon Fill click")
    tex3_key('ONE')


@step
def tex3_views_setup():
    check(m3d_texture.tool_of(bpy.context) == 'PAINT', "1 is the Paint tool again")
    tex3_key('B')


@step
def tex3_view_b():
    check(tex_mode3d() == "MAP:Normal" and tex_mat().m3d_show_map == "Crate3_Normal", "B showed the first mesh map in the 3D view (%s)" % tex_mode3d())
    tex3_key('B')


@step
def tex3_view_b2():
    check(tex_mode3d() == "MAP:AO", "B showed the next mesh map (%s)" % tex_mode3d())
    tex3_key('B', shift=True)


@step
def tex3_view_b3():
    check(tex_mode3d() == "MAP:Normal", "Shift+B went back a map (%s)" % tex_mode3d())
    tex3_key('M')


@step
def tex3_view_m():
    check(tex_mode3d() == 'MATERIAL' and not tex_mat().m3d_show_map and not m3d_texture.channel_view_on(tex_view()[0].spaces.active.shading),
          "M showed the material again (%s)" % tex_mode3d())
    tex3_key('C', tex3_xy2d())   # in the 2D view


@step
def tex3_view_2d():
    space = tex3_space2d()
    check(m3d_texture.view_mode_2d(bpy.context, space) == "CHANNEL:BASE_COLOR" and space.image is not None
          and space.image == m3d_texture.channel_slots(tex_mat())['BASE_COLOR'][1], "C in the 2D view showed the first channel (%s)" % m3d_texture.view_mode_2d(bpy.context, space))
    tex3_key('B', tex3_xy2d())


@step
def tex3_view_2d_map():
    space = tex3_space2d()
    check(m3d_texture.view_mode_2d(bpy.context, space) == "MAP:Normal" and space.ui_mode == 'PAINT' and space.image.name == "Crate3_Normal",
          "B in the 2D view showed a mesh map (%s, %s)" % (m3d_texture.view_mode_2d(bpy.context, space), space.ui_mode))
    tex3_key('M', tex3_xy2d())


@step
def tex3_view_2d_m():
    space = tex3_space2d()
    check(space.ui_mode == 'PAINT' and m3d_texture.view_mode_2d(bpy.context, space) == 'MATERIAL', "M in the 2D view is the material again, in Paint mode (%s)" % space.ui_mode)
    check(not tracebacks(), "Python error in the display mode keys")
    brush = m3d_texture.image_brush(bpy.context)
    GIZMO["lazy"], GIZMO["mirror"] = brush.use_smooth_stroke, bpy.context.active_object.data.use_mirror_x
    tex3_key('D')


@step
def tex3_key_d():
    brush = m3d_texture.image_brush(bpy.context)
    check(brush.use_smooth_stroke != GIZMO["lazy"], "D toggled Lazy Mouse")
    tex3_key('D')
    tex3_key('L')


@step
def tex3_key_l():
    check(bpy.context.active_object.data.use_mirror_x != GIZMO["mirror"], "L toggled Symmetry")
    tex3_key('L')
    tex3_key('S')


@step
def tex3_key_s():
    brush = m3d_texture.image_brush(bpy.context)
    check(m3d_texture.stencil_on(brush) and m3d_texture.tool_of(bpy.context) == 'PROJECTION', "S put the brush texture on a stencil")
    tex3_key('S')


@step
def tex3_key_s2():
    check(not m3d_texture.stencil_on(m3d_texture.image_brush(bpy.context)) and m3d_texture.tool_of(bpy.context) == 'PAINT', "S again took it off")
    tex3_key('Q', alt=True)


@step
def tex3_key_altq():
    check(bpy.context.scene.get("m3d_isolated") is not None, "Alt+Q isolated the texture set")
    tex3_key('Q', alt=True)


@step
def tex3_key_altq2():
    check(bpy.context.scene.get("m3d_isolated") is None, "Alt+Q again showed everything")
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    brush = m3d_texture.image_brush(bpy.context)
    GIZMO["size_owner"] = ups if ups.use_unified_size else brush
    GIZMO["flow_owner"] = ups if ups.use_unified_strength else brush
    GIZMO["size_owner"].size = 40
    brush.hardness = 0.5
    c = tex_xy()
    event('MOUSEMOVE', xy=c)
    event('RIGHTMOUSE', 'PRESS', c, ctrl=True)
    event('MOUSEMOVE', xy=(c[0] + 60, c[1] + 30), ctrl=True)


@step
def tex3_drag_rmb_release():
    c = tex_xy()
    event('RIGHTMOUSE', 'RELEASE', (c[0] + 60, c[1] + 30), ctrl=True)


@step
def tex3_drag_rmb_check():
    brush = m3d_texture.image_brush(bpy.context)
    check(GIZMO["size_owner"].size > 55, "Ctrl+RMB drag to the right made the brush bigger (%s)" % GIZMO["size_owner"].size)
    check(brush.hardness > 0.5, "...and dragging up made it harder (%.2f)" % brush.hardness)
    GIZMO["flow_owner"].strength = 0.3
    c = tex_xy()
    event('MOUSEMOVE', xy=c)
    event('LEFTMOUSE', 'PRESS', c, ctrl=True)
    event('MOUSEMOVE', xy=(c[0] + 90, c[1]), ctrl=True)


@step
def tex3_drag_lmb_release():
    c = tex_xy()
    event('LEFTMOUSE', 'RELEASE', (c[0] + 90, c[1]), ctrl=True)


@step
def tex3_drag_lmb_check():
    check(GIZMO["flow_owner"].strength > 0.45, "Ctrl+LMB drag to the right raised the flow (%.2f)" % GIZMO["flow_owner"].strength)
    GIZMO["flow_owner"].strength = 1.0
    shading = tex_view()[0].spaces.active.shading
    GIZMO["env"] = shading.studiolight_rotate_z
    c = tex_xy()
    event('MOUSEMOVE', xy=c)
    event('RIGHTMOUSE', 'PRESS', c, shift=True)
    event('MOUSEMOVE', xy=(c[0] + 100, c[1]), shift=True)


@step
def tex3_env_release():
    c = tex_xy()
    event('RIGHTMOUSE', 'RELEASE', (c[0] + 100, c[1]), shift=True)


@step
def tex3_env_check():
    shading = tex_view()[0].spaces.active.shading
    check(abs(shading.studiolight_rotate_z - GIZMO["env"]) > 0.1, "Shift+RMB drag turned the environment (%.2f -> %.2f)" % (GIZMO["env"], shading.studiolight_rotate_z))
    check(not tracebacks(), "Python error in the drag keys")
    tex3_key('F')


# --- Assets: a tile applies; Texture Sets; Bake Mesh Maps; layout buttons; the dock strip
@step
def tex3_assets_tile():
    check(not tracebacks(), "Python error after the frame key")
    assets, dock = tex_areas()
    bpy.context.scene.m3d_library.category = 'MATERIALS'
    res = press_ok("m3d.library_apply", _area=assets, item="starter:gold")
    check(res == {'FINISHED'}, "the Gold tile in Assets applies")


@step
def tex3_assets_check():
    mat = tex_mat()
    layer = LY.active_layer(mat)
    check(layer is not None and layer.name.startswith("Gold") and layer.kind == 'FILL' and layer.parent == "", "a Materials tile adds one fill layer: %s" % [l.name for l in mat.m3d_layers])
    check(window().workspace.m3d_page_right == "tex_layers" and not tracebacks(), "the dock shows the Layers; no Python error")
    roles = tex_roles()
    with bpy.context.temp_override(window=window(), area=roles["props"]):
        check(m3d_texture.FILL_PAGE in m3d_workspace.pages_shown(bpy.context), "Properties - Fill shows the fill page (%s)" % sorted(m3d_workspace.pages_shown(bpy.context)))
    check(m3d_texture.props_context(bpy.context) == 'FILL', "the title says Fill")
    press_ok("m3d.tex_set", _area=roles["sets"], object="Crate3", material=tex_mat().name)
    sets = m3d_texture.texture_sets(bpy.context)
    check([(m.name, o.name) for m, o in sets] == [(tex_mat().name, "Crate3")], "the Texture Set List has the mesh's material")
    for tab in ("tex_settings", "tex_layers"):
        press_ok("m3d.dock_page", _area=roles["dock"], tab=tab)
    press_ok("m3d.tex_bake_mode", _area=roles["dock"], on=True)


@step
def tex3_bake_mode():
    check(window().workspace.m3d_page_right == "tex_bake", "Bake Mesh Maps switched the dock to the Bake page")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def tex3_bake_mode_check():
    check(not tracebacks(), "Python error drawing the Bake page")
    press_ok("m3d.tex_bake_mode", _area=tex_roles()["dock"], on=False)


@step
def tex3_back():
    check(window().workspace.m3d_page_right == "tex_layers", "Back to Painting returned to the Layers")
    tex3_key('B', ctrl=True, shift=True)


@step
def tex3_bake_key():
    check(window().workspace.m3d_page_right == "tex_bake", "Ctrl+Shift+B opened the Bake page")
    press_ok("m3d.tex_bake_mode", _area=tex_roles()["dock"], on=False)
    tex3_key('E', ctrl=True, shift=True)


@step
def tex3_export_key():
    check(not tracebacks(), "Python error opening Export Textures with Ctrl+Shift+E")
    check(window().workspace.m3d_page_right == "tex_layers", "the dock is on Layers")
    event('ESC', 'PRESS')   # (closes the Export popover)
    event('ESC', 'RELEASE')


TEX3 = {}


def tex3_views():
    """(x, width) of the 3D view and of the 2D view."""
    view, image = m3d_texture.view_areas(window().screen)
    return [(a.x, a.width) if a is not None else None for a in (view, image)]


@step
def tex3_layout_buttons():
    check(m3d_texture.layout_mode(bpy.context) == 'BOTH', "both views are shown")
    TEX3["views"], TEX3["props"] = tex3_views(), sorted((a.x, a.y, a.width, a.height) for a in props_areas())
    TEX3["v3d"] = m3d_texture.view_areas(window().screen)[0].spaces.active.region_3d.view_matrix.copy()
    space = m3d_texture.view_areas(window().screen)[1].spaces.active
    TEX3["2d"] = (space.ui_mode, space.image)
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_layout('INVOKE_DEFAULT', mode='3D') == {'FINISHED'}, "3D Only")


def tex3_panels_kept(what):
    check(sorted((a.x, a.y, a.width, a.height) for a in props_areas()) == TEX3["props"] and not window().screen.show_fullscreen,
          "%s: the panels stay where they were (tool strip, Assets, Texture Sets, Layers, Properties, dock strip)" % what)


@step
def tex3_layout_3d():
    kinds = {a.type for a in window().screen.areas}
    check('VIEW_3D' in kinds and 'IMAGE_EDITOR' not in kinds and m3d_texture.layout_mode(bpy.context) == '3D', "3D Only: the 2D view is gone (%s)" % sorted(kinds))
    tex3_panels_kept("3D Only")
    view = m3d_texture.view_areas(window().screen)[0]
    check(view.x == min(x for x, _w in TEX3["views"]) and view.width >= sum(w for _x, w in TEX3["views"]), "...and the 3D view has the space of both")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_layout('INVOKE_DEFAULT', mode='2D') == {'FINISHED'}, "2D Only")


@step
def tex3_layout_2d():
    kinds = {a.type for a in window().screen.areas}
    check('IMAGE_EDITOR' in kinds and 'VIEW_3D' not in kinds and m3d_texture.layout_mode(bpy.context) == '2D', "2D Only: the 3D view is gone (%s)" % sorted(kinds))
    tex3_panels_kept("2D Only")
    image = m3d_texture.view_areas(window().screen)[1]
    space = image.spaces.active
    check(any(sp.type == 'VIEW_3D' for sp in image.spaces) and window().workspace.get("m3d_split") is not None,
          "...the 3D view waits in the area (and the workspace keeps where the edge was): both are saved with the file")
    got = (space.show_region_toolbar, space.show_region_ui, space.show_region_tool_header, space.show_region_asset_shelf)
    check(not any(got) and (space.ui_mode, space.image) == TEX3["2d"], "...the 2D view is set up as in the startup layout and shows what it showed: %s %s" % (got, (space.ui_mode, space.image)))
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_layout('INVOKE_DEFAULT', mode='BOTH') == {'FINISHED'}, "3D | 2D")


@step
def tex3_layout_both():
    check(m3d_texture.layout_mode(bpy.context) == 'BOTH' and len(props_areas()) == 6, "3D | 2D: both views and the six editors are back")
    got = tex3_views()
    check(all(abs(a - b) <= 2 for (x0, w0), (x1, w1) in zip(TEX3["views"], got) for a, b in ((x0, x1), (w0, w1))),
          "...the 3D view on the left and the 2D view on the right, the edge where it was: %s, before %s" % (got, TEX3["views"]))
    tex3_panels_kept("3D | 2D")
    view = m3d_texture.view_areas(window().screen)[0]
    check(all(abs(a - b) < 1e-4 for ra, rb in zip(view.spaces.active.region_3d.view_matrix, TEX3["v3d"]) for a, b in zip(ra, rb)),
          "...the 3D view looks at the model as before")
    check(not tracebacks(), "Python error switching the view layout")
    tex3_ctrl_space(m3d_texture.view_areas(window().screen)[1])


def tex3_ctrl_space(area):
    """Ctrl+Space over the middle of `area` (event() needs a 3D view: 2D Only has none)."""
    x, y = area.x + area.width // 2, area.y + area.height // 2
    window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    window().event_simulate(type='SPACE', value='PRESS', x=x, y=y, ctrl=True)
    window().event_simulate(type='SPACE', value='RELEASE', x=x, y=y, ctrl=True)


@step
def tex3_layout_key():
    check(m3d_texture.layout_mode(bpy.context) == '2D', "Ctrl+Space over the 2D view: the 2D view alone (%s)" % m3d_texture.layout_mode(bpy.context))
    tex3_panels_kept("Ctrl+Space")
    tex3_ctrl_space(m3d_texture.view_areas(window().screen)[1])


@step
def tex3_layout_key_back():
    check(m3d_texture.layout_mode(bpy.context) == 'BOTH' and tex3_views()[0][0] < tex3_views()[1][0], "Ctrl+Space again: both views, 3D on the left")
    space = m3d_texture.view_areas(window().screen)[1].spaces.active
    check((space.ui_mode, space.image) == TEX3["2d"], "...the 2D view shows what it showed, in the same mode: %s" % ((space.ui_mode, space.image),))
    check(not tracebacks(), "Python error with Ctrl+Space")


@step
def tex3_old_layout():
    # A Texture workspace saved with the old layout (Workspace.m3d_layout 0) keeps drawing, with its old tabs.
    ws = window().workspace
    ws.m3d_layout = 0
    for a in window().screen.areas:
        a.tag_redraw()


@step
def tex3_old_layout_check():
    check(not tracebacks(), "Python error with a Texture workspace of the old layout")
    window().workspace.m3d_layout = 1
    for a in window().screen.areas:
        a.tag_redraw()


# ----------------------------------------------------------------------------------------------------
# Phase 3d: Properties in the real window: the sections of each context and tool, an alpha picked in the Alpha section that changes a
# stroke, a fill layer's UV transform that changes the 3D view, the 2D view framing its image (F4, F, another size).

TEX4 = {}
TEX4_PP = "PROPERTIES_PT_m3d_tx_"


def tex4_redraw():
    for a in window().screen.areas:
        a.tag_redraw()


def tex4_sections():
    """The sections the Properties editor draws now: each panel's poll, asked in that editor."""
    area = tex_roles()["props"]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
        return {c.__name__[len(TEX4_PP):] for c in m3d_texture.classes if hasattr(c, "page") and hasattr(c, "poll") and c.poll(bpy.context)}


def tex4_dock():
    return tex_roles()["dock"]


def tex4_2d():
    area = next(a for a in window().screen.areas if a.type == 'IMAGE_EDITOR')
    return area, next(r for r in area.regions if r.type == 'WINDOW'), area.spaces.active


def tex4_fit():
    """How much of its 2D view the image fills (the larger of the two ratios): near 1 when it is framed."""
    _area, region, space = tex4_2d()
    if space.image is None or region.width < 100:
        return 0.0
    x0, y0 = region.view2d.view_to_region(0.0, 0.0, clip=False)   # (the image is 0..1 in the view)
    x1, y1 = region.view2d.view_to_region(1.0, 1.0, clip=False)
    return max(abs(x1 - x0) / region.width, abs(y1 - y0) / region.height)


def tex4_view_pixels():
    """The 3D view as drawn: its pixels (rgb, one row after the other)."""
    view, region = tex_view()
    path = os.path.join(tempfile.gettempdir(), "m3d_tex4_view.png")
    with bpy.context.temp_override(window=window(), screen=window().screen, area=view, region=region):
        bpy.ops.screen.screenshot_area(filepath=path)
    image = bpy.data.images.load(path)
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    size = tuple(image.size)
    bpy.data.images.remove(image)
    if os.environ.get("M3D_GUI_DUMP"):   # (looking at what the test sees)
        TEX4["dumps"] = TEX4.get("dumps", 0) + 1
        import shutil
        shutil.copy(path, os.path.join(os.environ["M3D_GUI_DUMP"], "view_%02d.png" % TEX4["dumps"]))
    return px.reshape(-1, 4)[:, :3].copy()


def tex4_changed(a, b):
    """The share of the pixels that differ visibly between two looks of the 3D view."""
    return float((np.abs(a - b).max(axis=1) > 0.04).mean())


def tex4_settled(base):
    """True when the 3D view differs from `base` and has stopped changing (two looks in a row are the same)."""
    now = tex4_view_pixels()
    before, TEX4["look"] = TEX4.get("look"), now
    return before is not None and before.shape == now.shape and tex4_changed(now, base) > 0.02 and tex4_changed(now, before) < 0.0005


@step
def tex4_enter():
    lb_sandbox()   # (alphas and thumbnails of this run in temporary folders: a no-op when the Library tests made them)
    if window().workspace.name != "Texture":
        bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: window().workspace.name == "Texture" and len([a for a in window().screen.areas if a.type == 'IMAGE_EDITOR']) == 1, "the Texture workspace for the Properties tests", tries=20))


@step
def tex4_setup():
    # A clean scene: a cube with a material and a Paint Layer, the Paint tool, Properties on Auto.
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
    bpy.context.active_object.name = "Props4"
    view, region = tex_view()
    with bpy.context.temp_override(window=win, area=view, region=region):
        bpy.ops.view3d.view_all(center=True)   # (the cube fills the view: a change of the texture is a large change of the picture)
    bpy.ops.m3d.tex_add_material()
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    bpy.context.scene.m3d_tex.resolution = '128'
    window().workspace.m3d_page_right = "tex_layers"
    press_ok("m3d.layer_add", _area=tex4_dock(), kind='PAINT')
    press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool='PAINT')
    tex4_redraw()


step(wait_until(lambda: bpy.context.mode == 'PAINT_TEXTURE' and tex4_2d()[2].image is not None, "the paint view to show the layer's image", tries=20))


@step
def tex4_ctx_paint():
    check(m3d_texture.props_context(bpy.context) == 'PAINT' and window().workspace.m3d_layout == 1, "a Paint Layer: Properties - Paint")
    check(tex4_sections() == {"pp_preview", "pp_brush", "pp_alpha", "pp_stencil", "pp_material", "pp_more", "layer_props"},
          "Properties - Paint with the Paint tool shows previews, Brush, Alpha, Stencil, Material and the More Settings button: %s" % sorted(tex4_sections()))
    bpy.context.scene.m3d_tex.props_more = True
    check(tex4_sections() == {"pp_preview", "pp_brush", "pp_alpha", "pp_stencil", "pp_material", "pp_advanced", "pp_cursor", "pp_more", "layer_props"},
          "...More Settings adds Advanced and Cursor: %s" % sorted(tex4_sections()))
    bpy.context.scene.m3d_tex.props_more = False
    check(not tracebacks(), "Python error drawing Properties - Paint")


def _tex4_tool_steps():
    sections = {
        'ERASER': {"pp_preview", "pp_brush", "pp_alpha", "pp_stencil", "pp_material", "pp_more"},
        'PROJECTION': {"pp_preview", "pp_projection", "pp_brush", "pp_material", "pp_more"},
        'POLYFILL': {"pp_preview", "pp_polyfill", "pp_material"},
        'SMUDGE': {"pp_preview", "pp_brush", "pp_more"},
        'CLONE': {"pp_preview", "pp_brush", "pp_clone", "pp_more"},
        'PAINT': {"pp_preview", "pp_brush", "pp_alpha", "pp_stencil", "pp_material", "pp_more"},
    }
    for tool, want in sections.items():
        def pick(tool=tool):
            press_ok("m3d.tex_tool", _area=tex_roles()["tools"], tool=tool)
            tex4_redraw()

        def verify(tool=tool, want=want):
            check(m3d_texture.tool_of(bpy.context) == tool and tex4_sections() == want | {"layer_props"},
                  "Properties - Paint, %s tool: %s (want %s)" % (tool, sorted(tex4_sections()), sorted(want)))
            check(not tracebacks(), "Python error drawing Properties - Paint with the %s tool and its toolbar" % tool)
        pick.__name__, verify.__name__ = "tex4_tool_" + tool.lower(), "tex4_tool_check_" + tool.lower()
        yield pick
        yield verify


for _fn in _tex4_tool_steps():
    step(_fn)


# --- An alpha picked in the Alpha section changes a stroke
def tex4_coverage():
    image = LY.entry_of(LY.active_layer(tex_mat()), 'BASE_COLOR').image
    return int((tex3_px(image)[:, 3] > 0.5).sum())


@step
def tex4_stroke_plain_setup():
    ups = bpy.context.tool_settings.image_paint.unified_paint_settings
    ups.use_unified_size = ups.use_unified_strength = True
    ups.size, ups.strength, ups.color = 70, 1.0, (0.9, 0.2, 0.1)
    brush = m3d_texture.image_brush(bpy.context)
    brush.hardness = 1.0
    brush.mask_texture = None
    TEX4["points"] = mc_points(-70, 70, n=24)
    event('MOUSEMOVE', xy=TEX4["points"][0])
    mc_press(TEX4["points"])


@step
def tex4_stroke_plain_release():
    mc_release(TEX4["points"])


@step
def tex4_stroke_plain_check():
    TEX4["plain"] = tex4_coverage()
    check(TEX4["plain"] > 300, "a plain stroke paints a good many texels (%d)" % TEX4["plain"])
    press_ok("m3d.layer_add", _area=tex4_dock(), kind='PAINT')
    brush = m3d_texture.image_brush(bpy.context)
    props = tex_roles()["props"]
    check(press_ok("m3d.alpha_pick", _area=props, name="Dots") == {'FINISHED'} and brush.mask_texture is not None and brush.mask_texture.name == "Dots",
          "a tile of the Alpha section (run in the Properties editor) gives the brush the Dots alpha")
    tex4_redraw()


@step
def tex4_stroke_alpha_press():
    event('MOUSEMOVE', xy=TEX4["points"][0])
    mc_press(TEX4["points"])


@step
def tex4_stroke_alpha_release():
    mc_release(TEX4["points"])


@step
def tex4_stroke_alpha_check():
    dots = tex4_coverage()
    check(0 < dots < 0.8 * TEX4["plain"], "the same stroke with the Dots alpha paints fewer texels, in its pattern (%d, plain %d)" % (dots, TEX4["plain"]))
    check(press_ok("m3d.alpha_pick", _area=tex_roles()["props"], name="") == {'FINISHED'} and m3d_texture.image_brush(bpy.context).mask_texture is None, "None takes the alpha off")
    check(not tracebacks(), "Python error in the alpha stroke")


# --- Properties - Fill, Folder and Mask in the window
@step
def tex4_fill_add():
    press_ok("m3d.layer_add", _area=tex4_dock(), kind='FILL')
    tex4_redraw()


@step
def tex4_ctx_fill():
    check(m3d_texture.props_context(bpy.context) == 'FILL' and tex4_sections() == {"fl_fill", "fl_material", "layer_props"},
          "a Fill Layer: Properties - Fill with Fill, Material and Layer Settings (%s)" % sorted(tex4_sections()))
    check(not tracebacks(), "Python error drawing Properties - Fill and its toolbar")
    # the toolbar follows: the UV transform instead of the brush (the operators it draws run too)
    layer = LY.active_layer(tex_mat())
    layer.uv_tiling = (3.0, 2.0)
    check(press_ok("m3d.layer_fill_reset", _area=tex_roles()["props"]) == {'FINISHED'} and tuple(layer.uv_tiling) == (1.0, 1.0), "Reset in Properties - Fill puts the transform back")
    # a texture with strong structure, for the 3D view
    image = bpy.data.images.new("Tex4Checker", 64, 64, alpha=False)
    ys, xs = np.mgrid[0:64, 0:64]
    px4 = np.ones((64, 64, 4), np.float32)
    px4[..., :3] = (((xs // 8 + ys // 8) % 2)[..., None] * np.array((0.9, 0.9, 0.2), np.float32)) + 0.05
    LY.write_pixels(image, px4)
    TEX4["base"] = tex4_view_pixels()
    TEX4["look"] = None
    LY.entry_of(layer, 'BASE_COLOR').texture = image   # (what picking it in the texture slot of Material does)
    tex4_redraw()


step(wait_until(lambda: tex4_settled(TEX4["base"]), "the 3D view to show the texture of the fill layer", tries=25))


@step
def tex4_fill_transform():
    layer = LY.active_layer(tex_mat())
    check(tex_mat().node_tree.nodes.get(LY.part('BASE_COLOR', layer.uid, "map")) is not None, "the fill's texture has its Mapping node in the material")
    TEX4["view0"] = TEX4["look"].copy()
    TEX4["look"] = None
    layer.uv_tiling = (6.0, 6.0)   # (the Tiling field of Properties - Fill)
    layer.uv_rotation = 0.6
    tex4_redraw()


step(wait_until(lambda: tex4_settled(TEX4["view0"]), "the 3D view to show the new tiling and rotation", tries=25))


@step
def tex4_fill_transform_check():
    check(tex4_changed(TEX4["look"], TEX4["view0"]) > 0.02, "Tiling and Rotation of the fill change what the 3D view shows (%.4f of the pixels)" % tex4_changed(TEX4["look"], TEX4["view0"]))
    check(not tracebacks(), "Python error changing the fill's UV transform")
    layer = LY.active_layer(tex_mat())
    layer.uv_tiling, layer.uv_rotation = (1.0, 1.0), 0.0


@step
def tex4_folder_add():
    press_ok("m3d.layer_folder_add", _area=tex4_dock())
    tex4_redraw()


@step
def tex4_ctx_folder():
    check(m3d_texture.props_context(bpy.context) == 'FOLDER' and tex4_sections() == {"fd_folder"},
          "a Folder: Properties - Folder (%s)" % sorted(tex4_sections()))
    check(not tracebacks(), "Python error drawing Properties - Folder")
    press_ok("m3d.layer_mask_add", _area=tex_roles()["props"], fill='WHITE')
    check(m3d_texture.props_context(bpy.context) == 'MASK', "(a mask is selected when it is made: Properties - Mask)")
    LY.active_layer(tex_mat()).paint_mask = False   # (the folder's content again)
    tex4_redraw()


@step
def tex4_ctx_folder_mask():
    check(tex4_sections() == {"fd_folder"}, "...the folder's content selected: the folder alone (its mask thumbnail shows the mask): %s" % sorted(tex4_sections()))
    check(not tracebacks(), "Python error drawing the folder's mask")
    press_ok("m3d.layer_add", _area=tex4_dock(), kind='PAINT')
    press_ok("m3d.layer_mask_add", _area=tex_roles()["props"], fill='WHITE')
    for kind in ('NOISE', 'LEVELS'):
        press_ok("m3d.mask_effect_add", _area=tex_roles()["props"], kind=kind)
    tex4_redraw()


@step
def tex4_ctx_mask():
    layer = LY.active_layer(tex_mat())
    check(m3d_texture.props_context(bpy.context) == 'MASK' and {"mk_stack", "mk_effect", "pp_brush"} <= tex4_sections() and layer.mask_stack[layer.mask_index].kind == 'LEVELS',
          "a new effect selects the mask: Properties - Mask with the stack, the selected effect and the brush (%s)" % sorted(tex4_sections()))
    check(not tracebacks(), "Python error drawing Properties - Mask")
    layer.mask_index = next(i for i, e in enumerate(layer.mask_stack) if e.kind == 'NOISE')
    tex4_redraw()


@step
def tex4_ctx_generator():
    check(not tracebacks(), "Python error drawing a generator's properties")
    layer = LY.active_layer(tex_mat())
    layer.paint_mask = True
    tex4_redraw()


@step
def tex4_ctx_mask_paint():
    check(tex4_sections() == {"mk_stack", "mk_effect", "pp_preview", "pp_brush", "pp_alpha", "pp_stencil", "pp_gray", "pp_more"},
          "painting the mask: the Paint sections follow the mask's, with the grays (%s)" % sorted(tex4_sections()))
    check(not tracebacks(), "Python error drawing Properties - Mask while the mask is painted")
    LY.active_layer(tex_mat()).paint_mask = False
    tex4_redraw()


# --- The 2D view frames its image: F4, F, another size, another layout (a view takes a redraw to show its new zoom: each check waits)
def tex4_framed():
    return 0.8 < tex4_fit() < 1.02


def tex4_zoom_out():
    area, region, _space = tex4_2d()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
        bpy.ops.image.view_zoom_ratio(ratio=0.1)   # (zoomed far out: a small square in a big empty area)


step(wait_until(lambda: tex4_framed(), "the 2D view to frame the image of the layer", tries=20))


@step
def tex4_fit_zoom_out():
    check(not tracebacks(), "Python error framing the image")
    tex4_zoom_out()


step(wait_until(lambda: tex4_fit() < 0.3, "the 2D view to zoom out", tries=15))


@step
def tex4_fit_leave():
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: window().workspace.name == "Modeling", "the Modeling workspace", tries=15))


@step
def tex4_fit_wait():
    pass   # (the timer notices that the Texture workspace was left)


@step
def tex4_fit_f4():
    bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: window().workspace.name == "Texture" and bpy.context.mode == 'PAINT_TEXTURE' and tex4_framed(), "F4 to frame the image in the 2D view", tries=25))


@step
def tex4_fit_f4_check():
    check(tex4_framed(), "opening the Texture workspace (F4) frames the image in the 2D view (%.2f)" % tex4_fit())
    tex4_zoom_out()


step(wait_until(lambda: tex4_fit() < 0.3, "the 2D view to zoom out again", tries=15))


@step
def tex4_fit_key():
    tex3_key('F', tex3_xy2d())   # F over the 2D view


step(wait_until(lambda: tex4_framed(), "F over the 2D view to frame the whole image", tries=15))


@step
def tex4_fit_key_check():
    check(not tracebacks(), "Python error in the 2D fit")
    TEX4["size"] = tuple(tex4_2d()[2].image.size)
    bpy.context.scene.m3d_tex.resolution = '256'
    press_ok("m3d.layer_add", _area=tex4_dock(), kind='PAINT')
    tex4_redraw()


step(wait_until(lambda: tex4_2d()[2].image is not None and tuple(tex4_2d()[2].image.size) == (256, 256) and tex4_framed(),
                "the 2D view to show the 256 px image, framed", tries=25))


@step
def tex4_fit_size():
    check(TEX4["size"] == (128, 128), "(the image was 128 px, now 256: the view framed it, %.2f)" % tex4_fit())
    bpy.context.scene.m3d_tex.resolution = '128'
    tex4_zoom_out()


step(wait_until(lambda: tex4_fit() < 0.3, "the 2D view to zoom out before the layout change", tries=15))


@step
def tex4_layout_2d():
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_layout('INVOKE_DEFAULT', mode='2D') == {'FINISHED'}, "2D Only")


step(wait_until(lambda: m3d_texture.layout_mode(bpy.context) == '2D' and tex4_framed(), "2D Only to frame the image in the bigger view", tries=25))


@step
def tex4_layout_back():
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.tex_layout('INVOKE_DEFAULT', mode='BOTH') == {'FINISHED'}, "3D | 2D")


step(wait_until(lambda: m3d_texture.layout_mode(bpy.context) == 'BOTH' and tex4_framed(), "3D | 2D to frame the image again", tries=25))


@step
def tex4_done():
    check(not tracebacks(), "Python error in the Properties tests")
    check(window().workspace.m3d_layout == 1, "the Texture workspace is still the new layout")
    for image in [i for i in bpy.data.images if i.name.startswith("Tex4")]:
        bpy.data.images.remove(image)


# ----------------------------------------------------------------------------------------------------
# Phase 3e: the layer stack like the reference, in the real window: the rows draw with thumbnails, the channel dropdown (a click, then
# the key of the channel) changes the blend modes the rows show, a click on a mask thumbnail selects the mask (Alt+click shows it, Shift+click switches it
# off), the right-click menu opens on the layer under the pointer, Ctrl+D / C / V and Delete over the stack. Buttons are found by
# hovering the window and asking Blender what is under the pointer (the key F19 runs a probe that reads the Python command or the
# data path of the active button).

S3E = {"probes": {}, "expected": 0, "looks": [], "menu": []}


class M3D_OT_test_probe(bpy.types.Operator):
    """Test only: what is the button under the pointer (its Python command, or its data path)."""
    bl_idname = "m3d.test_probe"
    bl_label = "Test Probe"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        wm = context.window_manager
        old, text = wm.clipboard, ""
        try:
            for op in (lambda: bpy.ops.ui.copy_python_command_button(), lambda: bpy.ops.ui.copy_data_path_button(full_path=True)):
                wm.clipboard = ""
                try:
                    op()
                except RuntimeError:
                    continue
                text = wm.clipboard
                if text:
                    break
        finally:
            wm.clipboard = old
        S3E["probes"][(event.mouse_x, event.mouse_y)] = text
        return {'PASS_THROUGH'}


def s3e_region():
    area = tex4_dock()
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def s3e_scan(points):
    S3E["probes"], S3E["expected"] = {}, len(points)
    for xy in points:
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        event('MOUSEMOVE', xy=xy)
        event('F19', 'PRESS', xy)
        event('F19', 'RELEASE', xy)


def s3e_scanned():
    return len(S3E["probes"]) >= S3E["expected"]


def s3e_hits(pattern):
    """The scanned points whose probe text matches `pattern` (a regular expression)."""
    import re
    return [xy for xy, text in S3E["probes"].items() if re.search(pattern, text)]


def s3e_center(points):
    return (sum(p[0] for p in points) // len(points), sum(p[1] for p in points) // len(points))


def s3e_top_center(points, height):
    """The middle of a button found by scanning down: the pointer keeps the last button for a while over empty space, so the run of
    points is longer than the button at its lower end: the first point (the top) is the edge, `height` pixels (at UI scale 1) the size."""
    scale = bpy.context.preferences.system.ui_scale or 1.0
    return (sum(p[0] for p in points) // len(points), max(p[1] for p in points) - int(height * scale / 2))


def s3e_mat():
    return bpy.context.active_object.active_material


def s3e_layer(name):
    return next(l for l in s3e_mat().m3d_layers if l.name == name)


@step
def s3e_enter():
    restore_window()
    lb_sandbox()   # (no thumbnails of the Library are made meanwhile)
    if window().workspace.name != "Texture":
        bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: window().workspace.name == "Texture" and len([a for a in window().screen.areas if a.type == 'IMAGE_EDITOR']) == 1
                and len(props_areas()) == 6, "the Texture workspace for the layer stack tests", tries=30))


@step
def s3e_setup():
    # A cube with three layers: a paint layer with a painted mask, a fill with a generator mask, a paint layer.
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
    bpy.context.active_object.name = "Stack3e"
    bpy.ops.m3d.tex_add_material()
    bpy.context.scene.m3d_tex.resolution = '64'
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    for name in ("Paint A", "Fill B", "Paint C"):
        bpy.ops.m3d.layer_add(kind='FILL' if name == "Fill B" else 'PAINT')
        LY.active_layer(s3e_mat()).name = name
        if name != "Fill B":
            bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
        if name == "Paint A":
            LY.write_pixels(LY.entry_of(LY.active_layer(s3e_mat()), 'BASE_COLOR').image, np.tile(np.array([1.0, 0.1, 0.1, 1.0], np.float32), (64 * 64, 1)))
            bpy.ops.m3d.layer_mask_add(fill='WHITE')
            ramp = np.ones((64, 64, 4), np.float32)
            ramp[..., :3] = np.linspace(0.0, 1.0, 64, dtype=np.float32)[None, :, None]
            LY.write_pixels(LY.paint_effect(LY.active_layer(s3e_mat())).image, ramp)
        if name == "Fill B":
            LY.active_layer(s3e_mat()).channels[0].color = (0.1, 0.5, 0.9, 1.0)
            bpy.ops.m3d.mask_effect_add(kind='NOISE')
            bpy.ops.m3d.mask_effect_add(kind='LEVELS')
    s3e_mat().m3d_layer_index = 1   # (Fill B: its effects are listed under it)
    S3E["real_look"], S3E["looks"] = LY.look_row, []

    def recorded(context, layout, owner, effect, selected, *args):
        if not effect:   # (a layer's row: the channel entry it shows)
            S3E["looks"].append((owner.id_data.name, owner.channel, owner.blend, round(owner.opacity, 3)))
        return S3E["real_look"](context, layout, owner, effect, selected, *args)
    LY.look_row = recorded
    LY.thumbs_clear()
    S3E["real_menu"] = LY.draw_list_menu
    bpy.types.UI_MT_button_context_menu.remove(LY.draw_list_menu)

    def menu_spy(self, context):
        mat = bpy.context.active_object.active_material
        ui_list = getattr(context, "ui_list", None)
        S3E["menu"].append((ui_list.bl_idname if ui_list is not None else None, LY.hovered_layer(context, mat) if mat is not None else ""))
        S3E["real_menu"](self, context)
    S3E["menu_spy"] = menu_spy
    bpy.types.UI_MT_button_context_menu.append(menu_spy)
    bpy.utils.register_class(M3D_OT_test_probe)
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name="Window", space_type='EMPTY', region_type='WINDOW')
    S3E["km"], S3E["kmi"] = km, km.keymap_items.new("m3d.test_probe", 'F19', 'PRESS')
    lay_show_tab()
    tex4_redraw()


def s3e_rows_ready():
    tex4_redraw()   # (asked again every tick: a window that is not on screen draws nothing)
    return len(S3E["looks"]) >= 3 and not LY._thumbs["todo"] and len(LY._thumbs["made"]) >= 4


step(wait_until(s3e_rows_ready, "the rows and their thumbnails", tries=40))


@step
def s3e_rows_check():
    mat = s3e_mat()
    check(not tracebacks(), "Python error drawing the layer rows")
    check({ch for _m, ch, _b, _o in S3E["looks"]} == {'BASE_COLOR'}, "the rows show Base Color first")
    coll = LY.thumb_collection()
    check(len(coll) >= 4 and all(t.icon_id for t in coll.values()), "the thumbnails are preview icons in the window (%d, ids %s)" % (len(coll), [t.icon_id for t in coll.values()]))
    key = "c:%s:%s:BASE_COLOR" % (mat.name, s3e_layer("Paint A").uid)
    px = np.array(coll[key].image_pixels_float).reshape(LY.THUMB, LY.THUMB, 4)
    check(key in LY._thumbs["made"] and px[..., 0].min() > 0.9 and px[..., 1].max() < 0.2, "the red paint layer has a red thumbnail")
    mkey = "m:%s:%s" % (mat.name, s3e_layer("Paint A").uid)
    mp = np.array(coll[mkey].image_pixels_float).reshape(LY.THUMB, LY.THUMB, 4)
    check(mp[:, 0, 0].max() < 0.05 and mp[:, -1, 0].min() > 0.95, "...and the mask thumbnail is the black to white ramp of its mask (%.2f to %.2f)" % (mp[:, 0, 0].max(), mp[:, -1, 0].min()))
    fkey = "c:%s:%s:BASE_COLOR" % (mat.name, s3e_layer("Fill B").uid)
    check(np.abs(np.array(coll[fkey].image_pixels_float[:3]) - LY.to_srgb(np.array([0.1, 0.5, 0.9], np.float32))).max() < 0.01, "the fill's thumbnail is its color")
    check(LY.mask_thumb(mat, s3e_layer("Fill B"))[0] is None, "a generator mask has no thumbnail")
    # find the header dropdown: scan the top of the dock under its tabs
    area, region = s3e_region()
    s3e_scan([(region.x + dx, y) for dx in (40, 110) for y in range(region.y + region.height - 20, region.y + region.height - 160, -4)])   # (Show, then the dropdown)


step(wait_until(s3e_scanned, "the probes of the dock header", tries=40))


@step
def s3e_dropdown_find():
    hits = s3e_hits(r"m3d_row_channel")
    check(bool(hits), "the channel dropdown is under the pointer at the top of the Layers tab (found at %d points)" % len(hits))
    S3E["dropdown"] = s3e_top_center(hits, 20) if hits else None
    check(s3e_mat().m3d_row_channel == 'BASE_COLOR', "the dropdown starts on Base Color")
    S3E["cycles"] = 0
    if hits:
        x, y = S3E["dropdown"]
        event('MOUSEMOVE', xy=(x + 1, y))
        event('MOUSEMOVE', xy=(x, y))


@step
def s3e_dropdown_open():
    """A click on the dropdown opens the list of channels; the key H (the first letter of Height, which no other channel starts with)
    picks it."""
    if S3E.get("dropdown") is not None:
        xy = S3E["dropdown"]
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        event('MOUSEMOVE', xy=xy)
        event('LEFTMOUSE', 'PRESS', xy)
        event('LEFTMOUSE', 'RELEASE', xy)


@step
def s3e_dropdown_pick():
    if S3E.get("dropdown") is not None:
        event('H', 'PRESS', S3E["dropdown"])
        event('H', 'RELEASE', S3E["dropdown"])


step(wait_until(lambda: S3E.get("dropdown") is None or s3e_mat().m3d_row_channel == 'HEIGHT', "Height to be picked in the channel list", tries=10))


@step
def s3e_dropdown_check():
    mat = s3e_mat()
    if mat.m3d_row_channel != 'HEIGHT':   # (a failure is on record: go on with the rest)
        mat.m3d_row_channel = 'HEIGHT'
    S3E["looks"].clear()
    tex4_redraw()


def s3e_looks_drawn():
    tex4_redraw()
    return len(S3E["looks"]) >= 3


step(wait_until(s3e_looks_drawn, "the rows to draw Height", tries=30))


@step
def s3e_dropdown_shown():
    check(not tracebacks(), "Python error after switching the channel")
    check(s3e_mat().m3d_row_channel == 'HEIGHT', "the dropdown is on Height")
    shown = {(ch, blend) for _m, ch, blend, _o in S3E["looks"]}
    check(shown == {('HEIGHT', 'LINEAR_LIGHT')}, "the rows show the Height blend of each layer: Linear Light (%s)" % sorted(shown))
    # find the rows: the content thumbnails of every layer, in a column at the left of the list
    area, region = s3e_region()
    S3E["col"] = region.x + int(70 * (bpy.context.preferences.system.ui_scale or 1.0))
    s3e_scan([(S3E["col"], y) for y in range(region.y + region.height - 12, region.y + 12, -5)])


step(wait_until(s3e_scanned, "the probes of the list", tries=40))


def s3e_find_rows():
    """{layer index: where its content thumbnail is} from the scan of the list."""
    import re
    rows = {}
    for (x, y), text in S3E["probes"].items():
        m = re.search(r"layer_pick\((?!.*part=)index=(\d+)\)", text)
        if m:
            rows.setdefault(int(m.group(1)), []).append((x, y))
    check(set(rows) == {0, 1, 2}, "a content thumbnail button for each of the three layers (rows found: %s)" % sorted(rows))
    return {i: s3e_top_center(points, 30) for i, points in rows.items()}


@step
def s3e_rows_find():
    S3E["rows"] = s3e_find_rows()
    effects = {text for text in S3E["probes"].values() if "layer_pick(part='EFFECT'" in text}
    check(len(effects) == 2, "the active layer (Fill B) lists the two effects of its mask, each a row with a button that selects it (%s)" % sorted(effects))
    # Paint C (the top row) active: another layer's list rows do not move when a thumbnail further down is clicked
    s3e_mat().m3d_layer_index = 2
    tex4_redraw()


@step
def s3e_rescan():
    area, region = s3e_region()
    s3e_scan([(S3E["col"], y) for y in range(region.y + region.height - 12, region.y + 12, -5)])


step(wait_until(s3e_scanned, "the probes of the list again", tries=40))


@step
def s3e_rows_again():
    S3E["rows"] = s3e_find_rows()
    area, region = s3e_region()
    # the mask thumbnail of layer 0 (Paint A): scan along its row
    if 0 in S3E["rows"]:
        y = S3E["rows"][0][1]
        s3e_scan([(x, y) for x in range(region.x + 10, region.x + int(region.width * 0.7), 6)])
    else:
        s3e_scan([])


step(wait_until(s3e_scanned, "the probes of the first row", tries=40))


@step
def s3e_mask_find():
    hits = s3e_hits(r"layer_pick\(part='MASK', index=0\)")
    check(bool(hits), "Paint A's mask thumbnail is a button of its row (found at %d points)" % len(hits))
    S3E["mask_xy"] = s3e_center(hits) if hits else S3E["rows"].get(0)
    mat = s3e_mat()
    check(mat.m3d_layer_index == 2 and not mat.m3d_show_mask, "Paint C is the active layer before the clicks")
    xy = S3E["mask_xy"]
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    event('LEFTMOUSE', 'PRESS', xy)
    event('LEFTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: s3e_mat().m3d_layer_index == 0 and LY.active_layer(s3e_mat()).paint_mask, "a click on the mask thumbnail to select the mask", tries=15))


@step
def s3e_mask_selected():
    mat = s3e_mat()
    layer = LY.active_layer(mat)
    check(layer.name == "Paint A", "the click selected Paint A")
    check(m3d_texture.props_context(bpy.context) == 'MASK', "Properties shows the mask")
    check(LY.target_image(bpy.context, mat, False) == LY.paint_effect(layer).image and LY.TARGETS not in bpy.context.window_manager,
          "strokes paint the mask's Paint effect alone")
    check(m3d_texture.paint_status(bpy.context, mat, layer) == "Painting Paint A mask", "the Layers panel says so")
    tex4_redraw()


step(wait_until(lambda: "mk_stack" in tex4_sections(), "Properties to draw the Mask section", tries=15))


@step
def s3e_content_click():
    check({"mk_stack", "mk_effect", "pp_brush"} <= tex4_sections(), "Properties - Mask: the mask, its effect and the brush (%s)" % sorted(tex4_sections()))
    xy = S3E["rows"][0]   # Paint A's content thumbnail
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    event('LEFTMOUSE', 'PRESS', xy)
    event('LEFTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: not LY.active_layer(s3e_mat()).paint_mask, "a click on the content thumbnail to select the layer's content", tries=15))


@step
def s3e_content_selected():
    mat = s3e_mat()
    layer = LY.active_layer(mat)
    check(layer.name == "Paint A" and m3d_texture.props_context(bpy.context) == 'PAINT', "the content thumbnail: Paint A, Properties - Paint")
    check(LY.target_image(bpy.context, mat, False) == LY.entry_of(layer, 'BASE_COLOR').image, "strokes paint the layer's Base Color again")
    check(m3d_texture.paint_status(bpy.context, mat, layer).startswith("Painting Paint A: "), "the Layers panel says so")
    tex4_redraw()


step(wait_until(lambda: "mk_stack" not in tex4_sections() and "pp_brush" in tex4_sections(), "Properties to draw the brush without the mask", tries=15))


def s3e_modifier_click(name, key, mods, cond, what):
    """Steps for a click with a modifier held: the modifier goes down in one step, the click is made in the next and the modifier goes up
    in a third. (A button runs its operator after the queued events have been handled: with everything in one step the modifier would be
    up again by then, which a hand on the keyboard never does.)"""
    def down():
        xy = S3E["mask_xy"]
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        event('MOUSEMOVE', xy=xy)
        event(key, 'PRESS', xy, **mods)

    def click():
        xy = S3E["mask_xy"]
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]), **mods)
        event('MOUSEMOVE', xy=xy, **mods)
        event('LEFTMOUSE', 'PRESS', xy, **mods)
        event('LEFTMOUSE', 'RELEASE', xy, **mods)

    def up():
        event(key, 'RELEASE', S3E["mask_xy"])
    down.__name__, click.__name__, up.__name__ = name + "_down", name + "_click", name + "_up"
    step(down)
    step(click)
    step(wait_until(cond, what, tries=15))
    step(up)


@step
def s3e_alt_prepare():
    check(not tracebacks(), "Python error after the mask click")


s3e_modifier_click("s3e_alt", 'LEFT_ALT', {"alt": True}, lambda: s3e_mat().m3d_show_mask, "Alt+click on the mask thumbnail to show the mask alone")


@step
def s3e_alt_shown():
    mat = s3e_mat()
    check(mat.node_tree.nodes.get(LY.MASKVIEW) is not None and mat.node_tree.nodes[LY.MASKVIEW].inputs["Color"].links, "the material shows the mask (Show Mask)")
    check(not tracebacks(), "Python error showing the mask")


s3e_modifier_click("s3e_alt2", 'LEFT_ALT', {"alt": True}, lambda: not s3e_mat().m3d_show_mask, "a second Alt+click to show the shader again")


@step
def s3e_shift_prepare():
    S3E["use_mask"] = LY.active_layer(s3e_mat()).use_mask


s3e_modifier_click("s3e_shift", 'LEFT_SHIFT', {"shift": True}, lambda: LY.active_layer(s3e_mat()).use_mask != S3E["use_mask"],
                   "Shift+click on the mask thumbnail to switch the mask off")


@step
def s3e_shift_check():
    layer = LY.active_layer(s3e_mat())
    check(S3E["use_mask"] and not layer.use_mask and layer.mask_stack, "Shift+click switched the mask off and kept it")
    mul = s3e_mat().node_tree.nodes[LY.part('BASE_COLOR', layer.uid, "maskmul")]
    check(not mul.inputs[1].links, "the material no longer uses the mask")
    layer.use_mask = True
    check(not tracebacks(), "Python error switching the mask")
    # right-click on the content thumbnail of Paint C (layer 2, not the active one)
    S3E["menu"].clear()
    xy = S3E["rows"][2]
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    event('RIGHTMOUSE', 'PRESS', xy)
    event('RIGHTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: bool(S3E["menu"]), "the right-click menu to open", tries=15))


@step
def s3e_menu_check():
    mat = s3e_mat()
    check(S3E["menu"][0][0] == "M3D_UL_layers", "the list item menu is asked for our list (%s)" % (S3E["menu"][0],))
    check(S3E["menu"][0][1] == s3e_layer("Paint C").uid and mat.m3d_layer_index != 2, "...and the layer under the pointer is the one clicked, not the active one (%s)" % (S3E["menu"][0],))
    check(not tracebacks(), "Python error opening the right-click menu")
    event('ESC', 'PRESS', S3E["rows"][2])
    event('ESC', 'RELEASE', S3E["rows"][2])


@step
def s3e_menus_open():
    # The Add Smart Material popover and the header menus open in the real window (the drawing runs in a real region)
    area, region = s3e_region()
    S3E["popups"] = []
    for kind, name in (("call_panel", "M3D_PT_lib_smart"), ("call_menu", "M3D_MT_layer_effect_add"), ("call_menu", "M3D_MT_layer_mask_add"),
                       ("call_menu", "M3D_MT_layer_more")):
        with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
            S3E["popups"].append((name, getattr(bpy.ops.wm, kind)('INVOKE_DEFAULT', name=name)))
        event('ESC', 'PRESS', S3E["rows"][2])
        event('ESC', 'RELEASE', S3E["rows"][2])


@step
def s3e_menus_check():
    check(all(res <= {'FINISHED', 'RUNNING_MODAL', 'INTERFACE'} for _name, res in S3E["popups"]), "the header menus and the smart material popover open: %s" % S3E["popups"])
    check(not tracebacks(), "Python error drawing the header menus and the smart material popover")


@step
def s3e_dup_key():
    # Ctrl+D over a thumbnail duplicates the active layer (over a property button Blender's own Ctrl+D would add a driver)
    mat = s3e_mat()
    S3E["count"] = len(mat.m3d_layers)
    mat.m3d_layer_index = LY.index_of(mat, s3e_layer("Paint C").uid)
    xy = S3E["rows"][2]
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    event('LEFT_CTRL', 'PRESS', xy, ctrl=True)
    event('D', 'PRESS', xy, ctrl=True)
    event('D', 'RELEASE', xy, ctrl=True)
    event('LEFT_CTRL', 'RELEASE', xy)


step(wait_until(lambda: len(s3e_mat().m3d_layers) == S3E["count"] + 1, "Ctrl+D over the layer list to duplicate the layer", tries=15))


@step
def s3e_dup_check():
    mat = s3e_mat()
    check(LY.active_layer(mat).name == "Paint C Copy" and not tracebacks(), "Ctrl+D duplicated the active layer: %s" % [l.name for l in mat.m3d_layers])
    S3E["count"] = len(mat.m3d_layers)
    area, region = s3e_region()
    xy = S3E["blank"] = (region.x + region.width // 2, region.y + 14)   # (the bottom of the dock: no button there; Blender's own Ctrl+V takes a button)
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    for key in ('C', 'V'):   # Ctrl+C, Ctrl+V: a copy above the active layer
        event('LEFT_CTRL', 'PRESS', xy, ctrl=True)
        event(key, 'PRESS', xy, ctrl=True)
        event(key, 'RELEASE', xy, ctrl=True)
        event('LEFT_CTRL', 'RELEASE', xy)


step(wait_until(lambda: len(s3e_mat().m3d_layers) == S3E["count"] + 1, "Ctrl+C, Ctrl+V over the layer list to paste a copy", tries=15))


@step
def s3e_delete_key():
    mat = s3e_mat()
    check(not tracebacks(), "Python error pasting")
    S3E["count"] = len(mat.m3d_layers)
    xy = S3E["blank"]
    event('DEL', 'PRESS', xy)
    event('DEL', 'RELEASE', xy)


step(wait_until(lambda: len(s3e_mat().m3d_layers) == S3E["count"] - 1, "Delete over the layer list to delete the layer", tries=15))


@step
def s3e_fill_scan():
    # Fill B: its mask thumbnail (a generator's icon), then a click on its name
    check(not tracebacks(), "Python error deleting")
    area, region = s3e_region()
    s3e_scan([(S3E["mask_xy"][0], y) for y in range(region.y + region.height - 12, region.y + 12, -5)])


step(wait_until(s3e_scanned, "the probes of the mask column", tries=40))


@step
def s3e_fill_mask_click():
    hits = s3e_hits(r"layer_pick\(part='MASK', index=1\)")
    check(bool(hits), "Fill B's mask thumbnail is in the mask column (found at %d points)" % len(hits))
    S3E["fill_xy"] = s3e_top_center(hits, 30) if hits else S3E["mask_xy"]
    LY.active_layer(s3e_mat()).paint_mask = False
    xy = S3E["fill_xy"]
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    event('LEFTMOUSE', 'PRESS', xy)
    event('LEFTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: LY.active_layer(s3e_mat()).name == "Fill B" and LY.active_layer(s3e_mat()).paint_mask, "a click on Fill B's mask thumbnail", tries=15))


@step
def s3e_fill_name_click():
    mat = s3e_mat()
    check(m3d_texture.props_context(bpy.context) == 'MASK' and LY.target_image(bpy.context, mat, False) is None,
          "Fill B's mask (generators only) selected: Properties - Mask, nothing to paint")
    check(m3d_texture.paint_status(bpy.context, mat, LY.active_layer(mat)) == "The mask has no Paint effect: add one to paint it", "...the hint says why")
    scale = bpy.context.preferences.system.ui_scale or 1.0
    xy = S3E["name_xy"] = (S3E["fill_xy"][0] + int(60 * scale), S3E["fill_xy"][1])   # (the name, right of the mask thumbnail)
    event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
    event('MOUSEMOVE', xy=xy)
    event('LEFTMOUSE', 'PRESS', xy)
    event('LEFTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: not LY.active_layer(s3e_mat()).paint_mask, "a click on Fill B's name to select its content", tries=15))


@step
def s3e_fill_content():
    mat = s3e_mat()
    check(LY.active_layer(mat).name == "Fill B" and m3d_texture.props_context(bpy.context) == 'FILL',
          "a click on the name of a fill whose mask was selected: Properties - Fill (%s)" % m3d_texture.props_context(bpy.context))
    check(m3d_texture.paint_status(bpy.context, mat, LY.active_layer(mat)) == "Fill Layer: click the mask thumbnail to paint", "...the hint says how to paint it")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo()


step(wait_until(lambda: LY.active_layer(s3e_mat()).paint_mask, "Undo to select the mask again", tries=15))


@step
def s3e_fill_undone():
    check(LY.active_layer(s3e_mat()).name == "Fill B" and m3d_texture.props_context(bpy.context) == 'MASK', "Undo brought the selected mask back")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.redo()


step(wait_until(lambda: not LY.active_layer(s3e_mat()).paint_mask, "Redo to select the content again", tries=15))


@step
def s3e_done():
    check(not tracebacks(), "Python error in the layer stack tests")
    LY.look_row = S3E["real_look"]
    bpy.types.UI_MT_button_context_menu.remove(S3E["menu_spy"])
    bpy.types.UI_MT_button_context_menu.append(S3E["real_menu"])
    S3E["km"].keymap_items.remove(S3E["kmi"])
    bpy.utils.unregister_class(M3D_OT_test_probe)
    check(window().workspace.m3d_layout == 1, "the Texture workspace is still the new layout")
    for image in [i for i in bpy.data.images if i.name.startswith("Stack3e")]:
        bpy.data.images.remove(image)


# ----------------------------------------------------------------------------------------------------
# The compact layer rows and the mask menu in the real window: a stack with a folder, a fill with a black mask and two more mask effects (their
# rows are under it), and a paint layer. A real right-click on the fill's mask thumbnail opens the mask menu (not the layer menu) for that layer,
# and its Add Fill adds a Fill effect to the mask. Pictures: F:/AI/m3d_layers_compact.png, F:/AI/m3d_mask_menu.png.

S3F = {"menu": []}


@step
def s3f_enter():
    restore_window()
    lb_sandbox()
    if window().workspace.name != "Texture":
        bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: window().workspace.name == "Texture" and len([a for a in window().screen.areas if a.type == 'IMAGE_EDITOR']) == 1
                and len(props_areas()) == 6, "the Texture workspace for the compact layer rows", tries=30))


@step
def s3f_setup():
    # A cube with: Paint Base, Fill Tint (a black mask and its Noise and Levels effects), a folder Group with Inner in it, Paint Top.
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
    bpy.context.active_object.name = "Stack3f"
    bpy.ops.m3d.tex_add_material()
    bpy.context.scene.m3d_tex.resolution = '64'
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    mat = s3e_mat()
    bpy.ops.m3d.layer_add(kind='PAINT')
    LY.active_layer(mat).name = "Paint Base"
    bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
    LY.write_pixels(LY.entry_of(LY.active_layer(mat), 'BASE_COLOR').image, np.tile(np.array([0.9, 0.3, 0.2, 1.0], np.float32), (64 * 64, 1)))
    bpy.ops.m3d.layer_add(kind='FILL')
    LY.active_layer(mat).name = "Fill Tint"
    LY.active_layer(mat).channels[0].color = (0.1, 0.5, 0.9, 1.0)
    bpy.ops.m3d.layer_mask_add(fill='BLACK')
    bpy.ops.m3d.mask_effect_add(kind='NOISE')
    bpy.ops.m3d.mask_effect_add(kind='LEVELS')
    bpy.ops.m3d.layer_add(kind='PAINT')
    LY.active_layer(mat).name = "Inner"
    bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
    bpy.ops.m3d.layer_folder_add(group=True)
    LY.active_layer(mat).name = "Group"
    bpy.ops.m3d.layer_add(kind='PAINT')
    LY.active_layer(mat).name = "Paint Top"
    bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
    mat.m3d_row_channel = 'BASE_COLOR'
    mat.m3d_layer_index = LY.index_of(mat, s3e_layer("Fill Tint").uid)
    LY.thumbs_clear()
    S3F["real_menu"] = LY.draw_list_menu
    bpy.types.UI_MT_button_context_menu.remove(LY.draw_list_menu)

    def menu_spy(self, context):
        mat_ = bpy.context.active_object.active_material
        ui_list = getattr(context, "ui_list", None)
        S3F["menu"].append((ui_list.bl_idname if ui_list is not None else None, LY.hovered(context, mat_) if mat_ is not None else None))
        S3F["real_menu"](self, context)
    S3F["menu_spy"] = menu_spy
    bpy.types.UI_MT_button_context_menu.append(menu_spy)
    bpy.utils.register_class(M3D_OT_test_probe)
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name="Window", space_type='EMPTY', region_type='WINDOW')
    S3F["km"], S3F["kmi"] = km, km.keymap_items.new("m3d.test_probe", 'F19', 'PRESS')
    lay_show_tab()
    tex4_redraw()


def s3f_rows_ready():
    tex4_redraw()
    return not LY._thumbs["todo"] and len(LY._thumbs["made"]) >= 3


step(wait_until(s3f_rows_ready, "the rows and their thumbnails", tries=40))


@step
def s3f_rows_shot():
    check(not tracebacks(), "Python error drawing the compact layer rows")
    e_screenshot("F:/AI/m3d_layers_compact.png")


def s3f_locate(tag, layer_name):
    """Steps that find the thumbnails of a layer (and the buttons of its mask's effect rows) by hovering the list and asking what is under the
    pointer: S3F[tag] = {"content": xy, "mask": xy, "effects": {index: xy}}."""
    import re

    def column():
        area, region = s3e_region()
        scale = bpy.context.preferences.system.ui_scale or 1.0
        S3F["region"] = (region.x, region.y, region.width, region.height, scale)
        s3e_scan([(region.x + int(36 * scale) + dx, y) for dx in (0, 6) for y in range(region.y + region.height - 12, region.y + 12, -5)])

    def row():
        mat = s3e_mat()
        eyes = {}
        for (x, y), text in S3E["probes"].items():
            m = re.search(r"m3d_layers\[(\d+)\]\.visible$", text)
            if m:
                eyes.setdefault(int(m.group(1)), []).append((x, y))
        check(set(eyes) == set(range(len(mat.m3d_layers))), "%s: an eye for each of the %d layers (found %s)" % (tag, len(mat.m3d_layers), sorted(eyes)))
        index = LY.index_of(mat, s3e_layer(layer_name).uid)
        S3F[tag] = {"index": index}
        if index not in eyes:
            s3e_scan([])
            return
        x0, y0, w, _h, scale = S3F["region"]
        top = s3e_top_center(eyes[index], 30)[1]
        points = [(x, top) for x in range(x0 + 10, x0 + int(w * 0.7), 5)]
        points += [(x0 + int(104 * scale), y) for y in range(top - 6, top - int(110 * scale), -4)]   # (the effect rows are under the row)
        s3e_scan(points)

    def found():
        index = S3F[tag]["index"]
        hits = s3e_hits(r"layer_pick\(part='MASK', index=%d\)" % index)
        content = s3e_hits(r"layer_pick\(index=%d\)" % index)
        S3F[tag]["mask"] = s3e_center(hits) if hits else None
        S3F[tag]["content"] = s3e_center(content) if content else None
        effects = {}
        for (x, y), text in S3E["probes"].items():
            m = re.search(r"layer_pick\(part='EFFECT', index=%d, effect=(\d+)\)" % index, text)
            if m:
                effects.setdefault(int(m.group(1)), []).append((x, y))
        S3F[tag]["effects"] = {i: s3e_center(points) for i, points in effects.items()}
        check(bool(hits), "%s: the mask thumbnail of %s is a button of its row (found at %d points)" % (tag, layer_name, len(hits)))
        check(bool(content), "%s: ...and so is its content thumbnail (found at %d points)" % (tag, len(content)))
        if hits and content:
            check(max(x for x, _y in content) < min(x for x, _y in hits), "%s: the content thumbnail is left of the mask thumbnail" % tag)

    for fn, name in ((column, "column"), (row, "row"), (found, "found")):
        fn.__name__ = "s3f_%s_%s" % (tag, name)
    step(column)
    step(wait_until(s3e_scanned, "the probes of the list (%s)" % tag, tries=60))
    step(row)
    step(wait_until(s3e_scanned, "the probes of the row of %s (%s)" % (layer_name, tag), tries=60))
    step(found)


def s3f_settle():
    """Steps after a menu was closed: the pointer goes to an empty place of the dock, the windows are drawn again."""
    def move():
        area, region = s3e_region()
        xy = (region.x + region.width // 2, region.y + 14)
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        event('MOUSEMOVE', xy=xy)
        tex4_redraw()
    S3F["settles"] = S3F.get("settles", 0) + 1
    move.__name__ = "s3f_settle_%d" % S3F["settles"]
    step(move)
    step(move)


def s3f_click(tag, what, button):
    """Steps: move to the button `what` ("mask", "content" or an effect index) of S3F[tag] and press the mouse button there (the menu spy is cleared first)."""
    def go():
        xy = S3F[tag][what] if what in {"mask", "content"} else S3F[tag]["effects"].get(what)
        S3F["xy"] = xy
        S3F["menu"].clear()
        check(xy is not None, "%s: the button %s is there to click" % (tag, what))
        if xy:
            event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
            event('MOUSEMOVE', xy=xy)
            event(button, 'PRESS', xy)
            event(button, 'RELEASE', xy)
    go.__name__ = "s3f_%s_%s_click" % (tag, what)
    step(go)


s3f_locate("a", "Fill Tint")
s3f_click("a", "mask", 'RIGHTMOUSE')
step(wait_until(lambda: S3F["xy"] is None or bool(S3F["menu"]), "the right-click menu to open on the mask thumbnail", tries=20))


@step
def s3f_a_menu():
    fill = s3e_layer("Fill Tint")
    check(set(S3F["a"]["effects"]) == {0, 1, 2}, "the three effect rows of the mask are buttons (found %s)" % sorted(S3F["a"]["effects"]))
    check(bool(S3F["menu"]) and S3F["menu"][0] == ("M3D_UL_layers", (fill.uid, True, -1)),
          "a real right-click on the mask thumbnail of Fill Tint opens the mask menu for that layer (%s)" % (S3F["menu"][:1],))
    check(not tracebacks(), "Python error opening the mask menu")
    for _i in range(3):   # (the key presses highlight Add Fill and take the tooltip of the first item away)
        event('DOWN_ARROW', 'PRESS', S3F["xy"])
        event('DOWN_ARROW', 'RELEASE', S3F["xy"])


@step
def s3f_a_menu_shot():
    e_screenshot("F:/AI/m3d_mask_menu.png")
    event('ESC', 'PRESS', S3F["xy"])
    event('ESC', 'RELEASE', S3F["xy"])


# a right-click on an effect row: the mask menu, for the effect under the pointer
s3f_settle()
s3f_click("a", 1, 'RIGHTMOUSE')
step(wait_until(lambda: S3F["xy"] is None or bool(S3F["menu"]), "the right-click menu to open on an effect row", tries=20))


@step
def s3f_a_effect_menu():
    fill = s3e_layer("Fill Tint")
    check(bool(S3F["menu"]) and S3F["menu"][0] == ("M3D_UL_layers", (fill.uid, True, 1)),
          "a right-click on the Noise effect row opens the mask menu for that effect (%s)" % (S3F["menu"][:1],))
    check(not tracebacks(), "Python error opening the mask menu from an effect row")
    event('ESC', 'PRESS', S3F["xy"])
    event('ESC', 'RELEASE', S3F["xy"])


# a right-click on the content thumbnail: the layer menu
s3f_settle()
s3f_click("a", "content", 'RIGHTMOUSE')
step(wait_until(lambda: S3F["xy"] is None or bool(S3F["menu"]), "the right-click menu to open on the content thumbnail", tries=20))


@step
def s3f_a_layer_menu():
    fill = s3e_layer("Fill Tint")
    check(bool(S3F["menu"]) and S3F["menu"][0] == ("M3D_UL_layers", (fill.uid, False, -1)),
          "a right-click on the content thumbnail opens the layer menu (%s)" % (S3F["menu"][:1],))
    event('ESC', 'PRESS', S3F["xy"])
    event('ESC', 'RELEASE', S3F["xy"])


s3f_settle()


@step
def s3f_other_active():
    # Another layer is the active one: the right-click is on a layer that is not
    mat = s3e_mat()
    mat.m3d_layer_index = LY.index_of(mat, s3e_layer("Paint Top").uid)
    S3F["count"] = len(s3e_layer("Fill Tint").mask_stack)
    tex4_redraw()


s3f_locate("b", "Fill Tint")
s3f_click("b", "mask", 'RIGHTMOUSE')
step(wait_until(lambda: S3F["xy"] is None or bool(S3F["menu"]), "the right-click menu to open on the mask thumbnail of another layer", tries=20))


@step
def s3f_b_menu():
    fill = s3e_layer("Fill Tint")
    mat = s3e_mat()
    check(bool(S3F["menu"]) and S3F["menu"][0] == ("M3D_UL_layers", (fill.uid, True, -1)) and LY.active_layer(mat).name == "Paint Top",
          "the mask thumbnail of a layer that is not the active one opens the mask menu for it (%s)" % (S3F["menu"][:1],))
    # (the menu starts with Blender's own items: Add to Quick Favorites under the pointer, Online Manual, Add to Shelf; then Add Fill)
    for key in ('DOWN_ARROW', 'DOWN_ARROW', 'DOWN_ARROW', 'RET'):
        event(key, 'PRESS', S3F["xy"])
        event(key, 'RELEASE', S3F["xy"])


step(wait_until(lambda: len(s3e_layer("Fill Tint").mask_stack) > S3F["count"], "Add Fill to add an effect to the mask", tries=20))


@step
def s3f_b_added():
    mat = s3e_mat()
    fill = s3e_layer("Fill Tint")
    check([e.kind for e in fill.mask_stack] == ['PAINT', 'NOISE', 'LEVELS', 'FILL'] and LY.active_effect(fill).kind == 'FILL',
          "Add Fill in the mask menu added a Fill effect to the mask, above the selected effect: %s" % [e.kind for e in fill.mask_stack])
    check(LY.active_layer(mat).name == "Fill Tint", "...and selected the layer the menu was for")
    check(not tracebacks(), "Python error running Add Fill from the mask menu")
    tex4_redraw()


# the effects of the Mask panel (Properties): closed at first under their heading; open, a right-click on one of its rows opens the mask
# menu too
def s3f_props_column():
    region = S3F["props_region"]
    s3e_scan([(region.x + int(region.width * f), y) for f in (0.05, 0.08, 0.11, 0.4) for y in range(region.y + region.height - 8, region.y + 8, -4)])


@step
def s3f_props_scan():
    area = tex_roles()["props"]
    S3F["props_region"] = next(r for r in area.regions if r.type == 'WINDOW')
    s3f_props_column()


step(wait_until(s3e_scanned, "the probes of the Properties editor", tries=60))


@step
def s3f_effects_open():
    hits = s3e_hits(r"layer_mask_invert")
    check(bool(hits), "Invert Mask is a button of the Mask section (found at %d points)" % len(hits))
    check(not s3e_hits(r"mask_stack\[1\]\.name$"), "the mask's effects are closed under their heading at first")
    if hits:
        scale = bpy.context.preferences.system.ui_scale or 1.0
        x, y = s3e_top_center(hits, 20)
        xy = (x, y - int(25 * scale))   # (the heading Mask Effects, under Invert Mask)
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        event('MOUSEMOVE', xy=xy)
        event('LEFTMOUSE', 'PRESS', xy)
        event('LEFTMOUSE', 'RELEASE', xy)
    tex4_redraw()


@step
def s3f_effects_scan():
    s3f_props_column()


step(wait_until(s3e_scanned, "the probes of the open effects", tries=60))


@step
def s3f_props_click():
    import re
    hits = [xy for xy, text in S3E["probes"].items() if re.search(r"mask_stack\[1\]\.visible$", text)]
    check(bool(hits), "a click on the heading opened the effects: the second effect's eye is in the Mask panel's list (found at %d points)" % len(hits))
    S3F["xy"] = s3e_top_center(hits, 20) if hits else None
    S3F["menu"].clear()
    if S3F["xy"]:
        xy = S3F["xy"]
        event('MOUSEMOVE', xy=(xy[0] + 1, xy[1]))
        event('MOUSEMOVE', xy=xy)
        event('RIGHTMOUSE', 'PRESS', xy)
        event('RIGHTMOUSE', 'RELEASE', xy)


step(wait_until(lambda: S3F["xy"] is None or bool(S3F["menu"]), "the right-click menu to open on an effect of the Mask panel", tries=20))


@step
def s3f_props_menu():
    fill = s3e_layer("Fill Tint")
    check(bool(S3F["menu"]) and S3F["menu"][0] == ("M3D_UL_mask_effects", (fill.uid, True, 1)),
          "a right-click on an effect of the Mask panel opens the mask menu for that effect (%s)" % (S3F["menu"][:1],))
    check(not tracebacks(), "Python error opening the mask menu from the Mask panel")
    event('ESC', 'PRESS', S3F["xy"] or (200, 200))
    event('ESC', 'RELEASE', S3F["xy"] or (200, 200))


@step
def s3f_done():
    check(not tracebacks(), "Python error in the compact layer rows tests")
    bpy.types.UI_MT_button_context_menu.remove(S3F["menu_spy"])
    bpy.types.UI_MT_button_context_menu.append(S3F["real_menu"])
    S3F["km"].keymap_items.remove(S3F["kmi"])
    bpy.utils.unregister_class(M3D_OT_test_probe)
    for image in [i for i in bpy.data.images if i.name.startswith("Stack3f")]:
        bpy.data.images.remove(image)


@step
def tex3_done():
    check(not tracebacks(), "Python error in the redesigned Texture workspace tests")


@step
def lb_done():
    LIB.library_dir, LIB.step, m3d_sculpt.alpha_dir = GIZMO["lb_saved"]
    LIB._gen["shipped"] = True
    shutil.rmtree(GIZMO["lb_dir"], ignore_errors=True)
    shutil.rmtree(GIZMO["lb_alphas"], ignore_errors=True)
    LIB._user["entries"] = None
    LIB._gen.update(running=False, done=True, stage=None, failed=set())   # (done: the Assets panel of the Texture workspace does not start the thumbnails again meanwhile)
    check(not tracebacks(), "Python error in the Library tests")


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
    bottom = next((a for a in screen.areas if a.ui_type == 'TIMELINE'), None)
    check(bottom is not None and bottom.y < view.y and bottom.height < view.height / 6, "Rigging: a Time Slider at the bottom, short (%s)" %
          ((bottom.height, view.height) if bottom else None,))
    header = next(r for r in bottom.regions if r.type == 'HEADER') if bottom else None
    check(header is not None and header.alignment == 'BOTTOM', "...with its controls under the slider, like the other workspaces")
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
    check(not m3d_rig.drivers_open(window().screen), "no Drivers editor at first")
    rig_status("m3d.rig_drivers_editor")


@step
def rig_drivers_check():
    screen = window().screen
    area, (view, _region) = m3d_rig.drivers_area(screen), rig_view()
    timeline = next((a for a in screen.areas if a.ui_type == 'TIMELINE'), None)
    check(area is not None and area.type == 'GRAPH_EDITOR' and area.spaces.active.mode == 'DRIVERS',
          "Status Line button: a Drivers editor opens (%s)" % ((area.type, area.ui_type) if area else None,))
    check(area is not None and timeline is not None and timeline.y < area.y < view.y and area.x == view.x and area.width == view.width,
          "...under the viewport, over the Time Slider (which stays)")
    check(area is not None and area.height > timeline.height * 2 and area.spaces.active.show_region_ui, "...tall enough, with its sidebar")
    press_ok("m3d.rig_drivers_editor")


@step
def rig_drivers_back():
    screen = window().screen
    check(not m3d_rig.drivers_open(screen) and len([a for a in screen.areas if a.type == 'VIEW_3D']) == 1,
          "...and again: closed, the viewport gets its room back")
    check(any(a.ui_type == 'TIMELINE' for a in screen.areas), "the Time Slider is still there")
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


# --- UX pass 2: Mirror names the sides first, new bones rotate in XYZ Euler, Constrain in Pose Mode makes a bone constraint
# that keeps its offset, the Constrain menu draws in Pose Mode, the Channel Box tab comes back in the mode it was picked in,
# Check Rig and the range-of-motion test from the Test tab.
@step
def rig_u3_mirror():
    arm = rig_obj().data
    for eb in arm.edit_bones:
        eb.select = eb.select_head = eb.select_tail = False
    eb = arm.edit_bones.new("Fin")
    eb.head, eb.tail = (0.5, 0, 1.0), (0.9, 0, 1.0)
    eb.select = eb.select_head = eb.select_tail = True
    press_ok("m3d.dock_page", tab="rig_skeleton")
    press_ok("m3d.rig_mirror", direction='POSITIVE_X')


@step
def rig_u3_mirror_check():
    names = {b.name for b in rig_obj().data.edit_bones}
    check({"Fin.L", "Fin.R"} <= names, "Mirror from the Skeleton tab names the side first: %s" % sorted(names))
    check(not tracebacks(), "Python error while mirroring")
    rig_status("m3d.rig_mode", mode='POSE')


step(wait_until(lambda: bpy.context.mode == 'POSE' and all(rig_obj().pose.bones[n].rotation_mode == 'XYZ' for n in ("Fin.L", "Fin.R")),
                "Pose Mode, the new bones in XYZ Euler"))


@step
def rig_u3_constrain():
    ob = rig_obj()
    for pb in ob.pose.bones:
        pb.select = pb.name in {"Fin.L", "Fin.R"}
    ob.data.bones.active = ob.data.bones["Fin.L"]
    bpy.context.view_layer.update()
    GIZMO["fin"] = (ob.matrix_world @ ob.pose.bones["Fin.L"].matrix).translation.copy()
    bpy.context.scene.m3d_rig.keep_offset = True
    rig_status("m3d.rig_constrain", type='COPY_LOCATION')   # (Constrain > Point runs it from the top bar)


@step
def rig_u3_constrain_check():
    ob = rig_obj()
    cons = ob.pose.bones["Fin.L"].constraints
    check(not ob.constraints and len(cons) == 1 and cons[0].type == 'COPY_LOCATION' and cons[0].subtarget == "Fin.R",
          "Constrain > Point in Pose Mode: a bone constraint to the other bone (%s)" % [(c.type, c.subtarget) for c in cons])
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    now = (ev.matrix_world @ ev.pose.bones["Fin.L"].matrix).translation
    check((now - GIZMO["fin"]).length < 1e-4, "...that keeps the bone where it was (%s vs %s)" % (tuple(now), tuple(GIZMO["fin"])))
    rig_status("m3d.rig_constraints_clear")
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.call_menu(name="M3D_MT_constrain")


@step
def rig_u3_menu_close():
    check(not rig_obj().pose.bones["Fin.L"].constraints, "Remove Constraints clears the bone's")
    check(not tracebacks(), "Python error drawing the Constrain menu in Pose Mode")
    event('ESC', 'PRESS', rig_xy())
    event('ESC', 'RELEASE', rig_xy())
    _left, dock = rig_dock()
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    press_ok("m3d.dock_page", _area=dock, tab="channel_box")


@step
def rig_u3_channel_box():
    _left, dock = rig_dock()
    check(dock.spaces.active.context == 'CHANNEL_BOX', "the Rigging dock's Channel Box tab")
    with bpy.context.temp_override(window=window(), area=dock):
        check(m3d_workspace.split_dock_tabs(bpy.context)[2] == "channel_box", "...is drawn as the active tab")
    press_ok("m3d.rig_rotate_order", order='XYZ')   # (the Rotate Order row of the Channel Box)
    rig_status("m3d.rig_mode", mode='OBJECT')


step(wait_until(lambda: bpy.context.mode == 'OBJECT', "Object Mode"))


@step
def rig_u3_channel_box_back():
    _left, dock = rig_dock()
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    press_ok("m3d.dock_page", _area=dock, tab="rig_test")
    rig_status("m3d.rig_mode", mode='POSE')


step(wait_until(lambda: bpy.context.mode == 'POSE' and rig_dock()[1].spaces.active.context == 'CHANNEL_BOX',
                "Pose Mode to bring back the Channel Box picked there"))


@step
def rig_u3_check_rig():
    check(not tracebacks(), "Python error drawing the Rigging Channel Box")
    _left, dock = rig_dock()
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    press_ok("m3d.dock_page", _area=dock, tab="rig_test")
    press_ok("m3d.rig_check")
    for pb in rig_obj().pose.bones:
        pb.select = pb.name in {"Fin.L", "Fin.R"}
    press_ok("m3d.rig_rom")


@step
def rig_u3_rom_check():
    ob = rig_obj()
    check(m3d_rig._checked["rig"] == ob.name and m3d_rig._checked["problems"] is not None, "Check Rig from the Test tab")
    check([t.name for t in ob.animation_data.nla_tracks] == [m3d_rig.ROM], "the range-of-motion test layer")
    check(not tracebacks(), "Python error on the Test tab")
    press_ok("m3d.rig_rom", remove=True)


@step
def rig_u3_rom_removed():
    ob = rig_obj()
    check(not ob.animation_data.nla_tracks and all(abs(v) < 1e-6 for v in ob.pose.bones["Fin.L"].rotation_euler), "...removed again")
    m3d_rig._state["picked"].pop('POSE', None)
    rig_status("m3d.rig_mode", mode='EDIT')


step(wait_until(lambda: bpy.context.mode == 'EDIT_ARMATURE', "Edit Mode"))


@step
def rig_u3_cleanup():
    arm = rig_obj().data
    for name in ("Fin.L", "Fin.R"):
        arm.edit_bones.remove(arm.edit_bones[name])


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
                if tab.page:
                    check(getattr(window().workspace, "m3d_page_" + side) == tab.page, "dock tab %s did not open its page" % tab.id)
                else:   # (the Channel Box)
                    check(rig_dock()[1].spaces.active.context == tab.context, "dock tab %s did not open" % tab.id)
                check(not tracebacks(), "Python error while drawing the Rigging page %s in %s" % (tab.page or tab.id, mode))
            show.__name__, check_draw.__name__ = "rig_show_%s_%s" % (tab.id, mode), "rig_drawn_%s_%s" % (tab.id, mode)
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


# ----------------------------------------------------------------------------------------------------
# Phase 5: Animation workspace with a keyed cube and a keyed two-bone rig: layout, F6, Graph / Dope Sheet, Auto Key, S,
# Tween by keys (drag, confirm, cancel), Push / Relax keys, motion paths, ghost curves, layers, Playblast, every tab.

import tempfile

import m3d_anim


def an_dock():
    return props_areas()[0]


def an_view():
    """(main 3D view area, its window region) of the Animation screen."""
    area = max((a for a in window().screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def an_xy(dx=0, dy=0):
    _area, region = an_view()
    return region.x + region.width // 2 + dx, region.y + region.height // 2 + dy


def an_status(idname, **props):
    """A Status Line button: the operator in the top bar's own context."""
    with bpy.context.temp_override(window=window(), screen=window().screen):
        return getattr(getattr(bpy.ops, idname.split(".")[0]), idname.split(".")[1])('INVOKE_DEFAULT', **props)


def an_press(idname, **props):
    return press_ok(idname, _area=an_dock(), **props)


def an_box():
    return bpy.data.objects.get("Box")


def an_rig():
    return bpy.data.objects.get("Rig")


def an_keys(ob, path, index=0):
    fc = next((f for f in m3d_anim.channel_fcurves(ob) if f.data_path == path and f.array_index == index), None)
    return {round(k.co.x): k.co.y for k in fc.keyframe_points} if fc else {}


def an_mod_key(key, down, shift=False, alt=False, ctrl=False, xy=None):
    """Press or release a key while the modifier keys are held (real modifier key events: flags alone are not enough)."""
    xy = xy or an_xy()
    for name, on in (('LEFT_ALT', alt), ('LEFT_SHIFT', shift), ('LEFT_CTRL', ctrl)):
        if on and down:
            event(name, 'PRESS', xy, alt=alt, shift=shift, ctrl=ctrl)
    event(key, 'PRESS' if down else 'RELEASE', xy, alt=alt, shift=shift, ctrl=ctrl)
    if not down:
        for name, on in (('LEFT_ALT', alt), ('LEFT_SHIFT', shift), ('LEFT_CTRL', ctrl)):
            if on:
                event(name, 'RELEASE', xy)


@step
def anim_setup():
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end, scene.frame_current = 1, 24, 1
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
    box = bpy.context.active_object
    box.name = "Box"
    bpy.ops.object.camera_add(location=(4.5, -4.5, 3.2), rotation=(1.12, 0, 0.785))
    scene.camera = bpy.context.active_object
    rig = m3d_rig.new_armature(bpy.context, "Rig")
    m3d_rig._select_only(bpy.context, rig)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, z in (("Root", 0.0), ("Arm", 1.0)):
        eb = rig.data.edit_bones.new(name)
        eb.head, eb.tail = (-1.5, 0, z), (-1.5, 0, z + 1.0)
    rig.data.edit_bones["Arm"].parent = rig.data.edit_bones["Root"]
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.m3d.rig_mode(mode='POSE')
    arm = rig.pose.bones["Arm"]
    for pb in rig.pose.bones:
        pb.rotation_mode = 'XYZ'
        pb.select = pb.name == "Arm"
    arm["IK_FK"] = 0.5
    rig.data.bones.active = rig.data.bones["Arm"]
    for frame, value in ((1, 0.0), (11, 1.0)):
        arm.location.x, arm.rotation_euler.x = value, value * 0.8
        arm.keyframe_insert("location", index=0, frame=frame)
        arm.keyframe_insert("rotation_euler", index=0, frame=frame)
        box.location.x = value * 10
        box.keyframe_insert("location", index=0, frame=frame)
    scene.frame_set(1)
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    m3d_rig._select_only(bpy.context, rig)
    bpy.context.window_manager.m3d_menu_set = 'MODELING'
    c = (window().width // 2, window().height // 2)
    event('MOUSEMOVE', xy=c)
    event('F6', 'PRESS', c)
    event('F6', 'RELEASE', c)


step(wait_until(lambda: window().workspace.name == "Animation", "F6 to switch to Animation"))


@step
def anim_f6_check():
    check(window().workspace.name == "Animation" and bpy.context.mode == 'POSE', "F6 enters Animation in Pose Mode on a skeleton (%s)" % bpy.context.mode)
    check(bpy.context.window_manager.m3d_menu_set == 'ANIMATION', "F6 shows the Animation menu set")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.workspace_reset()   # The earlier dock tests moved this workspace's tabs: the factory layout is checked.


step(wait_until(lambda: [w.name for w in bpy.data.workspaces if w.name.startswith("Animation")] == ["Animation"]
                and window().workspace.name == "Animation", "Reset Workspace to finish"))


@step
def anim_layout_check():
    screen = window().screen
    views = sorted((a for a in screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.x)
    bottom = m3d_anim.bottom_area(screen)
    timelines = [a for a in screen.areas if a.type == 'DOPESHEET_EDITOR' and a.spaces.active.mode == 'TIMELINE']
    check(len(views) == 2 and views[0].spaces.active.region_3d.view_perspective == 'CAMERA' and views[1].width > views[0].width * 1.2,
          "Animation: a camera view next to the large viewport")
    check(bottom is not None and bottom.ui_type == 'DOPESHEET' and len(timelines) == 1 and timelines[0].y < bottom.y
          and timelines[0].height < 250, "Animation: one Dope Sheet / Graph Editor with a short Timeline under it")
    check(len(props_areas()) == 1 and not [a for a in screen.areas if a.type == 'OUTLINER'], "Animation: one dock, no Outliner")
    dock = an_dock()
    check(dock.spaces.active.context == 'CHANNEL_BOX' and dock.width >= 600, "the dock opens on the Channel Box (%s, %d px)" % (dock.spaces.active.context, dock.width))
    check(not screen.use_play_properties_editors and screen.use_play_3d_editors and screen.use_play_animation_editors,
          "playback redraws only viewports and animation editors")
    header = next(r for r in timelines[0].regions if r.type == 'HEADER')
    check(header.alignment == 'BOTTOM', "the Timeline controls sit below the slider")
    space = bottom.spaces.active if bottom else None
    check(space is not None and not space.show_region_footer and not space.show_region_ui,
          "one transport row (the Time Slider's): the Dope Sheet has no playback footer, its sidebar is closed")
    check(window().workspace.m3d_layout == m3d_anim.ANIM_LAYOUT, "the factory layout is the one-transport-row one")
    check(m3d_ui.shelf_key(bpy.context.window_manager, 'ANIM') == 'ANIM_ANIMATE', "Animate shelf tab first")
    check(window().workspace.object_mode == 'POSE', "workspace enters Pose Mode")
    check(not tracebacks(), "Python error drawing the Animation workspace")


# --- Graph Editor / Dope Sheet from the Status Line
@step
def anim_graph_toggle():
    an_status("m3d.anim_editor", editor='GRAPH')


@step
def anim_graph_toggle_check():
    area = m3d_anim.bottom_area(window().screen)
    check(area is not None and area.type == 'GRAPH_EDITOR' and area.ui_type == 'FCURVES', "Status Line: the bottom editor is the Graph Editor")
    check(area is not None and not area.spaces.active.show_region_footer, "...without a second transport row")
    check(not tracebacks(), "Python error drawing the Graph Editor")
    an_status("m3d.anim_editor", editor='DOPESHEET')


@step
def anim_graph_toggle_back():
    area = m3d_anim.bottom_area(window().screen)
    check(area is not None and area.type == 'DOPESHEET_EDITOR' and area.spaces.active.mode == 'DOPESHEET', "...and back to the Dope Sheet")
    check(len([a for a in window().screen.areas if a.type == 'DOPESHEET_EDITOR' and a.spaces.active.mode == 'TIMELINE']) == 1, "the Timeline is untouched")


# --- Auto Key and S (Set Key), with new keys following the Preferences default
@step
def anim_autokey_on():
    bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(2.5, 2, 0.25))
    ob = bpy.context.active_object
    ob.name = "Fresh"
    check(bpy.context.scene.tool_settings.use_keyframe_insert_auto, "the Status Line's Auto Key toggle is on")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def anim_autokey_check():
    ob = bpy.data.objects["Fresh"]
    check(not tracebacks(), "Python error drawing the Status Line with Auto Key on")
    bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
    bpy.context.scene.frame_set(1)
    ob.location = (3.5, 2, 0.25)
    an_status("m3d.anim_interp", kind='LINEAR')
    bpy.context.scene.frame_set(1)
    event('MOUSEMOVE', xy=an_xy())
    event('S', 'PRESS', an_xy())
    event('S', 'RELEASE', an_xy())


@step
def anim_set_key_move():
    ob = bpy.data.objects["Fresh"]
    check(1 in an_keys(ob, "location"), "S sets a key: %s" % an_keys(ob, "location"))
    bpy.context.scene.frame_set(6)
    ob.location.x = 7.0
    event('MOUSEMOVE', xy=an_xy(1, 0))
    event('S', 'PRESS', an_xy())
    event('S', 'RELEASE', an_xy())


@step
def anim_set_key_check():
    ob = bpy.data.objects["Fresh"]
    fc = next(f for f in m3d_anim.channel_fcurves(ob) if f.data_path == "location" and f.array_index == 0)
    check(set(an_keys(ob, "location")) == {1, 6} and [k.interpolation for k in fc.keyframe_points] == ['LINEAR', 'LINEAR'],
          "new keys follow the Linear default: %s" % ([k.interpolation for k in fc.keyframe_points],))
    an_status("m3d.anim_preset", preset='RESTORE')
    check(not m3d_anim._prefs_before, "(defaults restored)")
    bpy.data.objects.remove(ob)
    check(not tracebacks(), "Python error with Auto Key / S")


# --- S in Pose Mode: the selected bone's unlocked channels and custom property (one Set Key rule)
@step
def anim_pose_s():
    rig = an_rig()
    m3d_rig._select_only(bpy.context, rig)
    bpy.ops.m3d.rig_mode(mode='POSE')
    for pb in rig.pose.bones:
        pb.select = pb.name == "Arm"
    rig.data.bones.active = rig.data.bones["Arm"]
    rig.pose.bones["Arm"].lock_location[2] = True
    bpy.context.scene.frame_set(16)
    event('MOUSEMOVE', xy=an_xy())
    event('S', 'PRESS', an_xy())
    event('S', 'RELEASE', an_xy())


@step
def anim_pose_s_check():
    rig = an_rig()
    check(16 in an_keys(rig, 'pose.bones["Arm"]["IK_FK"]'), "S in Pose Mode keys the bone's custom property: %s" % an_keys(rig, 'pose.bones["Arm"]["IK_FK"]'))
    check(16 in an_keys(rig, 'pose.bones["Arm"].location') and 16 not in an_keys(rig, 'pose.bones["Arm"].location', 2),
          "...its unlocked channels, not the locked translate Z")
    check(16 not in an_keys(rig, 'pose.bones["Root"].location'), "...only the selected bone")
    rig.pose.bones["Arm"].lock_location[2] = False
    for fc in m3d_anim.channel_fcurves(rig):   # (the keys at 16 go again: the steps below count on two keys a channel)
        for key in [k for k in fc.keyframe_points if round(k.co.x) == 16][::-1]:
            fc.keyframe_points.remove(key)
    bag = m3d_anim.animdata_get_channelbag_for_assigned_slot(rig.animation_data)
    for fc in [f for f in bag.fcurves if not len(f.keyframe_points)]:
        bag.fcurves.remove(fc)
    bpy.context.scene.frame_set(1)
    check(not tracebacks(), "Python error with S in Pose Mode")


# --- Z / Shift+Z undo and redo with the pointer over the Graph Editor (Z used to be Zoom Region there)
@step
def anim_z_undo():
    an_status("m3d.anim_editor", editor='GRAPH')
    bpy.ops.ed.undo_push(message="Before Z")
    an_box().location.z = 7.0
    bpy.ops.ed.undo_push(message="Box up")
    area = m3d_anim.bottom_area(window().screen)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    GIZMO["graph_xy"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["graph_xy"])
    event('Z', 'PRESS', GIZMO["graph_xy"])
    event('Z', 'RELEASE', GIZMO["graph_xy"])


@step
def anim_z_undo_check():
    check(abs(an_box().location.z - 7.0) > 1e-3, "Z over the Graph Editor undoes (z = %.2f)" % an_box().location.z)
    an_mod_key('Z', True, shift=True, xy=GIZMO["graph_xy"])
    an_mod_key('Z', False, shift=True, xy=GIZMO["graph_xy"])


@step
def anim_z_redo_check():
    check(abs(an_box().location.z - 7.0) < 1e-3, "Shift+Z over the Graph Editor redoes (z = %.2f)" % an_box().location.z)
    an_box().location.z = 0.5
    an_status("m3d.anim_editor", editor='DOPESHEET')
    check(not tracebacks(), "Python error with Z / Shift+Z")


# --- Breakdown key and Euler filter from the shelf's operators
@step
def anim_breakdown_key():
    m3d_rig._select_only(bpy.context, an_box())
    bpy.context.scene.frame_set(4)
    an_press("m3d.anim_key_type", key_type='BREAKDOWN')


@step
def anim_breakdown_key_check():
    fc = next(f for f in m3d_anim.channel_fcurves(an_box()) if f.data_path == "location" and f.array_index == 0)
    check([k.type for k in fc.keyframe_points if round(k.co.x) == 4] == ['BREAKDOWN'], "Breakdown key sets a breakdown key")
    check(bpy.context.scene.tool_settings.keyframe_type == 'KEYFRAME', "...and leaves the key type alone")
    for k in list(fc.keyframe_points):
        if round(k.co.x) == 4:
            fc.keyframe_points.remove(k)
    an_press("m3d.anim_euler_filter")


# --- Tween by key: Alt+Q, drag right, click
@step
def anim_tween_start():
    bpy.context.scene.frame_set(6)
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('Q', True, alt=True)


@step
def anim_tween_drag():
    an_mod_key('Q', False, alt=True)
    check(any(op.bl_idname == "M3D_OT_tween" for op in window().modal_operators), "Alt+Q starts the Tween modal")
    for i in range(1, 6):
        event('MOUSEMOVE', xy=an_xy(20 * i, 0))


@step
def anim_tween_check_drag():
    check(abs(an_box().location.x - 7.5) < 0.2, "dragging 100 px right tweens to 0.75 (x = %.3f)" % an_box().location.x)
    check(6 not in an_keys(an_box(), "location"), "(nothing is keyed before the click)")
    event('LEFTMOUSE', 'PRESS', an_xy(100, 0))
    event('LEFTMOUSE', 'RELEASE', an_xy(100, 0))


@step
def anim_tween_confirm_check():
    keys = an_keys(an_box(), "location")
    check(6 in keys and abs(keys[6] - 7.5) < 0.2, "the click keys the tween at the current frame: %s" % keys)
    check(not any(op.bl_idname == "M3D_OT_tween" for op in window().modal_operators), "the Tween modal ended")
    check(not tracebacks(), "Python error in the Tween")
    m3d_rig._select_only(bpy.context, an_box())
    bpy.context.scene.frame_set(3)
    GIZMO["tween_before"] = an_box().location.x
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('Q', True, alt=True)


@step
def anim_tween_cancel_drag():
    an_mod_key('Q', False, alt=True)
    for i in range(1, 6):
        event('MOUSEMOVE', xy=an_xy(-30 * i, 0))


@step
def anim_tween_cancel_check():
    check(abs(an_box().location.x - GIZMO["tween_before"]) > 0.1, "(the tween moved the cube while dragging)")
    event('ESC', 'PRESS', an_xy(-150, 0))
    event('ESC', 'RELEASE', an_xy(-150, 0))


@step
def anim_tween_cancel_done():
    check(abs(an_box().location.x - GIZMO["tween_before"]) < 1e-4, "Esc puts the value back (%.3f vs %.3f)" % (an_box().location.x, GIZMO["tween_before"]))
    check(3 not in an_keys(an_box(), "location"), "...and keys nothing")


# --- The dock's Tween & Poses tab: slider and Key
@step
def anim_tween_dock():
    bpy.context.scene.frame_set(9)
    press_ok("m3d.dock_page", _area=an_dock(), tab="anim_tween")
    bpy.context.scene.m3d_anim.tween = 0.25


@step
def anim_tween_dock_check():
    before = dict(an_keys(an_box(), "location"))
    check(9 not in before, "the dock slider previews without keying")
    an_press("m3d.tween", from_dock=True)
    keys = an_keys(an_box(), "location")
    check(9 in keys and abs(keys[9] - bpy.data.objects["Box"].location.x) < 1e-3, "Key on the dock keys the slider's tween: %s" % keys)


# --- Push and Relax by key, in Pose Mode
@step
def anim_push_setup():
    bpy.ops.m3d.rig_mode(mode='POSE')
    rig = an_rig()
    bpy.context.scene.frame_set(6)
    GIZMO["push_start"] = rig.pose.bones["Arm"].location.x = 0.3
    for pb in rig.pose.bones:
        pb.select = pb.name == "Arm"
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('P', True, alt=True, shift=True)


@step
def anim_push_drag():
    an_mod_key('P', False, alt=True, shift=True)
    check(any(op.bl_idname == "POSE_OT_push" for op in window().modal_operators), "Alt+Shift+P starts Push")
    for i in range(1, 6):
        event('MOUSEMOVE', xy=an_xy(20 * i, 0))


@step
def anim_push_confirm():
    event('LEFTMOUSE', 'PRESS', an_xy(100, 0))
    event('LEFTMOUSE', 'RELEASE', an_xy(100, 0))


@step
def anim_push_check():
    check(abs(an_rig().pose.bones["Arm"].location.x - GIZMO["push_start"]) > 1e-3, "Push moved the bone (%.3f)" % an_rig().pose.bones["Arm"].location.x)
    check(not any(op.bl_idname == "POSE_OT_push" for op in window().modal_operators), "Push ended")
    GIZMO["relax_start"] = an_rig().pose.bones["Arm"].location.x
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('R', True, alt=True, shift=True)


@step
def anim_relax_drag():
    an_mod_key('R', False, alt=True, shift=True)
    check(any(op.bl_idname == "POSE_OT_relax" for op in window().modal_operators), "Alt+Shift+R starts Relax")
    for i in range(1, 6):
        event('MOUSEMOVE', xy=an_xy(20 * i, 0))


@step
def anim_relax_confirm():
    event('LEFTMOUSE', 'PRESS', an_xy(100, 0))
    event('LEFTMOUSE', 'RELEASE', an_xy(100, 0))


@step
def anim_relax_check():
    check(abs(an_rig().pose.bones["Arm"].location.x - GIZMO["relax_start"]) > 1e-3, "Relax moved the bone (%.3f)" % an_rig().pose.bones["Arm"].location.x)
    check(not any(op.bl_idname == "POSE_OT_relax" for op in window().modal_operators), "Relax ended")
    check(not tracebacks(), "Python error in Push / Relax")
    bpy.context.scene.frame_set(1)


# --- Tween on bones through the key, then the dock's Breakdown button
@step
def anim_bone_tween():
    bpy.context.scene.frame_set(6)
    an_press("m3d.tween", factor=0.5)


@step
def anim_bone_tween_check():
    rig = an_rig()
    check(abs(rig.pose.bones["Arm"].location.x - 0.5) < 0.1, "Tween on the selected bone (x = %.3f)" % rig.pose.bones["Arm"].location.x)
    check(6 in an_keys(rig, 'pose.bones["Arm"].location'), "...keys the bone: %s" % an_keys(rig, 'pose.bones["Arm"].location'))
    check(6 not in an_keys(rig, 'pose.bones["Root"].location'), "...and only the selected bone")


# --- Motion paths and ghost curves
@step
def anim_paths():
    press_ok("m3d.dock_page", _area=an_dock(), tab="anim_motion")
    an_press("m3d.anim_paths", action='CALCULATE')


@step
def anim_paths_check():
    check(an_rig().pose.animation_visualization.motion_path.has_motion_paths, "Motion path calculated for the bone")
    an_press("m3d.anim_paths", action='UPDATE')
    an_press("m3d.anim_paths", action='CLEAR')


@step
def anim_paths_clear_check():
    check(not an_rig().pose.animation_visualization.motion_path.has_motion_paths, "...and cleared")
    an_press("m3d.anim_graph", action='GHOST_CREATE')
    area = m3d_anim.bottom_area(window().screen)
    check(area.ui_type == 'DOPESHEET', "ghost curves leave the bottom editor as it was")
    an_press("m3d.anim_graph", action='GHOST_CLEAR')
    check(not tracebacks(), "Python error with motion paths / ghost curves")


# --- Layers: push down, additive layer
@step
def anim_layers():
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    m3d_rig._select_only(bpy.context, an_box())
    press_ok("m3d.dock_page", _area=an_dock(), tab="anim_layers")
    an_press("m3d.anim_layer", action='PUSH_DOWN')


@step
def anim_layers_check():
    ad = an_box().animation_data
    check(ad.action is None and len(ad.nla_tracks) == 1, "Layers: Push Down (action %s, tracks %d, active %s, mode %s)" % (
        ad.action, len(ad.nla_tracks), bpy.context.active_object, bpy.context.mode))
    an_press("m3d.anim_layer", action='ADD_ADDITIVE')


@step
def anim_layers_check2():
    ad = an_box().animation_data
    check(ad.action is not None and ad.action_blend_type == 'ADD', "Layers: Add Additive Layer (%s %s %d)" % (ad.action, ad.action_blend_type, len(ad.nla_tracks)))
    for a in window().screen.areas:
        a.tag_redraw()


@step
def anim_layers_drawn():
    check(not tracebacks(), "Python error drawing the Layers tab")
    bpy.data.objects["Box"].animation_data.action = None   # Leave the cube with only the layer below.


# --- Playblast: three tiny frames, the output settings stay as they were
@step
def anim_playblast():
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 3
    GIZMO["pb_before"] = (scene.render.filepath, scene.render.resolution_percentage, scene.render.image_settings.file_format,
                          scene.frame_current, scene.frame_start, scene.frame_end)
    scene.m3d_anim.playblast_dir = tempfile.mkdtemp(prefix="m3d_gui_pb_")
    scene.m3d_anim.playblast_percent = 10
    scene.m3d_anim.playblast_format = 'IMAGES'
    GIZMO["pb_overlays"] = m3d_anim.playblast_area(window().screen).spaces.active.overlay.show_overlays
    check(an_status("m3d.playblast", play=False) == {'RUNNING_MODAL'}, "Playblast button runs")


step(wait_until(lambda: not m3d_anim.playblast_state["running"], "the Playblast to finish", tries=60))


@step
def anim_playblast_check():
    scene = bpy.context.scene
    files = m3d_anim.playblast_state["files"]
    check(len(files) == 3 and all(os.path.getsize(f) > 0 for f in files), "Playblast wrote 3 frames: %s" % files)
    after = (scene.render.filepath, scene.render.resolution_percentage, scene.render.image_settings.file_format, scene.frame_current,
             scene.frame_start, scene.frame_end)
    check(after == GIZMO["pb_before"], "the render output settings are put back: %s vs %s" % (after, GIZMO["pb_before"]))
    GIZMO["pb_base"] = base = bpy.path.clean_name(bpy.path.display_name_from_filepath(bpy.data.filepath) or "playblast")
    check(all(os.path.basename(f).startswith(base + "_v001_") for f in files), "...named after the file, version 1: %s" % files)
    check(scene.m3d_anim.playblast_note == "Last playblast: %s_v001 (3 frames)" % base, "Playblast reports: %r" % scene.m3d_anim.playblast_note)
    check(m3d_anim.playblast_area(window().screen).spaces.active.overlay.show_overlays == GIZMO["pb_overlays"],
          "the overlays are back after a Meshes Only playblast")
    check(not tracebacks(), "Python error in the Playblast")
    scene.m3d_anim.playblast_format = 'MOVIE'   # A movie of the same three frames, tiny: the next version.
    check(an_status("m3d.playblast", play=False) == {'RUNNING_MODAL'}, "Playblast button runs for a movie")


step(wait_until(lambda: not m3d_anim.playblast_state["running"], "the movie Playblast to finish", tries=60))


@step
def anim_playblast_movie_check():
    scene = bpy.context.scene
    files = m3d_anim.playblast_state["files"]
    check(len(files) == 1 and os.path.basename(files[0]) == GIZMO["pb_base"] + "_v002.mp4" and os.path.getsize(files[0]) > 0,
          "Movie playblast: one .mp4, version 2: %s" % files)
    after = (scene.render.filepath, scene.render.resolution_percentage, scene.render.image_settings.file_format, scene.frame_current,
             scene.frame_start, scene.frame_end)
    check(after == GIZMO["pb_before"] and scene.render.image_settings.media_type == 'IMAGE', "...the output settings are put back: %s" % (after,))
    check(not tracebacks(), "Python error in the movie Playblast")
    scene.frame_start, scene.frame_end = 1, 24


# --- Every tab draws, in Object and Pose Mode, with the Graph Editor and the Dope Sheet
def _anim_tab_steps():
    for mode in ('OBJECT', 'POSE'):
        for editor in ('DOPESHEET', 'GRAPH'):
            for tab in m3d_workspace.DOCK_TABS['ANIM']['RIGHT']:
                def show(tab=tab, mode=mode, editor=editor):
                    bpy.ops.m3d.rig_mode(mode='OBJECT')
                    m3d_rig._select_only(bpy.context, an_rig() if mode == 'POSE' else an_box())
                    bpy.ops.m3d.rig_mode(mode=mode)
                    an_status("m3d.anim_editor", editor=editor)
                    press_ok("m3d.dock_page", _area=an_dock(), tab=tab.id)
                    for a in window().screen.areas:
                        a.tag_redraw()

                def check_draw(tab=tab, mode=mode, editor=editor):
                    page = window().workspace.m3d_page_right
                    check(tab.page is None or page == tab.page, "dock tab %s did not open its page" % tab.id)
                    check(an_dock().spaces.active.context == tab.context, "dock tab %s context" % tab.id)
                    check(not tracebacks(), "Python error while drawing the Animation tab %s in %s with the %s" % (tab.id, mode, editor))
                show.__name__ = "anim_show_%s_%s_%s" % (tab.id, mode, editor)
                check_draw.__name__ = "anim_drawn_%s_%s_%s" % (tab.id, mode, editor)
                yield show
                yield check_draw


for _fn in _anim_tab_steps():
    step(_fn)


# --- Pick: Select All Controls; Tween & Poses: Mirror (the dock's buttons)
@step
def anim_select_controls():
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    m3d_rig._select_only(bpy.context, an_rig())
    bpy.ops.m3d.rig_mode(mode='POSE')
    rig = an_rig()
    for pb in rig.pose.bones:
        pb.select = pb.name == "Arm"
    press_ok("m3d.dock_page", _area=an_dock(), tab="anim_pick")
    an_press("pose.select_all", action='SELECT')


@step
def anim_select_controls_check():
    check(all(pb.select for pb in an_rig().pose.bones), "Select All Controls selects every bone")
    rig = an_rig()
    for pb in rig.pose.bones:
        pb.select = pb.name == "Arm"
    rig.pose.bones["Arm"].location.x = 0.25
    press_ok("m3d.dock_page", _area=an_dock(), tab="anim_tween")
    an_press("m3d.anim_mirror_pose", whole=True)


@step
def anim_mirror_check():
    check(abs(an_rig().pose.bones["Arm"].location.x + 0.25) < 1e-4, "Mirror All flips a middle bone (x = %.3f)" % an_rig().pose.bones["Arm"].location.x)
    check(not tracebacks(), "Python error with Select All Controls / Mirror")
    bpy.context.scene.frame_set(1)


# --- F6 with a bound mesh active: its skeleton in Pose Mode
@step
def anim_f6_bound():
    bpy.ops.m3d.workspace(kind='MODEL')
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(-1.5, 0, 1))
    body = bpy.context.active_object
    body.name = "Body"
    body.modifiers.new("Armature", 'ARMATURE').object = an_rig()
    m3d_rig._select_only(bpy.context, body)
    c = (window().width // 2, window().height // 2)
    event('MOUSEMOVE', xy=c)
    event('F6', 'PRESS', c)
    event('F6', 'RELEASE', c)


step(wait_until(lambda: window().workspace.name == "Animation", "F6 with a bound mesh"))


@step
def anim_f6_bound_check():
    check(bpy.context.active_object == an_rig() and bpy.context.mode == 'POSE',
          "F6 with a bound mesh active enters Pose Mode on its skeleton (%s, %s)" % (bpy.context.active_object, bpy.context.mode))
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    bpy.data.objects.remove(bpy.data.objects["Body"])
    check(not tracebacks(), "Python error with F6 on a bound mesh")


@step
def anim_shelves():
    for mode in ('POSE', 'OBJECT'):
        bpy.ops.m3d.rig_mode(mode=mode)
        for key in m3d_ui.shelves_for('ANIM'):
            bpy.context.window_manager.m3d_shelf = key
            for a in window().screen.areas:
                a.tag_redraw()


@step
def anim_shelves_check():
    check(not tracebacks(), "Python error drawing the Animation shelves / Status Line")
    bpy.context.window_manager.m3d_shelf = 'ANIM_ANIMATE'
    an_status("m3d.anim_editor", editor='DOPESHEET')
    ws = window().workspace
    ws.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')
    check(not tracebacks(), "Python error in the Animation workspace tests")


# ----------------------------------------------------------------------------------------------------
# Phase 6: Rendering workspace with a small lit scene: layout, F7, engine / quality buttons, camera from view, lights from the
# shelf, the light table, HDRI, IPR on and off, Shift+F12 / Ctrl+Shift+F12 / Alt+F12 at a tiny size, every tab.

import shutil

import m3d_render
from bpy.app.handlers import persistent
from mathutils import Euler


def rn_dock():
    return props_areas()[0]


def rn_space():
    return an_view()[0].spaces.active


def rn_press(idname, **props):
    return press_ok(idname, _area=rn_dock(), **props)


def rn_snapshot():
    scene = bpy.context.scene
    r = scene.render
    return {"engine": r.engine, "x": r.resolution_x, "y": r.resolution_y, "pct": r.resolution_percentage, "path": r.filepath,
            "fmt": r.image_settings.file_format, "cy": scene.cycles.samples, "ev": scene.eevee.taa_render_samples,
            "frame": scene.frame_current, "start": scene.frame_start, "end": scene.frame_end, "camera": scene.camera,
            "world": scene.world, "preset": scene.m3d_render.preset, "exposure": scene.view_settings.exposure,
            "bounces": scene.cycles.max_bounces, "denoise": scene.cycles.use_denoising, "lights": len(m3d_render.scene_lights(scene))}


def rn_image_area():
    return m3d_render.render_view_area(window().screen)


def rn_matrix_close(a, b, tol=1e-3):
    return all(abs(x - y) < tol for ra, rb in zip(a, b) for x, y in zip(ra, rb))


RN_DONE = {"renders": 0}


@persistent
def rn_render_done(*_args):
    RN_DONE["renders"] += 1


bpy.app.handlers.render_complete.append(rn_render_done)
bpy.app.handlers.render_cancel.append(rn_render_done)


@step
def rn_setup():
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end, scene.frame_current = 1, 2, 1
    scene.camera = None
    mat = bpy.data.materials.new("RnGuiMat")
    mat.use_nodes = True
    bpy.ops.mesh.primitive_plane_add(size=8)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
    box = bpy.context.active_object
    box.name = "Box"
    box.data.materials.append(mat)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(1.5, 0, 0.5))
    bpy.context.window_manager.m3d_menu_set = 'MODELING'
    c = (window().width // 2, window().height // 2)
    event('MOUSEMOVE', xy=c)
    event('F7', 'PRESS', c)
    event('F7', 'RELEASE', c)


step(wait_until(lambda: window().workspace.name == "Rendering", "F7 to switch to Rendering"))


@step
def rn_f7_check():
    check(window().workspace.name == "Rendering" and bpy.context.mode == 'OBJECT', "F7 enters Rendering in Object Mode (%s)" % bpy.context.mode)
    check(bpy.context.window_manager.m3d_menu_set == 'RENDERING', "F7 shows the Rendering menu set")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.workspace_reset()   # The earlier dock tests moved this workspace's tabs: the factory layout is checked.


step(wait_until(lambda: [w.name for w in bpy.data.workspaces if w.name.startswith("Rendering")] == ["Rendering"]
                and window().workspace.name == "Rendering", "Reset Workspace to finish"))


@step
def rn_layout_check():
    screen = window().screen
    views = [a for a in screen.areas if a.type == 'VIEW_3D']
    image = rn_image_area()
    dock = rn_dock()
    check(len(views) == 1 and image is not None, "Rendering: a 3D view and a Render View")
    check(views and image and views[0].x < image.x and views[0].width > 600 and image.width > 500,
          "Rendering: the 3D view is left of the Render View, both wide (%s, %s)" % (views and views[0].width, image and image.width))
    check(views and views[0].spaces.active.shading.type == 'MATERIAL', "the 3D view starts in Material Preview (Rendered is heavy)")
    check(image and image.spaces.active.image is not None and image.spaces.active.image.type == 'RENDER_RESULT',
          "the Render View shows the Render Result")
    if image is not None:
        with bpy.context.temp_override(window=window(), area=image, region=next(r for r in image.regions if r.type == 'WINDOW')):
            check(m3d_render.render_view_empty(bpy.context) == (not m3d_render._rendered[0]),
                  "the Render View says how to render until there is a render")
            check(image.spaces.active.mode == 'VIEW' and not tracebacks(), "...drawn without errors")
    check(len(props_areas()) == 1 and dock.spaces.active.context == 'MODELING_TOOLKIT' and dock.width >= 700,
          "one dock on its pages (%s, %d px)" % (dock.spaces.active.context, dock.width))
    check(window().workspace.m3d_page_right in ("", "render_camera"), "the dock opens on Camera (%s)" % window().workspace.m3d_page_right)
    check(m3d_ui.shelf_key(bpy.context.window_manager, 'RENDER') == 'RENDER_LIGHTS', "Lights shelf tab first")
    check(window().workspace.object_mode == 'OBJECT', "workspace enters Object Mode")
    check(not [a for a in screen.areas if a.type == 'OUTLINER'], "Rendering: no Outliner")
    check(not tracebacks(), "Python error drawing the Rendering workspace")


# --- Engine and quality preset buttons (Status Line): both engines
@step
def rn_quality_presets():
    scene = bpy.context.scene
    scene.cycles.device = 'CPU'
    GIZMO["rn_start"] = rn_snapshot()
    for engine in ('CYCLES', 'BLENDER_EEVEE'):
        scene.render.engine = engine   # The Status Line's engine buttons set this.
        for key, samples in (('DRAFT', (32, 16)), ('MEDIUM', (128, 64)), ('FINAL', (512, 256))):
            an_status("m3d.render_preset", preset=key)
            check((scene.cycles.samples, scene.eevee.taa_render_samples) == samples and m3d_render.current_quality(scene) == key,
                  "Status Line %s button with %s: %s" % (key, engine, (scene.cycles.samples, scene.eevee.taa_render_samples)))
    scene.cycles.device = 'CPU'   # (a preset picks the GPU when one passes the test bake: the small renders below stay on the CPU)
    scene.eevee.taa_render_samples += 1
    check(m3d_render.current_quality(scene) == 'CUSTOM', "an edit reads Custom")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_quality_drawn():
    check(not tracebacks(), "Python error drawing the quality presets / Custom")
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
    check(rn_space().shading.use_scene_lights and window().workspace.m3d_layout == m3d_render.RENDER_LAYOUT,
          "F7's Material Preview shows the scene's lights")


# --- Camera from view
@step
def rn_camera_view_setup():
    rv3d = rn_space().region_3d
    rv3d.view_perspective = 'PERSP'
    rv3d.view_location = (1.0, 0.5, 0.5)
    rv3d.view_rotation = Euler((1.2, 0.0, 0.6)).to_quaternion()
    rv3d.view_distance = 7.0
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_camera_view_redrawn():
    pass   # The view matrix is updated by the viewport redraw.


@step
def rn_camera_view_new():
    bpy.context.scene.camera = None
    check(rn_press("m3d.render_camera_from_view", mode='NEW') is not None, "New Camera from View runs from the dock")


@step
def rn_camera_view_check():
    scene = bpy.context.scene
    cam, rv3d = scene.camera, rn_space().region_3d
    check(cam is not None and cam.type == 'CAMERA' and cam == bpy.context.active_object, "New Camera from View: the scene camera is the new, active object")
    if cam is not None:
        check(rn_matrix_close(cam.matrix_world, rv3d.view_matrix.inverted()), "...at the viewport's view")
        target = cam.matrix_world @ Vector((0, 0, -7.0))
        check((target - Vector((1.0, 0.5, 0.5))).length < 0.01, "...looking at what the viewport looked at (%s)" % (target,))
        GIZMO["rn_cam"] = cam.name
    rv3d.view_location = (-1.0, 0.0, 1.0)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_camera_view_match():
    rn_press("m3d.render_camera_from_view", mode='MATCH')


@step
def rn_camera_view_match_check():
    scene = bpy.context.scene
    rv3d = rn_space().region_3d
    check(scene.camera.name == GIZMO["rn_cam"] and rn_matrix_close(scene.camera.matrix_world, rv3d.view_matrix.inverted()),
          "Match Camera to View moves the scene camera to the new view")
    rn_press("view3d.view_camera")


@step
def rn_camera_look_through():
    check(rn_space().region_3d.view_perspective == 'CAMERA', "Look Through Camera enters the camera view")
    rn_press("view3d.view_camera")


@step
def rn_camera_look_back():
    check(rn_space().region_3d.view_perspective == 'PERSP', "...and the button leaves it again")
    scene = bpy.context.scene
    scene.camera.data.dof.use_dof = True   # The Camera tab's depth of field, guides and border draw (checked below by every tab)
    scene.camera.data.show_composition_thirds = True
    scene.render.use_border = True
    scene.render.use_border = False


# --- Lights from the shelf, the light table
@step
def rn_lights_shelf():
    bpy.context.window_manager.m3d_shelf = 'RENDER_LIGHTS'
    bpy.context.scene.cursor.location = (0, 0, 0)
    for kind in ('POINT', 'SPOT', 'AREA', 'SUN'):
        check(an_status("m3d.render_light_add", kind=kind) == {'FINISHED'}, "shelf button adds a %s light" % kind)
    rn_press("m3d.dock_page", tab="render_lighting")


@step
def rn_lights_check():
    lights = m3d_render.scene_lights(bpy.context.scene)
    check({o.data.type for o in lights} == {'POINT', 'SPOT', 'AREA', 'SUN'} and all(o.location.z > 3.5 for o in lights),
          "four lights above the origin: %s" % [(o.name, o.data.type) for o in lights])
    check(window().workspace.m3d_page_right == "render_lighting", "the dock shows the Lighting tab")
    GIZMO["rn_point"] = next(o.name for o in lights if o.data.type == 'POINT')
    point = bpy.data.objects[GIZMO["rn_point"]]
    # Table edits: power, color, shadow, render and viewport visibility.
    point.data.energy = 777.0
    point.data.color = (1.0, 0.4, 0.2)
    point.data.use_shadow = False
    point.hide_render = True
    check(rn_press("m3d.render_light", name=point.name, action='VISIBLE') is not None and point.hide_get(), "the table's eye hides the light")
    # A light in an excluded collection, one in a hidden collection, two objects sharing a light.
    layer = bpy.context.view_layer
    for name, hidden in (("GuiExcluded", False), ("GuiHidden", True)):
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
        lamp = bpy.data.objects.new(name + "Lamp", bpy.data.lights.new(name + "Lamp", 'POINT'))
        coll.objects.link(lamp)
        if hidden:
            layer.layer_collection.children[name].hide_viewport = True
        else:
            layer.layer_collection.children[name].exclude = True
    twin = bpy.data.objects.new("GuiTwin", point.data)
    bpy.context.scene.collection.objects.link(twin)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_light_table_drawn():
    point = bpy.data.objects[GIZMO["rn_point"]]
    check(point.data.energy == 777.0 and not point.data.use_shadow and point.hide_render and point.hide_get(), "light table edits stuck")
    check(not tracebacks(), "Python error drawing the light table (hidden, excluded and shared lights)")
    check(m3d_render.light_state(bpy.context.view_layer, bpy.data.objects["GuiExcludedLamp"]) == 'EXCLUDED'
          and m3d_render.light_state(bpy.context.view_layer, bpy.data.objects["GuiHiddenLamp"]) == 'HIDDEN', "table states for the collection lights")
    rn_press("m3d.render_light", name="GuiTwin", action='SINGLE')
    rn_press("m3d.render_light", name=point.name, action='VISIBLE')
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_light_table_after():
    point = bpy.data.objects[GIZMO["rn_point"]]
    check(not point.hide_get() and point.data.users == 1, "the eye shows it again; the twin got its own light")
    check(not tracebacks(), "Python error drawing the light table after the buttons")
    for name in ("GuiExcludedLamp", "GuiHiddenLamp", "GuiTwin"):
        bpy.data.objects.remove(bpy.data.objects[name])
    for name in ("GuiExcluded", "GuiHidden"):
        bpy.data.collections.remove(bpy.data.collections[name])
    point.hide_render = False
    point.data.use_shadow = True


# --- HDRI from Blender's studio lights
@step
def rn_hdri():
    scene = bpy.context.scene
    GIZMO["rn_world"] = scene.world
    bundled = m3d_render.bundled_hdris()
    check(len(bundled) >= 4, "studio HDRIs are available (%d)" % len(bundled))
    GIZMO["rn_hdri"] = bundled[0][1]
    check(rn_press("m3d.hdri_setup", filepath=GIZMO["rn_hdri"]) is not None, "an HDRI button runs")


@step
def rn_hdri_check():
    scene = bpy.context.scene
    nodes = m3d_render.hdri_nodes(scene.world)
    check(scene.world.name == "m3dHDRI" and nodes is not None and nodes["env"].image is not None, "the HDRI world is assigned")
    check(scene.m3d_render.previous_world == GIZMO["rn_world"], "the old world is kept")
    check(rn_space().shading.use_scene_world, "...and F7's Material Preview shows the sky")
    scene.m3d_render.hdri_rotation = 1.2
    scene.m3d_render.hdri_strength = 1.5
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_hdri_drawn():
    check(not tracebacks(), "Python error drawing the HDRI controls")
    scene = bpy.context.scene
    nodes = m3d_render.hdri_nodes(scene.world)
    check(abs(nodes["mapping"].inputs["Rotation"].default_value[2] - 1.2) < 1e-4, "HDRI rotation writes the mapping")


# --- IPR on and off, both engines (the preview samples are kept low)
def _ipr_steps():
    for engine in ('BLENDER_EEVEE', 'CYCLES'):
        def on(engine=engine):
            scene = bpy.context.scene
            scene.render.engine = engine
            scene.cycles.preview_samples = 2
            GIZMO["rn_shading"] = rn_space().shading.type
            an_status("m3d.render_ipr")

        def off(engine=engine):
            check(rn_space().shading.type == 'RENDERED', "IPR turns on the Rendered viewport (%s)" % engine)
            an_status("m3d.render_ipr")

        def after(engine=engine):
            check(rn_space().shading.type == GIZMO["rn_shading"] == 'MATERIAL', "IPR off returns to Material Preview (%s)" % engine)
            check(not tracebacks(), "Python error in the %s IPR" % engine)
        on.__name__, off.__name__, after.__name__ = "rn_ipr_on_" + engine, "rn_ipr_off_" + engine, "rn_ipr_after_" + engine
        yield on
        yield off
        yield after


for _fn in _ipr_steps():
    step(_fn)


# --- Shift+F12: a still at 48 x 32 with Cycles; Ctrl+Shift+F12: two frames with EEVEE; Alt+F12: the Render View
@step
def rn_render_still_start():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 48, 32, 100
    scene.cycles.samples = scene.eevee.taa_render_samples = 1
    scene.camera = bpy.data.objects[GIZMO["rn_cam"]]
    rn_image_area().spaces.active.image = None
    GIZMO["rn_before"], RN_DONE["renders"] = rn_snapshot(), 0
    GIZMO["rn_windows"] = len(bpy.context.window_manager.windows)
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('F12', True, shift=True)


@step
def rn_render_still_keyup():
    an_mod_key('F12', False, shift=True)


step(wait_until(lambda: RN_DONE["renders"] >= 1 and not bpy.app.is_job_running('RENDER'), "Shift+F12 to render", tries=60))


@step
def rn_render_still_check():
    image = rn_image_area().spaces.active.image
    check(RN_DONE["renders"] >= 1, "Shift+F12 rendered the frame")
    check(image is not None and image.type == 'RENDER_RESULT', "the render shows in the Render View")
    with bpy.context.temp_override(window=window(), area=rn_image_area()):
        check(not m3d_render.render_view_empty(bpy.context), "...and the empty Render View's hint is gone")
    check(len(bpy.context.window_manager.windows) == GIZMO["rn_windows"], "...without a new window (%d windows)" % len(bpy.context.window_manager.windows))
    shot = os.path.join(tempfile.mkdtemp(prefix="m3d_gui_shot_"), "still.png")
    image.save_render(shot)   # (the Render Result reports no size itself)
    saved = bpy.data.images.load(shot)
    check(tuple(saved.size) == (48, 32), "...at 48 x 32 (%s)" % (tuple(saved.size),))
    bpy.data.images.remove(saved)
    shutil.rmtree(os.path.dirname(shot), ignore_errors=True)
    check(rn_snapshot() == GIZMO["rn_before"], "the render settings are as they were: %s" % {k: (v, rn_snapshot()[k]) for k, v in GIZMO["rn_before"].items() if rn_snapshot()[k] != v})
    check(not tracebacks(), "Python error in the still render")


@step
def rn_render_anim_start():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    GIZMO["rn_dir"] = tempfile.mkdtemp(prefix="m3d_gui_render_")
    scene.render.filepath = os.path.join(GIZMO["rn_dir"], "rn_")
    GIZMO["rn_before"], RN_DONE["renders"] = rn_snapshot(), 0
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('F12', True, shift=True, ctrl=True)


@step
def rn_render_anim_keyup():
    an_mod_key('F12', False, shift=True, ctrl=True)


step(wait_until(lambda: RN_DONE["renders"] >= 1 and not bpy.app.is_job_running('RENDER'), "Ctrl+Shift+F12 to render", tries=80))
step(wait_until(lambda: m3d_render._animation["scene"] is None, "the report after the animation render"))


@step
def rn_render_anim_report():
    event('ESC', 'PRESS', an_xy())   # (closes the "Rendered 2 frames ... Open Folder" popup)
    event('ESC', 'RELEASE', an_xy())


@step
def rn_render_anim_check():
    files = sorted(os.listdir(GIZMO["rn_dir"]))
    check(len(files) == 2 and all(os.path.getsize(os.path.join(GIZMO["rn_dir"], f)) > 0 for f in files),
          "Ctrl+Shift+F12 rendered the two frames: %s" % files)
    scene = bpy.context.scene
    now, before = rn_snapshot(), GIZMO["rn_before"]
    check(now == before, "the animation render left the settings as they were: %s" % {k: (v, now[k]) for k, v in before.items() if now[k] != v})
    check(not tracebacks(), "Python error in the animation render")
    scene.render.filepath = GIZMO["rn_start"]["path"]
    rn_image_area().spaces.active.image = None
    event('MOUSEMOVE', xy=an_xy())
    an_mod_key('F12', True, alt=True)


@step
def rn_render_view_key():
    an_mod_key('F12', False, alt=True)


@step
def rn_render_view_check():
    image = rn_image_area().spaces.active.image
    check(image is not None and image.type == 'RENDER_RESULT', "Alt+F12 shows the Render Result in the Render View")
    check(len(bpy.context.window_manager.windows) == GIZMO["rn_windows"], "...in the same window")
    an_status("m3d.render_view")
    check(not tracebacks(), "Python error with Render View")


# --- Before a render: frames that are there already, a hidden camera (each opens the question; Escape renders nothing)
@step
def rn_ask_frames():
    scene = bpy.context.scene
    scene.render.filepath = os.path.join(GIZMO["rn_dir"], "rn_")
    RN_DONE["renders"] = 0
    event('MOUSEMOVE', xy=an_xy())
    check(an_status("m3d.render", animation=True) == {'RUNNING_MODAL'}, "Render Animation over frames that are there asks first")


@step
def rn_ask_frames_close():
    event('ESC', 'PRESS', an_xy())
    event('ESC', 'RELEASE', an_xy())


@step
def rn_ask_camera():
    check(RN_DONE["renders"] == 0 and not bpy.app.is_job_running('RENDER'), "...Escape renders nothing")
    scene = bpy.context.scene
    scene.render.filepath = GIZMO["rn_start"]["path"]
    scene.camera.hide_set(True)
    check(an_status("m3d.render") == {'RUNNING_MODAL'}, "a render from a hidden camera asks first")


@step
def rn_ask_camera_close():
    event('ESC', 'PRESS', an_xy())
    event('ESC', 'RELEASE', an_xy())


@step
def rn_ask_done():
    check(RN_DONE["renders"] == 0 and not bpy.app.is_job_running('RENDER'), "...Escape renders nothing")
    bpy.context.scene.camera.hide_set(False)
    check(not tracebacks(), "Python error in the render questions")


# --- New Render Layer from Selection from the Passes & Layers tab
@step
def rn_layer_from_selection():
    scene = bpy.context.scene
    props = bpy.data.collections.new("RnProps")   # (the sphere in a collection: objects in none are in every layer)
    scene.collection.children.link(props)
    sphere = next(o for o in scene.collection.objects if o.name.startswith("Sphere"))
    props.objects.link(sphere)
    scene.collection.objects.unlink(sphere)
    GIZMO["rn_sphere"] = sphere.name
    bpy.ops.object.select_all(action='DESELECT')
    box = bpy.data.objects["Box"]
    box.select_set(True)
    bpy.context.view_layer.objects.active = box
    rn_press("m3d.dock_page", tab="render_passes")
    rn_press("m3d.render_layer_from_selection")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_layer_from_selection_check():
    layer = window().view_layer
    sphere = bpy.data.objects[GIZMO["rn_sphere"]]
    check(layer.name == "Box Layer" and layer.objects.get("Box") and not layer.objects.get(sphere.name),
          "New Render Layer from Selection: the window shows a layer with the Box, not the sphere (%s)" % layer.name)
    check(not tracebacks(), "Python error drawing the new render layer")
    scene = bpy.context.scene
    window().view_layer = scene.view_layers[0]
    scene.view_layers.remove(layer)
    scene.collection.objects.link(sphere)
    for name in ("Box Layer", "RnProps"):
        bpy.data.collections.remove(bpy.data.collections[name])


# --- Restore what the tests changed in the scene, then every tab with a few kinds of selection
@step
def rn_restore_settings():
    scene = bpy.context.scene
    start = GIZMO["rn_start"]
    r = scene.render
    r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage = start["engine"], start["x"], start["y"], start["pct"]
    scene.cycles.samples, scene.eevee.taa_render_samples = start["cy"], start["ev"]
    scene.frame_start, scene.frame_end = 1, 24
    shutil.rmtree(GIZMO["rn_dir"], ignore_errors=True)


def _render_tab_steps():
    for engine in ('BLENDER_EEVEE', 'CYCLES'):
        for what in ('Box', 'Light', None):
            for tab in m3d_workspace.DOCK_TABS['RENDER']['RIGHT']:
                def show(tab=tab, engine=engine, what=what):
                    bpy.context.scene.render.engine = engine
                    bpy.ops.object.select_all(action='DESELECT')
                    ob = bpy.data.objects.get(GIZMO["rn_point"] if what == 'Light' else what) if what else None
                    bpy.context.view_layer.objects.active = ob
                    if ob is not None:
                        ob.select_set(True)
                    rn_press("m3d.dock_page", tab=tab.id)
                    for a in window().screen.areas:
                        a.tag_redraw()

                def check_draw(tab=tab, engine=engine, what=what):
                    check(window().workspace.m3d_page_right == tab.page, "dock tab %s did not open its page" % tab.id)
                    check(rn_dock().spaces.active.context == tab.context, "dock tab %s context" % tab.id)
                    check(not tracebacks(), "Python error while drawing the Rendering tab %s with %s and %s" % (tab.id, engine, what))
                show.__name__ = "rn_show_%s_%s_%s" % (tab.id, engine, what)
                check_draw.__name__ = "rn_drawn_%s_%s_%s" % (tab.id, engine, what)
                yield show
                yield check_draw


for _fn in _render_tab_steps():
    step(_fn)


@step
def rn_shelves():
    for key in m3d_ui.shelves_for('RENDER'):
        bpy.context.window_manager.m3d_shelf = key
        for a in window().screen.areas:
            a.tag_redraw()


@step
def rn_shelves_check():
    check(not tracebacks(), "Python error drawing the Rendering shelves / Status Line")
    bpy.context.window_manager.m3d_shelf = 'RENDER_LIGHTS'
    bpy.context.scene.render.engine = GIZMO["rn_start"]["engine"]
    window().workspace.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')
    check(not tracebacks(), "Python error in the Rendering workspace tests")


# ----------------------------------------------------------------------------------------------------
# High poly / low poly in the real window: F1 <-> F2 with a paired mesh (the F-keys, the workspace picker), Edit High Poly,
# the face limit of UV and Texture, Create High Poly from the Sculpt Status Line and its Undo.
import m3d_pair as HPR


def hp_in(kind):
    return m3d_workspace.workspace_kind(window().workspace) == kind


def hp_press(key):
    xy = (window().width // 2, window().height // 2)
    event(key, 'PRESS', xy)
    event(key, 'RELEASE', xy)


def hp_ob(name):
    return bpy.data.objects[name]


def hp_viewport():
    win, area, region = view3d()
    return bpy.context.temp_override(window=win, area=area, region=region)


def hp_state():
    return {n: (o.hide_get(), o.m3d_pair.parked, o.select_get(), o.mode) for n, o in bpy.data.objects.items()}


@step
def hp_to_modeling():
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling for the high poly tests"))


@step
def hp_scene():
    with hp_viewport():
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.m3d.add_primitive(kind='CUBE')
        bpy.context.active_object.name = "Plain"
        bpy.context.active_object.location = (3, 0, 0)
        bpy.ops.m3d.add_primitive(kind='SPHERE')
        bpy.context.active_object.name = "Sword"
        for o in bpy.data.objects:
            o.select_set(o.name == "Sword")
        check(bpy.ops.m3d.hp_create(detail='MULTIRES', levels=2) == {'FINISHED'}, "Create High Poly in the window")
        check(hp_ob("Sword_high").m3d_pair.role == 'HIGH' and hp_ob("Sword").m3d_pair.role == 'LOW', "the pair is made")
        check(bpy.ops.m3d.hp_park() == {'FINISHED'}, "Park High Poly in the window")
        bpy.ops.view3d.view_all(center=True)
    win, _area, region = view3d()
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])
    GIZMO["hp_plain"] = hp_state()["Plain"]


@step
def hp_f2():
    check(hp_ob("Sword_high").hide_get() and bpy.context.active_object == hp_ob("Sword"), "(the high poly starts parked, the low poly active)")
    hp_press('F2')


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT', "F2 to enter Sculpt Mode"))


@step
def hp_f2_check():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(bpy.context.mode == 'SCULPT' and bpy.context.active_object == high and high.mode == 'SCULPT',
          "F2: Sculpt Mode starts on the high poly (%s, %s)" % (bpy.context.mode, bpy.context.active_object.name))
    check(not high.hide_get() and high.select_get() and low.hide_get() and low.m3d_pair.parked and not low.select_get(),
          "F2: the high poly is shown and selected, the low poly parked: %s" % hp_state())
    check(hp_state()["Plain"] == GIZMO["hp_plain"], "F2: a mesh without a role is untouched")
    check(not tracebacks(), "Python error drawing the Sculpt workspace with a pair")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def hp_f1():
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 to leave Sculpt Mode"))


@step
def hp_f1_check():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(bpy.context.mode == 'OBJECT' and high.mode == 'OBJECT', "F1: Object Mode (%s)" % bpy.context.mode)
    check(high.hide_get() and high.m3d_pair.parked and not high.select_get(), "F1: the high poly is parked: %s" % hp_state())
    check(not low.hide_get() and low.select_get() and bpy.context.active_object == low and not low.m3d_pair.parked,
          "F1: the low poly is shown, selected and active")
    check(hp_state()["Plain"] == GIZMO["hp_plain"], "F1: a mesh without a role is untouched")
    check(not tracebacks(), "Python error drawing Modeling with a pair")


# Switched some other way (the workspace picker): the timer does the same, a little late.
@step
def hp_picker_sculpt():
    window().workspace = bpy.data.workspaces["Sculpt"]


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT' and bpy.context.active_object == hp_ob("Sword_high"),
                "the workspace picker to enter Sculpt Mode on the high poly"))


@step
def hp_picker_sculpt_check():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(not high.hide_get() and low.hide_get() and high.mode == 'SCULPT' and low.mode == 'OBJECT',
          "picker: the high poly is sculpted, the low poly parked: %s" % hp_state())
    window().workspace = bpy.data.workspaces["Modeling"]


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT' and hp_ob("Sword_high").hide_get(), "the workspace picker to leave Sculpt"))


@step
def hp_picker_model_check():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(high.hide_get() and high.m3d_pair.parked and not low.hide_get() and bpy.context.active_object == low and high.mode == 'OBJECT',
          "picker: the high poly is parked again, the low poly active: %s" % hp_state())
    check(not tracebacks(), "Python error in the fallback")


# Sculpt straight to UV: Sculpt Mode ends, the high poly is parked and Edit Mode opens on the low poly.
@step
def hp_sculpt_uv():
    hp_press('F2')


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT', "F2 before F3"))


@step
def hp_sculpt_uv_f3():
    hp_press('F3')


step(wait_until(lambda: hp_in('UV') and bpy.context.mode == 'EDIT_MESH', "F3 from Sculpt to enter Edit Mode on the low poly"))


@step
def hp_sculpt_uv_check():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(high.hide_get() and high.m3d_pair.parked and bpy.context.active_object == low and low.mode == 'EDIT' and high.mode == 'OBJECT',
          "F3 from Sculpt: the high poly is parked, the low poly is in Edit Mode: %s" % hp_state())
    check(not tracebacks(), "Python error going from Sculpt to UV")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 after Sculpt to UV"))


# Edit High Poly: asks first (Enter confirms), shows the high poly until the next switch.
@step
def hp_edit_ask():
    with hp_viewport():
        bpy.ops.m3d.hp_edit('INVOKE_DEFAULT')


@step
def hp_edit_asked():
    check(hp_ob("Sword_high").hide_get(), "Edit High Poly asks before it shows the mesh")
    hp_press('RET')


step(wait_until(lambda: not hp_ob("Sword_high").hide_get(), "Enter to confirm Edit High Poly"))


@step
def hp_edit_shown():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(not high.m3d_pair.parked and bpy.context.active_object == high and high.select_get() and not low.select_get(),
          "Edit High Poly: shown, selected and active: %s" % hp_state())
    hp_press('F3')


step(wait_until(lambda: hp_in('UV') and bpy.context.mode == 'EDIT_MESH', "F3 to enter Edit Mode on the low poly"))


@step
def hp_uv_check():
    high, low = hp_ob("Sword_high"), hp_ob("Sword")
    check(high.hide_get() and high.m3d_pair.parked and bpy.context.active_object == low and low.mode == 'EDIT',
          "F3: the high poly is parked again and the low poly is in Edit Mode: %s" % hp_state())
    check(not tracebacks(), "Python error drawing the UV workspace with a pair")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 after UV"))


# The face limit: UV and Texture open on a mesh over the limit but leave it in Object Mode, and say why.
@step
def hp_limit_setup():
    for o in bpy.data.objects:
        o.select_set(o.name == "Plain")
    bpy.context.view_layer.objects.active = hp_ob("Plain")
    bpy.data.workspaces["UV"].m3d_face_limit = 3
    bpy.data.workspaces["Texture"].m3d_face_limit = 3
    hp_press('F3')


step(wait_until(lambda: hp_in('UV'), "F3 with a mesh over the limit"))


@step
def hp_limit_uv_check():
    plain = hp_ob("Plain")
    check(bpy.context.mode == 'OBJECT' and plain.mode == 'OBJECT' and bpy.context.active_object == plain,
          "F3 on a mesh over the face limit: it stays in Object Mode (%s)" % bpy.context.mode)
    check(bpy.data.workspaces["UV"].object_mode == 'EDIT', "...and the workspace gets its entry mode back (%s)" % bpy.data.workspaces["UV"].object_mode)
    note = HPR.big_note(bpy.context)
    check(note and note.startswith("High poly (6 faces): select the low poly"), "...the Status Line and dock say why: %r" % note)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def hp_limit_uv_drawn():
    check(not tracebacks(), "Python error drawing the UV workspace over the face limit")
    check(bpy.data.workspaces["UV"].object_mode == 'EDIT', "the UV entry mode is back after the switch")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 after the limit in UV"))


@step
def hp_limit_texture():
    hp_press('F4')


step(wait_until(lambda: hp_in('TEXTURE'), "F4 with a mesh over the limit"))


@step
def hp_limit_texture_check():
    check(bpy.context.mode == 'OBJECT' and bpy.context.active_object == hp_ob("Plain"), "F4 on a mesh over the face limit: Object Mode (%s)" % bpy.context.mode)
    check(bpy.data.workspaces["Texture"].object_mode == 'TEXTURE_PAINT', "...the Texture entry mode is back")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def hp_limit_texture_drawn():
    check(not tracebacks(), "Python error drawing the Texture workspace over the face limit")
    bpy.data.workspaces["UV"].m3d_face_limit = 500_000
    bpy.data.workspaces["Texture"].m3d_face_limit = 500_000
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 after the limit in Texture"))


@step
def hp_limit_off():
    hp_press('F3')


step(wait_until(lambda: hp_in('UV') and bpy.context.mode == 'EDIT_MESH', "F3 under the limit enters Edit Mode as before"))


@step
def hp_limit_off_check():
    check(bpy.context.active_object == hp_ob("Plain") and bpy.context.mode == 'EDIT_MESH', "under the limit F3 still enters Edit Mode")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 after the limit test"))


# Create High Poly from the button (the options box), then Undo: first in Object Mode.
@step
def hp_undo_object():
    for o in bpy.data.objects:
        o.select_set(o.name == "Plain")
    bpy.context.view_layer.objects.active = hp_ob("Plain")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo_push(message="Before Create High Poly")
        # (True: undo steps, as a click has them; a Python call without it takes none)
        res = bpy.ops.m3d.tool('INVOKE_DEFAULT', True, idname="m3d.hp_create", props="{}", label="Create High Poly")
    check(res == {'FINISHED'} and bpy.data.objects.get("Plain_high") is not None, "the button makes the high poly in Object Mode: %s" % res)
    check("m3d_options_box" not in bpy.context.window_manager, "the options box flag is cleared")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo()


@step
def hp_undo_object_check():
    check(bpy.data.objects.get("Plain_high") is None and hp_ob("Plain").m3d_pair.role == 'NONE' and hp_ob("Plain").m3d_pair.group == "",
          "Undo takes Create High Poly back in Object Mode: %s" % [(o.name, o.m3d_pair.role) for o in bpy.data.objects])
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.redo()


@step
def hp_redo_object_check():
    check(bpy.data.objects.get("Plain_high") is not None and hp_ob("Plain_high").m3d_pair.role == 'HIGH', "...and Redo makes it again")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo()


# ...then from the Sculpt Status Line (a mode change by a workspace switch has its own quirks with Undo: not tested here).
@step
def hp_create_status():
    check(bpy.data.objects.get("Plain_high") is None, "(back to the plain mesh)")
    for o in bpy.data.objects:
        o.select_set(o.name == "Plain")
    bpy.context.view_layer.objects.active = hp_ob("Plain")
    hp_press('F2')


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT', "F2 on a plain mesh"))


@step
def hp_create_click():
    check(hp_ob("Plain").mode == 'SCULPT', "a mesh without a role sculpts as before")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        res = bpy.ops.m3d.tool('INVOKE_DEFAULT', True, idname="m3d.hp_create", props="{}", label="Create High Poly")
    check(res == {'FINISHED'}, "the Status Line button runs: %s" % res)
    check("m3d_options_box" not in bpy.context.window_manager, "the options box flag is cleared")


@step
def hp_create_check():
    high, low = bpy.data.objects.get("Plain_high"), hp_ob("Plain")
    check(high is not None and bpy.context.active_object == high and high.mode == 'SCULPT' and low.hide_get() and not high.hide_get(),
          "Create High Poly in Sculpt: the copy is sculpted, the original put away: %s" % hp_state())
    check(not tracebacks(), "Python error after Create High Poly in Sculpt")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 after the Sculpt create"))


@step
def hp_cleanup():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.context.scene.m3d_show_low = False
    check(not tracebacks(), "Python error in the high poly / low poly tests")


# UX pass 2, P2 in the real window: Ctrl+D duplicates in Sculpt, a heavy Ctrl+3 asks first (Esc: nothing done, Enter: done),
# Apply Multires on a lower level asks naming what is lost, F2 on a game mesh stays in Object Mode with its card.
def p2_center():
    _win, _area, region = view3d()
    return region.x + region.width // 2, region.y + region.height // 2


def p2_key(key, **mods):
    xy = p2_center()
    event('MOUSEMOVE', xy=xy)
    event(key, 'PRESS', xy, **mods)
    event(key, 'RELEASE', xy, **mods)


@step
def p2_scene():
    with hp_viewport():
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.mesh.primitive_cube_add(size=2)
        bpy.context.active_object.name = "P2Box"
        bpy.ops.view3d.view_all(center=True)
    hp_press('F2')


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT', "F2 on a plain cube"))


@step
def p2_ctrl3():
    GIZMO["p2_ask"] = HPR.ASK_FACES
    HPR.ASK_FACES = 100   # (a cube's level 3, 384 faces, is "heavy" here: the real limit would need a mesh of millions)
    p2_key('THREE', ctrl=True)


@step
def p2_ctrl3_asks():
    check(m3d_sculpt.multires_of(hp_ob("P2Box")) is None, "a heavy Ctrl+3 asks before it subdivides")
    p2_key('ESC')


@step
def p2_ctrl3_again():
    check(m3d_sculpt.multires_of(hp_ob("P2Box")) is None, "...Esc: nothing is done")
    p2_key('THREE', ctrl=True)


@step
def p2_ctrl3_confirm():
    p2_key('RET')


step(wait_until(lambda: m3d_sculpt.multires_of(hp_ob("P2Box")) is not None, "Enter to confirm Ctrl+3"))


@step
def p2_ctrl3_done():
    HPR.ASK_FACES = GIZMO["p2_ask"]
    mod = m3d_sculpt.multires_of(hp_ob("P2Box"))
    check(mod.total_levels == 3 and mod.sculpt_levels == 3 and bpy.context.mode == 'SCULPT', "...Enter: level 3 (%d)" % mod.total_levels)
    mod.sculpt_levels = mod.levels = 1
    with hp_viewport():
        res = bpy.ops.m3d.multires_apply('INVOKE_DEFAULT')
    check(res == {'RUNNING_MODAL'} and m3d_sculpt.multires_of(hp_ob("P2Box")) is not None, "Apply Multires on level 1 of 3 asks first: %s" % res)
    p2_key('ESC')


@step
def p2_apply_cancelled():
    check(m3d_sculpt.multires_of(hp_ob("P2Box")) is not None, "...Esc keeps the levels")
    GIZMO["p2_objects"] = len(bpy.data.objects)
    p2_key('D', ctrl=True)


step(wait_until(lambda: len(bpy.data.objects) == GIZMO["p2_objects"] + 1, "Ctrl+D in Sculpt"))


@step
def p2_ctrl_d_check():
    ob = bpy.context.active_object
    check(ob is not None and ob.name != "P2Box" and bpy.context.mode == 'SCULPT', "Ctrl+D in Sculpt: a copy, sculpted (%s)" % (ob and ob.name))
    check(not tracebacks(), "Python error in the Sculpt keys")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 before the game mesh"))


@step
def p2_game_mesh():
    with hp_viewport():
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.mesh.primitive_cube_add(size=2)
        bpy.context.active_object.name = "P2Crate"
        bpy.ops.m3d.hp_mark(role='LOW')
    hp_press('F2')


step(wait_until(lambda: hp_in('SCULPT'), "F2 on a game mesh"))


@step
def p2_game_mesh_wait():
    pass


@step
def p2_game_mesh_card():
    check(bpy.context.mode == 'OBJECT' and hp_ob("P2Crate").mode == 'OBJECT', "F2 on a game mesh stays in Object Mode (the card asks)")
    check(window().workspace.object_mode == 'SCULPT', "...and the workspace keeps its own entry mode")
    check(not tracebacks(), "Python error drawing the game mesh card")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL'), "F1 after the game mesh"))


@step
def p2_cleanup():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    check(not tracebacks(), "Python error in the P2 sculpt tests")


# ----------------------------------------------------------------------------------------------------
# Sculpt Mode round trips of a big mesh in the real window (C: the draw buffers of a mesh are reused by the next buffer of
# the same size, the Tree is built in parallel): the viewport draws the same mesh after every round trip, a brush stroke
# comes out as the evaluated mesh with the right normals, and Undo brings the old mesh (and its drawing) back.
import numpy as np

SXG = {}


def sxg_positions(mesh):
    a = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def sxg_face_normals(mesh):
    co = sxg_positions(mesh).astype(np.float64)
    corner_verts = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", corner_verts)
    start = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_start", start)
    total = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_total", total)
    p = co[corner_verts]
    nxt = np.arange(len(corner_verts)) + 1
    nxt[start + total - 1] = start
    n = np.add.reduceat(np.cross(p, p[nxt]), start, axis=0)
    return n / np.linalg.norm(n, axis=1)[:, None]


def sxg_shot():
    """The 3D view of the Modeling workspace drawn into the Render Result (a viewport render), as an array."""
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 320, 240, 100
    with hp_viewport():
        bpy.ops.render.opengl(view_context=True)
    path = os.path.join(SXG["folder"], "shot.png")
    bpy.data.images["Render Result"].save_render(path)   # (the Render Result reports no size or pixels itself)
    image = bpy.data.images.load(path)
    pixels = np.empty(image.size[0] * image.size[1] * 4, np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels


def sxg_go(kind):
    def body():
        bpy.ops.m3d.workspace(kind=kind)
    return body


def sxg_mode(kind, mode):
    return lambda: hp_in(kind) and bpy.context.mode == mode and bpy.context.active_object is not None


@step
def sxg_setup():
    import tempfile
    SXG["folder"] = tempfile.mkdtemp(prefix="m3d_sx_")
    with hp_viewport():
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=200, ring_count=100)
        bpy.ops.object.shade_smooth()
        bpy.ops.view3d.view_all(center=True)
    SXG["ob"] = bpy.context.active_object
    SXG["before"] = sxg_positions(SXG["ob"].data)
    check(len(SXG["ob"].data.polygons) == 20000, "the sphere for the Sculpt round trips")
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(sxg_mode('MODEL', 'OBJECT'), "Modeling for the Sculpt round trips"))


@step
def sxg_base_shot():
    SXG["base"] = sxg_shot()
    check(float(np.abs(SXG["base"]).max()) > 0.0 and len(np.unique(SXG["base"][::4])) > 5, "the viewport render shows something")
    bpy.ops.ed.undo_push(message="Before the Sculpt round trips")


for _i in range(3):
    step(sxg_go('SCULPT'))
    step(wait_until(sxg_mode('SCULPT', 'SCULPT'), "Sculpt (round trip %d)" % _i))
    step(sxg_go('MODEL'))
    step(wait_until(sxg_mode('MODEL', 'OBJECT'), "Modeling (round trip %d)" % _i))


@step
def sxg_trips_check():
    now = sxg_shot()
    check(now.shape == SXG["base"].shape and float(np.abs(now - SXG["base"]).max()) < 0.01,
          "after three round trips through Sculpt Mode the viewport draws the same mesh (largest difference %.3g)"
          % (float(np.abs(now - SXG["base"]).max()) if now.shape == SXG["base"].shape else -1.0))
    check(not tracebacks(), "Python error in the Sculpt round trips")


step(sxg_go('SCULPT'))
step(wait_until(sxg_mode('SCULPT', 'SCULPT'), "Sculpt for the stroke"))


def sxg_event(type, value, dx):
    """A mouse event over the viewport, `dx` pixels from its centre (the sphere fills the middle of the view)."""
    def body():
        _win, _area, region = view3d()
        event(type, value, (region.x + region.width // 2 + dx, region.y + region.height // 2))
    return body


# A brush stroke made with the mouse (the Draw brush in the Sculpt workspace).
step(sxg_event('MOUSEMOVE', 'NOTHING', -60))
step(sxg_event('LEFTMOUSE', 'PRESS', -60))
for _k in range(1, 9):
    step(sxg_event('MOUSEMOVE', 'NOTHING', -60 + _k * 15))
step(sxg_event('LEFTMOUSE', 'RELEASE', 60))


@step
def sxg_stroke_done():
    moved = np.abs(sxg_positions(SXG["ob"].data) - SXG["before"]).max(axis=1)
    check(int((moved > 1e-6).sum()) > 50, "the brush stroke moved vertices (%d)" % int((moved > 1e-6).sum()))


step(sxg_go('MODEL'))
step(wait_until(sxg_mode('MODEL', 'OBJECT'), "Modeling after the stroke"))


@step
def sxg_stroke_check():
    ob = SXG["ob"]
    positions = sxg_positions(ob.data)
    moved = np.abs(positions - SXG["before"]).max(axis=1)
    check(int((moved > 1e-6).sum()) > 50, "the sculpted shape is kept after leaving Sculpt Mode")
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    check(float(np.abs(sxg_positions(ev.data) - positions).max()) < 1e-5, "...the evaluated mesh has it too")
    for label, mesh in (("mesh", ob.data), ("evaluated mesh", ev.data)):
        cached = np.empty(len(mesh.polygons) * 3, np.float32)
        mesh.polygon_normals.foreach_get("vector", cached)
        err = float(np.abs(cached.reshape(-1, 3) - sxg_face_normals(mesh)).max())
        check(err < 1e-3, "...and the face normals of the %s are right (error %.3g)" % (label, err))
    shot = sxg_shot()
    check(float(np.abs(shot - SXG["base"]).max()) > 0.02, "...and the viewport draws it")
    SXG["stroke_shot"] = shot
    bpy.ops.ed.undo_push(message="After the stroke")


def sxg_old_mesh_back():
    ob = bpy.context.active_object
    return (ob is not None and ob.type == 'MESH' and bpy.context.mode == 'OBJECT'
            and float(np.abs(sxg_positions(ob.data) - SXG["before"]).max()) < 1e-6)


def sxg_moved_mesh_back():
    ob = bpy.context.active_object
    return (ob is not None and ob.type == 'MESH' and bpy.context.mode == 'OBJECT'
            and float(np.abs(sxg_positions(ob.data) - SXG["before"]).max()) > 1e-3)


def sxg_undo_until(back, what, op):
    """Step body: Undo (or Redo) one step per tick until `back()` holds (each Sculpt Mode round trip is a few steps)."""
    def body():
        SXG["steps"] = SXG.get("steps", [])
        if back() or len(SXG["steps"]) >= 10:
            check(back(), "%s after %d steps (%s)" % (what, len(SXG["steps"]), SXG["steps"]))
            SXG["count"] = len(SXG["steps"])
            SXG["steps"] = []
            return
        op()
        ob = bpy.context.active_object
        SXG["steps"].append((bpy.context.mode, hp_in('MODEL')))
        steps.insert(0, body)
    return body


step(sxg_undo_until(sxg_old_mesh_back, "Undo brings the old mesh back", bpy.ops.ed.undo))


@step
def sxg_undo_check():
    now = sxg_shot()
    check(float(np.abs(now - SXG["base"]).max()) < 0.01, "...and the viewport draws it (largest difference %.3g)"
          % float(np.abs(now - SXG["base"]).max()))
    check(not tracebacks(), "Python error after Undo")


step(sxg_undo_until(sxg_moved_mesh_back, "Redo brings the sculpted mesh back", bpy.ops.ed.redo))


@step
def sxg_redo_check():
    shot = sxg_shot()
    check(float(np.abs(shot - SXG["stroke_shot"]).max()) < 0.01, "...and the viewport draws it (largest difference %.3g)"
          % float(np.abs(shot - SXG["stroke_shot"]).max()))
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    check(not tracebacks(), "Python error in the Sculpt Mode round trip tests")


# ----------------------------------------------------------------------------------------------------
# Bake groups in the real window: the Bake Groups panel in the Bake tab, a click on a row, Bake Group and Bake All from the dock
# (the high polys stay parked and are never drawn), the stale mark from the real depsgraph, Undo of Bake All.
import m3d_bakegroups as BGR


def bgg_plate(name, x=0.0, res=1, bump=0.0, size=2.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=res, y_segments=res, size=size / 2)
    layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        for loop in face.loops:
            loop[layer].uv = (loop.vert.co.x / size + 0.5, loop.vert.co.y / size + 0.5)
    if bump:
        for v in bm.verts:
            v.co.z += bump * math.exp(-((v.co.x ** 2 + v.co.y ** 2) ** 0.5 * 3) ** 2)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = (x, 0, 0)
    return ob


def bgg_group_state(group):
    return BGR.state_of(bpy.context.scene.m3d_bake_groups.get(group), group, *HPR.all_groups(bpy.context)[group])


def bgg_dock_context():
    dock = tex_areas()[1]
    return dock, next(r for r in dock.regions if r.type == 'WINDOW')


@step
def bgg_to_modeling():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling for the bake group tests"))


@step
def bgg_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bgg_plate("Sword_low")
    bgg_plate("Sword_high", res=16, bump=0.15)
    bgg_plate("Sword_high_bolts", res=4, bump=0.1, size=0.4).location.z = 0.2
    bgg_plate("Shield_low", x=3.0)
    bgg_plate("Shield_high", x=3.0, res=16, bump=0.2)
    bgg_plate("Rock_low", x=6.0)
    bpy.context.view_layer.update()
    check(bpy.ops.m3d.hp_auto_pair() == {'FINISHED'}, "Auto-Pair by Name in the window")
    for ob in bpy.data.objects:
        if ob.m3d_pair.role == 'LOW':
            s = ob.m3d_bake
            s.resolution, s.margin, s.samples, s.extrusion = '64', 4, 4, 0.4
            s.use_normal = s.use_ao = True
            s.use_curvature = s.use_position = s.use_thickness = False
    HPR.park_all(bpy.context)
    for name in ("Sword_high", "Sword_high_bolts", "Shield_high"):
        check(hp_ob(name).hide_get() and hp_ob(name).m3d_pair.parked, "(%s is parked)" % name)
    for ob in bpy.data.objects:
        ob.select_set(ob.name == "Sword_low")
    bpy.context.view_layer.objects.active = hp_ob("Sword_low")
    GIZMO["bgg_seen"] = []

    def draws():
        if not BVW._view["on"]:   # (the Bake mode view shows the high polys of the groups on purpose; a queue draws them as boxes)
            GIZMO["bgg_seen"] += [n for n in ("Sword_high", "Sword_high_bolts", "Shield_high")
                                  if not bpy.data.objects[n].hide_get() and bpy.data.objects[n].display_type != 'BOUNDS']
    GIZMO["bgg_handle"] = bpy.types.SpaceView3D.draw_handler_add(draws, (), 'WINDOW', 'POST_PIXEL')
    win, _area, region = view3d()
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])


@step
def bgg_f4():
    hp_press('F4')


step(wait_until(lambda: hp_in('TEXTURE') and bpy.context.mode == 'PAINT_TEXTURE', "F4 with a bake group"))


@step
def bgg_open_tab():
    window().workspace.m3d_page_right = "tex_bake"
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bgg_tab_check():
    check(not tracebacks(), "Python error drawing the Bake tab with bake groups")
    dock, region = bgg_dock_context()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=dock, region=region):
        check(m3d_workspace.active_page(bpy.context) == "tex_bake", "the dock shows the Bake page")
        check(m3d_texture.PROPERTIES_PT_m3d_tx_bake_high.poll(bpy.context), "...and High Poly, which shows the status of the group instead of the picker")
    props = tex_roles()["props"]
    with bpy.context.temp_override(window=window(), screen=window().screen, area=props, region=next(r for r in props.regions if r.type == 'WINDOW')):
        check(m3d_texture.PROPERTIES_PT_m3d_tx_bake_advanced.poll(bpy.context) and HPR.grouped(bpy.context.active_object),
              "Bake Settings (Properties) has Advanced, which holds the Bake Groups and the settings of the group of the active mesh")
    groups = HPR.all_groups(bpy.context)
    check(list(groups) == ["Rock", "Shield", "Sword"] and [len(x) for x in groups["Sword"]] == [1, 2], "three groups, the sword with a floater: %s" % {g: [len(x) for x in v] for g, v in groups.items()})
    check(bgg_group_state("Sword") == 'NONE', "nothing is baked yet")
    entry = bpy.context.scene.m3d_bake_groups.get("Sword")
    check(entry is None or abs(entry.extrusion - bpy.data.objects["Sword_low"].m3d_bake.extrusion) < 1e-6,
          "(the group's settings are made when High Poly first shows its Cage Distance, from the low poly's)")
    # A panel of the dock that draws the Group Settings as Advanced does when it is open.
    GIZMO["bgg_probe"] = type("PROPERTIES_PT_m3d_gui_group_probe", (bpy.types.Panel,), {
        "bl_label": "Group Settings Probe", "bl_space_type": 'PROPERTIES', "bl_region_type": 'WINDOW', "bl_context": "modeling_toolkit",
        "poll": classmethod(lambda cls, context: context.workspace.m3d_page_right == "tex_bake" and context.active_object is not None
                            and context.active_object.m3d_pair.group != ""),
        "draw": lambda self, context: BGR.draw_group_settings(self.layout, context)})
    bpy.utils.register_class(GIZMO["bgg_probe"])
    for a in window().screen.areas:
        a.tag_redraw()


step(wait_until(lambda: bpy.context.scene.m3d_bake_groups.get("Sword") is not None, "the settings of the group to be made for the open Group Settings"))


@step
def bgg_probe_check():
    check(bpy.context.scene.m3d_bake_groups.get("Sword") is not None, "the Group Settings were made a moment after they were drawn (not by the drawing)")
    check(not tracebacks(), "Python error drawing the Group Settings")
    bpy.utils.unregister_class(GIZMO.pop("bgg_probe"))
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bgg_click_row():
    dock, _region = bgg_dock_context()
    press_ok("m3d.bg_select", _area=dock, group="Shield")


step(wait_until(lambda: BVW.KEY in hp_ob("Shield_high") and BVW.KEY not in hp_ob("Sword_high"), "the Bake mode view to follow the group that was picked", 40))


@step
def bgg_click_row_check():
    low = hp_ob("Shield_low")
    check(bpy.context.active_object == low and low.select_get() and not hp_ob("Sword_low").select_get(), "a click on the Shield row selects its low poly")
    check(bpy.context.mode == 'PAINT_TEXTURE' and low.mode == 'TEXTURE_PAINT', "...and Texture Paint Mode goes with it (%s)" % bpy.context.mode)
    check(not hp_ob("Shield_high").hide_get() and hp_ob("Sword_high").hide_get() and hp_ob("Sword_high").m3d_pair.parked,
          "...Bake mode shows the high poly of that group (see-through blue), the high polys of the other groups stay hidden")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bgg_bake_group():
    GIZMO["bgg_engine"] = bpy.context.scene.render.engine
    dock, _region = bgg_dock_context()
    press_ok("m3d.bg_bake", _area=dock)


step(wait_until(lambda: not QB.running(), "Bake Group to finish (it is a queue of jobs: the window goes on)", 400))


@step
def bgg_bake_group_check():
    scene = bpy.context.scene
    check(scene.render.engine == GIZMO["bgg_engine"], "Cycles switched back after Bake Group (%s)" % scene.render.engine)
    check(bpy.context.mode == 'PAINT_TEXTURE' and bpy.context.active_object == hp_ob("Shield_low") and hp_ob("Shield_low").select_get(),
          "Texture Paint Mode, the active mesh and the selection are back (%s)" % bpy.context.mode)
    check(all(bpy.data.images.get("Shield_low_" + n) is not None for n in ("Normal", "AO")), "Shield's maps are baked")
    check(bpy.data.images.get("Sword_low_Normal") is None, "...and only Shield's")
    check(bgg_group_state("Shield") == 'BAKED' and bgg_group_state("Sword") == 'NONE', "Shield is baked, Sword is not")
    check(window().workspace.m3d_page_right == "tex_bake", "(the dock stays on the Bake page)")
    window().workspace.m3d_page_right = "tex_layers"


step(wait_until(lambda: not BVW._view["on"], "the Bake mode view to go with the page", 40))


@step
def bgg_bake_group_parked():
    check(hp_ob("Shield_high").hide_get() and hp_ob("Shield_high").m3d_pair.parked and not hp_ob("Shield_high").select_get(), "the parked high poly is hidden again")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bgg_bake_all():
    dock, _region = bgg_dock_context()
    press_ok("m3d.bg_bake_all", _area=dock)


step(wait_until(lambda: not QB.running(), "Bake All to finish (it is a queue of jobs: the window goes on)", 400))
step(wait_until(lambda: not BVW._view["on"] and window().workspace.m3d_page_right == "tex_layers", "the dock back on the Layers (the queue opened the Bake page)", 40))


@step
def bgg_bake_all_check():
    check(all(bgg_group_state(g) == 'BAKED' for g in ("Sword", "Shield", "Rock")), "Bake All: every group is baked: %s" % [bgg_group_state(g) for g in ("Sword", "Shield", "Rock")])
    check(bpy.data.images.get("Rock_low_Normal") is not None, "...also the one that has no high poly (it bakes itself)")
    normal = px(bpy.data.images["Sword_low_Normal"])[:, :3]
    check(normal.std(axis=0).max() > 0.01, "the sword's normal map shows the detail of its high polys and the floater")
    check(all(hp_ob(n).hide_get() and hp_ob(n).m3d_pair.parked for n in ("Sword_high", "Sword_high_bolts", "Shield_high")), "all the high polys are hidden again")
    check(bpy.context.mode == 'PAINT_TEXTURE' and bpy.context.active_object == hp_ob("Shield_low"), "mode and active mesh are back")
    check(not tracebacks(), "Python error while baking the groups")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bgg_edit_hidden():
    # A parked high poly is moved (a hidden mesh is in the real depsgraph too): its group is stale.
    hp_ob("Sword_high").location.x += 0.2


@step
def bgg_stale_check():
    check(bgg_group_state("Sword") == 'STALE' and bgg_group_state("Shield") == 'BAKED', "moving the parked high poly: Sword is stale, Shield is not (%s %s)" % (
        bgg_group_state("Sword"), bgg_group_state("Shield")))
    hp_ob("Sword_high").location.x -= 0.2
    check(not tracebacks(), "Python error drawing the stale group")


@step
def bgg_never_drawn():
    check(not GIZMO["bgg_seen"], "no parked high poly was ever drawn while it was shown for a bake: %s" % GIZMO["bgg_seen"])
    # The check can see: a high poly shown on purpose is seen by the draw handler.
    hp_ob("Shield_high").hide_set(False)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bgg_control():
    seen = bool(GIZMO["bgg_seen"])
    hp_ob("Shield_high").hide_set(True)
    check(seen and "Shield_high" in GIZMO["bgg_seen"], "(control: a high poly that is shown is seen by the draw handler)")
    bpy.types.SpaceView3D.draw_handler_remove(GIZMO.pop("bgg_handle"), 'WINDOW')


# Going into and out of modes and painting are no edits; a sculpt stroke on a parked high poly is.
def bgg_all(state):
    return all(bgg_group_state(g) == state for g in ("Sword", "Shield", "Rock"))


@step
def bgg_rebake():
    press_ok("m3d.bg_bake_all", _area=bgg_dock_context()[0])


step(wait_until(lambda: not QB.running(), "the second Bake All to finish (it is a queue of jobs: the window goes on)", 400))


@step
def bgg_modes_out():
    check(bgg_all('BAKED'), "(all baked: %s)" % [bgg_group_state(g) for g in ("Sword", "Shield", "Rock")])
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling after the bakes"))


@step
def bgg_modes_in():
    bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: hp_in('TEXTURE') and bpy.context.mode == 'PAINT_TEXTURE', "Texture again after the bakes"))


@step
def bgg_paint_setup():
    check(bgg_all('BAKED'), "leaving and entering Texture Paint Mode does not make a group stale: %s" % [bgg_group_state(g) for g in ("Sword", "Shield", "Rock")])
    dock, _region = bgg_dock_context()
    bpy.context.scene.m3d_tex.resolution = '64'
    press_ok("m3d.tex_add_material", _area=dock)
    press_ok("m3d.tex_channel", _area=dock, channel='BASE_COLOR')
    view, region = tex_view()
    with bpy.context.temp_override(window=window(), area=view, region=region):
        bpy.ops.view3d.view_all(center=True)


@step
def bgg_paint_aim():
    ob = bpy.context.active_object
    view, region = tex_view()
    p = location_3d_to_region_2d(region, view.spaces.active.region_3d, ob.matrix_world.translation)
    cx, cy = (int(region.x + p.x), int(region.y + p.y)) if p is not None else tex_xy()
    GIZMO["bgg_stroke"] = [(cx - 20 + i * 4, cy) for i in range(11)]
    GIZMO["bgg_image"] = m3d_texture.channel_slots(ob.active_material)['BASE_COLOR'][1]
    GIZMO["bgg_before"] = px(GIZMO["bgg_image"]).copy()
    event('MOUSEMOVE', xy=GIZMO["bgg_stroke"][0])


@step
def bgg_paint_press():
    event('LEFTMOUSE', 'PRESS', GIZMO["bgg_stroke"][0])
    for xy in GIZMO["bgg_stroke"][1:]:
        event('MOUSEMOVE', xy=xy)


@step
def bgg_paint_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["bgg_stroke"][-1])


@step
def bgg_paint_check():
    changed = np.abs(px(GIZMO["bgg_image"]) - GIZMO["bgg_before"]).max()
    check(changed > 0.05, "(the stroke painted: %.3f)" % changed)
    check(bgg_all('BAKED'), "a texture paint stroke does not make a group stale: %s" % [bgg_group_state(g) for g in ("Sword", "Shield", "Rock")])
    bpy.ops.m3d.workspace(kind='SCULPT')


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT', "Sculpt on the group of the active mesh"))


@step
def bgg_sculpt_view():
    check(hp_ob("Shield_high").mode == 'SCULPT' and not hp_ob("Shield_high").hide_get(), "(the shield's high poly is sculpted)")
    check(bgg_all('BAKED'), "going into Sculpt Mode on a parked high poly does not make a group stale: %s" % [bgg_group_state(g) for g in ("Sword", "Shield", "Rock")])
    with hp_viewport():
        bpy.ops.view3d.view_all(center=True)
    _win, _area, region = view3d()
    event('MOUSEMOVE', xy=(region.x + region.width // 2 - 60, region.y + region.height // 2))
    GIZMO["bgg_pos"] = sxg_positions(hp_ob("Shield_high").data)


step(sxg_event('MOUSEMOVE', 'NOTHING', -60))
step(sxg_event('LEFTMOUSE', 'PRESS', -60))
for _k in range(1, 9):
    step(sxg_event('MOUSEMOVE', 'NOTHING', -60 + _k * 15))
step(sxg_event('LEFTMOUSE', 'RELEASE', 60))


@step
def bgg_sculpt_check():
    moved = int((np.abs(sxg_positions(hp_ob("Shield_high").data) - GIZMO["bgg_pos"]).max(axis=1) > 1e-6).sum())
    check(moved > 5, "(the stroke moved %d vertices of the shield's high poly)" % moved)
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling after the sculpt stroke"))


@step
def bgg_after_sculpt():
    check(bgg_group_state("Shield") == 'STALE' and bgg_group_state("Sword") == 'BAKED' and bgg_group_state("Rock") == 'BAKED',
          "leaving Sculpt Mode after a stroke: the shield is stale, the others are not: %s" % [bgg_group_state(g) for g in ("Sword", "Shield", "Rock")])
    check(all(hp_ob(n).hide_get() for n in ("Sword_high", "Sword_high_bolts", "Shield_high")), "(the high polys are parked again)")
    check(not tracebacks(), "Python error in the stale tests")


@step
def bgg_undo_setup():
    bpy.ops.object.mode_set(mode='OBJECT')
    for entry in list(bpy.context.scene.m3d_bake_groups):
        bpy.context.scene.m3d_bake_groups.remove(0)
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo_push(message="Before Bake All")
        res = bpy.ops.m3d.bg_bake_all('EXEC_DEFAULT', True)   # (blocking: the Undo of one step is what is tested; the queue's own Undo is at the end)
    check(res == {'FINISHED'}, "Bake All with an undo step: %s" % res)
    check(bgg_group_state("Sword") == 'BAKED', "(baked)")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo()


@step
def bgg_undo_check():
    # (the panel makes the settings of the active group again, a moment after Undo, never as baked)
    check(all(bgg_group_state(g) == 'NONE' for g in ("Sword", "Shield", "Rock")),
          "one Undo takes the whole Bake All back: %s" % [(e.name, e.state) for e in bpy.context.scene.m3d_bake_groups])
    check(all(hp_ob(n).hide_get() for n in ("Sword_high", "Sword_high_bolts", "Shield_high")), "...the high polys are still parked")
    check(not tracebacks(), "Python error after Undo of Bake All")
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.m3d.workspace(kind='MODEL')



# ----------------------------------------------------------------------------------------------------
# Retopology in the real window: Make Live on a parked high poly (it asks first), New Low Poly (Quad Draw starts by itself),
# Poly Build with simulated events over a sphere (the new points land on its surface), Sculpt with a live surface,
# Make Not Live, Undo of New Low Poly.
import m3d_retopo as RTP

step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling for the retopology tests"))


def rt_ts():
    return RTP.snap_of(bpy.context.scene.tool_settings)


def rt_view_on():
    return view3d()[1].spaces.active.overlay.show_retopology


def rt_sp(az, el):
    """A point of the unit sphere facing the Front view."""
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def rt_xy(co):
    _win, area, region = view3d()
    p = location_3d_to_region_2d(region, area.spaces.active.region_3d, co)
    return int(region.x + p.x), int(region.y + p.y)


def rt_points():
    """The points of the mesh in Edit Mode, with their distance from the middle of the sphere."""
    mesh = bmesh.from_edit_mesh(bpy.context.active_object.data)
    return [(v.co.copy(), v.co.length) for v in mesh.verts], len(mesh.faces)


@step
def rt_pair_setup():
    with hp_viewport():
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.m3d.add_primitive(kind='CUBE')
        bpy.context.active_object.name = "Gem"
        check(bpy.ops.m3d.hp_create() == {'FINISHED'}, "(Create High Poly for the retopology tests)")
        bpy.ops.m3d.hp_park()
        bpy.ops.view3d.view_all(center=True)
    GIZMO["rt_ts"], GIZMO["rt_view"] = rt_ts(), rt_view_on()
    window().workspace.m3d_page_right = "modeling_toolkit"
    check(hp_ob("Gem_high").hide_get() and hp_ob("Gem_high").m3d_pair.parked, "(the high poly is parked)")


@step
def rt_ask():
    with hp_viewport():
        check(bpy.ops.m3d.hp_make_live('INVOKE_DEFAULT') == {'RUNNING_MODAL'} or hp_ob("Gem_high").hide_get(), "Make Live on a parked high poly asks first")


@step
def rt_asked():
    check(hp_ob("Gem_high").hide_get() and bpy.context.scene.m3d_live_surface is None, "Make Live asks before it shows the high poly")
    hp_press('RET')


step(wait_until(lambda: not hp_ob("Gem_high").hide_get(), "Enter to confirm Make Live"))


@step
def rt_live_check():
    high, low = hp_ob("Gem_high"), hp_ob("Gem")
    ts = bpy.context.tool_settings
    check(bpy.context.scene.m3d_live_surface == high and high.hide_select and not high.m3d_pair.parked and not high.select_get(),
          "Make Live (confirmed): the high poly is shown, live and unselectable")
    check(ts.use_snap and set(ts.snap_elements) == {'FACE_PROJECT'} and rt_view_on(), "...snapping and the retopology overlay are on: %s" % rt_ts())
    check(bpy.context.active_object == low and low.select_get(), "...the low poly stays active and selected")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rt_live_drawn():
    check(not tracebacks(), "Python error drawing the Status Line with a live surface")
    with hp_viewport():
        check(bpy.ops.m3d.hp_make_not_live() == {'FINISHED'}, "Make Not Live runs in the window")
    high = hp_ob("Gem_high")
    check(not high.hide_select and high.hide_get() and high.m3d_pair.parked and bpy.context.active_object == hp_ob("Gem"),
          "Make Not Live: selectable again, parked again (it has a low poly), the low poly active")
    check(rt_ts() == GIZMO["rt_ts"] and rt_view_on() == GIZMO["rt_view"], "...the snapping and the overlay are as they were: %s" % rt_ts())
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rt_sphere_setup():
    check(not tracebacks(), "Python error drawing the Status Line after Make Not Live")
    with hp_viewport():
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=64, ring_count=32)
        orb = bpy.context.active_object
        orb.name = "Orb_high"
        orb.m3d_pair.role, orb.m3d_pair.group = 'HIGH', "Orb"
        bpy.ops.object.shade_smooth()
        bpy.ops.view3d.view_axis(type='FRONT')
        rv3d = view3d()[1].spaces.active.region_3d
        rv3d.view_distance, rv3d.view_location = 5.0, (0, 0, 0)


@step
def rt_new_low():
    with hp_viewport():
        check(bpy.ops.m3d.hp_new_low('INVOKE_DEFAULT') == {'FINISHED'}, "New Low Poly runs in the window")


step(wait_until(lambda: bpy.context.mode == 'EDIT_MESH' and bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH').idname == "builtin.poly_build",
                "Edit Mode and Quad Draw to start on the new low poly"))


@step
def rt_new_low_check():
    low, high = hp_ob("Orb_low"), hp_ob("Orb_high")
    check(bpy.context.active_object == low and low.mode == 'EDIT' and len(low.data.vertices) == 0, "New Low Poly: an empty mesh in Edit Mode")
    check(low.m3d_pair.role == 'LOW' and high.m3d_pair.role == 'HIGH' and low.m3d_pair.group == high.m3d_pair.group == "Orb"
          and bpy.context.scene.m3d_live_surface == high and high.hide_select, "...paired with the live surface")
    check(rt_view_on() and bpy.context.tool_settings.use_snap, "...with the overlay and the snapping on")
    for a in window().screen.areas:
        a.tag_redraw()


def rt_add(name, az, el):
    """Steps: Shift+click at a point of the sphere (Quad Draw adds a point there)."""
    @step
    def aim():
        GIZMO[name] = rt_xy(rt_sp(az, el))
        event('MOUSEMOVE', xy=GIZMO[name])

    @step
    def press():
        xy = GIZMO[name]
        event('LEFT_SHIFT', 'PRESS', xy, shift=True)
        event('LEFTMOUSE', 'PRESS', xy, shift=True)
        event('MOUSEMOVE', xy=(xy[0] + 2, xy[1]), shift=True)
        event('MOUSEMOVE', xy=xy, shift=True)

    @step
    def release():
        xy = GIZMO[name]
        event('LEFTMOUSE', 'RELEASE', xy, shift=True)
        event('LEFT_SHIFT', 'RELEASE', xy)


def rt_on_surface(count, faces, what):
    points, nfaces = rt_points()
    off = [round(r, 4) for _co, r in points if abs(r - 1.0) > 0.01]
    check(len(points) == count and nfaces == faces and not off,
          "%s: %d points, %d faces, all on the sphere (radius 1 +- 0.01; off: %s; %s)" % (what, len(points), nfaces, off, [round(r, 4) for _co, r in points]))


rt_add("rt_p1", 0.0, 0.0)


@step
def rt_p1_check():
    rt_on_surface(1, 0, "Shift+click on an empty mesh adds a point on the surface")


def rt_extend(name_from, name_to, az, el):
    """Steps: hover a point, then Shift+press on it and drag to a point of the sphere: Quad Draw adds a point there, joined
    to the one it started from (to the other two as a quad when that one has two edges)."""
    @step
    def aim():
        GIZMO[name_to] = rt_xy(rt_sp(az, el))
        xy = GIZMO[name_from]
        event('MOUSEMOVE', xy=(xy[0] + 3, xy[1] + 3))

    @step
    def hover():
        event('MOUSEMOVE', xy=GIZMO[name_from])

    @step
    def shift():
        event('LEFT_SHIFT', 'PRESS', GIZMO[name_from], shift=True)   # (the preselection is refreshed when a modifier changes: a step of its own)

    @step
    def press():
        x0, y0 = GIZMO[name_from]
        x1, y1 = GIZMO[name_to]
        event('LEFTMOUSE', 'PRESS', (x0, y0), shift=True)
        for i in range(1, 7):
            event('MOUSEMOVE', xy=(x0 + (x1 - x0) * i // 6, y0 + (y1 - y0) * i // 6), shift=True)

    @step
    def release():
        event('LEFTMOUSE', 'RELEASE', GIZMO[name_to], shift=True)
        event('LEFT_SHIFT', 'RELEASE', GIZMO[name_to])


# A chain: each Shift+drag from the last point adds the next one and the edge.
rt_extend("rt_p1", "rt_p2", 0.4, 0.1)


@step
def rt_p2_check():
    mesh = bmesh.from_edit_mesh(bpy.context.active_object.data)
    rt_on_surface(2, 0, "Shift+drag from a point adds a point on the surface")
    check(len(mesh.edges) == 1, "...and an edge to it (%d edges)" % len(mesh.edges))


rt_extend("rt_p2", "rt_p3", 0.5, -0.3)


@step
def rt_p3_check():
    mesh = bmesh.from_edit_mesh(bpy.context.active_object.data)
    rt_on_surface(3, 0, "a chain of three points")
    check(len(mesh.edges) == 2, "...two edges (%d)" % len(mesh.edges))


# A quad: Shift+drag from the middle point, which has two edges, to the fourth corner.
rt_extend("rt_p2", "rt_p4", 0.1, -0.4)


@step
def rt_quad_check():
    mesh = bmesh.from_edit_mesh(bpy.context.active_object.data)
    rt_on_surface(4, 1, "a quad over the sphere (Shift+drag from the middle point of the chain)")
    check(len(mesh.edges) == 4, "...four edges (%d)" % len(mesh.edges))
    GIZMO["rt_before"] = [tuple(co) for co, _r in rt_points()[0]]


# Move a point: a plain drag.
@step
def rt_move_aim():
    GIZMO["rt_from"] = rt_xy(Vector(GIZMO["rt_before"][0]))
    GIZMO["rt_to"] = rt_xy(rt_sp(-0.3, 0.3))
    xy = GIZMO["rt_from"]
    event('MOUSEMOVE', xy=(xy[0] + 3, xy[1] + 3))


@step
def rt_move_hover():
    event('MOUSEMOVE', xy=GIZMO["rt_from"])


@step
def rt_move_press():
    x0, y0 = GIZMO["rt_from"]
    x1, y1 = GIZMO["rt_to"]
    event('LEFTMOUSE', 'PRESS', (x0, y0))
    for i in range(1, 7):
        event('MOUSEMOVE', xy=(x0 + (x1 - x0) * i // 6, y0 + (y1 - y0) * i // 6))


@step
def rt_move_release():
    event('LEFTMOUSE', 'RELEASE', GIZMO["rt_to"])


@step
def rt_move_check():
    rt_on_surface(4, 1, "a point moved with a plain drag stays on the sphere")
    after = [tuple(co) for co, _r in rt_points()[0]]
    moved = [i for i, (a, b) in enumerate(zip(GIZMO["rt_before"], after)) if (Vector(a) - Vector(b)).length > 0.2]
    check(len(moved) == 1, "...and it moved (points that moved: %s)" % moved)


# Delete a point: Ctrl+click on it.
@step
def rt_delete_aim():
    GIZMO["rt_victim"] = rt_xy(Vector(GIZMO["rt_before"][2]))
    xy = GIZMO["rt_victim"]
    event('MOUSEMOVE', xy=(xy[0] + 3, xy[1] + 3))


@step
def rt_delete_hover():
    event('MOUSEMOVE', xy=GIZMO["rt_victim"])


@step
def rt_delete_ctrl():
    event('LEFT_CTRL', 'PRESS', GIZMO["rt_victim"], ctrl=True)


@step
def rt_delete_click():
    xy = GIZMO["rt_victim"]
    event('LEFTMOUSE', 'PRESS', xy, ctrl=True)
    event('LEFTMOUSE', 'RELEASE', xy, ctrl=True)
    event('LEFT_CTRL', 'RELEASE', xy)


@step
def rt_delete_check():
    points, nfaces = rt_points()
    victim = Vector(GIZMO["rt_before"][2])
    check(len(points) == 3 and not any((co - victim).length < 0.05 for co, _r in points),
          "Ctrl+click deletes the point under the pointer (%d points left, %d faces)" % (len(points), nfaces))
    check(not tracebacks(), "Python error while drawing with Quad Draw")
    for a in window().screen.areas:
        a.tag_redraw()


# Sculpt with a live surface: F2 sculpts the high poly (shown, though it can't be selected), F1 leaves it shown.
@step
def rt_f2():
    hp_press('F2')


step(wait_until(lambda: hp_in('SCULPT') and bpy.context.mode == 'SCULPT', "F2 with a live surface"))


@step
def rt_f2_check():
    high, low = hp_ob("Orb_high"), hp_ob("Orb_low")
    check(bpy.context.active_object == high and high.mode == 'SCULPT' and not high.hide_get() and low.hide_get(),
          "F2 with a live surface: Sculpt Mode on the high poly, the low poly out of the way (%s, %s)" % (bpy.context.mode, bpy.context.active_object.name))
    check(bpy.context.scene.m3d_live_surface == high, "...the surface is still live")
    hp_press('F1')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "F1 with a live surface"))


@step
def rt_f1_check():
    high, low = hp_ob("Orb_high"), hp_ob("Orb_low")
    check(not high.hide_get() and not high.m3d_pair.parked and not low.hide_get() and bpy.context.active_object == low and low.select_get(),
          "F1 with a live surface: the high poly stays shown (it is live), the low poly is active and selected: %s" % hp_state())
    check(not tracebacks(), "Python error switching workspace with a live surface")


@step
def rt_not_live():
    with hp_viewport():
        bpy.ops.m3d.hp_make_not_live()
    high = hp_ob("Orb_high")
    check(bpy.context.scene.m3d_live_surface is None and not high.hide_select and high.hide_get() and rt_ts() == GIZMO["rt_ts"],
          "Make Not Live after the drawing: the high poly is parked, the snapping is as it was")


# Undo of New Low Poly in the window (Quad Draw starts on a timer; Undo must take the mesh and the live state back).
@step
def rt_undo_setup():
    with hp_viewport():
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=16, ring_count=8)
        orb = bpy.context.active_object
        orb.name = "Orb_high"
        orb.m3d_pair.role, orb.m3d_pair.group = 'HIGH', "Orb"
        bpy.ops.ed.undo_push(message="Before New Low Poly")
        bpy.ops.m3d.hp_new_low('INVOKE_DEFAULT', True)


step(wait_until(lambda: bpy.context.mode == 'EDIT_MESH', "Quad Draw to start before the Undo"))


@step
def rt_undo():
    check(bpy.data.objects.get("Orb_low") is not None, "(New Low Poly with an undo step)")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.undo()


@step
def rt_undo_check():
    check(bpy.data.objects.get("Orb_low") is None and bpy.context.mode == 'OBJECT' and bpy.context.scene.m3d_live_surface is None
          and not hp_ob("Orb_high").hide_select and rt_ts() == GIZMO["rt_ts"] and rt_view_on() == GIZMO["rt_view"],
          "Undo takes New Low Poly back in the window: the mesh, the live state, the snapping, the overlay (%s %s)" % (bpy.context.mode, rt_ts()))
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.ed.redo()


@step
def rt_redo_check():
    check(bpy.data.objects.get("Orb_low") is not None and bpy.context.scene.m3d_live_surface == hp_ob("Orb_high") and rt_ts()["use_snap"]
          and set(rt_ts()["snap_elements"]) == {'FACE_PROJECT'}, "...and Redo makes them again: %s" % rt_ts())
    with hp_viewport():
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if bpy.ops.m3d.hp_make_not_live.poll():
            bpy.ops.m3d.hp_make_not_live()
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)
    window().workspace.m3d_page_right = ""
    check(rt_ts() == GIZMO["rt_ts"], "(the snapping is as it was at the end of the retopology tests)")
    check(not tracebacks(), "Python error in the retopology tests")
    bpy.ops.m3d.workspace(kind='MODEL')


# ----------------------------------------------------------------------------------------------------
# The extras of the high poly / low poly workflow in the real window: Explode and the cage preview in the Bake tab (the preview goes away
# when another group is picked: by a timer; it is never saved or baked), the ID map, and a parked high poly exported with Bake meshes
# without ever being drawn.
import tempfile


def bx_state():
    return {o.name: tuple(o.location) for o in bpy.data.objects}


def bx_redraw():
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bx_to_modeling():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling for the bake extras tests"))


@step
def bx_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for entry in list(bpy.context.scene.m3d_bake_groups):
        bpy.context.scene.m3d_bake_groups.remove(0)
    for name in ("BxA", "BxB"):
        if name in bpy.data.materials:
            bpy.data.materials.remove(bpy.data.materials[name])
    bpy.context.scene.m3d_explode_axis, bpy.context.scene.m3d_explode_gap = 'X', 0.25
    for name, x in (("Axe", 0.0), ("Bow", 1.0), ("Cup", 9.0)):
        bgg_plate(name + "_low", x=x)
        bgg_plate(name + "_high", x=x, res=8, bump=0.1)
    high = hp_ob("Axe_high")
    for name in ("BxA", "BxB"):
        high.data.materials.append(bpy.data.materials.new(name))
    for poly in high.data.polygons:
        poly.material_index = 0 if sum(high.data.vertices[i].co.x for i in poly.vertices) < 0 else 1
    bpy.context.view_layer.update()
    check(bpy.ops.m3d.hp_auto_pair() == {'FINISHED'}, "Auto-Pair by Name in the window (bake extras)")
    for ob in bpy.data.objects:
        if ob.m3d_pair.role == 'LOW':
            s = ob.m3d_bake
            s.resolution, s.margin, s.samples, s.extrusion = '64', 4, 4, 0.5
            s.use_normal, s.use_ao, s.use_curvature, s.use_position, s.use_thickness, s.use_id = True, False, False, False, False, True
    HPR.park_all(bpy.context)
    for ob in bpy.data.objects:
        ob.select_set(ob.name == "Axe_low")
    bpy.context.view_layer.objects.active = hp_ob("Axe_low")
    GIZMO["bx_home"] = bx_state()
    GIZMO["bx_seen"] = []

    def draws():
        if not BVW._view["on"]:
            GIZMO["bx_seen"] += [n for n in ("Axe_high", "Bow_high", "Cup_high")
                                 if n in bpy.data.objects and not bpy.data.objects[n].hide_get() and bpy.data.objects[n].display_type != 'BOUNDS']
    GIZMO["bx_handle"] = bpy.types.SpaceView3D.draw_handler_add(draws, (), 'WINDOW', 'POST_PIXEL')
    _win, _area, region = view3d()
    GIZMO["center"] = (region.x + region.width // 2, region.y + region.height // 2)
    event('MOUSEMOVE', xy=GIZMO["center"])


@step
def bx_f4():
    hp_press('F4')


step(wait_until(lambda: hp_in('TEXTURE') and bpy.context.mode == 'PAINT_TEXTURE', "F4 for the bake extras tests"))


@step
def bx_open_tab():
    window().workspace.m3d_page_right = "tex_bake"
    bx_redraw()


@step
def bx_tab_check():
    check(not tracebacks(), "Python error drawing the Bake tab (bake extras)")
    dock, region = bgg_dock_context()
    props = tex_roles()["props"]
    with bpy.context.temp_override(window=window(), screen=window().screen, area=props, region=next(r for r in props.regions if r.type == 'WINDOW')):
        check(m3d_texture.PROPERTIES_PT_m3d_tx_bake_advanced.poll(bpy.context) and HPR.grouped(bpy.context.active_object), "Bake Settings shows Advanced, with the groups and the settings of the active one")
    check(not BGR.cage_objects() and not BGR.moved(bpy.context), "(nothing is apart, no cage preview)")


# --- Explode: the toggle of the Bake Groups panel
@step
def bx_explode():
    press_ok("m3d.bg_explode", _area=bgg_dock_context()[0])


@step
def bx_explode_check():
    now, home = bx_state(), GIZMO["bx_home"]
    check(now["Axe_low"] == home["Axe_low"] and now["Cup_low"] == home["Cup_low"] and now["Cup_high"] == home["Cup_high"]
          and abs(now["Bow_low"][0] - 2.5) < 1e-5 and now["Bow_high"] == now["Bow_low"], "Explode in the window: Bow moves aside with its high poly, the others stay: %s" % {n: v[0] for n, v in now.items()})
    check(sorted(o.name for o in BGR.moved(bpy.context)) == ["Bow_high", "Bow_low"], "...the meshes that moved remember it")
    check(hp_ob("Bow_high").hide_get() and hp_ob("Bow_high").m3d_pair.parked and bgg_group_state("Bow") == 'NONE', "...the parked high poly is still hidden")
    bx_redraw()


@step
def bx_explode_axis():
    bpy.context.scene.m3d_explode_axis = 'Y'


@step
def bx_explode_axis_check():
    now, home = bx_state(), GIZMO["bx_home"]
    check(all(now[n][0] == home[n][0] for n in home) and now["Bow_low"][1] > 2.0 and now["Axe_low"] == home["Axe_low"],
          "the axis changed in the window: the groups are lined up along Y instead (from the places they had)")
    bpy.context.scene.m3d_explode_axis = 'X'
    check(not tracebacks(), "Python error drawing the Explode toggle")
    bx_redraw()


@step
def bx_collapse():
    press_ok("m3d.bg_explode", _area=bgg_dock_context()[0])


@step
def bx_collapse_check():
    check(bx_state() == GIZMO["bx_home"] and not BGR.moved(bpy.context), "the toggle again: every mesh is exactly where it was")
    check(not tracebacks(), "Python error after Collapse")


# --- Cage preview: the toggle of the Group Settings panel
@step
def bx_cage_on():
    press_ok("m3d.bg_cage_preview", _area=bgg_dock_context()[0])


@step
def bx_cage_on_check():
    cage = BGR.cage_objects()
    check(len(cage) == 1 and cage[0].parent == hp_ob("Axe_low") and cage[0].visible_get() and cage[0].display_type == 'WIRE' and cage[0].hide_render,
          "Show Cage in the window: a wire object in the view, not rendered (%s)" % [o.name for o in cage])
    dg = bpy.context.evaluated_depsgraph_get()
    ev = cage[0].evaluated_get(dg)
    mesh = ev.to_mesh()
    heights = [(ev.matrix_world @ v.co).z for v in mesh.vertices]
    ev.to_mesh_clear()
    check(heights and abs(min(heights) - 0.5) < 1e-4 and abs(max(heights) - 0.5) < 1e-4, "...pushed out by the Extrusion (0.5): %s" % heights[:2])
    BGR.settings_of(bpy.context, "Axe").extrusion = 0.2
    check(abs(BGR.cage_objects()[0].modifiers[0].strength - 0.2) < 1e-5, "...and following it")
    check(not tracebacks(), "Python error drawing the cage preview toggle")
    bx_redraw()


@step
def bx_cage_other_group():
    press_ok("m3d.bg_select", _area=bgg_dock_context()[0], group="Bow")


step(wait_until(lambda: not BGR.cage_objects(), "the cage preview to go away when another group is picked"))


@step
def bx_cage_gone_check():
    check(bpy.context.active_object == hp_ob("Bow_low") and not BGR.cage_objects(), "picking another group takes the cage preview away (by a timer, in the real event loop)")
    check(not tracebacks(), "Python error after the preview went away")


@step
def bx_cage_again():
    press_ok("m3d.bg_cage_preview", _area=bgg_dock_context()[0])


@step
def bx_cage_save():
    check(len(BGR.cage_objects()) == 1, "(the preview of Bow is on)")
    GIZMO["bx_dir"] = tempfile.mkdtemp(prefix="m3d_bx_")
    path = os.path.join(GIZMO["bx_dir"], "cage.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    check(not BGR.cage_objects(), "saving the file takes the preview away")
    with bpy.data.libraries.load(path) as (src, _dst):
        names = list(src.objects)
    check("Bow_low" in names and not any(n.startswith("m3dCage") for n in names), "...and the file does not have it: %s" % names)


@step
def bx_cage_bake_on():
    press_ok("m3d.bg_cage_preview", _area=bgg_dock_context()[0])


@step
def bx_cage_bake():
    check(len(BGR.cage_objects()) == 1, "(the preview is on before the bake)")
    press_ok("m3d.bg_bake_all", _area=bgg_dock_context()[0])


step(wait_until(lambda: not QB.running(), "Bake All with the cage preview to finish (it is a queue of jobs: the window goes on)", 400))


@step
def bx_cage_bake_check():
    check(not BGR.cage_objects() and all(bgg_group_state(g) == 'BAKED' for g in ("Axe", "Bow", "Cup")), "Bake All takes the preview away and bakes every group")
    check(not GIZMO["bx_seen"], "no parked high poly was drawn during the bakes: %s" % GIZMO["bx_seen"])
    window().workspace.m3d_page_right = "tex_layers"   # (the dock stays on the Bake page after a bake: leave it)


step(wait_until(lambda: not BVW._view["on"], "the Bake mode view to go with the page (bake extras)", 40))


@step
def bx_cage_bake_parked():
    check(all(hp_ob(n).hide_get() and hp_ob(n).m3d_pair.parked for n in ("Axe_high", "Bow_high", "Cup_high")), "...they are hidden again")


# --- The ID map: a colour for each material of the high poly
@step
def bx_id_check():
    import numpy as np
    image = bpy.data.images.get("Axe_low_ID")
    check(image is not None and image.colorspace_settings.name == 'Non-Color' and "Axe_low_ID" in hp_ob("Axe_low").m3d_bake.baked.split("|"),
          "the ID map is baked with the others and listed in the Bake tab")
    a = px(image).reshape(64, 64, 4)
    colors = np.unique(np.round(a[..., :3], 3).reshape(-1, 3), axis=0)
    check(len(colors) == 2, "...two materials, two colours and nothing in between: %d" % len(colors))
    bpy.data.images["Axe_low_ID"].update()
    bx_redraw()


# --- Bake meshes: the parked high polys are shown for the export only, never drawn
@step
def bx_export_setup():
    dock, _region = bgg_dock_context()
    for ob in bpy.data.objects:
        ob.select_set(ob.name == "Axe_low")
    bpy.context.view_layer.objects.active = hp_ob("Axe_low")
    press_ok("m3d.tex_add_material", _area=dock)
    s = bpy.context.scene.m3d_tex
    s.export_folder, s.export_preset, s.export_bake_meshes = os.path.join(GIZMO["bx_dir"], "out"), 'UNREAL', True
    GIZMO["bx_flags"] = {n: (o.hide_get(), o.m3d_pair.parked, o.select_get()) for n, o in bpy.data.objects.items()}
    window().workspace.m3d_page_right = "tex_export"
    bx_redraw()


@step
def bx_export():
    press_ok("m3d.tex_export", _area=bgg_dock_context()[0])


@step
def bx_export_check():
    out = os.path.join(GIZMO["bx_dir"], "out")
    files = sorted(os.listdir(out)) if os.path.isdir(out) else []
    check("Axe_low.fbx" in files and "Axe_high.fbx" in files, "Export with Bake meshes writes the two files of the group: %s" % files)
    check({n: (o.hide_get(), o.m3d_pair.parked, o.select_get()) for n, o in bpy.data.objects.items()} == GIZMO["bx_flags"], "...and puts the parked high poly, the selection and the names back")
    check(not GIZMO["bx_seen"], "the parked high poly was never drawn while it was exported: %s" % GIZMO["bx_seen"])
    check(not tracebacks(), "Python error in the export")
    # The check can see: a high poly that is shown on purpose is seen by the draw handler.
    hp_ob("Cup_high").hide_set(False)
    bx_redraw()
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN', iterations=1)   # (draws now, whatever the window is doing)


@step
def bx_control():
    seen = list(GIZMO["bx_seen"])
    hp_ob("Cup_high").hide_set(True)
    check("Cup_high" in seen, "(control: a high poly that is shown is seen by the draw handler)")
    bpy.types.SpaceView3D.draw_handler_remove(GIZMO.pop("bx_handle"), 'WINDOW')
    import shutil
    shutil.rmtree(GIZMO.pop("bx_dir"), ignore_errors=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    window().workspace.m3d_page_right = ""
    check(not tracebacks(), "Python error in the bake extras tests")
    bpy.ops.m3d.workspace(kind='MODEL')


# --- Shift + double-click an edge: the edges between it and the edge clicked before, along their ring (the real keys).
step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling for the edges between test"))


@step
def eb_setup():
    with hp_viewport():
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=6, y_subdivisions=6, size=6)
        bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'EDGE'})
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        bpy.ops.view3d.view_axis(type='TOP')
        bpy.ops.view3d.view_all(center=True)


def eb_selected():
    mesh = bmesh.from_edit_mesh(bpy.context.active_object.data)
    return sorted((round((e.verts[0].co.x + e.verts[1].co.x) / 2, 2), round((e.verts[0].co.y + e.verts[1].co.y) / 2, 2))
                  for e in mesh.edges if e.select)


@step
def eb_click_first():
    xy = rt_xy(Vector((-0.5, -2.0, 0.0)))
    event('MOUSEMOVE', xy=xy)
    event('LEFTMOUSE', 'PRESS', xy)
    event('LEFTMOUSE', 'RELEASE', xy)


@step
def eb_shift_double_click():
    check(eb_selected() == [(-0.5, -2.0)], "(the first edge is selected by a click: %s)" % eb_selected())
    # The first click of the double-click (Shift+click toggles the edge on). Simulated events never make a double-click,
    # so the operator the Shift+double-click key runs is invoked with the pointer on the edge, after the click.
    xy = rt_xy(Vector((-0.5, 1.0, 0.0)))
    event('MOUSEMOVE', xy=xy)
    event('LEFT_SHIFT', 'PRESS', xy, shift=True)
    event('LEFTMOUSE', 'PRESS', xy, shift=True)
    event('LEFTMOUSE', 'RELEASE', xy, shift=True)
    event('LEFT_SHIFT', 'RELEASE', xy)


@step
def eb_double_click():
    km = bpy.context.window_manager.keyconfigs.active.keymaps["Mesh"]
    kmis = {(k.shift, k.ctrl, k.properties.deselect) for k in km.keymap_items
            if k.idname == "m3d.select_edges_between" and k.type == 'LEFTMOUSE' and k.value == 'DOUBLE_CLICK'}
    check(kmis == {(True, False, False), (False, True, True)}, "Shift / Ctrl + double-click run Select Edges Between: %s" % kmis)
    with hp_viewport():
        bpy.ops.m3d.select_edges_between('INVOKE_DEFAULT')


@step
def eb_check():
    check(eb_selected() == [(-0.5, y) for y in (-2.0, -1.0, 0.0, 1.0)],
          "Shift+double-click an edge up the ring: the edges between are selected: %s" % eb_selected())
    bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    check(not tracebacks(), "Python error in the edges between test")


# ----------------------------------------------------------------------------------------------------
# Phase 4 in the real window: the New Texture Project dialog, the Texture Set List and Texture Set Settings (channels, formats, size, mesh map
# slots), Bake Mesh Maps (Bake, Back to Painting), the Export Textures dialog (Ctrl+Shift+E, then its summary). Pictures: F:/AI/m3d_new_project.png,
# m3d_texset_settings.png, m3d_bake_mode.png, m3d_export_dialog.png.
import shutil

import m3d_texset


def t4_key(key, **mods):
    xy = tex_xy()
    event('MOUSEMOVE', xy=xy)
    event(key, 'PRESS', xy, **mods)
    event(key, 'RELEASE', xy, **mods)


def t4_redraw():
    for a in window().screen.areas:
        a.tag_redraw()


def t4_files(folder):
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


@step
def t4_setup():
    lb_sandbox()
    LIB._gen.update(shipped=True, done=False)   # (the Library uses the thumbnails that come with the program: none is made while these steps run)
    check(not LIB.pending(), "the starter items have their thumbnails already: the first Texture workspace makes none")
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    for mat in [m for m in bpy.data.materials if m.name.startswith(("T4", "Crate4", "Barrel4"))]:
        bpy.data.materials.remove(mat)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.m3d.add_primitive(kind='CUBE')
        bpy.context.active_object.name = "Crate4"
    GIZMO["t4_dir"] = tempfile.mkdtemp(prefix="m3d_t4_")
    event('MOUSEMOVE', xy=(region.x + region.width // 2, region.y + region.height // 2))
    event('F4', 'PRESS', (region.x + region.width // 2, region.y + region.height // 2))
    event('F4', 'RELEASE', (region.x + region.width // 2, region.y + region.height // 2))


step(wait_until(lambda: window().workspace.name == "Texture" and bpy.context.mode == 'PAINT_TEXTURE', "F4 for the texture sets tests"))


@step
def t4_no_project():
    ob = bpy.context.active_object
    check(window().workspace.m3d_layout == 1 and ob.name == "Crate4" and not ob.material_slots, "(a cube without a material in the Texture workspace)")
    check(not m3d_texture.texture_sets(bpy.context), "there is no texture set yet")
    window().workspace.m3d_page_right = "tex_layers"
    check(m3d_texture.no_project(bpy.context), "no project: the start card")
    t4_redraw()


@step
def t4_project_open():
    check(not tracebacks(), "Python error drawing the Texture workspace without a project")
    bpy.context.scene.m3d_tex.resolution = '1024'   # (the dialog starts at the scene's last project size: the Library steps set a small one)
    GIZMO["t4_defaults"] = (bpy.context.scene.m3d_tex.resolution, bpy.context.scene.m3d_tex.normal_format)
    roles = tex_roles()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=roles["sets"], region=next(r for r in roles["sets"].regions if r.type == 'WINDOW')):
        check(bpy.ops.m3d.tex_project.poll(), "New Texture Project is there for the selected mesh")
        bpy.ops.m3d.tex_project('INVOKE_DEFAULT')


@step
def t4_project_shot():
    t4_redraw()


@step
def t4_project_shot2():
    check(not tracebacks(), "Python error drawing the New Texture Project dialog")
    e_screenshot("F:/AI/m3d_new_project.png")


@step
def t4_project_ok():
    t4_key('RET')   # (the dialog's OK: the defaults, 1024 px, the default channels)


step(wait_until(lambda: bpy.context.active_object.active_material is not None and len(bpy.context.active_object.active_material.m3d_layers) == 1, "the New Texture Project dialog to make the project"))


@step
def t4_project_check():
    ob = bpy.context.active_object
    mat = ob.active_material
    check(mat is not None and len(mat.m3d_layers) == 1 and mat.m3d_layers[0].name == "Base" and mat.m3d_size == 1024 and LY.stack_size(mat) == 1024
          and [c.id for c in LY.set_channels(mat)] == ['BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL', 'HEIGHT'],
          "OK in the New Texture Project dialog made a texture set with a Base layer of 1024 px and the default channels")
    check(window().workspace.m3d_page_right == "tex_layers" and window().workspace.name == "Texture", "...and the dock shows the Layers (Bake Mesh Maps opens from its button)")
    roles = tex_roles()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=roles["dock"], region=next(r for r in roles["dock"].regions if r.type == 'WINDOW'),
                                   space_data=roles["dock"].spaces.active):
        shown = [c.__name__ for c in (*m3d_texture.classes, *m3d_texset.classes) if hasattr(c, "poll") and getattr(c, "page", "") in {"tex_layers", "tex_settings", "tex_bake"} and c.poll(bpy.context)]
    check("PROPERTIES_PT_m3d_tx_stack" in shown and not {"PROPERTIES_PT_m3d_tx_set_general", "PROPERTIES_PT_m3d_tx_bake_high"} & set(shown),
          "...the dock draws the Layers, not Texture Set Settings or the Bake page: %s" % shown)
    check(not tracebacks(), "Python error making the project")
    # small images keep the rest of the tests quick
    bpy.context.scene.m3d_tex.set_size = '128'
    s = ob.m3d_bake
    s.resolution, s.margin, s.samples = '64', 4, 2
    s.use_normal, s.use_ao, s.use_curvature, s.use_position, s.use_thickness, s.use_id, s.use_worldnormal = True, True, False, False, False, False, False
    check(LY.stack_size(mat) == 128, "(the set is 128 px from now on: %s)" % LY.stack_size(mat))
    t4_redraw()


# --- Bake Mesh Maps: the page, the Bake button, Back to Painting
T4 = {}   # what the 2D view showed before the bake


@step
def t4_bake_open():
    t4_key('B', ctrl=True, shift=True)


@step
def t4_bake_page():
    roles = tex_roles()
    check(window().workspace.m3d_page_right == "tex_bake", "Ctrl+Shift+B shows the Bake page in the dock")
    with bpy.context.temp_override(window=window(), screen=window().screen, area=roles["dock"], region=next(r for r in roles["dock"].regions if r.type == 'WINDOW'),
                                   space_data=roles["dock"].spaces.active):
        shown = [c.__name__ for c in (*m3d_texture.classes, *LIB.classes) if hasattr(c, "poll") and getattr(c, "page", "") == "tex_bake" and c.poll(bpy.context)]
    check(set(shown) == {"PROPERTIES_PT_m3d_tx_bake_high", "PROPERTIES_PT_m3d_tx_bake_maps", "PROPERTIES_PT_m3d_tx_bake_settings"},
          "Bake Mesh Maps shows Size and Bake, High Poly and Maps: %s" % shown)
    for role, want in (("assets", {"PROPERTIES_PT_m3d_tx_baked"}), ("props", {"PROPERTIES_PT_m3d_tx_bake_view", "PROPERTIES_PT_m3d_tx_bake_advanced"})):
        area = roles[role]
        with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=next(r for r in area.regions if r.type == 'WINDOW'),
                                       space_data=area.spaces.active):
            shown = {c.__name__ for c in (*m3d_texture.classes, *LIB.classes, *BV.classes) if hasattr(c, "page") and hasattr(c, "poll") and c.poll(bpy.context)}
        check(shown == want, "...%s shows %s instead of what painting needs: %s" % (role, sorted(want), sorted(shown)))
    image_area = m3d_texture.view_areas(window().screen)[1]
    with bpy.context.temp_override(window=window(), screen=window().screen, area=image_area):
        m3d_texture.show_in_2d(bpy.context, image_area.spaces.active, 'MATERIAL')   # (the material's picture, pinned)
    T4["2d"] = (image_area.spaces.active.image, image_area.spaces.active.use_image_pin)
    check(T4["2d"][0] is not None and T4["2d"][1], "(the 2D view shows the material: %s)" % (T4["2d"],))
    bpy.context.scene.m3d_tex.bake_map = 'AO'
    t4_redraw()


@step
def t4_bake_shot():
    check(not tracebacks(), "Python error drawing Bake Mesh Maps")
    e_screenshot("F:/AI/m3d_bake_mode.png")
    e_screenshot("F:/AI/m3d_fb_bake_page.png")


@step
def t4_bake_press():
    check(m3d_texture.bake_count(bpy.context) == (2, 1), "the Bake button counts 2 maps x 1 set: %s" % (m3d_texture.bake_count(bpy.context),))
    press_ok("m3d.tex_bake_sets", _area=tex_roles()["dock"])


step(wait_until(lambda: not QB.running(), "the Bake button to finish (it is a queue of jobs: the window goes on)", 400))


@step
def t4_bake_check():
    ob = bpy.context.active_object
    check({"Crate4_Normal", "Crate4_AO"} <= set(bpy.data.images.keys()) and ob.m3d_bake.baked == "Crate4_Normal|Crate4_AO", "Bake in the window baked the ticked maps: %s" % ob.m3d_bake.baked)
    check(tuple(bpy.data.images["Crate4_AO"].size) == (64, 64), "...at the size of the settings")
    check(window().workspace.m3d_page_right == "tex_bake" and not tracebacks(), "...and the dock stays on the Bake page when it is done; no Python error")
    space = m3d_texture.view_areas(window().screen)[1].spaces.active
    check(space.image == bpy.data.images["Crate4_AO"] and space.use_image_pin and space.ui_mode == 'VIEW', "...the 2D view shows the last map it baked: %s" % space.image)
    mat = ob.active_material
    check(mat.m3d_baked_normal == bpy.data.images["Crate4_Normal"] and mat.m3d_baked_ao == bpy.data.images["Crate4_AO"] and "m3d_layer.NORMAL.encode" in mat.node_tree.nodes
          and LY.principled_of(mat).inputs["Base Color"].links[0].from_node.name == LY.AO_MUL, "...the baked normal and AO are in the shader of the set")
    check(m3d_texture.view_mode_3d(bpy.context, tex_view()[0].spaces.active) == 'MATERIAL' and tex_view()[0].spaces.active.shading.type == 'MATERIAL', "...and the 3D view shows the material")
    t4_redraw()


@step
def t4_back_open():
    press_ok("m3d.tex_bake_mode", _area=tex_roles()["dock"], on=True)


@step
def t4_back():
    check(window().workspace.m3d_page_right == "tex_bake", "(Bake Mesh Maps is open again)")
    press_ok("m3d.tex_bake_mode", _area=tex_roles()["dock"], on=False)


@step
def t4_back_check():
    check(window().workspace.m3d_page_right == "tex_layers", "Back to Painting shows the Layers again")
    t4_redraw()


@step
def t4_back_2d():
    space = m3d_texture.view_areas(window().screen)[1].spaces.active
    check((space.image, space.use_image_pin) == T4["2d"] and "m3d_2d_bake" not in window().workspace,
          "...and the 2D view shows what it showed before the bake: %s %s, before %s" % (space.image, space.use_image_pin, T4["2d"]))


# --- Maps older than the mesh: a mesh baked on its own is tracked like a bake group; Rebake in the Layers
@step
def t4_stale():
    ob = bpy.context.active_object
    check(BGR.set_state(bpy.context, ob) == 'BAKED', "a mesh baked on its own is tracked: baked")
    ob.location.x += 0.1
    bpy.context.view_layer.update()
    check(BGR.set_state(bpy.context, ob) == 'STALE' and m3d_texture.stale_sets(bpy.context), "moving it makes its maps older than the mesh")
    t4_redraw()


@step
def t4_stale_drawn():
    check(not tracebacks(), "Python error drawing the out-of-date maps (the icon of the Texture Set List, the line of the Layers)")
    check(press_ok("m3d.tex_rebake", _area=tex_roles()["dock"], materials=bpy.context.active_object.active_material.name) == {'FINISHED'},
          "Rebake starts")


step(wait_until(lambda: not QB.running(), "Rebake to finish", 400))


@step
def t4_stale_rebaked():
    check(BGR.set_state(bpy.context, bpy.context.active_object) == 'BAKED' and not tracebacks(), "Rebake bakes it again: up to date")


# --- The Texture Set List and Texture Set Settings
@step
def t4_sets():
    roles = tex_roles()
    sets = m3d_texture.texture_sets(bpy.context)
    check([(m.name, o.name) for m, o in sets] == [("Crate4_Material", "Crate4")], "the Texture Set List has the set: %s" % [(m.name, o.name) for m, o in sets])
    rows = [r.name for r in bpy.context.scene.m3d_tex.sets]
    check(rows == ["Crate4_Material"] and bpy.context.scene.m3d_tex.set_index == 0, "...it is a row of the list (made by the panel's request) and the active one: %s" % rows)
    res = press_ok("m3d.tex_set_rename", _run='EXEC_DEFAULT', _area=roles["sets"], material="Crate4_Material", name="Crate4 Wood")
    check(bpy.data.materials.get("Crate4 Wood") is not None and bpy.context.active_object.active_material.name == "Crate4 Wood", "Rename renames the set in the window")
    check(all(m.preview is None for m, _o in sets), "the Texture Set List asks for no material preview (a preview job copies the material: an image removed meanwhile is a dangling pointer in the copy)")
    window().workspace.m3d_page_right = "tex_settings"
    t4_redraw()


@step
def t4_settings():
    check(not tracebacks(), "Python error drawing Texture Set Settings")
    roles = tex_roles()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=roles["dock"], region=next(r for r in roles["dock"].regions if r.type == 'WINDOW'),
                                   space_data=roles["dock"].spaces.active):
        shown = [c.__name__ for c in (*m3d_texture.classes, *m3d_texset.classes) if hasattr(c, "poll") and getattr(c, "page", "") == "tex_settings" and c.poll(bpy.context)]
    check({"PROPERTIES_PT_m3d_tx_set_general", "PROPERTIES_PT_m3d_tx_set_channels", "PROPERTIES_PT_m3d_tx_set_maps"} <= set(shown), "the settings tab shows General, Channels and Mesh Maps: %s" % shown)
    mat = bpy.context.active_object.active_material
    press_ok("m3d.tex_channel_remove", _area=roles["dock"], channel='HEIGHT')


@step
def t4_channel_removed():
    mat = bpy.context.active_object.active_material
    check(mat.m3d_off == "HEIGHT|EMISSION" and "m3d_layer.HEIGHT" not in mat.node_tree.nodes and LY.entry_of(mat.m3d_layers[0], 'HEIGHT').image is not None,
          "the x of a channel removes it from the set and keeps its image")
    press_ok("m3d.tex_channel_add", _area=tex_roles()["dock"], channel='HEIGHT')


@step
def t4_channel_added():
    mat = bpy.context.active_object.active_material
    check(mat.m3d_off == "EMISSION" and "m3d_layer.HEIGHT" in mat.node_tree.nodes, "adding it again builds it again")
    press_ok("m3d.tex_channel_format", _area=tex_roles()["dock"], _run='EXEC_DEFAULT', channel='HEIGHT', depth='16')


@step
def t4_format_check():
    mat = bpy.context.active_object.active_material
    image = LY.entry_of(mat.m3d_layers[0], 'HEIGHT').image
    check(image.is_float and image.use_half_precision and mat.m3d_depth == "HEIGHT" and "m3d_layer.HEIGHT" in mat.node_tree.nodes, "the format menu stores Height as 16 bit float")
    bpy.context.scene.m3d_tex.set_size = '256'


@step
def t4_size_check():
    mat = bpy.context.active_object.active_material
    check(LY.stack_size(mat) == 256 and all(tuple(i.size) == (256, 256) for i in LY.stack_images(mat)) and bpy.context.scene.m3d_tex.set_size == '256',
          "the Size dropdown scales every image of the set")
    check(not tracebacks(), "Python error after the channel and size changes")
    check(press_ok("m3d.tex_set_size", _area=tex_roles()["dock"], size='128') == {'RUNNING_MODAL'}, "a smaller size asks first (painted images lose detail)")


@step
def t4_size_down_cancel():
    t4_key('ESC')


@step
def t4_size_down_check():
    check(LY.stack_size(bpy.context.active_object.active_material) == 256 and not tracebacks(), "...Esc keeps the size")
    t4_redraw()


@step
def t4_settings_shot():
    e_screenshot("F:/AI/m3d_texset_settings.png")


# --- Export Textures: Ctrl+Shift+E opens the dialog, OK writes the files, a summary lists them
@step
def t4_export_open():
    check(bpy.context.mode == 'PAINT_TEXTURE', "(Texture Paint Mode before the export key)")
    s = bpy.context.scene.m3d_tex
    s.export_folder, s.export_preset, s.export_size, s.export_padding, s.export_format, s.export_depth = os.path.join(GIZMO["t4_dir"], "out"), 'UNREAL', 'SAME', 'INFINITE', 'PNG', '8'
    s.export_bake_meshes = False
    t4_key('E', ctrl=True, shift=True)


@step
def t4_export_shot():
    check(not tracebacks(), "Python error opening the Export Textures dialog with Ctrl+Shift+E")
    t4_redraw()


@step
def t4_export_shot2():
    e_screenshot("F:/AI/m3d_export_dialog.png")


@step
def t4_export_ok():
    t4_key('RET')   # (Export)


step(wait_until(lambda: t4_files(os.path.join(GIZMO["t4_dir"], "out")) != [], "the dialog to write the files", tries=40))


@step
def t4_export_check():
    files = t4_files(os.path.join(GIZMO["t4_dir"], "out"))
    check(files == ["T_Crate4_BC.png", "T_Crate4_N.png", "T_Crate4_ORM.png"], "the Export dialog wrote the files of the template: %s" % files)
    check(not tracebacks(), "Python error exporting")
    t4_redraw()


@step
def t4_export_summary():
    s = bpy.context.scene.m3d_tex
    check(len([f for f in s.export_files.split("|") if f]) == len(t4_files(os.path.join(GIZMO["t4_dir"], "out"))), "the files written are listed for the summary")
    check(not tracebacks(), "Python error opening the summary of the export")
    t4_key('RET')   # (closes the summary)


@step
def t4_export_buttons():
    roles = tex_roles()
    check(not tracebacks(), "Python error closing the summary")
    s = bpy.context.scene.m3d_tex
    s.export_preset = 'MESHMAPS'
    with bpy.context.temp_override(window=window(), screen=window().screen, area=roles["dockbar"], region=next(r for r in roles["dockbar"].regions if r.type == 'WINDOW')):
        check(bpy.ops.m3d.tex_export_dialog.poll(), "the dock strip button and the toolbar button open the dialog (it has a poll)")
    shutil.rmtree(os.path.join(GIZMO["t4_dir"], "out"), ignore_errors=True)
    s.export_preset = 'UNITY'


# --- Feedback on the redesigned workspace: a bake shows in the viewport (the normal detail on a low poly, in Material view), the clean
# headers with the whole name in the dropdown, the 2D view showing Material, the viewport types, the Display Settings. Pictures:
# F:/AI/m3d_fb_baked.png, m3d_fb_headers.png, m3d_fb_2d_material.png, m3d_fb_display.png (m3d_fb_bake_page.png is above).
def fb_view_text(area):
    """The text the display dropdown of a view of the Texture screen shows."""
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
        space = area.spaces.active
        mode = m3d_texture.view_mode_3d(bpy.context, space) if area.type == 'VIEW_3D' else m3d_texture.view_mode_2d(bpy.context, space)
        return m3d_texture.mode_text(bpy.context, mode), mode


def fb_area(kind):
    return next(a for a in window().screen.areas if a.type == kind)


@step
def fb_setup():
    """A low poly sphere and a high poly with dimples: the bake has detail to show. Nothing else is shown (Crate4 is hidden)."""
    import numpy as np
    for ob in bpy.data.objects:
        ob.hide_set(True)
    area, region = tex_view()
    with bpy.context.temp_override(window=window(), area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.0)
        high = bpy.context.active_object
        high.name = "FbHigh"
        co = np.empty(len(high.data.vertices) * 3, np.float32)
        high.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        bump = 1.0 + 0.07 * np.sin(9 * co[:, 0]) * np.sin(9 * co[:, 1]) * np.sin(9 * co[:, 2]) + 0.03 * np.sin(23 * co[:, 0] + 1) * np.sin(19 * co[:, 2])
        high.data.vertices.foreach_set("co", (co * bump[:, None]).ravel())
        high.data.polygons.foreach_set("use_smooth", [True] * len(high.data.polygons))
        high.data.update()
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1.0)
        low = bpy.context.active_object
        low.name = "FbLow"
        bpy.ops.object.shade_smooth()
        for o in bpy.data.objects:
            o.select_set(o == low)
        bpy.context.view_layer.objects.active = low
        bpy.ops.m3d.tex_project('EXEC_DEFAULT', resolution='512', template='DEFAULT', unwrap=False, bake_after=False)
        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
        high.hide_set(True)
        for m in bpy.data.materials:
            if m != low.active_material:
                m.m3d_set_bake = False
        s = low.m3d_bake
        s.high, s.resolution, s.samples, s.margin, s.extrusion = high, '512', 8, 8, 0.2
        s.use_normal = s.use_ao = True
        s.use_curvature = s.use_position = s.use_thickness = s.use_id = s.use_worldnormal = False
        for o in bpy.data.objects:
            o.select_set(o == low)
        bpy.ops.view3d.view_selected()
    window().workspace.m3d_page_right = "tex_layers"
    check(window().workspace.m3d_page_right == "tex_layers" and low.active_material.m3d_baked_normal is None, "(a low poly and its high poly, nothing baked yet)")
    t4_redraw()


@step
def fb_bake():
    press_ok("m3d.tex_bake_sets", _area=tex_roles()["dock"])


step(wait_until(lambda: not QB.running(), "the Bake button of the feedback tests to finish (it is a queue of jobs: the window goes on)", 400))


@step
def fb_baked_check():
    low = bpy.data.objects["FbLow"]
    mat = low.active_material
    check(not tracebacks(), "Python error baking a low poly and a high poly")
    normal = bpy.data.images.get("FbLow_Normal")
    check(normal is not None and normal.get("m3d_bake") == "Normal" and mat.m3d_baked_normal == normal and bpy.data.images.get("FbLow_AO") == mat.m3d_baked_ao,
          "the bake made the Normal and AO maps and the set uses them: %s" % mat.m3d_baked_normal)
    import numpy as np
    px = np.empty(len(normal.pixels), np.float32)
    normal.pixels.foreach_get(px)
    check(float(np.ptp(px.reshape(-1, 4)[:, 0])) > 0.2, "the baked normal has detail (red spans %.2f)" % np.ptp(px.reshape(-1, 4)[:, 0]))
    check("m3d_layer.NORMAL.encode" in mat.node_tree.nodes and mat.node_tree.nodes["m3d_layer.NORMAL.map"].inputs["Color"].links[0].from_node.name == "m3d_layer.NORMAL.encode"
          and LY.principled_of(mat).inputs["Normal"].links[0].from_node.name in {"m3d_layer.NORMAL.map", "m3d_layer.HEIGHT.bump"}
          and LY.principled_of(mat).inputs["Base Color"].links[0].from_node.name == LY.AO_MUL, "...the shader combines the baked normal with the layers' normal and multiplies the Base Color by the AO")
    area = fb_area('VIEW_3D')
    check(area.spaces.active.shading.type == 'MATERIAL' and window().workspace.m3d_page_right == "tex_layers", "...the 3D view is in Material and the dock on the Layers")
    t4_redraw()


@step
def fb_baked_wait():
    t4_redraw()


@step
def fb_baked_shot():
    check(not tracebacks(), "Python error drawing the baked material")
    e_screenshot("F:/AI/m3d_fb_baked.png")


@step
def fb_headers_setup():
    mat = bpy.data.objects["FbLow"].active_material
    LY.active_layer(mat).name = "Rust"
    press_ok("m3d.tex_view_mode", _area=fb_area('VIEW_3D'), mode="CHANNEL:BASE_COLOR")
    press_ok("m3d.tex_view_mode", _area=fb_area('IMAGE_EDITOR'), mode="CHANNEL:BASE_COLOR")
    t4_redraw()


@step
def fb_headers_check():
    check(not tracebacks(), "Python error drawing the clean headers")
    for kind in ('VIEW_3D', 'IMAGE_EDITOR'):
        text, mode = fb_view_text(fb_area(kind))
        check(text == "Base Color (Rust)" and mode == "CHANNEL:BASE_COLOR", "the %s dropdown shows the whole name: %r" % (kind, text))
    try:
        import blf
        scale = bpy.context.preferences.system.ui_scale
        blf.size(0, 11 * scale)
        width = blf.dimensions(0, "Base Color (Rust)")[0]
        check(m3d_texture.dropdown_units("Base Color (Rust)") * 20 * scale >= width + 60 * scale, "...the dropdown is wide enough for it (%.0f px of text in %.0f)" % (width, m3d_texture.dropdown_units("Base Color (Rust)") * 20 * scale))
    except Exception as err:
        print("blf:", err)
    t4_redraw()


@step
def fb_headers_shot():
    e_screenshot("F:/AI/m3d_fb_headers.png")


@step
def fb_2d_material():
    press_ok("m3d.tex_view_mode", _area=fb_area('IMAGE_EDITOR'), mode='MATERIAL')
    press_ok("m3d.tex_view_mode", _area=fb_area('VIEW_3D'), mode='MATERIAL')
    t4_redraw()


@step
def fb_2d_material_check():
    space = fb_area('IMAGE_EDITOR').spaces.active
    mat = bpy.data.objects["FbLow"].active_material
    check(space.image is not None and space.image.get("m3d_preview") == mat.name and space.ui_mode == 'VIEW' and space.use_image_pin,
          "the 2D view shows Material: a picture of the material, pinned so that a new paint target does not replace it (%s)" % (space.image and space.image.name))
    check(fb_view_text(fb_area('IMAGE_EDITOR'))[0] == "Material" and fb_view_text(fb_area('VIEW_3D'))[0] == "Material", "...both dropdowns say Material")
    import numpy as np
    px = np.empty(len(space.image.pixels), np.float32)
    space.image.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    check(float(px[:, :3].std()) > 0.01, "...with the lit detail of the baked normal in it (std %.3f)" % px[:, :3].std())
    check(not tracebacks(), "Python error drawing the 2D view's Material")
    t4_redraw()


@step
def fb_2d_material_wait():
    t4_redraw()


@step
def fb_2d_material_shot():
    e_screenshot("F:/AI/m3d_fb_2d_material.png")


@step
def fb_2d_refresh():
    """A change of the layers makes the picture again (the timer): a fill layer of a strong color changes it."""
    mat = bpy.data.objects["FbLow"].active_material
    area = fb_area('IMAGE_EDITOR')
    press_ok("m3d.layer_add", _area=tex_roles()["dock"], kind='FILL')
    layer = LY.active_layer(mat)
    layer.channels[0].color = (0.9, 0.1, 0.1, 1.0)
    check(mat.name in m3d_texture._preview["dirty"], "a change of the layers makes the Material View out of date")


step(wait_until(lambda: not (bpy.data.objects["FbLow"].active_material.name in m3d_texture._preview["dirty"]), "the timer to make the Material View again", tries=30))


@step
def fb_2d_refresh_check():
    import numpy as np
    image = fb_area('IMAGE_EDITOR').spaces.active.image
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    check(px[:, 0].mean() > 1.5 * px[:, 1].mean(), "...and it shows the red fill now (red %.2f, green %.2f on average)" % (px[:, 0].mean(), px[:, 1].mean()))
    press_ok("m3d.layer_remove", _area=tex_roles()["dock"])
    check(not tracebacks(), "Python error refreshing the Material View")


@step
def fb_types():
    """The viewport type of the 3D view: every type through the operator the dropdown calls, read back from the view."""
    area = fb_area('VIEW_3D')
    shading, mat = area.spaces.active.shading, bpy.data.objects["FbLow"].active_material
    scene = bpy.context.scene
    GIZMO["fb_engine"] = scene.render.engine
    for kind, want in (('UNLIT', 'MATERIAL'), ('SOLID', 'SOLID'), ('WIRE', 'MATERIAL'), ('RENDERED', 'RENDERED'), ('MATERIAL', 'MATERIAL')):
        press_ok("m3d.tex_view_type", _area=tex_roles()["dockbar"], kind=kind)
        check(shading.type == want and m3d_texture.view_type_of(area.spaces.active, mat) == kind and mat.m3d_unlit == (kind == 'UNLIT')
              and area.spaces.active.overlay.show_wireframes == (kind == 'WIRE'), "viewport type %s: shading %s, read back %s" % (kind, shading.type, m3d_texture.view_type_of(area.spaces.active, mat)))
        if kind == 'UNLIT':
            check(LY.output_node(mat.node_tree).inputs["Surface"].links[0].from_node.name == LY.MASKVIEW, "...Unlit shows an Emission of the Base Color")
        if kind == 'RENDERED':
            check(scene.render.engine == 'BLENDER_EEVEE', "...Rendered is EEVEE")
    scene.render.engine = GIZMO["fb_engine"]
    check(not tracebacks(), "Python error switching the viewport type")
    t4_redraw()


@step
def fb_defaults_check():
    """The 3D view of the Texture workspace starts as a studio: the studio HDRI, blurred behind the model."""
    sh = fb_area('VIEW_3D').spaces.active.shading
    check(sh.type == 'MATERIAL' and sh.studio_light == "studio.exr" and abs(sh.studiolight_background_blur - 0.5) < 1e-6 and sh.studiolight_background_alpha == 1.0,
          "the 3D view starts with the studio environment: %s, blur %.2f, background %.2f" % (sh.studio_light, sh.studiolight_background_blur, sh.studiolight_background_alpha))
    check(window().workspace.get("m3d_env") == 2, "(the workspace remembers that it did)")
    ov = fb_area('VIEW_3D').spaces.active.overlay
    check(not ov.show_floor and not ov.show_axis_x and not ov.show_axis_y, "...without the floor grid and the axis lines")
    xy = tex_roles()["dockbar"]
    event('MOUSEMOVE', xy=(xy.x + xy.width // 2, xy.y + xy.height - 30))
    with bpy.context.temp_override(window=window(), screen=window().screen, area=xy, region=next(r for r in xy.regions if r.type == 'WINDOW')):
        bpy.ops.wm.call_panel('INVOKE_DEFAULT', name="M3D_PT_tex_display", keep_open=True)


@step
def fb_display_shot():
    check(not tracebacks(), "Python error drawing Display Settings")
    e_screenshot("F:/AI/m3d_fb_display.png")
    event('ESC', 'PRESS')
    event('ESC', 'RELEASE')


# -----------------------------------------------------------------------------
# Bake queue and the view of Bake Mesh Maps: a bake that does not freeze the window (a queue of Blender's bake jobs), the guard that lets
# the view move and blocks everything else, Esc and Cancel, the blue high poly and the red cage problems.
import time

import m3d_bakeview as BV


def bq_sphere(name, u=24, v=12, push=None, push_by=0.0, cut=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")   # (the sphere gets its UVs on the active layer)
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1.0, calc_uvs=True)
    if push is not None:
        for vert in bm.verts:
            if push(vert.co):
                vert.co *= (1.0 + push_by)
    if cut is not None:
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if cut(f.calc_center_median())], context='FACES')
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


BQ = {}


def bq_flags():
    """Everything a queue puts away and has to put back."""
    sc, vl = bpy.context.scene, bpy.context.view_layer
    return ({o.name: (o.hide_get(), o.hide_viewport, o.hide_render, o.hide_select, o.select_get(), o.display_type, o.m3d_pair.parked,
                      [(s.link, s.material.name if s.material else None) for s in o.material_slots], o.show_transparent)
             for o in bpy.data.objects}, vl.objects.active.name if vl.objects.active else None, sc.render.engine, sc.cycles.samples,
            sc.cycles.device, bpy.context.mode, len([m for m in bpy.data.materials if m.name.startswith("m3dBake")]),
            [(a.spaces.active.shading.type) for a in window().screen.areas if a.type == 'VIEW_3D'])


def bq_dock():
    return tex_roles()["dock"]


def bq_sets_checkbox():
    """Where the Bake checkbox of the first row of the Texture Set List is (window pixels)."""
    area = tex_roles()["sets"]
    return area.x + area.width - 31, area.y + area.height - 48


@step
def bq_to_modeling():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: hp_in('MODEL') and bpy.context.mode == 'OBJECT', "Modeling for the bake queue tests"))


@step
def bq_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for entry in list(bpy.context.scene.m3d_bake_groups):
        bpy.context.scene.m3d_bake_groups.remove(0)
    high = bq_sphere("Orb_high", u=400, v=200, push=lambda co: co.z > 0.8, push_by=0.25, cut=lambda co: co.x > 0.9)
    low = bq_sphere("Orb_low")
    mat = bpy.data.materials.new("OrbMat")
    mat.use_nodes = True
    low.data.materials.append(mat)
    high.data.materials.append(bpy.data.materials.new("OrbHighMat"))
    bpy.context.view_layer.update()
    check(bpy.ops.m3d.hp_auto_pair() == {'FINISHED'}, "(the sphere and its high poly are paired)")
    s = low.m3d_bake
    s.resolution, s.margin = '1024', 8
    s.use_normal = s.use_ao = s.use_curvature = s.use_thickness = True
    s.use_position = s.use_id = s.use_worldnormal = False
    entry = BGR.settings_of(bpy.context, "Orb")
    entry.extrusion, entry.ray_distance = 0.05, 0.3
    bpy.context.scene.m3d_tex.bake_gpu = False   # (on a GPU the queue is over before the steps can look at it)
    HPR.park_all(bpy.context)
    for ob in bpy.data.objects:
        ob.select_set(ob.name == "Orb_low")
    bpy.context.view_layer.objects.active = low
    BQ["draws"], BQ["steps"] = [0], [0]

    def draws():
        BQ["draws"][0] += 1
    BQ["handle"] = bpy.types.SpaceView3D.draw_handler_add(draws, (), 'WINDOW', 'POST_PIXEL')
    check(hp_ob("Orb_high").hide_get() and hp_ob("Orb_high").m3d_pair.parked, "(the high poly is parked)")
    bpy.ops.m3d.workspace(kind='TEXTURE')


step(wait_until(lambda: hp_in('TEXTURE') and bpy.context.mode == 'PAINT_TEXTURE', "Texture Paint Mode for the bake queue tests"))


@step
def bq_open_page():
    BQ["before"] = bq_flags()
    window().workspace.m3d_page_right = "tex_bake"


step(wait_until(lambda: BV._view["on"] and BV._view["areas"] is not None, "the Bake mode view and its cage check", 100))


@step
def bq_view_check():
    high = hp_ob("Orb_high")
    check(not tracebacks(), "Python error in the Bake mode view")
    check(not high.hide_get() and [(s.link, s.material.name) for s in high.material_slots] == [('OBJECT', BV.MATERIAL)] and high.show_transparent,
          "Bake mode shows the high poly as the blue see-through material through its object slots: %s" % ([(s.link, s.material.name) for s in high.material_slots],))
    check([m.name for m in high.data.materials] == ["OrbHighMat"], "...the mesh and its material are not touched")
    check(BV.status_lines() == [("Cage too tight here: raise Cage Distance", True), ("Rays find no high poly here: the high poly does not cover it", True)],
          "...and the cage check finds the two problems (the high poly sticks out at the top and is missing at the side): %s" % (BV.status_lines(),))
    cage = BV._view["result"]["Orb_low"]
    check(cage.lines is not None and cage.tris is not None and cage.problems > 0, "...as batches the draw handler only draws (%d bad faces)" % cage.problems)
    check(bpy.data.materials[BV.MATERIAL].surface_render_method == 'BLENDED', "(the blue is blended)")
    win, area, region = view3d()
    from mathutils import Euler
    area.spaces.active.region_3d.view_rotation = Euler((math.radians(72), 0.0, math.radians(58))).to_quaternion()   # (a three-quarter view: the cap and the side)
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region, space_data=area.spaces.active):
        bpy.ops.view3d.view_all(center=False)
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bq_view_redraw():
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bq_view_shot():
    e_screenshot("F:/AI/m3d_bake_viz.png")


@step
def bq_fit():
    """Auto-fit Cage (next to the cage check in High Poly) fits the Cage Distance around the bump; the hole stays a problem."""
    press_ok("m3d.bake_cage_fit", _area=bq_dock())


step(wait_until(lambda: BV._view["areas"] is not None and BV._view["kinds"].get("tight") == 0, "the cage check after Auto-fit Cage", 100))


@step
def bq_fit_check():
    entry = bpy.context.scene.m3d_bake_groups["Orb"]
    check(0.25 < entry.extrusion < 0.5 and entry.ray_distance >= 0.3, "Auto-fit Cage set the group's Cage Distance past the bump (0.25): %.3f" % entry.extrusion)
    check(BV.status_lines() == [("Rays find no high poly here: the high poly does not cover it", True)], "...the check runs again: only the hole is left: %s" % BV.status_lines())
    check(not tracebacks(), "Python error in Auto-fit Cage")
    entry.extrusion, entry.ray_distance = 0.05, 0.3


step(wait_until(lambda: BV._view["areas"] is not None and BV._view["kinds"].get("tight") == 1, "the cage check with the old Cage Distance", 100))


@step
def bq_control_click():
    """(control) a click on the Bake checkbox of a texture set works while nothing bakes."""
    mat = bpy.data.materials["OrbMat"]
    BQ["checked"] = mat.m3d_set_bake
    x, y = bq_sets_checkbox()
    event('MOUSEMOVE', xy=(x, y))
    event('LEFTMOUSE', 'PRESS', xy=(x, y))
    event('LEFTMOUSE', 'RELEASE', xy=(x, y))


@step
def bq_control_check():
    mat = bpy.data.materials["OrbMat"]
    check(mat.m3d_set_bake != BQ["checked"], "(control: a click on the Bake checkbox of the Texture Set List toggles it)")
    mat.m3d_set_bake = BQ["checked"]
    BQ["tick"] = 0


@step
def bq_start():
    BQ["draws0"] = BQ["draws"][0]
    BQ["t0"] = time.monotonic()
    BQ["swap"] = bpy.data.materials["OrbMat"].m3d_set_bake
    BQ["select"] = [o.name for o in bpy.data.objects if o.select_get()]
    BQ["objects"] = len(bpy.data.objects)
    BQ["rot"] = view3d()[1].spaces.active.region_3d.view_rotation.copy()
    BQ["dist"] = view3d()[1].spaces.active.region_3d.view_distance
    press_ok("m3d.tex_bake_sets", _area=bq_dock())
    check(QB.running(), "the Bake button starts a queue and returns at once")


def bq_in_job():
    run = QB._run
    return run is not None and run.phase == 'WAIT' and run.count >= 1 and bpy.app.is_job_running('OBJECT_BAKE')


step(wait_until(bq_in_job, "the second bake of the queue to run as a job", 200))


@step
def bq_while_baking():
    check(QB.running() and bpy.app.is_job_running('OBJECT_BAKE') and window().workspace.m3d_page_right == "tex_bake", "a bake job runs and the Bake page is shown")
    check(BQ["draws"][0] > BQ["draws0"] + 3, "the window keeps drawing during the bake (%d redraws of the 3D view)" % (BQ["draws"][0] - BQ["draws0"]))
    check(not BV._view["on"] and not any(BV.KEY in o for o in bpy.data.objects), "the view of the Bake page is put away while the queue bakes")
    space = m3d_texture.view_areas(window().screen)[1].spaces.active
    check(space.image is not None and space.image.name == "Orb_low_Normal" and space.use_image_pin and QB.baked_names() == {"Orb_low_Normal"},
          "the 2D view shows the map the queue finished (the next one bakes): %s" % space.image)
    check(bpy.context.scene.render.engine == 'CYCLES' and hp_ob("Orb_high").display_type == 'BOUNDS', "(Cycles is the engine, the high poly is drawn as a box meanwhile)")
    BQ["steps"][0] += 1
    win, area, region = view3d()
    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    BQ["rv0"] = area.spaces.active.region_3d.view_rotation.copy()
    event('MOUSEMOVE', xy=(cx, cy))
    event('LEFTMOUSE', 'PRESS', xy=(cx, cy), alt=True)
    for i in range(1, 9):
        event('MOUSEMOVE', xy=(cx + i * 14, cy + i * 4), alt=True)
    event('LEFTMOUSE', 'RELEASE', xy=(cx + 120, cy + 32), alt=True)


@step
def bq_orbit_check():
    rv = view3d()[1].spaces.active.region_3d
    angle = rv.view_rotation.rotation_difference(BQ["rv0"]).angle
    check(angle > 0.05 and QB.running(), "an Alt+drag orbits the view while the bake runs (%.2f rad)" % angle)
    BQ["dist0"] = rv.view_distance
    win, area, region = view3d()
    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    event('MOUSEMOVE', xy=(cx, cy))
    for _ in range(3):
        event('WHEELUPMOUSE', 'PRESS', xy=(cx, cy))


@step
def bq_wheel_check():
    rv = view3d()[1].spaces.active.region_3d
    check(rv.view_distance < BQ["dist0"] - 1e-4 and QB.running(), "...the wheel zooms (%.2f -> %.2f)" % (BQ["dist0"], rv.view_distance))
    win, area, region = view3d()
    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    BQ["dist1"] = rv.view_distance
    BQ["loc1"] = rv.view_location.copy()
    event('MOUSEMOVE', xy=(cx, cy))
    event('F', 'PRESS', xy=(cx, cy))
    event('F', 'RELEASE', xy=(cx, cy))


@step
def bq_frame_check():
    rv = view3d()[1].spaces.active.region_3d
    check(QB.running() and ((rv.view_distance - BQ["dist1"]) ** 2 + (rv.view_location - BQ["loc1"]).length_squared) > 1e-8, "...and F frames the model")
    # Clicks and keys that edit are blocked: the viewport (a click selects), the Texture Set List, keys that delete or save
    win, area, region = view3d()
    cx, cy = region.x + region.width // 2, region.y + region.height // 2
    BQ["sel1"] = [o.name for o in bpy.data.objects if o.select_get()]
    BQ["n1"] = len(bpy.data.objects)
    for xy in ((cx - 60, cy - 60), (cx + 40, cy + 20)):
        event('MOUSEMOVE', xy=xy)
        event('LEFTMOUSE', 'PRESS', xy=xy)
        event('LEFTMOUSE', 'RELEASE', xy=xy)
    event('MOUSEMOVE', xy=(cx, cy))
    for key in ('X', 'DEL'):
        event(key, 'PRESS', xy=(cx, cy))
        event(key, 'RELEASE', xy=(cx, cy))
    event('S', 'PRESS', xy=(cx, cy), ctrl=True)
    event('S', 'RELEASE', xy=(cx, cy), ctrl=True)
    for key, mods in (('Z', {"ctrl": True}), ('F1', {}), ('TAB', {})):   # undo, another workspace, another mode
        event(key, 'PRESS', xy=(cx, cy), **mods)
        event(key, 'RELEASE', xy=(cx, cy), **mods)
    BQ["mode"], BQ["kind"] = bpy.context.mode, m3d_workspace.workspace_kind(window().workspace)
    x, y = bq_sets_checkbox()
    event('MOUSEMOVE', xy=(x, y))
    event('LEFTMOUSE', 'PRESS', xy=(x, y))
    event('LEFTMOUSE', 'RELEASE', xy=(x, y))
    BQ["draws1"] = BQ["draws"][0]


@step
def bq_blocked_check():
    check([o.name for o in bpy.data.objects if o.select_get()] == BQ["sel1"] and len(bpy.data.objects) == BQ["n1"], "a click in the 3D view, X and Delete change nothing during the bake")
    check(bpy.context.mode == BQ["mode"] and m3d_workspace.workspace_kind(window().workspace) == BQ["kind"] == 'TEXTURE' and bpy.data.objects.get("Orb_low") is not None,
          "Ctrl+Z, F1 (another workspace) and Tab (another mode) do nothing during the bake (%s, %s)" % (bpy.context.mode, BQ["kind"]))
    check(bpy.data.materials["OrbMat"].m3d_set_bake == BQ["swap"], "a click on a Texture Set row (a layer, a list, a panel) is blocked")
    check(QB.running(), "(the queue is still running)")
    check(QB._run is not None and time.monotonic() - QB._run.blocked < 5.0, "the guard noted the clicks it stopped (the banner flashes)")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bq_progress_redraw():
    for a in window().screen.areas:
        a.tag_redraw()


@step
def bq_progress_shot():
    e_screenshot("F:/AI/m3d_bake_progress.png")
    check(QB.text().startswith("Baking") and QB.progress()[1] == 4, "the progress says what bakes: %s (%s)" % (QB.text(), QB.progress()))


step(wait_until(lambda: not QB.running(), "the queue to finish", 600))


@step
def bq_done_check():
    check(not tracebacks(), "no Python error during the queue")
    check(all(bpy.data.images.get("Orb_low_" + n) is not None for n in ("Normal", "AO", "Curvature", "Thickness")), "the queue baked every map")
    check(bgg_group_state("Orb") == 'BAKED', "...the group is baked")
    check(window().workspace.m3d_page_right == "tex_bake", "...and the dock stays on the Bake page")
    space = m3d_texture.view_areas(window().screen)[1].spaces.active
    check(space.image is not None and space.image.name == "Orb_low_Thickness", "...the 2D view shows the last map: %s" % space.image)
    check(QB.progress()[0] == 0 and QB.text() == "", "no progress is shown when it is over")
    window().workspace.m3d_page_right = "tex_layers"


step(wait_until(lambda: not BV._view["on"], "the Bake mode view to go with the page", 100))


@step
def bq_done_left():
    after = bq_flags()
    check(after[0]["Orb_high"] == BQ["before"][0]["Orb_high"] and after[1:] == BQ["before"][1:], "everything is put back as it was before Bake Mesh Maps was opened: %s vs %s" % (after[1:], BQ["before"][1:]))
    check(not any(BV.KEY in o for o in bpy.data.objects) and BV.MATERIAL not in bpy.data.materials, "the Bake mode view is gone with the page")
    check("m3d_2d_bake" not in window().workspace, "(the 2D view has what it had)")
    bpy.context.scene.m3d_tex.bake_gpu = True
    win, area, region = view3d()
    event('MOUSEMOVE', xy=(region.x + 5, region.y + 5))


@step
def bq_display_open():
    """The Display Settings that a header offers while a bake runs (they have no setting of the scene) draw without a Python error."""
    area, region = tex_view()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region, space_data=area.spaces.active):
        bpy.ops.wm.call_panel('INVOKE_DEFAULT', name="M3D_PT_tex_display_baking", keep_open=True)


@step
def bq_display_check():
    check(not tracebacks(), "Python error drawing the Display Settings of a bake")
    event('ESC', 'PRESS')
    event('ESC', 'RELEASE')


# Esc cancels the running job (Blender's own), everything is put back
@step
def bq_cancel_open():
    for name in ("Normal", "AO", "Curvature", "Thickness"):
        bpy.data.images.remove(bpy.data.images["Orb_low_" + name])
    bpy.context.scene.m3d_bake_groups["Orb"].state = 'NONE'
    window().workspace.m3d_page_right = "tex_bake"


step(wait_until(lambda: BV._view["on"] and BV._view["areas"] is not None, "the Bake mode view again", 100))


@step
def bq_esc_start():
    BQ["before"] = bq_flags()
    BQ["esc_view"] = [(s.link, s.material.name) for s in hp_ob("Orb_high").material_slots]
    press_ok("m3d.tex_bake_sets", _area=bq_dock())


step(wait_until(bq_in_job, "the second bake of the queue to run as a job (Esc)", 200))


@step
def bq_esc():
    win, area, region = view3d()
    event('MOUSEMOVE', xy=(region.x + 50, region.y + 50))
    event('ESC', 'PRESS', xy=(region.x + 50, region.y + 50))
    event('ESC', 'RELEASE', xy=(region.x + 50, region.y + 50))


step(wait_until(lambda: not QB.running(), "Esc to cancel the queue", 200))


@step
def bq_esc_check():
    check(not tracebacks(), "no Python error when Esc cancels the bake")
    check(bgg_group_state("Orb") != 'BAKED' and window().workspace.m3d_page_right == "tex_bake", "Esc cancelled the bake: the group is not baked, the Bake page stays")


step(wait_until(lambda: BV._view["on"] and BV._view["areas"] is not None, "the Bake mode view comes back after Esc", 100))


@step
def bq_esc_restored():
    after = bq_flags()
    check(after[0] == BQ["before"][0] and after[1:] == BQ["before"][1:],
          "Esc restored everything exactly (selection, hidden, display, slots, engine, samples, device, mode): %s" % [k for k in after[0] if after[0][k] != BQ["before"][0].get(k)])
    check([(s.link, s.material.name) for s in hp_ob("Orb_high").material_slots] == BQ["esc_view"], "...and the Bake mode view is back as it was")


# The Cancel button stops the queue after the map that bakes
@step
def bq_cancel_start():
    BQ["before"] = bq_flags()
    press_ok("m3d.tex_bake_sets", _area=bq_dock())


step(wait_until(bq_in_job, "the second bake of the queue to run as a job (Cancel)", 200))


@step
def bq_cancel_press():
    dock = bq_dock()
    press_ok("m3d.bake_cancel", _area=dock)
    check(QB.cancelling(), "Cancel marks the queue")


step(wait_until(lambda: not QB.running(), "Cancel to end the queue", 600))


@step
def bq_cancel_check():
    check(not tracebacks(), "no Python error when Cancel stops the bake")
    check(bgg_group_state("Orb") != 'BAKED' and window().workspace.m3d_page_right == "tex_bake", "Cancel stopped the queue: the group is not baked")


step(wait_until(lambda: BV._view["on"] and BV._view["areas"] is not None, "the Bake mode view comes back after Cancel", 100))


@step
def bq_cancel_restored():
    after = bq_flags()
    check(after[0] == BQ["before"][0] and after[1:] == BQ["before"][1:],
          "Cancel restored everything exactly: %s" % [k for k in after[0] if after[0][k] != BQ["before"][0].get(k)])


# Leaving Bake mode puts the high poly back
@step
def bq_leave():
    window().workspace.m3d_page_right = "tex_layers"


step(wait_until(lambda: not BV._view["on"], "the Bake mode view to go away", 100))


@step
def bq_leave_check():
    high = hp_ob("Orb_high")
    check(high.hide_get() and high.m3d_pair.parked and [(s.link, s.material.name if s.material else None) for s in high.material_slots] == [('DATA', "OrbHighMat")]
          and not high.show_transparent and BV.MATERIAL not in bpy.data.materials and BV.KEY not in high,
          "leaving Bake mode parks the high poly again and gives it its own material back")
    check(bq_flags()[1:] == BQ["before"][1:], "...and nothing else changed: %s vs %s" % (bq_flags()[1:], BQ["before"][1:]))
    # A whole bake from the Bake page, undone
    window().workspace.m3d_page_right = "tex_bake"


step(wait_until(lambda: BV._view["on"] and BV._view["areas"] is not None, "the Bake mode view once more", 100))


@step
def bq_last_bake():
    BQ["state0"] = bpy.context.scene.m3d_bake_groups["Orb"].state
    for ob in bpy.data.objects:
        ob.select_set(ob.name == "Orb_low")
    dock = bq_dock()
    with bpy.context.temp_override(window=window(), screen=window().screen, area=dock, region=next(r for r in dock.regions if r.type == 'WINDOW'), space_data=dock.spaces.active):
        res = bpy.ops.m3d.tex_bake_sets('INVOKE_DEFAULT', True)   # (True: the call makes its undo step, as a click on the button does)
    check(res == {'FINISHED'}, "(the Bake button with its undo step)")


step(wait_until(lambda: not QB.running(), "the last queue to finish", 800))


@step
def bq_last_check():
    check(bgg_group_state("Orb") == 'BAKED' and window().workspace.m3d_page_right == "tex_bake", "(the last bake is done)")
    check(not tracebacks(), "no Python error in the bake queue tests")


@step
def bq_undo():
    """One Undo takes the whole queued bake back (the step of the button is the one before the first bake; the queue adds one at its end)."""
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.ed.undo() == {'FINISHED'}, "Undo after a queued bake runs")


@step
def bq_undo_check():
    entry = bpy.context.scene.m3d_bake_groups.get("Orb")
    check(entry is not None and entry.state != 'BAKED' and not QB.running(), "...and the group is not baked any more (%s, it was %s before the bake)" % (entry.state if entry else None, BQ["state0"]))
    check(not tracebacks(), "no Python error in the Undo of the bake")


@step
def bq_cleanup():
    bpy.types.SpaceView3D.draw_handler_remove(BQ.pop("handle"), 'WINDOW')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    for entry in list(bpy.context.scene.m3d_bake_groups):
        bpy.context.scene.m3d_bake_groups.remove(0)
    window().workspace.m3d_page_right = ""
    bpy.ops.m3d.workspace(kind='MODEL')


@step
def fb_cleanup():
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    check(not tracebacks(), "Python error in the feedback tests")


@step
def t4_cleanup():
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    shutil.rmtree(GIZMO.pop("t4_dir"), ignore_errors=True)
    s = bpy.context.scene.m3d_tex
    s.export_folder, s.export_padding, s.resolution = "//textures/", 'INFINITE', '2048'
    window().workspace.m3d_page_right = ""
    check(not tracebacks(), "Python error in the texture sets tests")
    bpy.ops.m3d.workspace(kind='MODEL')


# --- UX part 5: on a narrow window the docks keep the size their panels fit in (the views give up the room); the keys in the
# tooltips of the Texture tool strip come from the keymap.
P5 = {}


def p5_right():
    """The editors of the Texture layout's right column (Texture Sets, the dock, Properties)."""
    win = window()
    return [a for a in win.screen.areas if a.type == 'PROPERTIES' and m3d_workspace.area_role(win, a) in {'SETS', 'RIGHT', 'PROPS'}]


@step
def p5_fit_open():
    bpy.ops.m3d.workspace(kind='TEXTURE')


@step
def p5_fit_edge():
    area = p5_right()[0]
    event('MOUSEMOVE', xy=(area.x - 1, area.y + area.height // 2))   # (on an edge: area_move runs only there)


@step
def p5_fit_setup():
    win = window()
    area = next(a for a in p5_right() if m3d_workspace.area_role(win, a) == 'SETS')
    P5["scale"] = bpy.context.preferences.system.ui_scale or 1.0
    shrink = area.width - int(200 * P5["scale"])   # (the column narrower than its smallest size, as on a small screen)
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.area_move(x=area.x - 1, y=area.y + area.height // 2, delta=shrink)


@step
def p5_fit_pointer():
    """The pointer over an editor: area_move can't run, the fit waits (it tries again); then on the edge between two editors."""
    win = window()
    P5["before"] = [a.width for a in p5_right()]   # (the sizes are new after a redraw)
    m3d_workspace._fitted[win.as_pointer()] = (win.width, win.height, win.screen.as_pointer())
    area = p5_right()[0]
    event('MOUSEMOVE', xy=(area.x + area.width // 2, area.y + area.height // 2))


@step
def p5_fit_wait():
    check(m3d_workspace.fit_window(window().as_pointer()) == 0.25, "with the pointer over an editor the fit waits and tries again")
    area = p5_right()[0]
    event('MOUSEMOVE', xy=(area.x - 1, area.y + area.height // 2))


@step
def p5_fit():
    check(m3d_workspace.fit_window(window().as_pointer()) is None, "...on the edge between two editors it fits the columns")


@step
def p5_fit_check():
    need = int(next(px for role, side, px in m3d_workspace.MIN_SIZES['TEXTURE'] if (role, side) == ('SETS', 'W')) * P5["scale"])
    widths = [a.width for a in p5_right()]
    check(max(P5["before"]) < need and min(widths) >= need - 2,
          "a column narrower than its smallest size gets wide enough again, all of it: %s -> %s (%d)" % (P5["before"], widths, need))
    for tool, key in (('PAINT', "1"), ('CLONE', "6"), ('PICKER', "P")):
        check("(%s)" % key in m3d_texture.M3D_OT_tex_tool.description(bpy.context, SimpleNamespace(tool=tool)), "the tool strip's tooltip has the key of %s" % tool)
    check(not tracebacks(), "no Python error while fitting the columns")
    bpy.ops.m3d.workspace(kind='MODEL')


# --- Shared chrome: every task workspace hides the navigation bar beside its own tabs (All Settings brings it back), the
# status bar shows the keys of the mode, a one-line command line shows no example line over the prompt.
POL = {}


def pol_dock():
    return next(a for a in props_areas() if a.as_pointer() == POL["dock"])


@step
def pol_model():
    bpy.ops.m3d.workspace(kind='MODEL')
    for area in window().screen.areas:
        area.tag_redraw()


step(wait_until(lambda: window().workspace.name == "Modeling" and props_areas() and all(nav_width(a) <= 1 for a in props_areas()),
                "no navigation bar beside the Modeling dock"))


@step
def pol_all_settings():
    dock = props_areas()[0]
    POL["dock"], POL["context"] = dock.as_pointer(), dock.spaces.active.context
    dock.spaces.active.context = 'SCENE'   # What the All Settings tab shows (with nothing active).
    dock.tag_redraw()


step(wait_until(lambda: nav_width(pol_dock()) > 1, "the navigation bar with All Settings in Modeling"))


@step
def pol_tab_again():
    dock = pol_dock()
    dock.spaces.active.context = POL["context"] if POL["context"] in m3d_workspace.DOCK_CONTEXTS else 'CHANNEL_BOX'
    dock.tag_redraw()


step(wait_until(lambda: nav_width(pol_dock()) <= 1, "...and gone again on a tab of the dock"))


@step
def pol_hints():
    with bpy.context.temp_override(window=window(), screen=window().screen):
        mode, found = bpy.context.mode, m3d_ui.status_hints(bpy.context)
    labels = [hint[0] for hint in found[0]] if found else []
    if mode in {'OBJECT', 'EDIT_MESH'} and not window().modal_operators:
        check(labels[:3] == ["Select", "Toggle", "Deselect"] and "Marking Menu" in labels and "Hotbox" in labels,
              "the status bar has the keys of Modeling (%s): %s" % (mode, labels))
    console = next((a for a in window().screen.areas if a.type == 'CONSOLE'), None)
    if console is not None:
        region, sc = next(r for r in console.regions if r.type == 'WINDOW'), console.spaces.active
        if region.height < 2 * sc.font_size * (bpy.context.preferences.system.ui_scale or 1.0) + 8:
            check(not any("MEL command line" in line.body for line in sc.scrollback),
                  "a one-line command line has no example line over the prompt (%d px)" % region.height)
    bpy.ops.m3d.workspace(kind='RIG')
    for area in window().screen.areas:
        area.tag_redraw()


step(wait_until(lambda: window().workspace.name == "Rigging" and len(props_areas()) >= 2 and all(nav_width(a) <= 1 for a in props_areas()),
                "no navigation bar beside the Rigging docks, left and right"))


@step
def pol_done():
    check(not tracebacks(), "Python error in the shared chrome checks")
    bpy.ops.m3d.workspace(kind='MODEL')


# --- Dock pages: an empty state is one card (why + the button that fixes it), and its button fits the situation: with a camera
# selected, Rendering > Materials picks an object that can have a material; Skin adds the mesh to the skeleton's selection;
# Layers without animation sets a key.
POLB = {}


def polb_redraw():
    for area in window().screen.areas:
        area.tag_redraw()


def polb_select(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob


@step
def polb_setup():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.mesh.primitive_cube_add(location=(0, 9, 0))
        box = bpy.context.object
        box.name = "PB_Box"
        box.data.materials.clear()
        bpy.ops.object.camera_add(location=(6, 3, 2))
        bpy.context.object.name = "PB_Cam"
        bpy.ops.object.armature_add(location=(-3, 9, 0))
        bpy.context.object.name = "PB_Arm"
    bpy.ops.m3d.workspace(kind='RENDER')


step(wait_until(lambda: window().workspace.name == "Rendering", "the Rendering workspace"))


@step
def polb_materials():
    polb_select(bpy.data.objects["PB_Cam"])
    press_ok("m3d.dock_page", _area=rn_dock(), tab="render_materials")
    polb_redraw()


@step
def polb_materials_card():
    check(not tracebacks(), "Python error drawing the Materials card (a camera selected)")
    rn_press("m3d.pick_object", name="PB_Box", extend=False)
    check(bpy.context.active_object == bpy.data.objects["PB_Box"] and not bpy.data.objects["PB_Cam"].select_get(),
          "Materials with a camera selected: the card's button selects an object that can have a material")
    polb_redraw()


@step
def polb_materials_new():
    check(not tracebacks(), "Python error drawing the Materials card (a mesh without material)")
    rn_press("m3d.assign_material")
    box = bpy.data.objects["PB_Box"]
    check(box.active_material is not None and m3d_render.principled(box.active_material) is not None,
          "...then Assign New Material gives it one with a Principled shader")
    polb_redraw()


@step
def polb_skin():
    check(not tracebacks(), "Python error drawing the Materials page with a material")
    bpy.ops.m3d.workspace(kind='RIG')


step(wait_until(lambda: window().workspace.name == "Rigging", "the Rigging workspace"))


@step
def polb_skin_page():
    polb_select(bpy.data.objects["PB_Arm"])
    press_ok("m3d.dock_page", _area=rig_dock()[1], tab="rig_skin")
    polb_redraw()


@step
def polb_skin_pick():
    check(not tracebacks(), "Python error drawing the Skin card")
    press_ok("m3d.pick_object", _area=rig_dock()[1], name="PB_Box", extend=True)
    arm, box = bpy.data.objects["PB_Arm"], bpy.data.objects["PB_Box"]
    check(bpy.context.active_object == arm and arm.select_get() and box.select_get() and m3d_rig.skin_mesh(bpy.context) == box,
          "Skin: the card's button adds the mesh to the selection, the skeleton stays active (ready for Bind)")
    polb_redraw()


@step
def polb_layers():
    check(not tracebacks(), "Python error drawing the Skin page")
    bpy.ops.m3d.workspace(kind='ANIM')


step(wait_until(lambda: window().workspace.name == "Animation", "the Animation workspace"))


@step
def polb_layers_page():
    polb_select(bpy.data.objects["PB_Box"])
    press_ok("m3d.dock_page", _area=an_dock(), tab="anim_layers")
    polb_redraw()


@step
def polb_layers_key():
    check(not tracebacks(), "Python error drawing the Layers card")
    an_press("anim.keyframe_insert")
    ad = bpy.data.objects["PB_Box"].animation_data
    check(ad is not None and ad.action is not None, "Layers without animation: the card's Set Key keys the object")
    polb_redraw()


@step
def polb_done():
    check(not tracebacks(), "Python error drawing the Layers tab after a key")
    for name in ("PB_Box", "PB_Cam", "PB_Arm"):
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name])
    bpy.ops.m3d.workspace(kind='MODEL')


# ----------------------------------------------------------------------------------------------------
# Files, help and trust (UX pass 2, P5): Delete Workspace and its F-key, Windows > Command Line, a component tool from
# Object Mode, the status bar note, the card after a session that ended unexpectedly.

import m3d_help


@step
def p5_setup():
    import tempfile
    if not GIZMO.get("cfg"):   # (a run of this segment alone: the settings still go to a temp folder)
        GIZMO["cfg"] = tempfile.mkdtemp(prefix="m3d_gui_")
        m3d_user._path = lambda create=False: os.path.join(GIZMO["cfg"], "m3d_user.json")
        m3d_user.reset_cache()
    bpy.ops.m3d.workspace(kind='RIG')


step(wait_until(lambda: window().workspace.name == "Rigging", "the Rigging workspace"))


@step
def p5_delete_workspace():
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.workspace_delete() == {'FINISHED'}, "Delete Workspace")


step(wait_until(lambda: "Rigging" not in bpy.data.workspaces and window().workspace.name != "Rigging", "Rigging deleted"))


@step
def p5_fkey_restores():
    check(m3d_workspace.find_workspace('RIG') is None, "Rigging is gone")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.workspace(kind='RIG') == {'FINISHED'}, "F5 with Rigging deleted: it comes back")


step(wait_until(lambda: window().workspace.name == "Rigging", "the restored Rigging workspace"))


@step
def p5_fkey_restored():
    ws = window().workspace
    check(m3d_workspace.workspace_kind(ws) == 'RIG' and bpy.context.window_manager.m3d_menu_set == 'RIGGING'
          and any(a.type == 'PROPERTIES' for a in window().screen.areas) and not tracebacks(),
          "the restored Rigging: its factory layout and menu set")
    check(not any(a.type == 'CONSOLE' for a in window().screen.areas), "(Rigging has no command line)")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        check(bpy.ops.m3d.command_line() == {'FINISHED'}, "Windows > Command Line in Rigging")


@step
def p5_command_line():
    consoles = [a for a in window().screen.areas if a.type == 'CONSOLE']
    scale = bpy.context.preferences.system.ui_scale
    check(len(consoles) == 1 and consoles[0].height < 60 * scale and consoles[0].spaces.active.language == 'mel',
          "a one-line MEL command line under the 3D view: %s" % [(a.height, a.spaces.active.language) for a in consoles])
    view = max((a for a in window().screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    check(consoles and consoles[0].y < view.y and consoles[0].width == view.width, "...under it, as wide")


@step
def p5_command_line_tidy():
    console = next((a for a in window().screen.areas if a.type == 'CONSOLE'), None)
    sc = console.spaces.active if console else None
    check(sc is not None and not sc.show_region_header and sc.prompt == "MEL ", "the command line: no header, the MEL prompt")
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.command_line()


@step
def p5_command_line_closed():
    check(not any(a.type == 'CONSOLE' for a in window().screen.areas) and not tracebacks(), "Windows > Command Line again hides it")
    bpy.ops.m3d.workspace(kind='MODEL')


step(wait_until(lambda: window().workspace.name == "Modeling", "the Modeling workspace"))


@step
def p5_component_tool():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.m3d.add_primitive(kind='CUBE')
    ob = bpy.context.active_object
    GIZMO["p5_cube"] = ob.name
    # Edit Mesh > Add Divisions from the menu bar, the cube in Object Mode: it runs on the whole mesh in component mode.
    with bpy.context.temp_override(window=win, screen=win.screen):
        res = bpy.ops.m3d.call('INVOKE_DEFAULT', idname="mesh.subdivide", props="{}", label="Add Divisions")
    check(res == {'FINISHED'} and ob.mode == 'EDIT', "Add Divisions from Object Mode: component mode (%s, %s)" % (res, ob.mode))


@step
def p5_component_tool_explain():
    win, area, region = view3d()
    ob = bpy.data.objects[GIZMO["p5_cube"]]
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
    check(len(ob.data.polygons) == 24, "...on all of it (%d faces)" % len(ob.data.polygons))
    with bpy.context.temp_override(window=win, screen=win.screen):
        res = bpy.ops.m3d.call('INVOKE_DEFAULT', idname="mesh.merge", props="{'type': 'COLLAPSE'}", label="Collapse")
    check(res == {'CANCELLED'} and ob.mode == 'OBJECT' and len(ob.data.polygons) == 24, "Collapse from Object Mode: explained, nothing done")
    bpy.data.objects.remove(ob)
    # The status bar redraws for a note.
    GIZMO["p5_drawn"], GIZMO["p5_draw"] = [], m3d_help.draw_status

    def rec(layout):
        GIZMO["p5_drawn"].append(m3d_help.note_text())
        GIZMO["p5_draw"](layout)
    m3d_help.draw_status = rec
    m3d_help.show_note("P5 note", seconds=3.0)


step(wait_until(lambda: "P5 note" in GIZMO["p5_drawn"], "the status bar to show the note"))


@step
def p5_recover_card():
    import tempfile, time
    m3d_help.draw_status = GIZMO["p5_draw"]
    base = GIZMO["p5_base"] = tempfile.mkdtemp(prefix="m3d_gui_tmp_")
    GIZMO["p5_temp_base"], m3d_help.temp_base = m3d_help.temp_base, lambda: base
    for name, age in (("quit.blend", 100), ("scene_99999_autosave.blend", 10)):
        open(os.path.join(base, name), "w").close()
        os.utime(os.path.join(base, name), (time.time() - age, time.time() - age))
    m3d_help.offer_recovery()   # (the card opens: "Last session ended unexpectedly")
    path = os.path.join(base, "scene_99999_autosave.blend")
    check(m3d_user.data().get("recover_offered", [None])[0] == path and m3d_help.crash_autosave() is None and not tracebacks(),
          "the card for an auto save newer than the last quit, once")


@step
def p5_recover_card_close():
    import shutil
    event('ESC', 'PRESS')
    event('ESC', 'RELEASE')
    m3d_help.temp_base = GIZMO["p5_temp_base"]
    m3d_user.data().pop("recover_offered", None)
    m3d_user.save()
    shutil.rmtree(GIZMO["p5_base"], ignore_errors=True)


@step
def p5_done():
    check(not tracebacks(), "Python error in the P5 steps")


# ----------------------------------------------------------------------------------------------------
# UX pass 2, P9: render snapshots and their keys, the Shader Graph in F7, Scene Materials, the status bar notes (a texture not
# found, a background render: a real one), the Layer Editor, the turntable in Sculpt's Display tab, one Shader Editor window.
import m3d_help


def p9_redraw():
    for a in window().screen.areas:
        a.tag_redraw()
    m3d_help._redraw_status()


def p9_render_view_xy():
    region = next(r for r in rn_image_area().regions if r.type == 'WINDOW')
    return region.x + region.width // 2, region.y + region.height // 2


@step
def p9_setup():
    bpy.ops.m3d.workspace(kind='MODEL')
    for ob in list(bpy.data.objects):
        if ob.mode != 'OBJECT':
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    scene = bpy.context.scene
    r = scene.render
    GIZMO["p9_start"] = (r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, scene.frame_start, scene.frame_end)
    r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage = 'BLENDER_EEVEE', 32, 24, 100
    GIZMO["p9_samples"], scene.eevee.taa_render_samples = scene.eevee.taa_render_samples, 1
    scene.frame_start, scene.frame_end, scene.frame_current = 1, 2, 1
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.mesh.primitive_cube_add()
        box = bpy.context.active_object
        box.name = "P9Box"
        box.data.materials.append(bpy.data.materials.new("P9Mat"))
        bpy.ops.object.camera_add(location=(0, -6, 1), rotation=(math.radians(80), 0, 0))
    scene.camera = bpy.context.active_object
    m3d_render._camera_ok.add(scene.camera.name)
    m3d_render._slots.clear()
    GIZMO["p9_dir"] = tempfile.mkdtemp(prefix="m3d_gui_p9_")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(GIZMO["p9_dir"], "p9.blend"))
    r.filepath = "//render/"
    bpy.ops.m3d.workspace(kind='RENDER')


@step
def p9_render_one():   # (a step after the switch: the Render View is drawn by then)
    RN_DONE["renders"] = 0
    an_status("m3d.render")


step(wait_until(lambda: RN_DONE["renders"] >= 1 and not bpy.app.is_job_running('RENDER'), "the first P9 render", tries=60))


@step
def p9_render_two():
    RN_DONE["renders"] = 0
    an_status("m3d.render")


step(wait_until(lambda: RN_DONE["renders"] >= 1 and not bpy.app.is_job_running('RENDER'), "the second P9 render", tries=60))


@step
def p9_slots():
    image = m3d_render.render_result()
    slots = m3d_render._slots
    check(len(slots) == 2 and image.render_slots.active_index == slots[-1] and rn_image_area().spaces.active.image == image,
          "Keep Each Render: two renders, two slots, the newest shown (%s, %d)" % (slots, image.render_slots.active_index))
    check(all(m3d_render.SLOT_NAME.match(image.render_slots[i].name) for i in slots), "...named with the time")
    GIZMO["p9_frame"] = bpy.context.scene.frame_current
    xy = p9_render_view_xy()
    event('MOUSEMOVE', xy=xy)
    event('LEFT_ARROW', 'PRESS', xy)
    event('LEFT_ARROW', 'RELEASE', xy)


@step
def p9_slot_left():
    image = m3d_render.render_result()
    check(image.render_slots.active_index == m3d_render._slots[0], "Left over the Render View: the render before (%d)" % image.render_slots.active_index)
    check(bpy.context.scene.frame_current == GIZMO["p9_frame"], "...and not the frame")
    xy = p9_render_view_xy()
    event('J', 'PRESS', xy)
    event('J', 'RELEASE', xy)


@step
def p9_slot_j():
    image = m3d_render.render_result()
    check(image.render_slots.active_index == m3d_render._slots[-1], "J: the next render")
    an_status("m3d.render_graph")
    p9_redraw()


@step
def p9_graph():
    check(m3d_render.graph_shown(window().screen) and rn_image_area() is None, "Shader Graph: F7's middle area shows the graph")
    check(not tracebacks(), "Python error with the Shader Graph shown")
    RN_DONE["renders"] = 0
    an_status("m3d.render")


step(wait_until(lambda: RN_DONE["renders"] >= 1 and not bpy.app.is_job_running('RENDER'), "the render from the Shader Graph", tries=60))


@step
def p9_graph_render():
    check(not m3d_render.graph_shown(window().screen) and rn_image_area() is not None and len(m3d_render._slots) == 3,
          "a render brings the Render View back, into a third slot")
    check(len(bpy.context.window_manager.windows) == 1, "...without a render window: %s" % [[a.type for a in w.screen.areas]
                                                                      for w in bpy.context.window_manager.windows])
    rn_press("m3d.dock_page", tab="render_materials")
    p9_redraw()


@step
def p9_materials():
    check(window().workspace.m3d_page_right == "render_materials" and not tracebacks(), "Scene Materials drawn without an error")
    image = bpy.data.images.new("P9Missing", 4, 4)
    image.source = 'FILE'
    image.filepath_raw = os.path.join(GIZMO["p9_dir"], "gone.png")
    m3d_render._missing[:] = ["P9Missing"]
    GIZMO["p9_drawn"], GIZMO["p9_draw"] = [], m3d_render.draw_status

    def rec(layout):   # (what the status bar drew: the background render, the missing texture)
        GIZMO["p9_drawn"].append((m3d_render._bg["state"], tuple(m3d_render.still_missing())))
        GIZMO["p9_draw"](layout)
    m3d_render.draw_status = rec
    check(an_status("m3d.render_background") == {'FINISHED'} and m3d_render._bg["state"] == 'RUNNING', "Render Sequence in Background starts")
    p9_redraw()


step(wait_until(lambda: m3d_render._bg["state"] not in {None, 'RUNNING'}, "the background render", tries=150))
step(wait_until(lambda: (m3d_render._bg["state"], ("P9Missing",)) in GIZMO["p9_drawn"], "the status bar to show the result", tries=30))


@step
def p9_background_done():
    folder = os.path.join(GIZMO["p9_dir"], "render")
    files = sorted(n for n in os.listdir(folder) if n.endswith(".png")) if os.path.isdir(folder) else []
    check(m3d_render._bg["state"] == 'DONE' and len(files) == 2, "the background render saved both frames: %s, %s" % (m3d_render.background_text(), files))
    check(not tracebacks(), "Python error in the status bar (background render, texture not found)")
    m3d_render.draw_status = GIZMO["p9_draw"]
    check(('RUNNING', ("P9Missing",)) in GIZMO["p9_drawn"], "the status bar showed the progress and the texture not found")
    an_status("m3d.render_background_stop")
    an_status("m3d.missing_textures", dismiss=True)
    check(m3d_render._bg["state"] is None and not m3d_render.still_missing(), "the status bar notes close")
    bpy.data.images.remove(bpy.data.images["P9Missing"])
    # The Layer Editor with a layer inside another.
    outer, inner = bpy.data.collections.new("P9Outer"), bpy.data.collections.new("P9Inner")
    bpy.context.scene.collection.children.link(outer)
    outer.children.link(inner)
    inner.objects.link(bpy.data.objects["P9Box"])
    bpy.ops.m3d.workspace(kind='MODEL')
    with bpy.context.temp_override(window=window(), screen=window().screen):
        bpy.ops.m3d.dock_tab(tab='CHANNEL_BOX')
    p9_redraw()


@step
def p9_layers():
    check(not tracebacks(), "Python error in the Layer Editor with nested layers")
    box = bpy.data.objects["P9Box"]
    for ob in bpy.context.selected_objects:
        ob.select_set(False)
    box.select_set(True)
    bpy.context.view_layer.objects.active = box
    bpy.ops.m3d.turntable(turn='CAMERA')
    bpy.ops.m3d.workspace(kind='SCULPT')
    window().workspace.m3d_page_right = "sculpt_display"
    p9_redraw()


@step
def p9_turntable():
    check(m3d_render.turntable_pivot(bpy.context.scene) is not None and not tracebacks(), "the Turntable panel of Sculpt's Display tab")
    bpy.ops.m3d.turntable_remove()
    bpy.ops.m3d.workspace(kind='MODEL')
    GIZMO["p9_windows"] = len(bpy.context.window_manager.windows)
    an_status("m3d.open_editor", ui_type='ShaderNodeTree')


@step
def p9_editor_again():
    check(len(bpy.context.window_manager.windows) == GIZMO["p9_windows"] + 1, "a Shader Editor window opens")
    an_status("m3d.open_editor", ui_type='ShaderNodeTree')


@step
def p9_editor_once():
    wm = bpy.context.window_manager
    check(len(wm.windows) == GIZMO["p9_windows"] + 1, "a second click: still one Shader Editor window (%d)" % len(wm.windows))
    for win in list(wm.windows)[1:]:
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.window_close()


@step
def p9_done():
    check(len(bpy.context.window_manager.windows) == GIZMO["p9_windows"], "the Shader Editor window closes")
    check(not tracebacks(), "Python error in the P9 steps")
    scene = bpy.context.scene
    r = scene.render
    r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, scene.frame_start, scene.frame_end = GIZMO["p9_start"]
    scene.eevee.taa_render_samples = GIZMO["p9_samples"]
    shutil.rmtree(GIZMO["p9_dir"], ignore_errors=True)


@step
def finish():
    errors = "".join(stderr_tee.buf + sys.stdout.buf)
    check("Traceback" not in errors, "Python traceback in the output: " + errors[errors.find("Traceback"):][:600])
    with open(OUT, "w") as fh:
        fh.write("FAILS: %r\n" % (fails or "none"))
    bpy.ops.wm.quit_blender()


def run_next():
    fn = steps.pop(0)
    restore_window()   # (minimized while the steps run, e.g. started behind the apps in use: it would draw nothing)
    try:
        fn()
    except Exception as err:  # Report and quit rather than leave a window hanging.
        fails.append("%s: %r" % (fn.__name__, err))
        steps[:] = [finish]
    return 0.4 if steps else None


# M3D_GUI_FROM=<step name> skips the steps before it, M3D_GUI_TO=<step name> the steps after it (to iterate on one
# workspace; the full run is the one that counts).
_from, _to = os.environ.get("M3D_GUI_FROM"), os.environ.get("M3D_GUI_TO")
if _from or _to:
    _names = [fn.__name__ for fn in steps]
    steps[:] = steps[_names.index(_from) if _from else 0:_names.index(_to) + 1 if _to else None]
    if _to:
        steps.append(finish)

bpy.app.timers.register(run_next, first_interval=2.0)
