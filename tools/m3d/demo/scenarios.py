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

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

NAME, STATUS = sys.argv[sys.argv.index("--") + 1:][:2]
FPS = 30
state = {"mouse": (0, 0), "pressed": False, "caption": "", "mods": {}}


# -----------------------------------------------------------------------------
# Overlay: cursor + caption

def _draw_overlay():
    region = bpy.context.region
    x, y = state["mouse"][0] - region.x, state["mouse"][1] - region.y
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    if 0 <= x <= region.width and 0 <= y <= region.height:
        s = 1.6 * bpy.context.preferences.system.ui_scale
        arrow = [(x, y), (x, y - 22 * s), (x + 6 * s, y - 16 * s), (x + 11 * s, y - 26 * s), (x + 15 * s, y - 24 * s),
                 (x + 10 * s, y - 14 * s), (x + 17 * s, y - 14 * s)]
        fill = [arrow[0], arrow[1], arrow[2], arrow[0], arrow[2], arrow[6], arrow[2], arrow[3], arrow[5],
                arrow[3], arrow[4], arrow[5]]
        if state["pressed"]:
            ring = [(x + 14 * s * math.cos(a / 16 * math.tau), y + 14 * s * math.sin(a / 16 * math.tau))
                    for a in range(16)]
            shader.uniform_float("color", (1.0, 0.85, 0.1, 0.9))
            batch_for_shader(shader, 'LINE_LOOP', {"pos": ring}).draw(shader)
        shader.uniform_float("color", (1, 1, 1, 1))
        batch_for_shader(shader, 'TRIS', {"pos": fill}).draw(shader)
        shader.uniform_float("color", (0, 0, 0, 1))
        batch_for_shader(shader, 'LINE_LOOP', {"pos": arrow}).draw(shader)
    if state["caption"] and bpy.context.area.type == 'VIEW_3D' and region.width > 600:
        size = int(22 * bpy.context.preferences.system.ui_scale)
        blf.size(0, size)
        w, h = blf.dimensions(0, state["caption"])
        cx, cy = (region.width - w) / 2, 40
        pad = size * 0.6
        box = [(cx - pad, cy - pad), (cx + w + pad, cy - pad), (cx + w + pad, cy + h + pad), (cx - pad, cy + h + pad)]
        shader.uniform_float("color", (0.1, 0.1, 0.1, 0.8))
        batch_for_shader(shader, 'TRI_FAN', {"pos": box}).draw(shader)
        blf.color(0, 1, 1, 1, 1)
        blf.position(0, cx, cy, 0)
        blf.draw(0, state["caption"])
    gpu.state.blend_set('NONE')


HANDLES = [(space, space.draw_handler_add(_draw_overlay, (), 'WINDOW', 'POST_PIXEL'))
           for space in (bpy.types.SpaceView3D, bpy.types.SpaceProperties, bpy.types.SpaceImageEditor,
                         bpy.types.SpaceConsole, bpy.types.SpaceOutliner)]


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
    yield 0.12
    event(button, 'RELEASE')
    state["pressed"] = False
    yield 0.3


def drag(to, seconds=0.8, button='LEFTMOUSE'):
    state["pressed"] = True
    event(button, 'PRESS')
    yield 0.1
    yield from move(to, seconds)
    yield 0.1
    event(button, 'RELEASE')
    state["pressed"] = False
    yield 0.4


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

def s_interface():
    caption("Maelstrom3D: a Blender 5.2 based 3D suite with a classic studio workflow")
    yield from move(viewport_point(0.5, 0.55), 1.0)
    yield 1.5
    caption("Classic layout: Outliner, viewport, Channel Box dock, Time Slider, Command Line")
    for p in ((0.05, 0.9), (0.95, 0.9), (0.5, 0.08), (0.5, 0.55)):
        yield from move(viewport_point(*p), 0.7)
        yield 0.3
    caption("Menu sets: F2 Modeling  F3 Rigging  F4 Animation  F6 Rendering")
    for k in ('F3', 'F4', 'F6', 'F2'):
        yield from key(k)
        yield 0.9
    caption("Shelf tabs: Poly Modeling, Rigging, Animation, Rendering ...")
    for shelf in ('RIGGING', 'ANIMATION', 'RENDERING', 'POLY'):
        bpy.context.window_manager.m3d_shelf = shelf
        _redraw()
        yield 0.9
    caption("Space: tap for four view, tap again for one")
    yield from key('SPACE')
    yield 1.6
    yield from key('SPACE')
    yield 1.0


def s_modeling():
    caption("Shelf: standard-size polygon cube at the origin")
    yield from move(viewport_point(0.5, 0.5), 0.6)
    run_op(bpy.ops.m3d.add_primitive, kind='CUBE')
    frame_selected(2.4)
    yield 1.2
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
        yield from drag((start[0] + d.x * 70, start[1] + d.y * 70), 0.9)
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
    frame_selected()
    props_area, props_region = area_of('PROPERTIES')
    caption("Right-hand dock: Channel Box / Layer Editor")
    yield from move((props_region.x + props_region.width * 0.5, props_region.y + props_region.height * 0.8), 0.8)
    yield 1.6
    caption("Ctrl+A: switch to the Attribute Editor")
    yield from move(viewport_point(0.5, 0.5), 0.6)
    yield from key('A', ctrl=True)
    yield 1.6
    yield from key('A', ctrl=True)
    yield 0.8
    caption("Modeling Toolkit tab")
    yield from key('F11')
    props_area.spaces.active.context = 'MODELING_TOOLKIT'
    _redraw()
    yield from move((props_region.x + props_region.width * 0.5, props_region.y + props_region.height * 0.7), 0.8)
    yield 2.2
    caption("Back to the Channel Box")
    props_area.spaces.active.context = 'CHANNEL_BOX'
    _redraw()
    yield 1.2


def s_uv():
    run_op(bpy.ops.m3d.add_primitive, kind='CUBE')
    yield from move(viewport_point(0.5, 0.5), 0.6)
    caption("F12 (component mode): UV Editing workspace with the UV Toolkit")
    yield from key('F11')
    yield from key('F12')
    yield 1.5
    area, region = view3d()
    caption("Select all, Automatic UVs")
    yield from move((region.x + region.width * 0.5, region.y + region.height * 0.5), 0.6)
    run_op(bpy.ops.mesh.select_all, action='SELECT')
    run_op(bpy.ops.uv.smart_project)
    yield 1.6
    caption("Layout (Cut / Unfold / Layout workflow)")
    run_op(bpy.ops.uv.pack_islands, area_kind='IMAGE_EDITOR', margin=0.02)
    yield 1.6
    caption("Checker map")
    run_op(bpy.ops.m3d.uv_checker)
    yield 2.2


def s_mel():
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
             "dock": s_dock, "uv": s_uv, "mel": s_mel}


def main():
    def intro():
        bpy.context.preferences.view.smooth_view = 0  # Demo only: instant view changes.
        # Close the splash by clicking empty viewport space, then signal the recorder.
        yield 1.5
        yield from move(viewport_point(0.2, 0.3), 0.2)
        yield from click()
        state["pressed"] = False
        yield 1.0
        open(os.path.join(STATUS, "ready"), "w").close()
        yield 2.0
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
    bpy.app.timers.register(tick, first_interval=1.0)


main()
