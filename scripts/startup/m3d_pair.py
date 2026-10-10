# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
High poly / low poly pairs for Maelstrom3D. A mesh has a role (Low, High) and a group; meshes with the same group belong
together: one low poly and its high poly parts (Panel_low, Panel_high, Panel_high_bolts). The Bake tab builds on the
roles and groups (Object.m3d_pair).

Parking: a high poly that has a low poly is hidden everywhere but in the Sculpt workspace. Entering Sculpt hides the low
poly, shows the high poly and starts Sculpt Mode on it; leaving Sculpt exits the mode, hides the high poly again and shows
the low poly. The hiding happens in the same step as the workspace switch (M3D_OT_workspace, before the redraw): a mesh of
millions of faces that is already hidden is not rebuilt for the new mode. Only meshes we hid ourselves (`parked`) are ever
shown again, and meshes without a role are never touched.

Also here: Create High Poly, Mark / Pair, Auto-Pair by Name, Rename to Suffixes, Make Pair (from the old High Poly picker
of the Bake tab), Edit High Poly, the Channel Box row and the face limit of the UV and Texture workspaces (a huge mesh stays
in Object Mode there).
"""

import re
import time
from contextlib import contextmanager

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Menu, Operator, PropertyGroup

import m3d_inputs
from m3d_workspace import current_kind, workspace_kind

ROLES = (
    ('NONE', "None", "A plain mesh"),
    ('LOW', "Low Poly", "The light mesh you unwrap, paint and export"),
    ('HIGH', "High Poly", "The detailed sculpt the maps are baked from"),
)
ROLE_LABEL = {'NONE': "None", 'LOW': "Low", 'HIGH': "High"}


# -----------------------------------------------------------------------------
# Names

_ROLE_WORDS = {"low": 'LOW', "lp": 'LOW', "lo": 'LOW', "lowpoly": 'LOW',
               "high": 'HIGH', "hp": 'HIGH', "hi": 'HIGH', "highpoly": 'HIGH'}
_WORD = re.compile(r"[^_.\- ]+")
_TAIL = re.compile(r"\.\d+$")
_SEPARATORS = re.compile(r"[_.\- ]+")


def parse_name(name):
    """(base, role, extra) of a mesh name: "Sword_high.001" -> ("Sword", 'HIGH', ""), "Sword_LP" -> ("Sword", 'LOW', ""). Blender's
    .001 tail is ignored. Words after the role make the mesh a floater of that group: "Panel_high_bolts" -> ("Panel", 'HIGH',
    "_bolts"). A name without a role gives (name, None, "")."""
    stem = _TAIL.sub("", name)
    words = list(_WORD.finditer(stem))
    hits = [i for i, w in enumerate(words) if i > 0 and w.group().lower() in _ROLE_WORDS]
    if not hits:
        return name, None, ""
    i = hits[-1] if hits[-1] == len(words) - 1 else hits[0]   # (a name ends with its role, unless it is a floater)
    rest = stem[words[i].end():].strip("_.- ")
    return stem[:words[i].start()].rstrip("_.- "), _ROLE_WORDS[words[i].group().lower()], ("_" + _SEPARATORS.sub("_", rest) if rest else "")


def split_role(name):
    """(base, role) of a mesh name, see `parse_name`."""
    return parse_name(name)[:2]


def format_count(n):
    return "%.1fM" % (n / 1e6) if n >= 1_000_000 else "%dk" % (n // 1000) if n >= 10_000 else format(n, ",")


# -----------------------------------------------------------------------------
# Roles and groups

class M3D_Pair(PropertyGroup):
    """High poly / low poly role of a mesh (Object.m3d_pair)"""
    role: EnumProperty(name="Role", items=ROLES, default='NONE',
                       description="Low poly: the mesh you unwrap, paint and export. High poly: the sculpt it is baked from")
    group: StringProperty(name="Group", description="Meshes with the same group belong together (one bake group)")
    parked: BoolProperty(options={'HIDDEN'}, description="Hidden by Maelstrom3D, to be shown again by it")
    ghost: StringProperty(options={'HIDDEN'}, description="Display type before Show Low Poly drew this mesh as a wire")


def is_mesh(ob):
    return ob is not None and ob.type == 'MESH'


def group_of(context, group):
    """(low polys, high polys) of a group in the view layer, each sorted by name."""
    lows, highs = [], []
    if not group:
        return lows, highs
    for ob in context.view_layer.objects:
        if ob.type == 'MESH':
            p = ob.m3d_pair
            if p.group == group:
                (lows if p.role == 'LOW' else highs if p.role == 'HIGH' else []).append(ob)
    return sorted(lows, key=lambda o: o.name), sorted(highs, key=lambda o: o.name)


def pair_of(context, ob):
    """(low polys, high polys) of the group of `ob`; two empty lists for a mesh without a role."""
    if not is_mesh(ob) or ob.m3d_pair.role == 'NONE' or not ob.m3d_pair.group:
        return [], []
    return group_of(context, ob.m3d_pair.group)


def grouped(ob):
    """A mesh with a role and a group: what the Bake tab bakes from and onto."""
    return is_mesh(ob) and ob.m3d_pair.role != 'NONE' and bool(ob.m3d_pair.group)


def all_groups(context):
    """{group: (low polys, high polys)} of the view layer, by group name. Meshes without a role or a group are in none."""
    found = {}
    for ob in context.view_layer.objects:
        if ob.type == 'MESH':
            p = ob.m3d_pair
            if p.role != 'NONE' and p.group:
                found.setdefault(p.group, ([], []))[p.role == 'HIGH'].append(ob)
    for lows_highs in found.values():
        for obs in lows_highs:
            obs.sort(key=lambda o: o.name)
    return dict(sorted(found.items(), key=lambda item: item[0].lower()))


def set_role(ob, role, group=None):
    """Give a mesh a role. The group stays when it has one, else it is `group`, else the base of the mesh's name. What
    we did to the mesh under its old role (hidden, drawn as a wire) is undone."""
    p = ob.m3d_pair
    if p.role != role:
        restore(ob)
    p.role = role
    p.group = "" if role == 'NONE' else (group or p.group or split_role(ob.name)[0])


def meshes(context):
    """The selected meshes (the active one when none is selected)."""
    obs = [o for o in context.selected_objects if o.type == 'MESH']
    ob = context.active_object
    return obs or ([ob] if is_mesh(ob) else [])


def face_count(ob):
    """Faces the mesh has: a Multires mesh counts the level the viewport shows. No per-face work."""
    mesh = ob.data
    mod = next((m for m in ob.modifiers if m.type == 'MULTIRES'), None)
    if mod is not None and mod.levels > 0:
        return len(mesh.loops) * 4 ** (mod.levels - 1)
    return len(mesh.polygons)


# -----------------------------------------------------------------------------
# Parking: hide, show, wire

def park(ob):
    """Hide a mesh and remember that we did (one the user hid is left alone). The selection goes with it."""
    if not ob.hide_get():
        ob.select_set(False)
        ob.hide_set(True)
        ob.m3d_pair.parked = True


def restore(ob):
    """Undo what we did to a mesh: show it again if we hid it, draw it as before if we made it a wire."""
    p = ob.m3d_pair
    if p.ghost:
        ob.display_type, ob.hide_select, p.ghost = p.ghost, False, ""
    if p.parked and ob.hide_get():
        ob.hide_set(False)
    p.parked = False


def ghost(ob):
    """Show a low poly as an unselectable wire (Show Low Poly)."""
    p = ob.m3d_pair
    if ob.hide_get() and not p.parked:
        return   # the user hid it
    if p.parked and ob.hide_get():
        ob.hide_set(False)
    p.parked = False
    if not p.ghost:
        p.ghost = ob.display_type
    ob.select_set(False)
    ob.display_type, ob.hide_select = 'WIRE', True


def put_away(ob):
    """Get a low poly out of the way in Sculpt: hidden (a wire is drawn as it was first)."""
    if ob.m3d_pair.ghost:
        restore(ob)
    park(ob)


_quiet = [0]   # > 0 while something changes the meshes without editing them: the stale marks of the bake groups ignore it


@contextmanager
def quiet(context):
    """Changes that are no edit of the meshes (a bake showing and hiding them and swapping materials, new names, a checker
    map, an export's temporary material) are made inside this: the bake groups do not go stale from them. The depsgraph is
    brought up to date before it ends, while the marks are off (Blender reports a change of material slots, of visibility
    and the like as an edit)."""
    _quiet[0] += 1
    try:
        yield
    finally:
        try:
            context.view_layer.update()
        finally:
            _quiet[0] -= 1


_last = {}   # group -> name of the high poly sculpted last
_state = {"ws": None, "pending": None, "group": ""}   # workspace parking was done for, a switch in progress, group of Sculpt


def pick_high(highs, group):
    """The high poly to work on: the one sculpted last, else the first by name."""
    want = _last.get(group)
    return next((h for h in highs if h.name == want), highs[0])


def leave_modes(context):
    """Object Mode (a mesh that is about to be hidden can't be in a mode)."""
    ob = context.view_layer.objects.active
    if ob is not None and ob.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def enter_sculpt(context, set_mode=False):
    """Sculpt opens: sculpt the high poly of the active mesh's group, with the low poly out of the way. `set_mode`:
    also start Sculpt Mode on it (the window did not, or did on the low poly)."""
    vl = context.view_layer
    ob = vl.objects.active
    lows, highs = pair_of(context, ob)
    if not lows or not highs:
        return
    group = ob.m3d_pair.group
    target = ob if ob.m3d_pair.role == 'HIGH' else pick_high(highs, group)
    if target.hide_get() and not target.m3d_pair.parked:
        return   # the user hid it: not ours to show
    leave_modes(context)
    for high in highs:
        if high.m3d_pair.parked:
            restore(high)
    for low in lows:
        if context.scene.m3d_show_low:
            ghost(low)
        else:
            put_away(low)
    vl.objects.active = target
    target.select_set(True)
    _state["group"] = group
    if set_mode and target.mode != 'SCULPT':
        bpy.ops.object.mode_set(mode='SCULPT')


def start_sculpt(name):
    """Sculpt Mode on the mesh `name`, if it is still the active one in the Sculpt workspace and not in a mode."""
    ob = bpy.data.objects.get(name)
    context = bpy.context
    if ob is not None and context.view_layer.objects.active == ob and ob.mode == 'OBJECT' and current_kind(context) == 'SCULPT':
        bpy.ops.object.mode_set('EXEC_DEFAULT', False, mode='SCULPT')   # (False: no undo step of its own)


def sculpt_soon(name):
    """Start Sculpt Mode once the operator is over: its undo step is then one of Object Mode, which keeps the new meshes
    (a step taken in Sculpt Mode does not), and the redraw has not happened yet."""
    bpy.app.timers.register(lambda: start_sculpt(name), first_interval=0.0)


def park_all(context):
    """Hide every high poly that has a low poly. A high poly that was active hands over to its low poly."""
    vl = context.view_layer
    for lows, highs in all_groups(context).values():
        if lows:
            for high in highs:
                park(high)
    ob = vl.objects.active
    if is_mesh(ob) and ob.m3d_pair.role == 'HIGH' and ob.hide_get():
        low = next((o for o in pair_of(context, ob)[0] if not o.hide_get()), None)
        if low is not None:
            low.select_set(True)
            vl.objects.active = low


def leave_sculpt(context):
    """Sculpt closes: Object Mode, the high poly parked, the low poly shown, selected and active."""
    vl = context.view_layer
    ob = vl.objects.active
    leave_modes(context)
    if is_mesh(ob) and ob.m3d_pair.role == 'HIGH' and ob.m3d_pair.group:
        _last[ob.m3d_pair.group] = ob.name
    lows = pair_of(context, ob)[0] or group_of(context, _state["group"])[0]
    for o in vl.objects:   # every low poly we put away, whatever the group
        if o.type == 'MESH' and o.m3d_pair.role == 'LOW' and (o.m3d_pair.parked or o.m3d_pair.ghost):
            restore(o)
    for low in lows:
        if not low.hide_get():
            low.select_set(True)
    park_all(context)


def switch(context, old_ws, new_ws, set_mode=False):
    """Parking for the window going from workspace `old_ws` to `new_ws`: Sculpt shows the pair's high poly, leaving
    it parks the high poly, any other switch parks one that Edit High Poly showed."""
    if old_ws == new_ws or new_ws is None:
        return
    entering, leaving = workspace_kind(new_ws) == 'SCULPT', workspace_kind(old_ws) == 'SCULPT'
    if entering:
        enter_sculpt(context, set_mode)
    elif leaving:
        leave_sculpt(context)
    else:
        park_all(context)
    _state["ws"] = new_ws.name


def before_switch(context, old_ws, new_ws):
    """M3D_OT_workspace calls this just before the window changes workspace: the pair is parked or shown now, so the
    redraw never draws the wrong one. True when the new workspace has to open in Object Mode (a huge mesh)."""
    if old_ws == new_ws:
        return False
    try:
        switch(context, old_ws, new_ws)
    except Exception:   # (a bug here must not take the F-keys with it)
        import traceback
        traceback.print_exc()
    _state["pending"] = (new_ws.name, time.monotonic() + 2.0)   # (`follow` leaves this switch alone)
    return keeps_object_mode(context, new_ws)


def follow(wm):
    """Timer fallback (m3d_workspace._follow_workspace): the window was switched some other way (the workspace
    picker, Ctrl+Page Up / Down): the same parking, a little late, and the mode is set here."""
    win = wm.windows[0] if wm.windows else None
    if win is None or win.workspace is None:
        return
    name = win.workspace.name
    if _state["ws"] is None:
        _state["ws"] = name
        return
    pending = _state["pending"]
    if pending is not None:
        if name != pending[0] and time.monotonic() < pending[1]:
            return   # M3D_OT_workspace has switched, the window has not caught up yet
        _state["pending"] = None
    if name == _state["ws"]:
        return
    try:
        switch(bpy.context, bpy.data.workspaces.get(_state["ws"]), win.workspace, set_mode=True)
    except Exception:   # (an error here would stop the timer, and with it the menu set following the workspace)
        import traceback
        traceback.print_exc()
        _state["ws"] = name


@bpy.app.handlers.persistent
def _load_post(*_args):
    _state.update(ws=None, pending=None, group="")
    _last.clear()
    _holds.clear()
    _quiet[0] = 0


# -----------------------------------------------------------------------------
# The face limit of the UV and Texture workspaces

def too_big(ws, ob):
    limit = ws.m3d_face_limit
    return limit > 0 and is_mesh(ob) and face_count(ob) > limit


def keeps_object_mode(context, ws):
    """True when `ws` would put the active mesh in Edit or Texture Paint Mode and the mesh has more faces than the
    workspace's limit (opening a mode on a huge mesh takes seconds)."""
    return ws.object_mode in {'EDIT', 'TEXTURE_PAINT'} and too_big(ws, context.view_layer.objects.active)


_holds = {}   # workspace name -> its entry mode, while a switch holds it in Object Mode


def hold_object_mode(ws):
    """The window is about to switch to `ws`: its entry mode is Object Mode for that switch (C applies it when the
    notifier is handled, after the operator), then it is put back."""
    name, entry = ws.name, ws.object_mode
    if entry == 'OBJECT':
        return   # (nothing to hold: or it is held already, and the timer of that hold puts the mode back)
    ws.object_mode = 'OBJECT'
    _holds[name] = entry
    deadline = time.monotonic() + 3.0
    bpy.app.timers.register(lambda: release_hold(name, entry, deadline), first_interval=0.05)


def release_hold(name, entry, deadline):
    """Put the entry mode of workspace `name` back once the window has switched to it (or after the deadline)."""
    ws = bpy.data.workspaces.get(name)
    if ws is None:
        return None
    wm = bpy.context.window_manager
    if wm.windows and wm.windows[0].workspace != ws and time.monotonic() < deadline:
        return 0.05
    ws.object_mode = entry
    _holds.pop(name, None)
    return None


@bpy.app.handlers.persistent
def _save_pre(*_args):
    """A file saved during a hold keeps each workspace's own entry mode."""
    for name, entry in _holds.items():
        ws = bpy.data.workspaces.get(name)
        if ws is not None:
            ws.object_mode = entry


def big_note(context):
    """"High poly (2.1M faces): select the low poly to unwrap or paint" for the active mesh when it is over the
    workspace's face limit and in Object Mode (the workspace left it there), else None."""
    ob, ws = context.active_object, context.workspace
    if ws is None or ob is None or ob.mode != 'OBJECT' or not too_big(ws, ob):
        return None
    return "High poly (%s faces): select the low poly to unwrap or paint" % format_count(face_count(ob))


def draw_note(layout, note):
    """The note on two lines (docks are narrow)."""
    head, _sep, tail = note.partition(": ")
    layout.label(text=head + ":", icon='ERROR')
    layout.label(text=tail[:1].upper() + tail[1:])


# -----------------------------------------------------------------------------
# Operators

def _on(context, ob):
    """Context for operators that work on `ob` alone."""
    return context.temp_override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob])


def surface_area(mesh):
    import numpy as np
    area = np.empty(len(mesh.polygons), np.float32)
    mesh.polygons.foreach_get("area", area)
    return float(area.sum())


MAX_VOXEL_FACES = 6_000_000   # Voxel Remesh has no limit of its own: a tiny size would run for minutes


class M3D_OT_hp_create(Operator):
    """Make a high poly copy of the selected mesh to sculpt on, and pair it with the original (the low poly)"""
    bl_idname = "m3d.hp_create"
    bl_label = "Create High Poly"
    bl_options = {'REGISTER', 'UNDO'}

    detail: EnumProperty(name="Detail", default='NONE', items=(
        ('NONE', "None", "Sculpt the copy as it is"),
        ('MULTIRES', "Multires", "Add Multires levels to the copy (the low poly shape stays in the base)"),
        ('VOXEL', "Voxel Remesh", "Rebuild the copy as an even mesh of small faces")))
    levels: IntProperty(name="Levels", description="Multires levels to add", default=2, min=1, max=6)
    voxel_size: FloatProperty(name="Voxel Size", description="Size of the faces of the remeshed copy", default=0.01,
                              min=0.0001, soft_max=1.0, step=1, precision=4, subtype='DISTANCE', unit='LENGTH')

    @classmethod
    def poll(cls, context):
        return bool(meshes(context))

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "detail")
        if self.detail == 'MULTIRES':
            layout.prop(self, "levels")
        elif self.detail == 'VOXEL':
            layout.prop(self, "voxel_size")

    def execute(self, context):
        from m3d_sculpt import uniform_scale
        sources = [o for o in meshes(context) if o.m3d_pair.role != 'HIGH']
        if not sources:
            self.report({'WARNING'}, "Select the mesh to make a high poly of")
            return {'CANCELLED'}
        if self.detail == 'VOXEL':
            for src in sources:
                scale = 1.0 if uniform_scale(src) else max(abs(s) for s in src.scale) ** 2
                faces = surface_area(src.data) * scale / self.voxel_size ** 2
                if faces > MAX_VOXEL_FACES:
                    self.report({'ERROR'}, "Voxel size %g would make about %s faces on %s: use a bigger size" % (
                        self.voxel_size, format_count(int(faces)), src.name))
                    return {'CANCELLED'}
        vl = context.view_layer
        active = vl.objects.active
        sculpting = current_kind(context) == 'SCULPT'
        leave_modes(context)
        made = [(src, self._high_for(context, src)) for src in sources]
        high = next((h for s, h in made if s == active), made[-1][1])
        shown = [h for _s, h in made if not h.hide_get()]
        if sculpting or shown:
            for ob in context.selected_objects:
                ob.select_set(False)
            vl.objects.active = high
        if sculpting:
            enter_sculpt(context)   # (shows a parked high poly, puts the low poly away)
            sculpt_soon(vl.objects.active.name)
        else:
            for h in shown:
                h.select_set(True)
            if shown and high.hide_get():
                vl.objects.active = shown[-1]
        return {'FINISHED'}

    def _high_for(self, context, src):
        """The high poly of `src`: the one its group has, else a new copy of it (None when it can't be made)."""
        from m3d_sculpt import uniform_scale, multires_of
        base = split_role(src.name)[0]
        p = src.m3d_pair
        group = p.group if p.role == 'LOW' and p.group else base
        p.role, p.group = 'LOW', group
        highs = group_of(context, group)[1]
        if highs:
            self.report({'INFO'}, "%s already has a high poly: %s" % (src.name, highs[0].name) + (
                " (hidden: Edit High Poly shows it)" if highs[0].hide_get() else ""))
            return highs[0]
        copy = src.copy()
        copy.data = src.data.copy()
        copy.name = base + "_high"
        copy.data.name = copy.name
        for collection in src.users_collection:
            collection.objects.link(copy)
        m3d_inputs.clear(copy)
        cp = copy.m3d_pair
        if cp.ghost:   # (the original is a wire right now)
            copy.display_type, copy.hide_select = cp.ghost, False
        cp.role, cp.group, cp.parked, cp.ghost = 'HIGH', group, False, ""
        if not uniform_scale(copy):   # Sculpt mode wants a uniform scale: applied on the copy, the low poly keeps its own
            with _on(context, copy):
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        try:
            if self.detail == 'MULTIRES':
                mod = multires_of(copy) or copy.modifiers.new("Multires", 'MULTIRES')
                with _on(context, copy):
                    for _ in range(self.levels):
                        bpy.ops.object.multires_subdivide(modifier=mod.name, mode='CATMULL_CLARK')
            elif self.detail == 'VOXEL':
                copy.data.remesh_voxel_size = self.voxel_size
                with _on(context, copy):
                    bpy.ops.object.voxel_remesh()
        except RuntimeError as err:
            self.report({'WARNING'}, "%s: %s" % (copy.name, str(err).replace("Error: ", "").strip()))
        self.report({'INFO'}, "Created %s" % copy.name)
        return copy


def edit_message(highs):
    """What Edit High Poly asks before it shows a huge mesh."""
    faces, more = format(sum(face_count(h) for h in highs), ","), len(highs) - 1
    if not more:
        return "%s has %s faces. Showing it takes a moment" % (highs[0].name, faces)
    return "%s and %d more have %s faces. Showing them takes a moment" % (highs[0].name, more, faces)


class M3D_OT_hp_edit(Operator):
    """Show the high poly of the active mesh to work on it. It is hidden again when you switch workspace"""
    bl_idname = "m3d.hp_edit"
    bl_label = "Edit High Poly"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return current_kind(context) != 'SCULPT' and all(pair_of(context, context.active_object))

    def invoke(self, context, event):
        highs = [h for h in pair_of(context, context.active_object)[1] if h.m3d_pair.parked and h.hide_get()]
        if not highs:
            return self.execute(context)
        return context.window_manager.invoke_confirm(self, event, title="Edit High Poly", confirm_text="OK",
                                                     message=edit_message(highs))

    def execute(self, context):
        vl = context.view_layer
        ob = vl.objects.active
        lows, highs = pair_of(context, ob)
        if not lows or not highs:
            return {'CANCELLED'}
        target = ob if ob.m3d_pair.role == 'HIGH' else pick_high(highs, ob.m3d_pair.group)
        leave_modes(context)
        for high in highs:
            if high.m3d_pair.parked:
                restore(high)
        for o in context.selected_objects:
            o.select_set(False)
        for high in highs:
            if not high.hide_get():
                high.select_set(True)
        vl.objects.active = target
        return {'FINISHED'}


class M3D_OT_hp_park(Operator):
    """Hide the high poly again, and select the low poly"""
    bl_idname = "m3d.hp_park"
    bl_label = "Park High Poly"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        lows, highs = pair_of(context, context.active_object)
        return bool(lows) and any(not h.hide_get() for h in highs)

    def execute(self, context):
        leave_modes(context)
        park_all(context)
        return {'FINISHED'}


class M3D_OT_hp_mark(Operator):
    """Mark the selected meshes as low poly or high poly, or clear their role"""
    bl_idname = "m3d.hp_mark"
    bl_label = "Mark High / Low Poly"
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(name="Role", default='LOW', items=(
        ('LOW', "Low Poly", "The light mesh you unwrap, paint and export"),
        ('HIGH', "High Poly", "The detailed sculpt the maps are baked from; hidden outside Sculpt when it has a low poly"),
        ('NONE', "Clear Role", "Take the meshes out of any high poly / low poly pair")))

    @classmethod
    def description(cls, _context, props):
        return {'LOW': "Mark the selected meshes as low poly, the ones you unwrap, paint and export",
                'HIGH': "Mark the selected meshes as high poly, the sculpt the maps are baked from",
                'NONE': "Take the selected meshes out of any high poly / low poly pair"}[props.role]

    @classmethod
    def poll(cls, context):
        return bool(meshes(context))

    def execute(self, context):
        for ob in meshes(context):
            set_role(ob, self.role)
        return {'FINISHED'}


class M3D_OT_hp_pair(Operator):
    """Make the active mesh the low poly and the other selected meshes its high poly (one bake group)"""
    bl_idname = "m3d.hp_pair"
    bl_label = "Pair Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return is_mesh(ob) and any(o != ob for o in meshes(context))

    def execute(self, context):
        low = context.active_object
        p = low.m3d_pair
        group = p.group if p.role == 'LOW' and p.group else split_role(low.name)[0]
        others = [o for o in meshes(context) if o != low]
        set_role(low, 'LOW', group)
        for ob in others:
            set_role(ob, 'HIGH', group)
        self.report({'INFO'}, "%s is the low poly of %d high poly mesh%s" % (low.name, len(others), "" if len(others) == 1 else "es"))
        return {'FINISHED'}


SUFFIX_STYLES = {'LOW_HIGH': ("low", "high"), 'LP_HP': ("lp", "hp"), 'LO_HI': ("lo", "hi")}   # style -> (low word, high word)


def auto_pair(context):
    """Roles and groups for the meshes of the view layer that have none and are named with a suffix (`parse_name`). Meshes
    that differ only in case belong together, and join a group that exists. Returns the groups that got meshes and, for
    the meshes that found no partner, the names ({group: (lows, highs)}, [names without a low poly], [names without a
    high poly])."""
    spelling = {g.lower(): g for g in all_groups(context)}   # groups in use, by lower case
    found = {}   # lower case base -> [(mesh, base, role)]
    for ob in context.view_layer.objects:
        if ob.type == 'MESH' and ob.library is None and ob.m3d_pair.role == 'NONE':
            base, role = split_role(ob.name)
            if role:
                found.setdefault(base.lower(), []).append((ob, base, role))
    names = []
    for key, parts in found.items():
        group = spelling.get(key) or next((b for _o, b, r in parts if r == 'LOW'), parts[0][1])
        for ob, _base, role in parts:
            set_role(ob, role, group)
        names.append(group)
    every = all_groups(context)
    touched = {g: every[g] for g in names}
    no_low = [h.name for lows, highs in touched.values() if not lows for h in highs]
    no_high = [low.name for lows, highs in touched.values() if not highs for low in lows]
    return touched, no_low, no_high


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "es" if word.endswith("sh") else "s")


def names_note(label, names, limit=4):
    return "%s: %s%s" % (label, ", ".join(names[:limit]), "" if len(names) <= limit else " and %d more" % (len(names) - limit))


class M3D_OT_hp_auto_pair(Operator):
    """Give a role and a group to the meshes of the scene whose names end in _low / _high (also _lp / _hp, _lo / _hi,
    _lowpoly / _highpoly, in any case): Sword_low and Sword_high become the group Sword. Meshes that already have a role are
    left alone"""
    bl_idname = "m3d.hp_auto_pair"
    bl_label = "Auto-Pair by Name"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        touched, no_low, no_high = auto_pair(context)
        if not touched:
            self.report({'WARNING'}, "No mesh without a role has a name ending in _low or _high")
            return {'CANCELLED'}
        paired = ["%s (%d low, %d high)" % (g, len(lows), len(highs)) for g, (lows, highs) in touched.items() if lows and highs]
        self.report({'INFO'}, "Paired " + (names_note(plural(len(paired), "group"), paired) if paired else "nothing"))
        notes = [names_note(label, names) for label, names in (("No low poly for", no_low), ("No high poly for", no_high)) if names]
        if notes:
            self.report({'WARNING'}, "; ".join(notes))
        return {'FINISHED'}


def renamed(context, style):
    """[(mesh, new name)] that give the meshes of every group the suffixes of `style`: Sword_low, Sword_high, and the words
    of a floater stay (Sword_high_bolts). A name that is taken gets _2, _3 ..."""
    low_word, high_word = SUFFIX_STYLES[style]
    taken = set(bpy.data.objects.keys())
    out = []
    for group, (lows, highs) in all_groups(context).items():
        for ob in (*lows, *highs):
            extra = parse_name(ob.name)[2]
            word = low_word if ob.m3d_pair.role == 'LOW' else high_word
            wanted = new = "%s_%s%s" % (group, word, extra)
            n = 1
            while new in taken and new != ob.name:
                n += 1
                new = "%s_%d" % (wanted, n)
            if new != ob.name:
                taken.discard(ob.name)
                taken.add(new)
                out.append((ob, new))
    return out


class M3D_OT_hp_rename(Operator):
    """Rename the meshes of every group to one style of suffixes (Sword_low, Sword_high, Sword_high_bolts), so that other
    tools find the pairs by name. The baked maps of a renamed low poly keep up"""
    bl_idname = "m3d.hp_rename"
    bl_label = "Rename to Suffixes"
    bl_options = {'REGISTER', 'UNDO'}

    style: EnumProperty(name="Style", default='LOW_HIGH', items=(
        ('LOW_HIGH', "_low / _high", "Sword_low, Sword_high"),
        ('LP_HP', "_lp / _hp", "Sword_lp, Sword_hp"),
        ('LO_HI', "_lo / _hi", "Sword_lo, Sword_hi")))

    @classmethod
    def poll(cls, context):
        return bool(all_groups(context))

    def execute(self, context):
        import m3d_bakegroups
        import m3d_texture
        todo = [(ob, ob.name, new) for ob, new in renamed(context, self.style)]
        before = {g: m3d_bakegroups.signature(*members) for g, members in all_groups(context).items()}
        with quiet(context):   # (new names are no change of the meshes: the groups don't go stale)
            for ob, old, new in todo:
                ob.name = new
                if ob.data.name == old:
                    ob.data.name = new
        for ob, old, new in todo:   # (after all the names are final: Blender may have changed one)
            if ob.m3d_pair.role == 'LOW':
                m3d_texture.rename_maps(ob, old, ob.name)
        after = all_groups(context)
        for entry in context.scene.m3d_bake_groups:   # (a baked group stays baked under its new names)
            if entry.name in after and entry.members == before.get(entry.name):
                entry.members = m3d_bakegroups.signature(*after[entry.name])
        self.report({'INFO'}, "Renamed %s" % plural(len(todo), "mesh") if todo else "The names already have these suffixes")
        return {'FINISHED'}


def unique_group(context, base):
    """`base`, or base_2, base_3 ... when a group of that name exists."""
    groups = all_groups(context)
    return next(g for g in (base, *("%s_%d" % (base, n) for n in range(2, 10000))) if g not in groups)


class M3D_OT_hp_make_pair(Operator):
    """Turn the High Poly picker of this mesh into a pair: the mesh becomes the low poly, the picked mesh its high poly"""
    bl_idname = "m3d.hp_make_pair"
    bl_label = "Make Pair"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return is_mesh(ob) and ob.m3d_pair.role == 'NONE' and ob.m3d_bake.high is not None

    def execute(self, context):
        low = context.active_object
        high = low.m3d_bake.high
        group = unique_group(context, split_role(low.name)[0])
        set_role(low, 'LOW', group)
        set_role(high, 'HIGH', group)
        low.m3d_bake.high = None
        self.report({'INFO'}, "%s is the low poly of %s (group %s)" % (low.name, high.name, group))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Show Low Poly (Sculpt Status Line)

def _show_low_changed(self, context):
    """The low poly is a wire while sculpting its high poly, or hidden."""
    if context.mode != 'SCULPT':
        return
    lows, highs = pair_of(context, context.active_object)
    if highs:
        for low in lows:
            if self.m3d_show_low:
                ghost(low)
            else:
                put_away(low)


# -----------------------------------------------------------------------------
# UI

def draw_create(layout, context, label=True):
    """The Create High Poly button (it opens the options box, like the Modeling Toolkit tools)."""
    from m3d_mode import tool_button
    if label:
        tool_button(layout, context, "Create High Poly", "m3d.hp_create", 'DUPLICATE', {})
    else:
        o = layout.operator("m3d.tool", text="", icon='DUPLICATE')
        o.idname, o.props, o.label = "m3d.hp_create", "{}", "Create High Poly"


def draw_sculpt_status(layout, context, ob, label=True):
    """Sculpt Status Line: Show Low Poly on a mesh with a pair, Create High Poly on a low poly without a high poly or on
    a mesh without a role."""
    lows, highs = pair_of(context, ob)
    if lows and highs:
        layout.prop(context.scene, "m3d_show_low", text="Show Low Poly" if label else "", icon='MOD_WIREFRAME', toggle=True)
    elif ob.m3d_pair.role != 'HIGH':
        draw_create(layout, context, label)


def draw_channel(layout, ob):
    """Channel Box row: "Bake: Low · Sword" and a menu to change the role."""
    p = ob.m3d_pair
    row = layout.row(align=True)
    row.label(text="Bake: " + ROLE_LABEL[p.role] + (" · " + p.group if p.role != 'NONE' and p.group else ""))
    row.operator_menu_enum("m3d.hp_mark", "role", text="", icon='DOWNARROW_HLT')


class M3D_MT_hplp(Menu):
    """High poly / low poly: create, edit, park, mark and pair meshes"""
    bl_label = "High / Low Poly"

    def draw(self, context):
        from m3d_mode import tool_button
        layout = self.layout
        tool_button(layout, context, "Create High Poly", "m3d.hp_create", 'DUPLICATE', {})
        layout.operator("m3d.hp_edit", icon='HIDE_OFF')
        layout.operator("m3d.hp_park", icon='HIDE_ON')
        layout.separator()
        layout.operator("m3d.hp_mark", text="Mark as High Poly").role = 'HIGH'
        layout.operator("m3d.hp_mark", text="Mark as Low Poly").role = 'LOW'
        layout.operator("m3d.hp_mark", text="Clear Role").role = 'NONE'
        layout.operator("m3d.hp_pair", icon='LINKED')
        layout.operator("m3d.hp_auto_pair", icon='LINKED')
        layout.operator_menu_enum("m3d.hp_rename", "style", text="Rename to Suffixes")


classes = (
    M3D_Pair,
    M3D_OT_hp_create,
    M3D_OT_hp_edit,
    M3D_OT_hp_park,
    M3D_OT_hp_mark,
    M3D_OT_hp_pair,
    M3D_OT_hp_auto_pair,
    M3D_OT_hp_rename,
    M3D_OT_hp_make_pair,
    M3D_MT_hplp,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.m3d_pair = PointerProperty(type=M3D_Pair)
    bpy.types.Scene.m3d_show_low = BoolProperty(
        name="Show Low Poly", update=_show_low_changed,
        description="Show the low poly as a wire while you sculpt its high poly (it cannot be selected)")
    bpy.app.handlers.load_post.append(_load_post)
    bpy.app.handlers.save_pre.append(_save_pre)


def unregister():
    bpy.app.handlers.save_pre.remove(_save_pre)
    bpy.app.handlers.load_post.remove(_load_post)
    del bpy.types.Scene.m3d_show_low
    del bpy.types.Object.m3d_pair
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
