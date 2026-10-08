# SPDX-License-Identifier: GPL-2.0-or-later
"""
Screenshots of workspaces (real window, saved with bpy.ops.screen.screenshot).

    blender --factory-startup --python tools/m3d/screenshot.py -- <png prefix> [name ...]

Each name is a workspace name or kind (MODEL, SCULPT, ...); writes <prefix><name>.png and quits. Default: the first workspace.
"""

import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
PREFIX, NAMES = args[0], args[1:] or [None]
steps = []


def switch(name):
    wm = bpy.context.window_manager
    if name is None:
        return
    if name.isupper():
        bpy.ops.m3d.workspace(kind=name)
    else:
        wm.windows[0].workspace = bpy.data.workspaces[name]


def shot(name):
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen, area=win.screen.areas[0]):
        bpy.ops.screen.screenshot(filepath="%s%s.png" % (PREFIX, name or "default"), check_existing=False)


for name in NAMES:
    steps.append(lambda n=name: switch(n))
    steps.append(lambda: None)  # Let the workspace change and redraw.
    steps.append(lambda: None)
    steps.append(lambda n=name: shot(n))
steps.append(bpy.ops.wm.quit_blender)


def run_next():
    steps.pop(0)()
    return 0.6 if steps else None


bpy.app.timers.register(run_next, first_interval=3.0)
