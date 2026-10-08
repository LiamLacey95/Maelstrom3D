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
        left = areas(screen, 'OUTLINER')[0]
        run(bpy.ops.screen.area_split, left, direction='HORIZONTAL', factor=RIG_LEFT_SPLIT)
        yield 0.3
        lower = min(areas(screen, 'OUTLINER'), key=lambda a: a.y)
        lower.ui_type = 'PROPERTIES'
        yield 0.3
    view = areas(screen, 'VIEW_3D')[0]
    if view.spaces.active.show_region_asset_shelf:  # The brush tray replaces it (B still opens the brush popover).
        run(bpy.ops.screen.region_toggle, view, region_type='ASSET_SHELF')
        yield 0.3
    tray, dock = areas(screen, 'PROPERTIES')
    tray.spaces.active.context = dock.spaces.active.context = 'MODELING_TOOLKIT'
    ws.m3d_page_left, ws.m3d_page_right = "sculpt_brushes", "sculpt_geometry"


def phase2_uv():
    """UV: the UV editor wider than the 3D view (its sidebar closed: the UV tools are the dock's pages), the 3D view
    in Solid shading with seams shown, the dock on the Unwrap page."""
    ws = bpy.data.workspaces["UV"]
    show(ws)
    yield 0.6
    screen = window().screen
    image, view = areas(screen, 'IMAGE_EDITOR')[0], areas(screen, 'VIEW_3D')[0]
    if image.width < view.width * 1.15:
        edge = (view.x - 1, view.y + view.height // 2)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=UV_WIDER)
        yield 0.3
    image.spaces.active.show_region_ui = False
    view.spaces.active.shading.type = 'SOLID'
    view.spaces.active.overlay.show_edge_seams = True
    dock = areas(screen, 'PROPERTIES')[0]
    dock.spaces.active.context = 'MODELING_TOOLKIT'
    ws.m3d_page_right = "uv_unwrap"


def phase3_texture():
    """Texture: the brush tray (a Properties editor), the 3D view in Material Preview, the 2D paint view and the wider
    dock. The stock layout has the paint view left of the 3D view: the two swap places."""
    ws = bpy.data.workspaces["Texture"]
    # The workspace enters Texture Paint Mode on the active mesh: the brush asset shelf below is hidden in that mode.
    layer = bpy.context.view_layer
    active = layer.objects.active
    data = bpy.data.meshes.new("m3dTemp")   # The startup scene has no mesh: a temporary quad.
    data.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh = bpy.data.objects.new("m3dTemp", data)
    layer.active_layer_collection.collection.objects.link(mesh)
    layer.objects.active = mesh
    show(ws)
    yield 0.6
    screen = window().screen
    if len(areas(screen, 'PROPERTIES')) < 2:
        paint = areas(screen, 'IMAGE_EDITOR')[0]
        run(bpy.ops.screen.area_split, paint, direction='VERTICAL', factor=0.3)
        yield 0.3
        tray, left = areas(screen, 'IMAGE_EDITOR')[:2]   # The new area is a copy of the paint view, left of it.
        right = areas(screen, 'VIEW_3D')[0]
        tray.ui_type = 'PROPERTIES'
        left.ui_type = 'VIEW_3D'
        right.ui_type = 'IMAGE_EDITOR'
        yield 0.3
        dock = areas(screen, 'PROPERTIES')[-1]
        for edge, delta in (((dock.x - 1, dock.y + dock.height // 2), -DOCK_WIDER),
                            ((right.x - 1, right.y + right.height // 2), TEXTURE_VIEW_WIDER)):
            # Moving an edge needs the mouse on it (no active region): put it there with a simulated event.
            window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
            yield 0.3
            with bpy.context.temp_override(window=window(), screen=screen):
                bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=delta)
            yield 0.3
    view, image = areas(screen, 'VIEW_3D')[0], areas(screen, 'IMAGE_EDITOR')[0]
    yield 1.0   # The shelf region exists once the viewport has been drawn in Texture Paint Mode.
    assert bpy.context.mode == 'PAINT_TEXTURE', bpy.context.mode
    if view.spaces.active.show_region_asset_shelf:   # The brush tray replaces it.
        run(bpy.ops.screen.region_toggle, view, region_type='ASSET_SHELF')
        yield 0.3
    view.spaces.active.shading.type = 'MATERIAL'
    view.spaces.active.show_region_toolbar = image.spaces.active.show_region_toolbar = True   # The paint tools.
    image.spaces.active.ui_mode = 'PAINT'
    image.spaces.active.show_region_ui = False
    yield 0.3
    if image.spaces.active.show_region_asset_shelf:
        run(bpy.ops.screen.region_toggle, image, region_type='ASSET_SHELF')
        yield 0.3
    tray, dock = areas(screen, 'PROPERTIES')
    tray.spaces.active.context = dock.spaces.active.context = 'MODELING_TOOLKIT'
    ws.m3d_page_left, ws.m3d_page_right = "tex_brushes", "tex_layers"
    run(bpy.ops.object.mode_set, view, mode='OBJECT')
    layer.objects.active = active
    yield 0.3
    bpy.data.objects.remove(mesh)
    bpy.data.meshes.remove(data)


def phase4_rigging():
    """Rigging: the small left 3D view becomes the Outliner (the armature hierarchy: bones show under their armature) with
    a Properties editor under it (bone collections), the Outliner of the right column is closed so the dock gets its
    height, the bottom editor is a short Timeline (the Status Line and the Drive tab switch it to the Drivers editor)."""
    ws = bpy.data.workspaces["Rigging"]
    show(ws)
    yield 0.6
    screen = window().screen
    if len(areas(screen, 'PROPERTIES')) < 2:
        small = areas(screen, 'VIEW_3D')[0]   # Left of the large viewport.
        small.ui_type = 'OUTLINER'
        yield 0.3
        view = areas(screen, 'VIEW_3D')[0]
        edge = (view.x - 1, view.y + view.height // 2)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=-(small.width - RIG_LEFT_WIDTH))
        yield 0.3
        right_outliner = max(areas(screen, 'OUTLINER'), key=lambda a: a.x)
        run(bpy.ops.screen.area_close, right_outliner)
        yield 0.3
        bottom = areas(screen, 'DOPESHEET_EDITOR')[0]
        bottom.ui_type = 'TIMELINE'
        yield 0.3
        view = areas(screen, 'VIEW_3D')[0]
        edge = (view.x + view.width // 2, view.y - 1)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        bottom = areas(screen, 'DOPESHEET_EDITOR')[0]
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=-(bottom.height - RIG_TIMELINE_HEIGHT))
        yield 0.3
        dock = areas(screen, 'PROPERTIES')[-1]
        edge = (dock.x - 1, dock.y + dock.height // 2)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=-DOCK_WIDER)
        yield 0.3
        left = areas(screen, 'OUTLINER')[0]
        run(bpy.ops.screen.area_split, left, direction='HORIZONTAL', factor=RIG_LEFT_SPLIT)
        yield 0.3
        lower = min(areas(screen, 'OUTLINER'), key=lambda a: a.y)
        lower.ui_type = 'PROPERTIES'
        yield 0.3
    view = areas(screen, 'VIEW_3D')[0]
    view.spaces.active.shading.type = 'SOLID'
    view.spaces.active.overlay.show_xray_bone = True   # Bones show through the mesh in Pose Mode.
    props = sorted(areas(screen, 'PROPERTIES'), key=lambda a: a.x)
    for area in props:
        area.spaces.active.context = 'MODELING_TOOLKIT'
    ws.m3d_page_left, ws.m3d_page_right = "rig_bones", "rig_skeleton"


def phase5_animation():
    """Animation: the small left 3D view becomes the camera view, the right Outliner is closed so the dock gets its
    height, the bottom editor (Dope Sheet, switched to the Graph Editor by the Status Line) gets a short Timeline under
    it with its controls below the slider, and the screen redraws only viewports and animation editors while playing."""
    import m3d_anim
    ws = bpy.data.workspaces["Animation"]
    show(ws)
    yield 0.6
    screen = window().screen

    def timelines():
        return [a for a in areas(screen, 'DOPESHEET_EDITOR') if a.spaces.active.mode == 'TIMELINE']

    if not timelines():
        outliner = areas(screen, 'OUTLINER')[0]
        run(bpy.ops.screen.area_close, outliner)
        yield 0.3
        bottom = areas(screen, 'DOPESHEET_EDITOR')[0]
        run(bpy.ops.screen.area_split, bottom, direction='HORIZONTAL', factor=0.3)
        yield 0.3
        lower = min(areas(screen, 'DOPESHEET_EDITOR'), key=lambda a: a.y)
        lower.ui_type = 'TIMELINE'
        yield 0.3
        lower = timelines()[0]
        upper = next(a for a in areas(screen, 'DOPESHEET_EDITOR') if a != lower)
        edge = (upper.x + upper.width // 2, upper.y - 1)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=-(lower.height - ANIM_TIMELINE_HEIGHT))
        yield 0.3
        dock = areas(screen, 'PROPERTIES')[-1]
        edge = (dock.x - 1, dock.y + dock.height // 2)
        window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=edge[0], y=edge[1])
        yield 0.3
        with bpy.context.temp_override(window=window(), screen=screen):
            bpy.ops.screen.area_move(x=edge[0], y=edge[1], delta=-DOCK_WIDER)
        yield 0.3
        timeline = timelines()[0]   # The slider sits above its controls.
        header = next(r for r in timeline.regions if r.type == 'HEADER')
        if header.alignment == 'TOP':
            with bpy.context.temp_override(window=window(), screen=screen, area=timeline, region=header):
                bpy.ops.screen.region_flip()
            yield 0.3
    left, main = sorted(areas(screen, 'VIEW_3D'), key=lambda a: a.x)
    left.spaces.active.region_3d.view_perspective = 'CAMERA'
    main.spaces.active.shading.type = 'SOLID'
    main.spaces.active.overlay.show_xray_bone = True
    areas(screen, 'PROPERTIES')[0].spaces.active.context = 'CHANNEL_BOX'
    ws.m3d_page_right = "anim_pick"
    m3d_anim.limit_playback_redraw(screen)


ANIM_TIMELINE_HEIGHT = 130  # pixels the Timeline under the Graph Editor / Dope Sheet keeps

RIG_LEFT_WIDTH = 300  # pixels of the 2560 px build window: Outliner and bone collections
RIG_LEFT_SPLIT = 0.4  # share of the left column the bone collections get (the lower part; the Outliner keeps the rest)
RIG_TIMELINE_HEIGHT = 230  # pixels the bottom Timeline keeps (the Drivers editor is the same area)

DOCK_WIDER = 170  # pixels of the 2560 px build window: seven tabs, All Settings and the tab menu fit
UV_WIDER = 250  # pixels the UV editor gets from the 3D view
TEXTURE_VIEW_WIDER = 250  # pixels the Texture workspace's 3D view gets from the paint view

PHASES = [phase0_workspaces, phase1_sculpt, phase2_uv, phase3_texture, phase4_rigging, phase5_animation]


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
