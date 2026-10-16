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
from mathutils import Euler, Matrix, Quaternion

from m3d_mode import _button
from m3d_rig import (draw_pose_library, draw_selection_sets, pose_assets, rig_of, selected_pose_bones)
from m3d_sculpt import draw_lines, draw_object_picks, empty_state, grid, reason, split_props, viewport
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
# Set Key: one rule for S, the shelf, the Key menu and the marking menu

def character_bones(rig):
    """The controls of a character: the bones you can see and pick (hidden bones and bones in hidden collections are
    the rig's own machinery)."""
    return [pb for pb in rig.pose.bones if not pb.bone.hide
            and (not pb.bone.collections or any(c.is_visible_effectively for c in pb.bone.collections))]


def key_owners(context):
    """What Set Key keys: the selected bones of the skeleton in Pose Mode (all its controls with Key: Character), else
    the selected objects."""
    rig = posed_rig(context)
    if rig is not None:
        return character_bones(rig) if context.scene.m3d_anim.key_scope == 'CHARACTER' else selected_pose_bones(rig)
    return list(context.selected_objects) or ([context.active_object] if context.active_object is not None else [])


KEY_CHANNELS = (('ALL', "Set Key", "the unlocked translate, rotate and scale channels and the custom properties"),
                ('LOCATION', "Key Translate", "the unlocked translate channels"),
                ('ROTATION', "Key Rotate", "the unlocked rotate channels"),
                ('SCALE', "Key Scale", "the unlocked scale channels"))


def key_channels(owner, channels='ALL'):
    """[(data path, index)] of an object's or pose bone's channels to key: translate, rotate (in its rotation mode) and
    scale without the locked ones, and with 'ALL' the numeric custom properties (index -1)."""
    from m3d_mode import custom_properties, rotation_channel
    rot = rotation_channel(owner)[0]
    out = []
    for kind, attr, lock in (('LOCATION', "location", owner.lock_location), ('ROTATION', rot, owner.lock_rotation),
                             ('SCALE', "scale", owner.lock_scale)):
        if channels not in {'ALL', kind}:
            continue
        first = 0
        if attr in {"rotation_quaternion", "rotation_axis_angle"}:   # W is locked only with the 4D lock.
            first = 1
            if not (owner.lock_rotations_4d and owner.lock_rotation_w):
                out.append((attr, 0))
        out += [(attr, first + i) for i in range(3) if not lock[i]]
    if channels == 'ALL':
        out += [('["%s"]' % bpy.utils.escape_identifier(name), -1) for name in custom_properties(owner)]
    return out


def _fcurve(owner, path, index):
    """The F-curve of an object's or pose bone's channel (`path` relative to the owner), or None."""
    base = "" if isinstance(owner, bpy.types.ID) else owner.path_from_id()
    full = base + ("" if not base or path.startswith("[") else ".") + path
    return next((fc for fc in channel_fcurves(owner.id_data) if fc.data_path == full and fc.array_index == max(index, 0)),
                None)


def set_keys(owners, key_type='KEYFRAME', channels='ALL', frame=None):
    """Key the channels of `owners` (objects or pose bones). Returns the number of channels keyed. A curve's first two
    keys get the new key interpolation of the Preferences (keys from Python get Blender's defaults; later keys copy the
    key next to them, as S does in stock Blender)."""
    edit = bpy.context.preferences.edit
    at = bpy.context.scene.frame_current if frame is None else frame
    count = 0
    for owner in owners:
        for path, index in key_channels(owner, channels):
            fc = _fcurve(owner, path, index)
            before = len(fc.keyframe_points) if fc is not None else 0
            try:
                keyed = owner.keyframe_insert(path, index=index, keytype=key_type, frame=at)
            except (RuntimeError, TypeError):
                continue   # (a property that can't be animated, e.g. one a driver sets)
            count += bool(keyed)
            fc = fc or _fcurve(owner, path, index)
            if keyed and fc is not None and before < len(fc.keyframe_points) <= 2:
                key = min(fc.keyframe_points, key=lambda k: abs(k.co.x - at))
                key.interpolation = edit.keyframe_new_interpolation_type
                key.handle_left_type = key.handle_right_type = edit.keyframe_new_handle_type
                fc.update()
    return count


class M3D_OT_set_key(Operator):
    """Set Key: key the unlocked translate, rotate and scale channels and the custom properties of the selected bones
(Pose Mode; Key: Character keys all the character's controls) or the selected objects. Locked channels are skipped"""
    bl_idname = "m3d.set_key"
    bl_label = "Set Key"
    bl_options = {'REGISTER', 'UNDO'}

    channels: EnumProperty(name="Channels", items=[(k, label, "") for k, label, _d in KEY_CHANNELS], default='ALL')

    @classmethod
    def description(cls, _context, props):
        return "Key %s of the selected bones (Pose Mode) or objects; locked channels are skipped" % next(
            d for k, _l, d in KEY_CHANNELS if k == props.channels)

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and context.active_object is not None

    def execute(self, context):
        from m3d_rig import is_bound
        owners = key_owners(context)
        if not set_keys(owners, context.tool_settings.keyframe_type, self.channels):
            self.report({'WARNING'}, "Nothing to key: select bones or objects (locked channels are skipped)")
            return {'CANCELLED'}
        bound = [o.name for o in owners if isinstance(o, bpy.types.Object) and is_bound(o)]
        if bound:   # The object's own transform moves the whole bound mesh away from its skeleton.
            self.report({'WARNING'}, "Keyed the transform of the bound mesh %s: its skeleton's bones pose it "
                                     "(F6 enters Pose Mode on the skeleton)" % ", ".join(bound))
        return {'FINISHED'}


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
        curves = target_curves(context)
        moved = sum(unwrap_euler(fc) for _id, fc in curves if fc.data_path.endswith(".rotation_euler")
                    or fc.data_path == "rotation_euler")
        quats = {fc.data_path for _id, fc in curves if fc.data_path.endswith("rotation_quaternion")}
        if quats:   # (quaternion keys have no Euler flips: the filter does not apply to them)
            self.report({'WARNING'}, "Euler filter: %d keys moved; %d channel(s) rotate in quaternions and were left: set "
                        "their Rotate Order to XYZ (Channel Box) to filter them" % (moved, len(quats)))
        else:
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
# Frame rate: the common rates, keeping the timing of the keys or their frames

# label -> (fps, fps_base)
FRAME_RATES = {"23.976": (24, 1.001), "24": (24, 1.0), "25": (25, 1.0), "29.97": (30, 1.001), "30": (30, 1.0),
               "48": (48, 1.0), "50": (50, 1.0), "60": (60, 1.0), "120": (120, 1.0)}


def frame_rate_label(scene):
    """"24 fps", "29.97 fps" ... for the scene's rate."""
    r = scene.render
    name = next((k for k, (fps, base) in FRAME_RATES.items() if r.fps == fps and abs(r.fps_base - base) < 1e-4),
                "%.4g" % (r.fps / r.fps_base))
    return name + " fps"


def all_fcurves():
    """Every F-curve of every action of the file."""
    return [fc for action in bpy.data.actions for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for fc in bag.fcurves]


def retime(scene, factor):
    """Stretch the animation by `factor` around the scene start (keys, NLA strips, scene and preview range, markers),
    so it plays at the same speed at a new frame rate."""
    pivot = scene.frame_start

    def at(x):
        return pivot + (x - pivot) * factor

    def stretch(fc):
        for key in fc.keyframe_points:
            key.co.x, key.handle_left.x, key.handle_right.x = at(key.co.x), at(key.handle_left.x), at(key.handle_right.x)
        fc.update()

    for fc in all_fcurves():
        stretch(fc)
    for ob in bpy.data.objects:
        ad = ob.animation_data
        for track in (ad.nla_tracks if ad is not None else ()):
            # Later strips move first when the strips grow (earlier ones first when they shrink): they never overlap.
            for strip in sorted(track.strips, key=lambda s: s.frame_start, reverse=factor > 1):
                start, end = at(strip.action_frame_start), at(strip.action_frame_end)
                if factor > 1:
                    strip.action_frame_end, strip.action_frame_start = end, start
                else:
                    strip.action_frame_start, strip.action_frame_end = start, end
                strip.frame_start_ui = at(strip.frame_start)
                for fc in strip.fcurves:   # (the layer's weight keys)
                    stretch(fc)
    for marker in scene.timeline_markers:
        marker.frame = round(at(marker.frame))
    scene.frame_end = max(pivot, round(at(scene.frame_end)))
    scene.frame_preview_start, scene.frame_preview_end = round(at(scene.frame_preview_start)), round(at(scene.frame_preview_end))
    scene.frame_set(round(at(scene.frame_current)))


class M3D_OT_anim_fps(Operator):
    """Frame rate of the scene. When there are keys: Keep Timing moves them so the animation plays at the same speed,
Keep Frames leaves them on their frames (it plays faster or slower)"""
    bl_idname = "m3d.anim_fps"
    bl_label = "Frame Rate"
    bl_options = {'REGISTER', 'UNDO'}

    rate: EnumProperty(name="Frame Rate", items=[(k, k + " fps", "") for k in FRAME_RATES], default="24")
    keep: EnumProperty(name="Keys", default='TIMING', items=(
        ('TIMING', "Keep Timing", "Move the keys so the animation plays at the same speed"),
        ('FRAMES', "Keep Frames", "Leave the keys on their frames: the animation plays faster or slower")))

    def invoke(self, context, _event):
        if any(len(fc.keyframe_points) for fc in all_fcurves()):
            return context.window_manager.invoke_props_dialog(self, title="%s fps: the keys" % self.rate)
        return self.execute(context)

    def draw(self, _context):
        self.layout.prop(self, "keep", expand=True)

    def execute(self, context):
        scene = context.scene
        r = scene.render
        before = r.fps / r.fps_base
        r.fps, r.fps_base = FRAME_RATES[self.rate]
        if self.keep == 'TIMING' and abs(before - r.fps / r.fps_base) > 1e-6:
            retime(scene, (r.fps / r.fps_base) / before)
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


CONVERT_SCOPES = (('SELECTION', "Selection", "The selected bones (Pose Mode) or objects", 'RESTRICT_SELECT_OFF'),
                  ('CHARACTER', "Whole Character", "Every bone of the skeleton in Pose Mode; the selected objects and "
                                                   "their skeletons in Object Mode", 'ARMATURE_DATA'),
                  ('SCENE', "Scene", "Every animated object of the scene", 'SCENE_DATA'))


def scope_curves(context, scope):
    """[(id, fcurve)] of the unlocked, unmuted channels of `scope` (CONVERT_SCOPES)."""
    if scope == 'SELECTION':
        return target_curves(context)
    if scope == 'SCENE':
        owners = list(context.view_layer.objects)
    else:
        from m3d_rig import armature_of
        rig = posed_rig(context)
        owners = [rig] if rig is not None else list(context.selected_objects)
        owners += [r for r in map(armature_of, owners) if r is not None and r not in owners]
    return [(ob, fc) for ob in owners for fc in channel_fcurves(ob) if not (fc.lock or fc.mute)]


def convert_keys(context, kind, scope='SELECTION'):
    """Give the keys of `scope` (CONVERT_SCOPES) the interpolation of `kind`: a new key on a curve with several keys
    copies the key before it, so the preference alone would leave the old keys as they were."""
    interp, handle = INTERP[kind]
    count = 0
    for _id, fc in scope_curves(context, scope):
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
    space_type = {'GRAPH': 'GRAPH_EDITOR', 'DOPESHEET': 'DOPESHEET_EDITOR'}[editor]
    new = not any(s.type == space_type for s in area.spaces)
    area.ui_type = {'GRAPH': 'FCURVES', 'DOPESHEET': 'DOPESHEET'}[editor]
    if new:   # (an editor shown here for the first time: like the other one)
        tidy_bottom_editor(area)
    area.tag_redraw()
    return True


def tidy_bottom_editor(area):
    """One transport row in the Animation workspace, the Time Slider's: the Graph Editor / Dope Sheet show no playback footer,
    and no sidebar (the dock has the pose tools; N or View > Sidebar opens it)."""
    for space in area.spaces:
        if space.type in {'DOPESHEET_EDITOR', 'GRAPH_EDITOR'}:
            space.show_region_footer = space.show_region_ui = False


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
        return {'BLOCKING': "Blocking: new keys are stepped, the keys of the character (Blocking / Polish dropdown: "
                            "selection, whole character or scene) become stepped, and the Dope Sheet shows (the new key "
                            "default is a Preferences setting)",
                'POLISH': "Polish: new keys are clamped splines, the keys of the character (Blocking / Polish dropdown: "
                          "selection, whole character or scene) become clamped splines, and the Graph Editor shows (the "
                          "new key default is a Preferences setting)",
                'RESTORE': "Put the new key defaults back to what they were before Blocking / Polish"}[props.preset]

    def execute(self, context):
        if self.preset == 'RESTORE':
            if not restore_new_key_defaults(context):
                self.report({'INFO'}, "The new key defaults are your own already")
            return {'FINISHED'}
        blocking = self.preset == 'BLOCKING'
        kind = 'STEPPED' if blocking else 'CLAMPED'
        set_new_key_kind(context, kind)
        convert_keys(context, kind, context.scene.m3d_anim.convert_scope)
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
    key_scope: EnumProperty(name="Key", default='SELECTED', items=(
        ('SELECTED', "Selected", "Set Key keys the selected bones", 'RESTRICT_SELECT_OFF', 0),
        ('CHARACTER', "Character", "Set Key in Pose Mode keys every control of the character (the bones you can see)",
         'ARMATURE_DATA', 1)))
    convert_scope: EnumProperty(name="Convert", default='CHARACTER', description="Whose keys Blocking / Polish convert",
                                items=[(k, label, d, icon, i) for i, (k, label, d, icon) in enumerate(CONVERT_SCOPES)])
    playblast_dir: StringProperty(name="Folder", subtype='DIR_PATH', default="",
                                  description="Where the playblasts go (empty: a folder in the temporary directory)")
    playblast_percent: IntProperty(name="Size", default=50, min=10, max=100, subtype='PERCENTAGE',
                                   description="Playblast size as a percentage of the render resolution")
    playblast_play: BoolProperty(name="Play When Done", default=True, description="Open the player on the playblast")
    playblast_format: EnumProperty(name="Format", default='MOVIE', items=(
        ('MOVIE', "Movie", "One H.264 movie (.mp4) with the scene's sound"),
        ('IMAGES', "Images", "A PNG image per frame")))
    playblast_range: EnumProperty(name="Range", default='PLAYBACK', items=(
        ('PLAYBACK', "Playback Range", "The preview range when it is on, else the scene range"),
        ('SCENE', "Scene Range", "From the scene start to the scene end")))
    playblast_meshes: BoolProperty(name="Meshes Only", default=True,
                                   description="Leave out bones, controls, the grid and the other overlays")
    playblast_burn_in: BoolProperty(name="Burn-in", default=True,
                                    description="Write the frame, camera, file name and date onto the pictures")
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
# Mirror Pose, Mirror Animation, Copy / Paste World Position

# Rotation property -> indices that change sign in a pose mirrored left to right (as Blender's Paste Flipped does);
# translate X does too, scale and custom properties keep theirs.
_FLIP_SIGNS = {"location": {0}, "rotation_euler": {1, 2}, "rotation_quaternion": {2, 3}, "rotation_axis_angle": {2, 3}}


def mirror_sign(path, index):
    """-1 when the channel (a pose bone's data path and index) changes sign in the mirrored pose, else 1."""
    prop = path.rpartition(".")[2]
    return -1 if index in _FLIP_SIGNS.get(prop, ()) else 1


def _pose_values(pb):
    """{property: values} of a pose bone: translate, its rotation, scale and the numeric custom properties."""
    from m3d_mode import custom_properties, rotation_channel
    rot = rotation_channel(pb)[0]
    values = {attr: list(getattr(pb, attr)) for attr in ("location", rot, "scale")}
    values.update({'["%s"]' % bpy.utils.escape_identifier(n): pb[n] for n in custom_properties(pb)})
    return values


def _as_quaternion(attr, values, mode):
    if attr == "rotation_quaternion":
        return Quaternion(values)
    if attr == "rotation_axis_angle":
        return Quaternion(values[1:], values[0])
    return Euler(values, mode).to_quaternion()


def _set_rotation(pb, quat):
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = quat
    elif pb.rotation_mode == 'AXIS_ANGLE':
        axis, angle = quat.to_axis_angle()
        pb.rotation_axis_angle = (angle, *axis)
    else:
        pb.rotation_euler = quat.to_euler(pb.rotation_mode)


def mirror_pose(rig, bones):
    """Each of `bones` (pose bones) gives its pose, mirrored, to its other side (Arm.L -> Arm.R; a middle bone mirrors
    itself). Bones of both sides swap. Returns the bones that changed."""
    poses = [(pb.name, pb.rotation_mode, _pose_values(pb)) for pb in bones]   # (all read first: both sides swap)
    changed = []
    for name, mode, values in poses:
        dest = rig.pose.bones.get(bpy.utils.flip_name(name))
        if dest is None:
            continue
        for attr, value in values.items():
            if attr.startswith("["):
                dest[bpy.utils.unescape_identifier(attr[2:-2])] = value
                continue
            flipped = [v * mirror_sign(attr, i) for i, v in enumerate(value)]
            if attr.startswith("rotation_") and dest.rotation_mode != mode:   # (the other side rotates another way)
                _set_rotation(dest, _as_quaternion(attr, flipped, mode))
            else:
                setattr(dest, attr, flipped)
        changed.append(dest)
    return changed


class M3D_OT_anim_mirror_pose(Operator):
    """Mirror Pose: the selected bones' pose goes to the other side, mirrored (bones of both sides swap; a middle bone
mirrors itself). Whole Character flips the whole pose. Auto Key keys the changed bones"""
    bl_idname = "m3d.anim_mirror_pose"
    bl_label = "Mirror Pose"
    bl_options = {'REGISTER', 'UNDO'}

    whole: BoolProperty(name="Whole Character", default=False, description="Flip the pose of every control")

    @classmethod
    def description(cls, _context, props):
        return ("Flip the whole pose left to right (every control)" if props.whole else
                "Give the selected bones' pose, mirrored, to the bones of the other side (select both sides to swap them)")

    @classmethod
    def poll(cls, context):
        return posed_rig(context) is not None

    def execute(self, context):
        rig = posed_rig(context)
        changed = mirror_pose(rig, character_bones(rig) if self.whole else selected_pose_bones(rig))
        if not changed:
            self.report({'WARNING'}, "No bones to mirror: select bones named with a side (.L / .R, Left / Right)")
            return {'CANCELLED'}
        if context.tool_settings.use_keyframe_insert_auto:
            set_keys(changed, context.tool_settings.keyframe_type)
        context.view_layer.update()
        return {'FINISHED'}


def mirror_animation(rig, bones, offset):
    """The keys of each of `bones` go, mirrored, onto its other side's channels (replacing their keys), `offset` frames
    later; the keys that land past the end of the cycle (the action's frame range) wrap round to its start. Returns the
    number of channels written."""
    ad = rig.animation_data
    bag = animdata_get_channelbag_for_assigned_slot(ad) if ad is not None and ad.action is not None else None
    if bag is None:
        return 0
    start, end = ad.action.frame_range
    length = end - start
    # (source curve data read first: with both sides selected they swap)
    sources = []
    for pb in bones:
        dest = bpy.utils.flip_name(pb.name)
        if dest == pb.name or dest not in rig.pose.bones:
            continue
        prefix = 'pose.bones["%s"]' % bpy.utils.escape_identifier(pb.name)
        for fc in bag.fcurves:
            if len(fc.keyframe_points) and (fc.data_path.startswith(prefix + ".") or fc.data_path.startswith(prefix + "[")):
                keys = [(k.co.x, k.co.y, k.interpolation, k.handle_left_type, k.handle_right_type)
                        for k in fc.keyframe_points]
                path = 'pose.bones["%s"]' % bpy.utils.escape_identifier(dest) + fc.data_path[len(prefix):]
                sources.append((dest, path, fc.array_index, mirror_sign(fc.data_path, fc.array_index), fc, keys))
    written = 0
    for dest, path, index, sign, source, keys in sources:
        if offset and length > 0:   # A cycle: keys move round it, the last key is the first one again.
            shifted = [(start + (x - start + offset) % length, y, *rest) for x, y, *rest in keys if x < end]
            first = source.evaluate(start + (-offset) % length)
            shifted += [(start, first, *keys[0][2:]), (end, first, *keys[0][2:])]
        else:
            shifted = [(x + offset, y, *rest) for x, y, *rest in keys]
        fc = bag.fcurves.find(path, index=index) or bag.fcurves.new(path, index=index)
        fc.group = bag.groups.get(dest) or bag.groups.new(dest)
        fc.keyframe_points.clear()
        for x, y, interp, left, right in sorted({round(k[0], 4): k for k in shifted}.values()):
            key = fc.keyframe_points.insert(x, y * sign, options={'FAST'})
            key.interpolation, key.handle_left_type, key.handle_right_type = interp, left, right
        fc.update()
        written += 1
    return written


class M3D_OT_anim_mirror_animation(Operator):
    """Mirror Animation: the selected bones' keys go, mirrored, onto the bones of the other side (their keys are
replaced). For a cycle, Half a Cycle Later offsets them by half the action's length (a walk: the other leg)"""
    bl_idname = "m3d.anim_mirror_animation"
    bl_label = "Mirror Animation"
    bl_options = {'REGISTER', 'UNDO'}

    half_cycle: BoolProperty(name="Half a Cycle Later", default=True,
                             description="Offset the mirrored keys by half the action's length, wrapping round")

    @classmethod
    def poll(cls, context):
        return posed_rig(context) is not None

    def execute(self, context):
        rig = posed_rig(context)
        ad = rig.animation_data
        offset = 0.0
        if self.half_cycle and ad is not None and ad.action is not None:
            start, end = ad.action.frame_range
            offset = (end - start) / 2
        if not mirror_animation(rig, selected_pose_bones(rig), offset):
            self.report({'WARNING'}, "Nothing to mirror: select keyed bones named with a side (.L / .R, Left / Right)")
            return {'CANCELLED'}
        context.scene.frame_set(context.scene.frame_current)
        return {'FINISHED'}


_world_clip = {}   # frame -> world matrix of the bone or object copied


def world_matrix(owner):
    """World matrix of an object or pose bone."""
    return owner.id_data.matrix_world @ owner.matrix if isinstance(owner, bpy.types.PoseBone) else owner.matrix_world


def set_world_matrix(owner, matrix):
    """Put an object or pose bone where `matrix` is (position and rotation; it keeps its own scale)."""
    loc, rot, _scale = matrix.decompose()
    matrix = Matrix.LocRotScale(loc, rot, world_matrix(owner).to_scale())
    if isinstance(owner, bpy.types.PoseBone):
        owner.matrix = owner.id_data.matrix_world.inverted() @ matrix
    else:
        owner.matrix_world = matrix


class M3D_OT_anim_world_position(Operator):
    """Copy / Paste World Position: copy where the active bone or object is in the world, then put the selected bones or
objects there (over the playback range: frame by frame, keyed)"""
    bl_idname = "m3d.anim_world_position"
    bl_label = "World Position"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('COPY', "Copy", ""), ('PASTE', "Paste", "")))
    over_range: BoolProperty(name="Over the Playback Range", default=False,
                             description="Every frame of the playback range (pasting keys each frame)")

    @classmethod
    def description(cls, _context, props):
        what = "over the playback range" if props.over_range else "at this frame"
        return ("Copy where the active bone or object is in the world " if props.action == 'COPY' else
                "Put the selected bones or objects where the copied one was ") + what

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and context.active_object is not None

    def execute(self, context):
        scene = context.scene
        here = scene.frame_current
        frames = range(playblast_frames(scene)[0], playblast_frames(scene)[1] + 1) if self.over_range else [here]
        if self.action == 'COPY':
            rig = posed_rig(context)
            owner = context.active_pose_bone if rig is not None else context.active_object
            if owner is None:
                self.report({'WARNING'}, "Nothing to copy: make a bone active")
                return {'CANCELLED'}
            _world_clip.clear()
            for frame in frames:
                scene.frame_set(frame)
                _world_clip[frame] = world_matrix(owner).copy()
            scene.frame_set(here)
            self.report({'INFO'}, "World position copied (%d frame%s)" % (len(frames), "s" * (len(frames) > 1)))
            return {'FINISHED'}
        if not _world_clip:
            self.report({'WARNING'}, "Copy a world position first")
            return {'CANCELLED'}
        rig = posed_rig(context)
        owners = selected_pose_bones(rig) if rig is not None else list(context.selected_objects)
        auto = context.tool_settings.use_keyframe_insert_auto
        for frame in (sorted(_world_clip) if len(_world_clip) > 1 else [here]):
            scene.frame_set(frame)
            matrix = _world_clip.get(frame, next(iter(_world_clip.values())))
            for owner in owners:
                set_world_matrix(owner, matrix)
                context.view_layer.update()   # (a child bone after its parent)
            if len(_world_clip) > 1 or auto:
                set_keys(owners, context.tool_settings.keyframe_type, 'LOCATION', frame)
                set_keys(owners, context.tool_settings.keyframe_type, 'ROTATION', frame)
        if len(_world_clip) > 1:
            scene.frame_set(here)
        return {'FINISHED'}

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
    """The object's current action becomes a strip on a new NLA track. Returns the track, or None without an action.
    The strip grows with keys set later while the layer is edited, and its influence is the layer's keyable weight."""
    ad = ob.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action
    track = ad.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, int(action.frame_range[0]), action)
    strip.use_sync_length = True   # (Done Editing fits the strip to the action's keys)
    strip.use_animated_influence = True
    for key in strip.fcurves.find("influence").keyframe_points:   # (turning it on keys the unused value, 0)
        key.co.y = key.handle_left.y = key.handle_right.y = 1.0
    strip.influence = 1.0
    ad.action = None
    return track


def layer_strip(track):
    """The track's strip (a layer has one), or None."""
    return track.strips[0] if len(track.strips) else None


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
# Playblast: the viewport rendered into a movie (with the scene's sound) or a picture per frame, for review

def playblast_folder(scene):
    s = scene.m3d_anim
    return bpy.path.abspath(s.playblast_dir) if s.playblast_dir else os.path.join(tempfile.gettempdir(), "m3d_playblast")


def playblast_frames(scene, kind='PLAYBACK'):
    """Frames to play: the preview range when it is on (kind 'PLAYBACK'), else the scene range."""
    return (scene.frame_preview_start, scene.frame_preview_end) if scene.use_preview_range and kind == 'PLAYBACK' \
        else (scene.frame_start, scene.frame_end)


def playblast_name(folder, base):
    """<base>_v001, _v002 ...: the next version in the folder (a playblast never replaces an earlier one)."""
    pattern = re.compile(re.escape(base) + r"_v(\d{3,})")
    used = [int(m.group(1)) for m in map(pattern.match, os.listdir(folder) if os.path.isdir(folder) else ()) if m]
    return "%s_v%03d" % (base, max(used, default=0) + 1)


def has_sound(scene):
    """True when the scene has sound to put in the movie: sound strips or speakers."""
    ed = scene.sequence_editor
    return bool(ed is not None and any(s.type == 'SOUND' for s in ed.strips_all)) \
        or any(ob.type == 'SPEAKER' for ob in scene.objects)


_FFMPEG = ("format", "codec", "audio_codec", "constant_rate_factor")
BURN_IN = {"use_stamp", "use_stamp_frame", "use_stamp_camera", "use_stamp_filename", "use_stamp_date", "use_stamp_labels"}


def _stamp_props():
    return [p.identifier for p in bpy.types.RenderSettings.bl_rna.properties if p.identifier.startswith("use_stamp")]


def snapshot_render(scene):
    """The render settings a playblast changes (the user's output settings are put back afterwards)."""
    r = scene.render
    return {"render": {k: getattr(r, k) for k in ("filepath", "resolution_percentage", "use_file_extension",
                                                  *_stamp_props())},
            "image": {k: getattr(r.image_settings, k) for k in ("media_type", "file_format", "color_mode")},
            "ffmpeg": {k: getattr(r.ffmpeg, k) for k in _FFMPEG},
            "scene": {k: getattr(scene, k) for k in ("frame_start", "frame_end", "frame_current", "use_preview_range")}}


def restore_render(scene, snap):
    r = scene.render
    for k, v in snap["render"].items():
        setattr(r, k, v)
    for k in ("media_type", "file_format", "color_mode"):   # In this order: the format depends on the media type.
        setattr(r.image_settings, k, snap["image"][k])
    for k, v in snap["ffmpeg"].items():
        setattr(r.ffmpeg, k, v)
    for k, v in snap["scene"].items():
        setattr(scene, k, v)
    scene.frame_set(snap["scene"]["frame_current"])


def configure_playblast(scene, folder, percent, movie=False, burn_in=False):
    """PNG frames, or an H.264 movie (with the scene's sound), at `percent` of the render size; burn-in = the frame,
    camera, file name and date written onto the pictures."""
    r = scene.render
    r.resolution_percentage = percent
    r.use_file_extension = True
    if movie:
        r.image_settings.media_type = 'VIDEO'
        r.image_settings.file_format = 'FFMPEG'
        r.ffmpeg.format, r.ffmpeg.codec, r.ffmpeg.constant_rate_factor = 'MPEG4', 'H264', 'MEDIUM'
        r.ffmpeg.audio_codec = 'AAC' if has_sound(scene) else 'NONE'
    else:
        r.image_settings.media_type = 'IMAGE'
        r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGB'
    for name in _stamp_props():
        setattr(r, name, burn_in and name in BURN_IN)
    os.makedirs(folder, exist_ok=True)


def playblast_area(screen):
    """The 3D Viewport to render: a camera view when the workspace has one, else the biggest viewport."""
    views = [a for a in screen.areas if a.type == 'VIEW_3D']
    cams = [a for a in views if a.spaces.active.region_3d.view_perspective == 'CAMERA']
    pool = cams or views
    return max(pool, key=lambda a: a.width * a.height) if pool else None


playblast_state = {"running": False, "files": [], "folder": ""}


class M3D_OT_playblast(Operator):
    """Playblast: render the viewport (the camera view when there is one) into a movie with the scene's sound, or a
picture per frame, then play it. Each playblast is a new version named after the file; the render output settings are
put back afterwards. Esc cancels pictures"""
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
        s = scene.m3d_anim
        self.area = playblast_area(context.screen)
        self.window = context.window or context.window_manager.windows[0]
        self.folder = playblast_folder(scene)
        self.movie = s.playblast_format == 'MOVIE'
        base = bpy.path.clean_name(bpy.path.display_name_from_filepath(bpy.data.filepath) or "playblast")
        self.out_name = playblast_name(self.folder, base)
        self.snap = snapshot_render(scene)
        self.first, self.last = playblast_frames(scene, s.playblast_range)
        self.frames = list(range(self.first, self.last + 1))
        try:
            configure_playblast(scene, self.folder, s.playblast_percent, self.movie, s.playblast_burn_in)
        except OSError as err:
            restore_render(scene, self.snap)
            self.report({'ERROR'}, "Playblast folder: %s" % err)
            return {'CANCELLED'}
        overlay = self.area.spaces.active.overlay
        self.overlays = overlay.show_overlays
        if s.playblast_meshes:   # (bones, controls, the grid, cameras and lights are overlays)
            overlay.show_overlays = False
        playblast_state.update(running=True, files=[], folder=self.folder)
        s.playblast_note = ""
        context.workspace.status_text_set("Playblast: %d frames%s" % (
            len(self.frames), " into a movie" if self.movie else " (Esc cancels)"))
        self.timer = context.window_manager.event_timer_add(0.05, window=self.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def render(self, context, animation):
        region = next(r for r in self.area.regions if r.type == 'WINDOW')
        with context.temp_override(window=self.window, screen=context.screen, area=self.area, region=region,
                                   space_data=self.area.spaces.active):
            bpy.ops.render.opengl(animation=animation, write_still=not animation, view_context=True)

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            return self.finish(context, "Playblast cancelled", cancelled=True)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        scene = context.scene
        if self.movie:   # One call writes the whole movie (and its sound).
            path = os.path.join(self.folder, self.out_name + ".mp4")
            scene.render.filepath = path
            scene.use_preview_range = False
            scene.frame_start, scene.frame_end = self.first, self.last
            try:
                self.render(context, True)
            except RuntimeError as err:
                return self.finish(context, "Playblast failed: %s" % str(err).strip(), cancelled=True)
            if os.path.exists(path):
                playblast_state["files"].append(path)
            self.frames = []
        if not self.frames:
            return self.finish(context, "Playblast: %s in %s" % (self.result(), self.folder))
        frame = self.frames.pop(0)
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(self.folder, "%s_%04d" % (self.out_name, frame))
        context.workspace.status_text_set("Playblast: frame %d (Esc cancels)" % frame)
        try:
            self.render(context, False)
        except RuntimeError as err:
            return self.finish(context, "Playblast failed: %s" % str(err).strip(), cancelled=True)
        path = scene.render.filepath + ".png"
        if os.path.exists(path):
            playblast_state["files"].append(path)
        return {'RUNNING_MODAL'}

    def result(self):
        """"scene_v003.mp4 (24 frames)" or "scene_v003 (24 frames)"."""
        if self.movie:
            return "%s.mp4 (%d frames)" % (self.out_name, self.last - self.first + 1)
        return "%s (%d frames)" % (self.out_name, len(playblast_state["files"]))

    def finish(self, context, message, cancelled=False):
        scene = context.scene
        context.window_manager.event_timer_remove(self.timer)
        context.workspace.status_text_set(None)
        self.area.spaces.active.overlay.show_overlays = self.overlays
        if self.play and playblast_state["files"] and not cancelled:
            if not self.movie:
                scene.render.filepath = os.path.join(self.folder, self.out_name + "_####")
            scene.use_preview_range = False
            scene.frame_start, scene.frame_end = self.first, self.last
            try:
                bpy.ops.render.play_rendered_anim()
            except RuntimeError:
                pass   # The player is not essential: the playblast is in the folder.
        restore_render(scene, self.snap)
        playblast_state["running"] = False
        # (the dock's note leaves the folder out: its button opens it)
        scene.m3d_anim.playblast_note = message if cancelled else "Last playblast: " + self.result()
        self.report({'WARNING'} if cancelled else {'INFO'}, message)
        return {'CANCELLED'} if cancelled else {'FINISHED'}


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

# What a page needs. need -> (message, (button label, operator, icon, properties)); 'OBJ' picks one of the scene's objects
FIXES = {
    'OBJ': ("Select an object to animate", None),
    'POSE': ("Enter Pose Mode to work on the bones", ("Pose Mode", "m3d.rig_mode", 'POSE_HLT', {"mode": 'POSE'})),
}
NO_RIG = ("Needs a skeleton: make one in F5 Rigging", ("F5 Rigging", "m3d.workspace", 'ARMATURE_DATA', {"kind": 'RIG'}))


def has(context, need):
    return {'OBJ': lambda: bool(context.selected_objects or context.active_object is not None),
            'POSE': lambda: posed_rig(context) is not None}[need]()


def missing(context, needs):
    return [n for n in needs if not has(context, n)]


def ready(context, needs):
    return not missing(context, needs)


def draw_fixes(layout, context, needs):
    """The card of the first need that is missing (an object comes before Pose Mode; Pose Mode needs a skeleton)."""
    need = missing(context, needs)[0]
    if need == 'POSE' and rig_of(context) is None:
        empty_state(layout, context, *NO_RIG)
    elif need == 'OBJ':
        found = [o for o in context.view_layer.objects if o.visible_get() and o.type not in {'CAMERA', 'LIGHT'}]
        draw_object_picks(empty_state(layout, context, FIXES['OBJ'][0]), found)
    else:
        empty_state(layout, context, *FIXES[need])


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


class PROPERTIES_PT_m3d_an_controls(_Pick, Panel):
    bl_label = "Controls"

    @classmethod
    def page_poll(cls, context):   # (in Object Mode the Bone Collections panel says to enter Pose Mode)
        return posed_rig(context) is not None

    def draw(self, context):
        layout = self.layout
        rig = posed_rig(context)
        _button(layout, context, "Select All Controls", "pose.select_all", 'RESTRICT_SELECT_OFF', {"action": 'SELECT'})
        row = layout.row(align=True)
        row.label(text="Set Key keys")
        row.prop(context.scene.m3d_anim, "key_scope", expand=True)
        rig_id = rig.data.get("rig_id")
        if not isinstance(rig_id, str):
            return
        # A generated rig's own controls (IK / FK switches, snapping): the panel its script registers for the viewport.
        rig_ui = getattr(bpy.types, "VIEW3D_PT_rig_ui_" + rig_id, None)
        if rig_ui is None:
            reason(layout, "The rig's control script isn't running: allow Auto Run Python Scripts in Preferences > "
                           "Save & Load, then open the file again")
            return
        box = layout.box()
        box.label(text="Rig Controls", icon='ARMATURE_DATA')
        rig_ui.draw(namedtuple("RigPanel", "layout")(box.column()), context)


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
        if len(rig.selection_sets) and context.mode == 'POSE':
            flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
            for i, sel in enumerate(rig.selection_sets):
                _button(flow, context, sel.name, "pose.selection_set_select", 'NONE', {"selection_set_index": i})


class PROPERTIES_PT_m3d_an_object_sets(_Pick, Panel):
    bl_label = "Object Selection Sets"

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_anim
        row = layout.row()
        row.template_list("M3D_UL_anim_sets", "", s, "sets", s, "set_index", rows=min(max(len(s.sets), 1), 6),
                          show_handles=False)
        col = row.column(align=True)
        col.operator("m3d.anim_set", icon='ADD', text="").action = 'ADD'
        if not len(s.sets):
            reason(layout, "Select objects, then add a set with +")
            return
        col.operator("m3d.anim_set", icon='REMOVE', text="").action = 'REMOVE'
        row = layout.row(align=True)
        for action, label in (('ASSIGN', "Assign"), ('UNASSIGN', "Remove"), ('SELECT', "Select"), ('DESELECT', "Deselect")):
            row.operator("m3d.anim_set", text=label).action = action
        flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for i, sel in enumerate(s.sets):
            o = flow.operator("m3d.anim_set", text=sel.name)
            o.action, o.index = 'SELECT', i
        reason(layout, "Shift-click adds to the selection")


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
            if context.mode == 'POSE':
                row.operator("m3d.anim_pick_bones", text=coll.name).collection = coll.name
            else:   # (the name: picking works in Pose Mode)
                row.label(text=coll.name)
        if context.mode != 'POSE':
            reason(layout, "Enter Pose Mode to pick bones")
        else:
            reason(layout, "Shift-click adds to the selection")


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
            reason(layout, "0 = previous key, 1 = next key; the key is a breakdown")


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
        reason(layout, "Drag in the viewport, click to keep (Alt+Shift+P / R / B)")


class PROPERTIES_PT_m3d_an_poses(_Tween, Panel):
    bl_label = "Poses"

    @classmethod
    def page_poll(cls, context):   # (without a skeleton the Push, Relax, Breakdown card says where to make one)
        return ready(context, cls.needs) and _rig(context) is not None

    def draw(self, context):
        layout = self.layout
        rig = _rig(context)
        if not has(context, 'POSE'):
            draw_fixes(layout, context, ('POSE',))
        grid(layout, context, (
            ("Copy", "pose.copy", 'COPYDOWN', {}),
            ("Paste", "pose.paste", 'PASTEDOWN', {}),
            ("Flipped", "pose.paste", 'PASTEFLIPDOWN', {"flipped": True}),
            ("Mirror", "m3d.anim_mirror_pose", 'MOD_MIRROR', {"whole": False}),
            ("Mirror All", "m3d.anim_mirror_pose", 'ARMATURE_DATA', {"whole": True}),
            ("Mirror Anim", "m3d.anim_mirror_animation", 'ACTION', {"half_cycle": True}),
        ), columns=3)
        reason(layout, "Mirror: the selection's pose to the other side; Mirror Anim: half a cycle later")
        layout.label(text="World Position")
        grid(layout, context, (
            ("Copy", "m3d.anim_world_position", 'COPYDOWN', {"action": 'COPY', "over_range": False}),
            ("Paste", "m3d.anim_world_position", 'PASTEDOWN', {"action": 'PASTE', "over_range": False}),
            ("Copy Range", "m3d.anim_world_position", 'COPYDOWN', {"action": 'COPY', "over_range": True}),
            ("Paste Range", "m3d.anim_world_position", 'PASTEDOWN', {"action": 'PASTE', "over_range": True}),
        ), columns=2)
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
        shown = mp is not None and mp.has_motion_paths   # (Update and Clear once there are paths)
        for action, label, icon in (('CALCULATE', "Calculate", 'ANIM_DATA'), ('UPDATE', "Update", 'FILE_REFRESH'),
                                    ('CLEAR', "Clear", 'X')):
            if action == 'CALCULATE' or shown:
                row.operator("m3d.anim_paths", text=label, icon=icon).action = action
        if mp is not None:
            row = layout.row(align=True)
            row.prop(mp, "show_frame_numbers", text="Frame Numbers", toggle=True)
            row.prop(mp, "show_keyframe_numbers", text="Key Numbers", toggle=True)
        space = viewport(context)
        if space is not None:
            layout.prop(space.overlay, "show_motion_paths", text="Show Paths in the Viewport", toggle=True)
        reason(layout, "Paths of the selected " + ("bones" if posed_rig(context) is not None else "objects"))


class PROPERTIES_PT_m3d_an_ghost(_Motion, Panel):
    bl_label = "Ghost Curves"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("m3d.anim_graph", text="Create", icon='GHOST_ENABLED').action = 'GHOST_CREATE'
        row.operator("m3d.anim_graph", text="Clear", icon='GHOST_DISABLED').action = 'GHOST_CLEAR'
        reason(layout, "A copy of the curves to compare in the Graph Editor")


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
        if ad is None or (ad.action is None and not ad.nla_tracks):
            empty_state(layout, context, "%s has no animation yet" % ob.name,
                        ("Set Key", "m3d.set_key", 'KEY_HLT', {}))
            return
        reason(layout, "Layers are NLA tracks: each pushed action is one layer")
        tweak = ad.use_tweak_mode
        if not tweak:   # (while a layer is edited: Done Editing below)
            col = layout.column(align=True)
            col.scale_y = 1.2
            if ad.action is not None:
                col.operator("m3d.anim_layer", text="Push Down", icon='NLA_PUSHDOWN').action = 'PUSH_DOWN'
            col.operator("m3d.anim_layer", text="Add Additive Layer", icon='ADD').action = 'ADD_ADDITIVE'
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
                strip = layer_strip(track)
                if strip is not None:   # The layer's weight (keyable: S over it) and its frames.
                    row = col.row(align=True)
                    if strip.use_animated_influence:   # (layers pushed by older versions have none)
                        row.prop(strip, "influence", text="Weight", slider=True)
                    row.label(text="%d - %d" % (round(strip.frame_start), round(strip.frame_end)))
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
        reason(layout, "Bakes the selection over the playback range")


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
        split = layout.split(factor=0.4)   # (lined up with the property rows above)
        col = split.column()
        col.alignment = 'RIGHT'
        col.label(text="Frame Rate")
        split.operator_menu_enum("m3d.anim_fps", "rate", text=frame_rate_label(scene))
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
        layout.prop(context.scene.m3d_anim, "convert_scope", text="Convert")
        layout.label(text="New keys")
        row = layout.row(align=True)
        for k, label in INTERP_LABELS.items():
            row.operator("m3d.anim_interp", text=label, depress=kind == k).kind = k
        if _prefs_before:
            layout.operator("m3d.anim_preset", text="Restore My Defaults", icon='LOOP_BACK').preset = 'RESTORE'
        reason(layout, "Blocking / Polish also convert the keys of the choice above")
        reason(layout, "New keys copy the key before them; the default is a Preference")


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
        first, last = playblast_frames(context.scene, s.playblast_range)
        layout.prop(s, "playblast_format", expand=True)
        layout.prop(s, "playblast_range")
        layout.prop(s, "playblast_dir")
        layout.prop(s, "playblast_percent")
        col = layout.column()
        col.prop(s, "playblast_meshes")
        col.prop(s, "playblast_burn_in")
        layout.prop(s, "playblast_play")
        sub = layout.row()
        sub.scale_y = 1.3
        sub.operator("m3d.playblast", icon='RENDER_ANIMATION').play = s.playblast_play
        row = layout.row()
        row.label(text="Frames %d - %d, %s" % (first, last, "in the folder" if s.playblast_dir else "in a temp folder"))
        folder = playblast_folder(context.scene)
        if os.path.isdir(folder):   # (the folder in the file browser of the system: its full path)
            row.operator("wm.path_open", text="", icon='FILEBROWSER', emboss=False).filepath = folder
        if s.playblast_note:
            draw_lines(layout, context, s.playblast_note, icon='NONE')


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
        from m3d_render import NEW_CAMERA
        empty_state(self.layout, context, "No camera: the camera view is empty", NEW_CAMERA)


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


INTERP_ICONS = {'STEPPED': 'IPO_CONSTANT', 'SPLINE': 'IPO_BEZIER', 'LINEAR': 'IPO_LINEAR', 'CLAMPED': 'HANDLE_AUTOCLAMPED'}


def draw_status_line(layout, context):
    """Animation Status Line: file, Object / Pose, Auto Key (+ options), key type, new key interpolation, Blocking /
    Polish (+ whose keys), Key: Selected / Character, keying set, playback range, frame rate, loop mode, Graph / Dope
    Sheet, Playblast. Narrower windows show icons (with
    their tooltips) for the editors and Playblast first, then for the modes, Auto Key and the interpolation."""
    from m3d_ui import draw_file_buttons, draw_workspace_picker, status_narrow
    scene, ts = context.scene, context.tool_settings
    icons, editor_icons = status_narrow(context, 1700), status_narrow(context, 2100)
    draw_file_buttons(layout)
    row = layout.row(align=True)
    for mode, icon, label, modes in (('OBJECT', 'OBJECT_DATAMODE', "Object", {'OBJECT'}),
                                     ('POSE', 'POSE_HLT', "Pose", {'POSE'})):
        row.operator("m3d.rig_mode", text="" if icons else label, icon=icon, depress=context.mode in modes).mode = mode

    layout.separator()
    row = layout.row(align=True)
    row.prop(ts, "use_keyframe_insert_auto", text="" if icons else "Auto Key", icon='RECORD_ON' if ts.use_keyframe_insert_auto
             else 'RECORD_OFF', toggle=True)
    row.popover(panel="M3D_PT_anim_autokey", text="")
    layout.separator()
    row = layout.row(align=True)
    for key_type, icon in KEY_TYPE_ICONS:
        row.prop_enum(ts, "keyframe_type", key_type, text="", icon=icon)

    layout.separator()
    row = layout.row(align=True)
    if not icons:
        row.label(text="New keys:")   # A Preferences setting (every file): the tooltips say so.
    kind = new_key_kind(context)
    for k, label in INTERP_LABELS.items():
        row.operator("m3d.anim_interp", text="" if icons else label, icon=INTERP_ICONS[k] if icons else 'NONE',
                     depress=kind == k).kind = k
    layout.separator()
    row = layout.row(align=True)
    row.operator("m3d.anim_preset", text="Blocking", depress=kind == 'STEPPED').preset = 'BLOCKING'
    row.operator("m3d.anim_preset", text="Polish", depress=kind == 'CLAMPED').preset = 'POLISH'
    row.prop(scene.m3d_anim, "convert_scope", text="", icon_only=True)

    layout.separator()
    row = layout.row(align=True)
    if not icons:
        row.label(text="Key:")
    row.prop(scene.m3d_anim, "key_scope", expand=True, icon_only=icons)
    row = layout.row(align=True)
    row.scale_x = 0.8 if icons else 1.1
    row.prop_search(scene.keying_sets_all, "active", scene, "keying_sets_all", text="")

    layout.separator()
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
    sub = row.row(align=True)
    sub.ui_units_x = 4.5   # (a menu button is sized for its icon: "29.97 fps" needs the room)
    sub.operator_menu_enum("m3d.anim_fps", "rate", text=frame_rate_label(scene))
    row.prop(scene, "playback_loop_mode", text="")

    layout.separator()
    row = layout.row(align=True)
    area = bottom_area(context.screen)
    graph = area is not None and area.type == 'GRAPH_EDITOR'
    row.operator("m3d.anim_editor", text="" if editor_icons else "Graph", icon='GRAPH', depress=graph).editor = 'GRAPH'
    row.operator("m3d.anim_editor", text="" if editor_icons else "Dope Sheet", icon='ACTION',
                 depress=area is not None and not graph).editor = 'DOPESHEET'
    layout.separator()
    layout.operator("m3d.playblast", text="" if editor_icons else "Playblast", icon='RENDER_ANIMATION').play = scene.m3d_anim.playblast_play
    draw_workspace_picker(layout, context)


# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

def _pose_menu(row, _context):
    row.menu("M3D_MT_anim_poses", text="Apply Pose", icon='POSE_HLT')


SHELF_ANIMATE = [
    ("m3d.set_key", 'KEY_HLT', {"channels": 'ALL'}, "Set Key"),
    ("m3d.set_key", 'CON_LOCLIKE', {"channels": 'LOCATION'}, "Translate"),
    ("m3d.set_key", 'CON_ROTLIKE', {"channels": 'ROTATION'}, "Rotate"),
    ("m3d.set_key", 'CON_SIZELIKE', {"channels": 'SCALE'}, "Scale"),
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
    ("m3d.anim_mirror_pose", 'MOD_MIRROR', {"whole": False}, "Mirror Pose"),
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


ANIM_LAYOUT = 1   # Workspace.m3d_layout of the Animation workspace: 1 has one transport row (tidy_bottom_editor)


def follow(wm):
    """Workspace timer: an Animation workspace from an older file gets the playback redraw limits too, and once the one
    transport row (afterwards the footer and sidebar are the user's)."""
    win = wm.windows[0] if wm.windows else None
    if win is None or workspace_kind(win.workspace) != 'ANIM':
        return
    if win.screen.use_play_properties_editors:
        limit_playback_redraw(win.screen)
    if win.workspace.m3d_layout < ANIM_LAYOUT:
        area = bottom_area(win.screen)
        if area is not None:
            tidy_bottom_editor(area)
        win.workspace.m3d_layout = ANIM_LAYOUT


classes = (
    M3D_AnimSetItem,
    M3D_AnimSet,
    M3D_AnimSettings,
    M3D_UL_anim_sets,
    M3D_OT_set_key,
    M3D_OT_tween,
    M3D_OT_anim_revert,
    M3D_OT_anim_key_type,
    M3D_OT_anim_euler_filter,
    M3D_OT_anim_range,
    M3D_OT_anim_fps,
    M3D_OT_anim_interp,
    M3D_OT_anim_editor,
    M3D_OT_anim_preset,
    M3D_OT_anim_set,
    M3D_OT_anim_pick_bones,
    M3D_OT_anim_mirror_pose,
    M3D_OT_anim_mirror_animation,
    M3D_OT_anim_world_position,
    M3D_OT_anim_paths,
    M3D_OT_anim_graph,
    M3D_OT_anim_layer,
    M3D_OT_playblast,
    M3D_MT_anim_poses,
    M3D_PT_anim_autokey,
    PROPERTIES_PT_m3d_an_camera,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_an_object_sets,
    PROPERTIES_PT_m3d_an_controls,
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


def draw_zoom_region(self, _context):
    """View menu of the Graph Editor and the Dope Sheet: Zoom Region (Z is Undo there, as everywhere)."""
    self.layout.separator()
    self.layout.operator("view2d.zoom_border", text="Zoom Region...")


ZOOM_MENUS = ("GRAPH_MT_view", "DOPESHEET_MT_view")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_anim = PointerProperty(type=M3D_AnimSettings)
    for menu in ZOOM_MENUS:
        getattr(bpy.types, menu).append(draw_zoom_region)


def unregister():
    for menu in ZOOM_MENUS:
        getattr(bpy.types, menu).remove(draw_zoom_region)
    del bpy.types.Scene.m3d_anim
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
