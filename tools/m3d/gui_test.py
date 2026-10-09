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
        edge["xy"], edge["delta"] = ((area.x + area.width, mid), want - area.width) if side == 'LEFT'             else ((area.x - 1, mid), area.width - want)
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


# Workspace Settings: the Settings button at the right end of the Status Line (a popover; the rows are clicked at
# fixed offsets from the window's top right: Reset Workspace, then the tabs of the dock).
WS_SETTINGS_X, WS_SETTINGS_Y = 51, 38           # the button, from the right / top edge (UI scale 1)
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
    check(len([c for c in rec["cells"] if c[2]]) == 22, "edit-mode shelf has a cell per button: %d" % len(rec["cells"]))


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
    check(scene.m3d_anim.playblast_note.startswith("Playblast: 3 frames"), "Playblast reports: %r" % scene.m3d_anim.playblast_note)
    check(not tracebacks(), "Python error in the Playblast")
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
    scene.eevee.taa_render_samples += 1
    check(m3d_render.current_quality(scene) == 'CUSTOM', "an edit reads Custom")
    for a in window().screen.areas:
        a.tag_redraw()


@step
def rn_quality_drawn():
    check(not tracebacks(), "Python error drawing the quality presets / Custom")
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'


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


# M3D_GUI_FROM=<step name> skips the steps before it, M3D_GUI_TO=<step name> the steps after it (to iterate on one
# workspace; the full run is the one that counts).
_from, _to = os.environ.get("M3D_GUI_FROM"), os.environ.get("M3D_GUI_TO")
if _from or _to:
    _names = [fn.__name__ for fn in steps]
    steps[:] = steps[_names.index(_from) if _from else 0:_names.index(_to) + 1 if _to else None]
    if _to:
        steps.append(finish)

bpy.app.timers.register(run_next, first_interval=2.0)
