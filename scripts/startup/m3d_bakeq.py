# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Bakes that do not freeze the window, for Maelstrom3D (Texture workspace, Bake page): the Cycles device a bake runs on, the bake
queue and the bake guard.

A bake is written as a generator that yields the arguments of one `bpy.ops.object.bake` call at a time and gets control back after
it (`bake_maps_steps` in m3d_texture.py, `bake_group_steps` in m3d_bakegroups.py ...). `drive` runs such a generator at once, each
bake a blocking operator call: the Python API, background mode and the mask effects that bake what they need work like that. `run_queued` runs
it as a queue instead: each bake is Blender's own bake job (the window keeps drawing, the status bar shows its progress bar), and the
next one starts when `object_bake_complete` / `object_bake_cancel` say that the job is over. The generator is suspended meanwhile, so
its `with` blocks (the selection, the hidden meshes, the swapped materials, the engine and the device) stay open until the queue ends
or is cancelled, then close, also after an error. Esc cancels the running job (Blender does that itself); the Cancel button stops the
queue after the map that is baking.

A job reads the scene from its own thread, so nothing may change under it. The bake guard (a modal operator) lets the view move
(Alt + mouse, the middle button, the wheel, F, Home and the number pad in the 3D view and the 2D view, the headers of the views and the
Status Line of the Texture workspace, which draw only the View menu, the layout buttons and Cancel meanwhile, and the Bake page, which
shows only the progress) and the panels scroll, and blocks every other click and key, with a note in the 3D view. The high polys are
drawn as boxes (a bake needs them shown), the view of the Bake page (m3d_bakeview.py) is put away, and a 3D view in the Rendered type
is switched to Material for the time (Cycles is the engine meanwhile).

The device: a bake runs on the GPU when there is one that bakes right (`find_gpu`), else on the CPU. A GPU is tried with a test bake of a flat
color: a GPU that has no kernels in this build (or a driver that fails) makes Cycles write grey and say nothing.
"""

import time
from collections import namedtuple
from contextlib import nullcontext

import bpy
import numpy as np
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

BACKENDS = ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL')   # the GPU backends of Cycles, best first

# -----------------------------------------------------------------------------
# The device

_gpu = {"found": None, "kind": None}   # find_gpu's answer (backend or None, device names, note), and the compute device type it is for
PROBE_COLOR = (0.2, 0.5, 0.8)


def cycles_prefs(_context=None):
    """The preferences of the Cycles add-on (None when it is off)."""
    addon = bpy.context.preferences.addons.get('cycles')
    return addon.preferences if addon is not None else None


def offered(prefs, _context=None):
    """The GPU backends this build of Cycles has, best first."""
    try:
        have = {item[0] for item in prefs.get_device_types(bpy.context)}
    except (AttributeError, TypeError):
        have = set()
    return [kind for kind in BACKENDS if kind in have]


def gpus_of(prefs, kind):
    """The GPU entries of the preferences for a backend."""
    return [d for d in prefs.get_devices_for_type(kind) if d.type == kind]


def probe(_context=None):
    """Bake a flat color on the GPU, with the preferences as they are, in a scene of its own that goes away after, and say whether
    the pixels are right (a GPU without kernels makes Cycles write grey and say nothing: the bake of a mesh would be wrong
    and look done)."""
    scene, mesh = bpy.data.scenes.new("m3dProbe"), bpy.data.meshes.new("m3dProbe")
    image = bpy.data.images.new("m3dProbe", 8, 8, alpha=False, float_buffer=True)
    mat = bpy.data.materials.new("m3dProbe")
    ob = bpy.data.objects.new("m3dProbe", mesh)
    ok = False
    try:
        mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new(name="UVMap")
        for loop, co in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop.uv = co
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        out, emit, tex = nodes.new("ShaderNodeOutputMaterial"), nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeTexImage")
        emit.inputs["Color"].default_value = (*PROBE_COLOR, 1.0)
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
        tex.image = image
        nodes.active = tex
        mesh.materials.append(mat)
        scene.collection.objects.link(ob)
        scene.render.engine = 'CYCLES'
        scene.cycles.device, scene.cycles.samples, scene.cycles.use_denoising = 'GPU', 1, False
        layer = scene.view_layers[0]
        layer.objects.active = ob
        ob.select_set(True, view_layer=layer)
        with bpy.context.temp_override(scene=scene, view_layer=layer, active_object=ob, object=ob, selected_objects=[ob],
                                   selected_editable_objects=[ob]):
            bpy.ops.object.bake(type='EMIT', target='IMAGE_TEXTURES', margin=0, use_clear=True, save_mode='INTERNAL')
        px = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(px)
        ok = bool(np.abs(px.reshape(-1, 4)[:, :3] - PROBE_COLOR).max() < 0.02)
    except (RuntimeError, TypeError, ValueError):
        ok = False
    finally:
        for data, collection in ((ob, bpy.data.objects), (mesh, bpy.data.meshes), (mat, bpy.data.materials),
                                 (image, bpy.data.images), (scene, bpy.data.scenes)):
            collection.remove(data)
    return ok


def find_gpu(context):
    """(backend, device names, note) of the GPU a bake can use: backend is None, and `note` says why, when there is none. Cycles'
    preferences are set up for it, but only what is not set yet: a compute device type that was chosen stays, and the devices
    stay as they are. Without a choice the best backend that has a GPU and bakes right (a test bake) is set, with its GPUs on and the CPU off;
    what a backend that fails changed is put back. Asked once: the answer is kept until the compute device type changes."""
    prefs = cycles_prefs()
    if prefs is None:
        return None, [], "Cycles is off"
    kind = prefs.compute_device_type
    found = _gpu["found"]
    if found is not None and _gpu["kind"] == kind:
        return found
    if kind != 'NONE':   # (the user's choice: its devices as they ticked them)
        names = [d.name for d in gpus_of(prefs, kind) if d.use]
        found = (kind, names, "") if names and probe() else (None, [], "The Cycles preferences use no GPU" if not names else
                                                                    "The %s GPU did not pass a test bake" % kind)
    else:
        found, tried = (None, [], "No GPU in this computer or this build of Cycles"), []
        for backend in offered(prefs):
            gpus = gpus_of(prefs, backend)
            if not gpus:
                continue
            saved = [(d, d.use) for d in prefs.devices]
            prefs.compute_device_type = backend
            for d in prefs.devices:
                d.use = d.type == backend
            if probe():
                found = (backend, [d.name for d in gpus], "")
                break
            prefs.compute_device_type = 'NONE'
            for d, use in saved:
                d.use = use
            tried.append(backend)
        if tried:
            found = (None, [], "The GPU did not pass a test bake (%s)" % ", ".join(tried))
    _gpu["found"], _gpu["kind"] = found, prefs.compute_device_type
    return found


def device_for(context):
    """'GPU' when the bake runs on the GPU (Bake on GPU is on and there is a GPU that bakes right), else 'CPU'."""
    return 'GPU' if context.scene.m3d_tex.bake_gpu and find_gpu(context)[0] else 'CPU'


def device_note(context):
    """What the Bake page says about the device, from what is known (nothing is tried while a panel draws): the GPU, or the CPU with the
    reason."""
    prefs = cycles_prefs()
    if prefs is None:
        return "CPU: Cycles is off"
    if not context.scene.m3d_tex.bake_gpu:
        return "CPU: Bake on GPU is off"
    found = _gpu["found"]
    if found is None or _gpu["kind"] != prefs.compute_device_type:
        return "GPU: checked at the first bake" if offered(prefs) else "CPU: no GPU in this build of Cycles"
    return "GPU: %s (%s)" % (", ".join(found[1]), found[0]) if found[0] else "CPU: " + found[2]


def check_gpu_soon():
    """Ask find_gpu a moment later (a test bake takes a second: not while a panel draws)."""
    if _gpu["found"] is None and not bpy.app.timers.is_registered(_check_gpu):
        bpy.app.timers.register(_check_gpu, first_interval=0.1)


def _check_gpu():
    if _run is None and bpy.context.scene is not None:
        find_gpu(bpy.context)
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()


# -----------------------------------------------------------------------------
# Driving a bake generator

Job = namedtuple("Job", "title steps total finish")   # finish(context, report, result, error) -> True when something was baked
CANCELLED = RuntimeError("Cancelled")   # `error` of a finish function when the queue was cancelled
_note = {"label": "", "where": ""}   # what is being baked: the map and the group, for the panels


def note(label=None, where=None):
    """Say what is being baked (the Bake page shows it); called by the generators."""
    if label is not None:
        _note["label"] = label
    if where is not None:
        _note["where"] = where


def drive(steps):
    """Run a bake generator to its end with each bake it asks for as a blocking `bpy.ops.object.bake` call, as the bake operators
    do from Python. An error of the call is raised inside the generator at its `yield`, so that its `with` blocks close and its
    `except` clauses see it. Returns what the generator returns."""
    try:
        request = next(steps)
        while True:
            try:
                bpy.ops.object.bake(**request)
            except RuntimeError as err:
                request = steps.throw(err)
            else:
                request = steps.send(None)
    except StopIteration as done:
        return done.value


def run_blocking(context, job, report):
    """Bake at once, the window waits (an operator's execute, the Python API, background mode). `report(level, text)` says the news.
    True when something was baked."""
    result = error = None
    try:
        result = drive(job.steps)
    except RuntimeError as err:
        error = err
    return job.finish(context, report, result, error)


def report_later(level, text):
    """A report of a queue that is over (its operator is gone): an internal operator says it."""
    try:
        bpy.ops.m3d.bake_report('EXEC_DEFAULT', level=level, text=text)
    except RuntimeError:
        print("%s: %s" % (level, text))


# -----------------------------------------------------------------------------
# The queue

class Run:
    """The queue that is running (`_run`): the generator, what the panels show of it, what the handlers saw of the job."""
    def __init__(self, job, window):
        self.job, self.window = job, window
        self.total = max(job.total, 1)
        self.count = 0           # bakes that are done
        self.phase = 'START'     # START, then WAIT while a bake job runs, IDLE between two
        self.ended = None        # 'complete' or 'cancel': what the handlers said of the job
        self.cancelling = False  # Cancel was pressed, or Esc between two jobs
        self.t0 = time.perf_counter()
        self.launched = 0.0
        self.blocked = 0.0       # when the guard last stopped a click or a key
        self.restore = []        # (space, shading type) of the 3D views that were in Rendered


_run = None
_bars = {"status": None}   # the rectangle (x, y, width, height) of the Status Line in the window, noted by its header when it draws


def running():
    """Is a queued bake running?"""
    return _run is not None


def cancelling():
    return _run is not None and _run.cancelling


def progress():
    """(done, total, label, where, seconds) of the running queue."""
    run = _run
    return (run.count, run.total, _note["label"], _note["where"], time.perf_counter() - run.t0) if run is not None else (0, 0, "", "", 0.0)


def text():
    """The one line the panels say while a bake runs."""
    if _run is None:
        return ""
    done, total, label, where, _t = progress()
    return "Baking %s%s: %d of %d" % (label, " (%s)" % where if where else "", min(done + 1, total), total) + (
        " - stopping" if _run.cancelling else "")


def note_region(region):
    """The Status Line header tells where it is (window pixels): the guard lets a click on it through."""
    _bars["status"] = (region.x, region.y, region.width, region.height)


def window_of(context):
    wm = context.window_manager
    return context.window or (wm.windows[0] if wm.windows else None)


def run_queued(context, job):
    """Bake as a queue of bake jobs: this returns at once, the first bake starts a moment later (the undo step of the operator that
    called this is then the one before the bake), `job.finish` runs when the queue is over. In background mode there is
    no event loop for a job: the bake is blocking. False when a bake is running already."""
    if _run is not None:
        return False
    if bpy.app.background or window_of(context) is None:
        run_blocking(context, job, report_later)
        return True
    start(context, job, window_of(context))
    return True


def start(context, job, window):
    """Start the queue for a job in `window` (None: no window, the tests drive the timer by hand)."""
    global _run
    _run = Run(job, window)
    _note.update(label="", where="")
    if window is not None:
        prepare(context)
    bpy.app.timers.register(_tick, first_interval=0.0)


def prepare(context):
    """What the queue needs before it starts: the visualization of the Bake page is put away (it changes meshes and
    materials), a 3D view in Rendered goes to Material (Cycles is the engine meanwhile; a Cycles viewport would race the job), the
    Bake page is shown, the banner is drawn in the 3D views."""
    import m3d_bakeview
    import m3d_workspace as W
    m3d_bakeview.leave(context)
    for area in _run.window.screen.areas:
        if area.type == 'VIEW_3D':
            shading = area.spaces.active.shading
            if shading.type == 'RENDERED':
                _run.restore.append((area.spaces.active, 'RENDERED'))
                shading.type = 'MATERIAL'
    ws = _run.window.workspace
    if ws is not None and W.workspace_kind(ws) == 'TEXTURE' and ws.m3d_page_right != "tex_bake":
        ws.m3d_page_right = "tex_bake"
    _banner["handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw_banner, (), 'WINDOW', 'POST_PIXEL')


def retire(context):
    """The queue is over: the 3D views are as they were."""
    for space, kind in _run.restore:
        try:
            space.shading.type = kind
        except (ReferenceError, AttributeError):
            pass   # (the view is gone)
    handle = _banner.pop("handle", None)
    if handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')


def redraw(window):
    for area in window.screen.areas if window is not None else ():
        if area.type in {'PROPERTIES', 'VIEW_3D', 'IMAGE_EDITOR'}:
            area.tag_redraw()


def window_override(window):
    """The context of the window the queue was started in (a timer has no window of its own)."""
    return bpy.context.temp_override(window=window, screen=window.screen) if window is not None else nullcontext()


def _guard(window):
    """Start the bake guard (a modal operator of the window) unless it runs."""
    if not _guard_state["on"]:
        with bpy.context.temp_override(window=window, screen=window.screen):
            bpy.ops.m3d.bake_guard('INVOKE_DEFAULT')


def _tick():
    """Timer of the queue: starts it, then waits for each job to be over and starts the next bake."""
    run = _run
    if run is None:
        return None
    try:
        with window_override(run.window):
            if run.phase == 'START':
                if run.window is not None:
                    _guard(run.window)
                _advance(run, 'start')
            elif run.phase == 'WAIT' and not bpy.app.is_job_running('OBJECT_BAKE') and (
                    run.ended is not None or time.perf_counter() - run.launched > 2.0):
                _advance(run, 'complete' if run.ended in {'complete', None} and not run.cancelling else 'cancel')
            elif run.phase == 'IDLE':
                _advance(run, 'cancel' if run.cancelling else 'complete')
    except BaseException as err:   # (the queue must not be left half done: a timer that raises is gone, and the guard would stay)
        import traceback
        traceback.print_exc()
        _finish(run, None, err)
    if _run is not None:
        redraw(run.window)
    return 0.1 if _run is not None else None


def _advance(run, how):
    """The generator goes on ('start', 'complete': the bake it asked for is done) or is closed ('cancel'): its `with` blocks restore the
    scene. Then the next bake is launched, or the queue is over."""
    try:
        if how == 'cancel':
            run.job.steps.close()
            _finish(run, None, CANCELLED)
            return
        if how == 'start':
            request = next(run.job.steps)
        else:
            run.count += 1
            request = run.job.steps.send(None)
        while True:
            try:
                if run.cancelling:
                    run.job.steps.close()
                    _finish(run, None, CANCELLED)
                    return
                _launch(run, request)
                return
            except RuntimeError as err:   # (the bake could not start: raised at the yield, as a blocking call would)
                request = run.job.steps.throw(err)
    except StopIteration as done:
        _finish(run, done.value, None)
    except BaseException as err:
        _finish(run, None, err)


def _launch(run, request):
    """Start Blender's bake job for a request of the generator."""
    run.ended, run.launched = None, time.perf_counter()
    if bpy.ops.object.bake('INVOKE_DEFAULT', **request) != {'RUNNING_MODAL'}:
        raise RuntimeError("Blender did not start the bake")
    run.phase = 'WAIT'


def _finish(run, result, error):
    """The queue is over (done, cancelled or failed): the generator has closed its `with` blocks, the guard goes, the views are as
    they were, `job.finish` says the news."""
    global _run
    context = bpy.context
    try:
        run.phase = 'END'
        retire(context)
    finally:
        _run = None
    redraw(run.window)
    ws = run.window.workspace if run.window is not None else None
    if ws is not None:
        ws.status_text_set(None)
    try:
        with window_override(run.window):
            done = run.job.finish(context, report_later, result, error)
            if done and run.window is not None:
                bpy.ops.ed.undo_push(message=run.job.title)
    except BaseException:
        import traceback
        traceback.print_exc()
    redraw(run.window)


def cancel():
    """Stop after the bake that is running (Esc stops it at once: Blender cancels the job itself)."""
    if _run is not None:
        _run.cancelling = True


def _bake_ended(kind):
    """A bake job is over (called by the handlers, in the main thread): the timer goes on when the job has gone."""
    if _run is not None and _run.phase == 'WAIT':
        _run.ended = kind
        if kind == 'cancel':
            _run.cancelling = True   # (cancelled or failed: either way the queue stops)


@bpy.app.handlers.persistent
def _on_complete(*_args):
    _bake_ended('complete')


@bpy.app.handlers.persistent
def _on_cancel(*_args):
    _bake_ended('cancel')


# -----------------------------------------------------------------------------
# The banner in the 3D view

_banner = {}
_guard_state = {"on": False}


def _draw_banner():
    """Drawn in every 3D view while a bake runs: what is baking, a bar for the maps done, and how to stop it. A fixed number of
    draw calls: no work for the mesh."""
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    run = _run
    region = bpy.context.region
    if run is None or region is None:
        return
    done, total, _label, _where, seconds = progress()
    line = "%s    %d s    Esc to cancel" % (text(), seconds)
    font, size = 0, 15
    blf.size(font, size)
    width, height = blf.dimensions(font, line)
    x, y = region.width / 2 - width / 2, region.height - 44
    pad = 10
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    flash = time.monotonic() - run.blocked < 1.0
    left, right, bottom, top = x - pad, x + width + pad, y - pad - 6, y + height + pad

    def quad(x0, y0, x1, y1, color):
        batch = batch_for_shader(shader, 'TRI_FAN', {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
    quad(left, bottom, right, top, (0.35, 0.05, 0.05, 0.85) if flash else (0.05, 0.05, 0.05, 0.75))
    quad(left, bottom, left + (right - left) * min(done / total, 1.0), bottom + 4, (0.3, 0.6, 1.0, 1.0))
    blf.color(font, 1.0, 1.0, 1.0, 1.0)
    blf.position(font, x, y, 0)
    blf.draw(font, line)
    gpu.state.blend_set('NONE')


# -----------------------------------------------------------------------------
# The guard

QUIET = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'WINDOW_DEACTIVATE', 'NONE', 'TIMER', 'TIMER0', 'TIMER1', 'TIMER2', 'TIMER_JOBS',
         'TIMER_AUTOSAVE', 'TIMER_REPORT', 'TIMERREGION', 'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT',
         'RIGHT_ALT', 'OSKEY'}   # events that are no click and no key
WHEELS = {'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'}
GESTURES = {'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM', 'NDOF_MOTION', 'NDOF_BUTTON_FIT',
            'NDOF_BUTTON_FRONT', 'NDOF_BUTTON_BACK', 'NDOF_BUTTON_LEFT', 'NDOF_BUTTON_RIGHT', 'NDOF_BUTTON_TOP', 'NDOF_BUTTON_BOTTOM'}
VIEW_KEYS = {'F', 'HOME', 'NUMPAD_0', 'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4', 'NUMPAD_5', 'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8',
             'NUMPAD_9', 'NUMPAD_PERIOD', 'NUMPAD_PLUS', 'NUMPAD_MINUS', 'NUMPAD_SLASH'}
VIEWS = {'VIEW_3D', 'IMAGE_EDITOR'}


def locate(window, x, y):
    """(area, region) of the editor under a window position; (None, None) over the top bar or outside the editors. A region that
    lies over another (a sidebar over the view) wins over it."""
    for area in window.screen.areas:
        if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
            found = None
            for region in area.regions:
                if region.width > 1 and region.height > 1 and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                    if found is None or region.type != 'WINDOW':
                        found = region
            return area, found
    return None, None


def over_status_line(x, y):
    box = _bars["status"]
    return box is not None and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]


def is_bake_dock(context, area, region):
    """Is this Properties editor showing the Bake page? While a bake runs it shows the progress and Cancel and nothing else."""
    import m3d_workspace as W
    if area.type != 'PROPERTIES':
        return False
    with context.temp_override(area=area, region=region):
        return W.active_page(context) == "tex_bake"


def headers_reduced(context):
    """Do the headers of the views draw only what moves the view while a bake runs? They do in the Texture workspace of the new layout (m3d_texture.draw_view_header); the
    headers of the other layouts and workspaces have menus that edit, so a click on them is blocked."""
    import m3d_workspace as W
    return W.texture_clean(context)


def status_reduced(context):
    """Does the Status Line draw only Cancel and the view while a bake runs? In the Texture workspace (m3d_texture.draw_status_line)."""
    import m3d_workspace as W
    return W.current_kind(context) == 'TEXTURE'


def allowed(context, window, event):
    """May the event reach Blender's own handlers while a bake runs? The view moves and the panels scroll; nothing else does."""
    t = event.type
    if t in QUIET:
        return True
    area, region = locate(window, event.mouse_x, event.mouse_y)
    if t in WHEELS and not event.ctrl and not event.alt:
        return True   # (scrolls a panel or a list, zooms a view: with Ctrl or Alt it would change a value under the pointer)
    if area is None:
        return t == 'LEFTMOUSE' and over_status_line(event.mouse_x, event.mouse_y) and status_reduced(context)
    if area.type in VIEWS and region is not None:
        if region.type == 'WINDOW':
            if t == 'MIDDLEMOUSE' or t in WHEELS or t in GESTURES:
                return True
            if t in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.alt:   # (Alt + mouse: orbit, pan and zoom)
                return True
            return t in VIEW_KEYS and not event.ctrl and not event.alt and not event.shift or t == 'F' and event.shift
        if region.type in {'HEADER', 'TOOL_HEADER'}:
            return t == 'LEFTMOUSE' and headers_reduced(context)   # (the View menu and the layout buttons: such a header draws nothing else)
        return False
    if area.type == 'PROPERTIES' and region is not None and region.type == 'WINDOW' and is_bake_dock(context, area, region):
        return t == 'LEFTMOUSE'
    return False


class M3D_OT_bake_guard(Operator):
    """While a bake runs: the view can be moved and the panels scrolled, nothing else can be changed (a bake job reads the scene
    from its own thread). Esc cancels the bake"""
    bl_idname = "m3d.bake_guard"
    bl_label = "Baking"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        if _run is None or _guard_state["on"]:
            return {'CANCELLED'}
        _guard_state["on"] = True
        self.window = context.window
        wm = context.window_manager
        self.timer = wm.event_timer_add(0.2, window=context.window)   # (so that the guard notices that the queue is over, without waiting for a key)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        run = _run
        if run is None:
            _guard_state["on"] = False
            context.window_manager.event_timer_remove(self.timer)
            return {'FINISHED', 'PASS_THROUGH'}
        if event.type == 'ESC' and event.value == 'PRESS':   # (a running job cancels itself: it gets the key before this handler)
            run.cancelling = True
            return {'RUNNING_MODAL'}
        if allowed(context, self.window, event):
            return {'PASS_THROUGH'}
        if event.value in {'PRESS', 'CLICK', 'DOUBLE_CLICK'} or event.type in WHEELS:
            run.blocked = time.monotonic()
            context.workspace.status_text_set("Baking... (Esc to cancel)")
            redraw(self.window)
        return {'RUNNING_MODAL'}


class M3D_OT_bake_cancel(Operator):
    """Stop the bake queue after the map that is baking (Esc stops the running map at once)"""
    bl_idname = "m3d.bake_cancel"
    bl_label = "Cancel"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, _context):
        return _run is not None

    def execute(self, _context):
        cancel()
        return {'FINISHED'}


class M3D_OT_bake_report(Operator):
    """Say something in the status bar and the Info log (the news of a bake queue that is over)"""
    bl_idname = "m3d.bake_report"
    bl_label = "Bake Report"
    bl_options = {'INTERNAL'}

    level: EnumProperty(items=(('INFO', "Info", ""), ('WARNING', "Warning", ""), ('ERROR', "Error", "")), default='INFO')
    text: StringProperty()

    def execute(self, _context):
        self.report({self.level}, self.text)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Panels

def draw_progress(layout, context):
    """The Bake page while a bake runs: what is baking, the bar of the maps done, the job's own bar with its stop button, Cancel."""
    done, total, _label, _where, seconds = progress()
    col = layout.column()
    col.label(text=text(), icon='RENDER_STILL', translate=False)
    col.progress(factor=min(done / max(total, 1), 1.0), text="%d s" % seconds, type='BAR')
    col.template_running_jobs()
    row = col.row()
    row.scale_y = 1.4
    row.operator("m3d.bake_cancel", icon='CANCEL')
    col.label(text="Esc stops the map that is baking")
    col.label(text="The view moves with Alt + mouse and the wheel", icon='INFO')


# -----------------------------------------------------------------------------

classes = (
    M3D_OT_bake_guard,
    M3D_OT_bake_cancel,
    M3D_OT_bake_report,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.object_bake_complete.append(_on_complete)
    bpy.app.handlers.object_bake_cancel.append(_on_cancel)


def unregister():
    bpy.app.handlers.object_bake_cancel.remove(_on_cancel)
    bpy.app.handlers.object_bake_complete.remove(_on_complete)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
