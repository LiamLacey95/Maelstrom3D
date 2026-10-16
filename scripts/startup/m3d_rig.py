# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Rigging workspace (F5) for Maelstrom3D: the dock pages (Skeleton, Controls & Constraints, Skin, Drive, Test,
Collections), the Bone Collections page on the left, the Rigging Status Line, shelf items and the operators behind
them (modes, Joint tool, Orient Joint, control shapes, IK with pole, bind and weights, Driven Key, naming check).

The layout is built by tools/m3d/build_startup.py (phase4_rigging), the tabs are DOCK_TABS['RIG'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py. Controls that Blender already draws (the bone collection tree,
shape keys, selection sets) are re-used on the pages.
"""

import math
import re
from collections import namedtuple

import bmesh
import bpy
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList
from bpy_extras.anim_utils import action_ensure_channelbag_for_slot, animdata_get_channelbag_for_assigned_slot
from mathutils import Euler, Matrix, Quaternion, Vector

from m3d_mode import _button
from m3d_sculpt import draw_list, draw_lines, draw_object_picks, empty_state, grid, reason, split_props, viewport
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Finding the skeleton, the mesh and the mode

def armature_of(ob):
    """The skeleton `ob` is, or deforms `ob` (its Armature modifier, else its parent), or None."""
    if ob is None:
        return None
    if ob.type == 'ARMATURE':
        return ob
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object is not None:
            return mod.object
    return ob.parent if ob.parent is not None and ob.parent.type == 'ARMATURE' else None


def rig_of(context):
    """The skeleton to work on: the active armature, else the one the active or a selected mesh is bound to, else
    the only armature of the view layer."""
    rig = armature_of(context.active_object)
    if rig is None:
        rig = next((r for r in map(armature_of, context.selected_objects) if r is not None), None)
    if rig is None:
        rigs = [o for o in context.view_layer.objects if o.type == 'ARMATURE']
        rig = rigs[0] if len(rigs) == 1 else None
    return rig


def skin_mesh(context):
    """The mesh to skin or paint: the active mesh, else a selected one, else a mesh bound to the skeleton."""
    ob = context.active_object
    if ob is not None and ob.type == 'MESH':
        return ob
    mesh = next((o for o in context.selected_objects if o.type == 'MESH'), None)
    if mesh is None:
        rig = rig_of(context)
        mesh = next((o for o in context.view_layer.objects if o.type == 'MESH' and armature_of(o) is rig), None) \
            if rig is not None else None
    return mesh


def is_bound(ob):
    """True for a mesh with an Armature modifier that has a skeleton."""
    return ob is not None and ob.type == 'MESH' and any(m.type == 'ARMATURE' and m.object for m in ob.modifiers)


def selected_pose_bones(rig):
    """Selected, visible pose bones of `rig` (the active one when nothing is selected)."""
    bones = [pb for pb in rig.pose.bones if pb.select and not pb.hide]
    active = rig.data.bones.active
    if not bones and active is not None:
        bones = [rig.pose.bones[active.name]]
    return bones


# What a page needs. need -> (message, (button label, operator, icon, properties))
FIXES = {
    'RIG': ("No skeleton yet: draw one with the Joint Tool", ("Joint Tool", "m3d.rig_joint", 'BONE_DATA', {})),
    'EDIT': ("Enter Edit Mode to edit the skeleton", ("Edit Mode", "m3d.rig_mode", 'EDITMODE_HLT', {"mode": 'EDIT'})),
    'POSE': ("Enter Pose Mode to work on the bones", ("Pose Mode", "m3d.rig_mode", 'POSE_HLT', {"mode": 'POSE'})),
    'MESH': ("Select the mesh to skin", None),   # (draw_fixes: the scene's meshes, or F1 Modeling)
    'WEIGHT': ("Enter Weight Paint Mode to paint", ("Weight Paint Mode", "m3d.rig_mode", 'WPAINT_HLT',
                                                    {"mode": 'WEIGHT_PAINT'})),
}


def has(context, need):
    return {'RIG': lambda: rig_of(context) is not None,
            'EDIT': lambda: context.mode == 'EDIT_ARMATURE',
            'POSE': lambda: context.mode == 'POSE',
            'MESH': lambda: skin_mesh(context) is not None,
            'WEIGHT': lambda: context.mode == 'PAINT_WEIGHT'}[need]()


def missing(context, needs):
    """The needs (in the order given) that are not met yet: a skeleton comes before a mode."""
    return [n for n in needs if not has(context, n)]


def ready(context, needs):
    return not missing(context, needs)


def draw_fixes(layout, context, needs):
    """The card of the first need that is missing (a skeleton comes before a mode)."""
    need = missing(context, needs)[0]
    text, action = FIXES[need]
    if need != 'MESH':
        empty_state(layout, context, text, action)
        return
    meshes = [o for o in context.view_layer.objects if o.type == 'MESH' and o.visible_get()]
    if not meshes:
        empty_state(layout, context, "No mesh to skin yet: model one in F1 Modeling",
                    ("F1 Modeling", "m3d.workspace", 'EDITMODE_HLT', {"kind": 'MODEL'}))
        return
    # (added to the selection: the skeleton stays selected, as Bind wants it)
    draw_object_picks(empty_state(layout, context, text), sorted(meshes, key=is_bound), extend=True)


# -----------------------------------------------------------------------------
# Settings

AXES = [('+X', "+X", ""), ('-X', "-X", ""), ('+Y', "+Y", ""), ('-Y', "-Y", ""), ('+Z', "+Z", ""), ('-Z', "-Z", "")]
# (id, label, property, index): the channels a Driven Key reads and drives
CHANNELS = tuple((("%s_%s" % (short, axis)), "%s %s" % (label, axis), attr, i)
                 for short, label, attr in (("LOC", "Location", "location"), ("ROT", "Rotation", "rotation_euler"),
                                            ("SCL", "Scale", "scale"))
                 for i, axis in enumerate("XYZ")) + (('PROP', "Custom Property", None, -1),)
CHANNEL_BY_ID = {c[0]: c for c in CHANNELS}
CHANNEL_ITEMS = [(c[0], c[1], "") for c in CHANNELS]


def _pointer(label, desc, poll=None):
    return PointerProperty(name=label, type=bpy.types.Object, description=desc, poll=poll)


class M3D_RigSettings(PropertyGroup):
    """Rigging workspace options (Scene.m3d_rig)."""
    joint_name: StringProperty(name="Name", default="Bone", description="Name of the bones the Joint tool makes: a list "
                               "(Shoulder, Elbow, Wrist) names them in order, a name ending in a number (Arm_01) counts up")
    joint_place: EnumProperty(name="Place", default='PLANE', items=(
        ('PLANE', "View Plane", "Joints go on the plane through the last joint (or the 3D cursor) facing the view"),
        ('SURFACE', "Surface", "Joints go where the mouse is over a mesh (the view plane where it is not)")),
        description="Where the Joint tool puts a joint")
    joint_inset: FloatProperty(name="Inset", default=0.0, min=0.0, soft_max=1.0, unit='LENGTH',
                               description="Surface placement: push the joint this far into the mesh")
    joint_snap: BoolProperty(name="Snap to Joints", default=True,
                             description="A click close to an existing joint uses that joint (a chain can continue "
                             "from the tip of a bone, or branch from its start)")
    orient_axis: EnumProperty(name="Bone Axis", default='Z', items=(
        ('Z', "Z", "The bone's Z axis points along the direction"), ('X', "X", "The bone's X axis points along the direction")),
        description="Which side axis of the bone follows the direction (the Y axis always runs along the bone)")
    orient_dir: EnumProperty(name="Direction", default='+Z', items=AXES,
                             description="World direction the chosen axis points to (as far as the bone allows)")
    control_color: FloatVectorProperty(name="Color", subtype='COLOR', size=3, min=0.0, max=1.0,
                                       default=(0.95, 0.35, 0.1), description="Color of control bones")
    control_scale: FloatProperty(name="Scale", default=1.0, min=0.01, soft_max=10.0,
                                 description="Size of the control shape relative to the bone")
    ik_chain: IntProperty(name="Chain Length", default=2, min=1, max=32,
                          description="Bones the IK chain has, counted up from the active bone")
    ik_pole: FloatProperty(name="Pole Distance", default=0.6, min=0.0, soft_max=3.0,
                           description="How far the pole target sits from the middle joint, as a fraction of the chain length")
    skin_method: EnumProperty(name="Weights", default='AUTO', items=(
        ('AUTO', "Automatic", "Weights from the distance to the bones (bone heat)"),
        ('ENVELOPE', "Envelope", "Weights from the bones' envelopes"),
        ('EMPTY', "Empty Groups", "A vertex group per bone, no weights: paint them yourself")))
    skin_fallback: BoolProperty(name="Fall Back to Envelope", default=True,
                                description="When automatic weights leave vertices without weight, bind again with envelope weights")
    skin_limit: IntProperty(name="Max Influences", default=4, min=1, max=32, description="Groups a vertex keeps")
    skin_clean: FloatProperty(name="Threshold", default=0.01, min=0.0, max=1.0, description="Weights below this are removed")
    skin_smooth: FloatProperty(name="Smooth", default=0.5, min=0.0, max=1.0, description="Strength of one smoothing pass")
    skin_repeat: IntProperty(name="Passes", default=1, min=1, max=100, description="Smoothing passes")
    weight_value: FloatProperty(name="Weight", default=1.0, min=0.0, max=1.0,
                                description="Value the weight table sets on the selected vertices")
    weight_normalize: BoolProperty(name="Normalize", default=True,
                                   description="Setting or removing a weight in the table scales the vertex's other "
                                   "unlocked bone weights so they all add up to 1")
    select_threshold: FloatProperty(name="Above", default=0.1, min=0.0, max=1.0,
                                    description="Select Weighted Vertices: vertices with more weight than this")
    keep_offset: BoolProperty(name="Keep Offset", default=True,
                              description="A new Copy Location / Rotation / Scale / Transforms or Child Of constraint keeps "
                              "the bone or object where it is and adds the target's moves (off: it jumps onto the target)")
    euler_bones: BoolProperty(name="New Bones in XYZ Euler", default=True,
                              description="Bones made from now on rotate in XYZ Euler (rotate order XYZ) instead of "
                              "quaternions")
    rename_chain: StringProperty(name="Names", default="Shoulder, Elbow, Wrist",
                                 description="Rename Chain: the names from the root of the selected chain to its tip (a "
                                 "name ending in a number counts up: Spine_01); a chain on one side gets .L or .R")
    rom_angle: FloatProperty(name="Angle", default=math.radians(60.0), min=0.0, max=math.pi, subtype='ANGLE',
                             description="How far the range-of-motion test turns each bone, both ways, around each axis")
    transfer_source: _pointer("Source", "Mesh the weights are copied from",
                              lambda self, ob: ob.type == 'MESH')
    pose_name: StringProperty(name="Pose", default="Pose", description="Name of the pose asset")
    # Driven Key: the channel that drives (driver) and the channel that follows (driven)
    dk_driver_object: _pointer("Object", "Object that drives")
    dk_driver_bone: StringProperty(name="Bone", description="Bone that drives (empty: the object itself)")
    dk_driver_channel: EnumProperty(name="Channel", items=CHANNEL_ITEMS, default='ROT_X')
    dk_driver_prop: StringProperty(name="Property", description="Name of the custom property")
    dk_kind: EnumProperty(name="Drives", default='BONE', items=(
        ('BONE', "Channel", "A transform or custom property of an object or bone"),
        ('SHAPE_KEY', "Shape Key", "The value of a shape key")))
    dk_driven_object: _pointer("Object", "Object that follows")
    dk_driven_bone: StringProperty(name="Bone", description="Bone that follows (empty: the object itself)")
    dk_driven_channel: EnumProperty(name="Channel", items=CHANNEL_ITEMS, default='LOC_X')
    dk_driven_prop: StringProperty(name="Property", description="Name of the custom property")
    dk_driven_shape: StringProperty(name="Shape Key", description="Shape key that follows")
    dk_value: FloatProperty(name="Driven Value", default=0.0, description="Value the driven channel gets at the "
                            "driver's current value")
    dk_interp: EnumProperty(name="Curve", default='BEZIER', items=(
        ('BEZIER', "Smooth", "Smooth curve through the keys"), ('LINEAR', "Linear", "Straight lines between the keys"),
        ('CONSTANT', "Stepped", "Holds each value until the next key")))
    rigify_note: StringProperty(description="Result of the last Rigify step")
    qr_mesh: _pointer("Mesh", "The character mesh Quick Rig places the guides on", lambda self, ob: ob.type == 'MESH')
    qr_rigify: BoolProperty(name="Rigify Control Rig", default=False,
                            description="Fit the Rigify human meta-rig to the guides and generate its control rig (IK / FK "
                            "arms and legs, a torso); off: a simple skeleton of plain bones")


# -----------------------------------------------------------------------------
# Modes: Object / Edit / Pose / Weight Paint (what each needs selected)

def _select_only(context, ob):
    layer = context.view_layer
    if ob.hide_get(view_layer=layer):
        ob.hide_set(False, view_layer=layer)
    for o in layer.objects:
        if o.select_get(view_layer=layer):
            o.select_set(False, view_layer=layer)
    ob.select_set(True, view_layer=layer)
    layer.objects.active = ob


def leave_modes(context):
    """Back to Object Mode for every object (a skeleton in Pose Mode and a mesh in Weight Paint Mode together)."""
    layer = context.view_layer
    for _ in range(2):
        active = layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    for ob in layer.objects:
        if ob.mode != 'OBJECT':
            layer.objects.active = ob
            bpy.ops.object.mode_set(mode='OBJECT')


def enter_mode(context, mode):
    """Switch to OBJECT, EDIT, POSE or WEIGHT_PAINT the way the mode needs the selection:
    Edit and Pose act on the skeleton (made active); Weight Paint acts on the mesh while the skeleton stays in Pose
    Mode, so bones can still be picked. Returns None, or a message for what is missing."""
    rig, mesh = rig_of(context), skin_mesh(context)
    leave_modes(context)
    if mode == 'OBJECT':
        return None
    if mode == 'WEIGHT_PAINT':
        if mesh is None:
            return "Select a mesh to paint weights on"
        skeleton = armature_of(mesh)
        if skeleton is None:
            _select_only(context, mesh)
        else:   # The skeleton goes to Pose Mode first and stays selected: the mesh then paints with bones to pick.
            _select_only(context, skeleton)
            bpy.ops.object.mode_set(mode='POSE')
            if mesh.hide_get(view_layer=context.view_layer):
                mesh.hide_set(False, view_layer=context.view_layer)
            mesh.select_set(True, view_layer=context.view_layer)
            context.view_layer.objects.active = mesh
            # A bound mesh paints with Auto Normalize: its bone weights keep adding up to 1 (the Skin tab has the switch).
            context.tool_settings.use_auto_normalize = True
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        return None
    target = rig if rig is not None else context.active_object
    if mode == 'POSE' and rig is None:
        return "There is no skeleton: place joints with the Joint tool first"
    if target is None:
        return "Select an object first"
    _select_only(context, target)
    bpy.ops.object.mode_set(mode=mode)
    return None


class M3D_OT_rig_mode(Operator):
    """Switch mode: Object, Edit (skeleton), Pose (skeleton) or Weight Paint (the mesh, with its skeleton in Pose Mode)"""
    bl_idname = "m3d.rig_mode"
    bl_label = "Rigging Mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('OBJECT', "Object", ""), ('EDIT', "Edit", ""), ('POSE', "Pose", ""),
                              ('WEIGHT_PAINT', "Weight Paint", "")))

    @classmethod
    def description(cls, _context, props):
        return {'OBJECT': "Object Mode",
                'EDIT': "Edit Mode: place and edit the skeleton's bones (makes the skeleton active)",
                'POSE': "Pose Mode: pose the skeleton, add controls and constraints (makes the skeleton active)",
                'WEIGHT_PAINT': "Weight Paint Mode: paint the active mesh's weights; its skeleton is selected and stays "
                                "in Pose Mode, so bones can be picked (Ctrl+click)"}[props.mode]

    def execute(self, context):
        try:
            message = enter_mode(context, self.mode)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        if message:
            self.report({'WARNING'}, message)
            return {'CANCELLED'}
        follow_mode(context.window_manager)
        return {'FINISHED'}


# Dock tab to open when a mode is entered; the tab the user picked in a mode comes back in that mode.
MODE_TABS = {'EDIT': "rig_skeleton", 'POSE': "rig_controls", 'WEIGHT_PAINT': "rig_skin"}
_state = {"mode": None, "picked": {}}


def mode_key(view_layer):
    """EDIT / POSE / WEIGHT_PAINT while the active object is in that mode (armature edit only), else None."""
    ob = view_layer.objects.active
    if ob is None or ob.mode == 'OBJECT':
        return None
    if ob.mode == 'EDIT':
        return 'EDIT' if ob.type == 'ARMATURE' else None
    return ob.mode if ob.mode in MODE_TABS else None


def remember_tab(context, tab_id):
    """The user picked a tab of the right-hand dock: it is what that mode opens on from now on."""
    key = mode_key(context.view_layer)
    if key is not None:
        _state["picked"][key] = tab_id


def follow_mode(wm):
    """When the mode changes in the Rigging workspace, open the dock tab that fits it (the user's own pick for that
    mode, else the default). Called by the workspace timer and after a mode button."""
    from m3d_workspace import dock_tabs, workspace_kind
    win = wm.windows[0] if wm.windows else None
    if win is None:
        return
    key = mode_key(win.view_layer)
    prev, _state["mode"] = _state["mode"], key
    if key is None or key == prev or workspace_kind(win.workspace) != 'RIG':
        return
    want = _state["picked"].get(key, MODE_TABS[key])
    tab = next((t for t in dock_tabs('RIG', 'RIGHT') if t.id == want), None)
    docks = [a for a in win.screen.areas if a.type == 'PROPERTIES' and a.x + a.width / 2 > win.width / 2]
    if tab is None or not docks:
        return
    dock = docks[0]
    if dock.spaces.active.context != 'MODELING_TOOLKIT':
        return   # All Settings or the Channel Box: the user is looking at something else on purpose.
    if tab.page:
        win.workspace.m3d_page_right = tab.page
    else:   # (the Channel Box tab, picked in this mode)
        dock.spaces.active.context = tab.context
    dock.tag_redraw()


# -----------------------------------------------------------------------------
# Joint tool

SNAP_PIXELS = 14


def joints_of(rig):
    """[(world position, bone name, 'HEAD' or 'TAIL')] of the bones of a skeleton (in Edit Mode: the edit bones)."""
    editing = rig.mode == 'EDIT'
    mat = rig.matrix_world
    out = []
    for b in (rig.data.edit_bones if editing else rig.data.bones):
        head, tail = (b.head, b.tail) if editing else (b.head_local, b.tail_local)
        out.append((mat @ head, b.name, 'HEAD'))
        out.append((mat @ tail, b.name, 'TAIL'))
    return out


def new_armature(context, name="Armature"):
    """A skeleton object in the active collection: octahedral bones, drawn in front of the meshes."""
    arm = bpy.data.armatures.new(name)
    arm.display_type = 'OCTAHEDRAL'
    rig = bpy.data.objects.new(name, arm)
    rig.show_in_front = True
    context.collection.objects.link(rig)
    return rig


def chain_name(names, i):
    """Name of the i-th bone (from 0) of a chain named by `names`: a list ("Shoulder, Elbow, Wrist") names the bones in
    order (Blender numbers the last name when the chain is longer), a name ending in a number counts up from it (Arm_01,
    Arm_02; before a side: Arm_01.L, Arm_02.L), any other name is numbered by Blender (Bone, Bone.001)."""
    parts = [n.strip() for n in names.split(",") if n.strip()] or ["Bone"]
    if len(parts) > 1:
        return parts[min(i, len(parts) - 1)]
    side = SIDE_SUFFIX.search(parts[0])
    stem, suffix = (parts[0][:side.start()], side.group(0)) if side else (parts[0], "")
    number = re.search(r"\d+$", stem)
    if number is None:
        return parts[0]
    return "%s%0*d%s" % (stem[:number.start()], len(number.group(0)), int(number.group(0)) + i, suffix)


class JointChain:
    """The joints and bones the Joint tool has placed in one go (the tool only handles the mouse and the keys)."""

    def __init__(self, rig_name, base_name="Bone"):
        self.rig_name, self.base = rig_name, base_name or "Bone"
        self.joints = []      # world positions
        self.bones = []       # names of the bones made
        self.parent = None    # the bone the next one hangs from
        self.connect = False  # ...and whether it starts at that bone's tip

    @property
    def rig(self):
        return bpy.data.objects[self.rig_name]

    def add(self, pos, snapped=None):
        """A joint at world position `pos`. The first one starts the chain: snapped to the tip of a bone it continues
        that bone, snapped to the start of one it branches from that bone's parent. Later ones add a bone."""
        arm = self.rig.data
        if not self.joints:
            self.joints.append(Vector(pos))
            if snapped is not None:
                name, which = snapped
                bone = arm.edit_bones[name]
                self.parent = name if which == 'TAIL' else (bone.parent.name if bone.parent else None)
                self.connect = which == 'TAIL' or bool(bone.use_connect)
            return None
        prev = self.joints[-1]
        if (pos - prev).length < 1e-6:
            return None
        inv = self.rig.matrix_world.inverted()
        eb = arm.edit_bones.new(chain_name(self.base, len(self.bones)))
        eb.head, eb.tail = inv @ prev, inv @ pos
        if self.parent is not None and self.parent in arm.edit_bones:
            eb.parent = arm.edit_bones[self.parent]
            eb.use_connect = self.connect
        for b in arm.edit_bones:
            b.select = b.select_head = b.select_tail = False
        eb.select = eb.select_head = eb.select_tail = True
        arm.edit_bones.active = eb
        self.bones.append(eb.name)
        self.parent, self.connect = eb.name, True
        self.joints.append(Vector(pos))
        return eb.name

    def remove_last(self):
        arm = self.rig.data
        if self.joints:
            self.joints.pop()
        if self.bones:
            eb = arm.edit_bones.get(self.bones.pop())
            if eb is not None:
                arm.edit_bones.remove(eb)
            self.parent = self.bones[-1] if self.bones else None

    def discard(self):
        """Take back every bone of the chain."""
        while self.bones:
            self.remove_last()
        self.joints.clear()

    def mirror(self):
        """X-Mirror: a chain on one side gets a .L name and a mirrored .R copy (or .R and .L). Returns a message when
        the chain was not mirrored."""
        arm = self.rig.data
        bones = [arm.edit_bones[n] for n in self.bones]
        if not bones:
            return None
        side = side_by_position(bones, True)
        if not side:
            return "X-Mirror: the chain crosses the center, so it was not mirrored"
        direction = 'POSITIVE_X' if side == ".L" else 'NEGATIVE_X'
        for b in bones:
            if not side_of_name(b.name):
                b.name = b.name + side
        self.bones = [b.name for b in bones]
        for b in arm.edit_bones:
            b.select = b.select_head = b.select_tail = False
        for b in bones:
            b.select = b.select_head = b.select_tail = True
        bpy.ops.armature.symmetrize(direction=direction)
        return None


class M3D_OT_rig_joint(Operator):
    """Joint tool: click to place joints, each click adds a bone from the last joint (a chain). Enter or right-click
finishes, Backspace removes the last joint, Esc cancels. Click on an existing joint to continue or branch from it"""
    bl_idname = "m3d.rig_joint"
    bl_label = "Joint Tool"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and context.region_data is not None

    def invoke(self, context, event):
        rig = rig_of(context)
        self.created = rig is None
        if rig is None:
            rig = new_armature(context)
        leave_modes(context)
        _select_only(context, rig)
        bpy.ops.object.mode_set(mode='EDIT')
        self.chain = JointChain(rig.name, context.scene.m3d_rig.joint_name)
        self.area, self.region = context.area, context.region
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("Joint tool: click to place a joint   Enter / right-click: finish   "
                                          "Backspace: undo last joint   Esc: cancel")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def draw_overlay(self):
        try:
            import gpu
            from bpy_extras.view3d_utils import location_3d_to_region_2d
            from gpu_extras.batch import batch_for_shader
            rv3d = self.area.spaces.active.region_3d
            pts = [location_3d_to_region_2d(self.region, rv3d, p) for p in self.chain.joints]
            pts = [p for p in pts if p is not None]
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.blend_set('ALPHA')
            if pts:
                shader.uniform_float("color", (1.0, 0.8, 0.2, 0.9))
                batch_for_shader(shader, 'LINE_STRIP', {"pos": [*pts, self.mouse]}).draw(shader)
            gpu.state.point_size_set(9.0)
            batch_for_shader(shader, 'POINTS', {"pos": [*pts, self.mouse]}).draw(shader)
            gpu.state.blend_set('NONE')
        except Exception:   # A drawing problem must never stop the tool.
            pass

    def place(self, context, event):
        """(world position, snapped joint (bone, 'HEAD' / 'TAIL') or None) under the mouse."""
        from bpy_extras.view3d_utils import (location_3d_to_region_2d, region_2d_to_location_3d,
                                             region_2d_to_origin_3d, region_2d_to_vector_3d)
        s = context.scene.m3d_rig
        region, rv3d = self.region, self.area.spaces.active.region_3d
        co = Vector((event.mouse_region_x, event.mouse_region_y))
        if s.joint_snap:
            best = None
            for pos, name, which in joints_of(self.chain.rig):
                p = location_3d_to_region_2d(region, rv3d, pos)
                if p is not None and (p - co).length < SNAP_PIXELS and (best is None or (p - co).length < best[0]):
                    best = ((p - co).length, pos, (name, which))
            if best is not None:
                return best[1], best[2]
        if s.joint_place == 'SURFACE':
            origin, vec = region_2d_to_origin_3d(region, rv3d, co), region_2d_to_vector_3d(region, rv3d, co)
            hit, loc, _n, _i, _ob, _m = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, vec)
            if hit:
                return loc + vec.normalized() * s.joint_inset, None
        depth = self.chain.joints[-1] if self.chain.joints else context.scene.cursor.location
        return region_2d_to_location_3d(region, rv3d, co, depth), None

    def inside(self, event):
        r = self.region
        return r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'} or \
                event.type.startswith(('NDOF', 'TRACKPAD')) or (event.alt and event.type != 'ESC'):
            return {'PASS_THROUGH'}   # Navigation.
        if event.type == 'MOUSEMOVE':
            self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self.area.tag_redraw()
            return {'PASS_THROUGH'}
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self.finish(context)
        if event.type == 'RIGHTMOUSE' and self.inside(event):
            return self.finish(context) if event.value == 'PRESS' else {'RUNNING_MODAL'}
        if event.type == 'ESC' and event.value == 'PRESS':
            return self.cancel(context)
        if event.type == 'BACK_SPACE' and event.value == 'PRESS':
            self.chain.remove_last()
            self.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and self.inside(event):   # The release and click events are ours too.
            if event.value == 'PRESS':
                self.chain.add(*self.place(context, event))
                self.area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def stop(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self.handler, 'WINDOW')
        context.workspace.status_text_set(None)
        self.area.tag_redraw()

    def finish(self, context):
        self.stop(context)
        chain = self.chain
        if chain.bones and chain.rig.data.use_mirror_x:
            message = chain.mirror()
            if message:
                self.report({'INFO'}, message)
        if not chain.bones:
            self.discard_empty()
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        self.stop(context)
        self.chain.discard()
        self.discard_empty()
        return {'CANCELLED'}

    def discard_empty(self):
        """A skeleton this run made and gave no bones is taken away again."""
        rig = self.chain.rig
        if self.created and not rig.data.edit_bones:
            arm = rig.data
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(rig)
            bpy.data.armatures.remove(arm)


# -----------------------------------------------------------------------------
# Orient Joint

def orient_edit_bone(eb, direction, axis):
    """Roll an edit bone so its side axis `axis` ('X' or 'Z') points along `direction` (armature space; the part of it
    across the bone). Returns False when the direction runs along the bone: the bone is left alone."""
    y = (eb.tail - eb.head).normalized()
    d = direction - y * direction.dot(y)
    if d.length < 1e-4:
        return False
    d.normalize()
    if axis == 'Z':
        z = d
        x = y.cross(z)
    else:
        x = d
        z = x.cross(y)
    eb.roll = bpy.types.Bone.AxisRollFromMatrix(Matrix((x, y, z)).transposed(), axis=y)[1]
    return True


def axis_vector(name):
    return Vector({'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[name[1]]) * (1 if name[0] == '+' else -1)


def orient_bones(rig, bones, direction_name, axis):
    """Orient `bones` (edit bones of `rig`) to a world direction; a bone that runs along it uses -Y (or +Z when the bone
    runs along Y). With X-Mirror on, Blender rolls the opposite bone to match, so a bone whose twin is done is skipped.
    Returns the number of bones oriented."""
    arm = rig.data
    inv = rig.matrix_world.to_3x3().inverted()
    done = set()
    for eb in bones:
        if arm.use_mirror_x and bpy.utils.flip_name(eb.name) in done:
            continue
        d = inv @ axis_vector(direction_name)
        if not orient_edit_bone(eb, d, axis):
            d = inv @ (axis_vector('+Z') if abs((eb.tail - eb.head).normalized().y) > 0.9 else axis_vector('-Y'))
            orient_edit_bone(eb, d, axis)
        done.add(eb.name)
    return len(done)


def selected_edit_bones(arm):
    """Selected bones of the skeleton in Edit Mode, or all of them when nothing is selected."""
    chosen = [b for b in arm.edit_bones if b.select or b.select_head or b.select_tail]
    return chosen or list(arm.edit_bones)


class M3D_OT_rig_orient(Operator):
    """Orient Joint: roll the selected bones (all when none) so the chosen side axis points to a world direction. The
bone's Y axis always runs from its start to its tip. A bone that runs along the direction uses -Y instead"""
    bl_idname = "m3d.rig_orient"
    bl_label = "Orient Joint"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name="Bone Axis", items=(('Z', "Z", ""), ('X', "X", "")), default='Z')
    direction: EnumProperty(name="Direction", items=AXES, default='+Z')
    use_settings: BoolProperty(default=True, options={'SKIP_SAVE'},
                               description="Take the axis and direction from the Skeleton tab")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'ARMATURE' and ob.mode == 'EDIT'

    def execute(self, context):
        s = context.scene.m3d_rig
        axis, direction = (s.orient_axis, s.orient_dir) if self.use_settings else (self.axis, self.direction)
        rig = context.active_object
        n = orient_bones(rig, selected_edit_bones(rig.data), direction, axis)
        self.report({'INFO'}, "Oriented %d bones: %s axis to %s" % (n, axis, direction))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Control shapes (widgets) and colors

def _ring(plane, n=32, r=0.5):
    pts = []
    for i in range(n):
        a = math.tau * i / n
        c, s = r * math.cos(a), r * math.sin(a)
        pts.append({'XZ': (c, 0.0, s), 'XY': (c, s, 0.0), 'YZ': (0.0, c, s)}[plane])
    return pts, [(i, (i + 1) % n) for i in range(n)]


def _loop(points):
    return list(points), [(i, (i + 1) % len(points)) for i in range(len(points))]


def _merge(*parts):
    verts, edges = [], []
    for v, e in parts:
        edges += [(a + len(verts), b + len(verts)) for a, b in e]
        verts += v
    return verts, edges


def _arrow(swap):
    pts = [(-0.1, 0.0), (0.1, 0.0), (0.1, 0.6), (0.3, 0.6), (0.0, 1.0), (-0.3, 0.6), (-0.1, 0.6)]
    return _loop([(0.0, y, x) if swap else (x, y, 0.0) for x, y in pts])


def _cube():
    pts = [(x, y, z) for z in (-0.5, 0.5) for y in (-0.5, 0.5) for x in (-0.5, 0.5)]
    edges = [(a, b) for a in range(8) for b in range(a + 1, 8) if bin(a ^ b).count("1") == 1]
    return pts, edges


# shape id -> (label, icon, builder): shapes lie across the bone (its Y axis) and are 1 bone length wide
SHAPES = {
    'CIRCLE': ("Circle", 'MESH_CIRCLE', lambda: _ring('XZ')),
    'SQUARE': ("Square", 'MESH_PLANE', lambda: _loop([(-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 0.0, 0.5), (-0.5, 0.0, 0.5)])),
    'ARROW': ("Arrow", 'EMPTY_SINGLE_ARROW', lambda: _merge(_arrow(False), _arrow(True))),
    'CUBE': ("Cube", 'MESH_CUBE', _cube),
    'SPHERE': ("Sphere", 'MESH_UVSPHERE', lambda: _merge(_ring('XZ'), _ring('XY'), _ring('YZ'))),
}
SHAPE_ITEMS = [(k, v[0], "") for k, v in SHAPES.items()]
WIDGETS = "Widgets"


def widget_collection(context):
    """The hidden collection that holds the control shape meshes (made on first use)."""
    coll = bpy.data.collections.get(WIDGETS) or bpy.data.collections.new(WIDGETS)
    root = context.scene.collection
    if coll.name not in root.children:
        root.children.link(coll)
    coll.hide_render = True

    def find(lc):
        if lc.collection is coll:
            return lc
        return next(filter(None, (find(c) for c in lc.children)), None)
    layer_coll = find(context.view_layer.layer_collection)
    if layer_coll is not None:
        layer_coll.hide_viewport = True
    return coll


def widget_object(context, shape):
    """The mesh object of a control shape, made the first time. Edges only: it draws as a wire shape."""
    name = "WGT-" + SHAPES[shape][0]
    ob = bpy.data.objects.get(name)
    if ob is None or ob.type != 'MESH':
        verts, edges = SHAPES[shape][2]()
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, edges, [])
        ob = bpy.data.objects.new(name, mesh)
        widget_collection(context).objects.link(ob)
    elif ob.name not in widget_collection(context).objects:
        widget_collection(context).objects.link(ob)
    return ob


def lighter(rgb, amount):
    return tuple(c + (1.0 - c) * amount for c in rgb)


def color_pose_bone(pb, rgb):
    """A custom color set for a pose bone: normal as given, selected and active lighter."""
    pb.color.palette = 'CUSTOM'
    custom = pb.color.custom
    custom.normal, custom.select, custom.active = rgb, lighter(rgb, 0.35), lighter(rgb, 0.7)


COLOR_PRESETS = (('PICKED', "Picked Color", ""), ('RED', "Red", ""), ('GREEN', "Green", ""), ('BLUE', "Blue", ""),
                 ('YELLOW', "Yellow", ""))
PRESET_RGB = {'RED': (0.9, 0.15, 0.15), 'GREEN': (0.2, 0.8, 0.25), 'BLUE': (0.2, 0.4, 0.95), 'YELLOW': (0.95, 0.85, 0.15)}


class M3D_OT_rig_control(Operator):
    """Give the selected bones a control shape (a circle, square, arrow, cube or sphere), with the picked color"""
    bl_idname = "m3d.rig_control"
    bl_label = "Control Shape"
    bl_options = {'REGISTER', 'UNDO'}

    shape: EnumProperty(items=[*SHAPE_ITEMS, ('NONE', "No Shape", "")])
    use_color: BoolProperty(name="Color", default=True, description="Also color the bones")

    @classmethod
    def description(cls, _context, props):
        if props.shape == 'NONE':
            return "Remove the custom shape of the selected bones"
        return "Give the selected bones a %s control shape and the picked color (size and color are in the Controls tab)" \
            % SHAPES[props.shape][0].lower()

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None and context.mode != 'EDIT_ARMATURE'

    def execute(self, context):
        rig, s = rig_of(context), context.scene.m3d_rig
        bones = selected_pose_bones(rig)
        if not bones:
            self.report({'WARNING'}, "Select a bone first")
            return {'CANCELLED'}
        wgt = None if self.shape == 'NONE' else widget_object(context, self.shape)
        for pb in bones:
            pb.custom_shape = wgt
            if wgt is not None:
                pb.custom_shape_scale_xyz = (s.control_scale,) * 3
                if self.use_color:
                    color_pose_bone(pb, tuple(s.control_color))
        self.report({'INFO'}, "%s for %d bone(s)" % ("No shape" if wgt is None else SHAPES[self.shape][0], len(bones)))
        return {'FINISHED'}


class M3D_OT_rig_control_color(Operator):
    """Color the selected bones (the picked color, or a preset); Default goes back to the theme colors"""
    bl_idname = "m3d.rig_control_color"
    bl_label = "Bone Color"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(items=[*COLOR_PRESETS, ('DEFAULT', "Default", "")])

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None and context.mode != 'EDIT_ARMATURE'

    def execute(self, context):
        rig = rig_of(context)
        bones = selected_pose_bones(rig)
        for pb in bones:
            if self.preset == 'DEFAULT':
                pb.color.palette = 'DEFAULT'
            else:
                rgb = tuple(context.scene.m3d_rig.control_color) if self.preset == 'PICKED' else PRESET_RGB[self.preset]
                color_pose_bone(pb, rgb)
        return {'FINISHED'}


class M3D_OT_rig_lock(Operator):
    """Lock or unlock the transform channels of the selected bones"""
    bl_idname = "m3d.rig_lock"
    bl_label = "Lock Channels"
    bl_options = {'REGISTER', 'UNDO'}

    channels: EnumProperty(items=(('LOCATION', "Location", ""), ('ROTATION', "Rotation", ""), ('SCALE', "Scale", ""),
                                  ('ALL', "All", "")))
    lock: BoolProperty(default=True)

    @classmethod
    def description(cls, _context, props):
        return "%s %s of the selected bones" % ("Lock" if props.lock else "Unlock", props.channels.lower())

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None and context.mode != 'EDIT_ARMATURE'

    def execute(self, context):
        for pb in selected_pose_bones(rig_of(context)):
            if self.channels in {'LOCATION', 'ALL'}:
                pb.lock_location = (self.lock,) * 3
            if self.channels in {'ROTATION', 'ALL'}:
                pb.lock_rotation = (self.lock,) * 3
                pb.lock_rotation_w = self.lock
            if self.channels in {'SCALE', 'ALL'}:
                pb.lock_scale = (self.lock,) * 3
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Rotate order: XYZ ... ZYX Euler, Quaternion or Axis Angle, keeping the pose and the keys

ROTATE_ORDERS = [(m, m.replace("_", " ").title() if len(m) > 3 else m, "") for m in
                 ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX', 'QUATERNION', 'AXIS_ANGLE')]
ROTATE_LABELS = {m: label for m, label, _d in ROTATE_ORDERS}


def rotation_attr(mode):
    """The property that holds a rotation in `mode`."""
    return {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(mode, "rotation_euler")


def to_quaternion(mode, values):
    if mode == 'QUATERNION':
        return Quaternion(values).normalized()
    if mode == 'AXIS_ANGLE':
        return Quaternion(Vector(values[1:]), values[0])
    return Euler(values, mode).to_quaternion()


def from_quaternion(mode, q, prev=None):
    """The values of rotation `q` in `mode`, the closest ones to `prev` (the values of the key before: no flips)."""
    if mode == 'QUATERNION':
        if prev is not None:
            q.make_compatible(Quaternion(prev))
        return tuple(q)
    if mode == 'AXIS_ANGLE':
        axis, angle = q.to_axis_angle()
        return (angle, *axis)
    return tuple(q.to_euler(mode, Euler(prev, mode)) if prev is not None else q.to_euler(mode))


def set_rotate_order(owner, mode):
    """Switch an object's or pose bone's rotation mode keeping its pose and its rotation keys: each key is converted on
    its frame (in between, the new curves can take a slightly different path). Returns the number of frames keyed."""
    old = owner.rotation_mode
    if old == mode:
        return 0
    ob = owner.id_data
    prefix = 'pose.bones["%s"].' % bpy.utils.escape_identifier(owner.name) if isinstance(owner, bpy.types.PoseBone) else ""
    ad = ob.animation_data
    bag = animdata_get_channelbag_for_assigned_slot(ad) if ad is not None and ad.action is not None else None
    curves = [fc for fc in bag.fcurves if fc.data_path == prefix + rotation_attr(old)] if bag is not None else []
    rest = list(getattr(owner, rotation_attr(old)))
    samples = []
    for frame in sorted({kp.co.x for fc in curves for kp in fc.keyframe_points}):
        values = list(rest)
        for fc in curves:
            values[fc.array_index] = fc.evaluate(frame)
        samples.append((frame, to_quaternion(old, values)))
    for fc in curves:
        bag.fcurves.remove(fc)
    owner.rotation_mode = mode   # (Blender converts the rotation it has now)
    attr, prev = rotation_attr(mode), None
    for frame, q in samples:
        prev = from_quaternion(mode, q, prev)
        setattr(owner, attr, prev)
        owner.keyframe_insert(attr, frame=frame)
    if samples:
        bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    return len(samples)


class M3D_OT_rig_rotate_order(Operator):
    """Set Rotate Order: the rotation mode of the selected bones (Pose Mode) or objects, keeping their pose and turning
their rotation keys into keys of the new mode"""
    bl_idname = "m3d.rig_rotate_order"
    bl_label = "Set Rotate Order"
    bl_options = {'REGISTER', 'UNDO'}

    order: EnumProperty(name="Rotate Order", items=ROTATE_ORDERS)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.mode in {'OBJECT', 'POSE'}

    def execute(self, context):
        ob = context.active_object
        owners = selected_pose_bones(ob) if ob.type == 'ARMATURE' and ob.mode == 'POSE' else (context.selected_objects or [ob])
        keys = sum(set_rotate_order(o, self.order) for o in owners)
        self.report({'INFO'}, "Rotate order %s for %d %s%s" % (ROTATE_LABELS[self.order], len(owners),
                                                              "bone(s)" if ob.mode == 'POSE' else "object(s)",
                                                              " (%d keyed frames converted)" % keys if keys else ""))
        return {'FINISHED'}


# New bones rotate in XYZ Euler (Scene.m3d_rig.euler_bones): Blender makes them in quaternions. The depsgraph handler
# notices bones it has not seen (a skeleton that leaves Edit Mode, a new skeleton); a timer switches them, outside of the
# evaluation. Bones of a file that is opened are seen, not new; linked skeletons, Rigify rigs and keyed rotations are left.
_bones_seen = {}       # armature object name -> names of its bones
_bones_pending = {}    # armature object name -> names of new bones to switch


def remember_bones():
    _bones_seen.clear()
    _bones_pending.clear()
    for ob in bpy.data.objects:
        if ob.type == 'ARMATURE' and ob.pose is not None:
            _bones_seen[ob.name] = set(ob.pose.bones.keys())


@persistent
def _bones_load(*_args):
    remember_bones()


@persistent
def _bones_update(_scene, depsgraph):
    for update in depsgraph.updates:
        ob = update.id
        if not isinstance(ob, bpy.types.Object) or ob.type != 'ARMATURE':
            continue
        ob = ob.original
        seen = _bones_seen.get(ob.name)
        if ob.pose is None or ob.mode == 'EDIT' or (seen is not None and len(seen) == len(ob.pose.bones)):
            continue
        names = set(ob.pose.bones.keys())
        _bones_seen[ob.name] = names
        new = names - (seen or set())
        if new:
            _bones_pending.setdefault(ob.name, set()).update(new)
            if not bpy.app.timers.is_registered(euler_new_bones):
                bpy.app.timers.register(euler_new_bones, first_interval=0.0)


def euler_new_bones():
    """Switch the new bones the handler found to XYZ Euler (when the setting is on). A timer: returns None."""
    pending = dict(_bones_pending)
    _bones_pending.clear()
    if not bpy.context.scene.m3d_rig.euler_bones:
        return None
    for name, bones in pending.items():
        ob = bpy.data.objects.get(name)
        if ob is None or ob.pose is None or ob.library is not None or ob.override_library is not None or "rig_id" in ob.data:
            continue
        ad = ob.animation_data
        bag = animdata_get_channelbag_for_assigned_slot(ad) if ad is not None and ad.action is not None else None
        keyed = {fc.data_path.split('"')[1] for fc in (bag.fcurves if bag is not None else ())
                 if fc.data_path.startswith("pose.bones[")}
        for pb in (ob.pose.bones.get(n) for n in bones if n not in keyed):
            if pb is not None and pb.rotation_mode == 'QUATERNION':
                pb.rotation_mode = 'XYZ'
    return None


# -----------------------------------------------------------------------------
# IK with a pole target

def ik_chain(arm, end_name, length):
    """The bones of an IK chain from the root to `end_name` (at most `length` bones)."""
    bones, bone = [], arm.bones[end_name]
    while bone is not None and len(bones) < length:
        bones.append(bone)
        bone = bone.parent
    return bones[::-1]


def pole_position(bones, factor):
    """Where the pole target goes: out from the middle joint, away from the line through the chain (-Y when the chain is
    straight), `factor` x the chain length away. Armature space."""
    root, tip = bones[0].head_local, bones[-1].tail_local
    mid = bones[len(bones) // 2].head_local
    total = sum(b.length for b in bones)
    line = tip - root
    away = mid - (root + line * ((mid - root).dot(line) / max(line.dot(line), 1e-12)))
    away = away.normalized() if away.length > 1e-4 * total else Vector((0.0, -1.0, 0.0))
    return mid + away * (factor * total)


def tip_child(bone):
    """The child (bone or edit bone) that starts at the tip of `bone`: the hand of a forearm, the foot of a shin."""
    near = [c for c in bone.children if (c.head - bone.tail).length <= 1e-3 * max(bone.length, 1e-6)]
    return next((c for c in near if c.use_connect), near[0] if near else None)


def ik_with_pole(context, rig, end_name, chain, factor):
    """An IK constraint on `end_name` with a target bone at its tip and, for chains of two or more bones, a pole target
    bone. The pole angle is searched so the chain bends toward the pole. The target and the pole become animator controls
    (ik_controls). Returns (target name, pole name or None)."""
    arm = rig.data
    bones = ik_chain(arm, end_name, chain)
    tip = bones[-1].tail_local.copy()
    total = sum(b.length for b in bones)
    pole_pos = pole_position(bones, factor) if len(bones) > 1 else None
    small = max(total * 0.1, 1e-3)
    mode = rig.mode
    if mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')
    end = arm.edit_bones[end_name]
    hand = tip_child(end)
    target = arm.edit_bones.new("IK_" + end_name)
    # Lined up with the hand (the bone that copies its rotation; else the end bone), so it does not turn at rest.
    along = hand or end
    target.head, target.tail = tip, tip + (along.tail - along.head).normalized() * small
    target.roll = along.roll
    target.use_deform = False
    hand_name = hand.name if hand else None
    pole = None
    if pole_pos is not None:
        pole = arm.edit_bones.new("Pole_" + end_name)
        pole.head, pole.tail = pole_pos, pole_pos + Vector((0.0, 0.0, small))
        pole.use_deform = False
    target_name, pole_name = target.name, pole.name if pole else None
    bpy.ops.object.mode_set(mode='POSE')
    pb = rig.pose.bones[end_name]
    for con in [c for c in pb.constraints if c.type == 'IK']:
        pb.constraints.remove(con)
    con = pb.constraints.new('IK')
    con.target, con.subtarget, con.chain_count = rig, target_name, len(bones)
    if pole_name:
        con.pole_target, con.pole_subtarget = rig, pole_name
        fit_pole_angle(context, rig, con, end_name, pole_pos)
    ik_controls(context, rig, end_name, rig.pose.bones[hand_name] if hand_name else None, con, target_name, pole_name)
    if mode != 'POSE':
        bpy.ops.object.mode_set(mode=mode)
    return target_name, pole_name


IK_SWITCH = "IK_FK"
CONTROLS = "Controls"
SIDE_RGB = {'L': PRESET_RGB['BLUE'], 'R': PRESET_RGB['RED'], '': PRESET_RGB['YELLOW']}


def ik_controls(context, rig, end_name, hand, con, target_name, pole_name):
    """Make an IK setup ready to animate: a cube shape on the target and a sphere on the pole, coloured by side (.L blue,
    .R red, middle yellow), both in the "Controls" bone collection; the hand (the bone at the end of the chain, if there is
    one) copies the target's rotation; an IK_FK property on the target (0 = IK, 1 = FK; a slider in the Channel Box)
    drives the IK and that rotation."""
    rgb = SIDE_RGB[side_of_name(end_name)]
    coll = rig.data.collections.get(CONTROLS) or rig.data.collections.new(CONTROLS)
    for name, shape, scale in ((target_name, 'CUBE', 2.0), (pole_name, 'SPHERE', 1.0)):
        if name is None:
            continue
        pb = rig.pose.bones[name]
        pb.custom_shape = widget_object(context, shape)
        pb.custom_shape_scale_xyz = (scale,) * 3
        color_pose_bone(pb, rgb)
        coll.assign(pb)
    target = rig.pose.bones[target_name]
    target[IK_SWITCH] = 0.0
    target.id_properties_ui(IK_SWITCH).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                                              description="0 = IK (the target moves the limb), 1 = FK (rotate its bones)")
    target.property_overridable_library_set('["%s"]' % IK_SWITCH, True)
    driven = [con]
    if hand is not None:
        follow = hand.constraints.new('COPY_ROTATION')
        follow.name, follow.target, follow.subtarget = "IK Rotation", rig, target_name
        driven.append(follow)
    for c in driven:
        fc = c.driver_add("influence")
        drv = fc.driver
        drv.type, drv.expression = 'SCRIPTED', "1 - switch"   # (a simple expression: no Python needed to run it)
        var = drv.variables.new()
        var.name, var.type = "switch", 'SINGLE_PROP'
        var.targets[0].id = rig
        var.targets[0].data_path = 'pose.bones["%s"]["%s"]' % (bpy.utils.escape_identifier(target_name), IK_SWITCH)
    context.view_layer.update()


IKSetup = namedtuple("IKSetup", "end con target pole chain hand")


def ik_setups(rig):
    """[IKSetup] of the IK constraints of `rig` whose target bone has an IK_FK switch (IK with Pole makes them)."""
    out = []
    for pb in rig.pose.bones:
        for con in pb.constraints:
            if con.type != 'IK' or con.target != rig or not con.subtarget:
                continue
            target = rig.pose.bones.get(con.subtarget)
            if target is None or IK_SWITCH not in target:
                continue
            pole = rig.pose.bones.get(con.pole_subtarget) if con.pole_target == rig and con.pole_subtarget else None
            chain = [rig.pose.bones[b.name] for b in ik_chain(rig.data, pb.name, con.chain_count or len(rig.data.bones))]
            hand = next((p for p in rig.pose.bones for c in p.constraints if c.type == 'COPY_ROTATION'
                         and c.target == rig and c.subtarget == target.name), None)
            out.append(IKSetup(pb, con, target, pole, chain, hand))
    return out


def ik_setup_of(rig, names):
    """The IK setups that one of the bones `names` belongs to (a bone of the chain, the target or the pole); all of them
    when none of the bones is part of one."""
    setups = ik_setups(rig)
    picked = [s for s in setups if names & ({b.name for b in s.chain} | {s.target.name} | {s.pole.name if s.pole else "",
                                                                                         s.hand.name if s.hand else ""})]
    return picked or setups


def _with_switch(context, setup, value, read):
    """Evaluate the rig with the IK_FK switch of `setup` at `value`, call read(), and put the switch back."""
    before = setup.target[IK_SWITCH]
    setup.target[IK_SWITCH] = value
    setup.target.id_data.update_tag()
    context.view_layer.update()
    try:
        return read()
    finally:
        setup.target[IK_SWITCH] = before
        setup.target.id_data.update_tag()
        context.view_layer.update()


def match_fk_to_ik(context, setup):
    """Pose the chain's own (FK) channels where the IK puts the bones now. Returns the changed pose bones."""
    rig = setup.target.id_data
    bones = setup.chain + ([setup.hand] if setup.hand else [])
    mats = _with_switch(context, setup, 0.0, lambda: [pb.matrix.copy() for pb in bones])
    before = setup.target[IK_SWITCH]
    setup.target[IK_SWITCH] = 1.0   # (the channels are set with the IK off: each bone below its FK parent)
    try:
        for pb, mat in zip(bones, mats):
            rig.update_tag()
            context.view_layer.update()
            pb.matrix = mat
    finally:
        setup.target[IK_SWITCH] = before
        rig.update_tag()
        context.view_layer.update()
    return bones


def match_ik_to_fk(context, setup):
    """Put the IK target on the tip of the FK chain (turned like the hand, else like the end bone) and the pole out from
    its middle joint, on the side the chain bends to. Returns the changed pose bones."""
    def read():
        return ([pb.matrix.copy() for pb in setup.chain], setup.chain[-1].tail.copy(),
                (setup.hand or setup.chain[-1]).matrix.copy())
    mats, tip, turn = _with_switch(context, setup, 1.0, read)
    target = setup.target
    target.matrix = Matrix.Translation(tip) @ turn.to_quaternion().to_matrix().to_4x4()
    changed = [target]
    if setup.pole is not None and len(setup.chain) > 1:
        root, mid = mats[0].translation, mats[len(mats) // 2].translation
        line = tip - root
        away = mid - (root + line * ((mid - root).dot(line) / max(line.dot(line), 1e-12)))
        bones = [pb.bone for pb in setup.chain]
        rest_mid = bones[len(bones) // 2].head_local
        distance = (setup.pole.bone.head_local - rest_mid).length
        if away.length > 1e-4 * max(line.length, 1e-6):   # (a straight chain: the pole stays where it is)
            pole = setup.pole
            pole.matrix = Matrix.Translation(mid + away.normalized() * distance) @ pole.matrix.to_3x3().to_4x4()
            changed.append(pole)
    target.id_data.update_tag()
    context.view_layer.update()
    return changed


class M3D_OT_rig_ik_match(Operator):
    """Match an IK / FK limb for this frame (keyed when Auto Key is on): the limb of the selected bone (its chain, IK
target or pole), else every limb made with IK with Pole"""
    bl_idname = "m3d.rig_ik_match"
    bl_label = "Match IK / FK"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(('IK_TO_FK', "Match IK to FK", "Move the IK target and pole onto the FK pose"),
                                   ('FK_TO_IK', "Match FK to IK", "Rotate the FK bones onto the IK pose")))

    @classmethod
    def description(cls, _context, props):
        return {'IK_TO_FK': "Match IK to FK: move the IK target and pole so the IK limb lands on the FK pose (this frame)",
                'FK_TO_IK': "Match FK to IK: rotate the limb's own bones onto where the IK puts them (this frame)"}[
            props.direction]

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE'

    def execute(self, context):
        from m3d_anim import set_keys
        rig = context.active_object
        names = {pb.name for pb in selected_pose_bones(rig)}
        setups = ik_setup_of(rig, names)
        if not setups:
            self.report({'WARNING'}, "No IK / FK limb: make one with IK with Pole (Controls tab)")
            return {'CANCELLED'}
        changed = []
        for setup in setups:
            changed += (match_ik_to_fk if self.direction == 'IK_TO_FK' else match_fk_to_ik)(context, setup)
        if context.scene.tool_settings.use_keyframe_insert_auto:
            set_keys(changed, context.scene.tool_settings.keyframe_type)
        self.report({'INFO'}, "Matched %s for %s" % ("IK to FK" if self.direction == 'IK_TO_FK' else "FK to IK",
                                                    ", ".join(s.end.name for s in setups)))
        return {'FINISHED'}


def draw_ik_switches(layout, context, rig):
    """The IK_FK switch of each IK / FK limb with the Match buttons (nothing without one)."""
    setups = ik_setups(rig)
    if not setups:
        return False
    col = layout.column(align=True)
    for setup in setups:
        col.prop(setup.target, '["%s"]' % IK_SWITCH, text="%s IK / FK" % setup.end.name, slider=True)
    row = layout.row(align=True)
    for direction, label in (('IK_TO_FK', "Match IK to FK"), ('FK_TO_IK', "Match FK to IK")):
        row.operator("m3d.rig_ik_match", text=label).direction = direction
    return True


def fit_pole_angle(context, rig, con, end_name, pole_pos):
    """Search the pole angle of the IK constraint `con` of bone `end_name` so the chain's middle joint lands closest to
    `pole_pos` (armature space). A target bone of the skeleton is pulled toward the chain's root meanwhile, so the chain
    has to bend."""
    bones = ik_chain(rig.data, end_name, con.chain_count or len(rig.data.bones))
    root, tip = bones[0].head_local, bones[-1].tail_local
    total = sum(b.length for b in bones)
    mid_name = bones[len(bones) // 2].name
    target_pb = rig.pose.bones.get(con.subtarget) if con.target == rig and con.subtarget else None
    if target_pb is not None:
        rest = target_pb.location.copy()
        target_pb.location = rest + target_pb.bone.matrix_local.to_3x3().inverted() @ ((root - tip).normalized() * total * 0.25)
    best = None

    def tries(angles):
        nonlocal best
        for angle in angles:
            con.pole_angle = angle
            context.view_layer.update()
            evaluated = rig.evaluated_get(context.evaluated_depsgraph_get())
            dist = (evaluated.pose.bones[mid_name].head - pole_pos).length
            if best is None or dist < best[0] - 1e-9:
                best = (dist, angle)
    tries([math.radians(-180 + step * 15) for step in range(24)])
    for step in (5.0, 1.5, 0.5, 0.15):   # (then closer around the best, so Match IK to FK lands on the FK pose)
        here = best[1]
        tries([here - math.radians(step), here + math.radians(step)])
    con.pole_angle = best[1]
    if target_pb is not None:
        target_pb.location = rest
    context.view_layer.update()


class M3D_OT_rig_ik_pole(Operator):
    """IK with a pole: the active bone becomes the end of an IK chain (chain length in the Controls tab), with a target
bone at its tip and a pole target bone next to the middle joint. Move the target to pose the chain, the pole to turn
the bend"""
    bl_idname = "m3d.rig_ik_pole"
    bl_label = "IK with Pole"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE' and ob.data.bones.active is not None

    def execute(self, context):
        rig, s = context.active_object, context.scene.m3d_rig
        end = rig.data.bones.active.name
        target, pole = ik_with_pole(context, rig, end, s.ik_chain, s.ik_pole)
        for pb in rig.pose.bones:
            pb.select = pb.name in {target, pole}
        rig.data.bones.active = rig.data.bones[target]
        self.report({'INFO'}, "IK on %s: move %s%s" % (end, target, " and " + pole if pole else ""))
        return {'FINISHED'}


class M3D_OT_rig_pole_vector(Operator):
    """Pole Vector: the other selected bone (or a selected object) becomes the pole of the active bone's IK, so moving
it turns the bend. Select the pole, then the bone with the IK"""
    bl_idname = "m3d.rig_pole_vector"
    bl_label = "Pole Vector"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE' and ob.data.bones.active is not None

    def execute(self, context):
        rig = context.active_object
        pb = rig.pose.bones[rig.data.bones.active.name]
        con = next((c for c in pb.constraints if c.type == 'IK'), None)
        if con is None:
            self.report({'WARNING'}, "%s has no IK: add one first (IK Handle, or IK with Pole Target)" % pb.name)
            return {'CANCELLED'}
        pole = next((p for p in rig.pose.bones if p.select and p != pb and p.name != con.subtarget), None)
        other = next((o for o in context.selected_objects if o != rig), None)
        if pole is not None:
            con.pole_target, con.pole_subtarget = rig, pole.name
            pole_pos = pole.head.copy()
        elif other is not None:
            con.pole_target = other
            pole_pos = rig.matrix_world.inverted() @ other.matrix_world.translation
        else:
            self.report({'WARNING'}, "Select the pole (a bone or an object), then the bone with the IK")
            return {'CANCELLED'}
        fit_pole_angle(context, rig, con, pb.name, pole_pos)
        self.report({'INFO'}, "%s is the pole of the IK on %s" % (pole.name if pole else other.name, pb.name))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Constraints (the Constrain menu and the Controls tab): on the active bone in Pose Mode, else on the active object

# constraint type -> (property, value) that adds the target's moves to the owner's own transform (Keep Offset)
OFFSET_MIX = {'COPY_LOCATION': ("use_offset", True), 'COPY_SCALE': ("use_offset", True),
              'COPY_ROTATION': ("mix_mode", 'BEFORE'), 'COPY_TRANSFORMS': ("mix_mode", 'BEFORE_FULL')}
BONE_ONLY = {'IK', 'SPLINE_IK'}
CONSTRAINT_TYPES = [(i.identifier, i.name, "") for i in bpy.types.Constraint.bl_rna.properties["type"].enum_items]
CONSTRAINT_LABELS = {kind: name for kind, name, _d in CONSTRAINT_TYPES}


def world_matrix(owner):
    """World matrix of an object or a pose bone, constraints included (as evaluated)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if isinstance(owner, bpy.types.PoseBone):
        ev = owner.id_data.evaluated_get(depsgraph)
        return ev.matrix_world @ ev.pose.bones[owner.name].matrix
    return owner.evaluated_get(depsgraph).matrix_world.copy()


def keep_offset(context, owner, con, before):
    """Make the new constraint `con` keep its owner (object or pose bone) at `before`, its world matrix: Child Of sets its
    inverse; the Copy constraints add the target's moves to the owner's own transform (between two bones in their rest
    spaces, so a bone in the rest pose keeps its channels at rest). What is left of a jump (a target that is not at
    rest) moves the owner's own channels back."""
    if getattr(con, "target", None) is None:
        return
    if con.type == 'CHILD_OF':
        con.set_inverse_pending = True
    elif con.type in OFFSET_MIX:
        setattr(con, *OFFSET_MIX[con.type])
        if isinstance(owner, bpy.types.PoseBone) and con.target.type == 'ARMATURE' and con.subtarget:
            con.target_space, con.owner_space = 'LOCAL_OWNER_ORIENT', 'LOCAL'
    else:
        return
    context.view_layer.update()
    after = world_matrix(owner)
    if len(owner.constraints) == 1 and any(abs(a - b) > 1e-5 for ra, rb in zip(after, before) for a, b in zip(ra, rb)):
        # These constraints move their owner by a matrix of their own (after = A @ before): A's inverse undoes it.
        fixed = (after @ before.inverted()).inverted() @ before
        if isinstance(owner, bpy.types.PoseBone):
            owner.matrix = owner.id_data.matrix_world.inverted() @ fixed
        else:
            owner.matrix_world = fixed
        context.view_layer.update()


class M3D_OT_rig_constrain(Operator):
    """Constrain the active bone (Pose Mode) or the active object to the other selected bone or object. Keep Offset
(Controls tab, on) keeps it where it is"""
    bl_idname = "m3d.rig_constrain"
    bl_label = "Constrain"
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(items=CONSTRAINT_TYPES)

    @classmethod
    def description(cls, _context, props):
        return "%s: the active bone (Pose Mode) or object follows the other selected one (select the target first)" % \
            CONSTRAINT_LABELS[props.type]

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        ob = context.active_object
        posing = ob.type == 'ARMATURE' and ob.mode == 'POSE'
        if posing and ob.data.bones.active is None:
            self.report({'WARNING'}, "Select the bone to constrain last (it is the active one)")
            return {'CANCELLED'}
        if not posing and self.type in BONE_ONLY:
            self.report({'WARNING'}, "%s works on bones: in Pose Mode" % CONSTRAINT_LABELS[self.type])
            return {'CANCELLED'}
        owner = ob.pose.bones[ob.data.bones.active.name] if posing else ob
        before = world_matrix(owner)
        add = bpy.ops.pose.constraint_add_with_targets if posing else bpy.ops.object.constraint_add_with_targets
        try:
            add(type=self.type)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        con = owner.constraints[-1]
        if context.scene.m3d_rig.keep_offset:
            keep_offset(context, owner, con, before)
        target = getattr(con, "target", None)
        self.report({'INFO'}, "%s on %s%s" % (con.name, owner.name, " to " + (con.subtarget or target.name) if target else
                                              ": no other bone or object was selected, pick the target in the constraint"))
        return {'FINISHED'}


class M3D_OT_rig_constraints_clear(Operator):
    """Remove the constraints of the selected bones (Pose Mode) or of the selected objects"""
    bl_idname = "m3d.rig_constraints_clear"
    bl_label = "Remove Constraints"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        ob = context.active_object
        if ob.type == 'ARMATURE' and ob.mode == 'POSE':
            owners = selected_pose_bones(ob)
        else:
            owners = context.selected_objects or [ob]
        count = sum(len(o.constraints) for o in owners)
        for o in owners:
            for con in list(o.constraints):
                o.constraints.remove(con)
        context.view_layer.update()
        self.report({'INFO'}, "Removed %d constraint(s)" % count)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Naming check

SIDE_SUFFIX = re.compile(r"[._\- ](L|R|l|r|left|right|Left|Right)$")


def side_of_name(name):
    """'L' or 'R' for a name that ends in a side marker (.L .R _L _R -L -R, with or without lower case), else ''."""
    m = SIDE_SUFFIX.search(name)
    return "" if not m else ("L" if m.group(1).lower() in {"l", "left"} else "R")


def name_issues(rig):
    """[(bone name, message)] naming problems of a skeleton: a side name without its mirror partner, a name on the wrong
    side, a bone that mirrors another one by position but has no side name, and numbered duplicates (Bone.001, and
    Bone.001.L next to Bone.L)."""
    arm = rig.data
    editing = arm.is_editmode
    bones = {b.name: ((b.head.copy(), b.tail.copy()) if editing else (b.head_local.copy(), b.tail_local.copy()))
             for b in (arm.edit_bones if editing else arm.bones)}
    issues, eps = [], 1e-3
    for name, (head, tail) in bones.items():
        side = side_of_name(name)
        if side:
            partner = bpy.utils.flip_name(name)
            if partner not in bones:
                issues.append((name, "No mirror partner \"%s\"" % partner))
            mid_x = (head.x + tail.x) / 2
            if abs(mid_x) > eps and ((side == "L") != (mid_x > 0)):
                issues.append((name, "Named .%s but on the %s side" % (side, "-X" if side == "L" else "+X")))
        else:
            span = max((tail - head).length, eps)
            for other, (oh, ot) in bones.items():
                if other != name and side_of_name(other) and (Vector((-head.x, head.y, head.z)) - oh).length < span * 0.05 \
                        and (Vector((-tail.x, tail.y, tail.z)) - ot).length < span * 0.05 and abs(head.x) > eps:
                    issues.append((name, "Mirrors \"%s\" but has no side in its name" % other))
                    break
        sided = SIDE_SUFFIX.search(name)   # (the number sits before the side: Bone.001.L)
        stem, suffix = (name[:sided.start()], sided.group(0)) if sided else (name, "")
        base = re.match(r"^(.*)\.\d{3}$", stem)
        if base and base.group(1) + suffix in bones:
            issues.append((name, "Numbered duplicate of \"%s\"" % (base.group(1) + suffix)))
    return issues


class M3D_OT_rig_name_check(Operator):
    """Select the bones that have a naming problem (missing mirror partner, wrong side, numbered duplicates)"""
    bl_idname = "m3d.rig_name_check"
    bl_label = "Select Problem Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None

    def execute(self, context):
        rig = rig_of(context)
        bad = {name for name, _msg in name_issues(rig)}
        arm = rig.data
        if arm.is_editmode:
            for eb in arm.edit_bones:
                eb.select = eb.select_head = eb.select_tail = eb.name in bad
        else:
            for pb in rig.pose.bones:
                pb.select = pb.name in bad
        self.report({'INFO'}, "%d bone(s) with naming problems" % len(bad))
        return {'FINISHED'}


def side_by_position(bones, editing):
    """'.L' for bones (edit bones when `editing`) all on the +X side of the skeleton, '.R' for all on -X, '' for bones in
    the middle or on both sides."""
    xs = [v for b in bones for v in ((b.head.x, b.tail.x) if editing else (b.head_local.x, b.tail_local.x))]
    eps = 1e-4
    if xs and min(xs) >= -eps and max(xs) > eps:
        return ".L"
    if xs and max(xs) <= eps and min(xs) < -eps:
        return ".R"
    return ""


def chain_order(bones):
    """`bones` from the root of their chain to the tip (fewer parents first)."""
    def depth(b):
        n = 0
        while b.parent is not None:
            b, n = b.parent, n + 1
        return n
    return sorted(bones, key=depth)


class M3D_OT_rig_rename_chain(Operator):
    """Rename Chain: the selected bones get the names of the Names field from the root of the chain to its tip (a list
such as Shoulder, Elbow, Wrist, or a name with a number that counts up). A chain on one side gets .L or .R"""
    bl_idname = "m3d.rig_rename_chain"
    bl_label = "Rename Chain"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'ARMATURE' and ob.mode in {'EDIT', 'POSE'}

    def execute(self, context):
        rig = context.active_object
        editing = rig.data.is_editmode
        bones = [b for b in rig.data.edit_bones if b.select] if editing else [pb.bone for pb in selected_pose_bones(rig)]
        if not bones:
            self.report({'WARNING'}, "Select the bones of the chain")
            return {'CANCELLED'}
        bones = chain_order(bones)
        side = side_by_position(bones, editing)
        names = [chain_name(context.scene.m3d_rig.rename_chain, i) for i in range(len(bones))]
        names = [n if side_of_name(n) else n + side for n in names]
        for b in bones:   # (out of the way first: a new name may be one the chain has now)
            b.name = "_m3d_rename_" + b.name
        for b, name in zip(bones, names):
            b.name = name
        self.report({'INFO'}, "Renamed %d bones: %s" % (len(bones), ", ".join(b.name for b in bones)))
        return {'FINISHED'}


class M3D_OT_rig_mirror(Operator):
    """Mirror the selected bones (all when none) to the other side of X. Bones without a side in their name are named
.L (or .R) by where they are first, so the copies get the matching names"""
    bl_idname = "m3d.rig_mirror"
    bl_label = "Mirror Joints"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(('POSITIVE_X', "+X to -X", ""), ('NEGATIVE_X', "-X to +X", "")))

    @classmethod
    def description(cls, _context, props):
        return "Mirror the selected bones (all when none) from %s; bones without a side in their name get one first" % \
            ("+X to -X" if props.direction == 'POSITIVE_X' else "-X to +X")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_ARMATURE'

    def execute(self, context):
        arm = context.active_object.data
        side = ".L" if self.direction == 'POSITIVE_X' else ".R"
        named = 0
        for eb in selected_edit_bones(arm):
            if not side_of_name(eb.name) and side_by_position([eb], True) == side:
                eb.name += side
                named += 1
            eb.select = eb.select_head = eb.select_tail = True
        before = len(arm.edit_bones)
        bpy.ops.armature.symmetrize(direction=self.direction)
        made = len(arm.edit_bones) - before
        self.report({'INFO'}, "Named %d bones %s and mirrored them" % (named, side) if named else "Mirrored %d bones" % made)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Skin: bind, unbind, weights

def bind_targets(context):
    """(skeleton, meshes) for Bind: the selected skeleton (or the one the active mesh is bound to, or the only one) and
    the selected meshes (or the active one)."""
    selected = context.selected_objects
    rig = next((o for o in selected if o.type == 'ARMATURE'), None) or rig_of(context)
    meshes = [o for o in selected if o.type == 'MESH']
    if not meshes and skin_mesh(context) is not None:
        meshes = [skin_mesh(context)]
    return rig, meshes


def unbind(ob, rig):
    """Remove the skeleton's Armature modifiers, the parent link and the vertex groups named after its bones."""
    for mod in [m for m in ob.modifiers if m.type == 'ARMATURE' and m.object == rig]:
        ob.modifiers.remove(mod)
    names = {b.name for b in rig.data.bones}
    for group in [g for g in ob.vertex_groups if g.name in names]:
        ob.vertex_groups.remove(group)
    if ob.parent == rig:
        keep = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = keep


def unweighted(ob, rig):
    """Vertices of the mesh without any weight on a deforming bone of the skeleton."""
    names = {b.name for b in rig.data.bones if b.use_deform}
    indices = {g.index for g in ob.vertex_groups if g.name in names}
    return sum(1 for v in ob.data.vertices if not any(g.group in indices and g.weight > 0.0 for g in v.groups))


BIND_TYPES = {'AUTO': 'ARMATURE_AUTO', 'ENVELOPE': 'ARMATURE_ENVELOPE', 'EMPTY': 'ARMATURE_NAME'}


def _parent_set(context, rig, meshes, kind):
    leave_modes(context)
    for o in context.view_layer.objects:
        o.select_set(False, view_layer=context.view_layer)
    for mesh in meshes:
        mesh.select_set(True, view_layer=context.view_layer)
    rig.select_set(True, view_layer=context.view_layer)
    context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type=BIND_TYPES[kind], keep_transform=True)


def bind(context, rig, meshes, method, fallback=True):
    """Bind meshes to a skeleton. Automatic weights that leave vertices without weight (a mesh with holes or overlapping
    parts, a bone outside the mesh) are replaced by envelope weights when `fallback`. Returns the message."""
    _parent_set(context, rig, meshes, method)
    bad = [m for m in meshes if method == 'AUTO' and unweighted(m, rig) > 0]
    message = "%s bound to %s (%s weights)" % (", ".join(m.name for m in meshes), rig.name, method.lower())
    if bad and fallback:
        for mesh in bad:
            count = unweighted(mesh, rig)
            unbind(mesh, rig)
            _parent_set(context, rig, [mesh], 'ENVELOPE')
            message = ("Automatic weights left %d vertices of %s without weight: bound with envelope weights instead. "
                       "Close holes and merge overlapping parts, then bind again for better weights." % (count, mesh.name))
    elif bad:
        message += ": automatic weights left some vertices without weight"
    if method != 'EMPTY':   # (automatic and envelope weights come out a little under 1: they add up to 1, as painted ones do)
        for mesh in meshes:
            on_all_vertices(context, mesh, bpy.ops.object.vertex_group_normalize_all, group_select_mode='BONE_DEFORM',
                            lock_active=False)
        for ob in (rig, *meshes):
            ob.select_set(True)
    context.view_layer.objects.active = meshes[0]
    return message


def on_all_vertices(context, mesh, op, **props):
    """Run a vertex group operator on every vertex of `mesh` (made the only selected and active object): with Vertex or
    Face Select of Weight Paint on, Blender would only do the selected ones."""
    _select_only(context, mesh)
    me = mesh.data
    masks = me.use_paint_mask_vertex, me.use_paint_mask
    me.use_paint_mask_vertex = me.use_paint_mask = False
    try:
        op(**props)
    finally:
        me.use_paint_mask_vertex, me.use_paint_mask = masks


class M3D_OT_rig_bind(Operator):
    """Bind the selected meshes to the skeleton (select the meshes, then the skeleton or nothing when the scene has
only one). Automatic weights fall back to envelope weights when they fail"""
    bl_idname = "m3d.rig_bind"
    bl_label = "Bind Skin"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.m3d_rig
        rig, meshes = bind_targets(context)
        if rig is None or not meshes:
            self.report({'WARNING'}, "Select the mesh (and the skeleton) to bind")
            return {'CANCELLED'}
        try:
            message = bind(context, rig, meshes, s.skin_method, s.skin_fallback)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        problems = check_rig(context, rig)   # (the Test tab's Check Rig panel lists them, with their fixes)
        if problems:
            message += ". Check Rig (Test tab): " + "; ".join(p.text for p in problems[:2]) + (" ..." if len(problems) > 2 else "")
        self.report({'WARNING'} if "instead" in message or problems else {'INFO'}, message)
        return {'FINISHED'}


class M3D_OT_rig_unbind(Operator):
    """Remove the skeleton from the selected meshes: the Armature modifier, the parent and the bone weights"""
    bl_idname = "m3d.rig_unbind"
    bl_label = "Unbind Skin"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        leave_modes(context)
        count = 0
        for mesh in [o for o in context.selected_objects if o.type == 'MESH'] or [skin_mesh(context)]:
            rig = armature_of(mesh) if mesh is not None else None
            if rig is not None:
                unbind(mesh, rig)
                count += 1
        self.report({'INFO'} if count else {'WARNING'}, "Unbound %d mesh(es)" % count if count else "No bound mesh selected")
        return {'FINISHED' if count else 'CANCELLED'}


def solo_state(ob, index):
    """True when group `index` is the only unlocked group."""
    groups = ob.vertex_groups
    return not groups[index].lock_weight and all(g.lock_weight for g in groups if g.index != index) and len(groups) > 1


class M3D_OT_rig_solo(Operator):
    """Solo an influence: make it the active group and lock every other group, so painting only changes this one.
Again to unlock them all"""
    bl_idname = "m3d.rig_solo"
    bl_label = "Solo Influence"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH' and len(ob.vertex_groups) > 0

    def execute(self, context):
        groups = context.active_object.vertex_groups
        if not 0 <= self.index < len(groups):
            return {'CANCELLED'}
        solo = solo_state(context.active_object, self.index)
        for g in groups:
            g.lock_weight = False if solo else g.index != self.index
        groups.active_index = self.index
        return {'FINISHED'}


class M3D_OT_rig_transfer_weights(Operator):
    """Copy the vertex group weights of the Source mesh to the active mesh (nearest surface; missing groups are made)"""
    bl_idname = "m3d.rig_transfer_weights"
    bl_label = "Transfer Weights"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        s = context.scene.m3d_rig
        return ob is not None and ob.type == 'MESH' and s.transfer_source is not None and s.transfer_source != ob

    def execute(self, context):
        source, target = context.scene.m3d_rig.transfer_source, context.active_object
        if not source.vertex_groups:
            self.report({'WARNING'}, "%s has no vertex groups" % source.name)
            return {'CANCELLED'}
        leave_modes(context)
        _select_only(context, target)
        mod = target.modifiers.new("M3D Transfer", 'DATA_TRANSFER')
        mod.object, mod.use_vert_data, mod.data_types_verts = source, True, {'VGROUP_WEIGHTS'}
        mod.vert_mapping, mod.layers_vgroup_select_src, mod.layers_vgroup_select_dst = 'POLYINTERP_NEAREST', 'ALL', 'NAME'
        mod.mix_mode = 'REPLACE'
        try:   # The modifier makes the missing groups, then bakes the weights into the mesh.
            bpy.ops.object.datalayout_transfer(modifier=mod.name)
            bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError as err:
            target.modifiers.remove(mod)
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        self.report({'INFO'}, "Weights copied from %s to %s" % (source.name, target.name))
        return {'FINISHED'}


class M3D_OT_rig_mirror_weights(Operator):
    """Copy the weights of one side of the mesh to the other (+X to -X or -X to +X) for every group: the .L groups
fill the .R groups and the other way round. The side it copies from stays as it is. Needs a symmetric mesh"""
    bl_idname = "m3d.rig_mirror_weights"
    bl_label = "Mirror Weights"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(('POSITIVE_X', "+X to -X", ""), ('NEGATIVE_X', "-X to +X", "")))
    use_topology: BoolProperty(default=False, name="Topology", description="Match vertices by topology instead of position")

    @classmethod
    def description(cls, _context, props):
        return "Copy the weights from the %s side of the mesh to the other side, flipping .L / .R group names" % \
            ("+X" if props.direction == 'POSITIVE_X' else "-X")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH' and len(ob.vertex_groups) > 0 and ob.mode in {'OBJECT', 'WEIGHT_PAINT', 'EDIT'}

    def execute(self, context):
        ob = context.active_object
        mode, kwargs = ob.mode, dict(mirror_weights=True, flip_group_names=True, all_groups=True, use_topology=self.use_topology)
        if mode == 'OBJECT':   # Only Edit Mode and vertex-select Weight Paint honor a selection.
            bpy.ops.object.mode_set(mode='EDIT')
        try:
            if ob.mode == 'EDIT':
                self.mirror_in_edit_mode(context, ob.data, kwargs)
            else:
                self.mirror_in_weight_paint(ob.data, kwargs)
        finally:
            if mode == 'OBJECT' and ob.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}

    def receives(self, x):
        """True for a vertex on the side that gets the weights."""
        return x < -1e-5 if self.direction == 'POSITIVE_X' else x > 1e-5

    def mirror_in_edit_mode(self, context, mesh, kwargs):
        """The vertices that receive are the selection (picked in vertex mode, then put back)."""
        ts = context.tool_settings
        old_mode = tuple(ts.mesh_select_mode)
        ts.mesh_select_mode = (True, False, False)
        bm = bmesh.from_edit_mesh(mesh)
        old = [v.select for v in bm.verts]
        for v in bm.verts:
            v.select = self.receives(v.co.x)
        bm.select_flush_mode()
        bpy.ops.object.vertex_group_mirror(**kwargs)
        bm = bmesh.from_edit_mesh(mesh)
        for v, was in zip(bm.verts, old):
            v.select = was
        ts.mesh_select_mode = old_mode
        bm.select_flush_mode()
        bmesh.update_edit_mesh(mesh)

    def mirror_in_weight_paint(self, mesh, kwargs):
        import numpy as np
        old = np.zeros(len(mesh.vertices), dtype=bool)
        mesh.vertices.foreach_get("select", old)
        xs = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", xs)
        xs = xs[0::3]
        mesh.vertices.foreach_set("select", (xs < -1e-5) if self.direction == 'POSITIVE_X' else (xs > 1e-5))
        mesh.update()
        was_mask = mesh.use_paint_mask_vertex
        mesh.use_paint_mask_vertex = True
        try:
            bpy.ops.object.vertex_group_mirror(**kwargs)
        finally:
            mesh.use_paint_mask_vertex = was_mask
            mesh.vertices.foreach_set("select", old)
            mesh.update()


def active_vertex(ob):
    """(vertex index, [(group name, weight)]) of the active vertex: the active (or first selected) vertex in Edit Mode, the
    first selected vertex otherwise. None when no vertex is selected."""
    if ob.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(ob.data)
        vert = bm.select_history.active if isinstance(bm.select_history.active, bmesh.types.BMVert) else \
            next((v for v in bm.verts if v.select), None)
        if vert is None:
            return None
        layer = bm.verts.layers.deform.active
        names = {g.index: g.name for g in ob.vertex_groups}
        items = vert[layer].items() if layer is not None else []
        return vert.index, [(names[i], w) for i, w in items if i in names]
    import numpy as np
    mesh = ob.data
    selected = np.zeros(len(mesh.vertices), dtype=bool)
    mesh.vertices.foreach_get("select", selected)
    if not selected.any():
        return None
    vert = mesh.vertices[int(selected.argmax())]
    names = {g.index: g.name for g in ob.vertex_groups}
    return vert.index, [(names[g.group], g.weight) for g in vert.groups if g.group in names]


def deform_groups(ob):
    """Indices of the mesh's groups that are bone weights: the deforming bones of its skeleton (every group when it has
    none)."""
    rig = armature_of(ob)
    names = {b.name for b in rig.data.bones if b.use_deform} if rig is not None else None
    return {g.index for g in ob.vertex_groups if names is None or g.name in names}


def normalized(weights, index, value, locked, deform):
    """The weights {group index: weight} of a vertex with group `index` set to `value` and its other unlocked bone weights
    scaled so the bone weights add up to 1 (locked ones stay; the set weight is lowered when they leave less room; other
    weights at 0 share the rest evenly). With no other unlocked bone group on the vertex, the set weight takes the rest."""
    out = dict(weights)
    if index not in deform:
        out[index] = value
        return out
    fixed = sum(w for g, w in out.items() if g in deform and g in locked and g != index)
    free = [g for g in out if g in deform and g not in locked and g != index]
    value = min(value, max(0.0, 1.0 - fixed))
    rest, total = 1.0 - fixed - value, sum(out[g] for g in free)
    for g in free:
        out[g] = out[g] * rest / total if total > 1e-9 else rest / len(free)
    out[index] = value if free else max(0.0, 1.0 - fixed)
    return out


class M3D_OT_rig_vertex_weight(Operator):
    """Set the weight of one group on the selected vertices (the weight table), or take them out of the group. With
Normalize on, the vertex's other unlocked bone weights are scaled so they all add up to 1"""
    bl_idname = "m3d.rig_vertex_weight"
    bl_label = "Set Vertex Weight"
    bl_options = {'REGISTER', 'UNDO'}

    group: StringProperty()
    weight: FloatProperty(min=0.0, max=1.0)
    remove: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH' and ob.mode in {'EDIT', 'WEIGHT_PAINT', 'OBJECT'}

    def new_weights(self, context, ob, weights, index):
        """{group index: weight} of a vertex after the change (a removed group is left out)."""
        if not context.scene.m3d_rig.weight_normalize:
            out = dict(weights)
            out[index] = 0.0 if self.remove else self.weight
        else:
            locked = {g.index for g in ob.vertex_groups if g.lock_weight}
            out = normalized(weights, index, 0.0 if self.remove else self.weight, locked, deform_groups(ob))
        if self.remove:
            out.pop(index, None)
        return out

    def execute(self, context):
        ob = context.active_object
        group = ob.vertex_groups.get(self.group)
        if group is None:
            return {'CANCELLED'}
        if ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(ob.data)
            layer = bm.verts.layers.deform.verify()
            for v in bm.verts:
                if v.select:
                    new = self.new_weights(context, ob, dict(v[layer].items()), group.index)
                    v[layer].clear()
                    for g, w in new.items():
                        v[layer][g] = w
            bmesh.update_edit_mesh(ob.data)
            return {'FINISHED'}
        picked = [v for v in ob.data.vertices if v.select]
        if not picked:
            self.report({'WARNING'}, "Select vertices first")
            return {'CANCELLED'}
        groups = ob.vertex_groups
        for v in picked:
            old = {g.group: g.weight for g in v.groups}
            new = self.new_weights(context, ob, old, group.index)
            for g in set(old) - set(new):
                groups[g].remove([v.index])
            for g, w in new.items():
                groups[g].add([v.index], w, 'REPLACE')
        ob.data.update()
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Driven Key: a driver with a keyed mapping curve (driver value -> driven value)

Channel = namedtuple("Channel", "id path index label")


def _quote(name):
    return name.replace("\\", "\\\\").replace('"', '\\"')


def bone_channel(ob, bone, channel_id, prop=""):
    """The channel of an object (bone empty) or one of its pose bones, as a Channel (id, data path, index), or None when
    the object, bone or property is not there."""
    if ob is None:
        return None
    owner, base = ob, ""
    if bone:
        if ob.pose is None or bone not in ob.pose.bones:
            return None
        owner, base = ob.pose.bones[bone], 'pose.bones["%s"]' % _quote(bone)
    _id, label, attr, index = CHANNEL_BY_ID[channel_id]
    if attr is None:
        if not prop or prop not in owner.keys():
            return None
        path, index = (base + '["%s"]' % _quote(prop)), -1
    else:
        path = (base + "." if base else "") + attr
    return Channel(ob, path, index, "%s%s %s" % (ob.name, " / " + bone if bone else "", prop or label))


def shape_channel(ob, name):
    key = ob.data.shape_keys if ob is not None and ob.type == 'MESH' else None
    if key is None or name not in key.key_blocks:
        return None
    return Channel(key, 'key_blocks["%s"].value' % _quote(name), -1, "%s / %s" % (ob.name, name))


def driver_channel(s):
    return bone_channel(s.dk_driver_object, s.dk_driver_bone, s.dk_driver_channel, s.dk_driver_prop)


def driven_channel(s):
    if s.dk_kind == 'SHAPE_KEY':
        return shape_channel(s.dk_driven_object, s.dk_driven_shape)
    return bone_channel(s.dk_driven_object, s.dk_driven_bone, s.dk_driven_channel, s.dk_driven_prop)


def channel_value(ch):
    value = ch.id.path_resolve(ch.path)
    return float(value[ch.index] if ch.index >= 0 else value)


def full_path(ch):
    return ch.path + ("[%d]" % ch.index if ch.index >= 0 else "")


def driven_curve(ch, create=False):
    """The F-curve with the driver of a channel, or None (made when `create`)."""
    ad = ch.id.animation_data
    fc = ad.drivers.find(ch.path, index=max(ch.index, 0)) if ad else None
    if fc is None and create:
        fc = ch.id.driver_add(ch.path, ch.index) if ch.index >= 0 else ch.id.driver_add(ch.path)
        fc.keyframe_points.clear()   # Blender starts the mapping with the keys (0, 0) and (1, 1): ours only.
    return fc


def prepare_rotation(ch):
    """A rotation channel reads the Euler angles: a bone in Quaternion mode switches to XYZ Euler."""
    if ch.path.endswith("rotation_euler") and ch.path.startswith("pose.bones"):
        name = ch.path.split('"')[1].replace('\\"', '"')
        pb = ch.id.pose.bones[name]
        if pb.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}:
            pb.rotation_mode = 'XYZ'


def set_driven_key(driver, driven, x, y, interpolation='BEZIER'):
    """Key the mapping curve of `driven`: when `driver` has value x the driven channel gets value y. The first key makes the
    driver (the driver channel is its only variable); keys at other x values shape the curve between them."""
    for ch in (driver, driven):
        if ch.id.id_type == 'OBJECT':
            prepare_rotation(ch)
    fc = driven_curve(driven, create=True)
    drv = fc.driver
    drv.type = 'AVERAGE'
    var = drv.variables[0] if drv.variables else drv.variables.new()
    var.name, var.type = "driver", 'SINGLE_PROP'
    target = var.targets[0]
    target.id_type, target.id, target.data_path = 'OBJECT', driver.id, full_path(driver)
    fc.keyframe_points.insert(x, y, options={'FAST'})
    for kp in fc.keyframe_points:
        kp.interpolation = interpolation
    fc.extrapolation = 'CONSTANT'
    fc.update()
    return fc


def driven_keys(driven):
    """[(driver value, driven value)] of a channel's mapping curve."""
    fc = driven_curve(driven)
    return [(kp.co[0], kp.co[1]) for kp in fc.keyframe_points] if fc is not None else []


class M3D_OT_rig_driven_key(Operator):
    """Driven Key: key the driven channel to the Value for the driver channel's current value. Pose the driver, type
the value the driven channel should have there, and key; repeat for each pair"""
    bl_idname = "m3d.rig_driven_key"
    bl_label = "Driven Key"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('KEY', "Key", ""), ('REMOVE', "Remove Key", ""), ('CLEAR', "Clear", ""),
                                ('USE_DRIVER', "Use Active as Driver", ""), ('USE_DRIVEN', "Use Active as Driven", ""),
                                ('READ', "Read Driven Value", "")))
    index: IntProperty(description="Key to remove")

    @classmethod
    def description(cls, _context, props):
        return {'KEY': "Key the driven channel to the Driven Value at the driver's current value",
                'REMOVE': "Remove this key from the mapping curve",
                'CLEAR': "Remove the driver and its keys from the driven channel",
                'USE_DRIVER': "Use the active object and bone as the driver",
                'USE_DRIVEN': "Use the active object and bone (or shape key) as the driven channel",
                'READ': "Put the driven channel's current value in Driven Value"}[props.action]

    def execute(self, context):
        s = context.scene.m3d_rig
        ob = context.active_object
        if self.action in {'USE_DRIVER', 'USE_DRIVEN'}:
            if ob is None:
                return {'CANCELLED'}
            bone = ob.data.bones.active.name if ob.type == 'ARMATURE' and ob.data.bones.active else ""
            if self.action == 'USE_DRIVER':
                s.dk_driver_object, s.dk_driver_bone = ob, bone
            else:
                s.dk_driven_object, s.dk_driven_bone = ob, bone
                if ob.type == 'MESH' and ob.active_shape_key is not None:
                    s.dk_kind, s.dk_driven_shape = 'SHAPE_KEY', ob.active_shape_key.name
            return {'FINISHED'}
        driven = driven_channel(s)
        if driven is None:
            self.report({'WARNING'}, "Pick the driven channel first")
            return {'CANCELLED'}
        if self.action == 'READ':
            s.dk_value = channel_value(driven)
            return {'FINISHED'}
        if self.action == 'CLEAR':
            if driven_curve(driven) is not None:
                driven.id.driver_remove(driven.path, driven.index)
            return {'FINISHED'}
        if self.action == 'REMOVE':
            fc = driven_curve(driven)
            if fc is None or not 0 <= self.index < len(fc.keyframe_points):
                return {'CANCELLED'}
            fc.keyframe_points.remove(fc.keyframe_points[self.index])
            return {'FINISHED'}
        driver = driver_channel(s)
        if driver is None:
            self.report({'WARNING'}, "Pick the driver channel first")
            return {'CANCELLED'}
        if driver.id == driven.id and driver.path == driven.path:
            self.report({'WARNING'}, "A channel cannot drive itself")
            return {'CANCELLED'}
        set_driven_key(driver, driven, channel_value(driver), s.dk_value, s.dk_interp)
        return {'FINISHED'}


def drivers_of(ob):
    """[(owner label, owner ID, F-curve)] of all drivers on an object, its data (shape keys included)."""
    out = []
    for label, owner in (("Object", ob), ("Data", ob.data), ("Shape Keys", getattr(ob.data, "shape_keys", None))):
        if owner is not None and owner.animation_data is not None:
            out += [(label, owner, fc) for fc in owner.animation_data.drivers]
    return out


class M3D_OT_rig_driver_remove(Operator):
    """Remove a driver"""
    bl_idname = "m3d.rig_driver_remove"
    bl_label = "Remove Driver"
    bl_options = {'REGISTER', 'UNDO'}

    owner: StringProperty()
    path: StringProperty()
    index: IntProperty()

    def execute(self, context):
        ob = context.active_object
        if ob is None:
            return {'CANCELLED'}
        for _label, owner, fc in drivers_of(ob):
            if owner.name == self.owner and fc.data_path == self.path and fc.array_index == self.index:
                owner.driver_remove(self.path, self.index)
                return {'FINISHED'}
        return {'CANCELLED'}


def drivers_area(screen):
    """The screen's Drivers editor, or None."""
    return next((a for a in screen.areas if a.ui_type == 'DRIVERS'), None) if screen is not None else None


def drivers_open(screen):
    return drivers_area(screen) is not None


DRIVERS_SHARE = 0.4   # of the viewport's height the Drivers editor takes (under it, over the Time Slider)


def run_in(context, area, op, **props):
    """Run a screen operator in `area`'s main region."""
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with context.temp_override(area=area, region=region):
        op(**props)


class M3D_OT_rig_drivers_editor(Operator):
    """Open or close the Drivers editor, under the viewport (the Time Slider stays)"""
    bl_idname = "m3d.rig_drivers_editor"
    bl_label = "Drivers Editor"

    def execute(self, context):
        screen = context.screen
        area, timeline = drivers_area(screen), next((a for a in screen.areas if a.ui_type == 'TIMELINE'), None)
        views = [a for a in screen.areas if a.type == 'VIEW_3D']
        if area is not None and timeline is not None:
            run_in(context, area, bpy.ops.screen.area_close)
        elif area is not None or (timeline is not None and not views):
            # (a file where the bottom Timeline itself became the Drivers editor, or a screen without a viewport: switch it)
            area = area or timeline
            area.ui_type = 'TIMELINE' if area.ui_type == 'DRIVERS' else 'DRIVERS'
        elif views:
            view = max(views, key=lambda a: a.width * a.height)
            before = {a.as_pointer() for a in screen.areas}
            run_in(context, view, bpy.ops.screen.area_split, direction='HORIZONTAL', factor=DRIVERS_SHARE)
            # The new area is the lower part (a share under one half); the areas' places are only updated on the next redraw.
            lower = next(a for a in screen.areas if a.as_pointer() not in before)
            lower.ui_type = 'DRIVERS'
            lower.spaces.active.show_region_ui = True   # (the sidebar edits the driver)
        else:
            self.report({'WARNING'}, "This workspace has no viewport or Timeline for the Drivers editor")
            return {'CANCELLED'}
        for a in screen.areas:
            a.tag_redraw()
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Test poses

class M3D_OT_rig_reset_pose(Operator):
    """Put the bones back to the rest pose: location, rotation and scale cleared (locked channels too)"""
    bl_idname = "m3d.rig_reset_pose"
    bl_label = "Reset Pose"
    bl_options = {'REGISTER', 'UNDO'}

    selected_only: BoolProperty(default=False)

    @classmethod
    def description(cls, _context, props):
        return "Reset the selected bones to the rest pose" if props.selected_only else "Reset every bone to the rest pose"

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None

    def execute(self, context):
        rig = rig_of(context)
        reset_bones(selected_pose_bones(rig) if self.selected_only else list(rig.pose.bones))
        context.view_layer.update()
        return {'FINISHED'}


def reset_bones(bones, rotation_only=False):
    for pb in bones:
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        if not rotation_only:
            pb.location = (0.0, 0.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)


# --- Range-of-motion test: an NLA layer of its own that turns the bones each way around each axis

ROM = "ROM Test"
ROM_STEP = 10   # frames from one pose of the test to the next


def make_rom(rig, bones, angle, start):
    """Key the range-of-motion test of `bones` (pose bones) in an action of its own on the NLA layer "ROM Test" (made
    again when there is one): from the rest pose each bone turns +angle, -angle and back around its X, then Y, then Z axis,
    ROM_STEP frames a pose. The skeleton's own animation is left alone. Returns the last frame."""
    remove_rom(rig)
    action = bpy.data.actions.new(ROM)
    slot = action.slots.new(id_type='OBJECT', name=rig.name)
    bag = action_ensure_channelbag_for_slot(action, slot)
    poses = [None] + [(axis, sign) for axis in range(3) for sign in (1.0, -1.0, 0.0)]
    for pb in bones:
        mode = pb.rotation_mode
        path = 'pose.bones["%s"].%s' % (bpy.utils.escape_identifier(pb.name), rotation_attr(mode))
        size = 4 if mode in {'QUATERNION', 'AXIS_ANGLE'} else 3
        curves = [bag.fcurves.new(path, index=i) for i in range(size)]
        for k, pose in enumerate(poses):
            turn = Euler((0.0, 0.0, 0.0))
            if pose is not None:
                turn[pose[0]] = pose[1] * angle
            for fc, value in zip(curves, from_quaternion(mode, turn.to_quaternion())):
                fc.keyframe_points.insert(start + k * ROM_STEP, value, options={'FAST'})
        for fc in curves:
            fc.update()
    ad = rig.animation_data or rig.animation_data_create()
    track = ad.nla_tracks.new()
    track.name = ROM
    strip = track.strips.new(ROM, int(start), action)
    strip.action_slot = slot
    return start + (len(poses) - 1) * ROM_STEP


def remove_rom(rig):
    """Take the range-of-motion layer and its action away; the bones it turned go back to no rotation. True when there
    was one."""
    ad = rig.animation_data
    tracks = [t for t in ad.nla_tracks if t.name == ROM] if ad is not None else []
    actions = {s.action for t in tracks for s in t.strips if s.action is not None}
    names = {fc.data_path.split('"')[1] for a in actions for fc in action_fcurves(a) if fc.data_path.startswith("pose.bones[")}
    for t in tracks:
        ad.nla_tracks.remove(t)
    for a in actions:
        if a.users == 0:
            bpy.data.actions.remove(a)
    reset_bones([rig.pose.bones[n] for n in names if n in rig.pose.bones], rotation_only=True)
    return bool(tracks)


class M3D_OT_rig_rom(Operator):
    """Range-of-motion test: the selected bones (every deforming bone when none) turn each way around each axis on an
NLA layer of their own; play it to see how the skin deforms. Remove takes the layer away again"""
    bl_idname = "m3d.rig_rom"
    bl_label = "Range-of-Motion Test"
    bl_options = {'REGISTER', 'UNDO'}

    remove: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return "Remove the range-of-motion test layer" if props.remove else cls.__doc__

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None

    def execute(self, context):
        rig = rig_of(context)
        if self.remove:
            found = remove_rom(rig)
            context.view_layer.update()
            self.report({'INFO'}, "Range-of-motion test removed" if found else "No range-of-motion test to remove")
            return {'FINISHED'}
        bones = [pb for pb in rig.pose.bones if pb.select and not pb.hide] if rig.mode == 'POSE' else []
        bones = bones or [pb for pb in rig.pose.bones if pb.bone.use_deform]
        if not bones:
            self.report({'WARNING'}, "No deforming bones to test")
            return {'CANCELLED'}
        scene = context.scene
        end = make_rom(rig, bones, scene.m3d_rig.rom_angle, scene.frame_start)
        scene.frame_set(scene.frame_start + ROM_STEP)
        self.report({'INFO'}, "Range-of-motion test of %d bones on frames %d-%d: play it (Remove takes it away)" %
                    (len(bones), scene.frame_start, end))
        return {'FINISHED'}


class M3D_OT_rig_select_weighted(Operator):
    """Select the vertices of the active influence (the bone picked while painting) that have more weight than the
threshold (in Weight Paint Mode with Vertex Select, or in Edit Mode)"""
    bl_idname = "m3d.rig_select_weighted"
    bl_label = "Select Weighted Vertices"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = skin_mesh(context)
        return ob is not None and ob.vertex_groups.active is not None

    def execute(self, context):
        ob = skin_mesh(context)
        group, limit = ob.vertex_groups.active, context.scene.m3d_rig.select_threshold
        if ob.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(ob.data)
            layer = bm.verts.layers.deform.verify()
            for v in bm.verts:
                v.select = v[layer].get(group.index, 0.0) > limit
            bm.select_flush_mode()
            bmesh.update_edit_mesh(ob.data)
            count = sum(v.select for v in bm.verts)
        else:
            if ob.mode != 'WEIGHT_PAINT':
                enter_mode(context, 'WEIGHT_PAINT')
            mesh = ob.data
            picked = [any(g.group == group.index and g.weight > limit for g in v.groups) for v in mesh.vertices]
            mesh.vertices.foreach_set("select", picked)
            mesh.use_paint_mask_vertex = True
            mesh.update()
            count = sum(picked)
        self.report({'INFO'}, "%d vertices weighted to %s (more than %.2f)" % (count, group.name, limit))
        return {'FINISHED'}


# --- Check Rig: what goes wrong at bind or export, each with its fix

Problem = namedtuple("Problem", "kind text fix mesh", defaults=("",))   # fix: the button's label ("" for none)
_checked = {"rig": None, "problems": None}   # the last check: the skeleton's name and its problems


def is_identity(m):
    return all(abs(m[i][j] - (i == j)) < 1e-4 for i in range(len(m)) for j in range(len(m)))


def unapplied(ob):
    """True for an object with a rotation or a scale that is not applied."""
    return not is_identity(ob.matrix_basis.to_3x3())


def rig_meshes(context, rig):
    """The meshes bound to the skeleton, then the selected meshes (the ones about to be bound)."""
    bound = [o for o in context.view_layer.objects if o.type == 'MESH' and armature_of(o) is rig]
    return bound + [o for o in context.selected_objects if o.type == 'MESH' and o not in bound]


def weight_counts(ob, rig, limit):
    """(vertices without bone weight, with more than `limit` bone weights, whose bone weights do not add up to 1)."""
    names = {b.name for b in rig.data.bones if b.use_deform}
    deform = {g.index for g in ob.vertex_groups if g.name in names}
    empty = over = off = 0
    for v in ob.data.vertices:
        weights = [g.weight for g in v.groups if g.group in deform and g.weight > 0.0]
        if not weights:
            empty += 1
        else:
            over += len(weights) > limit
            off += abs(sum(weights) - 1.0) > 1e-3
    return empty, over, off


def _few(names, n=3):
    return ", ".join(names[:n]) + (" ..." if len(names) > n else "")


def rig_problems(context, rig):
    """[Problem] of the skeleton and its meshes, in the order to fix them."""
    s = context.scene.m3d_rig
    meshes = rig_meshes(context, rig)
    out = []
    loose = [o.name for o in (rig, *meshes) if unapplied(o)]
    if loose:
        out.append(Problem('TRANSFORMS', "Rotation or scale not applied: %s" % _few(loose), "Apply Rotation and Scale"))
    animated = rig.animation_data is not None and rig.animation_data.action is not None
    if not animated and any(not is_identity(pb.matrix_basis) for pb in rig.pose.bones):
        out.append(Problem('POSED', "The skeleton is not in its rest pose", "Reset Pose"))
    quats = [pb.name for pb in rig.pose.bones if pb.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}]
    if quats:
        out.append(Problem('QUATERNION', "%d bone(s) rotate in quaternions: %s" % (len(quats), _few(quats)), "Make Them XYZ Euler"))
    controls = [pb.name for pb in rig.pose.bones if pb.custom_shape is not None and pb.bone.use_deform]
    if controls:
        out.append(Problem('CONTROLS', "%d control(s) deform the mesh: %s" % (len(controls), _few(controls)), "Deform Off"))
    for mesh in (m for m in meshes if armature_of(m) is rig):
        empty, over, off = weight_counts(mesh, rig, s.skin_limit)
        if empty:
            out.append(Problem('UNWEIGHTED', "%s: %d vertices without bone weights" % (mesh.name, empty), "Select Them", mesh.name))
        if over:
            out.append(Problem('INFLUENCES', "%s: %d vertices with more than %d influences" % (mesh.name, over, s.skin_limit),
                               "Limit to %d" % s.skin_limit, mesh.name))
        if off:
            out.append(Problem('NORMALIZE', "%s: %d vertices whose weights do not add up to 1" % (mesh.name, off), "Normalize",
                               mesh.name))
    issues = name_issues(rig)
    if issues:
        out.append(Problem('NAMES', "%d naming problem(s): %s" % (len(issues), _few([n for n, _m in issues])), "Select Them"))
    return out


def check_rig(context, rig):
    """Run the check and keep its result for the Check Rig panel."""
    _checked["rig"], _checked["problems"] = rig.name, rig_problems(context, rig)
    return _checked["problems"]


class M3D_OT_rig_check(Operator):
    """Check Rig: look for what goes wrong at bind or export (rotation or scale not applied, a posed skeleton, quaternion
bones, controls that deform, vertices without weights or with too many, weights that do not add up to 1, names)"""
    bl_idname = "m3d.rig_check"
    bl_label = "Check Rig"
    bl_options = {'REGISTER', 'UNDO'}

    fix: EnumProperty(items=[(k, k.title(), "") for k in ('NONE', 'TRANSFORMS', 'POSED', 'QUATERNION', 'CONTROLS',
                                                           'UNWEIGHTED', 'INFLUENCES', 'NORMALIZE', 'NAMES')],
                      options={'SKIP_SAVE'})
    mesh: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return {'NONE': cls.__doc__,
                'TRANSFORMS': "Apply the rotation and scale of the skeleton and its meshes (they stay where they are)",
                'POSED': "Put every bone back to the rest pose",
                'QUATERNION': "Make the quaternion bones rotate in XYZ Euler (their pose and keys are kept)",
                'CONTROLS': "Bones with a control shape stop deforming the mesh",
                'UNWEIGHTED': "Select the vertices without bone weights (Edit Mode)",
                'INFLUENCES': "Keep the strongest influences of each vertex, up to Max Influences (Skin tab)",
                'NORMALIZE': "Scale each vertex's bone weights so they add up to 1",
                'NAMES': "Select the bones with a naming problem"}[props.fix]

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None

    def execute(self, context):
        rig = rig_of(context)
        if self.fix != 'NONE':
            try:
                self.repair(context, rig, bpy.data.objects.get(self.mesh))
            except RuntimeError as err:
                self.report({'WARNING'}, str(err).strip())
                return {'CANCELLED'}
        problems = check_rig(context, rig)
        self.report({'WARNING'} if problems else {'INFO'}, "Check Rig: %d problem(s)" % len(problems) if problems else
                    "Check Rig: no problems")
        return {'FINISHED'}

    def repair(self, context, rig, mesh):
        s = context.scene.m3d_rig
        if self.fix == 'TRANSFORMS':
            loose = [o for o in (rig, *rig_meshes(context, rig)) if unapplied(o)]
            leave_modes(context)
            _select_only(context, loose[0])
            for o in loose:
                o.select_set(True)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        elif self.fix == 'POSED':
            reset_bones(rig.pose.bones)
        elif self.fix == 'QUATERNION':
            for pb in rig.pose.bones:
                if pb.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}:
                    set_rotate_order(pb, 'XYZ')
        elif self.fix == 'CONTROLS':
            for pb in rig.pose.bones:
                if pb.custom_shape is not None:
                    pb.bone.use_deform = False
        elif self.fix == 'NAMES':
            bpy.ops.m3d.rig_name_check()
        elif mesh is not None:
            leave_modes(context)
            _select_only(context, mesh)
            if self.fix == 'INFLUENCES':
                on_all_vertices(context, mesh, bpy.ops.object.vertex_group_limit_total, group_select_mode='BONE_DEFORM',
                                limit=s.skin_limit)
            elif self.fix == 'NORMALIZE':
                on_all_vertices(context, mesh, bpy.ops.object.vertex_group_normalize_all, group_select_mode='BONE_DEFORM',
                                lock_active=False)
            else:   # UNWEIGHTED: Edit Mode with them selected
                names = {b.name for b in rig.data.bones if b.use_deform}
                deform = {g.index for g in mesh.vertex_groups if g.name in names}
                bpy.ops.object.mode_set(mode='EDIT')
                context.tool_settings.mesh_select_mode = (True, False, False)
                bm = bmesh.from_edit_mesh(mesh.data)
                layer = bm.verts.layers.deform.verify()
                for v in bm.verts:
                    v.select = not any(g in deform and w > 0.0 for g, w in v[layer].items())
                bm.select_flush_mode()
                bmesh.update_edit_mesh(mesh.data)
        context.view_layer.update()


def pose_assets():
    """Actions that are pose assets (made by Save Pose or marked as assets)."""
    return [a for a in bpy.data.actions if a.asset_data is not None and any(
        fc.data_path.startswith("pose.bones[") for fc in action_fcurves(a))]


def action_fcurves(action):
    return [fc for layer in action.layers for strip in layer.strips if hasattr(strip, "channelbags")
            for bag in strip.channelbags for fc in bag.fcurves]


def _flip_value(attr, index, value):
    """A bone channel value seen from the other side of the X axis."""
    if attr == "location":
        return -value if index == 0 else value
    if attr == "rotation_quaternion":
        return -value if index in {2, 3} else value
    if attr == "rotation_euler":
        return -value if index in {1, 2} else value
    return value


def apply_pose(rig, action, blend=1.0, flipped=False):
    """Apply a pose asset to the skeleton: each bone channel moves `blend` of the way to the stored value. `flipped` puts
    the pose on the opposite side (left bone values go to the right bone). Returns the channels set."""
    count = 0
    for fc in action_fcurves(action):
        if not fc.data_path.startswith("pose.bones[") or not fc.keyframe_points:
            continue
        bone_part, _dot, attr = fc.data_path.rpartition(".")
        name = bone_part.split('"')[1].replace('\\"', '"')
        value = fc.keyframe_points[0].co[1]
        if flipped:
            name, value = bpy.utils.flip_name(name), _flip_value(attr, fc.array_index, value)
        pb = rig.pose.bones.get(name)
        if pb is None or not hasattr(pb, attr):
            continue
        current = getattr(pb, attr)
        try:
            current[fc.array_index] = current[fc.array_index] + (value - current[fc.array_index]) * blend
        except (TypeError, IndexError):
            continue
        count += 1
    return count


class M3D_OT_rig_pose_apply(Operator):
    """Apply a pose from the pose library to the skeleton (Shift-click Flipped puts it on the other side)"""
    bl_idname = "m3d.rig_pose_apply"
    bl_label = "Apply Pose"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty()
    blend: FloatProperty(default=1.0, min=0.0, max=1.0)
    flipped: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return rig_of(context) is not None

    def execute(self, context):
        action = bpy.data.actions.get(self.name)
        if action is None:
            return {'CANCELLED'}
        apply_pose(rig_of(context), action, self.blend, self.flipped)
        context.view_layer.update()
        return {'FINISHED'}


class M3D_OT_rig_pose_save(Operator):
    """Save the pose of the selected bones as a pose asset in this file (it also shows in the viewport's asset shelf)"""
    bl_idname = "m3d.rig_pose_save"
    bl_label = "Save Pose"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'ARMATURE' and ob.mode == 'POSE'

    def execute(self, context):
        try:
            return bpy.ops.poselib.create_pose_asset(pose_name=context.scene.m3d_rig.pose_name or "Pose",
                                                     asset_library_reference='LOCAL')
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}


# -----------------------------------------------------------------------------
# Rigify (bundled, off until first use)

def rigify_enabled():
    import addon_utils
    return addon_utils.check("rigify")[1]


class M3D_OT_rig_rigify(Operator):
    """Rigify: enable the bundled auto-rig add-on (the first time), add a human meta-rig, or generate the rig from the
active meta-rig"""
    bl_idname = "m3d.rig_rigify"
    bl_label = "Rigify"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('ENABLE', "Enable Rigify", "Turn on the bundled Rigify add-on"),
                                ('META', "Human Meta-Rig", "Add a human meta-rig to the scene"),
                                ('GENERATE', "Generate Rig", "Build the control rig from the active meta-rig")))

    @classmethod
    def description(cls, _context, props):
        return {'ENABLE': "Turn on the bundled Rigify add-on (it is off until you ask for it)",
                'META': "Add a human meta-rig: scale it to your character, then Generate Rig",
                'GENERATE': "Build the control rig from the active meta-rig"}[props.action]

    def execute(self, context):
        s = context.scene.m3d_rig
        if self.action == 'ENABLE':
            return self.enable(s)
        if not rigify_enabled():
            if self.enable(s) == {'CANCELLED'}:
                return {'CANCELLED'}
        try:
            if self.action == 'META':
                bpy.ops.object.armature_human_metarig_add()
            else:
                bpy.ops.pose.rigify_generate()
        except (RuntimeError, AttributeError) as err:
            s.rigify_note = str(err).strip()[:200]
            self.report({'WARNING'}, "Rigify: " + s.rigify_note)
            return {'CANCELLED'}
        return {'FINISHED'}

    def enable(self, s):
        import addon_utils
        try:
            module = addon_utils.enable("rigify", default_set=True, persistent=True)
        except Exception as err:   # An add-on that fails to load must not take the interface with it.
            module, s.rigify_note = None, str(err).strip()[:200]
        if module is None and not rigify_enabled():
            s.rigify_note = s.rigify_note or "the add-on could not be loaded"
            self.report({'WARNING'}, "Rigify could not be enabled: " + s.rigify_note)
            return {'CANCELLED'}
        s.rigify_note = ""
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Quick Rig: numbered guides on a humanoid mesh (the middle and its left side; the right side mirrors), a skeleton fitted
# to them (a simple one of our own, or the Rigify human meta-rig and the rig it generates), bound with automatic weights
# and checked. The character stands on the ground facing -Y (the front view), its left side on +X.

# (guide, x from the middle and height, as fractions of the character's height; the arms: T-pose, see guide_spots)
QR_GUIDES = (("Chin", 0.0, 0.875), ("Neck", 0.0, 0.83), ("Hips", 0.0, 0.53), ("Shoulder", 0.10, 0.81),
             ("Elbow", 0.25, 0.81), ("Wrist", 0.40, 0.81), ("Hip", 0.09, 0.50), ("Knee", 0.09, 0.28),
             ("Ankle", 0.09, 0.05))
QR_SIDED = {"Shoulder", "Elbow", "Wrist", "Hip", "Knee", "Ankle"}
QR_COLLECTION = "Quick Rig Guides"


def guide_name(i, part):
    return "Guide %d %s%s" % (i + 1, part, ".L" if part in QR_SIDED else "")


def world_bounds(ob):
    """(min corner, max corner) of the object's bounding box in the world."""
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    return (Vector(min(p[i] for p in pts) for i in range(3)), Vector(max(p[i] for p in pts) for i in range(3)))


def guide_spots(ob):
    """{guide: world position} first guesses from the mesh's size: arms out (T-pose) when the mesh is wide, else down."""
    low, high = world_bounds(ob)
    height = max(high.z - low.z, 1e-6)
    mid = (low + high) / 2
    half = (high.x - low.x) / 2
    spots = {}
    for part, x, z in QR_GUIDES:
        if part in {"Elbow", "Wrist"} and half < 0.3 * height:   # (arms down, or an A-pose)
            x, z = {"Elbow": (0.15, 0.66), "Wrist": (0.19, 0.53)}[part]
        elif part == "Wrist":
            x = min(x, 0.9 * half / height)
        elif part == "Elbow":
            x = (0.10 + min(0.40, 0.9 * half / height)) / 2
        spots[part] = Vector((mid.x + x * height, mid.y, low.z + z * height))
    return spots


def center_in_mesh(ob, point):
    """`point` moved front to back (along Y) to halfway between where the mesh is hit from the front and from the back."""
    low, high = world_bounds(ob)
    inv = ob.matrix_world.inverted()
    hits = []
    for start, way in ((low.y - 1.0, 1.0), (high.y + 1.0, -1.0)):
        origin = inv @ Vector((point.x, start, point.z))
        direction = (inv.to_3x3() @ Vector((0.0, way, 0.0))).normalized()
        found, location, _normal, _index = ob.ray_cast(origin, direction)
        if not found:
            return point
        hits.append((ob.matrix_world @ location).y)
    return Vector((point.x, sum(hits) / 2, point.z))


def guides_collection(context):
    coll = bpy.data.collections.get(QR_COLLECTION) or bpy.data.collections.new(QR_COLLECTION)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


def guide_objects():
    """{guide part: its empty} of the guides in the scene."""
    found = {}
    for i, (part, _x, _z) in enumerate(QR_GUIDES):
        ob = bpy.data.objects.get(guide_name(i, part))
        if ob is not None:
            found[part] = ob
    return found


def place_guides(context, mesh, reset=False):
    """Numbered guide empties on `mesh` (made where they are missing, or all again with `reset`); returns them."""
    coll = guides_collection(context)
    low, high = world_bounds(mesh)
    size = (high.z - low.z) * 0.025
    found = guide_objects()
    spots = guide_spots(mesh)
    for i, (part, _x, _z) in enumerate(QR_GUIDES):
        ob = found.get(part)
        if ob is None:
            ob = bpy.data.objects.new(guide_name(i, part), None)
            coll.objects.link(ob)
            found[part] = ob
            reset_one = True
        else:
            reset_one = reset
        ob.empty_display_type, ob.empty_display_size = 'SPHERE', size
        ob.show_name = ob.show_in_front = True
        if reset_one:   # (elbows a little back, knees a little forward: an IK chain needs a bend to know its way)
            bend = {"Elbow": 0.012, "Knee": -0.012}.get(part, 0.0) * (high.z - low.z)
            ob.location = center_in_mesh(mesh, spots[part]) + Vector((0.0, bend, 0.0))
    layer = context.view_layer.layer_collection.children.get(coll.name)
    if layer is not None:
        layer.exclude = False
        layer.hide_viewport = False
    return found


def mirrored(point, middle_x):
    return Vector((2.0 * middle_x - point.x, point.y, point.z))


def joint_points(guides, mesh):
    """{point: armature position} of the skeleton's joints from the guides (left side and middle)."""
    low, high = world_bounds(mesh)
    height = high.z - low.z
    g = {part: ob.matrix_world.translation.copy() for part, ob in guides.items()}
    hips, neck, chin = g["Hips"], g["Neck"], g["Chin"]
    p = {"spine%d" % i: hips.lerp(neck, t) for i, t in enumerate((0.0, 0.2, 0.45, 0.7, 1.0))}
    p.update(g)
    p["neck_mid"] = neck.lerp(chin, 0.5)
    p["head_top"] = Vector((chin.x, chin.y, max(high.z, chin.z + 0.05 * height)))
    p["clavicle"] = Vector((neck.x + (g["Shoulder"].x - neck.x) * 0.2, g["Shoulder"].y, g["Shoulder"].z - 0.01 * height))
    forearm = g["Wrist"] - g["Elbow"]
    p["hand_tip"] = g["Wrist"] + forearm.normalized() * forearm.length * 0.45
    ankle = g["Ankle"]
    floor = low.z + 0.02 * height
    p["ball"] = Vector((ankle.x, ankle.y - 0.08 * height, floor))
    p["toe_tip"] = Vector((ankle.x, ankle.y - 0.13 * height, floor))
    p["heel_in"] = Vector((ankle.x - 0.025 * height, ankle.y + 0.03 * height, low.z))
    p["heel_out"] = Vector((ankle.x + 0.025 * height, ankle.y + 0.03 * height, low.z))
    p["pelvis_tip"] = Vector((g["Hip"].x, hips.y - 0.04 * height, hips.z + 0.1 * height))
    chest = hips.lerp(neck, 0.75)
    p["breast"] = chest + Vector((0.05 * height, -0.06 * height, 0.0))
    p["breast_tip"] = chest + Vector((0.05 * height, -0.1 * height, 0.0))
    return p


# Our skeleton: (bone, head point, tail point, parent, connected); the .L bones get .R copies.
QR_BONES = (
    ("Hips", "spine0", "spine1", None, False), ("Spine", "spine1", "spine2", "Hips", True),
    ("Chest", "spine2", "spine4", "Spine", True), ("Neck", "spine4", "Chin", "Chest", True),
    ("Head", "Chin", "head_top", "Neck", True),
    ("Shoulder.L", "clavicle", "Shoulder", "Chest", False), ("UpperArm.L", "Shoulder", "Elbow", "Shoulder.L", True),
    ("Forearm.L", "Elbow", "Wrist", "UpperArm.L", True), ("Hand.L", "Wrist", "hand_tip", "Forearm.L", True),
    ("Thigh.L", "Hip", "Knee", "Hips", False), ("Shin.L", "Knee", "Ankle", "Thigh.L", True),
    ("Foot.L", "Ankle", "ball", "Shin.L", True), ("Toe.L", "ball", "toe_tip", "Foot.L", True),
)
# The Rigify basic human meta-rig: bone -> (head point, tail point)
QR_RIGIFY = {
    "spine": ("spine0", "spine1"), "spine.001": ("spine1", "spine2"), "spine.002": ("spine2", "spine3"),
    "spine.003": ("spine3", "spine4"), "spine.004": ("spine4", "neck_mid"), "spine.005": ("neck_mid", "Chin"),
    "spine.006": ("Chin", "head_top"), "shoulder.L": ("clavicle", "Shoulder"), "upper_arm.L": ("Shoulder", "Elbow"),
    "forearm.L": ("Elbow", "Wrist"), "hand.L": ("Wrist", "hand_tip"), "thigh.L": ("Hip", "Knee"),
    "shin.L": ("Knee", "Ankle"), "foot.L": ("Ankle", "ball"), "toe.L": ("ball", "toe_tip"),
    "heel.02.L": ("heel_in", "heel_out"), "pelvis.L": ("spine0", "pelvis_tip"), "breast.L": ("breast", "breast_tip"),
}


def build_skeleton(context, points, middle_x):
    """Our simple skeleton fitted to the joint points; the right side mirrors the left. Returns the armature object."""
    arm = bpy.data.armatures.new("QuickRig")
    rig = bpy.data.objects.new("QuickRig", arm)
    context.collection.objects.link(rig)
    arm.display_type = 'STICK'
    rig.show_in_front = True
    _select_only(context, rig)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, head, tail, parent, connect in QR_BONES:
        for side in (".L", ".R") if name.endswith(".L") else ("",):
            eb = arm.edit_bones.new(name[:-2] + side if side else name)
            flip = side == ".R"
            eb.head = mirrored(points[head], middle_x) if flip else points[head]
            eb.tail = mirrored(points[tail], middle_x) if flip else points[tail]
            if parent:
                eb.parent = arm.edit_bones[parent[:-2] + side if parent.endswith(".L") and side else parent]
                eb.use_connect = connect
    for eb in arm.edit_bones:   # (Z forward for the spine, legs and arms; up for the feet)
        foot = eb.name.startswith(("Foot", "Toe"))
        eb.align_roll(Vector((0.0, 0.0, 1.0)) if foot else Vector((0.0, -1.0, 0.0)))
        if eb.name.endswith(".R"):
            mirror = arm.edit_bones[eb.name[:-2] + ".L"]
            eb.roll = -mirror.roll
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'XYZ'
    return rig


def fit_rigify(context, points, middle_x):
    """The Rigify basic human meta-rig moved onto the joint points (the .R bones mirror the .L ones). Returns it."""
    bpy.ops.object.armature_basic_human_metarig_add()
    meta = context.active_object
    meta.matrix_world = Matrix.Identity(4)
    bpy.ops.object.mode_set(mode='EDIT')
    bones = meta.data.edit_bones
    connected = {eb.name for eb in bones if eb.use_connect}   # (Rigify reads its chains from these: they are kept)
    for eb in bones:
        eb.use_connect = False   # (both ends are set; connected bones are joined again below)
    for name, (head, tail) in QR_RIGIFY.items():
        for side_name, flip in ((name, False), (name[:-2] + ".R", True)) if name.endswith(".L") else ((name, False),):
            eb = bones.get(side_name)
            if eb is None:
                continue
            eb.head = mirrored(points[head], middle_x) if flip else points[head]
            eb.tail = mirrored(points[tail], middle_x) if flip else points[tail]
    for eb in bones:
        eb.use_connect = eb.name in connected
    bpy.ops.object.mode_set(mode='OBJECT')
    return meta


class M3D_OT_rig_quick(Operator):
    """Quick Rig: place numbered guides on the selected mesh, then build a skeleton on them, bind the mesh and check
the rig"""
    bl_idname = "m3d.rig_quick"
    bl_label = "Quick Rig"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('GUIDES', "Place Guides", ""), ('RESET', "Reset Guides", ""), ('BUILD', "Build", ""),
                                ('REMOVE', "Remove Guides", "")))

    @classmethod
    def description(cls, _context, props):
        return {'GUIDES': "Put numbered guides on the selected mesh (chin, neck, hips, then shoulder, elbow, wrist, hip, "
                          "knee and ankle of the left side, +X): move them onto the joints",
                'RESET': "Put the guides back where Quick Rig first guessed them",
                'BUILD': "Build the skeleton on the guides (the right side mirrors), bind the mesh with automatic "
                         "weights and run Check Rig",
                'REMOVE': "Delete the guides"}[props.action]

    def execute(self, context):
        s = context.scene.m3d_rig
        if self.action == 'REMOVE':
            for ob in guide_objects().values():
                bpy.data.objects.remove(ob)
            coll = bpy.data.collections.get(QR_COLLECTION)
            if coll is not None and not coll.objects:
                bpy.data.collections.remove(coll)
            return {'FINISHED'}
        active = context.active_object
        mesh = active if active is not None and active.type == 'MESH' else s.qr_mesh
        if mesh is None or mesh.type != 'MESH':
            self.report({'WARNING'}, "Select the character's mesh first")
            return {'CANCELLED'}
        s.qr_mesh = mesh
        leave_modes(context)
        if self.action in {'GUIDES', 'RESET'}:
            guides = place_guides(context, mesh, reset=self.action == 'RESET')
            _select_only(context, guides["Chin"])
            self.report({'INFO'}, "Move the numbered guides onto the joints (left side; the right side mirrors), then Build")
            return {'FINISHED'}
        guides = guide_objects()
        if len(guides) < len(QR_GUIDES):
            guides = place_guides(context, mesh)
        points = joint_points(guides, mesh)
        middle_x = points["Hips"].x
        if s.qr_rigify:
            if not rigify_enabled() and M3D_OT_rig_rigify.enable(self, s) == {'CANCELLED'}:
                return {'CANCELLED'}
            try:
                meta = fit_rigify(context, points, middle_x)
                bpy.ops.pose.rigify_generate()
            except (RuntimeError, AttributeError) as err:
                s.rigify_note = str(err).strip()[:200]
                self.report({'WARNING'}, "Rigify: " + s.rigify_note)
                return {'CANCELLED'}
            rig = getattr(meta.data, "rigify_target_rig", None) or context.active_object
            if rig is None or rig is meta or rig.type != 'ARMATURE':
                self.report({'WARNING'}, "Rigify made no rig")
                return {'CANCELLED'}
            meta.hide_set(True)
        else:
            rig = build_skeleton(context, points, middle_x)
        layer = context.view_layer.layer_collection.children.get(QR_COLLECTION)
        if layer is not None:
            layer.hide_viewport = True   # (the guides stay for a second try: Place Guides shows them again)
        try:
            message = bind(context, rig, [mesh], 'AUTO', s.skin_fallback)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        problems = check_rig(context, rig)
        if problems:
            message += ". Check Rig (Test tab): " + "; ".join(p.text for p in problems[:2]) + (" ..." if len(problems) > 2 else "")
        self.report({'WARNING'} if "instead" in message or problems else {'INFO'}, message)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Naming pie and small helpers

class M3D_MT_rig_names(Menu):
    """Shift+N: naming and mirroring for bones"""
    bl_label = "Bone Names"

    def draw(self, context):
        pie = self.layout.menu_pie()
        edit = context.mode == 'EDIT_ARMATURE'
        auto = "armature.autoside_names" if edit else "pose.autoside_names"
        key = "type" if edit else "axis"
        for text, axis in (("Name Sides by X (.L / .R)", 'XAXIS'), ("Name Sides by Y", 'YAXIS'), ("Name Sides by Z", 'ZAXIS')):
            o = pie.operator(auto, text=text)
            setattr(o, key, axis)
        pie.operator("armature.flip_names" if edit else "pose.flip_names", text="Flip Names (.L <-> .R)")
        if edit:
            pie.operator("m3d.rig_mirror", text="Mirror Bones", icon='MOD_MIRROR').direction = 'POSITIVE_X'
            pie.operator("armature.select_mirror", text="Select Mirror")
        else:
            pie.operator("pose.select_mirror", text="Select Mirror")
        pie.operator("m3d.rig_name_check", text="Select Problem Names", icon='ERROR')


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

class _Page(_PagePanel):
    """Panel that needs `needs` (see `FIXES`): the page shows a message with fix buttons until they are met."""
    needs = ('RIG',)

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.needs)


def _gate(page, needs, unless=()):
    """The panel a page shows first when something is missing: what to do next. `unless`: needs the page's own panels
    already fix (the Skeleton page's Create panel makes a skeleton)."""
    def draw(self, context):
        draw_fixes(self.layout, context, needs)

    def page_poll(cls, context):
        first = missing(context, needs)[:1]
        return bool(first) and first[0] not in unless
    return type("PROPERTIES_PT_m3d_rg_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Rigging", "bl_options": {'HIDE_HEADER'}, "page": "rig_" + page,
        "page_poll": classmethod(page_poll), "draw": draw})


def _rig_data(context):
    """(skeleton object, its armature data) or (None, None)."""
    rig = rig_of(context)
    return rig, (rig.data if rig is not None else None)


def _small(layout, text):
    """A hint line (see reason)."""
    reason(layout, text)


def _buttons(layout, context, items, columns=2):
    grid(layout, context, items, columns=columns)


# --- Skeleton

class _Skeleton(_Page):
    page = "rig_skeleton"
    needs = ('RIG', 'EDIT')


class PROPERTIES_PT_m3d_rg_create(_Skeleton, Panel):
    bl_label = "Create"
    needs = ()

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        rig, arm = _rig_data(context)
        col = layout.column(align=True)
        col.scale_y = 1.4
        _button(col, context, "Joint Tool", "m3d.rig_joint", 'BONE_DATA', {})
        row = layout.row(align=True)
        if context.mode == 'EDIT_ARMATURE':
            _button(row, context, "Add Bone", "armature.bone_primitive_add", 'ADD', {})
        else:
            _button(row, context, "Add Skeleton", "object.armature_add", 'ARMATURE_DATA', {})
        layout.prop(s, "joint_name")
        layout.prop(s, "joint_place", expand=True)
        if s.joint_place == 'SURFACE':
            layout.prop(s, "joint_inset")
        layout.prop(s, "joint_snap")
        if arm is not None:
            layout.prop(arm, "use_mirror_x", text="X-Mirror")
            if arm.use_mirror_x:
                reason(layout, "The Joint Tool names a one-sided chain .L / .R and mirrors it")


class PROPERTIES_PT_m3d_rg_quickrig(_Page, Panel):
    page = "rig_skeleton"
    bl_label = "Quick Rig"
    needs = ()

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_rig
        guides = guide_objects()
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("m3d.rig_quick", text="1. Show Guides" if guides else "1. Place Guides",
                     icon='EMPTY_DATA').action = 'GUIDES'
        if guides:
            row = layout.row(align=True)
            row.operator("m3d.rig_quick", text="Reset Guides", icon='LOOP_BACK').action = 'RESET'
            row.operator("m3d.rig_quick", text="Remove", icon='X').action = 'REMOVE'
            _small(layout, "2. Move the numbered guides onto the joints: the middle and the left side (+X); the right "
                           "side mirrors")
        else:
            _small(layout, "Select the character's mesh (standing, facing the front view)")
        layout.prop(s, "qr_rigify")
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("m3d.rig_quick", text="3. Build and Bind", icon='ARMATURE_DATA').action = 'BUILD'
        _small(layout, "Builds the skeleton, binds the mesh with automatic weights and runs Check Rig (Test tab)")


class PROPERTIES_PT_m3d_rg_edit(_Skeleton, Panel):
    bl_label = "Edit Bones"

    def draw(self, context):
        _buttons(self.layout, context, (
            ("Extrude", "armature.extrude_move", 'EXPORT', {}),
            ("Extrude Forked", "armature.extrude_forked", 'FORCE_CURVE', {}),
            ("Click Extrude", "armature.click_extrude", 'RESTRICT_SELECT_OFF', {}),
            ("Subdivide", "armature.subdivide", 'MOD_SUBSURF', {"number_cuts": 2}),
            ("Duplicate", "armature.duplicate_move", 'DUPLICATE', {}),
            ("Delete", "armature.delete", 'X', {}),
            ("Fill Between Joints", "armature.fill", 'SNAP_MIDPOINT', {}),
            ("Switch Direction", "armature.switch_direction", 'ARROW_LEFTRIGHT', {}),
            ("Align Bones", "armature.align", 'ALIGN_JUSTIFY', {}),
        ))


class PROPERTIES_PT_m3d_rg_mirror(_Skeleton, Panel):
    bl_label = "Mirror"

    def draw(self, context):
        layout = self.layout
        rig, arm = _rig_data(context)
        layout.prop(arm, "use_mirror_x", text="X-Mirror")
        _buttons(layout, context, (
            ("Mirror +X to -X", "m3d.rig_mirror", 'MOD_MIRROR', {"direction": 'POSITIVE_X'}),
            ("Mirror -X to +X", "m3d.rig_mirror", 'MOD_MIRROR', {"direction": 'NEGATIVE_X'}),
            ("Select Mirror", "armature.select_mirror", 'RESTRICT_SELECT_OFF', {}),
            ("Add Mirror to Selection", "armature.select_mirror", 'SELECT_EXTEND', {"extend": True}),
        ))
        _small(layout, "Bones without .L / .R get the side they are on first")


# (label, calculate_roll type): roll presets
ROLL_PRESETS = (
    ("Global +X", 'GLOBAL_POS_X'), ("Global +Y", 'GLOBAL_POS_Y'), ("Global +Z", 'GLOBAL_POS_Z'),
    ("Global -X", 'GLOBAL_NEG_X'), ("Global -Y", 'GLOBAL_NEG_Y'), ("Global -Z", 'GLOBAL_NEG_Z'),
    ("Local +X", 'POS_X'), ("Local +Z", 'POS_Z'), ("Active Bone", 'ACTIVE'),
    ("Local -X", 'NEG_X'), ("Local -Z", 'NEG_Z'), ("3D Cursor", 'CURSOR'),
)


class PROPERTIES_PT_m3d_rg_orient(_Skeleton, Panel):
    bl_label = "Orient"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        layout.prop(s, "orient_axis", expand=True)
        layout.prop(s, "orient_dir", expand=True)
        _small(layout, "Y runs along the bone; the axis above turns to the direction")
        col = layout.column(align=True)
        col.scale_y = 1.3
        _button(col, context, "Orient Joint", "m3d.rig_orient", 'ORIENTATION_GIMBAL', {})
        layout.separator()
        layout.label(text="Roll to")
        _buttons(layout, context, [(label, "armature.calculate_roll", 'NONE', {"type": kind}) for label, kind in ROLL_PRESETS],
                 columns=3)
        _buttons(layout, context, (("Clear Roll", "armature.roll_clear", 'X', {}),
                                   ("Flip Axis (Global +Z)", "armature.calculate_roll", 'NONE',
                                    {"type": 'GLOBAL_POS_Z', "axis_flip": True})))


class PROPERTIES_PT_m3d_rg_names(_Skeleton, Panel):
    bl_label = "Names"

    def draw(self, context):
        layout = self.layout
        rig, arm = _rig_data(context)
        active = arm.edit_bones.active
        if active is not None:
            layout.prop(active, "name", text="Bone")
        layout.label(text="Add .L / .R by position")
        _buttons(layout, context, (
            ("By X", "armature.autoside_names", 'NONE', {"type": 'XAXIS'}),
            ("By Y", "armature.autoside_names", 'NONE', {"type": 'YAXIS'}),
            ("By Z", "armature.autoside_names", 'NONE', {"type": 'ZAXIS'}),
        ), columns=3)
        _button(layout, context, "Flip Names (.L <-> .R)", "armature.flip_names", 'ARROW_LEFTRIGHT', {})
        layout.separator()
        split_props(layout)
        layout.prop(context.scene.m3d_rig, "rename_chain")
        _buttons(layout, context, (("Rename Chain", "m3d.rig_rename_chain", 'SORTALPHA', {}),
                                   ("Prefix, Find / Replace...", "wm.batch_rename", 'SORTALPHA', {})))
        layout.use_property_split = False
        issues = name_issues(rig)
        col = layout.column(align=True)
        if not issues:
            col.label(text="Names are consistent", icon='CHECKMARK')
        else:
            col.label(text="%d naming problem(s)" % len(issues), icon='ERROR')
            for name, message in issues[:6]:
                col.label(text="%s: %s" % (name, message))
            if len(issues) > 6:
                col.label(text="... and %d more" % (len(issues) - 6))
            col.operator("m3d.rig_name_check", icon='RESTRICT_SELECT_OFF')


class PROPERTIES_PT_m3d_rg_hierarchy(_Skeleton, Panel):
    bl_label = "Hierarchy"

    def draw(self, context):
        layout = self.layout
        rig, arm = _rig_data(context)
        active = arm.edit_bones.active
        if active is not None:
            layout.prop_search(active, "parent", arm, "edit_bones", text="Parent")
            layout.prop(active, "use_connect")
        _buttons(layout, context, (
            ("Parent (Connected)", "armature.parent_set", 'CONSTRAINT_BONE', {"type": 'CONNECTED'}),
            ("Parent (Keep Offset)", "armature.parent_set", 'CONSTRAINT_BONE', {"type": 'OFFSET'}),
            ("Disconnect", "armature.parent_clear", 'UNLINKED', {"type": 'DISCONNECT'}),
            ("Clear Parent", "armature.parent_clear", 'X', {"type": 'CLEAR'}),
            ("Select Parent", "armature.select_hierarchy", 'TRIA_UP', {"direction": 'PARENT'}),
            ("Select Child", "armature.select_hierarchy", 'TRIA_DOWN', {"direction": 'CHILD'}),
        ))
        _small(layout, "Keys: P parent, Shift+P unparent, Shift+N names")


class PROPERTIES_PT_m3d_rg_rigify(_Page, Panel):
    page = "rig_skeleton"
    bl_label = "Generate Rig (Rigify)"
    bl_options = {'DEFAULT_CLOSED'}
    needs = ()

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_rig
        if not rigify_enabled():
            _small(layout, "Rigify builds a full control rig from a meta-rig; it is off until you turn it on")
            layout.operator("m3d.rig_rigify", text="Enable Rigify", icon='PLUGIN').action = 'ENABLE'
        else:
            layout.operator("m3d.rig_rigify", text="Human Meta-Rig", icon='ARMATURE_DATA').action = 'META'
            layout.operator("m3d.rig_rigify", text="Generate Rig", icon='ARMATURE_DATA').action = 'GENERATE'
            _small(layout, "Fit the meta-rig to the character in Edit Mode first")
        if s.rigify_note:
            draw_lines(layout, context, "Rigify: " + s.rigify_note, icon='ERROR')


# --- Controls & Constraints

class _Controls(_Page):
    page = "rig_controls"
    needs = ('RIG', 'POSE')


# (label, constraint type, icon)
CONSTRAINTS = (
    ("Copy Location", 'COPY_LOCATION', 'CON_LOCLIKE'), ("Copy Rotation", 'COPY_ROTATION', 'CON_ROTLIKE'),
    ("Copy Scale", 'COPY_SCALE', 'CON_SIZELIKE'), ("Copy Transforms", 'COPY_TRANSFORMS', 'CON_TRANSLIKE'),
    ("Child Of", 'CHILD_OF', 'CON_CHILDOF'), ("Damped Track", 'DAMPED_TRACK', 'CON_TRACKTO'),
    ("Stretch To", 'STRETCH_TO', 'CON_STRETCHTO'), ("Armature", 'ARMATURE', 'CON_ARMATURE'),
    ("Limit Location", 'LIMIT_LOCATION', 'CON_LOCLIMIT'), ("Limit Rotation", 'LIMIT_ROTATION', 'CON_ROTLIMIT'),
    ("Limit Scale", 'LIMIT_SCALE', 'CON_SIZELIMIT'), ("Limit Distance", 'LIMIT_DISTANCE', 'CON_DISTLIMIT'),
    ("Action", 'ACTION', 'ACTION'), ("Spline IK", 'SPLINE_IK', 'CON_SPLINEIK'), ("IK", 'IK', 'CON_KINEMATIC'),
)


class PROPERTIES_PT_m3d_rg_constraints(_Controls, Panel):
    bl_label = "Add Constraint"

    def draw(self, context):
        _small(self.layout, "Select the target bone, then the bone to constrain (active)")
        self.layout.prop(context.scene.m3d_rig, "keep_offset")
        _buttons(self.layout, context, [(label, "m3d.rig_constrain", icon, {"type": kind})
                                        for label, kind, icon in CONSTRAINTS])
        _button(self.layout, context, "Remove Constraints (Selected Bones)", "m3d.rig_constraints_clear", 'X', {})


class PROPERTIES_PT_m3d_rg_ik(_Controls, Panel):
    bl_label = "IK"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        rig = rig_of(context)
        layout.prop(s, "ik_chain")
        layout.prop(s, "ik_pole")
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("m3d.rig_ik_pole", icon='CON_KINEMATIC')
        _buttons(layout, context, (("IK to Bone", "pose.ik_add", 'CON_KINEMATIC', {"with_targets": False}),
                                   ("Pole Vector", "m3d.rig_pole_vector", 'EMPTY_SINGLE_ARROW', {}),
                                   ("Clear IK", "pose.ik_clear", 'X', {})))
        active = rig.data.bones.active
        if active is not None:
            pb = rig.pose.bones[active.name]
            row = layout.row(align=True)
            row.prop(pb, "lock_ik_x", text="Lock X", toggle=True)
            row.prop(pb, "lock_ik_y", text="Y", toggle=True)
            row.prop(pb, "lock_ik_z", text="Z", toggle=True)
            layout.prop(pb, "ik_stretch", slider=True)
        layout.use_property_split = False
        if draw_ik_switches(layout, context, rig):
            _small(layout, "IK_FK: 0 = the target moves the limb, 1 = rotate its bones (a key on it switches over time)")


def draw_constraint(layout, pb, con):
    """One constraint of the stack: on/off, name, order, remove, target and the settings that matter most."""
    box = layout.box()
    row = box.row(align=True)
    row.prop(con, "mute", text="", icon='HIDE_ON' if con.mute else 'HIDE_OFF', emboss=False)
    row.prop(con, "name", text="")
    for idname, icon in (("constraint.move_up", 'TRIA_UP'), ("constraint.move_down", 'TRIA_DOWN'), ("constraint.delete", 'X')):
        o = row.operator(idname, text="", icon=icon)
        o.constraint, o.owner = con.name, 'BONE'
    if hasattr(con, "target"):
        box.prop(con, "target", text="Target")
        if con.target is not None and con.target.type == 'ARMATURE':
            box.prop_search(con, "subtarget", con.target.data, "bones", text="Bone")
    if hasattr(con, "pole_target"):
        box.prop(con, "pole_target", text="Pole")
        if con.pole_target is not None and con.pole_target.type == 'ARMATURE':
            box.prop_search(con, "pole_subtarget", con.pole_target.data, "bones", text="Pole Bone")
    if con.type == 'IK':
        box.prop(con, "chain_count")
        box.prop(con, "pole_angle")
    elif con.type == 'ACTION':
        box.prop(con, "action")
    box.prop(con, "influence", slider=True)


class PROPERTIES_PT_m3d_rg_stack(_Controls, Panel):
    bl_label = "Constraints of the Active Bone"

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        active = rig.data.bones.active
        if active is None:
            _small(layout, "Select a bone")
            return
        pb = rig.pose.bones[active.name]
        layout.label(text=pb.name, icon='BONE_DATA')
        if not pb.constraints:
            _small(layout, "No constraints")
        for con in pb.constraints:
            draw_constraint(layout, pb, con)


class PROPERTIES_PT_m3d_rg_shapes(_Controls, Panel):
    bl_label = "Control Shape and Color"

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_rig
        rig = rig_of(context)
        col = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for shape, (label, icon, _build) in SHAPES.items():
            col.operator("m3d.rig_control", text=label, icon=icon).shape = shape
        col.operator("m3d.rig_control", text="No Shape", icon='X').shape = 'NONE'
        split_props(layout)
        layout.prop(s, "control_scale")
        layout.prop(s, "control_color")
        row = layout.row(align=True)
        for preset, label, _desc in COLOR_PRESETS:
            row.operator("m3d.rig_control_color", text=label if preset != 'PICKED' else "Apply").preset = preset
        layout.operator("m3d.rig_control_color", text="Default Colors").preset = 'DEFAULT'
        active = rig.data.bones.active
        if active is not None:
            pb = rig.pose.bones[active.name]
            layout.separator()
            layout.prop(pb, "custom_shape", text="Shape")
            layout.prop(pb, "custom_shape_scale_xyz", text="Scale")
            layout.prop(pb, "custom_shape_translation", text="Offset")
            layout.prop(pb, "custom_shape_rotation_euler", text="Rotation")
            layout.prop(pb, "use_custom_shape_bone_size")
            layout.prop(pb.bone, "show_wire")


class PROPERTIES_PT_m3d_rg_locks(_Controls, Panel):
    bl_label = "Locks"

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        active = rig.data.bones.active
        if active is not None:
            pb = rig.pose.bones[active.name]
            for label, attr in (("Translate", "lock_location"), ("Rotate", "lock_rotation"), ("Scale", "lock_scale")):
                row = layout.row(align=True)
                row.label(text=label)
                for i in range(3):
                    row.prop(pb, attr, index=i, text="XYZ"[i], toggle=True, icon='LOCKED' if getattr(pb, attr)[i] else 'UNLOCKED')
        row = layout.row(align=True)
        for channels, label in (('LOCATION', "Translate"), ('ROTATION', "Rotate"), ('SCALE', "Scale")):
            o = row.operator("m3d.rig_lock", text="Lock " + label, icon='LOCKED')
            o.channels, o.lock = channels, True
        row = layout.row(align=True)
        o = row.operator("m3d.rig_lock", text="Lock All", icon='LOCKED')
        o.channels, o.lock = 'ALL', True
        o = row.operator("m3d.rig_lock", text="Unlock All", icon='UNLOCKED')
        o.channels, o.lock = 'ALL', False
        layout.separator()
        row = layout.row(align=True)
        row.label(text="Rotate Order")
        mode = rig.pose.bones[active.name].rotation_mode if active is not None else 'XYZ'
        row.operator_menu_enum("m3d.rig_rotate_order", "order", text=ROTATE_LABELS[mode])
        _small(layout, "Sets the selected bones; their pose and keys are kept")
        layout.prop(context.scene.m3d_rig, "euler_bones")


# --- Skin

class _Skin(_Page):
    page = "rig_skin"
    needs = ('RIG', 'MESH')


class PROPERTIES_PT_m3d_rg_bind(_Skin, Panel):
    bl_label = "Bind"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        mesh = skin_mesh(context)
        rig = armature_of(mesh)
        layout.label(text="%s: %s" % (mesh.name, ("bound to " + rig.name) if is_bound(mesh) else "not bound"),
                     icon='LINKED' if is_bound(mesh) else 'UNLINKED')
        row = layout.row()
        row.use_property_split = False   # (no label: the three methods fit a narrow dock)
        row.prop(s, "skin_method", expand=True)
        if s.skin_method == 'AUTO':
            layout.prop(s, "skin_fallback")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("m3d.rig_bind", icon='ARMATURE_DATA')
        if is_bound(mesh):
            row.operator("m3d.rig_unbind", icon='UNLINKED')
        _small(layout, "Select the mesh, then the skeleton")


class PROPERTIES_PT_m3d_rg_paint(_Skin, Panel):
    bl_label = "Weight Paint"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        mesh = skin_mesh(context)
        painting = context.mode == 'PAINT_WEIGHT'
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("m3d.rig_mode", text="Paint Weights" if not painting else "Back to Object Mode",
                     icon='WPAINT_HLT' if not painting else 'OBJECT_DATAMODE', depress=painting).mode = \
            'OBJECT' if painting else 'WEIGHT_PAINT'
        if painting:
            ts = context.tool_settings
            paint = ts.weight_paint
            brush = paint.brush if paint else None
            ups = paint.unified_paint_settings if paint else None
            if brush is not None:
                for prop, flag in (("weight", "use_unified_weight"), ("size", "use_unified_size"),
                                   ("strength", "use_unified_strength")):
                    row = layout.row(align=True)
                    row.prop(ups if getattr(ups, flag) else brush, prop, slider=True)
                    row.prop(ups, flag, text="", icon='BRUSHES_ALL')
            layout.use_property_split = False
            row = layout.row(align=True)   # (Auto Normalize: on when Paint Weights starts on a bound mesh)
            row.prop(ts, "use_auto_normalize", text="Auto Normalize", toggle=True)
            row.prop(ts, "use_multipaint", text="Multi-Paint", toggle=True)
            row.prop(ts, "use_lock_relative", text="Lock-Relative", toggle=True)
            row = layout.row(align=True)
            row.prop(mesh.data, "use_paint_mask_vertex", text="Vertex Select", toggle=True)
            row.prop(mesh.data, "use_paint_mask", text="Face Select", toggle=True)
            layout.prop(mesh.data, "use_paint_bone_selection", text="Paint Only the Selected Bones")
            row = layout.row(align=True)
            row.prop(mesh.data, "use_mirror_x", text="Mirror X", toggle=True)
            row.prop(mesh.data, "use_mirror_vertex_groups", text="Mirror Groups", toggle=True)
            row.prop(mesh.data, "use_mirror_topology", text="Topology", toggle=True)
            if mesh.data.use_paint_bone_selection:
                _small(layout, "Ctrl+click a bone in the view to pick it")
        else:
            _small(layout, "The skeleton stays in Pose Mode while you paint")


class M3D_UL_rig_influences(UIList):
    """Vertex groups of the mesh: name, lock, solo."""

    def draw_item(self, _context, layout, data, item, _icon, _active_data, _active_propname, index):
        rig = armature_of(data)
        row = layout.row(align=True)
        row.label(text=item.name, icon='GROUP_BONE' if rig is not None and item.name in rig.data.bones else 'GROUP_VERTEX')
        row.prop(item, "lock_weight", text="", emboss=False, icon='LOCKED' if item.lock_weight else 'UNLOCKED')
        row.operator("m3d.rig_solo", text="", emboss=False, icon='SOLO_ON' if solo_state(data, index) else 'SOLO_OFF').index = index


class PROPERTIES_PT_m3d_rg_influences(_Skin, Panel):
    bl_label = "Influences"

    def draw(self, context):
        layout = self.layout
        mesh = skin_mesh(context)
        if not mesh.vertex_groups:
            _small(layout, "No vertex groups: bind the mesh first")
            return
        layout.template_list("M3D_UL_rig_influences", "", mesh, "vertex_groups", mesh.vertex_groups, "active_index",
                             rows=min(len(mesh.vertex_groups), 6), show_handles=False)
        row = layout.row(align=True)
        row.operator("object.vertex_group_lock", text="Lock All", icon='LOCKED').action = 'LOCK'
        row.operator("object.vertex_group_lock", text="Unlock All", icon='UNLOCKED').action = 'UNLOCK'
        row = layout.row(align=True)
        row.operator("m3d.rig_select_weighted", text="Select Weighted Vertices", icon='RESTRICT_SELECT_OFF')
        sub = row.row(align=True)
        sub.scale_x = 0.7
        sub.prop(context.scene.m3d_rig, "select_threshold")


class PROPERTIES_PT_m3d_rg_weights(_Skin, Panel):
    bl_label = "Weights"

    @classmethod
    def page_poll(cls, context):   # (without vertex groups Influences says to bind first)
        return ready(context, cls.needs) and bool(skin_mesh(context).vertex_groups)

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        mesh = skin_mesh(context)
        painting = context.mode == 'PAINT_WEIGHT'
        if painting:
            col = layout.column(align=True)
            _button(col, context, "Flood Weight (brush value)", "paint.weight_set", 'BRUSH_DATA', {})
            _buttons(col, context, (("Weights from Bones", "paint.weight_from_bones", 'BONE_DATA', {"type": 'AUTOMATIC'}),
                                    ("From Envelopes", "paint.weight_from_bones", 'BONE_DATA', {"type": 'ENVELOPES'})))
        else:
            _small(layout, "Flood and Weights from Bones: in Weight Paint Mode (Paint Weights)")
        layout.separator()
        row = layout.row(align=True)
        row.prop(s, "skin_smooth")
        row.prop(s, "skin_repeat")
        _button(layout, context, "Smooth Active Group", "object.vertex_group_smooth", 'MOD_SMOOTH',
                {"group_select_mode": 'ACTIVE', "factor": s.skin_smooth, "repeat": s.skin_repeat})
        _small(layout, "Smooth works on selected vertices (Edit Mode or Vertex Select)")
        layout.separator()
        _button(layout, context, "Normalize All", "object.vertex_group_normalize_all", 'MOD_VERTEX_WEIGHT',
                {"group_select_mode": 'BONE_DEFORM', "lock_active": False})
        row = layout.row(align=True)
        row.prop(s, "skin_limit")
        _button(layout, context, "Limit Total", "object.vertex_group_limit_total", 'MOD_DECIM',
                {"group_select_mode": 'BONE_DEFORM', "limit": s.skin_limit})
        row = layout.row(align=True)
        row.prop(s, "skin_clean")
        _button(layout, context, "Clean", "object.vertex_group_clean", 'BRUSH_DATA',
                {"group_select_mode": 'BONE_DEFORM', "limit": s.skin_clean})
        layout.separator()
        _buttons(layout, context, (("Mirror +X to -X", "m3d.rig_mirror_weights", 'MOD_MIRROR', {"direction": 'POSITIVE_X'}),
                                   ("Mirror -X to +X", "m3d.rig_mirror_weights", 'MOD_MIRROR', {"direction": 'NEGATIVE_X'})))
        _small(layout, "Mirror needs a symmetric mesh and .L / .R group names")


class PROPERTIES_PT_m3d_rg_transfer(_Skin, Panel):
    bl_label = "Transfer Weights"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        layout.prop(s, "transfer_source")
        layout.operator("m3d.rig_transfer_weights", icon='MOD_DATA_TRANSFER')
        _small(layout, "Copies to the active mesh by nearest surface")


class PROPERTIES_PT_m3d_rg_table(_Skin, Panel):
    bl_label = "Weight Table"

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.needs) and skin_mesh(context) is context.active_object

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_rig
        mesh = context.active_object
        found = active_vertex(mesh)
        if found is None:
            _small(layout, "Select a vertex (Edit Mode, or Weight Paint with Vertex Select)")
            return
        index, weights = found
        row = layout.row()
        row.label(text="Vertex %d" % index, icon='VERTEXSEL')
        row.prop(s, "weight_normalize")
        layout.prop(s, "weight_value")
        col = layout.column(align=True)
        for name, weight in sorted(weights, key=lambda item: -item[1]):
            row = col.row(align=True)
            row.label(text=name)
            sub = row.row(align=True)
            sub.scale_x = 0.8
            sub.label(text="%.3f" % weight)
            o = row.operator("m3d.rig_vertex_weight", text="Set")
            o.group, o.weight, o.remove = name, s.weight_value, False
            o = row.operator("m3d.rig_vertex_weight", text="", icon='X')
            o.group, o.remove = name, True
        if not weights:
            col.label(text="No weights on this vertex")


# --- Drive

class _Drive(_Page):
    page = "rig_drive"
    needs = ()


class PROPERTIES_PT_m3d_rg_shapekeys(_Drive, Panel):
    bl_label = "Shape Keys"

    def draw(self, context):
        layout = self.layout
        mesh = skin_mesh(context)
        if mesh is None:
            meshes = [o for o in context.view_layer.objects if o.type == 'MESH' and o.visible_get()]
            if meshes:
                draw_object_picks(empty_state(layout, context, "Select a mesh for shape keys"), meshes)
            else:
                reason(layout, "Shape keys need a mesh")
            return
        key = mesh.data.shape_keys
        if key is None:
            empty_state(layout, context, "%s has no shape keys yet" % mesh.name,
                        ("Add Basis Shape", "object.shape_key_add", 'SHAPEKEY_DATA', {"from_mix": False}))
            return
        row = layout.row()
        row.template_list("MESH_UL_shape_keys", "", key, "key_blocks", mesh, "active_shape_key_index",
                          rows=min(len(key.key_blocks), 6), show_handles=False)
        col = row.column(align=True)
        o = col.operator("object.shape_key_add", icon='ADD', text="")
        o.from_mix = False
        col.operator("object.shape_key_remove", icon='REMOVE', text="").all = False
        block = mesh.active_shape_key
        if block is not None and mesh.active_shape_key_index > 0:
            layout.prop(block, "value", slider=True)
            row = layout.row(align=True)
            row.prop(block, "slider_min", text="Min")
            row.prop(block, "slider_max", text="Max")
        row = layout.row(align=True)
        row.operator("object.shape_key_add", text="From Mix", icon='SHAPEKEY_DATA').from_mix = True
        row.operator("object.shape_key_clear", text="Reset Values", icon='X')
        row = layout.row(align=True)
        row.operator("object.shape_key_mirror", text="Mirror Shape", icon='MOD_MIRROR').use_topology = False
        row.operator("object.shape_key_mirror", text="Topology Mirror").use_topology = True
        _small(layout, "Mirror needs a symmetric mesh and .L / .R key names")


def _channel_rows(layout, ob_prop, bone_prop, channel_prop, prop_prop, s, which):
    """Object, bone, channel (and custom property name) rows of a Driven Key side."""
    ob = getattr(s, ob_prop)
    layout.prop(s, ob_prop, text="Object")
    if ob is not None and ob.type == 'ARMATURE':
        layout.prop_search(s, bone_prop, ob.data, "bones", text="Bone")
    if channel_prop:
        layout.prop(s, channel_prop, text="Channel")
        if getattr(s, channel_prop) == 'PROP':
            layout.prop(s, prop_prop, text="Property")


class PROPERTIES_PT_m3d_rg_driven_key(_Drive, Panel):
    bl_label = "Driven Key"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        box = layout.box()
        row = box.row()
        row.label(text="Driver", icon='DRIVER')
        row.operator("m3d.rig_driven_key", text="Use Active").action = 'USE_DRIVER'
        _channel_rows(box, "dk_driver_object", "dk_driver_bone", "dk_driver_channel", "dk_driver_prop", s, 'DRIVER')
        driver = driver_channel(s)
        if driver is not None:
            box.label(text="Now: %.4g" % channel_value(driver))
        box = layout.box()
        row = box.row()
        row.label(text="Driven", icon='CON_TRANSLIKE')
        row.operator("m3d.rig_driven_key", text="Use Active").action = 'USE_DRIVEN'
        box.row().prop(s, "dk_kind", expand=True)
        if s.dk_kind == 'SHAPE_KEY':
            box.prop(s, "dk_driven_object", text="Mesh")
            ob = s.dk_driven_object
            if ob is not None and ob.type == 'MESH' and ob.data.shape_keys:
                box.prop_search(s, "dk_driven_shape", ob.data.shape_keys, "key_blocks", text="Shape Key")
        else:
            _channel_rows(box, "dk_driven_object", "dk_driven_bone", "dk_driven_channel", "dk_driven_prop", s, 'DRIVEN')
        driven = driven_channel(s)
        row = layout.row(align=True)
        row.prop(s, "dk_value")
        row.operator("m3d.rig_driven_key", text="", icon='EYEDROPPER').action = 'READ'
        layout.prop(s, "dk_interp")
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("m3d.rig_driven_key", text="Key", icon='KEYFRAME_HLT').action = 'KEY'
        if driven is not None:
            keys = driven_keys(driven)
            if keys:
                box = layout.box()
                box.label(text="Keys (driver -> driven)")
                for i, (x, y) in enumerate(keys):
                    row = box.row(align=True)
                    row.label(text="%.4g -> %.4g" % (x, y))
                    o = row.operator("m3d.rig_driven_key", text="", icon='X')
                    o.action, o.index = 'REMOVE', i
                box.operator("m3d.rig_driven_key", text="Clear Driver", icon='TRASH').action = 'CLEAR'


class PROPERTIES_PT_m3d_rg_drivers(_Drive, Panel):
    bl_label = "Drivers"

    def draw(self, context):
        layout = self.layout
        layout.operator("m3d.rig_drivers_editor", text="Drivers Editor" if not drivers_open(context.screen) else
                        "Close Drivers Editor", icon='DRIVER', depress=drivers_open(context.screen))
        ob = context.active_object
        found = drivers_of(ob) if ob is not None else []
        if not found:
            _small(layout, "No drivers on the active object")
            return
        col = layout.column(align=True)
        for label, owner, fc in found[:20]:
            row = col.row(align=True)
            row.label(text="%s: %s%s" % (label, fc.data_path, "[%d]" % fc.array_index if fc.array_index else ""))
            o = row.operator("m3d.rig_driver_remove", text="", icon='X')
            o.owner, o.path, o.index = owner.name, fc.data_path, fc.array_index
        if len(found) > 20:
            col.label(text="... and %d more" % (len(found) - 20))


# --- Test

class _Test(_Page):
    page = "rig_test"
    needs = ('RIG', 'POSE')


class PROPERTIES_PT_m3d_rg_pose(_Test, Panel):
    bl_label = "Pose"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("m3d.rig_reset_pose", text="Reset Pose", icon='LOOP_BACK').selected_only = False
        row.operator("m3d.rig_reset_pose", text="Reset Selected").selected_only = True
        _buttons(layout, context, (
            ("Clear Location", "pose.loc_clear", 'NONE', {}),
            ("Clear Rotation", "pose.rot_clear", 'NONE', {}),
            ("Clear Scale", "pose.scale_clear", 'NONE', {}),
        ), columns=3)
        layout.label(text="Copy and paste")
        _buttons(layout, context, (
            ("Copy Pose", "pose.copy", 'COPYDOWN', {}),
            ("Paste", "pose.paste", 'PASTEDOWN', {}),
            ("Paste Flipped", "pose.paste", 'PASTEFLIPDOWN', {"flipped": True}),
        ), columns=3)


class PROPERTIES_PT_m3d_rg_position(_Test, Panel):
    bl_label = "Rest / Pose"

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        row = layout.row(align=True)
        row.prop_enum(rig.data, "pose_position", 'REST', text="Rest Position")
        row.prop_enum(rig.data, "pose_position", 'POSE', text="Pose Position")
        _button(layout, context, "Apply Pose as Rest Pose", "pose.armature_apply", 'ARMATURE_DATA',
                {"selected": False})


class PROPERTIES_PT_m3d_rg_rom(_Test, Panel):
    bl_label = "Range of Motion"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        layout.prop(context.scene.m3d_rig, "rom_angle")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("m3d.rig_rom", text="Make Test", icon='ANIM').remove = False
        ad = rig_of(context).animation_data
        if ad is not None and any(t.name == ROM for t in ad.nla_tracks):
            row.operator("m3d.rig_rom", text="Remove", icon='X').remove = True
        _small(layout, "The selected bones (all deforming bones when none) turn each way around X, Y and Z; "
                       "play it to watch the skin")


class PROPERTIES_PT_m3d_rg_check(_Page, Panel):
    page = "rig_test"
    bl_label = "Check Rig"

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        row = layout.row()
        row.scale_y = 1.3
        row.operator("m3d.rig_check", icon='CHECKMARK').fix = 'NONE'
        problems = _checked["problems"] if _checked["rig"] == rig.name else None
        if problems is None:
            _small(layout, "Run it before Bind and before export (Bind runs it too)")
            return
        if not problems:
            layout.label(text="No problems found", icon='CHECKMARK')
        for p in problems:
            draw_lines(layout, context, p.text, icon='ERROR')
            if p.fix:
                o = layout.operator("m3d.rig_check", text=p.fix)
                o.fix, o.mesh = p.kind, p.mesh


def draw_pose_library(layout, context, limit=20):
    """Pose list of the Pose Library: name, Apply, Flipped (also used by the Animation workspace)."""
    poses = pose_assets()
    if not poses:
        _small(layout, "No poses saved in this file yet")
    col = layout.column(align=True)
    for action in poses[:limit]:
        row = col.row(align=True)
        row.label(text=action.name, icon='POSE_HLT')
        o = row.operator("m3d.rig_pose_apply", text="Apply")
        o.name, o.flipped = action.name, False
        o = row.operator("m3d.rig_pose_apply", text="Flipped")
        o.name, o.flipped = action.name, True


class PROPERTIES_PT_m3d_rg_library(_Test, Panel):
    bl_label = "Pose Library"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        layout.prop(s, "pose_name")
        layout.operator("m3d.rig_pose_save", icon='ASSET_MANAGER')
        space = viewport(context)
        if space is not None:
            layout.prop(space, "show_region_asset_shelf", text="Pose Shelf in the Viewport", toggle=True)
        draw_pose_library(layout, context)


# --- Collections

class _Collections(_Page):
    page = "rig_collections"


def draw_bone_collections(layout, context, arm, compact=False):
    """The bone collection tree with its buttons (add, remove, move, assign, select): like the other lists of the docks, no
    resize grip and as tall as its items."""
    row = layout.row()
    row.template_bone_collection_tree(show_handles=False)
    col = row.column(align=True)
    col.operator("armature.collection_add", icon='ADD', text="")
    if not len(arm.collections_all):
        reason(layout, "No bone collections: add one with +")
        return
    col.operator("armature.collection_remove", icon='REMOVE', text="")
    if arm.collections.active is not None:
        col.separator()
        col.operator("armature.collection_move", icon='TRIA_UP', text="").direction = 'UP'
        col.operator("armature.collection_move", icon='TRIA_DOWN', text="").direction = 'DOWN'
    if context.mode in {'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'} and arm.collections.active is not None:
        row = layout.row()
        sub = row.row(align=True)
        sub.operator("armature.collection_assign", text="Assign")
        sub.operator("armature.collection_unassign", text="Remove")
        sub = row.row(align=True)
        sub.operator("armature.collection_select", text="Select")
        sub.operator("armature.collection_deselect", text="Deselect")
    if not compact:   # (only what can work: a hidden collection to show, a soloed one to unsolo)
        row = layout.row(align=True)
        if any(not c.is_visible for c in arm.collections_all):
            row.operator("armature.collection_show_all", text="Show All")
        if any(c.is_solo for c in arm.collections_all):
            row.operator("armature.collection_unsolo_all", text="Unsolo All")


class PROPERTIES_PT_m3d_rg_bcolls(_Collections, Panel):
    bl_label = "Bone Collections"

    def draw(self, context):
        draw_bone_collections(self.layout, context, rig_of(context).data)


def draw_selection_sets(layout, context, rig):
    """The skeleton's selection sets: list, add / remove, assign / select (also used by the Animation workspace). They work
    on bones: outside Pose Mode the card that enters it."""
    if context.mode != 'POSE':
        empty_state(layout, context, "Enter Pose Mode to use bone selection sets", FIXES['POSE'][1])
        return
    draw_list(layout, "POSE_UL_selection_set", rig, "selection_sets", rig, "active_selection_set", "pose.selection_set_add",
              "pose.selection_set_remove", "Select bones, then add a set with +")
    if len(rig.selection_sets):
        row = layout.row(align=True)
        row.operator("pose.selection_set_assign", text="Assign")
        row.operator("pose.selection_set_unassign", text="Remove")
        row.operator("pose.selection_set_select", text="Select").selection_set_index = -1
        row.operator("pose.selection_set_deselect", text="Deselect")


class PROPERTIES_PT_m3d_rg_selsets(_Collections, Panel):
    bl_label = "Selection Sets"

    @classmethod
    def page_poll(cls, context):
        rig = rig_of(context)
        return rig is not None and rig.pose is not None

    def draw(self, context):
        draw_selection_sets(self.layout, context, rig_of(context))


class PROPERTIES_PT_m3d_rg_colors(_Collections, Panel):
    bl_label = "Bone Colors"

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        row = layout.row(align=True)
        for preset, label, _desc in COLOR_PRESETS[1:]:
            row.operator("m3d.rig_control_color", text=label).preset = preset
        s = context.scene.m3d_rig
        layout.prop(s, "control_color")
        row = layout.row(align=True)
        row.operator("m3d.rig_control_color", text="Apply Picked").preset = 'PICKED'
        row.operator("m3d.rig_control_color", text="Default").preset = 'DEFAULT'
        layout.prop(rig.data, "show_bone_colors")


class PROPERTIES_PT_m3d_rg_display(_Collections, Panel):
    bl_label = "Bone Display"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        arm = rig.data
        layout.prop(arm, "display_type", expand=True)
        row = layout.row(align=True)
        row.prop(arm, "show_names", toggle=True)
        row.prop(arm, "show_axes", toggle=True)
        row.prop(rig, "show_in_front", toggle=True)
        layout.prop(arm, "show_bone_custom_shapes")
        layout.prop(arm, "relation_line_position", expand=True)


# --- Left page: bone collections under the Outliner

class PROPERTIES_PT_m3d_rg_left_bcolls(_Page, Panel):
    page = "rig_bones"
    bl_label = "Bone Collections"

    def draw(self, context):
        draw_bone_collections(self.layout, context, rig_of(context).data, compact=True)


class PROPERTIES_PT_m3d_rg_left_bone(_Page, Panel):
    page = "rig_bones"
    bl_label = "Active Bone"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        rig, arm = _rig_data(context)
        if context.mode == 'EDIT_ARMATURE':
            bone = arm.edit_bones.active
        else:
            bone = arm.bones.active
        if bone is None:
            _small(layout, "No active bone")
            return
        layout.prop(bone, "name")
        layout.prop(bone, "use_deform")
        if bone.collections:
            draw_lines(layout, context, "In: " + ", ".join(c.name for c in bone.collections), icon='GROUP_BONE')


GATES = {"skeleton": ('RIG', 'EDIT'), "controls": ('RIG', 'POSE'), "skin": ('RIG', 'MESH'), "test": ('RIG', 'POSE'),
         "collections": ('RIG',), "bones": ('RIG',)}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page, needs, unless=('RIG',) if page == "skeleton" else ()) for page, needs in GATES.items())


# -----------------------------------------------------------------------------
# Status Line

def draw_status_line(layout, context):
    """Rigging Status Line: file, modes (Object / Edit / Pose / Weight Paint), X-Mirror, bone display, names, axes, in
    front, Rest / Pose position, Drivers editor. On a narrow window the bone display is a menu."""
    from m3d_ui import draw_file_buttons, draw_workspace_picker, status_narrow
    draw_file_buttons(layout)
    row = layout.row(align=True)
    for mode, icon, label, modes in (
            ('OBJECT', 'OBJECT_DATAMODE', "Object", {'OBJECT'}), ('EDIT', 'EDITMODE_HLT', "Edit", {'EDIT_ARMATURE', 'EDIT_MESH'}),
            ('POSE', 'POSE_HLT', "Pose", {'POSE'}), ('WEIGHT_PAINT', 'WPAINT_HLT', "Weight Paint", {'PAINT_WEIGHT'})):
        row.operator("m3d.rig_mode", text=label, icon=icon, depress=context.mode in modes).mode = mode
    rig = rig_of(context)
    if rig is not None:
        arm = rig.data
        layout.separator()
        if context.mode == 'POSE':
            layout.prop(rig.pose, "use_mirror_x", text="X-Mirror", icon='MOD_MIRROR', toggle=True)
        elif context.mode == 'PAINT_WEIGHT' and context.active_object.type == 'MESH':
            layout.prop(context.active_object.data, "use_mirror_x", text="X-Mirror", icon='MOD_MIRROR', toggle=True)
        else:
            layout.prop(arm, "use_mirror_x", text="X-Mirror", icon='MOD_MIRROR', toggle=True)
        layout.separator()
        row = layout.row(align=True)
        if status_narrow(context, 1500):
            row.prop(arm, "display_type", text="")
        else:
            for kind, label in (('OCTAHEDRAL', "Octahedral"), ('STICK', "Stick"), ('BBONE', "B-Bone"),
                                ('ENVELOPE', "Envelope"), ('WIRE', "Wire")):
                row.prop_enum(arm, "display_type", kind, text=label)
        layout.separator()
        row = layout.row(align=True)
        row.prop(arm, "show_names", text="Names", toggle=True)
        row.prop(arm, "show_axes", text="Axes", toggle=True)
        row.prop(rig, "show_in_front", text="In Front", toggle=True)
        layout.separator()
        row = layout.row(align=True)
        row.prop_enum(arm, "pose_position", 'REST', text="Rest")
        row.prop_enum(arm, "pose_position", 'POSE', text="Pose")
    layout.separator()
    layout.operator("m3d.rig_drivers_editor", text="Drivers", icon='DRIVER', depress=drivers_open(context.screen))
    draw_workspace_picker(layout, context)


# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

def _color_swatch(row, context):
    sub = row.row()
    sub.scale_x = 1.5   # (a square, like the shelf's icon buttons)
    sub.prop(context.scene.m3d_rig, "control_color", text="")


SHELF_SKELETON = [
    ("m3d.rig_joint", 'BONE_DATA', {}, "Joint"),
    ("armature.extrude_move", 'EXPORT', {}, "Extrude"),
    ("m3d.rig_mirror", 'MOD_MIRROR', {"direction": 'POSITIVE_X'}, "Mirror"),
    ("m3d.rig_orient", 'ORIENTATION_GIMBAL', {}, "Orient"),
    ("armature.autoside_names", 'SORTALPHA', {"type": 'XAXIS'}, "Names L/R"),
    None,
    ("armature.parent_set", 'CONSTRAINT_BONE', {"type": 'CONNECTED'}, "Parent"),
    ("armature.parent_clear", 'UNLINKED', {"type": 'DISCONNECT'}, "Disconnect"),
]
SHELF_CONTROLS = [
    *(("m3d.rig_control", icon, {"shape": shape}, label) for shape, (label, icon, _b) in SHAPES.items()),
    _color_swatch,
    ("m3d.rig_control_color", 'COLOR', {"preset": 'PICKED'}, "Apply"),
    None,
    ("m3d.rig_ik_pole", 'CON_KINEMATIC', {}, "IK + Pole"),
]
SHELF_SKIN = [
    ("m3d.rig_bind", 'ARMATURE_DATA', {}, "Bind"),
    ("m3d.rig_mode", 'WPAINT_HLT', {"mode": 'WEIGHT_PAINT'}, "Paint Weights"),
    ("object.vertex_group_normalize_all", 'MOD_VERTEX_WEIGHT', {"group_select_mode": 'BONE_DEFORM', "lock_active": False},
     "Normalize"),
    ("m3d.rig_mirror_weights", 'MOD_MIRROR', {"direction": 'POSITIVE_X'}, "Mirror Weights"),
]


# -----------------------------------------------------------------------------

classes = (
    M3D_RigSettings,
    M3D_OT_rig_mode,
    M3D_OT_rig_joint,
    M3D_OT_rig_orient,
    M3D_OT_rig_control,
    M3D_OT_rig_control_color,
    M3D_OT_rig_lock,
    M3D_OT_rig_rotate_order,
    M3D_OT_rig_ik_pole,
    M3D_OT_rig_pole_vector,
    M3D_OT_rig_ik_match,
    M3D_OT_rig_constrain,
    M3D_OT_rig_constraints_clear,
    M3D_OT_rig_name_check,
    M3D_OT_rig_rename_chain,
    M3D_OT_rig_mirror,
    M3D_OT_rig_bind,
    M3D_OT_rig_unbind,
    M3D_OT_rig_solo,
    M3D_OT_rig_transfer_weights,
    M3D_OT_rig_mirror_weights,
    M3D_OT_rig_vertex_weight,
    M3D_OT_rig_driven_key,
    M3D_OT_rig_driver_remove,
    M3D_OT_rig_drivers_editor,
    M3D_OT_rig_reset_pose,
    M3D_OT_rig_rom,
    M3D_OT_rig_select_weighted,
    M3D_OT_rig_check,
    M3D_OT_rig_pose_apply,
    M3D_OT_rig_pose_save,
    M3D_OT_rig_rigify,
    M3D_OT_rig_quick,
    M3D_MT_rig_names,
    M3D_UL_rig_influences,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_rg_create,
    PROPERTIES_PT_m3d_rg_quickrig,
    PROPERTIES_PT_m3d_rg_edit,
    PROPERTIES_PT_m3d_rg_mirror,
    PROPERTIES_PT_m3d_rg_orient,
    PROPERTIES_PT_m3d_rg_names,
    PROPERTIES_PT_m3d_rg_hierarchy,
    PROPERTIES_PT_m3d_rg_rigify,
    PROPERTIES_PT_m3d_rg_constraints,
    PROPERTIES_PT_m3d_rg_ik,
    PROPERTIES_PT_m3d_rg_stack,
    PROPERTIES_PT_m3d_rg_shapes,
    PROPERTIES_PT_m3d_rg_locks,
    PROPERTIES_PT_m3d_rg_bind,
    PROPERTIES_PT_m3d_rg_paint,
    PROPERTIES_PT_m3d_rg_influences,
    PROPERTIES_PT_m3d_rg_weights,
    PROPERTIES_PT_m3d_rg_transfer,
    PROPERTIES_PT_m3d_rg_table,
    PROPERTIES_PT_m3d_rg_shapekeys,
    PROPERTIES_PT_m3d_rg_driven_key,
    PROPERTIES_PT_m3d_rg_drivers,
    PROPERTIES_PT_m3d_rg_pose,
    PROPERTIES_PT_m3d_rg_position,
    PROPERTIES_PT_m3d_rg_rom,
    PROPERTIES_PT_m3d_rg_library,
    PROPERTIES_PT_m3d_rg_check,
    PROPERTIES_PT_m3d_rg_bcolls,
    PROPERTIES_PT_m3d_rg_selsets,
    PROPERTIES_PT_m3d_rg_colors,
    PROPERTIES_PT_m3d_rg_display,
    PROPERTIES_PT_m3d_rg_left_bcolls,
    PROPERTIES_PT_m3d_rg_left_bone,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_rig = PointerProperty(type=M3D_RigSettings)
    bpy.app.handlers.load_post.append(_bones_load)
    bpy.app.handlers.depsgraph_update_post.append(_bones_update)


def unregister():
    bpy.app.handlers.depsgraph_update_post.remove(_bones_update)
    bpy.app.handlers.load_post.remove(_bones_load)
    del bpy.types.Scene.m3d_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
