# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Bake groups for Maelstrom3D: the Bake Groups panel of the Bake tab (Texture workspace, F4) and the bakes behind it.

A bake group is the meshes that share a group key (Object.m3d_pair, see m3d_pair.py): one or more low polys, which get the
maps, and one or more high polys, which the detail is baked from (several high polys are the floaters of the group). Each
group bakes on its own, whatever else is in the scene: only its high polys are the source, and the other meshes are not
rendered meanwhile, so they cannot shadow its ambient occlusion (AO scope "Whole Model" keeps every group's high polys in
the picture, for contact shadows between the groups). Cycles never counts the low poly it bakes onto.

Low polys that share a material are one texture set: they bake into the same images, each adding its own UV islands
(m3d_texture.texture_set names the images). The settings of a group live on the scene (Scene.m3d_bake_groups), made on the
first use from the Bake tab values of the group's low poly. A group is stale when one of its meshes changed after the bake:
the depsgraph handler notes it in memory (it may not write ID data) and the save handler writes it into the file.

Two aids for checking the groups: Explode moves the groups apart along one axis (each mesh remembers where it was, so Collapse puts
it back exactly), and the cage preview draws the low poly pushed out by the group's Extrusion as a wire, on temporary objects that
are never saved and never baked.
"""

import time

import bpy
from bpy.props import CollectionProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector

import m3d_pair
import m3d_texture as T
from m3d_sculpt import mesh_of, reason, split_props
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Settings and state

SCOPES = (
    ('GROUP', "This Group", "Only the high polys of this group cast shadows into its ambient occlusion"),
    ('MODEL', "Whole Model", "The high polys of every group cast shadows: contact shadows between the groups"),
)
STATES = (('NONE', "Not baked", ""), ('BAKED', "Baked", ""), ('STALE', "Stale", ""))
STATE_ICONS = {'NONE': 'DOT', 'BAKED': 'CHECKMARK', 'STALE': 'ERROR'}
STATE_TEXT = {key: label for key, label, _text in STATES}


def _settings_changed(self, _context):
    """A setting changed after the bake: the maps no longer show it."""
    if self.state == 'BAKED':
        self.state = 'STALE'


def _extrusion_changed(self, context):
    """The cage preview of this group follows the Extrusion."""
    _settings_changed(self, context)
    for ob in cage_objects():
        if ob.get(CAGE) == self.name and ob.parent is not None and ob.modifiers:
            ob.modifiers[0].strength = cage_strength(ob.parent, self.extrusion)


def _cage_changed(self, context):
    """A custom cage was picked or cleared: the cage preview of this group shows it."""
    _settings_changed(self, context)
    if any(ob.get(CAGE) == self.name for ob in cage_objects()):
        cage_show(context, self.name)


class M3D_BakeGroup(PropertyGroup):
    """Bake settings of one group (Scene.m3d_bake_groups); the name is the group key of Object.m3d_pair"""
    name: StringProperty(name="Group")
    extrusion: FloatProperty(name="Extrusion", default=0.02, min=0.0, soft_max=1.0, unit='LENGTH', update=_extrusion_changed,
                             description="Distance the rays start from the low-poly surface")
    ray_distance: FloatProperty(name="Max Ray Distance", default=0.0, min=0.0, soft_max=1.0, unit='LENGTH',
                                update=_settings_changed,
                                description="Longest distance a ray travels to the high-poly meshes (0: no limit)")
    cage: PointerProperty(
        name="Cage", type=bpy.types.Object, update=_cage_changed,
        description="Mesh the rays start from instead of the extruded low poly (it needs the faces of the low poly; "
                    "for a group with one low poly)", poll=lambda self, ob: ob.type == 'MESH')
    ao_scope: EnumProperty(name="AO Shadows", default='GROUP', items=SCOPES, update=_settings_changed,
                           description="Whose high polys cast shadows into the ambient occlusion of this group")
    state: EnumProperty(items=STATES, default='NONE', options={'HIDDEN'})
    members: StringProperty(options={'HIDDEN'}, description="The meshes of the group at the last bake")


def signature(lows, highs):
    return "%s/%s" % ("|".join(o.name for o in lows), "|".join(o.name for o in highs))


def settings_of(context, group):
    """The settings of a group, made on the first use from the Bake tab values (extrusion, ray distance) of its low poly."""
    entries = context.scene.m3d_bake_groups
    entry = entries.get(group)
    if entry is None:
        entry = entries.add()
        entry.name = group
        lows = m3d_pair.group_of(context, group)[0]
        if lows:
            entry.extrusion, entry.ray_distance = lows[0].m3d_bake.extrusion, lows[0].m3d_bake.ray_distance
    return entry


_wanted = set()   # (scene name, group) a panel wants settings for


def _make_wanted():
    for scene_name, group in sorted(_wanted):
        if bpy.context.scene.name == scene_name:
            settings_of(bpy.context, group)
    _wanted.clear()
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


def request_settings(context, group):
    """A panel needs the settings of a group that has none (files from before bake groups): made a moment later, since
    drawing may not write."""
    _wanted.add((context.scene.name, group))
    if not bpy.app.timers.is_registered(_make_wanted):
        bpy.app.timers.register(_make_wanted, first_interval=0.0)


# -----------------------------------------------------------------------------
# Stale groups

_stale = set()   # groups with a mesh that changed since it was seen last (a mark is only read for a group that was baked)
_modes = {}      # mesh name -> the mode it was in at the last update seen (Blender reports a change of mode as a change of geometry)


@bpy.app.handlers.persistent
def _depsgraph_update(_scene, depsgraph):
    """A mesh of a group changed its geometry or its transform. Nothing per vertex: the update list only. Hidden (parked)
    meshes are in it too. Going into a mode, and out of a paint mode, is no edit; going out of Sculpt Mode or Edit Mode is
    (a sculpt stroke is only reported then, and Blender does not say whether anything changed)."""
    cage = bpy.data.objects.get(CAGE)   # (the cage preview goes away when another group is picked: one lookup)
    if cage is not None and not bpy.app.timers.is_registered(_cage_drop):
        active = bpy.context.view_layer.objects.active
        if not (m3d_pair.grouped(active) and active.m3d_pair.group == cage.get(CAGE)):
            bpy.app.timers.register(_cage_drop, first_interval=0.0)
    if m3d_pair._quiet[0]:
        return
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Object):
            ob = update.id.original
            mode, before = ob.mode, _modes.get(ob.name, 'OBJECT')
            _modes[ob.name] = mode
            no_edit = mode != before and before not in {'EDIT', 'SCULPT'}
            if (update.is_updated_geometry or update.is_updated_transform) and not no_edit:
                p = ob.m3d_pair
                if p.role != 'NONE' and p.group:
                    _stale.add(p.group)


@bpy.app.handlers.persistent
def _save_pre(*_args):
    """The marks go into the file (the depsgraph handler could not write them); the cage preview does not."""
    cage_hide()
    for scene in bpy.data.scenes:
        for entry in scene.m3d_bake_groups:
            if entry.state == 'BAKED' and entry.name in _stale:
                entry.state = 'STALE'


@bpy.app.handlers.persistent
def _load_post(*_args):
    _stale.clear()
    _wanted.clear()
    _modes.clear()
    cage_hide()   # (an autosave or a crash file may hold the preview)


def state_of(entry, group, lows, highs):
    """'NONE' (never baked), 'BAKED', or 'STALE': a mesh changed, a mesh joined or left, or a setting changed since."""
    if entry is None or entry.state == 'NONE':
        return 'NONE'
    stale = entry.state == 'STALE' or group in _stale or entry.members != signature(lows, highs)
    return 'STALE' if stale else 'BAKED'


# -----------------------------------------------------------------------------
# Explode: the groups side by side along one axis

AXES = (('X', "X", "Line the groups up along X"), ('Y', "Y", "Line the groups up along Y"),
        ('Z', "Z", "Line the groups up along Z"))


def moved(context):
    """The meshes Explode moved (each keeps its old location and what was added, Object.m3d_pair: they go into the file)."""
    return [ob for ob in context.scene.objects if ob.type == 'MESH' and any(ob.m3d_pair.explode_offset)]


def members_of(context, group, lows, highs):
    """What moves with a group: its low polys, high polys and custom cage."""
    entry = context.scene.m3d_bake_groups.get(group)
    return list(dict.fromkeys([*lows, *highs, *([entry.cage] if entry is not None and entry.cage is not None else [])]))


def parents(ob):
    while ob.parent is not None:
        ob = ob.parent
        yield ob


def explode_plan(context):
    """(axis index, [(meshes of a group, shift along the axis)]) for the groups in the order they have along the axis. A
    group is moved past the one before it when their bounds overlap or are closer than the gap (a share of the average size
    of a group); a group that has room stays where it is."""
    axis = 'XYZ'.index(context.scene.m3d_explode_axis)
    boxes = []
    for group, (lows, highs) in m3d_pair.all_groups(context).items():
        obs = members_of(context, group, lows, highs)
        lo, hi = T.world_bounds(obs)
        boxes.append((float(lo[axis]), float(hi[axis]), obs))
    boxes.sort(key=lambda box: box[0])
    gap = context.scene.m3d_explode_gap * sum(hi - lo for lo, hi, _obs in boxes) / max(len(boxes), 1)
    plan, edge = [], None
    for lo, hi, obs in boxes:
        shift = 0.0 if edge is None else max(0.0, edge + gap - lo)
        edge = hi + shift if edge is None else max(edge, hi + shift)
        plan.append((obs, shift))
    return axis, plan


def collapse(context):
    """Every mesh Explode moved goes back where it was, exactly when nothing moved it since, else by what Explode added.
    Returns how many meshes moved."""
    obs = moved(context)
    with m3d_pair.quiet(context):
        for ob in obs:
            p = ob.m3d_pair
            home, offset, now = Vector(p.explode_from), Vector(p.explode_offset), Vector(ob.location)
            ob.location = home if (now - (home + offset)).length <= 1e-6 * (1.0 + now.length) else now - offset
            p.explode_from = p.explode_offset = (0.0, 0.0, 0.0)
    return len(obs)


def explode(context):
    """Put the groups apart along the axis of the scene (collapsing first, so new groups are included). A mesh moves by
    changing its location (the one under a parent that moves with its group follows it). Returns how many groups moved."""
    collapse(context)
    axis, plan = explode_plan(context)
    count = 0
    with m3d_pair.quiet(context):
        for obs, shift in plan:
            if not shift:
                continue
            world, inside, count = Vector((0.0, 0.0, 0.0)), set(obs), count + 1
            world[axis] = shift
            for ob in obs:
                if any(ob.m3d_pair.explode_offset) or not inside.isdisjoint(parents(ob)):
                    continue   # (moved with another group, or follows its parent)
                local = world if ob.parent is None else (ob.parent.matrix_world @ ob.matrix_parent_inverse).to_3x3().inverted_safe() @ world
                ob.m3d_pair.explode_from, ob.m3d_pair.explode_offset = ob.location, local
                ob.location = Vector(ob.location) + local
    return count


def _explode_changed(_self, context):
    """The axis or the gap changed while the groups are apart: line them up again."""
    if moved(context):
        explode(context)


class M3D_OT_bg_explode(Operator):
    """Move the groups apart along one axis so that they do not overlap, to look at them one by one or to export them to
    another baker. The low poly, the high polys and the cage of a group move together, so a bake gives the same maps.
    Again: every mesh goes back where it was"""
    bl_idname = "m3d.bg_explode"
    bl_label = "Explode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="Mode", default='TOGGLE', options={'HIDDEN'}, items=(
        ('TOGGLE', "Toggle", "Explode, or collapse when the groups are apart"),
        ('EXPLODE', "Explode", "Line the groups up again (after a group was added)"),
        ('COLLAPSE', "Collapse", "Put every mesh back")))

    @classmethod
    def poll(cls, context):
        return bool(m3d_pair.all_groups(context)) or bool(moved(context))

    def execute(self, context):
        if self.mode == 'COLLAPSE' or self.mode == 'TOGGLE' and moved(context):
            self.report({'INFO'}, "Put %s back" % m3d_pair.plural(collapse(context), "mesh"))
            return {'FINISHED'}
        count = explode(context)
        self.report({'INFO'}, "Moved %s apart along %s" % (m3d_pair.plural(count, "group"), context.scene.m3d_explode_axis) if count else
                    "The groups have room along %s already" % context.scene.m3d_explode_axis)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Cage preview: the low poly pushed out by the Extrusion, drawn as a wire
#
# Temporary objects share the mesh of the low poly (so edits show at once), carry a Displace modifier along the normals, are
# parented to it (so they follow it) and are drawn as a wire. They are named CAGE and hold the group in a custom property of that
# name, which is how they are found: nothing is kept in memory, so Undo, Redo and a reload cannot leave it out of step. They are
# removed when the preview is turned off, when another group is picked, before a bake and before a file is saved or loaded, and they are
# never rendered or selected.

CAGE = "m3dCage"


def cage_objects():
    return [ob for ob in bpy.data.objects if CAGE in ob]


def cage_hide():
    """Take the preview away (the view layer is brought up to date inside `quiet`: it would still list the removed objects, and
    the low polys, whose children changed, would be seen as edited)."""
    gone = cage_objects()
    if gone:
        with m3d_pair.quiet(bpy.context):
            for ob in gone:
                bpy.data.objects.remove(ob)


def cage_strength(low, extrusion):
    """Strength of the Displace modifier that moves the points of `low` out by `extrusion` in the world (its scale is in the way)."""
    return extrusion / max(low.matrix_world.median_scale, 1e-6)


def cage_show(context, group):
    """The preview of `group`: each low poly pushed out by the group's Extrusion, or its custom cage as it is. Returns how
    many objects it is made of."""
    cage_hide()
    lows = m3d_pair.group_of(context, group)[0]
    entry = settings_of(context, group)
    cage = entry.cage if len(lows) == 1 and entry.cage is not None and entry.cage != lows[0] else None
    shown = [(cage, None)] if cage is not None else [(low, entry.extrusion) for low in lows]
    with m3d_pair.quiet(context):
        for src, extrusion in shown:
            ob = bpy.data.objects.new(CAGE, src.data)
            ob[CAGE] = group
            (src.users_collection or (context.scene.collection,))[0].objects.link(ob)
            ob.parent = src
            ob.display_type, ob.color = 'WIRE', (1.0, 0.5, 0.1, 1.0)
            ob.hide_select = ob.hide_render = True
            if extrusion is not None:
                mod = ob.modifiers.new("Cage", 'DISPLACE')
                mod.direction, mod.mid_level, mod.strength = 'NORMAL', 0.0, cage_strength(src, extrusion)
    return len(shown)


def _cage_drop():
    """Timer: the preview shows a group that is not the active one any more."""
    cage_hide()


class M3D_OT_bg_cage_preview(Operator):
    """Show the low poly of this group pushed out by its Extrusion (or its custom cage) as a wire in the 3D view, to check
    that it covers the high poly. It is only drawn: it is not saved, not baked, and it goes away when you pick another group"""
    bl_idname = "m3d.bg_cage_preview"
    bl_label = "Show Cage"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return m3d_pair.grouped(ob) and (bool(m3d_pair.group_of(context, ob.m3d_pair.group)[0]) or bool(cage_objects()))

    def execute(self, context):
        if cage_objects():
            cage_hide()
        elif not cage_show(context, context.active_object.m3d_pair.group):
            self.report({'WARNING'}, "This group has no low poly")
            return {'CANCELLED'}
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Bakes

def hidden_for(context, low, group, groups, scope):
    """The meshes that are not rendered while `low` is baked: everything but the group's own geometry (its high polys; a
    group without any bakes itself, so its low polys stay), or with the scope 'MODEL' the geometry of every group."""
    keep = {low.name}
    for name, (lows, highs) in groups.items():
        if name == group or scope == 'MODEL':
            keep.update(o.name for o in (highs or lows))
    return [o for o in context.view_layer.objects if o.type in T.RENDERED and o.name not in keep and not o.hide_render]


def ticked(s):
    return [m for m in T.BAKE_MAPS if getattr(s, m[2])]


def bake_low(context, low, groups, s, maps, name, others):
    """The maps of one low poly of a group, from the high polys of the group, with everything else not rendered."""
    group = low.m3d_pair.group
    lows, highs = groups[group]
    entry = settings_of(context, group)
    if not low.data.uv_layers:
        raise RuntimeError("%s has no UVs: unwrap it first" % low.name)
    cage = entry.cage if len(lows) == 1 and entry.cage is not None and entry.cage != low else None
    with m3d_pair.quiet(context), T.bake_scene(context, low, highs, hidden_for(context, low, group, groups, entry.ao_scope)):
        T.bake_maps(context, low, highs, s, maps, name=name, extrusion=entry.extrusion, ray_distance=entry.ray_distance,
                    cage=cage, others=others, normalise=False)


def bake_set(context, lows, maps, times=None, errors=None, progress=None):
    """Bake `maps` ((key, label, flag) as in T.BAKE_MAPS) of `lows`, low polys of one texture set, each from its own group,
    into the maps of the set. All the low polys of the set: the images start over; some: their islands are added to what
    the images hold. `times` {group: seconds}, `errors` {group: message} (a low poly that fails is skipped; without it the
    error is raised), `progress()` is called after each low poly. The cage preview is taken away first."""
    cage_hide()
    name, every = T.texture_set(lows[0])
    s = T.bake_owner(lows[0]).m3d_bake
    groups = m3d_pair.all_groups(context)
    others = [o.name for o in every]
    whole = len(lows) == len(every)
    position = any(m[0] == 'POSITION' for m in maps)
    if whole:
        T.forget_parts(name, [m[1] for m in maps])

    def run(targets, todo):
        for low in targets:
            t0 = time.perf_counter()
            try:
                bake_low(context, low, groups, s, todo, name, others)
            except RuntimeError as err:
                if errors is None:
                    raise
                errors[low.m3d_pair.group] = str(err).strip()
            if times is not None:
                times[low.m3d_pair.group] = times.get(low.m3d_pair.group, 0.0) + time.perf_counter() - t0
            if progress is not None:
                progress()

    run(lows, maps if whole else [m for m in maps if m[0] != 'POSITION'])
    if position and not whole:   # (the map is scaled to the bounds of the whole set: all of it is baked again)
        T.forget_parts(name, ["Position"])
        run(every, [m for m in maps if m[0] == 'POSITION'])
    image = bpy.data.images.get("%s_Position" % name)
    if position and image is not None:
        geometry = {o.name: o for low in every for o in (groups[low.m3d_pair.group][1] or [low])}
        T.normalise_position(image, list(geometry.values()), every[0])


def bake_groups_done(context, groups, names):
    """The groups `names` are baked now: their meshes are what the maps show."""
    for group in names:
        entry = settings_of(context, group)
        entry.state, entry.members = 'BAKED', signature(*groups[group])
        _stale.discard(group)


def record_baked(s, name, maps):
    """The Bake tab lists the images of the last bake."""
    s.baked = "|".join("%s_%s" % (name, m[1]) for m in maps)


def stepper(wm):
    """progress() for bake_set: moves the progress bar one step further each time."""
    count = [0]

    def step():
        count[0] += 1
        wm.progress_update(count[0])
    return step


class M3D_OT_bg_select(Operator):
    """Select the low poly of this group and make it active"""
    bl_idname = "m3d.bg_select"
    bl_label = "Select Group"
    bl_options = {'REGISTER', 'UNDO'}

    group: StringProperty(name="Group")

    def execute(self, context):
        lows = [o for o in m3d_pair.group_of(context, self.group)[0] if not o.hide_get()]
        if not lows:
            self.report({'WARNING'}, "%s has no low poly to select (hidden or missing)" % self.group)
            return {'CANCELLED'}
        layer = context.view_layer
        active = layer.objects.active
        mode = active.mode if active is not None else 'OBJECT'
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.selected_objects:
            ob.select_set(False)
        for ob in lows:
            ob.select_set(True)
        layer.objects.active = lows[0]
        if mode == 'TEXTURE_PAINT' and not m3d_pair.too_big(context.workspace, lows[0]):   # (the mode the tab was in)
            try:
                bpy.ops.object.mode_set(mode=mode)
            except RuntimeError:
                pass
        return {'FINISHED'}


class M3D_OT_bg_bake(Operator):
    """Bake the maps ticked in the Bake tab for every low poly of a group, from the high poly meshes of that group (only
    they are baked from, and nothing else shadows them). Low polys that share a material bake into the same images"""
    bl_idname = "m3d.bg_bake"
    bl_label = "Bake Group"
    bl_options = {'REGISTER', 'UNDO'}

    group: StringProperty(name="Group", description="The group to bake (empty: the group of the active mesh)")

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return m3d_pair.grouped(ob) and bool(m3d_pair.group_of(context, ob.m3d_pair.group)[0])

    def execute(self, context):
        ob = mesh_of(context)
        group = self.group or (ob.m3d_pair.group if m3d_pair.grouped(ob) else "")
        groups = m3d_pair.all_groups(context)
        lows = groups.get(group, ([], []))[0]
        if not lows:
            self.report({'WARNING'}, "%s has no low poly to bake onto" % (group or "No group"))
            return {'CANCELLED'}
        sets = {}
        for low in lows:
            sets.setdefault(T.texture_set(low)[0], []).append(low)
        wm = context.window_manager
        wm.progress_begin(0, len(lows))
        step, t0, shown = stepper(wm), time.perf_counter(), []
        try:
            for name, set_lows in sets.items():
                s = T.bake_owner(set_lows[0]).m3d_bake
                maps = ticked(s)
                if not maps:
                    self.report({'WARNING'}, "Tick at least one map")
                    return {'CANCELLED'}
                bake_set(context, set_lows, maps, progress=step)
                record_baked(s, name, maps)
                shown = maps
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            wm.progress_end()
        bake_groups_done(context, groups, [group])
        self.report({'INFO'}, "Baked %s: %s at %s px in %.1f s" % (
            group, ", ".join(m[1] for m in shown), T.bake_owner(lows[0]).m3d_bake.resolution, time.perf_counter() - t0))
        return {'FINISHED'}


class M3D_OT_bg_bake_all(Operator):
    """Bake every group, one after the other, with the maps ticked in the Bake tab. A group that fails is skipped and
    reported. Low polys that share a material bake into the same images; one Undo takes the whole bake back"""
    bl_idname = "m3d.bg_bake_all"
    bl_label = "Bake All"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(lows for lows, _highs in m3d_pair.all_groups(context).values())

    def execute(self, context):
        groups = m3d_pair.all_groups(context)
        sets = {}   # texture set -> its low polys, the sets in the order of their first group
        for lows, _highs in groups.values():
            for low in lows:
                name, every = T.texture_set(low)
                sets[name] = every
        total = sum(len(every) for every in sets.values())
        wm = context.window_manager
        wm.progress_begin(0, total)
        step, times, errors, t0 = stepper(wm), {}, {}, time.perf_counter()
        try:
            for name, every in sets.items():
                s = T.bake_owner(every[0]).m3d_bake
                maps = ticked(s)
                if not maps:
                    errors[name] = "no map is ticked"
                    continue
                bake_set(context, every, maps, times, errors, progress=step)
                record_baked(s, name, maps)
        finally:
            wm.progress_end()
        baked = [g for g in times if g not in errors]
        bake_groups_done(context, groups, baked)
        for group in baked:
            self.report({'INFO'}, "%s: %.1f s" % (group, times[group]))
        if errors:
            self.report({'WARNING'}, "Not baked: " + "; ".join("%s (%s)" % item for item in errors.items()))
        if not baked:
            return {'CANCELLED'}
        self.report({'INFO'}, "Baked %s in %.1f s" % (m3d_pair.plural(len(baked), "group"), time.perf_counter() - t0))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Panels of the Bake tab (the High Poly, Maps, Settings and Bake panels are in m3d_texture.py)

class PROPERTIES_PT_m3d_tx_bake_groups(_PagePanel, Panel):
    bl_label = "Bake Groups"
    page = "tex_bake"

    def draw(self, context):
        layout = self.layout
        groups = m3d_pair.all_groups(context)
        ob = context.active_object
        active = ob.m3d_pair.group if m3d_pair.grouped(ob) else ""
        if groups:
            col = layout.column(align=True)
            for group, (lows, highs) in groups.items():
                state = state_of(context.scene.m3d_bake_groups.get(group), group, lows, highs)
                split = col.split(factor=0.5, align=True)
                split.operator("m3d.bg_select", text=group, icon=STATE_ICONS[state], depress=group == active).group = group
                info = split.row(align=True)
                info.alert = state == 'STALE'
                info.label(text="%d low  %d high" % (len(lows), len(highs)))
                info.label(text=STATE_TEXT[state])
        else:
            reason(layout, "Name meshes Sword_low and Sword_high, then Auto-Pair")
        pair = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        pair.operator("m3d.hp_auto_pair", icon='LINKED')
        pair.operator("m3d.hp_pair", icon='LINKED')
        layout.operator_menu_enum("m3d.hp_rename", "style", text="Rename to Suffixes", icon='SORTALPHA')
        row = layout.row(align=True)
        row.scale_y = 1.6
        row.operator("m3d.bg_bake", icon='RENDER_STILL')
        row.operator("m3d.bg_bake_all", icon='RENDER_ANIMATION')
        reason(layout, "Uses Cycles; the window waits until it is done")
        apart = bool(moved(context))
        row = layout.row(align=True)
        row.operator("m3d.bg_explode", text="Collapse" if apart else "Explode", icon='FULLSCREEN_EXIT' if apart else 'FULLSCREEN_ENTER',
                     depress=apart).mode = 'TOGGLE'
        if apart:
            row.operator("m3d.bg_explode", text="", icon='FILE_REFRESH').mode = 'EXPLODE'
        row = layout.row(align=True)
        row.prop(context.scene, "m3d_explode_axis", expand=True)
        split_props(layout)
        layout.prop(context.scene, "m3d_explode_gap", slider=True)
        if apart and any(entry.ao_scope == 'MODEL' for entry in context.scene.m3d_bake_groups):
            reason(layout, "AO Shadows: Whole Model sees the groups as placed now")


def names_line(label, obs, limit=3):
    names = [o.name for o in obs]
    return "%s: %s%s" % (label, ", ".join(names[:limit]), " +%d" % (len(names) - limit) if len(names) > limit else "")


class PROPERTIES_PT_m3d_tx_bake_group(_PagePanel, Panel):
    bl_label = "Group Settings"
    page = "tex_bake"

    @classmethod
    def page_poll(cls, context):
        return m3d_pair.grouped(context.active_object)

    def draw(self, context):
        layout = self.layout
        group = context.active_object.m3d_pair.group
        lows, highs = m3d_pair.group_of(context, group)
        entry = context.scene.m3d_bake_groups.get(group)
        layout.label(text=group, icon='OUTLINER_COLLECTION')
        col = layout.column(align=True)
        col.label(text=names_line("Low", lows) if lows else "No low poly: nothing to bake onto")
        col.label(text=names_line("High", highs) if highs else "No high poly: the low poly bakes itself")
        if entry is None:
            request_settings(context, group)
            return
        split_props(layout)
        layout.prop(entry, "extrusion")
        layout.prop(entry, "ray_distance")
        sub = layout.column()
        sub.active = len(lows) == 1
        sub.prop(entry, "cage")
        shown = bool(cage_objects())
        layout.operator("m3d.bg_cage_preview", icon='MOD_DISPLACE', depress=shown)
        if shown:
            reason(layout, "A wire in the 3D view: not saved, not baked")
        layout.prop(entry, "ao_scope", expand=True)
        for low in lows:
            if not low.data.uv_layers:
                reason(layout, "%s has no UVs" % low.name)
        if len(lows) > 1 and entry.cage is not None:
            reason(layout, "A custom cage needs one low poly")
        if entry.ao_scope == 'MODEL':
            reason(layout, "Other groups' high polys shadow this group")


classes = (
    M3D_BakeGroup,
    M3D_OT_bg_explode,
    M3D_OT_bg_cage_preview,
    M3D_OT_bg_select,
    M3D_OT_bg_bake,
    M3D_OT_bg_bake_all,
    PROPERTIES_PT_m3d_tx_bake_groups,
    PROPERTIES_PT_m3d_tx_bake_group,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_bake_groups = CollectionProperty(type=M3D_BakeGroup)
    bpy.types.Scene.m3d_explode_axis = EnumProperty(name="Axis", default='X', items=AXES, update=_explode_changed,
                                                    description="The groups are lined up along this axis")
    bpy.types.Scene.m3d_explode_gap = FloatProperty(
        name="Gap", default=0.25, min=0.0, soft_max=2.0, subtype='FACTOR', update=_explode_changed,
        description="Room between the groups, as a share of the average size of a group along the axis")
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)
    bpy.app.handlers.save_pre.append(_save_pre)
    bpy.app.handlers.load_post.append(_load_post)


def unregister():
    bpy.app.handlers.load_post.remove(_load_post)
    bpy.app.handlers.save_pre.remove(_save_pre)
    bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update)
    del bpy.types.Scene.m3d_explode_gap
    del bpy.types.Scene.m3d_explode_axis
    del bpy.types.Scene.m3d_bake_groups
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
