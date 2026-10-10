# SPDX-License-Identifier: GPL-2.0-or-later
"""
Times workspace switches with a huge mesh in a real window: each switch is timed until the next main-loop tick after it
(the notifiers, the mode change, the depsgraph and the redraw all happen in between).

    blender --factory-startup --python tools/m3d/profile_workspaces.py -- <out file> [voxel size ...]

Two cases per voxel size (default 0.0035 and 0.0025, about 1.5M and 3M faces):
  - one huge mesh, no pair: every switch rebuilds its viewport data;
  - a low poly with a high poly of that size (Create High Poly > Voxel Remesh), parked: Sculpt > Modeling hides the high
    poly in the same step, so only Model > Sculpt (showing it) pays for the mesh.
"""
import sys
import time

import bpy

OUT = sys.argv[sys.argv.index("--") + 1]
VOXELS = [float(v) for v in sys.argv[sys.argv.index("--") + 2:]] or [0.0035, 0.0025]
SWITCHES = ('MODEL', 'SCULPT', 'MODEL', 'SCULPT', 'MODEL', 'UV', 'MODEL', 'TEXTURE', 'MODEL', 'RENDER', 'MODEL')
lines = []


def log(text):
    print(text)
    lines.append(text)
    with open(OUT, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def clear_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)


def make_mesh(voxel):
    """One smooth sphere of millions of faces (a voxel remesh of a UV sphere)."""
    clear_scene()
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0)
    ob = bpy.context.active_object
    mod = ob.modifiers.new("r", 'REMESH')
    mod.mode, mod.voxel_size = 'VOXEL', voxel
    bpy.ops.object.modifier_apply(modifier="r")
    bpy.ops.object.shade_smooth()
    return ob


def make_pair(voxel):
    """A low poly sphere and its high poly (Create High Poly), parked: hidden, the low poly active."""
    clear_scene()
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0)
    low = bpy.context.active_object
    low.name = "Sword"
    bpy.ops.m3d.hp_create(detail='VOXEL', voxel_size=voxel)
    high = bpy.data.objects["Sword_high"]
    bpy.ops.object.shade_smooth()
    bpy.ops.m3d.hp_park()
    return low, high


def switch(kind):
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen, area=None, region=None):
        bpy.ops.m3d.workspace(kind=kind)


def timed(kind, note=lambda: ""):
    """Generator step: switch, wait one tick, log the time (`note()` adds to the line)."""
    t0 = time.perf_counter()
    switch(kind)
    yield 0.0
    ob = bpy.context.active_object
    log("  -> %-8s %-14s %7.0f ms %s" % (kind, ob.mode if ob else "-", (time.perf_counter() - t0) * 1000, note()))
    yield 0.5


def steps():
    yield 2.0
    for voxel in VOXELS:
        ob = make_mesh(voxel)
        log("mesh %d faces, no pair" % len(ob.data.polygons))
        yield 1.0
        for kind in SWITCHES:
            yield from timed(kind)
        low, high = make_pair(voxel)
        log("pair: low poly %d faces, high poly %d faces (parked)" % (len(low.data.polygons), len(high.data.polygons)))
        yield 1.0
        for kind in SWITCHES:
            yield from timed(kind, lambda: "(high poly %s)" % ("hidden" if high.hide_get() else "shown"))
    log("DONE")
    bpy.ops.wm.quit_blender()


_gen = steps()


def tick():
    try:
        return next(_gen)
    except StopIteration:
        return None
    except Exception:
        import traceback
        log("ERROR " + traceback.format_exc())
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1.0)
