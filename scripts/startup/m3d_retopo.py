# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Retopology for Maelstrom3D: a low poly drawn over a high poly, or made from it (see m3d_pair.py for the pairs).

A live surface is a mesh that new points snap onto (Scene.m3d_live_surface). Make Live shows it, makes it unselectable so
that clicks go to the new mesh, and sets the scene's snapping to project every moved point onto the faces under the pointer;
Make Not Live puts all that back. What was set before is kept in Scene.m3d_live_saved (JSON), so a file saved while live
opens live with the same settings, and a surface that is deleted gives them back.

New Low Poly starts an empty mesh paired with the surface and enters Quad Draw (the Poly Build tool). Auto Low Poly makes
the low poly from a copy of the high poly with QuadriFlow (quads) or Decimate (triangles).
"""

import json
import time

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator

import m3d_inputs
import m3d_pair
from m3d_pair import format_count, is_mesh, pair_of, set_role, split_role
from m3d_workspace import current_kind

QUADRIFLOW_LIMIT = 300_000   # QuadriFlow on millions of faces takes minutes or fails: the copy is reduced to this first

# Snapping while a surface is live: every moved point lands where the pointer is on the faces (Face Project, individual
# elements), never on the mesh being drawn, and the surface may not be selectable.
RETOPO_SNAP = {"use_snap": True, "snap_elements": ['FACE_PROJECT'], "use_snap_self": False, "use_snap_nonedit": True,
               "use_snap_selectable": False, "use_snap_translate": True}
SURFACE_PROPS = ("hide_select", "display_type", "hide_surface_pick")   # (what Make Live changes on the surface)

# Scene name -> what was saved, for every scene whose snapping is set for retopology in this session. Undo and Redo bring back
# the data of a scene (the live surface, the saved settings) but not its tool settings: `_undo_post` makes them follow.
_live = {}


# -----------------------------------------------------------------------------
# The live state

def saved_of(scene):
    """What was set before the surface went live ({} when none is)."""
    try:
        return json.loads(scene.m3d_live_saved) if scene.m3d_live_saved else {}
    except ValueError:
        return {}


def spaces_3d():
    """The 3D views of every screen."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                yield area.spaces.active


def snap_of(ts):
    return {name: sorted(getattr(ts, name)) if name == "snap_elements" else getattr(ts, name) for name in RETOPO_SNAP}


def set_snap(ts, state):
    for name, value in state.items():
        setattr(ts, name, set(value) if name == "snap_elements" else value)


def set_overlay(value):
    for space in spaces_3d():
        space.overlay.show_retopology = value


def give_back(scene, saved):
    """The snapping and the overlay of the user (`saved`) are back."""
    if "snap" in saved:
        set_snap(scene.tool_settings, saved["snap"])
    if saved.get("overlay") is not None:
        set_overlay(saved["overlay"])


def stop_live(scene, keep_settings=False):
    """The surface of the scene is not live any more: it can be selected and is drawn as before, and the snapping and the
    overlay come back (unless another surface goes live right after). Returns the surface that was live."""
    surface, saved = scene.m3d_live_surface, saved_of(scene)
    if surface is not None:
        for name, value in saved.get("surface", {}).items():
            setattr(surface, name, value)
        scene.m3d_live_surface = None
    if not keep_settings:
        give_back(scene, saved)
        scene.m3d_live_saved = ""
        _live.pop(scene.name, None)
    return surface


def start_live(scene, surface):
    """`surface` is the live surface. The first one saves the snapping and the overlay of the user and turns on the retopology
    ones; a surface that replaces another keeps what was saved. Nothing about visibility here: see `make_live`."""
    if scene.m3d_live_surface == surface:
        return
    if scene.m3d_live_surface is not None:
        stop_live(scene, keep_settings=True)
    saved, ts = saved_of(scene), scene.tool_settings
    first = "snap" not in saved
    if first:
        spaces = list(spaces_3d())
        saved["snap"] = snap_of(ts)
        saved["overlay"] = spaces[0].overlay.show_retopology if spaces else None
    saved["surface"] = {name: getattr(surface, name) for name in SURFACE_PROPS}
    surface.hide_select, surface.hide_surface_pick = True, False
    if surface.display_type in {'BOUNDS', 'WIRE'}:   # (these are never snapped to)
        surface.display_type = 'TEXTURED'
    scene.m3d_live_surface = surface
    scene.m3d_live_saved = json.dumps(saved)
    if first:
        take_over(scene)
        _live[scene.name] = scene.m3d_live_saved


def take_over(scene):
    """The snapping and the overlay for retopology."""
    set_snap(scene.tool_settings, RETOPO_SNAP)
    set_overlay(True)


def stale(scene):
    """Settings are saved but the surface is gone (deleted, or out of the scene)."""
    if not scene.m3d_live_saved:
        return False
    surface = scene.m3d_live_surface
    return surface is None or surface.name not in scene.objects


def surface_for(context):
    """The mesh to make live for the active mesh: its group's high poly, else the mesh itself."""
    ob = context.view_layer.objects.active
    if not is_mesh(ob):
        return None
    lows, highs = pair_of(context, ob)
    if ob.m3d_pair.role == 'HIGH' or not highs:
        return ob
    return m3d_pair.pick_high(highs, ob.m3d_pair.group)


def make_live(context, surface):
    """Show `surface` (a parked high poly is shown again), take it out of the selection and make it the live surface. Returns
    why that can't be done, else None."""
    vl = context.view_layer
    if surface.hide_viewport or (not surface.hide_get() and not surface.visible_get()):
        return "%s is hidden: it can't be a live surface" % surface.name
    if vl.objects.active == surface:
        m3d_pair.leave_modes(context)
        low = next((o for o in pair_of(context, surface)[0] if not o.hide_get()), None)
        if low is not None:   # (the low poly takes over; a mesh with no pair stays active, but can't be selected)
            vl.objects.active = low
            low.select_set(True)
    if surface.hide_get():
        if surface.m3d_pair.parked:
            m3d_pair.restore(surface)
        else:
            surface.hide_set(False)
    surface.select_set(False)
    start_live(context.scene, surface)
    return None


def ask_first(context, surface):
    """True when showing `surface` is something to ask about: it is a high poly we parked."""
    return surface is not None and surface.hide_get() and surface.m3d_pair.parked and surface != context.scene.m3d_live_surface


# -----------------------------------------------------------------------------
# Operators

class M3D_OT_hp_make_live(Operator):
    """Make the high poly of this mesh (or the mesh itself) a live surface: what you draw snaps onto it. It can't be selected while it is live"""
    bl_idname = "m3d.hp_make_live"
    bl_label = "Make Live"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return surface_for(context) is not None

    def invoke(self, context, event):
        surface = surface_for(context)
        if ask_first(context, surface):
            return context.window_manager.invoke_confirm(self, event, title="Make Live", confirm_text="OK",
                                                         message=m3d_pair.edit_message([surface]))
        return self.execute(context)

    def execute(self, context):
        surface = surface_for(context)
        if surface is None:
            return {'CANCELLED'}
        problem = make_live(context, surface)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}
        self.report({'INFO'}, "%s is live" % surface.name)
        return {'FINISHED'}


class M3D_OT_hp_make_not_live(Operator):
    """The live surface can be selected again and the snapping goes back to what it was. A high poly that has a low poly is hidden again"""
    bl_idname = "m3d.hp_make_not_live"
    bl_label = "Make Not Live"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.m3d_live_surface or context.scene.m3d_live_saved)

    def execute(self, context):
        surface = stop_live(context.scene)
        lows = [o for o in pair_of(context, surface)[0] if not o.hide_get()] if surface is not None else []
        if lows and current_kind(context) != 'SCULPT':   # (it has a low poly: back to being parked)
            vl = context.view_layer
            if vl.objects.active == surface:
                vl.objects.active = lows[0]
                lows[0].select_set(True)
            m3d_pair.park(surface)
        return {'FINISHED'}


def group_for(context, surface):
    """The group a new low poly of `surface` joins: the one it has, else a new one named after it."""
    p = surface.m3d_pair
    if p.role != 'NONE' and p.group:
        return p.group
    return m3d_pair.unique_group(context, split_role(surface.name)[0])


def finish_low(context, low, group):
    """The new mesh is the low poly of `group`, and the only mesh selected and the active one."""
    set_role(low, 'LOW', group)
    for ob in context.selected_objects:
        ob.select_set(False)
    low.select_set(True)
    context.view_layer.objects.active = low


def start_quad_draw(name):
    """Edit Mode and the Quad Draw tool on the mesh `name`, if it is still the active one and in Object Mode."""
    ob = bpy.data.objects.get(name)
    context = bpy.context
    if ob is None or context.view_layer.objects.active != ob or ob.mode != 'OBJECT':
        return
    bpy.ops.object.mode_set('EXEC_DEFAULT', False, mode='EDIT')   # (False: no undo step of its own)
    if not bpy.app.background:   # (the toolbar has not been drawn: a tool can't be set)
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.poly_build", space_type='VIEW_3D')
        except RuntimeError:
            pass   # (no 3D View to set it in: Edit Mode is all there is)


def quad_draw_soon(name):
    """Start Quad Draw once the operator is over: its undo step is then one of Object Mode, which keeps the new mesh (a
    step taken in Edit Mode does not: Redo would lose it)."""
    bpy.app.timers.register(lambda: start_quad_draw(name), first_interval=0.0)


class M3D_OT_hp_new_low(Operator):
    """Draw a new low poly over the live surface (Quad Draw): an empty mesh paired with it, in Edit Mode"""
    bl_idname = "m3d.hp_new_low"
    bl_label = "New Low Poly"
    bl_options = {'REGISTER', 'UNDO'}

    symmetric: BoolProperty(name="Symmetric (X)", options={'SKIP_SAVE'},
                            description="Draw one half: a Mirror modifier (X, points on the middle stay there) makes the other")

    @classmethod
    def description(cls, _context, props):
        return ("Draw one half of a new low poly over the live surface (Quad Draw): a Mirror modifier makes the other half"
                if props.symmetric else cls.__doc__)

    @classmethod
    def poll(cls, context):
        return context.scene.m3d_live_surface is not None or surface_for(context) is not None

    def invoke(self, context, event):
        surface = context.scene.m3d_live_surface or surface_for(context)
        if ask_first(context, surface):
            return context.window_manager.invoke_confirm(self, event, title="New Low Poly", confirm_text="OK",
                                                         message=m3d_pair.edit_message([surface]))
        return self.execute(context)

    def execute(self, context):
        surface = context.scene.m3d_live_surface or surface_for(context)
        if surface is None:
            return {'CANCELLED'}
        group = group_for(context, surface)
        set_role(surface, 'HIGH', group)   # (before it goes live: a role change gives back what the old role did to it)
        problem = make_live(context, surface)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}
        name = group + "_low"
        low = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        for collection in surface.users_collection or (context.scene.collection,):
            collection.objects.link(low)
        low.matrix_world = surface.matrix_world.copy()
        if self.symmetric:
            mirror = low.modifiers.new("Mirror", 'MIRROR')
            mirror.use_clip = mirror.use_mirror_merge = True
        m3d_pair.inherit_explode(low, surface)
        m3d_pair.leave_modes(context)
        finish_low(context, low, group)
        quad_draw_soon(low.name)
        self.report({'INFO'}, "Quad Draw on %s: Shift+click on it to add the first point" % surface.name)
        return {'FINISHED'}


def copy_of(context, src, name, drop=()):
    """A copy of the mesh `src` as it shows (modifiers applied, but those of a type in `drop`) with no role, inputs or
    flags of `src`."""
    copy = src.copy()
    copy.data = src.data.copy()
    copy.name = copy.data.name = name
    for collection in src.users_collection or (context.scene.collection,):
        collection.objects.link(copy)
    m3d_inputs.clear(copy)
    p = copy.m3d_pair
    if p.render_parked:   # (left out of renders as a part of `src`'s pair)
        copy.hide_render = False
    p.role, p.group, p.parked, p.ghost, p.render_parked, p.display_level = 'NONE', "", False, "", False, 0
    copy.hide_select = copy.hide_viewport = False   # (a live surface can't be selected)
    for mod in [m for m in copy.modifiers if m.type in drop]:
        copy.modifiers.remove(mod)
    if copy.modifiers:   # (a Multires high poly: what the viewport shows, not its base mesh)
        try:
            mesh = bpy.data.meshes.new_from_object(copy.evaluated_get(context.evaluated_depsgraph_get()))
        except RuntimeError:
            discard(copy)
            raise
        old, copy.data = copy.data, mesh
        copy.modifiers.clear()
        bpy.data.meshes.remove(old)
        mesh.name = name
    return copy


def discard(ob):
    """Take a mesh we made out of the file again (object and mesh)."""
    mesh = ob.data
    bpy.data.objects.remove(ob)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def decimate(context, ob, target, symmetry=False):
    """Collapse the faces of `ob` into `target` triangles, about (the Decimate modifier, applied); `symmetry`: the same on
    both sides of X."""
    tris = len(ob.data.loop_triangles)
    if tris > target:
        mod = ob.modifiers.new("Decimate", 'DECIMATE')
        mod.decimate_type, mod.ratio, mod.use_collapse_triangulate = 'COLLAPSE', target / tris, True
        mod.use_symmetry, mod.symmetry_axis = symmetry, 'X'
        with m3d_pair._on(context, ob):
            bpy.ops.object.modifier_apply(modifier=mod.name)


def merge_tiny_edges(ob):
    """Merge the points that decimating left almost on top of each other: QuadriFlow refuses a mesh with an edge shorter than
    0.0001. Not for a mesh whose faces are that small themselves."""
    mesh = ob.data
    edge = (4 * m3d_pair.surface_area(mesh) / (max(len(mesh.polygons), 1) * 3 ** 0.5)) ** 0.5   # (of a triangle of that area)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=min(2e-4, 0.1 * edge))
    bm.to_mesh(mesh)
    bm.free()


def reduce(context, ob, boundary, name=""):
    """A mesh over QUADRIFLOW_LIMIT faces is brought down to about that before QuadriFlow: Voxel Remesh (~1 s instead of
    ~30 s at 1.5M faces, and a closed mesh, which QuadriFlow needs), or with `boundary` Decimate (a voxel remesh would close
    the open borders). Returns the note for the report, about `name` (the mesh's own by default; "" when nothing was done)."""
    if len(ob.data.polygons) <= QUADRIFLOW_LIMIT:
        return ""
    name = name or ob.name
    if boundary:
        decimate(context, ob, QUADRIFLOW_LIMIT)
        merge_tiny_edges(ob)
    else:
        ob.data.remesh_voxel_size = (m3d_pair.surface_area(ob.data) / QUADRIFLOW_LIMIT) ** 0.5
        with m3d_pair._on(context, ob):
            bpy.ops.object.voxel_remesh()
    return " (%s first reduced to about %s faces)" % (name, format_count(QUADRIFLOW_LIMIT))


class M3D_OT_hp_auto_low(Operator):
    """Make a low poly from the high poly: a copy of it with fewer faces, paired with it. It has no UVs yet"""
    bl_idname = "m3d.hp_auto_low"
    bl_label = "Auto Low Poly"
    bl_options = {'REGISTER', 'UNDO'}

    method: EnumProperty(name="Method", default='QUADRIFLOW', items=(
        ('QUADRIFLOW', "Auto Retopology (quads)", "Rebuild the surface as an even mesh of quads"),
        ('DECIMATE', "Decimate", "Collapse the faces of the high poly into fewer triangles")))
    faces: IntProperty(name="Faces", description="About how many faces the low poly gets", default=2000, min=4,
                       soft_max=100000)
    sharp: BoolProperty(name="Preserve Sharp", description="Keep the sharp features of the high poly")
    boundary: BoolProperty(name="Preserve Boundary", description="Keep the open borders of the high poly")
    symmetry: BoolProperty(name="Symmetry (X)", options={'SKIP_SAVE'},
                           description="The low poly is the same on both sides of X (on at first when the high poly's Mirror X "
                                       "is on)")

    @classmethod
    def poll(cls, context):
        return surface_for(context) is not None

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "method")
        layout.prop(self, "faces")
        layout.prop(self, "symmetry")
        if self.method == 'QUADRIFLOW':
            layout.prop(self, "sharp")
            layout.prop(self, "boundary")

    def execute(self, context):
        surface = surface_for(context)
        if surface is None:
            return {'CANCELLED'}
        if not self.properties.is_property_set("symmetry"):
            self.symmetry = surface.data.use_mirror_x
        t0 = time.perf_counter()
        m3d_pair.leave_modes(context)   # (the copy is of the mesh as it is stored)
        group = group_for(context, surface)
        copy = copy_of(context, surface, group + "_low")
        note = ""
        try:
            if self.method == 'QUADRIFLOW':
                note = reduce(context, copy, self.boundary, surface.name)
                copy.data.use_mirror_x = self.symmetry   # (QuadriFlow's symmetry is the mesh's own)
                with m3d_pair._on(context, copy):
                    done = bpy.ops.object.quadriflow_remesh(mode='FACES', target_faces=self.faces, smooth_normals=True,
                                                            use_preserve_sharp=self.sharp, use_preserve_boundary=self.boundary,
                                                            use_mesh_symmetry=self.symmetry)
                if done != {'FINISHED'}:
                    raise RuntimeError("Auto Retopology found no result")
            else:
                decimate(context, copy, self.faces, self.symmetry)
                copy.data.shade_smooth()
        except RuntimeError as err:
            discard(copy)
            if self.method == 'QUADRIFLOW':
                self.report({'ERROR'}, "Auto Retopology could not remesh %s: the mesh must be closed, without loose edges or "
                            "flipped faces. Try Voxel Remesh on the high poly first, or use Decimate" % surface.name)
            else:
                self.report({'ERROR'}, "Decimate failed on %s: %s" % (surface.name, str(err).strip()))
            return {'CANCELLED'}
        set_role(surface, 'HIGH', group)
        finish_low(context, copy, group)
        self.report({'INFO'}, "%s: %s faces in %.1f s%s. Unwrap it in the UV workspace (F3)" % (
            copy.name, format(len(copy.data.polygons), ","), time.perf_counter() - t0, note))
        return {'FINISHED'}


def conform_target(context, ob):
    """The surface the low poly `ob` conforms to: the live surface, else the shown high poly of its pair (None: none)."""
    target = context.scene.m3d_live_surface
    if target is None:
        target = next((h for h in pair_of(context, ob)[1] if not h.hide_get()), None)
    return target if target is not None and target != ob and target.visible_get() else None


class M3D_OT_hp_conform(Operator):
    """Move every point of this low poly onto the live surface (or its high poly), along the point's normal"""
    bl_idname = "m3d.hp_conform"
    bl_label = "Conform to Surface"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.view_layer.objects.active
        return is_mesh(ob) and conform_target(context, ob) is not None

    def execute(self, context):
        ob = context.view_layer.objects.active
        mode = ob.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')   # (Apply works in Object Mode only)
        mod = ob.modifiers.new("Conform", 'SHRINKWRAP')
        mod.target, mod.wrap_method, mod.wrap_mode = conform_target(context, ob), 'PROJECT', 'ON_SURFACE'
        mod.use_negative_direction = mod.use_positive_direction = True   # (no axis: along the normals, both ways)
        try:
            with m3d_pair._on(context, ob):
                bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)   # (before a Mirror)
                bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError as err:
            ob.modifiers.remove(mod)
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        finally:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
        return {'FINISHED'}


class M3D_OT_retopo_quads(Operator):
    """Rebuild this mesh as even quads, in place: the target face count, ratio or edge length below. UVs and Face Sets
    are lost; a mesh of more than 300,000 faces is reduced first. Auto Low Poly makes a paired copy instead"""
    bl_idname = "m3d.retopo_quads"
    bl_label = "Rebuild as Quads"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.view_layer.objects.active
        return is_mesh(ob) and not any(m.type == 'MULTIRES' for m in ob.modifiers) and not ob.use_dynamic_topology_sculpting

    @staticmethod
    def estimate(context, ob):
        """About how many faces QuadriFlow makes with its last settings (the Geometry tab's)."""
        props = context.window_manager.operator_properties_last("object.quadriflow_remesh")
        if props.mode == 'FACES':
            return props.target_faces
        if props.mode == 'RATIO':
            return min(len(ob.data.polygons), QUADRIFLOW_LIMIT) * props.target_ratio
        return m3d_pair.surface_area(ob.data) / max(props.target_edge_length, 1e-6) ** 2

    def invoke(self, context, event):
        ob = context.view_layer.objects.active
        return m3d_pair.heavy_guard(self, context, event, self.estimate(context, ob), "Rebuild as Quads")

    def execute(self, context):
        ob = context.view_layer.objects.active
        problem = m3d_pair.heavy_problem(self.estimate(context, ob), "Rebuild as Quads")
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}
        props = context.window_manager.operator_properties_last("object.quadriflow_remesh")
        options = {name: getattr(props, name) for name in (
            "mode", "target_ratio", "target_edge_length", "target_faces", "use_mesh_symmetry", "use_preserve_sharp",
            "use_preserve_boundary", "smooth_normals", "seed")}
        mode = ob.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            note = reduce(context, ob, options["use_preserve_boundary"])
            with m3d_pair._on(context, ob):
                done = bpy.ops.object.quadriflow_remesh('EXEC_DEFAULT', **options)
            if done != {'FINISHED'}:
                raise RuntimeError("found no result")
        except RuntimeError as err:
            self.report({'ERROR'}, "Auto Retopology could not remesh %s (%s): the mesh must be closed, without loose edges "
                        "or flipped faces. Try Voxel Remesh first" % (ob.name, str(err).replace("Error: ", "").strip()))
            return {'CANCELLED'}
        finally:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
        self.report({'INFO'}, "%s: %s faces%s" % (ob.name, format(len(ob.data.polygons), ","), note))
        return {'FINISHED'}


class M3D_OT_quad_add(bpy.types.Macro):
    """Quad Draw: add a point, an edge or a quad at the pointer, and move it with the pointer"""
    bl_idname = "m3d.quad_add"
    bl_label = "Quad Draw Add"
    bl_options = {'REGISTER', 'UNDO'}


def define_quad_add():
    """Poly Build's add leaves the point it extends from selected, so the drag of the new point drags that one too: nothing is
    selected first (the other ways of adding clear the selection themselves)."""
    M3D_OT_quad_add.define("MESH_OT_select_all").properties.action = 'DESELECT'
    M3D_OT_quad_add.define("MESH_OT_polybuild_face_at_cursor")
    move = M3D_OT_quad_add.define("TRANSFORM_OT_translate").properties
    move.release_confirm, move.use_proportional_edit, move.mirror = True, False, False


# -----------------------------------------------------------------------------
# Keeping the state true

@bpy.app.handlers.persistent
def _depsgraph_update(scene, _depsgraph):
    """The live surface was deleted: the snapping comes back (from a timer, where writing is allowed)."""
    if scene.m3d_live_saved and stale(scene) and not bpy.app.timers.is_registered(clean_up):
        bpy.app.timers.register(clean_up, first_interval=0.0)


def clean_up():
    """Give back the settings of every scene whose live surface is gone."""
    for scene in bpy.data.scenes:
        if stale(scene):
            stop_live(scene)


@bpy.app.handlers.persistent
def _load_post(*_args):
    """A file that was live keeps its surface and its settings (they are in the file); one without its surface gets the old
    settings back."""
    _live.clear()
    _live.update({scene.name: scene.m3d_live_saved for scene in bpy.data.scenes if scene.m3d_live_saved})
    clean_up()


@bpy.app.handlers.persistent
def _undo_post(*_args):
    """Undo or Redo went through a Make Live or a Make Not Live: the scene is live or not, and its snapping follows."""
    for scene in bpy.data.scenes:
        saved = scene.m3d_live_saved
        if saved and scene.name not in _live:
            take_over(scene)
            _live[scene.name] = saved
        elif not saved and scene.name in _live:
            give_back(scene, json.loads(_live.pop(scene.name)))


# -----------------------------------------------------------------------------
# UI

def draw_live(layout, context):
    """Modeling Status Line: "Live: Sword_high" and a button that ends it, while a surface is live."""
    surface = context.scene.m3d_live_surface
    if surface is not None:
        row = layout.row(align=True)
        row.label(text="Live: " + surface.name, icon='SNAP_FACE')
        row.operator("m3d.hp_make_not_live", text="", icon='X')


def draw_quad_hint(layout, context):
    """Under the tools of the Modeling Toolkit: Quad Draw snaps onto a live surface, so there should be one."""
    if context.scene.m3d_live_surface is None:
        row = layout.row(align=True)
        row.label(text="Quad Draw: Make Live first", icon='INFO')
        if surface_for(context) not in (None, context.active_object):   # (a mesh can't be live while you edit it)
            row.operator("m3d.hp_make_live", text="", icon='SNAP_FACE')
    elif M3D_OT_hp_conform.poll(context):
        layout.operator("m3d.hp_conform", icon='MOD_SHRINKWRAP')


classes = (
    M3D_OT_hp_make_live,
    M3D_OT_hp_make_not_live,
    M3D_OT_hp_new_low,
    M3D_OT_hp_auto_low,
    M3D_OT_hp_conform,
    M3D_OT_retopo_quads,
    M3D_OT_quad_add,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    define_quad_add()
    bpy.types.Scene.m3d_live_surface = PointerProperty(
        type=bpy.types.Object, poll=lambda _self, ob: ob.type == 'MESH',
        description="The mesh that new points snap onto while you draw a low poly (Make Live)")
    bpy.types.Scene.m3d_live_saved = StringProperty(options={'HIDDEN'}, description="The settings from before Make Live")
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update)
    bpy.app.handlers.load_post.append(_load_post)
    bpy.app.handlers.undo_post.append(_undo_post)
    bpy.app.handlers.redo_post.append(_undo_post)


def unregister():
    bpy.app.handlers.redo_post.remove(_undo_post)
    bpy.app.handlers.undo_post.remove(_undo_post)
    bpy.app.handlers.load_post.remove(_load_post)
    bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update)
    del bpy.types.Scene.m3d_live_saved
    del bpy.types.Scene.m3d_live_surface
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
