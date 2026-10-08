# SPDX-License-Identifier: GPL-2.0-or-later
"""
Build Maelstrom3D's factory startup file (workspaces and their layouts).

Runs on Maelstrom3D's own build: it loads the current factory startup file and applies only the edits of each
phase, so running it again changes nothing (it does not re-split areas). One function per phase, listed in
PHASES; a function is a generator, `yield seconds` waits for the window to catch up (workspace switches
happen on the next event). Later phases add their own layout steps (new workspaces, areas, tabs) the same way.

Run in the GUI (screen operators need a window), it saves and quits by itself:

    set BLENDER_USER_RESOURCES=<empty temp dir>
    blender --factory-startup --enable-event-simulate --python tools/m3d/build_startup.py -- release/datafiles/startup.blend

The build also installs startup.blend as datafiles/m3d_factory_layout.blend (read by Reset Workspace).
"""

import os
import shutil
import sys
import traceback

import bpy

import m3d_workspace as mw

OUT = os.path.abspath(sys.argv[sys.argv.index("--") + 1])


def window():
    return bpy.context.window_manager.windows[0]


def areas(screen, type):
    return sorted((a for a in screen.areas if a.type == type), key=lambda a: (a.x, a.y))


def run(op, area, **props):
    """Run a screen operator in an area's main region (for later phases that split or close areas)."""
    region = next(r for r in area.regions if r.type == 'WINDOW')
    print("M3D STEP", op.idname(), area.type, flush=True)
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
        op(**props)


def show(ws):
    """Make `ws` the window's workspace (takes effect on the next event: `yield` after this)."""
    window().workspace = ws


def phase0_workspaces():
    """Names, kinds, entry modes, order; drops Blender's spare Modeling workspace."""
    data = bpy.data
    for old, new in mw.WORKSPACE_NAMES.items():
        for collection in (data.workspaces, data.screens):
            if old in collection and new not in collection:
                collection[old].name = new

    spare = data.workspaces.get("Modeling - Standard")
    if spare is not None:
        show(data.workspaces["Modeling"])
        yield 0.6
        screens = list(spare.screens)
        data.batch_remove({spare})
        data.batch_remove({s for s in screens if s.users == 0})

    for kind, (name, _key, mode, _menu_set) in mw.KINDS.items():
        ws = data.workspaces[name]
        ws.m3d_kind = kind
        ws.object_mode = mode

    # The tab order is a number on each workspace. "Reorder to Back" gives the moved one the same number as the
    # last one moved, so it lands in front of those: move them in reverse.
    for name in reversed(mw.WORKSPACE_ORDER):
        show(data.workspaces[name])
        yield 0.5
        with bpy.context.temp_override(window=window()):
            bpy.ops.workspace.reorder_to_back()
        yield 0.2
    # The order is a hidden number on each workspace (not in Python's collection order): check by cycling.
    show(data.workspaces["Modeling"])
    yield 0.5
    seen = ["Modeling"]
    for _ in mw.WORKSPACE_ORDER[1:]:
        with bpy.context.temp_override(window=window()):
            bpy.ops.screen.workspace_cycle('INVOKE_DEFAULT', direction='NEXT')
        yield 0.4
        seen.append(window().workspace.name)
    assert seen == mw.WORKSPACE_ORDER, seen


def phase1_sculpt():
    """Sculpt: the brush tray (a Properties editor left of the viewport), wider dock with the Sculpt tabs. The
    Outliner stays under the dock: the Objects tab lists the meshes to sculpt, the Outliner keeps the hierarchy."""
    ws = bpy.data.workspaces["Sculpt"]
    show(ws)
    yield 0.6
    screen = window().screen
    if len(areas(screen, 'PROPERTIES')) < 2:
        view = areas(screen, 'VIEW_3D')[0]
        run(bpy.ops.screen.area_split, view, direction='VERTICAL', factor=0.16)
        yield 0.3
        left = areas(screen, 'VIEW_3D')[0]  # The new area is a copy of the viewport; the leftmost one is the tray.
        left.ui_type = 'PROPERTIES'
        yield 0.3
        dock = areas(screen, 'PROPERTIES')[-1]
        # Moving an edge needs the mouse on it (no active region): put it there with a simulated event.
        edge = (dock.x - 1, dock.y + dock.height // 2)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=-DOCK_WIDER)
        yield 0.3
    view = areas(screen, 'VIEW_3D')[0]
    if view.spaces.active.show_region_asset_shelf:  # The brush tray replaces it (B still opens the brush popover).
        run(bpy.ops.screen.region_toggle, view, region_type='ASSET_SHELF')
        yield 0.3
    tray, dock = areas(screen, 'PROPERTIES')
    tray.spaces.active.context = dock.spaces.active.context = 'MODELING_TOOLKIT'
    ws.m3d_page_left, ws.m3d_page_right = "sculpt_brushes", "sculpt_geometry"


DOCK_WIDER = 170  # pixels of the 2560 px build window: seven tabs, All Settings and the tab menu fit

PHASES = [phase0_workspaces, phase1_sculpt]


def save():
    """Hide the command line's header now that it has been drawn (doing it right after the split crashes),
    save, copy to the output paths and quit."""
    wm = bpy.context.window_manager
    wm.m3d_menu_set, wm.m3d_shelf = 'MODELING', 'POLY'
    for screen in bpy.data.workspaces["Modeling"].screens:
        for area in areas(screen, 'CONSOLE'):
            area.spaces.active.show_region_header = False
    bpy.context.preferences.filepaths.use_file_compression = True
    bpy.ops.wm.save_homefile()
    saved = os.path.join(bpy.utils.resource_path('USER'), "config", "startup.blend")
    shutil.copyfile(saved, OUT)
    print("M3D STARTUP SAVED", OUT, [w.name for w in bpy.data.workspaces], flush=True)
    bpy.ops.wm.quit_blender()


def driver():
    """Timer: run the phases one after the other, then save."""
    global steps
    if steps is None:
        def all_phases():
            for phase in PHASES:
                yield from phase()
            show(bpy.data.workspaces["Modeling"])
            yield 0.6
            save()
        steps = all_phases()
    try:
        return next(steps)
    except StopIteration:
        return None
    except Exception:  # Report and quit rather than leave a window hanging.
        traceback.print_exc()
        bpy.ops.wm.quit_blender()


steps = None
bpy.app.timers.register(driver, first_interval=1.5)
