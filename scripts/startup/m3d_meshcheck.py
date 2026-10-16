# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Mesh checks for Maelstrom3D: the Low Poly Check (the Check tab of the UV workspace, and above the Bake button of Bake Mesh Maps),
Harden UV Borders (Mesh Display menu, Cut and Sew) and the Cleanup dialog (Mesh > Cleanup...).

Every check is numpy over the mesh's arrays, O(n) apart from the UV raster of the overlap test (a loop over the triangles bigger
than a pixel), and runs on demand: the panels show what the last check found, made again by themselves only for a small mesh out
of Edit Mode (its cache key is cheap: counts and sums), otherwise when Check is pressed (in Edit Mode the edit mesh is written
back first). A UV check reads the first UV map: the one painting, baking and export use. A fix is one undo step and checks again.

UV shells are the faces joined by edges whose two sides have the same UVs (a label propagation over those edges with pointer
jumping). Overlaps are found by drawing the shells that lie inside the 0-1 square into a grid of the texture's size (at most 1024):
a pixel two shells cover is an overlap. Shells moved whole tiles away (Move Overlaps One Tile) read the same pixels and are left
out of the test, as a bake leaves them out.
"""

import types
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.props import EnumProperty
from bpy.types import Operator

from m3d_sculpt import mesh_of, reason

AUTO_FACES = 50000   # a mesh up to this many faces is checked again by the panels themselves when its key changes
EPS = 1e-5           # UVs closer than this are the same


# -----------------------------------------------------------------------------
# Arrays

def _get(coll, attr, n, dtype, width=1):
    a = np.empty(n * width, dtype)
    if n:
        coll.foreach_get(attr, a)
    return a.reshape(n, width) if width > 1 else a


def _flag(me, name, n):
    """A boolean attribute of the mesh (sharp_edge, sharp_face) as an array; all False when it has none."""
    a = me.attributes.get(name)
    out = np.zeros(n, bool)
    if a is not None and a.data_type == 'BOOLEAN' and n:
        a.data.foreach_get("value", out)
    return out


def first_uv(me):
    """(n loops, 2) of the mesh's first UV map, or None without one."""
    if not me.uv_layers:
        return None
    return _get(me.uv_layers[0].uv, "vector", len(me.loops), np.float32, 2)


def arrays(me):
    """The mesh's corners, faces and edges as numpy arrays (Object Mode data: write an edit mesh back first)."""
    nl, nf, ne, nv = len(me.loops), len(me.polygons), len(me.edges), len(me.vertices)
    d = types.SimpleNamespace(nl=nl, nf=nf, ne=ne, nv=nv)
    d.vert = _get(me.loops, "vertex_index", nl, np.int32)
    d.edge = _get(me.loops, "edge_index", nl, np.int32)
    d.start = _get(me.polygons, "loop_start", nf, np.int32)
    d.total = _get(me.polygons, "loop_total", nf, np.int32)
    d.face = np.repeat(np.arange(nf, dtype=np.int32), d.total)
    i = np.arange(nl, dtype=np.int32)
    end = (d.start + d.total)[d.face]
    d.next = np.where(i + 1 == end, d.start[d.face], i + 1)
    d.prev = np.where(i == d.start[d.face], end - 1, i - 1)
    d.edge_faces = np.bincount(d.edge, minlength=ne) if nl else np.zeros(ne, np.int64)
    d.uv = first_uv(me)
    return d


def uv_pairs(d):
    """(a, b, joined): the two corners of every edge with two faces, and whether the UVs on both sides of it are the same."""
    order = np.argsort(d.edge, kind='stable')
    o = order[d.edge_faces[d.edge[order]] == 2]
    a, b = o[0::2], o[1::2]
    if d.uv is None:
        return a, b, np.zeros(len(a), bool)
    same = (d.vert[a] == d.vert[b])[:, None]   # (the faces run the same way along the edge: flipped normals)
    ua, ua2 = d.uv[a], d.uv[d.next[a]]
    ub, ub2 = np.where(same, d.uv[b], d.uv[d.next[b]]), np.where(same, d.uv[d.next[b]], d.uv[b])
    return a, b, (np.abs(ua - ub).max(axis=1) < EPS) & (np.abs(ua2 - ub2).max(axis=1) < EPS)


def uv_borders(d, pairs=None):
    """(n edges) bool: the edges on a UV border (the edge of a shell: a seam, an open edge, or an edge of three faces or more)."""
    a, _b, joined = uv_pairs(d) if pairs is None else pairs
    border = d.edge_faces > 0
    border[d.edge[a[joined]]] = False
    return border


def components(n, a, b):
    """Labels of the groups of n items joined by the pairs (a, b): union by hooking roots, then pointer jumping."""
    label = np.arange(n)
    while len(a):
        la, lb = label[a], label[b]
        apart = la != lb
        if not apart.any():
            break
        la, lb = la[apart], lb[apart]
        np.minimum.at(label, np.maximum(la, lb), np.minimum(la, lb))
        while True:
            jumped = label[label]
            if (jumped == label).all():
                break
            label = jumped
    return label


def shells(d, pairs=None):
    """(shell of each face, number of shells)."""
    a, b, joined = uv_pairs(d) if pairs is None else pairs
    label = components(d.nf, d.face[a[joined]], d.face[b[joined]])
    _u, shell = np.unique(label, return_inverse=True)
    return shell.ravel(), len(_u)


def triangle_pixels(t, size):
    """The pixels (of a size x size grid, or width x height for a pair; rows from the bottom) whose centres are inside the triangle
    `t` (3 x 2, in pixels): (y0, x0, inside, a, b), `a` and `b` the barycentric weights of corners 0 and 1 on the box from (y0, x0);
    None when it covers none."""
    x0, y0 = np.maximum(np.floor(t.min(axis=0)), 0).astype(int)
    x1, y1 = np.minimum(np.ceil(t.max(axis=0)), (size, size) if np.isscalar(size) else size).astype(int)
    if x1 <= x0 or y1 <= y0:
        return None
    d = (t[1, 1] - t[2, 1]) * (t[0, 0] - t[2, 0]) + (t[2, 0] - t[1, 0]) * (t[0, 1] - t[2, 1])
    if abs(d) < 1e-9:
        return None
    px = np.arange(x0, x1, dtype=np.float32) + 0.5
    py = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None]
    a = ((t[1, 1] - t[2, 1]) * (px - t[2, 0]) + (t[2, 0] - t[1, 0]) * (py - t[2, 1])) / d
    b = ((t[2, 1] - t[0, 1]) * (px - t[2, 0]) + (t[0, 0] - t[2, 0]) * (py - t[2, 1])) / d
    inside = (a >= -1e-4) & (b >= -1e-4) & (1.0 - a - b >= -1e-4)
    return y0, x0, inside, a, b


def loop_triangles(me):
    """(n, 3) corners and (n) faces of the mesh's triangles."""
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    return _get(me.loop_triangles, "loops", n, np.int32, 3).reshape(n, 3), _get(me.loop_triangles, "polygon_index", n, np.int32)


# -----------------------------------------------------------------------------
# Low Poly Check

def grid_size(context, ob):
    """Side of the overlap test's grid: the texture set's size (one pixel of the texture), at most 1024."""
    import m3d_layers as L
    mat = ob.active_material
    size = (L.stack_size(mat) or mat.m3d_size if mat is not None else 0) or 1024
    return int(min(max(size, 64), 1024))


def overlaps(d, shell, count, size):
    """(per shell: overlaps another shell, tiles to move it so it does not), for the shells inside the 0-1 square."""
    n = max(count, 1)
    tris, tri_face = d.tris
    hit, move = np.zeros(n, bool), np.zeros(n, np.int32)
    if d.uv is None or not len(tris):
        return hit, move
    lo, hi = np.full((n, 2), np.inf, np.float32), np.full((n, 2), -np.inf, np.float32)
    np.minimum.at(lo, shell[d.face], d.uv)
    np.maximum.at(hi, shell[d.face], d.uv)
    inside = ((lo > -EPS) & (hi < 1.0 + EPS)).all(axis=1)
    keep = inside[shell[tri_face]]
    t, owner = d.uv[tris[keep]] * size, shell[tri_face[keep]]
    small = ((t.max(axis=1) - t.min(axis=1)) <= 1.0).all(axis=1)
    c = np.clip(t[small].mean(axis=1).astype(np.int64), 0, size - 1)   # (a triangle of a pixel or less: its centre)
    pix, own = [c[:, 1] * size + c[:, 0]], [owner[small]]
    for i in np.nonzero(~small)[0]:
        got = triangle_pixels(t[i], size)
        if got is not None:
            y0, x0, cover = got[:3]
            ys, xs = np.nonzero(cover)
            pix.append((ys + y0).astype(np.int64) * size + xs + x0)
            own.append(np.full(len(ys), owner[i]))
    key = np.unique(np.concatenate(pix) * n + np.concatenate(own))   # (pixel, shell) once each, by pixel then shell
    p, s = key // n, key % n
    first = np.r_[True, p[1:] != p[:-1]] if len(p) else np.zeros(0, bool)
    rank = np.arange(len(p)) - np.maximum.accumulate(np.where(first, np.arange(len(p)), 0))
    shared = np.isin(p, p[rank > 0])
    hit[s[shared]] = True
    np.maximum.at(move, s, rank)   # (the first shell on a pixel stays; the second moves one tile, the third two)
    return hit, move


def analyse(ob, size=1024):
    """Everything the Low Poly Check reports, with the faces and edges each problem is about."""
    me = ob.data
    d = arrays(me)
    d.tris = loop_triangles(me)
    pairs = uv_pairs(d)
    border = uv_borders(d, pairs)
    shell, count = shells(d, pairs) if d.uv is not None else (np.zeros(d.nf, np.int64), 0)
    r = types.SimpleNamespace(faces=d.nf, shells=count, uv=d.uv is not None)
    if d.uv is not None and d.nf:
        cross = d.uv[:, 0] * d.uv[d.next, 1] - d.uv[d.next, 0] * d.uv[:, 1]
        area = np.add.reduceat(cross, d.start) if d.nl else np.zeros(d.nf)
        shell_area = np.bincount(shell, weights=area, minlength=count)
        r.mirrored = shell_area < 0
        lo, hi = np.full((count, 2), np.inf), np.full((count, 2), -np.inf)
        np.minimum.at(lo, shell[d.face], d.uv)
        np.maximum.at(hi, shell[d.face], d.uv)
        r.outside = (np.floor(lo + EPS) != np.floor(hi - EPS)).any(axis=1)   # (across a tile border: part of it is not in 0-1)
        r.overlap, r.move = overlaps(d, shell, count, size)
    else:
        r.mirrored = r.outside = r.overlap = np.zeros(count, bool)
        r.move = np.zeros(count, np.int32)
    r.shell = shell
    r.flat = _flag(me, "sharp_face", d.nf)
    sharp = _flag(me, "sharp_edge", d.ne)
    r.hard = sharp & ~border & (d.edge_faces == 2) if d.uv is not None else np.zeros(d.ne, bool)
    r.border = border
    r.negative = ob.matrix_world.determinant() < 0
    r.triangulated = triangulate_mod(ob) is not None
    r.ngons = d.total > 3
    r.d = d
    return r


def triangulate_mod(ob):
    return next((m for m in ob.modifiers if m.type == 'TRIANGULATE' and m.show_render), None)


# (id, label, what Select picks, fix id, fix label): one line each in the order the panel shows them
LOWPOLY = (
    ('OVERLAP', "Overlapping shells", 'FACE', 'MOVE', "Move Overlaps One Tile"),
    ('MIRRORED', "Mirrored shells", 'FACE', None, ""),
    ('OUTSIDE', "Shells outside 0-1", 'FACE', None, ""),
    ('FLAT', "Flat shaded faces", 'FACE', 'SMOOTH', "Shade Smooth"),
    ('HARD', "Hard edges not on UV borders", 'EDGE', 'HARDEN', "Harden UV Borders"),
    ('SCALE', "Negative scale", None, 'FREEZE', "Freeze Scale"),
    ('UNTRI', "Faces not triangulated", 'FACE', 'TRIANGULATE', "Triangulate"),
)


def counts(r):
    """{problem id: how many} of an analysis."""
    return {'OVERLAP': int(r.overlap.sum()), 'MIRRORED': int(r.mirrored.sum()), 'OUTSIDE': int(r.outside.sum()),
            'FLAT': int(r.flat.sum()), 'HARD': int(r.hard.sum()), 'SCALE': int(r.negative),
            'UNTRI': 0 if r.triangulated else int(r.ngons.sum())}


def picks(r, problem):
    """The faces (or edges) Select picks for a problem: (domain, mask)."""
    if problem in {'OVERLAP', 'MIRRORED', 'OUTSIDE'}:
        return 'FACE', getattr(r, problem.lower())[r.shell] if len(r.shell) else np.zeros(0, bool)
    if problem == 'FLAT':
        return 'FACE', r.flat
    if problem == 'HARD':
        return 'EDGE', r.hard
    if problem == 'UNTRI':
        return 'FACE', r.ngons
    return None, None


_results = {}   # mesh object name -> (cache key, counts, shells, grid size)


def cache_key(ob):
    """What the cached result goes by: the counts of the mesh, and for a small mesh also sums of its first UV map and its hard
    edges / flat faces (cheap; a big mesh keeps its result until Check is pressed again). In Edit Mode the mesh data is the one
    from before Edit Mode: Check writes the edit mesh back."""
    me = ob.data
    key = [len(me.vertices), len(me.edges), len(me.polygons), len(me.loops), len(me.uv_layers), ob.matrix_world.determinant() < 0,
           triangulate_mod(ob) is not None]
    if len(me.polygons) <= AUTO_FACES and ob.mode != 'EDIT':
        uv = first_uv(me)
        key += [round(float(uv.sum(dtype=np.float64)), 4) if uv is not None else 0.0,
                round(float(np.abs(uv).sum(dtype=np.float64)), 4) if uv is not None else 0.0,
                int(_flag(me, "sharp_edge", len(me.edges)).sum()), int(_flag(me, "sharp_face", len(me.polygons)).sum())]
    return tuple(key)


def check(context, ob):
    """Run the Low Poly Check on `ob` (an edit mesh is written back first: Object Mode for a moment) and keep the result. Returns
    the analysis."""
    size = grid_size(context, ob)
    with object_data(context, ob):
        r = analyse(ob, size)
    _results[ob.name] = (cache_key(ob), counts(r), r.shells, size)
    return r


def result(context, ob):
    """(counts, shells, up to date) of the last check of `ob`, None before the first; a small mesh out of Edit Mode is checked
    here when it changed (a panel may read but not write: this only reads the mesh)."""
    key, got = cache_key(ob), _results.get(ob.name)
    if (got is None or got[0] != key) and ob.mode != 'EDIT' and len(ob.data.polygons) <= AUTO_FACES:
        check(context, ob)
        got = _results[ob.name]
    if got is None:
        return None
    return got[1], got[2], got[0] == key


def draw_lowpoly(layout, context, ob, compact=False):
    """The Low Poly Check: a line for each problem with its count, Select and its fix; Check runs it again. `compact` (the Bake
    page): only the problems. A dock narrower than a line puts the short names of the fixes there, a very narrow one the buttons
    on a line of their own."""
    region = getattr(context, "region", None)
    width = region.width / (context.preferences.system.ui_scale or 1.0) if region is not None and region.width else 400
    narrow, tiny = width < 440, width < 300
    got = result(context, ob)
    row = layout.row(align=True)
    if got is None:
        row.label(text="Not checked yet", icon='QUESTION')
    else:
        found, count, fresh = got
        problems = [p for p in LOWPOLY if found[p[0]]]
        if not problems:
            row.label(text="No problems: ready to bake" if fresh else "No problems at the last check", icon='CHECKMARK')
        else:
            row.label(text="%d problem%s%s" % (len(problems), "s" if len(problems) > 1 else "",
                                                "" if fresh else " at the last check"), icon='ERROR')
    sub = row.row(align=True)
    sub.ui_units_x = 1.5 if tiny else 4
    sub.operator("m3d.lowpoly_check", text="" if tiny else "Check" if got is None else "Check Again", icon='FILE_REFRESH')
    if got is None:
        if not compact:
            reason(layout, "Overlaps, mirrored shells, shading, hard edges, scale and triangles: what spoils a bake")
        return
    col = layout.column(align=True)
    for pid, label, domain, fix, fix_label in LOWPOLY:
        n = found[pid]
        if not n and compact:
            continue
        line = col.row(align=True)
        text = label if pid == 'SCALE' else "%s: %d" % (label, n)
        line.label(text=text if n else "%s: none" % label, icon='ERROR' if n else 'CHECKMARK')
        if not n:
            continue
        if tiny:   # (the buttons under the line, indented)
            line = col.row(align=True)
            line.separator(factor=2.0)
        if domain is not None:
            line.operator("m3d.mesh_check_select", text="Select" if tiny else "", icon='RESTRICT_SELECT_OFF').problem = pid
        if fix is not None:
            sub = line.row(align=True)
            if not tiny:
                sub.ui_units_x = 6.5
            sub.operator("m3d.mesh_check_fix", text=FIX_SHORT.get(fix, fix_label) if narrow else fix_label).fix = fix
    if not compact:
        reason(layout, "%d shells. UVs: the first UV map" % count)
    if any(found[p] for p in ('FLAT', 'HARD', 'UNTRI')):
        layout.operator("m3d.mesh_check_fix", text="Prepare for Baking", icon='CHECKMARK').fix = 'PREPARE'


# -----------------------------------------------------------------------------
# Cleanup (Mesh > Cleanup...)

def cleanup_analyse(ob):
    """Cleanup problems of the mesh `ob`: {id: mask} over faces, edges or vertices (CLEANUP says which)."""
    me = ob.data
    d = arrays(me)
    co = _get(me.vertices, "co", d.nv, np.float32, 3)
    normal = _get(me.polygons, "normal", d.nf, np.float32, 3)
    area = _get(me.polygons, "area", d.nf, np.float32)
    out = {'NGON': d.total > 4}
    p, pn, pp = co[d.vert], co[d.vert[d.next]], co[d.vert[d.prev]]
    e0, e1 = p - pp, pn - p
    turn = (np.cross(e0, e1) * normal[d.face]).sum(axis=1)
    bent = turn < -1e-6 * np.linalg.norm(e0, axis=1) * np.linalg.norm(e1, axis=1)
    concave = np.zeros(d.nf, bool)
    concave[d.face[bent]] = True
    out['CONCAVE'] = concave & (d.total > 3)
    ev = _get(me.edges, "vertices", d.ne, np.int32, 2)
    out['NONMANIFOLD'] = (d.edge_faces == 1) | (d.edge_faces > 2)
    out['OPEN'] = d.edge_faces == 1   # (what Fill Holes can close)
    v = d.vert.astype(np.int64) + 1   # (a face with the same corners as another, in any order: sums of powers of its vertices)
    keys = np.stack([d.total.astype(np.int64)] + [np.add.reduceat(v ** k, d.start) if d.nl else np.zeros(d.nf, np.int64)
                                                  for k in (1, 2, 3)], axis=1) if d.nf else np.zeros((0, 4), np.int64)
    _u, first, inverse, many = np.unique(keys, axis=0, return_index=True, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    out['LAMINA'] = many[inverse] > 1 if d.nf else np.zeros(0, bool)
    out['LAMINA_EXTRA'] = out['LAMINA'] & (first[inverse] != np.arange(d.nf))   # (all but one face of each pile: what Fix deletes)
    span = float(np.ptp(co, axis=0).max()) if d.nv else 0.0
    out['ZERO'] = area <= max(span * span * 1e-10, 1e-14)
    loose_v = np.bincount(ev.ravel(), minlength=d.nv) == 0 if d.ne else np.ones(d.nv, bool)
    out['LOOSE_V'], out['LOOSE_E'] = loose_v, d.edge_faces == 0
    out['LOOSE'] = loose_v.copy()   # (to select: the loose vertices and the vertices of the loose edges)
    out['LOOSE'][ev[out['LOOSE_E']].ravel()] = True
    return out


# (id, label, domain, fix label): one line each in the dialog
CLEANUP = (
    ('NGON', "N-gons (more than 4 sides)", 'FACE', "Triangulate"),
    ('CONCAVE', "Concave faces", 'FACE', "Split"),
    ('NONMANIFOLD', "Non-manifold edges (open or 3+ faces)", 'EDGE', "Fill Holes"),
    ('LAMINA', "Lamina faces (two faces on the same corners)", 'FACE', "Delete Extra"),
    ('ZERO', "Zero-area faces", 'FACE', "Dissolve"),
    ('LOOSE', "Loose vertices and edges", 'VERT', "Delete Loose"),
)


CLEANUP_IDS = {p[0]: p for p in CLEANUP}


def cleanup_counts(found):
    n = {pid: int(found[pid].sum()) for pid, *_r in CLEANUP if pid != 'LOOSE'}
    n['LOOSE'] = int(found['LOOSE_V'].sum() + found['LOOSE_E'].sum())
    return n


# -----------------------------------------------------------------------------
# Selecting and fixing

@contextmanager
def object_data(context, ob):
    """The mesh data of `ob` up to date and writable inside (Object Mode for a while when it is in Edit Mode); the mode after is the
    one before."""
    mode = ob.mode
    if mode == 'EDIT':
        bpy.ops.object.mode_set(mode='OBJECT')
    try:
        yield ob.data
    finally:
        if mode == 'EDIT' and ob.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')


def select_elements(context, ob, domain, mask):
    """Edit Mode on `ob` with exactly these faces / edges / vertices selected (in that select mode)."""
    me = ob.data
    with object_data(context, ob):
        d = arrays(me)
        ev = _get(me.edges, "vertices", d.ne, np.int32, 2)
        face, edge, vert = np.zeros(d.nf, bool), np.zeros(d.ne, bool), np.zeros(d.nv, bool)
        if domain == 'FACE':
            face[:] = mask
            on = face[d.face]
            edge[d.edge[on]] = vert[d.vert[on]] = True
        elif domain == 'EDGE':
            edge[:] = mask
            vert[ev[mask].ravel()] = True
        else:
            vert[:] = mask
            if len(mask) == d.nv and d.ne:
                edge[:] = vert[ev].all(axis=1)
        if d.nv:
            me.vertices.foreach_set("select", vert)
        if d.ne:
            me.edges.foreach_set("select", edge)
        if d.nf:
            me.polygons.foreach_set("select", face)
    if ob.mode != 'EDIT':
        with context.temp_override(active_object=ob, object=ob):
            bpy.ops.object.mode_set(mode='EDIT')
    context.tool_settings.mesh_select_mode = (domain == 'VERT', domain == 'EDGE', domain == 'FACE')


def harden_uv_borders(ob):
    """Smooth shading with the hard edges exactly on the UV borders of the first UV map (what a bake wants: the normal map then has
    no seams inside the shells). As Seams from Shells with Mark Sharp after Shade Smooth, for the whole mesh. Returns how many hard
    edges there are now (None without a UV map)."""
    me = ob.data
    if not me.uv_layers:
        return None
    border = uv_borders(arrays(me))
    me.shade_smooth()   # (every face smooth, the old hard edges cleared)
    attr = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
    attr.data.foreach_set("value", border)
    me.update()
    return int(border.sum())


def move_overlaps(ob, r):
    """Move the shells that overlap one before them whole tiles to the right (they read the same pixels; a bake leaves them out).
    Returns how many moved."""
    me = ob.data
    if not r.uv or not r.move.any():
        return 0
    uv = first_uv(me)
    uv[:, 0] += r.move[r.shell[r.d.face]]
    me.uv_layers[0].uv.foreach_set("vector", uv.ravel())
    me.update()
    return int((r.move > 0).sum())


def add_triangulate(ob):
    """A Triangulate modifier (keeping custom normals): the bake and the export see the same triangles; the quads stay editable."""
    mod = triangulate_mod(ob)
    if mod is None:
        mod = ob.modifiers.new("Triangulate", 'TRIANGULATE')
        mod.keep_custom_normals = True
    return mod


class M3D_OT_lowpoly_check(Operator):
    """Check the active mesh before baking: overlapping and mirrored shells, UVs outside 0-1, flat shading, hard edges inside
    shells, negative scale and faces that are not triangles"""
    bl_idname = "m3d.lowpoly_check"
    bl_label = "Low Poly Check"

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        found = counts(check(context, ob))
        n = sum(1 for v in found.values() if v)
        self.report({'INFO'}, "Low Poly Check: %s" % ("%d problems" % n if n else "no problems"))
        return {'FINISHED'}


PROBLEMS = [(p[0], p[1], "") for p in LOWPOLY] + [(p[0], p[1], "") for p in CLEANUP]


class M3D_OT_mesh_check_select(Operator):
    """Select what the check found (Edit Mode): the faces of the shells, the faces or the edges"""
    bl_idname = "m3d.mesh_check_select"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    problem: EnumProperty(items=PROBLEMS)

    @classmethod
    def description(cls, _context, props):
        return "Select the %s (Edit Mode)" % dict((p[0], p[1]) for p in PROBLEMS)[props.problem].lower()

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        if self.problem in CLEANUP_IDS:
            with object_data(context, ob):
                found = cleanup_analyse(ob)
            domain, mask = CLEANUP_IDS[self.problem][2], found[self.problem]
        else:
            domain, mask = picks(check(context, ob), self.problem)
            if domain is None:
                return {'CANCELLED'}
        select_elements(context, ob, domain, mask)
        self.report({'INFO'}, "Selected %d" % int(np.count_nonzero(mask)))
        return {'FINISHED'}


FIX_SHORT = {'MOVE': "Move Overlaps", 'HARDEN': "Harden Borders"}   # (the tooltip has the whole name)
FIXES = [(f[3], f[4], "") for f in LOWPOLY if f[3]] + [('PREPARE', "Prepare for Baking", "")] + \
        [("C_" + p[0], p[3], "") for p in CLEANUP]
FIX_TEXT = {
    'MOVE': "Move Overlaps One Tile: the shells that overlap others move whole tiles away. They read the same pixels, and the bake "
            "writes each pixel once",
    'SMOOTH': "Shade the mesh smooth (its hard edges stay)",
    'HARDEN': "Harden UV Borders: smooth shading with hard edges exactly on the UV borders, so the baked normal map has no seams "
              "inside the shells",
    'FREEZE': "Freeze the object's scale into the mesh: a negative scale turns the baked normals inside out",
    'TRIANGULATE': "Add a Triangulate modifier: the bake and the export use the same triangles (the quads stay editable)",
    'PREPARE': "Harden UV Borders and Triangulate: the shading and the triangles a bake wants",
    'C_NGON': "Triangulate the n-gons", 'C_CONCAVE': "Split the concave faces into convex ones",
    'C_NONMANIFOLD': "Fill the open holes", 'C_LAMINA': "Delete the extra faces of each pile, keeping one",
    'C_ZERO': "Dissolve the faces and edges of zero size", 'C_LOOSE': "Delete the vertices and edges without faces",
}


class M3D_OT_mesh_check_fix(Operator):
    """Fix what the check found"""
    bl_idname = "m3d.mesh_check_fix"
    bl_label = "Fix"
    bl_options = {'REGISTER', 'UNDO'}

    fix: EnumProperty(items=FIXES)

    @classmethod
    def description(cls, _context, props):
        return FIX_TEXT[props.fix]

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        fix = self.fix
        if fix.startswith("C_"):
            done = self.cleanup(context, ob, fix[2:])
        elif fix == 'FREEZE':
            done = self.freeze(context, ob)
        else:
            with object_data(context, ob):
                if fix == 'MOVE':
                    done = "%d shells moved" % move_overlaps(ob, analyse(ob, grid_size(context, ob)))
                elif fix == 'SMOOTH':
                    flat = ob.data.attributes.get("sharp_face")   # (every face smooth; the hard edges stay)
                    if flat is not None:
                        ob.data.attributes.remove(flat)
                    ob.data.update()
                    done = "Shaded smooth"
                else:
                    hard = harden_uv_borders(ob) if fix in {'HARDEN', 'PREPARE'} else 0
                    if hard is None:
                        self.report({'WARNING'}, "The mesh has no UV map")
                        return {'CANCELLED'}
                    if fix in {'TRIANGULATE', 'PREPARE'}:
                        add_triangulate(ob)
                    done = {'HARDEN': "%d hard edges on the UV borders" % hard, 'TRIANGULATE': "Triangulate modifier added",
                            'PREPARE': "%d hard edges on the UV borders, Triangulate modifier added" % hard}[fix]
        if done is None:
            return {'CANCELLED'}
        if fix.startswith("C_"):
            if not bpy.app.background:
                bpy.app.timers.register(_reopen_cleanup, first_interval=0.1)   # (the dialog shows the counts after the fix)
        else:
            check(context, ob)
        self.report({'INFO'}, done)
        return {'FINISHED'}

    def freeze(self, context, ob):
        mode = ob.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            with context.temp_override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return None
        finally:
            if ob.mode != mode:
                bpy.ops.object.mode_set(mode=mode)
        return "Scale frozen"

    def cleanup(self, context, ob, pid):
        with object_data(context, ob):
            found = cleanup_analyse(ob)
        n = cleanup_counts(found)[pid]
        mode = ob.mode
        mask = {'LAMINA': 'LAMINA_EXTRA', 'NONMANIFOLD': 'OPEN'}.get(pid, pid)
        select_elements(context, ob, CLEANUP_IDS[pid][2], found[mask])
        if pid == 'LOOSE':
            bpy.ops.mesh.select_all(action='SELECT')   # (Delete Loose looks at the selection for what has no faces)
        {'NGON': lambda: bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY'),
         'CONCAVE': lambda: bpy.ops.mesh.vert_connect_concave(),
         'NONMANIFOLD': lambda: bpy.ops.mesh.fill_holes(sides=0),
         'LAMINA': lambda: bpy.ops.mesh.delete(type='ONLY_FACE'),
         'ZERO': lambda: bpy.ops.mesh.dissolve_degenerate(),
         'LOOSE': lambda: bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)}[pid]()
        bpy.ops.mesh.select_all(action='DESELECT')
        if mode != 'EDIT':
            bpy.ops.object.mode_set(mode=mode)
        return "%s: %d" % (CLEANUP_IDS[pid][3], n)


def _reopen_cleanup():
    wm = bpy.context.window_manager
    if wm.windows:
        win = wm.windows[0]
        with bpy.context.temp_override(window=win, screen=win.screen):
            bpy.ops.m3d.mesh_cleanup('INVOKE_DEFAULT')


class M3D_OT_mesh_cleanup(Operator):
    """Cleanup: find n-gons, concave faces, non-manifold edges, lamina faces, zero-area faces and loose geometry, and select or
    fix each kind"""
    bl_idname = "m3d.mesh_cleanup"
    bl_label = "Cleanup"

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def invoke(self, context, _event):
        self.execute(context)
        return context.window_manager.invoke_popup(self, width=420)

    def execute(self, context):
        ob = mesh_of(context)
        with object_data(context, ob):
            _cleanup[0] = (ob.name, cleanup_counts(cleanup_analyse(ob)))
        if bpy.app.background:
            self.report({'INFO'}, "Cleanup: %s" % ", ".join("%s %d" % (k, v) for k, v in _cleanup[0][1].items()))
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        name, found = _cleanup[0] or ("", {})
        layout.label(text="Cleanup: %s" % name, icon='BRUSH_DATA', translate=False)
        col = layout.column(align=True)
        for pid, label, _domain, fix in CLEANUP:
            n = found.get(pid, 0)
            row = col.row(align=True)
            row.label(text="%s: %d" % (label, n) if n else "%s: none" % label, icon='ERROR' if n else 'CHECKMARK')
            if n:
                row.operator("m3d.mesh_check_select", text="", icon='RESTRICT_SELECT_OFF').problem = pid
                sub = row.row(align=True)
                sub.ui_units_x = 5
                sub.operator("m3d.mesh_check_fix", text=fix).fix = "C_" + pid
        if context.mode == 'EDIT_MESH':   # (it works on the selection in Edit Mode)
            layout.operator("mesh.remove_doubles", text="Merge by Distance", icon='AUTOMERGE_ON')
        reason(layout, "Each fix is one Undo step")


_cleanup = [None]   # (mesh name, counts) of the last Cleanup dialog


class M3D_OT_uv_harden_borders(Operator):
    """Harden UV Borders: smooth shading with hard edges exactly on the UV borders (first UV map), so a baked normal map has no
    seams inside the shells"""
    bl_idname = "m3d.uv_harden_borders"
    bl_label = "Harden UV Borders"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        with object_data(context, ob):
            hard = harden_uv_borders(ob)
        if hard is None:
            self.report({'WARNING'}, "The mesh has no UV map")
            return {'CANCELLED'}
        self.report({'INFO'}, "%d hard edges on the UV borders" % hard)
        return {'FINISHED'}


classes = (
    M3D_OT_lowpoly_check,
    M3D_OT_mesh_check_select,
    M3D_OT_mesh_check_fix,
    M3D_OT_mesh_cleanup,
    M3D_OT_uv_harden_borders,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
