# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The view of Bake Mesh Maps for Maelstrom3D (Texture workspace, the Bake page): what the 3D view shows while the dock is on the Bake
page, so that the cage can be judged before an hour of baking.

The high polys of the groups that are baked are shown (the ones that are parked, see m3d_pair.py, are shown for as long) as a
see-through blue mesh: each gets a temporary material in its object slots (`slot.link = 'OBJECT'`; the mesh and its materials are not
touched), and goes back when the dock leaves the Bake page, when the file is saved, undone or loaded. What an object had before is
kept in a custom property of the object itself, so that an undo can never leave the blue behind.

The cage is the low poly pushed out by the group's Extrusion, drawn as an orange wire. Where a bake would go wrong it is red:
from every point of the low poly a ray goes along the normal as the bake sends it (from the extruded surface, inwards, as far as
the Max Ray Distance) and a point is a problem when the ray finds no high poly (a miss), or when the point is inside a high poly (the
high poly sticks out past the cage, so the ray starts inside it and the bake takes the inner wall). The check is done by a timer in
small slices, a moment after the last change, never while drawing; the draw handler only draws batches that the check made.
"""

import time

import bpy
import gpu
import numpy as np
from bpy.types import Operator, Panel
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import m3d_bakeq as Q
import m3d_pair
import m3d_texture as T
import m3d_workspace as W
from m3d_sculpt import mesh_of, reason, split_props

MATERIAL = "m3dViewHigh"
KEY = "m3d_view"          # custom property of an object the view changed: what it had before
CAGE_COLOR = (1.0, 0.5, 0.1, 1.0)
SLICE = 0.02              # seconds of the check that one timer call may take
CHUNK = 300               # rays between two looks at the clock
BIG_FACE = 3.0            # a face this many times bigger than the average one also sends a ray from its middle
MAX_FACES = 8_000_000     # high polys with more faces than this (all together) are not checked: a BVH of them takes too long

_view = {
    "on": False,          # the view is up
    "sig": None,          # what it was made for
    "mat": None,
    "dirty": 0.0,         # when the check was last asked for (0: it is not)
    "geo": set(),         # names of the high polys that changed their geometry (their BVH is made again)
    "touched": set(),     # names of the meshes of the groups: a change of them asks for a check
    "pause": 0.0,         # no following before this time (after an error)
    "writing": False,     # the view itself is changing objects (a material slot is no change of the geometry: the BVH stays)
    "bvh": {},            # high poly name -> BVHTree of its evaluated mesh (object space)
    "job": None,          # the check that is running (a generator, see check_steps)
    "result": {},         # low poly name -> Cage: what the draw handler draws
    "areas": None,        # problem areas found (None: not checked yet)
    "note": "",           # why there is no check
    "handles": [],        # draw handlers
}


class Cage:
    """What the check found for one low poly: the batches to draw (in the object space of the low poly), how many faces are bad and
    which (a bool for each face)."""
    def __init__(self, lines, tris, bad):
        self.lines, self.tris, self.bad = lines, tris, bad
        self.problems = int(bad.sum())


# -----------------------------------------------------------------------------
# What is shown

def in_bake_mode(context):
    """Does the dock of this workspace show the Bake page (and no bake is running)?"""
    ws = context.workspace
    return (ws is not None and W.workspace_kind(ws) == 'TEXTURE' and ws.m3d_page_right == "tex_bake" and mesh_of(context) is not None
            and not Q.running())


def targets(context):
    """[(group or "", low polys, high polys)] the Bake button would bake: the groups (and the meshes with a High Poly) of the texture
    sets that are ticked, else those of the active mesh."""
    sets = T.bake_checked(context)
    if not sets:
        ob = mesh_of(context)
        sets = [(ob.active_material, ob)]
    found = []
    for kind, unit in T.bake_units(sets):
        if kind == 'GROUP':
            lows, highs = m3d_pair.group_of(context, unit)
            found.append((unit, lows, highs))
        elif unit.m3d_bake.high is not None:
            found.append(("", [unit], [unit.m3d_bake.high]))
    return found


def settings_of(context, group, low):
    """(extrusion, max ray distance, custom cage object) a bake of this low poly would use."""
    import m3d_bakegroups as BG
    if group:
        entry = context.scene.m3d_bake_groups.get(group)
        if entry is not None:
            return entry.extrusion, entry.ray_distance, entry.cage if entry.cage is not None and entry.cage != low else None
    s = low.m3d_bake
    return s.extrusion, s.ray_distance, s.cage


def signature(context, found):
    tex = context.scene.m3d_tex
    return (tuple((g, tuple(o.name for o in lows), tuple(o.name for o in highs),
                   tuple(settings_of(context, g, lows[0]))[:2] + (getattr(settings_of(context, g, lows[0])[2], "name", ""),))
                  for g, lows, highs in found if lows),
            tex.view_hp, tex.view_cage, round(tex.view_opacity, 3), tuple(round(c, 3) for c in tex.view_problem))


# -----------------------------------------------------------------------------
# The blue high poly

def blue_material(context):
    """The one material of the see-through high polys (made on the first use, its opacity follows the setting)."""
    tex = context.scene.m3d_tex
    mat = bpy.data.materials.get(MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL)
        mat.use_nodes = True
        mat.surface_render_method = 'BLENDED'
        mat.use_backface_culling = False
        bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bsdf.inputs["Base Color"].default_value = (0.08, 0.3, 1.0, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.4
        bsdf.inputs["Emission Color"].default_value = (0.08, 0.3, 1.0, 1.0)   # (it stays blue in any light)
        bsdf.inputs["Emission Strength"].default_value = 1.0
    mat.diffuse_color = (0.08, 0.3, 1.0, tex.view_opacity)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Alpha"].default_value = tex.view_opacity
    return mat


def show_high(ob, mat):
    """Draw a high poly in `mat` through its object slots, and remember what it had (custom property KEY): its slots' links and
    object-level materials, the Transparency flag, whether a slot was added (a mesh without a material gets an empty one meanwhile),
    whether it was parked."""
    if KEY in ob:
        return
    record = {"transparent": bool(ob.show_transparent), "added": False, "parked": bool(ob.m3d_pair.parked and ob.hide_get()), "slots": []}
    if not ob.material_slots:
        ob.data.materials.append(None)
        record["added"] = True
    for slot in ob.material_slots:
        link = slot.link
        slot.link = 'OBJECT'
        record["slots"].append([link, slot.material.name if slot.material else ""])
        slot.material = mat
    ob.show_transparent = True
    ob[KEY] = record
    if record["parked"]:
        m3d_pair.restore(ob)


def hide_high(ob, repark=True):
    """Give a high poly back as it was."""
    record = ob.get(KEY)
    if record is None:
        return
    for slot, (link, latent) in zip(ob.material_slots, record["slots"]):
        slot.link = 'OBJECT'
        slot.material = bpy.data.materials.get(latent) if latent else None
        slot.link = link
    if record["added"] and len(ob.data.materials) == 1:
        ob.data.materials.clear()   # (the mesh had no slot: the one the view added goes)
    ob.show_transparent = bool(record["transparent"])
    parked = bool(record["parked"])
    del ob[KEY]
    if parked and repark and not ob.hide_get():
        m3d_pair.park(ob)


def repair(context):
    """Every object that the view changed goes back (an undo, a load or a save may have left the blue on objects the view does not know
    any more), and the material is removed."""
    _view["writing"] = True
    try:
        with m3d_pair.quiet(context):
            for ob in bpy.data.objects:
                if KEY in ob:
                    hide_high(ob, repark=W.workspace_kind(context.workspace) != 'SCULPT')   # (Sculpt shows high polys: leave them there)
    finally:
        _view["writing"] = False
    mat = bpy.data.materials.get(MATERIAL)
    if mat is not None and mat.users == 0:
        bpy.data.materials.remove(mat)


# -----------------------------------------------------------------------------
# Entering and leaving

def leave(context):
    """The view goes away: the high polys are as they were, the cage is not drawn, a check that runs is dropped."""
    if _view["on"] or any(KEY in ob for ob in bpy.data.objects):
        repair(context)
    stop_check()
    for handle in _view["handles"]:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _view.update(on=False, sig=None, handles=[], result={}, areas=None, note="", dirty=0.0, bvh={}, geo=set(), touched=set())
    redraw(context)


def redraw(context):
    wm = context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in {'VIEW_3D', 'PROPERTIES'}:
                area.tag_redraw()


def touch():
    """A setting of the view changed (or a check is asked for): the next tick puts the view right."""
    _view["sig"] = None


def enter(context, found):
    """Show what `found` (targets) says, as it is now."""
    tex = context.scene.m3d_tex
    highs = {h.name: h for _g, _lows, hs in found for h in hs if h.type == 'MESH'}
    _view["writing"] = True
    try:
        with m3d_pair.quiet(context):
            for ob in [o for o in bpy.data.objects if KEY in o and (o.name not in highs or not tex.view_hp)]:
                hide_high(ob)
            if tex.view_hp:
                mat = blue_material(context)
                for ob in highs.values():
                    show_high(ob, mat)
            elif bpy.data.materials.get(MATERIAL) is not None and bpy.data.materials[MATERIAL].users == 0:
                bpy.data.materials.remove(bpy.data.materials[MATERIAL])
    finally:
        _view["writing"] = False
    _view["touched"] = {o.name for _g, lows, hs in found for o in (*lows, *hs)}
    if not _view["handles"]:
        _view["handles"] = [bpy.types.SpaceView3D.draw_handler_add(_draw_cage, (), 'WINDOW', 'POST_VIEW'),
                            bpy.types.SpaceView3D.draw_handler_add(_draw_note, (), 'WINDOW', 'POST_PIXEL')]
    _view["on"] = True
    ask_check()
    redraw(context)


def follow(wm):
    """Timer (m3d_texture.follow, four times a second): the view follows the page of the dock and the setup of the groups. A bug in it must
    not stop the timer (the other followers share it): the error is printed and the view waits some seconds."""
    if time.monotonic() < _view["pause"]:
        return
    try:
        _follow(wm)
    except Exception:
        import traceback
        traceback.print_exc()
        _view["pause"] = time.monotonic() + 5.0


def _follow(wm):
    if not wm.windows:
        return
    context = bpy.context
    if not in_bake_mode(context):
        if _view["on"]:
            leave(context)
        return
    found = targets(context)
    sig = signature(context, found)
    if sig != _view["sig"] or not _view["on"]:
        _view["sig"] = sig
        enter(context, found)
    if _view["job"] is None and _view["dirty"] and time.monotonic() - _view["dirty"] > 0.4:
        _view["dirty"] = 0.0
        start_check(context, found)


def ask_check():
    """Something the check depends on changed: it starts again a moment after the last change."""
    _view["dirty"] = time.monotonic()
    if _view["job"] is not None:
        stop_check()
        _view["areas"] = None


# -----------------------------------------------------------------------------
# The check

def stamp_ok(ob):
    return ob.name not in _view["geo"]


def hp_bvh(context, ob):
    """BVH of the evaluated mesh of a high poly in its own space (made again after its geometry changed)."""
    cached = _view["bvh"].get(ob.name)
    if cached is not None and stamp_ok(ob):
        return cached
    _view["geo"].discard(ob.name)
    bvh = BVHTree.FromObject(ob, context.evaluated_depsgraph_get())
    _view["bvh"][ob.name] = bvh
    return bvh


def low_samples(context, low, extrusion):
    """The points a bake of `low` sends rays from, as numpy arrays: world positions of the extruded surface, the world directions of the
    rays (inwards), and for the face colors the loop and face of each, plus the cage's wire and triangles in object space. The extrusion is
    in object space (the bake does so), a point is sent from the corner normal of each loop, and from the middle of the faces that
    are big."""
    ev = low.evaluated_get(context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
        co = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        vert = np.empty(nl, np.int32)
        me.loops.foreach_get("vertex_index", vert)
        normals = np.empty(nl * 3, np.float32)
        me.corner_normals.foreach_get("vector", normals)
        normals = normals.reshape(-1, 3)
        start, total = np.empty(npoly, np.int32), np.empty(npoly, np.int32)
        me.polygons.foreach_get("loop_start", start)
        me.polygons.foreach_get("loop_total", total)
        area = np.empty(npoly, np.float32)
        me.polygons.foreach_get("area", area)
        center = np.empty(npoly * 3, np.float32)
        me.polygons.foreach_get("center", center)
        center = center.reshape(-1, 3)
        ntri = len(me.loop_triangles)
        tri_loops = np.empty(ntri * 3, np.int32)
        me.loop_triangles.foreach_get("loops", tri_loops)
        tri_loops = tri_loops.reshape(-1, 3)
        tri_poly = np.empty(ntri, np.int32)
        me.loop_triangles.foreach_get("polygon_index", tri_poly)
    finally:
        ev.to_mesh_clear()
    face_of = np.repeat(np.arange(npoly, dtype=np.int32), total)
    corner = co[vert] + normals * extrusion   # the cage, one point for each corner
    # one sample for each corner (the ones that are the same are one), and one for the middle of each big face
    keys = np.round(np.concatenate([co[vert], normals], axis=1), 5)
    _unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    big = np.flatnonzero(area > BIG_FACE * max(float(area.mean()), 1e-12)) if npoly else np.empty(0, np.int64)
    big = big[:20000]
    face_normal = np.zeros((npoly, 3), np.float32)
    np.add.at(face_normal, face_of, normals)
    face_normal /= np.maximum(np.linalg.norm(face_normal, axis=1, keepdims=True), 1e-12)
    local_origin = np.concatenate([corner[first], center[big] + face_normal[big] * extrusion])
    local_normal = np.concatenate([normals[first], face_normal[big]])
    m = np.array(ev.matrix_world, np.float32)
    origin = local_origin @ m[:3, :3].T + m[:3, 3]
    inv_t = np.linalg.inv(m[:3, :3]).T
    direction = -(local_normal @ inv_t.T)
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-12)
    # which sample belongs to which corner / face (for the colors)
    return dict(origin=origin, direction=direction, count_corners=len(first), corner_sample=inverse, big=big, face_of=face_of,
                start=start, total=total, tri_loops=tri_loops, tri_poly=tri_poly, corner=corner, vert=vert, npoly=npoly)


def cast(origin, direction, highs, limit):
    """0 for a point that is fine, 1 for a miss, 2 for a point inside a high poly, for the rays `origin` / `direction` (world space).
    Done like the bake does: the nearest hit of the ray along the direction counts when it is closer than `limit` (0: no limit).
    `highs`: [(bvh, matrix, inverse)]. A hit on a back face means the ray started inside."""
    status = np.zeros(len(origin), np.uint8)
    for i in range(len(origin)):
        o, d = Vector(origin[i]), Vector(direction[i])
        best, best_back, inside = None, False, False
        for bvh, mat, inv in highs:
            lo, ld = inv @ o, inv.to_3x3() @ d
            ld.normalize()
            loc, nrm, idx, _dist = bvh.ray_cast(lo, ld)
            if idx is not None:
                dist = (mat @ loc - o).length
                if best is None or dist < best:
                    best, best_back = dist, nrm.dot(ld) > 0.0
            out = bvh.ray_cast(lo, -ld)   # (outwards: a back face first means the start is inside)
            if out[2] is not None and out[1].dot(-ld) > 0.0:
                inside = True
        if inside or best_back:
            status[i] = 2
        elif best is None or (limit > 0.0 and best >= limit):
            status[i] = 1
    return status


def check_steps(context, entries):
    """The check as a generator that yields now and then, so that a timer can run it in slices. `entries`: [(low, highs, extrusion,
    ray distance)]. Returns {low name: Cage}, the number of problem areas."""
    result, areas = {}, 0
    for low, highs, extrusion, limit in entries:
        yield
        bvhs = []
        for h in highs:
            bvhs.append((hp_bvh(context, h), h.matrix_world.copy(), h.matrix_world.inverted()))
            yield
        s = low_samples(context, low, extrusion)
        yield
        n = len(s["origin"])
        status = np.zeros(n, np.uint8)
        for a in range(0, n, CHUNK):
            status[a:a + CHUNK] = cast(s["origin"][a:a + CHUNK], s["direction"][a:a + CHUNK], bvhs, limit)
            yield
        flagged_corner = status[:s["count_corners"]][s["corner_sample"]] > 0   # for each loop
        face_bad = np.zeros(s["npoly"], bool)
        np.logical_or.at(face_bad, s["face_of"], flagged_corner)
        face_bad[s["big"]] |= status[s["count_corners"]:] > 0
        areas += count_areas(face_bad, s)
        result[low.name] = make_cage(face_bad, s)
        yield
    return result, areas


def count_areas(face_bad, s):
    """How many separate patches the bad faces make (faces that share a corner belong together)."""
    bad = np.flatnonzero(face_bad)
    parent = {int(f): int(f) for f in bad}

    def find(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f
    owner = {}
    for f in bad:
        for loop in range(s["start"][f], s["start"][f] + s["total"][f]):
            v = int(s["vert"][loop])
            other = owner.setdefault(v, int(f))
            a, b = find(int(f)), find(other)
            if a != b:
                parent[a] = b
    return len({find(f) for f in parent})


def make_cage(face_bad, s):
    """The batches of one low poly: the wire of the cage (orange) and the triangles of the bad faces (red). Background mode has no GPU:
    the count of the bad faces is all there is."""
    if bpy.app.background:
        return Cage(None, None, face_bad)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    start, total, corner = s["start"], s["total"], s["corner"]
    nxt = np.arange(len(corner)) + 1
    nxt[start + total - 1] = start
    lines = batch_for_shader(shader, 'LINES', {"pos": np.concatenate([corner[:, None, :], corner[nxt][:, None, :]], axis=1).reshape(-1, 3)})
    pick = face_bad[s["tri_poly"]]
    tris = batch_for_shader(shader, 'TRIS', {"pos": corner[s["tri_loops"][pick]].reshape(-1, 3)}) if pick.any() else None
    return Cage(lines, tris, face_bad)


def start_check(context, found):
    """Begin the check of every group (a timer runs it)."""
    entries = []
    faces = 0
    for group, lows, highs in found:
        if not lows or not highs:
            continue
        faces += sum(m3d_pair.face_count(h) for h in highs)
        for low in lows:
            extrusion, limit, _cage = settings_of(context, group, low)
            entries.append((low, highs, extrusion, limit))
    if not entries:
        _view.update(result={}, areas=None, note="No high poly to check against")
    elif faces > MAX_FACES:
        _view.update(result={}, areas=None, note="The high polys (%s faces) are too big to check" % m3d_pair.format_count(faces))
    else:
        _view.update(note="", job=check_steps(context, entries))
        if not bpy.app.timers.is_registered(_check_tick):
            bpy.app.timers.register(_check_tick, first_interval=0.0)
    redraw(context)


def stop_check():
    job = _view["job"]
    if job is not None:
        _view["job"] = None
        job.close()


def _check_tick():
    """Timer: a slice of the check."""
    job = _view["job"]
    if job is None:
        return None
    deadline = time.perf_counter() + SLICE
    try:
        while time.perf_counter() < deadline:
            next(job)
    except StopIteration as done:
        _view["job"] = None
        _view["result"], _view["areas"] = done.value
        redraw(bpy.context)
        return None
    except Exception:   # (a timer that raises is gone; the view goes on without a check)
        import traceback
        traceback.print_exc()
        _view.update(job=None, areas=None, note="The cage check failed")
        return None
    return 0.0


def status_text():
    """(text, problems) of the cage check for the Bake page."""
    if not _view["on"]:
        return "", False
    if _view["note"]:
        return "Cage: " + _view["note"], False
    areas = _view["areas"]
    if areas is None:
        return "Cage: checking...", False
    if areas == 0:
        return "Cage: no problems found", False
    return "Cage: %d problem area%s" % (areas, "" if areas == 1 else "s"), True


# -----------------------------------------------------------------------------
# Drawing (batches that the check made: no work for the mesh)

def _draw_cage():
    """POST_VIEW: the wire of the cage, and its bad faces in red."""
    context = bpy.context
    if not _view["on"] or not _view["result"] or not context.scene.m3d_tex.view_cage:
        return
    color = tuple(context.scene.m3d_tex.view_problem)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.line_width_set(1.5)
    for name, cage in _view["result"].items():
        low = bpy.data.objects.get(name)
        if low is None:
            continue
        gpu.matrix.push()
        gpu.matrix.multiply_matrix(low.matrix_world)
        if cage.lines is None:
            gpu.matrix.pop()
            continue
        shader.bind()
        if cage.tris is not None:
            shader.uniform_float("color", (*color, 0.6))
            cage.tris.draw(shader)
        shader.uniform_float("color", CAGE_COLOR)
        cage.lines.draw(shader)
        gpu.matrix.pop()
    gpu.state.line_width_set(1.0)
    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _draw_note():
    """POST_PIXEL: the result of the check in the corner of the 3D view."""
    import blf
    text, bad = status_text()
    region = bpy.context.region
    if not text or region is None:
        return
    blf.size(0, 15)
    if bad:
        blf.color(0, 1.0, 0.35, 0.3, 1.0)
    else:
        blf.color(0, 0.85, 0.85, 0.85, 1.0)
    blf.position(0, 16, region.height - 52, 0)
    blf.draw(0, text)


# -----------------------------------------------------------------------------
# The Bake page

class PROPERTIES_PT_m3d_tx_bake_view(T._Bake, Panel):
    bl_label = "Visualization"
    bl_order = 15

    def draw(self, context):
        layout = self.layout
        tex = context.scene.m3d_tex
        split_props(layout)
        layout.prop(tex, "view_hp")
        sub = layout.column()
        sub.active = tex.view_hp
        sub.prop(tex, "view_opacity", slider=True)
        layout.prop(tex, "view_cage")
        sub = layout.column()
        sub.active = tex.view_cage
        sub.prop(tex, "view_problem")
        text, bad = status_text()
        if text:
            row = layout.row()
            row.alert = bad
            row.label(text=text, icon='ERROR' if bad else 'CHECKMARK', translate=False)
            row.operator("m3d.bake_view_check", text="", icon='FILE_REFRESH')
        reason(layout, "Red: the rays find no high poly there, or start inside it")


class M3D_OT_bake_view_check(Operator):
    """Check the cage again: from every point of the low polys a ray goes in along the normal as the bake sends it, and the points
    where it finds no high poly or starts inside one are red"""
    bl_idname = "m3d.bake_view_check"
    bl_label = "Check Cage"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, _context):
        return _view["on"]

    def execute(self, context):
        _view["geo"] |= set(_view["touched"])
        ask_check()
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Handlers

@bpy.app.handlers.persistent
def _depsgraph_update(_scene, depsgraph):
    """A mesh of the groups changed its geometry or moved: the cage is checked again a moment later (names only: nothing per vertex)."""
    if not _view["on"] or _view["writing"]:
        return
    touched = _view["touched"]
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Object) and update.id.name in touched and (update.is_updated_geometry or update.is_updated_transform):
            if update.is_updated_geometry:
                _view["geo"].add(update.id.name)
            ask_check()
            return


@bpy.app.handlers.persistent
def _save_pre(*_args):
    """The file never has the blue: it is put right before the file is written, and made again by the timer after."""
    leave(bpy.context)


@bpy.app.handlers.persistent
def _load_post(*_args):
    stop_check()
    for handle in _view["handles"]:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _view.update(on=False, sig=None, handles=[], result={}, areas=None, note="", dirty=0.0, bvh={}, geo=set(), touched=set(), job=None)
    repair(bpy.context)   # (an autosave or a crash file may hold the blue)


@bpy.app.handlers.persistent
def _undo_post(*_args):
    """An undo or redo brings the objects as they were at that step: the blue that it holds goes, the view is made again."""
    context = bpy.context
    repair(context)
    _view["sig"] = None


classes = (
    PROPERTIES_PT_m3d_tx_bake_view,
    M3D_OT_bake_view_check,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)
    bpy.app.handlers.save_pre.append(_save_pre)
    bpy.app.handlers.load_post.append(_load_post)
    bpy.app.handlers.undo_post.append(_undo_post)
    bpy.app.handlers.redo_post.append(_undo_post)


def unregister():
    bpy.app.handlers.redo_post.remove(_undo_post)
    bpy.app.handlers.undo_post.remove(_undo_post)
    bpy.app.handlers.load_post.remove(_load_post)
    bpy.app.handlers.save_pre.remove(_save_pre)
    bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
