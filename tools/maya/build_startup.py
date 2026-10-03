# SPDX-License-Identifier: GPL-2.0-or-later
"""
Build MayaBlender's factory startup file (Maya workspaces and Maya Classic layout).

Run in the GUI (screen operators need a window), it saves and quits by itself:

    set BLENDER_USER_RESOURCES=<empty temp dir>
    blender --factory-startup --python tools/maya/build_startup.py -- release/datafiles/startup.blend
"""

import os
import shutil
import sys

import bpy

OUT = os.path.abspath(sys.argv[sys.argv.index("--") + 1])

# Blender workspace -> Maya workspace name.
RENAME = {
    "Layout": "Maya Classic",
    "Modeling": "Modeling - Standard",
    "Texture Paint": "3D Paint",
    "Shading": "Hypershade",
    "Geometry Nodes": "Node Editor",
    "Scripting": "Script Editor",
}


def areas(screen, type):
    return sorted((a for a in screen.areas if a.type == type), key=lambda a: (a.x, a.y))


def run(op, area, **props):
    win = bpy.context.window_manager.windows[0]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    print("MAYA STEP", op.idname(), area.type, flush=True)
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        op(**props)


def maya_classic_layout():
    """Outliner docked left, viewport centre, Attribute Editor right, command line at the bottom."""
    screen = bpy.context.window_manager.windows[0].screen
    outliner_top_right = areas(screen, 'OUTLINER')[0]
    run(bpy.ops.screen.area_close, outliner_top_right)  # Properties (Attribute Editor) takes the column.

    run(bpy.ops.screen.area_split, areas(screen, 'VIEW_3D')[0], direction='VERTICAL', factor=0.14)
    areas(screen, 'VIEW_3D')[0].ui_type = 'OUTLINER'

    run(bpy.ops.screen.area_split, areas(screen, 'DOPESHEET_EDITOR')[0], direction='HORIZONTAL', factor=0.35)
    command_line = min(areas(screen, 'DOPESHEET_EDITOR'), key=lambda a: a.y)
    command_line.ui_type = 'CONSOLE'


def step_layout():
    maya_classic_layout()
    win = bpy.context.window_manager.windows[0]
    win.workspace = bpy.data.workspaces["Animation"]
    bpy.app.timers.register(step_rigging, first_interval=1.0)


def step_rigging():
    # Maya ships a Rigging workspace; start it from the animation layout.
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win):
        bpy.ops.workspace.duplicate()
    bpy.data.workspaces["Animation.001"].name = "Rigging"
    for old, new in RENAME.items():
        bpy.data.workspaces[old].name = new
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.show_region_tool_header = True  # Maya shelf row.
    win.workspace = bpy.data.workspaces["Maya Classic"]
    bpy.app.timers.register(step_save, first_interval=1.0)


def step_save():
    # Hide the command line's header now that it has been drawn (doing it right after the split crashes).
    for area in areas(bpy.context.window_manager.windows[0].screen, 'CONSOLE'):
        area.spaces.active.show_region_header = False
    bpy.context.preferences.filepaths.use_file_compression = True
    bpy.ops.wm.save_homefile()
    saved = os.path.join(bpy.utils.resource_path('USER'), "config", "startup.blend")
    shutil.copyfile(saved, OUT)
    print("MAYA STARTUP SAVED", OUT, [w.name for w in bpy.data.workspaces])
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(step_layout, first_interval=1.0)
