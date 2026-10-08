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
from collections import namedtuple

import bmesh
import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList
from mathutils import Matrix, Vector

from m3d_mode import _button
from m3d_sculpt import grid, reason, split_props, viewport
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


# What a page needs. need -> (message, button label, icon, operator, properties)
FIXES = {
    'RIG': ("No skeleton in the scene", "Joint Tool", 'BONE_DATA', "m3d.rig_joint", {}),
    'EDIT': ("Enter Edit Mode to edit the skeleton", "Edit Mode", 'EDITMODE_HLT', "m3d.rig_mode", {"mode": 'EDIT'}),
    'POSE': ("Enter Pose Mode to add controls and constraints", "Pose Mode", 'POSE_HLT', "m3d.rig_mode",
             {"mode": 'POSE'}),
    'MESH': ("Select the mesh to skin", None, None, None, None),
    'WEIGHT': ("Enter Weight Paint Mode to paint", "Weight Paint Mode", 'WPAINT_HLT', "m3d.rig_mode",
               {"mode": 'WEIGHT_PAINT'}),
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
    col = layout.column(align=True)
    for key in missing(context, needs):
        text, label, icon, idname, props = FIXES[key]
        col.label(text=text)
        if idname:
            _button(col, context, label, idname, icon, props)
        if key == 'RIG':
            break   # Without a skeleton the modes can wait.


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
    joint_name: StringProperty(name="Name", default="Bone", description="Name of the bones the Joint tool makes")
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
    win.workspace.m3d_page_right = tab.page
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
        eb = arm.edit_bones.new(self.base)
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
        xs = [v for b in bones for v in (b.head.x, b.tail.x)]
        eps = 1e-4
        if min(xs) >= -eps and max(xs) > eps:
            side, direction = ".L", 'POSITIVE_X'
        elif max(xs) <= eps and min(xs) < -eps:
            side, direction = ".R", 'NEGATIVE_X'
        else:
            return "X-Mirror: the chain crosses the center, so it was not mirrored"
        for b in bones:
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


def ik_with_pole(context, rig, end_name, chain, factor):
    """An IK constraint on `end_name` with a target bone at its tip and, for chains of two or more bones, a pole target
    bone. The pole angle is searched so the chain bends toward the pole. Returns (target name, pole name or None)."""
    arm = rig.data
    bones = ik_chain(arm, end_name, chain)
    root, tip = bones[0].head_local.copy(), bones[-1].tail_local.copy()
    total = sum(b.length for b in bones)
    pole_pos = pole_position(bones, factor) if len(bones) > 1 else None
    mid_name = bones[len(bones) // 2].name
    small = max(total * 0.1, 1e-3)
    mode = rig.mode
    if mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')
    target = arm.edit_bones.new("IK_" + end_name)
    target.head, target.tail = tip, tip + Vector((0.0, 0.0, small))
    target.use_deform = False
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
        # Pull the target toward the root so the chain has to bend, and try pole angles until the middle joint
        # lands closest to the pole.
        target_pb = rig.pose.bones[target_name]
        pull = (root - tip).normalized() * total * 0.25
        target_pb.location = target_pb.bone.matrix_local.to_3x3().inverted() @ pull
        best = None
        for step in range(24):
            angle = math.radians(-180 + step * 15)
            con.pole_angle = angle
            context.view_layer.update()
            evaluated = rig.evaluated_get(context.evaluated_depsgraph_get())
            dist = (evaluated.pose.bones[mid_name].head - pole_pos).length
            if best is None or dist < best[0] - 1e-9:
                best = (dist, angle)
        con.pole_angle = best[1]
        target_pb.location = (0.0, 0.0, 0.0)
        context.view_layer.update()
    if mode != 'POSE':
        bpy.ops.object.mode_set(mode=mode)
    return target_name, pole_name


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


# -----------------------------------------------------------------------------
# Naming check

def side_of_name(name):
    """'L' or 'R' for a name that ends in a side marker (.L .R _L _R -L -R, with or without lower case), else ''."""
    import re
    m = re.search(r"[._\- ](L|R|l|r|left|right|Left|Right)$", name)
    return "" if not m else ("L" if m.group(1).lower() in {"l", "left"} else "R")


def name_issues(rig):
    """[(bone name, message)] naming problems of a skeleton: a side name without its mirror partner, a name on the wrong
    side, a bone that mirrors another one by position but has no side name, and numbered duplicates (Bone.001)."""
    import re
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
        base = re.match(r"^(.*)\.\d{3}$", name)
        if base and base.group(1) in bones:
            issues.append((name, "Numbered duplicate of \"%s\"" % base.group(1)))
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
    context.view_layer.objects.active = meshes[0]
    return message


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
        self.report({'WARNING'} if "instead" in message else {'INFO'}, message)
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


class M3D_OT_rig_vertex_weight(Operator):
    """Set the weight of one group on the selected vertices (the weight table), or take them out of the group"""
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
                    if self.remove:
                        v[layer].pop(group.index, None)
                    else:
                        v[layer][group.index] = self.weight
            bmesh.update_edit_mesh(ob.data)
            return {'FINISHED'}
        picked = [v.index for v in ob.data.vertices if v.select]
        if not picked:
            self.report({'WARNING'}, "Select vertices first")
            return {'CANCELLED'}
        if self.remove:
            group.remove(picked)
        else:
            group.add(picked, self.weight, 'REPLACE')
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


def bottom_area(screen):
    """The editor the Timeline / Drivers switch works on: the lowest Timeline, Drivers or Graph Editor area."""
    found = [a for a in screen.areas if a.ui_type in {'TIMELINE', 'DRIVERS'}] if screen is not None else []
    return min(found, key=lambda a: a.y) if found else None


def drivers_open(screen):
    area = bottom_area(screen)
    return area is not None and area.ui_type == 'DRIVERS'


class M3D_OT_rig_drivers_editor(Operator):
    """Switch the bottom editor between the Timeline and the Drivers editor"""
    bl_idname = "m3d.rig_drivers_editor"
    bl_label = "Drivers Editor"

    def execute(self, context):
        area = bottom_area(context.screen)
        if area is None:
            self.report({'WARNING'}, "This workspace has no Timeline or Drivers editor")
            return {'CANCELLED'}
        area.ui_type = 'TIMELINE' if area.ui_type == 'DRIVERS' else 'DRIVERS'
        area.tag_redraw()
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
        bones = selected_pose_bones(rig) if self.selected_only else list(rig.pose.bones)
        for pb in bones:
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)
        context.view_layer.update()
        return {'FINISHED'}


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
            pie.operator("armature.symmetrize", text="Mirror Bones", icon='MOD_MIRROR').direction = 'POSITIVE_X'
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


def _gate(page, needs):
    """The panel a page shows first when something is missing: what to do next."""
    def draw(self, context):
        draw_fixes(self.layout, context, needs)
    return type("PROPERTIES_PT_m3d_rg_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Rigging", "bl_options": {'HIDE_HEADER'}, "page": "rig_" + page,
        "page_poll": classmethod(lambda cls, context: not ready(context, needs)), "draw": draw})


def _rig_data(context):
    """(skeleton object, its armature data) or (None, None)."""
    rig = rig_of(context)
    return rig, (rig.data if rig is not None else None)


def _small(layout, text):
    layout.label(text=text)


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
            layout.prop(arm, "use_mirror_x", text="X-Mirror (names a one-sided chain .L / .R and mirrors it)")


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
            ("Mirror +X to -X", "armature.symmetrize", 'MOD_MIRROR', {"direction": 'POSITIVE_X'}),
            ("Mirror -X to +X", "armature.symmetrize", 'MOD_MIRROR', {"direction": 'NEGATIVE_X'}),
            ("Select Mirror", "armature.select_mirror", 'RESTRICT_SELECT_OFF', {}),
            ("Add Mirror to Selection", "armature.select_mirror", 'SELECT_EXTEND', {"extend": True}),
        ))


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
        _small(layout, "Roll to")
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
        _small(layout, "Add .L / .R by position")
        _buttons(layout, context, (
            ("By X", "armature.autoside_names", 'NONE', {"type": 'XAXIS'}),
            ("By Y", "armature.autoside_names", 'NONE', {"type": 'YAXIS'}),
            ("By Z", "armature.autoside_names", 'NONE', {"type": 'ZAXIS'}),
        ), columns=3)
        _button(layout, context, "Flip Names (.L <-> .R)", "armature.flip_names", 'ARROW_LEFTRIGHT', {})
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
            _small(layout, "Rigify builds a full control rig from a meta-rig.")
            _small(layout, "It is off until you turn it on:")
            layout.operator("m3d.rig_rigify", text="Enable Rigify", icon='PLUGIN').action = 'ENABLE'
        else:
            layout.operator("m3d.rig_rigify", text="Human Meta-Rig", icon='ARMATURE_DATA').action = 'META'
            layout.operator("m3d.rig_rigify", text="Generate Rig", icon='ARMATURE_DATA').action = 'GENERATE'
            _small(layout, "Fit the meta-rig to the character in Edit Mode first")
        if s.rigify_note:
            layout.label(text="Rigify: " + s.rigify_note[:60], icon='ERROR')


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
        _buttons(self.layout, context, [(label, "pose.constraint_add_with_targets", icon, {"type": kind})
                                        for label, kind, icon in CONSTRAINTS])


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
                                   ("Clear IK", "pose.ik_clear", 'X', {})))
        active = rig.data.bones.active
        if active is not None:
            pb = rig.pose.bones[active.name]
            row = layout.row(align=True)
            row.prop(pb, "lock_ik_x", text="Lock X", toggle=True)
            row.prop(pb, "lock_ik_y", text="Y", toggle=True)
            row.prop(pb, "lock_ik_z", text="Z", toggle=True)
            layout.prop(pb, "ik_stretch", slider=True)


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
        layout.prop(s, "skin_method", expand=True)
        if s.skin_method == 'AUTO':
            layout.prop(s, "skin_fallback")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("m3d.rig_bind", icon='ARMATURE_DATA')
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
        layout.template_list("M3D_UL_rig_influences", "", mesh, "vertex_groups", mesh.vertex_groups, "active_index", rows=6)
        row = layout.row(align=True)
        row.operator("object.vertex_group_lock", text="Lock All", icon='LOCKED').action = 'LOCK'
        row.operator("object.vertex_group_lock", text="Unlock All", icon='UNLOCKED').action = 'UNLOCK'


class PROPERTIES_PT_m3d_rg_weights(_Skin, Panel):
    bl_label = "Weights"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = context.scene.m3d_rig
        mesh = skin_mesh(context)
        painting = context.mode == 'PAINT_WEIGHT'
        col = layout.column(align=True)
        col.enabled = painting
        _button(col, context, "Flood Weight (brush value)", "paint.weight_set", 'BRUSH_DATA', {})
        _buttons(col, context, (("Weights from Bones", "paint.weight_from_bones", 'BONE_DATA', {"type": 'AUTOMATIC'}),
                                ("From Envelopes", "paint.weight_from_bones", 'BONE_DATA', {"type": 'ENVELOPES'})))
        if not painting:
            _small(layout, "Flood needs Weight Paint Mode")
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
        layout.label(text="Vertex %d" % index, icon='VERTEXSEL')
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
            reason(layout, "Select a mesh for shape keys")
            return
        key = mesh.data.shape_keys
        row = layout.row()
        if key is not None:
            row.template_list("MESH_UL_shape_keys", "", key, "key_blocks", mesh, "active_shape_key_index", rows=4)
        col = row.column(align=True)
        o = col.operator("object.shape_key_add", icon='ADD', text="")
        o.from_mix = False
        col.operator("object.shape_key_remove", icon='REMOVE', text="").all = False
        if key is None:
            layout.operator("object.shape_key_add", text="Add Basis", icon='SHAPEKEY_DATA').from_mix = False
            return
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
        box.prop(s, "dk_kind", expand=True)
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
                        "Back to Timeline", icon='DRIVER', depress=drivers_open(context.screen))
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
        _small(layout, "Copy and paste")
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
        poses = pose_assets()
        if not poses:
            _small(layout, "No poses saved in this file yet")
        col = layout.column(align=True)
        for action in poses[:20]:
            row = col.row(align=True)
            row.label(text=action.name, icon='POSE_HLT')
            o = row.operator("m3d.rig_pose_apply", text="Apply")
            o.name, o.flipped = action.name, False
            o = row.operator("m3d.rig_pose_apply", text="Flipped")
            o.name, o.flipped = action.name, True


# --- Collections

class _Collections(_Page):
    page = "rig_collections"


def draw_bone_collections(layout, context, arm, compact=False):
    """The bone collection tree with its buttons (add, remove, move, assign, select)."""
    row = layout.row()
    row.template_bone_collection_tree()
    col = row.column(align=True)
    col.operator("armature.collection_add", icon='ADD', text="")
    col.operator("armature.collection_remove", icon='REMOVE', text="")
    if arm.collections.active is not None:
        col.separator()
        col.operator("armature.collection_move", icon='TRIA_UP', text="").direction = 'UP'
        col.operator("armature.collection_move", icon='TRIA_DOWN', text="").direction = 'DOWN'
    if context.mode in {'POSE', 'EDIT_ARMATURE', 'PAINT_WEIGHT'}:
        row = layout.row()
        sub = row.row(align=True)
        sub.operator("armature.collection_assign", text="Assign")
        sub.operator("armature.collection_unassign", text="Remove")
        sub = row.row(align=True)
        sub.operator("armature.collection_select", text="Select")
        sub.operator("armature.collection_deselect", text="Deselect")
    if not compact:
        row = layout.row(align=True)
        row.operator("armature.collection_show_all", text="Show All")
        row.operator("armature.collection_unsolo_all", text="Unsolo All")


class PROPERTIES_PT_m3d_rg_bcolls(_Collections, Panel):
    bl_label = "Bone Collections"

    def draw(self, context):
        draw_bone_collections(self.layout, context, rig_of(context).data)


class PROPERTIES_PT_m3d_rg_selsets(_Collections, Panel):
    bl_label = "Selection Sets"

    @classmethod
    def page_poll(cls, context):
        rig = rig_of(context)
        return rig is not None and rig.pose is not None

    def draw(self, context):
        layout = self.layout
        rig = rig_of(context)
        row = layout.row()
        row.enabled = context.mode == 'POSE'
        row.template_list("POSE_UL_selection_set", "", rig, "selection_sets", rig, "active_selection_set",
                          rows=4 if len(rig.selection_sets) else 1)
        col = row.column(align=True)
        col.operator("pose.selection_set_add", icon='ADD', text="")
        col.operator("pose.selection_set_remove", icon='REMOVE', text="")
        row = layout.row(align=True)
        row.enabled = context.mode == 'POSE'
        row.operator("pose.selection_set_assign", text="Assign")
        row.operator("pose.selection_set_unassign", text="Remove")
        row.operator("pose.selection_set_select", text="Select").selection_set_index = -1
        row.operator("pose.selection_set_deselect", text="Deselect")


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
            layout.label(text="In: " + ", ".join(c.name for c in bone.collections)[:48], icon='GROUP_BONE')


GATES = {"skeleton": ('RIG', 'EDIT'), "controls": ('RIG', 'POSE'), "skin": ('RIG', 'MESH'), "test": ('RIG', 'POSE'),
         "collections": ('RIG',), "bones": ('RIG',)}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page, needs) for page, needs in GATES.items())


# -----------------------------------------------------------------------------
# Status Line

def draw_status_line(layout, context):
    """Rigging Status Line: file, modes (Object / Edit / Pose / Weight Paint), X-Mirror, bone display, names, axes, in
    front, Rest / Pose position, Drivers editor."""
    from m3d_ui import draw_file_buttons, draw_workspace_picker
    draw_file_buttons(layout)
    row = layout.row(align=True)
    for mode, icon, label, modes in (
            ('OBJECT', 'OBJECT_DATAMODE', "Object", {'OBJECT'}), ('EDIT', 'EDITMODE_HLT', "Edit", {'EDIT_ARMATURE', 'EDIT_MESH'}),
            ('POSE', 'POSE_HLT', "Pose", {'POSE'}), ('WEIGHT_PAINT', 'WPAINT_HLT', "Weight Paint", {'PAINT_WEIGHT'})):
        row.operator("m3d.rig_mode", text=label, icon=icon, depress=context.mode in modes).mode = mode
    rig = rig_of(context)
    if rig is not None:
        arm = rig.data
        if context.mode == 'POSE':
            layout.prop(rig.pose, "use_mirror_x", text="X-Mirror", icon='MOD_MIRROR', toggle=True)
        elif context.mode == 'PAINT_WEIGHT' and context.active_object.type == 'MESH':
            layout.prop(context.active_object.data, "use_mirror_x", text="X-Mirror", icon='MOD_MIRROR', toggle=True)
        else:
            layout.prop(arm, "use_mirror_x", text="X-Mirror", icon='MOD_MIRROR', toggle=True)
        row = layout.row(align=True)
        for kind, label in (('OCTAHEDRAL', "Octahedral"), ('STICK', "Stick"), ('BBONE', "B-Bone"),
                            ('ENVELOPE', "Envelope"), ('WIRE', "Wire")):
            row.prop_enum(arm, "display_type", kind, text=label)
        row = layout.row(align=True)
        row.prop(arm, "show_names", text="Names", toggle=True)
        row.prop(arm, "show_axes", text="Axes", toggle=True)
        row.prop(rig, "show_in_front", text="In Front", toggle=True)
        row = layout.row(align=True)
        row.prop_enum(arm, "pose_position", 'REST', text="Rest")
        row.prop_enum(arm, "pose_position", 'POSE', text="Pose")
    layout.operator("m3d.rig_drivers_editor", text="Drivers", icon='DRIVER', depress=drivers_open(context.screen))
    draw_workspace_picker(layout, context)


# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

def _color_swatch(row, context):
    sub = row.row()
    sub.scale_x = 0.8
    sub.prop(context.scene.m3d_rig, "control_color", text="")


SHELF_SKELETON = [
    ("m3d.rig_joint", 'BONE_DATA', {}, "Joint"),
    ("armature.extrude_move", 'EXPORT', {}, "Extrude"),
    ("armature.symmetrize", 'MOD_MIRROR', {"direction": 'POSITIVE_X'}, "Mirror"),
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
    M3D_OT_rig_ik_pole,
    M3D_OT_rig_name_check,
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
    M3D_OT_rig_pose_apply,
    M3D_OT_rig_pose_save,
    M3D_OT_rig_rigify,
    M3D_MT_rig_names,
    M3D_UL_rig_influences,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_rg_create,
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
    PROPERTIES_PT_m3d_rg_library,
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


def unregister():
    del bpy.types.Scene.m3d_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
