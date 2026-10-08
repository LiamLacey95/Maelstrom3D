# SPDX-License-Identifier: GPL-2.0-or-later
"""
Screenshots of workspaces (real window, saved with bpy.ops.screen.screenshot).

    blender --factory-startup --python tools/m3d/screenshot.py -- <png prefix> [name ...]

Each name is a workspace name or kind (MODEL, SCULPT, ...); writes <prefix><name>.png and quits. Default: the first workspace.
`KIND/page` also shows that dock page (e.g. SCULPT/sculpt_mask). Setup steps (no picture): `+sphere` / `+cube` add a
mesh, `+unwrap` runs Auto Unwrap (Edit Mode, UV workspace), `+checker` toggles the checker map, `+distortion` shows
the UV Editor's distortion, `+paint` (Texture workspace: a material, four painted channels), `+bake` (bakes Normal and
AO at 128 px).
"""

import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
PREFIX, NAMES = args[0], args[1:] or [None]
steps = []


def distortion():
    area = next(a for a in bpy.context.window_manager.windows[0].screen.areas if a.type == 'IMAGE_EDITOR')
    area.spaces.active.uv_editor.show_stretch = True


def paint():
    import numpy as np
    bpy.ops.m3d.tex_add_material()
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    bpy.context.scene.m3d_tex.resolution = '512'
    for channel in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL', 'BASE_COLOR'):
        bpy.ops.m3d.tex_channel(channel=channel)
    from m3d_texture import channel_slots
    base = channel_slots(bpy.context.active_object.active_material)['BASE_COLOR'][1]
    ramp = np.linspace(0.0, 1.0, 512, dtype=np.float32)
    px = np.ones((512, 512, 4), np.float32)
    px[..., 0], px[..., 1], px[..., 2] = 0.8, 0.25 + 0.5 * ramp[None, :], 0.1 + 0.2 * ramp[:, None]
    base.pixels.foreach_set(px.ravel())
    base.update()


def bake():
    ob = bpy.context.active_object
    ob.m3d_bake.resolution, ob.m3d_bake.samples = '128', 8
    bpy.ops.m3d.tex_bake()


SETUP = {
    "+paint": paint,
    "+bake": bake,
    "+sphere": lambda: bpy.ops.m3d.add_primitive(kind='SPHERE'),
    "+cube": lambda: bpy.ops.m3d.add_primitive(kind='CUBE'),
    "+unwrap": lambda: bpy.ops.m3d.uv_auto(),
    "+checker": lambda: bpy.ops.m3d.uv_checker(),
    "+distortion": distortion,
}


def switch(name):
    wm = bpy.context.window_manager
    name, _slash, page = (name or "").partition("/")
    if not name:
        return
    if name in SETUP:
        SETUP[name]()
    elif name.isupper():
        bpy.ops.m3d.workspace(kind=name)
    else:
        wm.windows[0].workspace = bpy.data.workspaces[name]
    if page:
        from m3d_workspace import DOCK_TABS
        win = wm.windows[0]
        left = {t.page for t in DOCK_TABS[name]['LEFT']}
        setattr(win.workspace, "m3d_page_" + ("left" if page in left else "right"), page)
        for area in win.screen.areas:
            area.tag_redraw()


def shot(name):
    win = bpy.context.window_manager.windows[0]
    if name and name.startswith("+"):
        return
    with bpy.context.temp_override(window=win, screen=win.screen, area=win.screen.areas[0]):
        bpy.ops.screen.screenshot(filepath="%s%s.png" % (PREFIX, (name or "default").replace("/", "_")),
                                  check_existing=False)


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
