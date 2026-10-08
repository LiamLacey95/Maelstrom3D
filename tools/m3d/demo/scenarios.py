# SPDX-License-Identifier: GPL-2.0-or-later
"""
Maelstrom3D demo scenarios for the README videos. Run by tools/m3d/demo/record.py:

    blender --factory-startup --enable-event-simulate --python scenarios.py -- <name> <status-dir>

Each scenario drives the UI with simulated input (keys, drags, marking menus), draws a cursor and a caption
(simulated input doesn't move the real cursor), writes <status-dir>/ready when recording can start and
<status-dir>/done when it is finished.
"""

import math
import os
import sys
import time
import traceback

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Matrix, Vector

NAME, STATUS = sys.argv[sys.argv.index("--") + 1:][:2]
FPS = 30
UI_SCALE = float(os.environ.get("M3D_UI_SCALE", "1.0"))
SCENARIO_UI_SCALE = {"mel": 1.8}   # (the MEL video is all text in the Command Line)
CAPTION_SIZE = 32  # Pixels at the full window size; the videos are scaled down.
state = {"mouse": (0, 0), "pressed": False, "caption": "", "mods": {}, "t0": time.time()}


# -----------------------------------------------------------------------------
# Overlay: cursor + caption

def _caption_lines(text, max_width):
    """Wrap the caption into at most two lines of about the same length."""
    if blf.dimensions(0, text)[0] <= max_width or " " not in text:
        return [text]
    words = text.split(" ")
    best = min(range(1, len(words)), key=lambda i: abs(blf.dimensions(0, " ".join(words[:i]))[0] -
                                                     blf.dimensions(0, " ".join(words[i:]))[0]))
    return [" ".join(words[:best]), " ".join(words[best:])]


def _caption_area():
    """The area that carries the caption: the widest 3D view (or paint view, when it is wider)."""
    areas = [a for a in bpy.context.window_manager.windows[0].screen.areas if a.type in {'VIEW_3D', 'IMAGE_EDITOR'}]
    return max(areas, key=lambda a: a.width) if areas else None


def _draw_overlay():
    region = bpy.context.region
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    area = bpy.context.area
    first = min((r for r in area.regions if r.type == 'WINDOW'), key=lambda r: (r.y, r.x)) if area else None
    if state["caption"] and region.type == 'WINDOW' and area == _caption_area() and region == first:
        size = int(CAPTION_SIZE * bpy.context.preferences.view.ui_scale)
        blf.size(0, size)
        lines = _caption_lines(state["caption"], region.width - 4 * size)
        widths = [blf.dimensions(0, line)[0] for line in lines]
        line_h = size * 1.35
        pad = size * 0.55
        box_w, box_h = max(widths) + 2 * pad, line_h * len(lines) - (line_h - size) + 2 * pad
        bx, by = (region.width - box_w) / 2, 30
        box = [(bx, by), (bx + box_w, by), (bx + box_w, by + box_h), (bx, by + box_h)]
        shader.uniform_float("color", (0.06, 0.06, 0.06, 0.82))
        batch_for_shader(shader, 'TRI_FAN', {"pos": box}).draw(shader)
        blf.color(0, 1, 1, 1, 1)
        for i, (line, w) in enumerate(zip(lines, widths)):
            blf.position(0, bx + (box_w - w) / 2, by + pad + (len(lines) - 1 - i) * line_h, 0)
            blf.draw(0, line)
    gpu.state.blend_set('NONE')


def _add_handlers():
    handles = []
    for name in ("SpaceView3D", "SpaceProperties", "SpaceImageEditor", "SpaceConsole", "SpaceOutliner",
                 "SpaceDopeSheetEditor", "SpaceGraphEditor", "SpaceNLA", "SpaceNodeEditor"):
        space = getattr(bpy.types, name)
        handles.append((space, space.draw_handler_add(_draw_overlay, (), 'WINDOW', 'POST_PIXEL')))
    return handles


HANDLES = _add_handlers()


def _start_cursor():
    """The pointer: a window of its own that follows state["mouse"] (see oscursor.py)."""
    import ctypes
    import ctypes.wintypes as wt
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from oscursor import OsCursor
    user32 = ctypes.windll.user32
    user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    pid = os.getpid()
    cursor = OsCursor()
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, ctypes.c_void_p, wt.LPARAM)
    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
        return True

    def sync():
        found.clear()
        user32.EnumWindows(visit, 0)
        if found:
            rect, origin = wt.RECT(), wt.POINT(0, 0)
            user32.GetClientRect(found[0], ctypes.byref(rect))
            user32.ClientToScreen(found[0], ctypes.byref(origin))
            x, y = state["mouse"]
            cursor.update(origin.x + x, origin.y + rect.bottom - y, state["pressed"])
        return 1 / 60
    bpy.app.timers.register(sync, first_interval=0.5, persistent=True)
    return cursor


CURSOR = _start_cursor() if os.name == "nt" else None


def _redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


# -----------------------------------------------------------------------------
# Input helpers (generators: `yield seconds` waits)

def win():
    return bpy.context.window_manager.windows[0]


def view3d():
    area = max((a for a in win().screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def area_of(kind):
    area = max((a for a in win().screen.areas if a.type == kind), key=lambda a: a.width * a.height)
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def event(type, value='NOTHING', **mods):
    x, y = state["mouse"]
    win().event_simulate(type=type, value=value, x=int(x), y=int(y), **{**state["mods"], **mods})


def caption(text):
    print("CAPTION %5.1fs  %s" % (time.time() - state["t0"], text))
    state["caption"] = text
    _redraw()


def wait(seconds):
    yield seconds


def move(xy, seconds=0.4):
    x0, y0 = state["mouse"]
    steps = max(1, int(seconds * FPS))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        state["mouse"] = (x0 + (xy[0] - x0) * t, y0 + (xy[1] - y0) * t)
        event('MOUSEMOVE')
        _redraw()
        yield 1 / FPS


def key(type, hold=0.12, **mods):
    event(type, 'PRESS', **mods)
    yield hold
    event(type, 'RELEASE', **mods)
    yield 0.25


def hold_modifier(type, flag):
    state["mods"] = {**state["mods"], flag: True}
    event(type, 'PRESS')


def release_modifier(type, flag):
    state["mods"] = {k: v for k, v in state["mods"].items() if k != flag}
    event(type, 'RELEASE')


def click(button='LEFTMOUSE'):
    state["pressed"] = True
    event(button, 'PRESS')
    yield 0.1
    event(button, 'RELEASE')
    state["pressed"] = False
    yield 0.2


def drag(to, seconds=0.8, button='LEFTMOUSE'):
    state["pressed"] = True
    event(button, 'PRESS')
    yield 0.1
    yield from move(to, seconds)
    yield 0.1
    event(button, 'RELEASE')
    state["pressed"] = False
    yield 0.4


def D(x, y):
    """Window point from a spot in a screenshot scaled to 2000 px wide (y from the top): how the UI positions
    below were measured. Scales with the window, so it only needs the same layout."""
    return (win().width * x / 2000, win().height * (1 - y / 1070))


def click_at(point, button='LEFTMOUSE', seconds=0.35, wait_after=0.15, pre=0.15):
    """Move to a window point and click it (pre: how long the pointer rests on the button first)."""
    yield from move(point, seconds)
    yield pre
    yield from click(button)
    yield wait_after


def stroke(points, seconds=1.0):
    """Press at the first point, glide through the others (a smooth curve), release: a brush stroke."""
    yield from move(points[0], 0.5)
    state["pressed"] = True
    event('LEFTMOUSE', 'PRESS')
    yield 0.1
    steps = max(2, int(seconds * FPS))
    n = len(points) - 1
    for i in range(1, steps + 1):
        t = i / steps * n
        k = min(int(t), n - 1)
        f = t - k
        x = points[k][0] + (points[k + 1][0] - points[k][0]) * f
        y = points[k][1] + (points[k + 1][1] - points[k][1]) * f
        state["mouse"] = (x, y)
        event('MOUSEMOVE')
        _redraw()
        yield 1 / FPS
    yield 0.1
    event('LEFTMOUSE', 'RELEASE')
    state["pressed"] = False
    yield 0.4


def type_into(point, text):
    """Double-click a number field, type a value, Enter."""
    yield from move(point, 0.4)
    yield 0.1
    yield from click()
    yield 0.4   # (a click without a drag starts typing in a number field)
    for ch in text:
        digit = {"0": 'ZERO', "1": 'ONE', "2": 'TWO', "3": 'THREE', "4": 'FOUR', "5": 'FIVE', "6": 'SIX', "7": 'SEVEN',
                 "8": 'EIGHT', "9": 'NINE'}[ch]
        win().event_simulate(type=digit, value='PRESS', x=int(state["mouse"][0]), y=int(state["mouse"][1]), unicode=ch)
        yield 0.05
        win().event_simulate(type=digit, value='RELEASE', x=int(state["mouse"][0]), y=int(state["mouse"][1]))
        yield 0.1
    yield 0.3
    yield from key('RET')
    yield 0.3


def run_op(op, area_kind='VIEW_3D', **props):
    area, region = area_of(area_kind)
    with bpy.context.temp_override(window=win(), area=area, region=region):
        op(**props)
    _redraw()


def to_window(region, co):
    return (region.x + co.x, region.y + co.y)


def viewport_point(fx, fy):
    _area, region = view3d()
    return (region.x + region.width * fx, region.y + region.height * fy)


def object_point(ob, offset=(0, 0, 0)):
    area, region = view3d()
    co = location_3d_to_region_2d(region, area.spaces.active.region_3d,
                                  ob.matrix_world.translation + Vector(offset))
    return to_window(region, co)


def frame_selected(margin=1.8):
    """Frame the selection (F), with some room around it."""
    run_op(bpy.ops.view3d.view_selected)
    area, _region = view3d()
    area.spaces.active.region_3d.view_distance *= margin
    _redraw()


def selection_center(ob):
    """World-space centre of the selected components (edit mode) or the object origin."""
    if ob.mode != 'EDIT':
        return ob.matrix_world.translation.copy()
    import bmesh
    bm = bmesh.from_edit_mesh(ob.data)
    verts = [v.co for v in bm.verts if v.select]
    return ob.matrix_world @ (sum(verts, Vector()) / len(verts))


def gizmo_arrow(ob, distance=45):
    """Point on the move manipulator's Z arrow, `distance` pixels from its centre."""
    area, region = view3d()
    rv3d = area.spaces.active.region_3d
    center = selection_center(ob)
    p0 = location_3d_to_region_2d(region, rv3d, center)
    p1 = location_3d_to_region_2d(region, rv3d, center + Vector((0, 0, 1)))
    d = (p1 - p0).normalized()
    return to_window(region, p0 + d * distance), d


def snap(name):
    """Development only: save a screenshot of the whole window to $M3D_SNAP_DIR (record.py --probe)."""
    folder = os.environ.get("M3D_SNAP_DIR")
    if folder:
        with bpy.context.temp_override(window=win(), screen=win().screen, area=win().screen.areas[0]):
            bpy.ops.screen.screenshot(filepath=os.path.join(folder, name + ".png"), check_existing=False)


def type_command(text, seconds_per_char=0.05):
    area, region = area_of('CONSOLE')
    line = area.spaces.active.history[-1]
    for i in range(1, len(text) + 1):
        line.body = text[:i]
        line.current_character = i
        area.tag_redraw()
        yield seconds_per_char
    yield 0.3
    with bpy.context.temp_override(window=win(), area=area, region=region):
        bpy.ops.console.execute(interactive=True)
    _redraw()
    yield 0.6


# -----------------------------------------------------------------------------
# Scenarios

TOUR = (('F1', "F1 Modeling: poly tools, Channel Box dock, shelves"),
        ('F2', "F2 Sculpt: brushes, masks, Multires, Voxel Remesh"),
        ('F3', "F3 UV: unwrap, layout, checker, texel density"),
        ('F4', "F4 Texture: paint channels and layers, bake, export"),
        ('F5', "F5 Rigging: joints, skin weights, IK, controls"),
        ('F6', "F6 Animation: keys, Graph Editor, tween, motion paths"),
        ('F7', "F7 Rendering: presets, lights, HDRI sky, Render View"))


def s_interface():
    caption("Maelstrom3D: a Blender 5.2 based 3D suite with a classic studio workflow")
    import shutil
    import tempfile
    import m3d_user
    config = tempfile.mkdtemp(prefix="m3d_demo_cfg_")   # Add to Shelf writes a file: not into the real config.
    m3d_user._path = lambda create=False: os.path.join(config, "m3d_user.json")
    m3d_user.reset_cache()
    run_op(bpy.ops.m3d.add_primitive, kind='SPHERE')
    bpy.ops.object.shade_smooth()
    yield from move(viewport_point(0.5, 0.55), 0.8)
    yield 1.2
    caption("Seven task workspaces on F1 - F7, each with its own menu set")
    yield 1.6
    for name, text in TOUR:
        caption(text)
        yield from key(name)
        yield 1.7
    caption("Back to Modeling: right-click a shelf button, Add to Shelf")
    yield from key('F1')
    yield from move(viewport_point(0.5, 0.5), 0.4)
    yield 1.2
    yield from click_at(D(27, 30), button='RIGHTMOUSE', wait_after=0.9, pre=0.4)
    snap("iface_menu")
    yield from click_at(D(51, 137), wait_after=0.8)
    caption("It appears on the Custom shelf tab")
    yield from click_at(D(492, 51), wait_after=1.8)
    yield from click_at(D(137, 51), wait_after=0.4)
    caption("Space: tap for four view, tap again for one")
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('SPACE')
    yield 0.6
    snap("iface_quad")
    yield 1.2
    yield from key('SPACE')
    yield 1.0

def s_modeling():
    caption("Shelf: the cube button adds a standard-size polygon cube at the origin")
    yield from move(viewport_point(0.5, 0.5), 0.6)
    yield from click_at(D(50, 80), wait_after=0.4)
    yield from move(viewport_point(0.5, 0.5), 0.5)
    frame_selected(1.5)
    yield 1.0
    caption("F11 face mode, W move tool, click the top face")
    yield from key('F11')
    yield from key('W')
    ob = bpy.context.active_object
    area, region = view3d()
    top = location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector((0.15, -0.15, 0.5)))
    yield from move(to_window(region, top), 0.6)
    yield from click()
    yield 0.6
    caption("Shift+drag the manipulator to extrude")
    for _ in range(2):
        start, d = gizmo_arrow(ob)
        yield from move(start, 0.6)
        yield 0.3
        hold_modifier('LEFT_SHIFT', 'shift')
        yield 0.1
        yield from drag((start[0] + d.x * 100, start[1] + d.y * 100), 0.9)
        release_modifier('LEFT_SHIFT', 'shift')
        yield 0.6
        ob.update_from_editmode()
    caption("Right-click: every tool for the selected faces")
    yield from move(viewport_point(0.62, 0.45), 0.5)
    state["pressed"] = True
    event('RIGHTMOUSE', 'PRESS')
    yield 2.8
    event('RIGHTMOUSE', 'RELEASE')
    state["pressed"] = False
    yield from key('ESC')
    caption("Toolkit tools apply on the click and open their options box (Bevel)")
    yield from move(to_window(region, location_3d_to_region_2d(region, area.spaces.active.region_3d,
                                                               selection_center(ob))), 0.5)
    with bpy.context.temp_override(window=win(), area=area, region=region):
        bpy.ops.m3d.tool('INVOKE_DEFAULT', True, idname="mesh.bevel", props="{'offset_type': 'PERCENT'}",
                         label="Bevel")
    _redraw()
    yield 3.0
    caption("3 = smooth mesh preview, 1 = off")
    yield from key('THREE')
    yield 1.4
    yield from key('ONE')
    yield 0.8


def s_marking_menus():
    run_op(bpy.ops.m3d.add_primitive, kind='TORUS')
    frame_selected()
    yield from move(viewport_point(0.5, 0.5), 0.6)
    caption("Hold W + left click: Move tool marking menu")
    yield 0.6
    event('W', 'PRESS')
    yield 0.3
    yield from click()
    yield 1.8
    event('W', 'RELEASE')
    yield from key('ESC')
    caption("Shift+right-click with an object selected: polygon tools")
    hold_modifier('LEFT_SHIFT', 'shift')
    event('RIGHTMOUSE', 'PRESS')
    yield 2.4
    event('RIGHTMOUSE', 'RELEASE')
    release_modifier('LEFT_SHIFT', 'shift')
    yield from key('ESC')
    caption("Ctrl+Shift+right-click: symmetry, soft select, preserve UVs")
    hold_modifier('LEFT_CTRL', 'ctrl')
    hold_modifier('LEFT_SHIFT', 'shift')
    event('RIGHTMOUSE', 'PRESS')
    yield 2.2
    event('RIGHTMOUSE', 'RELEASE')
    release_modifier('LEFT_SHIFT', 'shift')
    release_modifier('LEFT_CTRL', 'ctrl')
    yield from key('ESC')
    caption("Hold Space: the hotbox, every menu in one place")
    event('SPACE', 'PRESS')
    yield 2.6
    event('SPACE', 'RELEASE')
    yield from key('ESC')
    yield 0.6


def s_dock():
    run_op(bpy.ops.m3d.add_primitive, kind='CYLINDER')
    frame_selected(1.6)
    yield from move(viewport_point(0.5, 0.5), 0.5)
    caption("Right-hand dock: Channel Box shows the selected object's channels")
    yield 1.0
    yield from move(D(1810, 166), 0.5)
    yield 0.2
    yield from drag(D(1860, 166), seconds=0.7)
    yield 0.8
    caption("Layer Editor below it: collections with their V (view) and R (render) toggles")
    yield from move(D(1800, 410), 0.8)
    yield 1.8
    caption("Ctrl+A switches to the Attribute Editor and back")
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('A', ctrl=True)
    yield 1.8
    yield from key('A', ctrl=True)
    yield 0.6
    caption("Modeling Toolkit tab: tools for what is selected")
    yield from key('F11')
    ob = bpy.context.active_object
    yield from click_at(D(1846, 101), wait_after=0.8)
    yield from click_at(object_point(ob, (0, 0, ob.dimensions.z / 2)), wait_after=0.6)
    caption("A tool applies on the click, its options box opens beside it")
    yield from click_at(D(1740, 503), wait_after=2.6)
    caption("The tab menu hides tabs you do not use, or resets the workspace")
    yield from key('F2')
    yield from click_at(D(1988, 280), wait_after=0.8)
    yield 2.0
    yield from key('ESC')
    yield 0.3
    yield from key('F1')
    yield 0.8



def select_meridian(ob):
    """Edit Mode: select one pole-to-pole edge line of a UV sphere (the seam to cut)."""
    import bmesh
    bm = bmesh.from_edit_mesh(ob.data)
    for item in (*bm.verts, *bm.edges, *bm.faces):
        item.select = False
    for e in bm.edges:
        if all(abs(v.co.y) < 1e-4 and v.co.x > -1e-4 for v in e.verts):
            e.select = True
            for v in e.verts:
                v.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data)


def s_uv():
    caption("F3: the UV workspace, UV Editor on the left and the 3D view with the same mesh")
    run_op(bpy.ops.m3d.add_primitive, kind='SPHERE')
    ob = bpy.context.active_object
    ob.data.polygons.foreach_set("use_smooth", [True] * len(ob.data.polygons))
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F3')
    area, region = view3d()
    yield 0.5
    run_op(bpy.ops.view3d.view_selected)
    run_op(bpy.ops.image.view_all, area_kind='IMAGE_EDITOR', fit_view=True)
    yield 2.2
    caption("Create tab: Auto Unwrap")
    yield from click_at(D(1858, 280))
    yield from click_at(D(1817, 368))
    run_op(bpy.ops.image.view_all, area_kind='IMAGE_EDITOR', fit_view=True)
    yield 1.8
    caption("Unwrap tab: select an edge line, Cut, then Unfold")
    yield from click_at(D(1707, 280))
    select_meridian(ob)
    yield 0.5
    yield from click_at(D(1740, 326))
    yield 1.0
    run_op(bpy.ops.mesh.select_all, action='SELECT')
    yield from click_at(D(1817, 451))
    yield 1.5
    caption("Layout packs the shells into the 0-1 square")
    yield from click_at(D(1817, 634))
    yield 1.5
    caption("Check tab: checker map and distortion")
    yield from click_at(D(1810, 280))
    yield from click_at(D(1817, 326))
    run_op(bpy.ops.image.view_all, area_kind='IMAGE_EDITOR', fit_view=True)
    yield 0.8
    yield from click_at(D(1873, 375), wait_after=1.4)
    caption("Texel density: read it, set it to the target for the whole mesh")
    yield from click_at(D(1713, 522))
    yield from click_at(D(1815, 522), wait_after=1.8)

def screen_disc(ob, radius=1.0):
    """Window centre and pixel radius of a sphere-ish object, for planning strokes over it."""
    area, region = view3d()
    rv3d = area.spaces.active.region_3d
    c = location_3d_to_region_2d(region, rv3d, ob.matrix_world.translation)
    right = rv3d.view_rotation @ Vector((1, 0, 0))
    e = location_3d_to_region_2d(region, rv3d, ob.matrix_world.translation + right * radius)
    return to_window(region, c), (e - c).length


def over(disc, *fractions):
    """Window points at fractions (dx, dy) of the disc radius from its centre (y up)."""
    (cx, cy), r = disc
    return [(cx + dx * r, cy + dy * r) for dx, dy in fractions]


def s_sculpt():
    caption("F2: the Sculpt workspace, a brush tray on the left and task tabs on the right")
    run_op(bpy.ops.m3d.add_primitive, kind='SPHERE')
    ob = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    ob.data.remesh_voxel_size = 0.05
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F2')
    paint = bpy.context.scene.tool_settings.sculpt.unified_paint_settings
    paint.use_unified_size, paint.size = True, 170
    frame_selected(0.5)
    yield 1.4
    caption("Geometry tab: Voxel Remesh gives the sphere an even surface")
    yield from click_at(D(1750, 476), wait_after=1.0)
    caption("Brush tray: Clay Strips with Mirror X")
    yield from click_at(D(173, 290))
    yield from click_at(D(123, 513), wait_after=0.2)
    disc = screen_disc(ob)
    yield from stroke(over(disc, (-0.75, 0.45), (-0.25, 0.15), (0.0, 0.3), (0.35, 0.0), (0.7, 0.4)), 1.3)
    yield 0.5
    caption("Smooth brush softens it")
    yield from click_at(D(173, 307))
    yield from stroke(over(disc, (-0.7, 0.3), (-0.2, 0.25), (0.4, 0.2), (0.75, 0.3)), 1.1)
    yield 0.4
    caption("Shift+4 picks Grab: pull the surface")
    yield from key('FOUR', shift=True)
    yield from stroke(over(disc, (0.55, 0.55), (0.9, 1.0)), 1.0)
    yield 0.4
    caption("Mask tab: paint a mask, then Invert it")
    yield from click_at(D(1631, 280))
    yield from click_at(D(173, 393))
    yield from stroke(over(disc, (-0.8, -0.1), (-0.3, -0.05), (0.2, -0.1), (0.8, -0.05)), 1.2)
    yield from click_at(D(1897, 326), wait_after=0.9)
    caption("Only the unmasked part moves")
    yield from click_at(D(173, 290))
    yield from stroke(over(disc, (-0.7, -0.55), (0.0, -0.6), (0.7, -0.5)), 1.0)
    yield from click_at(D(1750, 326))
    caption("Geometry tab: Subdivide adds a Multires level")
    yield from click_at(D(1578, 280))
    yield from click_at(D(1597, 326), wait_after=1.4)
    caption("Face Sets tab: paint colored groups")
    yield from click_at(D(1683, 280))
    yield from click_at(D(67, 409))
    yield from stroke(over(disc, (-0.7, 0.5), (-0.1, 0.4), (0.5, 0.5)), 1.0)
    yield from stroke(over(disc, (-0.6, -0.4), (0.0, -0.3), (0.6, -0.4)), 1.0)
    yield 1.2


def tilt_view(yaw=0.7, pitch=1.15, margin=0.55, kind='VIEW_3D'):
    """Turn the largest 3D view to a three-quarter angle and frame the selection."""
    area, _region = view3d()
    rv3d = area.spaces.active.region_3d
    rv3d.view_perspective = 'PERSP'
    rv3d.view_rotation = Euler((pitch, 0, yaw)).to_quaternion()
    frame_selected(margin)


def set_brush_color(color):
    ts = bpy.context.scene.tool_settings
    ups = ts.image_paint.unified_paint_settings
    ups.use_unified_color = True
    ups.color = color[:3]
    _redraw()


def s_texture():
    caption("F4: the Texture workspace, 3D view and paint view side by side")
    run_op(bpy.ops.m3d.add_primitive, kind='SPHERE')
    ob = bpy.context.active_object
    ob.data.polygons.foreach_set("use_smooth", [True] * len(ob.data.polygons))
    bpy.context.scene.m3d_tex.resolution = '1024'
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F4')
    tilt_view()
    yield 1.5
    caption("Layers tab: Add Material")
    yield from click_at(D(1750, 320), wait_after=1.0)
    caption("Status Line: add channels, Base Color and Roughness")
    yield from click_at(D(121, 30), wait_after=1.0)
    yield from click_at(D(184, 30), wait_after=0.8)
    yield from click_at(D(121, 30), wait_after=0.5)
    run_op(bpy.ops.image.view_all, area_kind='IMAGE_EDITOR', fit_view=True)
    caption("Paint strokes with the brush tray's brushes")
    yield from click_at(D(63, 290))
    disc = screen_disc(ob)
    set_brush_color((0.9, 0.3, 0.1))
    yield from stroke(over(disc, (-0.8, 0.5), (-0.2, 0.3), (0.3, 0.55), (0.8, 0.3)), 1.1)
    set_brush_color((0.1, 0.4, 0.9))
    yield from stroke(over(disc, (-0.8, -0.3), (-0.2, -0.55), (0.4, -0.2), (0.8, -0.5)), 1.1)
    caption("Layers: add a Paint Layer, paint on it")
    yield from click_at(D(1640, 326), wait_after=0.8)
    set_brush_color((0.2, 0.8, 0.3))
    yield from stroke(over(disc, (-0.6, 0.0), (0.0, 0.1), (0.6, 0.0)), 1.0)
    caption("A Fill Layer with a mask: paint white to reveal it")
    yield from click_at(D(1860, 326), wait_after=0.8)
    mat = ob.active_material
    mat.m3d_layers[2].name = "Tint"
    mat.m3d_layers[2].channels[0].color = (0.9, 0.75, 0.1, 1.0)
    yield from click_at(D(1840, 762), wait_after=0.8)
    set_brush_color((1.0, 1.0, 1.0))
    yield from stroke(over(disc, (-0.5, 0.75), (0.0, 0.85), (0.5, 0.7)), 1.0)
    caption("Blend mode of the layer: Multiply")
    yield from click_at(D(1833, 551), wait_after=0.4)
    yield from click_at(D(1775, 587), wait_after=1.4)
    caption("Bake tab: Normal and Ambient Occlusion maps at a small size")
    ob.m3d_bake.resolution, ob.m3d_bake.samples = '128', 8
    yield from click_at(D(1702, 280), wait_after=0.8)
    yield from click_at(D(1750, 563), wait_after=1.5)
    caption("Export tab: glTF, Unreal and Unity presets")
    yield from click_at(D(1747, 280), wait_after=2.0)

def make_body():
    """A standing capsule-ish body mesh (z 0..2, radius .32) with enough rings to bend."""
    import bmesh
    bpy.ops.m3d.add_primitive(kind='CYLINDER')
    body = bpy.context.active_object
    body.name = "Body"
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24, radius1=0.32, radius2=0.32, depth=2.0,
                          matrix=Matrix.Translation((0, 0, 1.0)))
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.5],
                              cuts=8, use_grid_fill=True)
    bm.to_mesh(body.data)
    bm.free()
    body.data.shade_smooth()
    return body


def world_point(co):
    """Window point of a world position in the largest 3D view."""
    area, region = view3d()
    return to_window(region, location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector(co)))


def front_view(margin=1.0):
    """Orthographic front view of the largest 3D view, framed on everything."""
    run_op(bpy.ops.view3d.view_axis, type='FRONT')
    run_op(bpy.ops.view3d.view_all, center=True)
    area, _region = view3d()
    area.spaces.active.region_3d.view_distance *= margin
    _redraw()


def s_rigging():
    caption("F5: the Rigging workspace, bone hierarchy on the left, Skeleton tab on the right")
    body = make_body()
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F5')
    front_view(1.15)
    yield 1.5
    caption("Joint tool: click to place joints, Enter finishes the chain")
    scene = bpy.context.scene
    scene.m3d_rig.joint_name = "Spine"
    yield from click_at(D(1750, 141), wait_after=0.5)
    for z in (0.9, 1.2, 1.55, 1.9):
        yield from click_at(world_point((0, 0, z)), seconds=0.4, wait_after=0.15)
    yield from key('RET')
    yield 0.6
    caption("X-Mirror on: a chain on one side gets a mirrored copy")
    yield from click_at(D(1530, 418), wait_after=0.4)
    scene.m3d_rig.joint_name = "Leg"
    yield from click_at(D(1750, 141), wait_after=0.4)
    for z, x in ((0.9, 0.17), (0.5, 0.17), (0.08, 0.17)):
        yield from click_at(world_point((x, 0, z)), seconds=0.4, wait_after=0.15)
    yield from key('RET')
    yield 1.2
    caption("Orient Joint rolls the bones to a chosen axis")
    yield from click_at(D(1750, 565), wait_after=1.2)
    caption("Object mode, pick the mesh then the skeleton, Skin tab: Bind")
    yield from click_at(D(79, 30), wait_after=0.4)
    yield from click_at(D(62, 136), wait_after=0.4)
    hold_modifier('LEFT_CTRL', 'ctrl')
    yield from click_at(D(70, 121), wait_after=0.3)
    release_modifier('LEFT_CTRL', 'ctrl')
    yield from click_at(D(1733, 101), wait_after=0.6)
    yield from click_at(D(1640, 208), wait_after=1.0)
    caption("Paint Weights shows and edits the bone influence")
    yield from click_at(D(1750, 281), wait_after=1.5)
    yield from click_at(D(1570, 521), wait_after=1.0)
    rig = bpy.data.objects["Armature"]
    caption("Pose mode: IK with Pole on the end of a leg")
    yield from click_at(D(170, 30), wait_after=0.4)
    for pb in rig.pose.bones:
        pb.select = pb.name == "Leg.001.L"
    rig.data.bones.active = rig.data.bones["Leg.001.L"]
    yield from click_at(D(1658, 101), wait_after=0.5)
    yield from click_at(D(1750, 378), wait_after=1.0)
    target = next(pb for pb in rig.pose.bones if pb.name.startswith("IK_"))
    caption("Control shapes: a circle on the IK target, then pose the leg")
    for pb in rig.pose.bones:
        pb.select = pb == target
    rig.data.bones.active = target.bone
    yield from click_at(D(1604, 557), wait_after=0.3)
    yield from click_at(D(1655, 632), wait_after=0.6)
    base = target.matrix.copy()
    for i in range(1, 25):
        m = base.copy()
        m.translation.z += 0.45 * math.sin(i / 24 * math.pi)
        m.translation.x -= 0.25 * math.sin(i / 24 * math.pi)
        target.matrix = m
        bpy.context.view_layer.update()
        _redraw()
        yield 1 / FPS * 1.5
    caption("Drive tab: Driven Key links one channel to another")
    yield from click_at(D(1775, 101), wait_after=1.8)

def s_animation():
    caption("F6: the Animation workspace, a camera view, the viewport, Graph / Dope Sheet and a Timeline")
    scene = bpy.context.scene
    bpy.ops.m3d.add_primitive(kind='SPHERE')
    ball = bpy.context.active_object
    ball.name = "Ball"
    ball.location = (-3.0, 0, 1.0)
    ball.data.polygons.foreach_set("use_smooth", [True] * len(ball.data.polygons))
    bpy.ops.object.camera_add(location=(0, -11, 3.2), rotation=(math.radians(82), 0, 0))
    scene.camera = bpy.context.active_object
    scene.frame_start, scene.frame_end = 1, 24
    bpy.ops.object.select_all(action='DESELECT')
    ball.select_set(True)
    bpy.context.view_layer.objects.active = ball
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F6')
    front_view(0.5)
    area3d, _r = view3d()
    area3d.spaces.active.region_3d.view_location = (0.0, 0.0, 2.0)
    yield 1.2
    caption("S sets a key; click the Time Slider, move the ball, S again")
    yield from move(viewport_point(0.5, 0.35), 0.4)
    yield from key('S')
    for frame, pos in ((12, (0.0, 0, 3.2)), (24, (3.0, 0, 1.0))):
        yield from click_at(D(57 + (frame - 1) * 5.6, 960), wait_after=0.2)
        start = ball.location.copy()
        for i in range(1, 13):
            t = i / 12
            ball.location = start.lerp(Vector(pos), t)
            _redraw()
            yield 1 / FPS
        yield from move(viewport_point(0.5, 0.35), 0.3)
        yield from key('S')
    yield from click_at(D(57, 960), wait_after=0.3)
    caption("Graph Editor and Dope Sheet switch in the same area")
    yield from click_at(D(1080, 30), wait_after=1.4)
    yield from click_at(D(1140, 30), wait_after=0.6)
    caption("Alt+Q tween: drag between two keys, click to key it")
    yield from click_at(D(57 + 5 * 5.6, 960), wait_after=0.3)
    yield from click_at(D(1697, 101), wait_after=0.3)
    yield from move(viewport_point(0.45, 0.3), 0.4)
    event('Q', 'PRESS', alt=True)
    yield 0.15
    event('Q', 'RELEASE', alt=True)
    yield 0.2
    yield from move(viewport_point(0.62, 0.3), 0.9)
    yield 0.3
    yield from click()
    yield 0.8
    caption("Motion tab: Calculate shows the motion path in the viewport")
    yield from click_at(D(1763, 101), wait_after=0.3)
    yield from click_at(D(1604, 207), wait_after=1.8)
    caption("Blocking makes stepped keys, Polish makes clamped splines")
    yield from click_at(D(585, 30), wait_after=1.4)
    yield from click_at(D(634, 30), wait_after=1.4)
    caption("Playback tab: range, key defaults and Playblast")
    yield from click_at(D(1865, 101), wait_after=2.0)

def render_scene():
    """Floor and three shaded objects, no camera or lights (those are added in the video)."""
    scene = bpy.context.scene

    def material(name, color, metallic, roughness):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        return mat

    bpy.ops.mesh.primitive_plane_add(size=12)
    bpy.context.active_object.name = "Floor"
    bpy.context.active_object.data.materials.append(material("Floor", (0.55, 0.55, 0.6, 1), 0.0, 0.5))
    for name, make, mat in (
            ("Ball", lambda: bpy.ops.mesh.primitive_uv_sphere_add(radius=0.9, location=(-1.8, 0, 0.9)),
             material("Ball", (0.9, 0.2, 0.15, 1), 1.0, 0.25)),
            ("Head", lambda: bpy.ops.mesh.primitive_monkey_add(size=1.6, location=(0, 0, 0.8)),
             material("Head", (0.85, 0.7, 0.4, 1), 0.0, 0.4)),
            ("Block", lambda: bpy.ops.mesh.primitive_cube_add(size=1.4, location=(1.9, 0.2, 0.7)),
             material("Block", (0.2, 0.55, 0.3, 1), 0.0, 0.7))):
        make()
        ob = bpy.context.active_object
        ob.name = name
        bpy.ops.object.shade_smooth()
        ob.data.materials.append(mat)
    scene.eevee.taa_render_samples = 16
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = bpy.data.objects["Head"]
    bpy.data.objects["Head"].select_set(True)


def s_rendering():
    caption("F7: the Rendering workspace, 3D view, Render View and task tabs")
    render_scene()
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F7')
    tilt_view(yaw=0.75, pitch=1.2, margin=1.1)
    run_op(bpy.ops.view3d.view_all, center=True)
    area3d, _r = view3d()
    area3d.spaces.active.region_3d.view_distance *= 0.85
    yield 1.5
    caption("Quality presets: Draft / Medium / Final")
    yield from click_at(D(313, 30), wait_after=1.0)
    caption("Camera tab: New Camera from View")
    yield from click_at(D(1700, 166), wait_after=1.0)
    area3d.spaces.active.region_3d.view_distance *= 1.25
    _redraw()
    yield 0.8
    caption("Lighting tab: add lights, then edit them in the light table")
    yield from click_at(D(1525, 101), wait_after=0.4)
    yield from click_at(D(1880, 147), wait_after=0.5)
    yield from click_at(D(1519, 147), wait_after=0.5)
    area_light, point_light = bpy.data.objects["Area"], bpy.data.objects["Point"]
    area_light.location, point_light.location = (3.0, -3.0, 4.5), (-4.0, -3.0, 2.0)
    area_light.data.size = 3.0
    _redraw()
    yield 0.3
    yield from type_into(D(1815, 232), "900")
    yield from type_into(D(1815, 264), "400")
    caption("HDRI Sky: pick one of the bundled studio skies")
    yield from click_at(D(1872, 350), wait_after=1.2)
    caption("IPR: the viewport renders as you work")
    yield from click_at(D(612, 30), wait_after=2.2)
    yield from click_at(D(612, 30), wait_after=0.5)
    caption("Shift+F12 renders into the Render View")
    yield from move(viewport_point(0.5, 0.5), 0.5)
    yield from key('F12', shift=True)
    yield 4.0
    snap("render_done")

def grow_console(pixels):
    """Drag the area edges above the Command Line up, like a user would (the viewport gets smaller)."""
    for kind in ('DOPESHEET_EDITOR', 'CONSOLE'):
        area, _region = area_of(kind)
        edge = (area.x + area.width * 0.5, area.y + area.height)
        yield from move(edge, 0.4)
        yield 0.2
        yield from drag((edge[0], edge[1] + pixels), 0.6)


def s_mel():
    yield from grow_console(230)
    yield 0.5
    caption("The command line speaks MEL")
    area, region = area_of('CONSOLE')
    yield from move((region.x + region.width * 0.3, region.y + region.height * 0.5), 0.8)
    yield 0.5
    yield from type_command("polyCube -w 3 -h 0.3 -d 3 -n floor;")
    yield from type_command("polySphere -r 0.7 -n ball; move -r 0 0 1;")
    yield from type_command("polyTorus -r 1 -sr 0.15 -n ring; rotate 90 0 0 ring; move 0 0 1 ring;")
    caption("Python mode has cmds: cmds.polyCube(), cmds.move(), cmds.setAttr() ...")
    run_op(bpy.ops.view3d.view_all, center=True)
    yield 2.4


SCENARIOS = {"interface": s_interface, "modeling": s_modeling, "marking_menus": s_marking_menus,
             "dock": s_dock, "uv": s_uv, "mel": s_mel, "sculpt": s_sculpt, "texture": s_texture, "rigging": s_rigging, "animation": s_animation, "rendering": s_rendering}


def main():
    def intro():
        bpy.context.preferences.view.smooth_view = 0  # Demo only: instant view changes.
        bpy.context.preferences.view.ui_scale = SCENARIO_UI_SCALE.get(NAME, UI_SCALE)  # Bigger UI: the video is scaled down to 1600 / 960 px.
        # Close the splash by clicking empty viewport space, then signal the recorder.
        yield 1.5
        yield from move(viewport_point(0.2, 0.3), 0.2)
        yield from click()
        state["pressed"] = False
        yield 1.0
        open(os.path.join(STATUS, "ready"), "w").close()
        yield 1.0
        state["t0"] = time.time()
        yield from SCENARIOS[NAME]()
        caption("")
        yield 0.8
        open(os.path.join(STATUS, "done"), "w").close()
        yield 1.5
        bpy.ops.wm.quit_blender()

    steps = intro()

    def tick():
        try:
            return next(steps)
        except StopIteration:
            return None
        except Exception:   # Tell the recorder instead of leaving it waiting.
            traceback.print_exc()
            with open(os.path.join(STATUS, "error"), "w") as f:
                f.write(traceback.format_exc())
            open(os.path.join(STATUS, "done"), "w").close()
            bpy.ops.wm.quit_blender()
            return None
    bpy.app.timers.register(tick, first_interval=1.0)


if __name__ == "__main__":
    main()
