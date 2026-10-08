# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Animation workspace (F6) for Maelstrom3D: the dock pages (Pick, Tween & Poses, Motion, Layers, Playback), the Animation
Status Line, the Animate and Poses shelves and the operators behind them (Tween, object selection sets, Blocking /
Polish presets, Euler filter, motion paths, NLA layers, Playblast).

The layout is built by tools/m3d/build_startup.py (phase5_animation), the tabs are DOCK_TABS['ANIM'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py. The pose list and the skeleton's selection sets come from
m3d_rig.py.
"""

import math
import os
import re
import tempfile
from collections import namedtuple

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot

from m3d_mode import _button
from m3d_rig import (draw_pose_library, draw_selection_sets, pose_assets, rig_of, selected_pose_bones)
from m3d_sculpt import grid, reason, split_props, viewport
from m3d_workspace import _PagePanel, current_kind, workspace_kind

# -----------------------------------------------------------------------------
# What is being animated

def posed_rig(context):
    """The skeleton in Pose Mode (its selected bones are what the animation tools act on), else None."""
    ob = context.active_object
    return ob if ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE' else None


def channel_fcurves(owner):
    """F-curves of the action the object (or ID) plays now: the slot it is assigned to."""
    ad = owner.animation_data
    bag = animdata_get_channelbag_for_assigned_slot(ad) if ad is not None and ad.action is not None else None
    return list(bag.fcurves) if bag is not None else []


Target = namedtuple("Target", "id prefix")


def targets(context):
    """What the tools act on: the selected bones of the skeleton in Pose Mode (prefix = their data path), else the
    selected objects (prefix None = every channel that is not a bone's)."""
    rig = posed_rig(context)
    if rig is not None:
        return [Target(rig, 'pose.bones["%s"]' % bpy.utils.escape_identifier(pb.name)) for pb in selected_pose_bones(rig)]
    return [Target(ob, None) for ob in (context.selected_objects or ([context.active_object] if context.active_object
                                                                      else []))]


def target_curves(context):
    """[(id, fcurve)] of the unlocked, unmuted channels of the targets."""
    out = []
    for target in targets(context):
        for fc in channel_fcurves(target.id):
            if fc.lock or fc.mute:
                continue
            if target.prefix is None:
                if fc.data_path.startswith("pose.bones["):
                    continue
            elif not fc.data_path.startswith(target.prefix + ".") and not fc.data_path.startswith(target.prefix + "["):
                continue
            out.append((target.id, fc))
    return out


_CUSTOM_PATH = re.compile(r'^(.*)\["((?:[^"\\]|\\.)*)"\]$')
_ATTR_PATH = re.compile(r'^(.*)\.(\w+)$')


def _split_path(owner_id, path):
    """(object that has the property, property name, custom?) for a data path of an ID."""
    custom = _CUSTOM_PATH.match(path)
    if custom:
        head, name, is_custom = custom.group(1), bpy.utils.unescape_identifier(custom.group(2)), True
    else:
        match = _ATTR_PATH.match(path)
        head, name, is_custom = (match.group(1), match.group(2), False) if match else ("", path, False)
    return (owner_id.path_resolve(head) if head else owner_id), name, is_custom


def get_channel(owner_id, path, index):
    owner, name, custom = _split_path(owner_id, path)
    value = owner[name] if custom else getattr(owner, name)
    try:
        return value[index]
    except TypeError:
        return value


def set_channel(owner_id, path, index, value):
    owner, name, custom = _split_path(owner_id, path)
    if custom:
        owner[name] = value
        return
    try:
        getattr(owner, name)[index] = value
    except TypeError:   # Not an array.
        setattr(owner, name, value)


# -----------------------------------------------------------------------------
# Tween: a value between the previous and the next key of each channel

TweenItem = namedtuple("TweenItem", "id path index a b")


def collect_tween(context, frame=None):
    """[TweenItem] for every channel of the targets that has a key before and a key after `frame` (the current frame):
    a and b are the channel's values at those two keys."""
    frame = context.scene.frame_current if frame is None else frame
    items = []
    for owner_id, fc in target_curves(context):
        before = [k.co.x for k in fc.keyframe_points if k.co.x < frame]
        after = [k.co.x for k in fc.keyframe_points if k.co.x > frame]
        if before and after:
            items.append(TweenItem(owner_id, fc.data_path, fc.array_index, fc.evaluate(max(before)),
                                   fc.evaluate(min(after))))
    return items


def apply_tween(items, factor):
    for it in items:
        set_channel(it.id, it.path, it.index, it.a + (it.b - it.a) * factor)


def key_tween(items, frame, key_type='BREAKDOWN'):
    for it in items:
        it.id.keyframe_insert(data_path=it.path, index=it.index, frame=frame, keytype=key_type)


KEY_TYPES = (('KEYFRAME', "Keyframe", ""), ('BREAKDOWN', "Breakdown", ""), ('MOVING_HOLD', "Moving Hold", ""),
             ('EXTREME', "Extreme", ""), ('JITTER', "Jitter", ""))
TWEEN_PIXELS = 400   # Mouse travel for the whole 0..1 range.


class M3D_OT_tween(Operator):
    """Tween: a pose between the previous and the next key of the selected bones (or objects). Move the mouse left /
right, click or Enter to key it, Esc to cancel (Ctrl snaps to tenths, Shift is slower)"""
    bl_idname = "m3d.tween"
    bl_label = "Tween"
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(name="Amount", default=0.5, min=-1.0, max=2.0,
                          description="0 is the previous key, 1 the next key, 0.5 half way")
    key_type: EnumProperty(name="Key Type", items=KEY_TYPES, default='BREAKDOWN')
    interactive: BoolProperty(name="Interactive", default=False, options={'SKIP_SAVE', 'HIDDEN'},
                              description="Drag in the viewport instead of using the Amount")
    from_dock: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'}, description="Use the dock's Tween slider")

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and context.active_object is not None

    def execute(self, context):
        items = collect_tween(context)
        if not items:
            self.report({'WARNING'}, "Nothing to tween: the selection needs a key before and after this frame")
            return {'CANCELLED'}
        factor = context.scene.m3d_anim.tween if self.from_dock else self.factor
        apply_tween(items, factor)
        key_tween(items, context.scene.frame_current, self.key_type)
        context.view_layer.update()
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.interactive:
            return self.execute(context)
        self.items = collect_tween(context)
        if not self.items:
            self.report({'WARNING'}, "Nothing to tween: the selection needs a key before and after this frame")
            return {'CANCELLED'}
        self.originals = [get_channel(it.id, it.path, it.index) for it in self.items]
        self.start_x, self.factor = event.mouse_x, 0.5
        apply_tween(self.items, self.factor)
        context.window_manager.modal_handler_add(self)
        self.status(context)
        return {'RUNNING_MODAL'}

    def status(self, context):
        context.workspace.status_text_set("Tween %d%%   click / Enter: key it   Esc / right-click: cancel   "
                                          "Ctrl: snap   Shift: fine" % round(self.factor * 100))
        if context.area is not None:
            context.area.tag_redraw()

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            span = TWEEN_PIXELS * (4 if event.shift else 1)
            factor = max(-0.5, min(1.5, 0.5 + (event.mouse_x - self.start_x) / span))
            self.factor = round(factor * 10) / 10 if event.ctrl else factor
            apply_tween(self.items, self.factor)
            self.status(context)
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            key_tween(self.items, context.scene.frame_current, self.key_type)
            context.workspace.status_text_set(None)
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            for it, value in zip(self.items, self.originals):
                set_channel(it.id, it.path, it.index, value)
            context.workspace.status_text_set(None)
            if context.area is not None:
                context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class M3D_OT_anim_revert(Operator):
    """Put the animated channels back to what their keys say at this frame (drops an unkeyed tween)"""
    bl_idname = "m3d.anim_revert"
    bl_label = "Revert to Keys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.frame_set(context.scene.frame_current)
        return {'FINISHED'}


def _tween_preview(self, context):
    """The dock slider moves the selection live (nothing is keyed until Key)."""
    apply_tween(collect_tween(context), self.tween)


# -----------------------------------------------------------------------------
# Keys: breakdown key, Euler filter, key range

class M3D_OT_anim_key_type(Operator):
    """Set a key of the chosen type (Breakdown, Extreme, Moving Hold ...); the key type setting is left as it was"""
    bl_idname = "m3d.anim_key_type"
    bl_label = "Set Key of Type"
    bl_options = {'REGISTER', 'UNDO'}

    key_type: EnumProperty(name="Type", items=KEY_TYPES, default='BREAKDOWN')

    @classmethod
    def description(cls, _context, props):
        return "Set a %s key on the selection" % props.key_type.replace("_", " ").title()

    def execute(self, context):
        ts = context.tool_settings
        before, ts.keyframe_type = ts.keyframe_type, self.key_type
        try:
            with _in_viewport(context):
                return bpy.ops.anim.keyframe_insert()
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            ts.keyframe_type = before


def unwrap_euler(fc):
    """Keys of a rotation curve that jump by more than half a turn are moved by whole turns, so the rotation takes the
    short way round. Returns the number of keys moved."""
    moved, keys = 0, fc.keyframe_points
    for prev, key in zip(keys, list(keys)[1:]):
        turns = round((key.co.y - prev.co.y) / math.tau)
        if turns:
            shift = -turns * math.tau
            key.co.y += shift
            key.handle_left.y += shift
            key.handle_right.y += shift
            moved += 1
    if moved:
        fc.update()
    return moved


class M3D_OT_anim_euler_filter(Operator):
    """Euler filter: remove 360 degree flips from the rotation keys of the selection"""
    bl_idname = "m3d.anim_euler_filter"
    bl_label = "Euler Filter"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and context.active_object is not None

    def execute(self, context):
        moved = sum(unwrap_euler(fc) for _id, fc in target_curves(context) if fc.data_path.endswith(".rotation_euler")
                    or fc.data_path == "rotation_euler")
        self.report({'INFO'}, "Euler filter: %d keys moved" % moved)
        return {'FINISHED'}


def key_range(context):
    """(first, last) frame of the keys of the targets, or None."""
    frames = [k.co.x for _id, fc in target_curves(context) for k in fc.keyframe_points]
    return (int(math.floor(min(frames))), int(math.ceil(max(frames)))) if frames else None


class M3D_OT_anim_range(Operator):
    """Playback range: from the keys of the selection (preview range), the whole scene, or the scene range itself"""
    bl_idname = "m3d.anim_range"
    bl_label = "Set Playback Range"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=(('KEYS', "Preview from Keys", "Preview range = first to last key of the selection"),
                              ('SCENE', "Scene Range", "Play the scene range (preview range off)"),
                              ('FIT', "Scene from Keys", "Scene start / end = first to last key of the selection")))

    @classmethod
    def description(cls, _context, props):
        return {'KEYS': "Preview range from the first to the last key of the selection",
                'SCENE': "Play the whole scene range (preview range off)",
                'FIT': "Scene start and end from the first to the last key of the selection"}[props.kind]

    def execute(self, context):
        scene = context.scene
        if self.kind == 'SCENE':
            scene.use_preview_range = False
            return {'FINISHED'}
        span = key_range(context)
        if span is None:
            self.report({'WARNING'}, "The selection has no keys")
            return {'CANCELLED'}
        if self.kind == 'KEYS':
            scene.frame_preview_start, scene.frame_preview_end = span
            scene.use_preview_range = True
        else:
            scene.frame_start, scene.frame_end = span
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# New key defaults (preferences): Stepped / Spline / Linear / Clamped, Blocking and Polish presets

# kind -> (interpolation, handle type or None = left alone)
INTERP = {'STEPPED': ('CONSTANT', None), 'SPLINE': ('BEZIER', 'AUTO'), 'LINEAR': ('LINEAR', None),
          'CLAMPED': ('BEZIER', 'AUTO_CLAMPED')}
INTERP_LABELS = {'STEPPED': "Stepped", 'SPLINE': "Spline", 'LINEAR': "Linear", 'CLAMPED': "Clamped"}
_prefs_before = {}   # The user's own defaults, kept while a preset or a button has changed them


def new_key_kind(context):
    """Which of INTERP the preferences use for new keys now (None for something else)."""
    edit = context.preferences.edit
    for kind, (interp, handle) in INTERP.items():
        if edit.keyframe_new_interpolation_type == interp and handle in {None, edit.keyframe_new_handle_type}:
            return kind
    return None


def set_new_key_kind(context, kind):
    """New keys get this interpolation (a Preferences setting: it applies to every file). The first change remembers the
    values to come back to."""
    edit = context.preferences.edit
    if not _prefs_before:
        _prefs_before.update(interp=edit.keyframe_new_interpolation_type, handle=edit.keyframe_new_handle_type)
    interp, handle = INTERP[kind]
    edit.keyframe_new_interpolation_type = interp
    if handle is not None:
        edit.keyframe_new_handle_type = handle


def convert_keys(context, kind):
    """Give the keys of the selection (bones in Pose Mode, else objects) the interpolation of `kind`: a new key on a curve
    with several keys copies the key before it, so the preference alone would leave the old keys as they were."""
    interp, handle = INTERP[kind]
    count = 0
    for _id, fc in target_curves(context):
        for key in fc.keyframe_points:
            key.interpolation = interp
            if handle is not None:
                key.handle_left_type = key.handle_right_type = handle
            count += 1
        fc.update()
    return count


def restore_new_key_defaults(context):
    """Back to the preferences as they were before the first change. False when nothing was changed."""
    if not _prefs_before:
        return False
    edit = context.preferences.edit
    edit.keyframe_new_interpolation_type = _prefs_before["interp"]
    edit.keyframe_new_handle_type = _prefs_before["handle"]
    _prefs_before.clear()
    return True


class M3D_OT_anim_interp(Operator):
    """Interpolation of the keys you set from now on. This is a Preferences setting: it applies to every file"""
    bl_idname = "m3d.anim_interp"
    bl_label = "New Key Interpolation"
    bl_options = {'INTERNAL'}

    kind: EnumProperty(items=[(k, v, "") for k, v in INTERP_LABELS.items()])

    @classmethod
    def description(cls, _context, props):
        return "New keys are %s: a Preferences setting that applies to every file. A key set between two others copies "                "the key before it; Blocking / Polish convert the selection's keys" % INTERP_LABELS[props.kind]

    def execute(self, context):
        set_new_key_kind(context, self.kind)
        return {'FINISHED'}


def bottom_area(screen):
    """The Graph Editor / Dope Sheet area of a screen (the biggest one; the Timeline is not one)."""
    if screen is None:
        return None
    areas = [a for a in screen.areas if a.type == 'GRAPH_EDITOR'
             or (a.type == 'DOPESHEET_EDITOR' and a.spaces.active.mode != 'TIMELINE')]
    return max(areas, key=lambda a: a.width * a.height) if areas else None


def show_editor(screen, editor):
    """Switch the bottom editor to 'GRAPH' or 'DOPESHEET'. False when the screen has none."""
    area = bottom_area(screen)
    if area is None:
        return False
    area.ui_type = {'GRAPH': 'FCURVES', 'DOPESHEET': 'DOPESHEET'}[editor]
    area.tag_redraw()
    return True


class M3D_OT_anim_editor(Operator):
    """Show the Graph Editor or the Dope Sheet in the bottom editor"""
    bl_idname = "m3d.anim_editor"
    bl_label = "Animation Editor"
    bl_options = {'INTERNAL'}

    editor: EnumProperty(items=(('GRAPH', "Graph Editor", ""), ('DOPESHEET', "Dope Sheet", "")))

    @classmethod
    def description(cls, _context, props):
        return "Show the %s in the bottom editor (Ctrl+Space maximizes it)" % ("Graph Editor" if props.editor == 'GRAPH'
                                                                              else "Dope Sheet")

    def execute(self, context):
        if not show_editor(context.screen, self.editor):
            self.report({'WARNING'}, "This workspace has no Graph Editor / Dope Sheet")
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_anim_preset(Operator):
    """Blocking: new keys are stepped, the selection's keys too, and the Dope Sheet shows. Polish: clamped splines and the
Graph Editor. Restore: your own new key defaults. The new key defaults are Preferences: they apply to every file"""
    bl_idname = "m3d.anim_preset"
    bl_label = "Animation Preset"
    bl_options = {'INTERNAL', 'UNDO'}   # Undo brings the converted keys back (Preferences are not part of undo).

    preset: EnumProperty(items=(('BLOCKING', "Blocking", "New keys are stepped; Dope Sheet"),
                                ('POLISH', "Polish", "New keys are clamped splines; Graph Editor"),
                                ('RESTORE', "Restore", "Back to your new key defaults")))

    @classmethod
    def description(cls, _context, props):
        return {'BLOCKING': "Blocking: new keys are stepped, the selection's keys become stepped, and the Dope Sheet "
                            "shows (the new key default is a Preferences setting)",
                'POLISH': "Polish: new keys are clamped splines, the selection's keys become clamped splines, and the "
                          "Graph Editor shows (the new key default is a Preferences setting)",
                'RESTORE': "Put the new key defaults back to what they were before Blocking / Polish"}[props.preset]

    def execute(self, context):
        if self.preset == 'RESTORE':
            if not restore_new_key_defaults(context):
                self.report({'INFO'}, "The new key defaults are your own already")
            return {'FINISHED'}
        blocking = self.preset == 'BLOCKING'
        kind = 'STEPPED' if blocking else 'CLAMPED'
        set_new_key_kind(context, kind)
        convert_keys(context, kind)
        show_editor(context.screen, 'DOPESHEET' if blocking else 'GRAPH')
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Settings

class M3D_AnimSetItem(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)


class M3D_AnimSet(PropertyGroup):
    """An object selection set (name is inherited)."""
    items: CollectionProperty(type=M3D_AnimSetItem)


class M3D_AnimSettings(PropertyGroup):
    """Animation workspace options (Scene.m3d_anim)."""
    tween: FloatProperty(name="Tween", default=0.5, min=-0.5, max=1.5, update=_tween_preview,
                         description="Pose between the previous key (0) and the next key (1); Key keeps it")
    sets: CollectionProperty(type=M3D_AnimSet)
    set_index: IntProperty(default=0)
    path_display: EnumProperty(name="Show", default='RANGE', items=(
        ('RANGE', "In Range", "The whole path around the current frame"),
        ('CURRENT_FRAME', "Around Frame", "Only a few frames before and after the current frame")))
    path_range: EnumProperty(name="Range", default='KEYS_ALL', items=(
        ('KEYS_ALL', "All Keys", "From the first to the last key"), ('KEYS_SELECTED', "Selected Keys", ""),
        ('SCENE', "Scene Range", ""), ('MANUAL', "Manual", "The frames set below")))
    playblast_dir: StringProperty(name="Folder", subtype='DIR_PATH', default="",
                                  description="Where the frames go (empty: a folder in the temporary directory)")
    playblast_percent: IntProperty(name="Size", default=50, min=10, max=100, subtype='PERCENTAGE',
                                   description="Playblast size as a percentage of the render resolution")
    playblast_play: BoolProperty(name="Play When Done", default=True, description="Open the player on the frames")
    playblast_note: StringProperty(description="Result of the last Playblast")


class M3D_UL_anim_sets(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_prop, _index):
        layout.prop(item, "name", text="", emboss=False, icon='GROUP')
        layout.label(text=str(len([i for i in item.items if i.object is not None])))


# -----------------------------------------------------------------------------
# Object selection sets

def set_objects(sel):
    return [i.object for i in sel.items if i.object is not None]


class M3D_OT_anim_set(Operator):
    """Object selection sets: add a set from the selection, assign / remove objects, select a set (Shift adds to the
selection)"""
    bl_idname = "m3d.anim_set"
    bl_label = "Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('ADD', "Add", ""), ('REMOVE', "Remove", ""), ('ASSIGN', "Assign", ""),
                                ('UNASSIGN', "Unassign", ""), ('SELECT', "Select", ""), ('DESELECT', "Deselect", "")))
    index: IntProperty(default=-1, description="Set to act on (-1: the active one)")
    extend: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return {'ADD': "Add a set made of the selected objects", 'REMOVE': "Remove the set (not its objects)",
                'ASSIGN': "Add the selected objects to the set", 'UNASSIGN': "Take the selected objects out of the set",
                'SELECT': "Select the objects of the set (Shift adds them to the selection)",
                'DESELECT': "Deselect the objects of the set"}[props.action]

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        s = context.scene.m3d_anim
        if self.action == 'ADD':
            sel = s.sets.add()
            sel.name = "Set %d" % len(s.sets)
            s.set_index = len(s.sets) - 1
            for ob in context.selected_objects:
                sel.items.add().object = ob
            return {'FINISHED'}
        index = s.set_index if self.index < 0 else self.index
        if not 0 <= index < len(s.sets):
            self.report({'WARNING'}, "No selection set")
            return {'CANCELLED'}
        sel = s.sets[index]
        members = set_objects(sel)
        if self.action == 'REMOVE':
            s.sets.remove(index)
            s.set_index = max(0, min(s.set_index, len(s.sets) - 1))
        elif self.action == 'ASSIGN':
            for ob in context.selected_objects:
                if ob not in members:
                    sel.items.add().object = ob
        elif self.action == 'UNASSIGN':
            chosen = set(context.selected_objects)
            for i in reversed(range(len(sel.items))):
                if sel.items[i].object in chosen or sel.items[i].object is None:
                    sel.items.remove(i)
        else:
            layer = context.view_layer
            if self.action == 'SELECT' and not self.extend:
                for ob in layer.objects:
                    if ob.select_get(view_layer=layer):
                        ob.select_set(False, view_layer=layer)
            for ob in members:
                if ob.name in layer.objects and not ob.hide_get(view_layer=layer):
                    ob.select_set(self.action == 'SELECT', view_layer=layer)
            visible = [ob for ob in members if ob.name in layer.objects and not ob.hide_get(view_layer=layer)]
            if self.action == 'SELECT' and visible:
                layer.objects.active = visible[0]
        return {'FINISHED'}


class M3D_OT_anim_pick_bones(Operator):
    """Select the bones of a bone collection (Shift adds them to the selection)"""
    bl_idname = "m3d.anim_pick_bones"
    bl_label = "Select Collection"
    bl_options = {'REGISTER', 'UNDO'}

    collection: StringProperty()
    extend: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return posed_rig(context) is not None

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        rig = posed_rig(context)
        coll = rig.data.collections_all.get(self.collection)
        if coll is None:
            return {'CANCELLED'}
        if not self.extend:
            for pb in rig.pose.bones:
                pb.select = False
        bones = [b for b in coll.bones if b.name in rig.pose.bones and not b.hide]
        for bone in bones:
            rig.pose.bones[bone.name].select = True
        if bones:
            rig.data.bones.active = bones[0]
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Motion paths and ghost curves

def _in_viewport(context):
    """Context override for operators that want a 3D Viewport (the dock has none)."""
    if context.area is not None and context.area.type == 'VIEW_3D':
        return context.temp_override()
    area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        return context.temp_override()
    return context.temp_override(area=area, region=next(r for r in area.regions if r.type == 'WINDOW'),
                                 space_data=area.spaces.active)


class M3D_OT_anim_paths(Operator):
    """Motion paths of the selected bones (Pose Mode) or objects: calculate, update or clear"""
    bl_idname = "m3d.anim_paths"
    bl_label = "Motion Paths"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('CALCULATE', "Calculate", ""), ('UPDATE', "Update", ""), ('CLEAR', "Clear", "")))

    @classmethod
    def description(cls, _context, props):
        return {'CALCULATE': "Draw the path the selection moves along (range and display are set above)",
                'UPDATE': "Recalculate the paths after editing the animation",
                'CLEAR': "Remove the paths of the selection"}[props.action]

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and context.active_object is not None

    def execute(self, context):
        s = context.scene.m3d_anim
        group = bpy.ops.pose if posed_rig(context) is not None else bpy.ops.object
        try:
            with _in_viewport(context):
                if self.action == 'CALCULATE':
                    group.paths_calculate(display_type=s.path_display, range=s.path_range)
                elif self.action == 'UPDATE':
                    group.paths_update()
                else:
                    group.paths_clear(only_selected=True)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_anim_graph(Operator):
    """Ghost curves: keep a copy of the curves in the Graph Editor to compare with while you edit (clear removes them)"""
    bl_idname = "m3d.anim_graph"
    bl_label = "Ghost Curves"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('GHOST_CREATE', "Create", ""), ('GHOST_CLEAR', "Clear", "")))

    def execute(self, context):
        area = bottom_area(context.screen)
        if area is None:
            self.report({'WARNING'}, "This workspace has no Graph Editor")
            return {'CANCELLED'}
        before = area.ui_type
        area.ui_type = 'FCURVES'   # The operators work in the Graph Editor: it shows while they run.
        win = context.window or context.window_manager.windows[0]
        try:
            with context.temp_override(window=win, screen=context.screen, area=area, space_data=area.spaces.active,
                                       region=next(r for r in area.regions if r.type == 'WINDOW')):
                getattr(bpy.ops.graph, {'GHOST_CREATE': 'ghost_curves_create', 'GHOST_CLEAR': 'ghost_curves_clear'}[self.action])()
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            area.ui_type = before
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Layers: NLA tracks

def layer_owner(context):
    """The object the layer tools act on: the active object (a skeleton in Pose Mode too), else a selected one."""
    return context.active_object or next(iter(context.selected_objects), None)


def push_down(ob):
    """The object's current action becomes a strip on a new NLA track. Returns the track, or None without an action."""
    ad = ob.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action
    track = ad.nla_tracks.new()
    track.name = action.name
    track.strips.new(action.name, int(action.frame_range[0]), action)
    ad.action = None
    return track


def add_additive_layer(ob):
    """Push the current action down (if there is one) and start an empty action on top that adds to the layers below.
    Returns the new action."""
    if ob.animation_data is None:
        ob.animation_data_create()
    push_down(ob)
    ad = ob.animation_data
    action = bpy.data.actions.new("%s_Layer" % ob.name)
    ad.action = action
    ad.action_blend_type = 'ADD'
    ad.action_influence = 1.0
    return action


class M3D_OT_anim_layer(Operator):
    """Layers (NLA tracks): push the action down, add an additive layer, edit a layer, remove a track"""
    bl_idname = "m3d.anim_layer"
    bl_label = "Layer"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('PUSH_DOWN', "Push Down", ""), ('ADD_ADDITIVE', "Add Additive Layer", ""),
                                ('TWEAK', "Edit Layer", ""), ('EXIT_TWEAK', "Done Editing", ""),
                                ('REMOVE', "Remove Track", "")))
    index: IntProperty(default=0, description="Track to act on")

    @classmethod
    def description(cls, _context, props):
        return {'PUSH_DOWN': "Put the current action on its own layer (an NLA track) and start fresh",
                'ADD_ADDITIVE': "Push the action down and start an empty layer on top that adds to the layers below",
                'TWEAK': "Edit the keys of this layer (the layers above it are muted meanwhile)",
                'EXIT_TWEAK': "Leave layer editing", 'REMOVE': "Remove this layer's track"}[props.action]

    @classmethod
    def poll(cls, context):
        return layer_owner(context) is not None

    def execute(self, context):
        ob = layer_owner(context)
        ad = ob.animation_data
        if self.action == 'ADD_ADDITIVE':
            add_additive_layer(ob)
        elif self.action == 'PUSH_DOWN':
            if push_down(ob) is None:
                self.report({'WARNING'}, "%s has no action to push down" % ob.name)
                return {'CANCELLED'}
        elif ad is None:
            return {'CANCELLED'}
        elif self.action == 'EXIT_TWEAK':
            ad.use_tweak_mode = False
        elif not 0 <= self.index < len(ad.nla_tracks):
            return {'CANCELLED'}
        elif self.action == 'REMOVE':
            ad.nla_tracks.remove(ad.nla_tracks[self.index])
        else:
            track = ad.nla_tracks[self.index]
            if not track.strips:
                return {'CANCELLED'}
            for t in ad.nla_tracks:
                t.select = t == track
                for strip in t.strips:
                    strip.select = t == track
            ad.nla_tracks.active = track
            ad.use_tweak_mode = True
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Playblast: the viewport rendered frame by frame into a folder

def playblast_folder(scene):
    s = scene.m3d_anim
    return bpy.path.abspath(s.playblast_dir) if s.playblast_dir else os.path.join(tempfile.gettempdir(), "m3d_playblast")


def playblast_frames(scene):
    """Frames to play: the preview range when it is on, else the scene range."""
    return (scene.frame_preview_start, scene.frame_preview_end) if scene.use_preview_range \
        else (scene.frame_start, scene.frame_end)


def snapshot_render(scene):
    """The render settings a playblast changes (the user's output settings are put back afterwards)."""
    r = scene.render
    return {"render": {k: getattr(r, k) for k in ("filepath", "resolution_percentage", "use_file_extension")},
            "image": {k: getattr(r.image_settings, k) for k in ("media_type", "file_format", "color_mode")},
            "scene": {k: getattr(scene, k) for k in ("frame_start", "frame_end", "frame_current")}}


def restore_render(scene, snap):
    r = scene.render
    for k, v in snap["render"].items():
        setattr(r, k, v)
    for k in ("media_type", "file_format", "color_mode"):   # In this order: the format depends on the media type.
        setattr(r.image_settings, k, snap["image"][k])
    for k, v in snap["scene"].items():
        setattr(scene, k, v)
    scene.frame_set(snap["scene"]["frame_current"])


def configure_playblast(scene, folder, percent):
    """PNG frames at `percent` of the render size, no file extension surprises."""
    r = scene.render
    r.resolution_percentage = percent
    r.use_file_extension = True
    r.image_settings.media_type = 'IMAGE'
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGB'
    os.makedirs(folder, exist_ok=True)


def playblast_area(screen):
    """The 3D Viewport to render: a camera view when the workspace has one, else the biggest viewport."""
    views = [a for a in screen.areas if a.type == 'VIEW_3D']
    cams = [a for a in views if a.spaces.active.region_3d.view_perspective == 'CAMERA']
    pool = cams or views
    return max(pool, key=lambda a: a.width * a.height) if pool else None


playblast_state = {"running": False, "files": [], "folder": ""}


class M3D_OT_playblast(Operator):
    """Playblast: render the viewport (the camera view when there is one) over the playback range into a folder, then play
it. The render output settings are put back afterwards. Esc cancels"""
    bl_idname = "m3d.playblast"
    bl_label = "Playblast"
    bl_options = {'REGISTER'}

    play: BoolProperty(name="Play", default=True, options={'SKIP_SAVE'}, description="Open the player when done")

    @classmethod
    def poll(cls, context):
        return not playblast_state["running"] and context.screen is not None \
            and any(a.type == 'VIEW_3D' for a in context.screen.areas)

    def invoke(self, context, _event):
        scene = context.scene
        self.area = playblast_area(context.screen)
        self.window = context.window or context.window_manager.windows[0]
        self.folder = playblast_folder(scene)
        self.base = bpy.path.clean_name(bpy.path.display_name_from_filepath(bpy.data.filepath) or "playblast")
        self.snap = snapshot_render(scene)
        first, last = playblast_frames(scene)
        self.frames = list(range(first, last + 1))
        try:
            configure_playblast(scene, self.folder, scene.m3d_anim.playblast_percent)
        except OSError as err:
            restore_render(scene, self.snap)
            self.report({'ERROR'}, "Playblast folder: %s" % err)
            return {'CANCELLED'}
        for old in os.listdir(self.folder):   # A new playblast replaces the last one.
            if old.startswith(self.base + "_") and old.endswith(".png"):
                os.remove(os.path.join(self.folder, old))
        playblast_state.update(running=True, files=[], folder=self.folder)
        scene.m3d_anim.playblast_note = ""
        self.timer = context.window_manager.event_timer_add(0.05, window=self.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            return self.finish(context, "Playblast cancelled", cancelled=True)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if not self.frames:
            return self.finish(context, "Playblast: %d frames in %s" % (len(playblast_state["files"]), self.folder))
        frame = self.frames.pop(0)
        scene = context.scene
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(self.folder, "%s_%04d" % (self.base, frame))
        context.workspace.status_text_set("Playblast: frame %d (Esc cancels)" % frame)
        try:
            region = next(r for r in self.area.regions if r.type == 'WINDOW')
            with context.temp_override(window=self.window, screen=context.screen, area=self.area, region=region,
                                       space_data=self.area.spaces.active):
                bpy.ops.render.opengl(write_still=True, view_context=True)
        except RuntimeError as err:
            return self.finish(context, "Playblast failed: %s" % str(err).strip(), cancelled=True)
        path = scene.render.filepath + ".png"
        if os.path.exists(path):
            playblast_state["files"].append(path)
        return {'RUNNING_MODAL'}

    def finish(self, context, message, cancelled=False):
        scene = context.scene
        context.window_manager.event_timer_remove(self.timer)
        context.workspace.status_text_set(None)
        files = playblast_state["files"]
        if self.play and files and not cancelled:
            scene.render.filepath = os.path.join(self.folder, self.base + "_####")
            scene.frame_start, scene.frame_end = playblast_frames(scene)
            try:
                bpy.ops.render.play_rendered_anim()
            except RuntimeError:
                pass   # The player is not essential: the frames are in the folder.
        restore_render(scene, self.snap)
        playblast_state["running"] = False
        scene.m3d_anim.playblast_note = message
        self.report({'WARNING'} if cancelled else {'INFO'}, message)
        return {'CANCELLED'} if cancelled else {'FINISHED'}


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

# What a page needs. need -> (message, button label, icon, operator, properties)
FIXES = {
    'OBJ': ("Select an object to animate", "Select All", 'SELECT_EXTEND', "object.select_all", {"action": 'SELECT'}),
    'POSE': ("Enter Pose Mode to work on bones", "Pose Mode", 'POSE_HLT', "m3d.rig_mode", {"mode": 'POSE'}),
}


def has(context, need):
    return {'OBJ': lambda: bool(context.selected_objects or context.active_object is not None),
            'POSE': lambda: posed_rig(context) is not None}[need]()


def missing(context, needs):
    return [n for n in needs if not has(context, n)]


def ready(context, needs):
    return not missing(context, needs)


def draw_fixes(layout, context, needs):
    col = layout.column(align=True)
    for key in missing(context, needs):
        text, label, icon, idname, props = FIXES[key]
        col.label(text=text)
        _button(col, context, label, idname, icon, props)
        if key == 'OBJ':
            break


class _Page(_PagePanel):
    """Panel that needs `needs` (see `FIXES`): the page shows a message with fix buttons until they are met."""
    needs = ()

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.needs)


def _gate(page, needs):
    def draw(self, context):
        draw_fixes(self.layout, context, needs)
    return type("PROPERTIES_PT_m3d_an_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Animation", "bl_options": {'HIDE_HEADER'}, "page": "anim_" + page,
        "page_poll": classmethod(lambda cls, context: not ready(context, needs)), "draw": draw})


GATES = {"tween": ('OBJ',), "motion": ('OBJ',), "layers": ('OBJ',)}
PAGE_GATES = tuple(_gate(page, needs) for page, needs in GATES.items())


# --- Pick

class _Pick(_Page):
    page = "anim_pick"


def _rig(context):
    return posed_rig(context) or rig_of(context)


class PROPERTIES_PT_m3d_an_bone_sets(_Pick, Panel):
    bl_label = "Bone Selection Sets"

    @classmethod
    def page_poll(cls, context):
        rig = _rig(context)
        return rig is not None and rig.pose is not None

    def draw(self, context):
        layout = self.layout
        rig = _rig(context)
        draw_selection_sets(layout, context, rig)
        if len(rig.selection_sets):
            flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
            flow.enabled = context.mode == 'POSE'
            for i, sel in enumerate(rig.selection_sets):
                _button(flow, context, sel.name, "pose.selection_set_select", 'NONE', {"selection_set_index": i})


class PROPERTIES_PT_m3d_an_object_sets(_Pick, Panel):
    bl_label = "Object Selection Sets"

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_anim
        row = layout.row()
        row.template_list("M3D_UL_anim_sets", "", s, "sets", s, "set_index", rows=4 if len(s.sets) else 1)
        col = row.column(align=True)
        col.operator("m3d.anim_set", icon='ADD', text="").action = 'ADD'
        col.operator("m3d.anim_set", icon='REMOVE', text="").action = 'REMOVE'
        row = layout.row(align=True)
        for action, label in (('ASSIGN', "Assign"), ('UNASSIGN', "Remove"), ('SELECT', "Select"), ('DESELECT', "Deselect")):
            row.operator("m3d.anim_set", text=label).action = action
        if len(s.sets):
            flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
            for i, sel in enumerate(s.sets):
                o = flow.operator("m3d.anim_set", text=sel.name)
                o.action, o.index = 'SELECT', i
            layout.label(text="Shift-click adds to the selection")
        else:
            reason(layout, "Select objects, then add a set")


class PROPERTIES_PT_m3d_an_collections(_Pick, Panel):
    bl_label = "Bone Collections"

    @classmethod
    def page_poll(cls, context):
        rig = _rig(context)
        return rig is not None and len(rig.data.collections_all) > 0

    def draw(self, context):
        layout = self.layout
        rig = _rig(context)
        col = layout.column(align=True)
        for coll in list(rig.data.collections_all)[:40]:
            row = col.row(align=True)
            row.prop(coll, "is_visible", text="", icon='HIDE_OFF' if coll.is_visible else 'HIDE_ON')
            sub = row.row(align=True)
            sub.enabled = context.mode == 'POSE'
            sub.operator("m3d.anim_pick_bones", text=coll.name).collection = coll.name
        if context.mode != 'POSE':
            reason(layout, "Enter Pose Mode to pick bones")
        else:
            layout.label(text="Shift-click adds to the selection")


# --- Tween & Poses

class _Tween(_Page):
    page = "anim_tween"
    needs = ('OBJ',)


class PROPERTIES_PT_m3d_an_tween(_Tween, Panel):
    bl_label = "Tween"

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_anim
        layout.prop(s, "tween", slider=True)
        row = layout.row(align=True)
        for pct in (0, 25, 50, 75, 100):
            o = row.operator("m3d.tween", text="%d" % pct)
            o.factor, o.interactive = pct / 100, False
        row = layout.row(align=True)
        row.scale_y = 1.2
        o = row.operator("m3d.tween", text="Key", icon='KEY_HLT')
        o.from_dock, o.interactive = True, False
        row.operator("m3d.anim_revert", text="Revert", icon='LOOP_BACK')
        layout.operator("m3d.tween", text="Tween in the Viewport (Alt+Q)", icon='ARROW_LEFTRIGHT').interactive = True
        if not collect_tween(context):
            reason(layout, "Needs keys before and after this frame (S sets a key)")
        else:
            layout.label(text="0 = previous key, 1 = next key; the key is a breakdown")


class PROPERTIES_PT_m3d_an_inbetween(_Tween, Panel):
    bl_label = "Push, Relax, Breakdown"

    def draw(self, context):
        layout = self.layout
        if not has(context, 'POSE'):
            draw_fixes(layout, context, ('POSE',))
            return
        grid(layout, context, (
            ("Push", "pose.push", 'TRIA_UP', {}),
            ("Relax", "pose.relax", 'TRIA_DOWN', {}),
            ("Breakdown", "pose.breakdown", 'KEYTYPE_BREAKDOWN_VEC', {}),
            ("To Neighbor", "pose.blend_to_neighbor", 'NEXT_KEYFRAME', {}),
            ("To Rest", "pose.blend_with_rest", 'LOOP_BACK', {}),
        ), columns=2)
        layout.label(text="Drag in the viewport, click to keep (Alt+Shift+P / R / B)")


class PROPERTIES_PT_m3d_an_poses(_Tween, Panel):
    bl_label = "Poses"

    def draw(self, context):
        layout = self.layout
        rig = _rig(context)
        if rig is None:
            reason(layout, "Poses need a skeleton")
            return
        if not has(context, 'POSE'):
            draw_fixes(layout, context, ('POSE',))
        grid(layout, context, (
            ("Copy", "pose.copy", 'COPYDOWN', {}),
            ("Paste", "pose.paste", 'PASTEDOWN', {}),
            ("Flipped", "pose.paste", 'PASTEFLIPDOWN', {"flipped": True}),
        ), columns=3)
        split_props(layout)
        layout.prop(context.scene.m3d_rig, "pose_name")
        layout.operator("m3d.rig_pose_save", icon='ASSET_MANAGER')
        draw_pose_library(layout, context)


# --- Motion

class _Motion(_Page):
    page = "anim_motion"
    needs = ('OBJ',)


def path_settings(context):
    """The motion path settings of what is animated: the pose in Pose Mode, else the active object."""
    owner = posed_rig(context)
    owner = owner.pose if owner is not None else context.active_object
    return owner.animation_visualization.motion_path if owner is not None else None


class PROPERTIES_PT_m3d_an_paths(_Motion, Panel):
    bl_label = "Motion Paths"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_anim
        mp = path_settings(context)
        layout.prop(s, "path_display")
        layout.prop(s, "path_range")
        if mp is not None and s.path_range == 'MANUAL':
            layout.prop(mp, "frame_start")
            layout.prop(mp, "frame_end")
        if mp is not None:
            layout.prop(mp, "frame_step")
        row = layout.row(align=True)
        row.scale_y = 1.2
        for action, label, icon in (('CALCULATE', "Calculate", 'ANIM_DATA'), ('UPDATE', "Update", 'FILE_REFRESH'),
                                    ('CLEAR', "Clear", 'X')):
            sub = row.row(align=True)
            sub.enabled = action == 'CALCULATE' or (mp is not None and mp.has_motion_paths)
            sub.operator("m3d.anim_paths", text=label, icon=icon).action = action
        if mp is not None:
            row = layout.row(align=True)
            row.prop(mp, "show_frame_numbers", toggle=True)
            row.prop(mp, "show_keyframe_numbers", toggle=True)
        space = viewport(context)
        if space is not None:
            layout.prop(space.overlay, "show_motion_paths", text="Show Paths in the Viewport", toggle=True)
        layout.label(text=("Bones" if posed_rig(context) is not None else "Objects") + ": the selected ones")


class PROPERTIES_PT_m3d_an_ghost(_Motion, Panel):
    bl_label = "Ghost Curves"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("m3d.anim_graph", text="Create", icon='GHOST_ENABLED').action = 'GHOST_CREATE'
        row.operator("m3d.anim_graph", text="Clear", icon='GHOST_DISABLED').action = 'GHOST_CLEAR'
        layout.label(text="A copy of the curves to compare in the Graph Editor")


# --- Layers

class _Layers(_Page):
    page = "anim_layers"
    needs = ('OBJ',)


class PROPERTIES_PT_m3d_an_layers(_Layers, Panel):
    bl_label = "Layers"

    def draw(self, context):
        layout = self.layout
        ob = layer_owner(context)
        ad = ob.animation_data
        layout.label(text="Layers are NLA tracks: each pushed action is one layer", icon='NLA')
        tweak = ad is not None and ad.use_tweak_mode
        col = layout.column(align=True)
        col.scale_y = 1.2
        sub = col.row(align=True)
        sub.enabled = not tweak and ad is not None and ad.action is not None
        sub.operator("m3d.anim_layer", text="Push Down", icon='NLA_PUSHDOWN').action = 'PUSH_DOWN'
        sub = col.row(align=True)
        sub.enabled = not tweak
        sub.operator("m3d.anim_layer", text="Add Additive Layer", icon='ADD').action = 'ADD_ADDITIVE'
        if ad is None:
            reason(layout, "%s has no animation yet" % ob.name)
            return
        if ad.action is not None and not tweak:
            box = layout.box()
            box.label(text="Top: " + ad.action.name, icon='ACTION')
            box.prop(ad, "action_blend_type", text="Blend")
            box.prop(ad, "action_influence", text="Influence", slider=True)
        if ad.nla_tracks:
            col = layout.column(align=True)
            for i, track in enumerate(ad.nla_tracks):
                row = col.row(align=True)
                row.prop(track, "mute", text="", icon='CHECKBOX_DEHLT' if track.mute else 'CHECKBOX_HLT', emboss=False)
                row.prop(track, "name", text="")
                row.prop(track, "is_solo", text="", icon='SOLO_ON' if track.is_solo else 'SOLO_OFF')
                sub = row.row(align=True)
                sub.enabled = not tweak
                o = sub.operator("m3d.anim_layer", text="Edit")
                o.action, o.index = 'TWEAK', i
                o = sub.operator("m3d.anim_layer", text="", icon='X')
                o.action, o.index = 'REMOVE', i
        else:
            reason(layout, "No layers yet: Push Down puts the action on one")
        if tweak:
            layout.operator("m3d.anim_layer", text="Done Editing", icon='CHECKMARK').action = 'EXIT_TWEAK'


class PROPERTIES_PT_m3d_an_bake(_Layers, Panel):
    bl_label = "Bake"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        first, last = playblast_frames(scene)
        mode = {"bake_types": {'POSE'} if posed_rig(context) is not None else {'OBJECT'}}
        _button(layout, context, "Bake Layers to One Action", "nla.bake", 'NLA',
                {"frame_start": first, "frame_end": last, "visual_keying": True, **mode})
        layout.label(text="Bakes the selection over the playback range")


# --- Playback

class _Playback(_Page):
    page = "anim_playback"


class PROPERTIES_PT_m3d_an_range(_Playback, Panel):
    bl_label = "Range"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        scene = context.scene
        layout.prop(scene, "frame_start")
        layout.prop(scene, "frame_end")
        layout.prop(scene, "use_preview_range", text="Preview Range")
        if scene.use_preview_range:
            layout.prop(scene, "frame_preview_start", text="Start")
            layout.prop(scene, "frame_preview_end", text="End")
        layout.prop(scene.render, "fps")
        row = layout.row(align=True)
        for kind, label in (('KEYS', "Range from Keys"), ('FIT', "Scene from Keys"), ('SCENE', "Scene Range")):
            row.operator("m3d.anim_range", text=label).kind = kind


class PROPERTIES_PT_m3d_an_blocking(_Playback, Panel):
    bl_label = "Blocking / Polish"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.scale_y = 1.3
        kind = new_key_kind(context)
        row.operator("m3d.anim_preset", text="Blocking", depress=kind == 'STEPPED').preset = 'BLOCKING'
        row.operator("m3d.anim_preset", text="Polish", depress=kind == 'CLAMPED').preset = 'POLISH'
        layout.label(text="New keys:")
        row = layout.row(align=True)
        for k, label in INTERP_LABELS.items():
            row.operator("m3d.anim_interp", text=label, depress=kind == k).kind = k
        if _prefs_before:
            layout.operator("m3d.anim_preset", text="Restore My Defaults", icon='LOOP_BACK').preset = 'RESTORE'
        layout.label(text="Blocking / Polish also convert the selection's keys")
        layout.label(text="New keys copy the key before them; the default is a Preference")


class PROPERTIES_PT_m3d_an_playback(_Playback, Panel):
    bl_label = "Playback"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        scene = context.scene
        layout.prop(scene, "playback_loop_mode", text="Loop")
        layout.prop(scene, "allow_preroll")
        layout.prop(scene, "sync_mode", text="Sync")
        layout.prop(scene, "use_audio_scrub")


class PROPERTIES_PT_m3d_an_playblast(_Playback, Panel):
    bl_label = "Playblast"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_anim
        first, last = playblast_frames(context.scene)
        layout.prop(s, "playblast_dir")
        layout.prop(s, "playblast_percent")
        layout.prop(s, "playblast_play")
        sub = layout.row()
        sub.scale_y = 1.3
        sub.operator("m3d.playblast", icon='RENDER_ANIMATION').play = s.playblast_play
        layout.label(text="Frames %d - %d, PNG, %s" % (first, last, playblast_folder(context.scene)))
        if s.playblast_note:
            layout.label(text=s.playblast_note)


# --- Channel Box hint: no camera for the camera view

class PROPERTIES_PT_m3d_an_camera(Panel):
    """The Animation workspace's camera view needs a scene camera"""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "channel_box"
    bl_label = "Camera"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return current_kind(context) == 'ANIM' and context.scene.camera is None

    def draw(self, context):
        reason(self.layout, "No camera: the camera view is empty")
        _button(self.layout, context, "Add Camera", "object.camera_add", 'CAMERA_DATA', {})


# -----------------------------------------------------------------------------
# Status Line

KEY_TYPE_ICONS = (('KEYFRAME', 'KEYTYPE_KEYFRAME_VEC'), ('BREAKDOWN', 'KEYTYPE_BREAKDOWN_VEC'),
                  ('EXTREME', 'KEYTYPE_EXTREME_VEC'), ('MOVING_HOLD', 'KEYTYPE_MOVING_HOLD_VEC'))


class M3D_PT_anim_autokey(Panel):
    """Auto Key options"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Auto Key"
    bl_ui_units_x = 10

    def draw(self, context):
        layout = self.layout
        ts = context.tool_settings
        layout.active = ts.use_keyframe_insert_auto
        layout.prop(ts, "auto_keying_mode", expand=True)
        col = layout.column(align=True)
        col.prop(ts, "use_keyframe_insert_keyingset", text="Only Active Keying Set")
        col.prop(ts, "use_keyframe_cycle_aware")
        if not context.preferences.edit.use_keyframe_insert_available:
            col.prop(ts, "use_record_with_nla", text="Layered Recording")


def draw_status_line(layout, context):
    """Animation Status Line: file, Object / Pose, Auto Key (+ options), key type, new key interpolation, keying set,
    playback range, FPS, loop mode, Graph / Dope Sheet, Blocking / Polish, Playblast."""
    from m3d_ui import draw_file_buttons, draw_workspace_picker
    scene, ts = context.scene, context.tool_settings
    draw_file_buttons(layout)
    row = layout.row(align=True)
    for mode, icon, label, modes in (('OBJECT', 'OBJECT_DATAMODE', "Object", {'OBJECT'}),
                                     ('POSE', 'POSE_HLT', "Pose", {'POSE'})):
        row.operator("m3d.rig_mode", text=label, icon=icon, depress=context.mode in modes).mode = mode

    row = layout.row(align=True)
    row.prop(ts, "use_keyframe_insert_auto", text="Auto Key", icon='RECORD_ON' if ts.use_keyframe_insert_auto
             else 'RECORD_OFF', toggle=True)
    row.popover(panel="M3D_PT_anim_autokey", text="")
    row = layout.row(align=True)
    for key_type, icon in KEY_TYPE_ICONS:
        row.prop_enum(ts, "keyframe_type", key_type, text="", icon=icon)

    row = layout.row(align=True)
    row.label(text="New keys:")   # A Preferences setting (every file): the tooltips say so.
    kind = new_key_kind(context)
    for k, label in INTERP_LABELS.items():
        row.operator("m3d.anim_interp", text=label, depress=kind == k).kind = k
    row = layout.row(align=True)
    row.operator("m3d.anim_preset", text="Blocking", depress=kind == 'STEPPED').preset = 'BLOCKING'
    row.operator("m3d.anim_preset", text="Polish", depress=kind == 'CLAMPED').preset = 'POLISH'

    row = layout.row(align=True)
    row.scale_x = 1.1
    row.prop_search(scene.keying_sets_all, "active", scene, "keying_sets_all", text="")

    row = layout.row(align=True)
    row.scale_x = 0.8
    if scene.use_preview_range:
        row.prop(scene, "frame_preview_start", text="")
        row.prop(scene, "frame_preview_end", text="")
    else:
        row.prop(scene, "frame_start", text="")
        row.prop(scene, "frame_end", text="")
    row.prop(scene, "use_preview_range", text="", icon='PREVIEW_RANGE')
    row = layout.row(align=True)
    row.scale_x = 0.9
    row.prop(scene.render, "fps", text="FPS")
    row.prop(scene, "playback_loop_mode", text="")

    row = layout.row(align=True)
    area = bottom_area(context.screen)
    graph = area is not None and area.type == 'GRAPH_EDITOR'
    row.operator("m3d.anim_editor", text="Graph", icon='GRAPH', depress=graph).editor = 'GRAPH'
    row.operator("m3d.anim_editor", text="Dope Sheet", icon='ACTION', depress=area is not None and not graph).editor = 'DOPESHEET'
    layout.operator("m3d.playblast", text="Playblast", icon='RENDER_ANIMATION').play = scene.m3d_anim.playblast_play
    draw_workspace_picker(layout, context)


# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

def _pose_menu(row, _context):
    row.menu("M3D_MT_anim_poses", text="Apply Pose", icon='POSE_HLT')


SHELF_ANIMATE = [
    ("anim.keyframe_insert", 'KEY_HLT', {}, "Set Key"),
    ("anim.keyframe_insert_by_name", 'CON_LOCLIKE', {"type": 'Location'}, "Translate"),
    ("anim.keyframe_insert_by_name", 'CON_ROTLIKE', {"type": 'Rotation'}, "Rotate"),
    ("anim.keyframe_insert_by_name", 'CON_SIZELIKE', {"type": 'Scaling'}, "Scale"),
    ("m3d.anim_key_type", 'KEYTYPE_BREAKDOWN_VEC', {"key_type": 'BREAKDOWN'}, "Breakdown"),
    ("anim.keyframe_delete_v3d", 'KEY_DEHLT', {}, "Delete Key"),
    None,
    ("m3d.anim_euler_filter", 'DRIVER_ROTATIONAL_DIFFERENCE', {}, "Euler Filter"),
    ("m3d.set_tangents", 'IPO_CONSTANT', {"kind": 'STEPPED'}, "Stepped"),
    ("m3d.set_tangents", 'IPO_BEZIER', {"kind": 'SPLINE'}, "Spline"),
]
SHELF_POSES = [
    ("pose.copy", 'COPYDOWN', {}, "Copy"),
    ("pose.paste", 'PASTEDOWN', {}, "Paste"),
    ("pose.paste", 'PASTEFLIPDOWN', {"flipped": True}, "Paste Flipped"),
    None,
    ("m3d.rig_reset_pose", 'LOOP_BACK', {}, "Reset"),
    ("m3d.rig_pose_save", 'ASSET_MANAGER', {}, "Save Pose"),
    _pose_menu,
]


class M3D_MT_anim_poses(bpy.types.Menu):
    """Pose Library: apply a saved pose"""
    bl_label = "Apply Pose"

    def draw(self, context):
        layout = self.layout
        poses = pose_assets()
        for action in poses[:30]:
            o = layout.operator("m3d.rig_pose_apply", text=action.name, icon='POSE_HLT')
            o.name, o.flipped = action.name, False
        if not poses:
            layout.label(text="No poses saved in this file yet")


# -----------------------------------------------------------------------------
# Playback redraw and workspace hook

def limit_playback_redraw(screen):
    """While playing: the viewports and the animation editors redraw, the Properties editors (Channel Box, dock) do not."""
    screen.use_play_properties_editors = False
    for name in ("use_play_image_editors", "use_play_node_editors", "use_play_sequence_editors", "use_play_clip_editors",
                 "use_play_spreadsheet_editors"):
        setattr(screen, name, False)
    screen.use_play_3d_editors = screen.use_play_animation_editors = screen.use_play_top_left_3d_editor = True


def follow(wm):
    """Workspace timer: an Animation workspace from an older file gets the playback redraw limits too."""
    win = wm.windows[0] if wm.windows else None
    if win is not None and workspace_kind(win.workspace) == 'ANIM' and win.screen.use_play_properties_editors:
        limit_playback_redraw(win.screen)


classes = (
    M3D_AnimSetItem,
    M3D_AnimSet,
    M3D_AnimSettings,
    M3D_UL_anim_sets,
    M3D_OT_tween,
    M3D_OT_anim_revert,
    M3D_OT_anim_key_type,
    M3D_OT_anim_euler_filter,
    M3D_OT_anim_range,
    M3D_OT_anim_interp,
    M3D_OT_anim_editor,
    M3D_OT_anim_preset,
    M3D_OT_anim_set,
    M3D_OT_anim_pick_bones,
    M3D_OT_anim_paths,
    M3D_OT_anim_graph,
    M3D_OT_anim_layer,
    M3D_OT_playblast,
    M3D_MT_anim_poses,
    M3D_PT_anim_autokey,
    PROPERTIES_PT_m3d_an_camera,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_an_object_sets,
    PROPERTIES_PT_m3d_an_bone_sets,
    PROPERTIES_PT_m3d_an_collections,
    PROPERTIES_PT_m3d_an_tween,
    PROPERTIES_PT_m3d_an_inbetween,
    PROPERTIES_PT_m3d_an_poses,
    PROPERTIES_PT_m3d_an_paths,
    PROPERTIES_PT_m3d_an_ghost,
    PROPERTIES_PT_m3d_an_layers,
    PROPERTIES_PT_m3d_an_bake,
    PROPERTIES_PT_m3d_an_range,
    PROPERTIES_PT_m3d_an_blocking,
    PROPERTIES_PT_m3d_an_playback,
    PROPERTIES_PT_m3d_an_playblast,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_anim = PointerProperty(type=M3D_AnimSettings)


def unregister():
    del bpy.types.Scene.m3d_anim
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
