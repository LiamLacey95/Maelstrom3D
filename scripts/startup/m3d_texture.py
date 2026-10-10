# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Texture workspace (F4) for Maelstrom3D: the brush tray (left), the dock pages (Layers, Brush, Library, Bake, Export,
Display), the Texture Status Line, shelf items, paint channels, Bake and Export, and the save handler that keeps
painted images.

The layout is built by tools/m3d/build_startup.py (phase3_texture), the tabs are DOCK_TABS['TEXTURE'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py. Brush, stroke, falloff and texture controls are Blender's own
panel classes re-used on the pages. A channel is a paint slot of the active material (Base Color, Roughness,
Metallic, Normal, Height, Emission). The Layers tab is the layer stack (data, node chains and operators: m3d_layers.py);
a material without layers works on its paint slots directly, and gets its slots as the bottom layer on the first layer
operation. The Library tab (materials, mask presets, brushes, alphas, your own items) is m3d_library.py.
"""

import colorsys
import os
from contextlib import ExitStack, contextmanager, nullcontext

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup
from bl_ui.properties_paint_common import (
    BrushSelectPanel, ClonePanel, ColorPalettePanel, DisplayPanel, FalloffPanel, SmoothStrokePanel,
    StrokePanel, TextureMaskPanel, UnifiedPaintPanel, brush_settings, brush_settings_advanced, brush_texture_settings)
from mathutils import Vector

import m3d_layers as L
import m3d_masks as MK
import m3d_pair
import m3d_uv
from m3d_layers import (CHANNEL_BY_ID, CHANNEL_ITEMS, CHANNELS, active_layer, entry_of, pixels_of, principled_of,
                        set_channel_space)
from m3d_mode import _button
from m3d_sculpt import brush_tiles, mesh_of, multires_of, reason, split_props, viewport
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Brushes

BRUSH_ASSET = "brushes/essentials_brushes-mesh_texture.blend/Brush/"
# (label, asset name): the tray grid and the Paint shelf
BRUSHES = (
    ("Paint Soft", "Paint Soft"), ("Paint Hard", "Paint Hard"), ("Airbrush", "Airbrush"), ("Blur", "Blur"),
    ("Smear", "Smear"), ("Clone", "Clone"), ("Fill", "Fill"), ("Erase Soft", "Erase Soft"),
    ("Erase Hard", "Erase Hard"), ("Mask", "Mask"),
)
# The Library tab adds the pressure and pixel art variants.
MORE_BRUSHES = tuple((name, name) for name in (
    "Paint Soft Pressure", "Paint Hard Pressure", "Erase Hard Pressure", "Paint Pixel Art", "Erase Pixel Art"))


def brush_props(name):
    return {"asset_library_type": 'ESSENTIALS', "relative_asset_identifier": BRUSH_ASSET + name}


def brush_item(label, name):
    """Brush button for a shelf (the optional fourth entry is the button text)."""
    return ("brush.asset_activate", 'NONE', brush_props(name), label)


# -----------------------------------------------------------------------------
# Channels: paint slots of the active material (or, with layers, channels of the stack: m3d_layers.py)

SIZES = [(str(n), "%d px" % n, "") for n in (64, 128, 256, 512, 1024, 2048, 4096)]


def channel_of(mat, image):
    """Channel an image of `mat` feeds, by following the image node's link (Normal Map -> Normal, Bump -> Height);
    images created here also remember it (with layers the stored channel is the answer)."""
    for node in () if mat.m3d_layers or not mat.node_tree else mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image == image:
            ch = L.node_channel(node)
            if ch:
                return ch
    stored = image.get("m3d_channel")
    return stored if stored in CHANNEL_BY_ID else None


def paint_slots(mat):
    """[(slot index, image, channel id or None)] of the material's paint slots."""
    if mat is None:
        return []
    return [(i, img, channel_of(mat, img)) for i, img in enumerate(mat.texture_paint_images)]


def channel_slots(mat):
    """{channel id: (slot index, image)}: the first slot of each channel (with layers: where each channel is painted)."""
    if mat.m3d_layers:
        return L.stack_slots(mat)
    found = {}
    for i, img, ch in paint_slots(mat):
        if ch and ch not in found:
            found[ch] = (i, img)
    return found


def active_channel(mat):
    """Channel id of the active paint slot (with layers: the channel being painted), or None."""
    if mat.m3d_layers:
        return mat.m3d_channel
    slots = paint_slots(mat)
    return slots[mat.paint_active_slot][2] if slots and mat.paint_active_slot < len(slots) else None


def select_channel(mat, ch_id):
    """Paint a channel the material already has."""
    if mat.m3d_layers:
        mat.m3d_channel = ch_id
        L.sync_target(bpy.context, mat, True)
    else:
        mat.paint_active_slot = channel_slots(mat)[ch_id][0]


def add_emission_slot(ob, mat, name, size):
    """Emission has no slot type in Blender: a black image feeding Emission Color (strength 1)."""
    bsdf = principled_of(mat)
    if bsdf is None:
        return None
    image = bpy.data.images.new(name, size, size, alpha=False)
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.location = (bsdf.location.x - 400, bsdf.location.y - 1100)
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    mat.node_tree.nodes.active = tex
    bpy.context.view_layer.update()   # Refreshes the material's paint slots.
    return image


def ensure_channel(context, ob, ch):
    """Make `ch` the active paint slot of the active material, adding the slot first. Returns its image, or None.
    With layers the active layer gets the channel (and its image, once)."""
    mat = ob.active_material
    if mat.m3d_layers:
        return L.paint_channel(context, ob, ch)
    found = channel_slots(mat)
    if ch.id in found:
        mat.paint_active_slot = found[ch.id][0]
        return found[ch.id][1]
    size = int(context.scene.m3d_tex.resolution)
    name = "%s_%s" % (ob.name, ch.label.replace(" ", ""))
    before = set(mat.texture_paint_images)
    if ch.slot_type:
        bpy.ops.paint.add_texture_paint_slot(
            type=ch.slot_type, slot_type='IMAGE', name=name, width=size, height=size, color=ch.color,
            alpha=ch.id == 'BASE_COLOR', float=False)
    else:
        image = add_emission_slot(ob, mat, name, size)
        if image is None:
            return None
    images = [img for img in mat.texture_paint_images if img not in before]
    if not images:
        return None
    set_channel_space(images[0], ch)
    mat.paint_active_slot = list(mat.texture_paint_images).index(images[0])
    return images[0]


# -----------------------------------------------------------------------------
# What a mesh needs before it can be painted, baked or exported

def missing(context):
    """What the active mesh still needs, in the order the gates list it."""
    ob = mesh_of(context)
    if ob is None:
        return ['MESH']
    out = []
    if m3d_pair.big_note(context):
        out.append('BIG')
    if not ob.data.uv_layers:
        out.append('UV')
    if ob.active_material is None:
        out.append('MATERIAL')
    if m3d_uv.CHECKER in ob:
        out.append('CHECKER')
    if ob.mode != 'TEXTURE_PAINT':
        out.append('MODE')
    return out


NEEDS = {None: (), 'MESH': ('MESH',), 'PAINT': ('MESH', 'BIG', 'UV', 'MATERIAL', 'CHECKER', 'MODE'),
         'BAKE': ('MESH', 'UV'), 'EXPORT': ('MESH', 'MATERIAL')}
# need -> (message, button, icon, operator, properties)
FIXES = {
    'MESH': ("Select a mesh to paint", "Add Cube", 'MESH_CUBE', "m3d.add_primitive", {"kind": 'CUBE'}),
    'UV': ("This mesh has no UVs", "Auto Unwrap", 'MOD_UVPROJECT', "m3d.tex_unwrap", {}),
    'MATERIAL': ("This mesh has no material", "Add Material", 'MATERIAL', "m3d.tex_add_material", {}),
    'CHECKER': ("The checker map is on: turn it off to paint", "Checker Off", 'TEXTURE', "m3d.uv_checker", {}),
    'MODE': ("Enter Texture Paint Mode to paint", "Texture Paint Mode", 'TPAINT_HLT', "object.mode_set",
             {"mode": 'TEXTURE_PAINT'}),
}


def needed(context, need):
    """What the active mesh still needs for `need`. The Bake tab of a mesh in a bake group does not ask for UVs: it bakes
    the group's low polys, which say themselves when they have none."""
    ob = mesh_of(context)
    skip = {'UV'} if need == 'BAKE' and m3d_pair.grouped(ob) else set()
    return [key for key in missing(context) if key in NEEDS[need] and key not in skip]


def ready(context, need):
    return not needed(context, need)


def draw_fixes(layout, context, need):
    col = layout.column(align=True)
    for key in needed(context, need):
        if key == 'BIG':   # a huge mesh stays in Object Mode here: the message says which mesh to pick instead
            m3d_pair.draw_note(col, m3d_pair.big_note(context))
            continue
        text, label, icon, idname, props = FIXES[key]
        col.label(text=text)
        _button(col, context, label, idname, icon, props)


# -----------------------------------------------------------------------------
# Settings

class M3D_TexSettings(PropertyGroup):
    """Texture workspace options (Scene.m3d_tex): new slot size and the Export tab."""
    resolution: EnumProperty(name="Resolution", default='2048', items=SIZES,
                             description="Size of new paint slots (bigger images use more memory)")
    export_preset: EnumProperty(name="Preset", default='UNREAL', items=(
        ('GLTF', "glTF", "One .glb file with the mesh, the material and its textures"),
        ('UNREAL', "Unreal", "Base Color, Normal (DirectX), packed ORM (Occlusion, Roughness, Metallic), Emissive"),
        ('UNITY', "Unity", "Albedo, Normal, Metallic with Smoothness in alpha, Occlusion, Emission")))
    export_folder: StringProperty(name="Folder", subtype='DIR_PATH', default="//textures/",
                                  options={'PATH_SUPPORTS_BLEND_RELATIVE'}, description="Where the files are written")
    export_size: EnumProperty(name="Size", default='SAME', items=(
        ('SAME', "Same as Paint", "Keep the size of each paint image"), *SIZES),
        description="Size of the exported images")
    export_bake_meshes: BoolProperty(
        name="Bake meshes", default=False,
        description="Also write the low polys and the high polys of the groups of this texture set as two FBX files "
                    "(<name>_low.fbx, <name>_high.fbx) with the meshes named Part_low and Part_high, for tools that match by name")
    export_files: StringProperty(description="Files of the last export, separated by |")


class M3D_BakeSettings(PropertyGroup):
    """Bake options of an object (Object.m3d_bake): the low-poly mesh the maps are baked onto."""
    high: PointerProperty(
        name="High Poly", type=bpy.types.Object, description="Mesh the detail is baked from (empty: bake the mesh itself)",
        poll=lambda self, ob: ob.type == 'MESH' and ob != self.id_data)
    use_normal: BoolProperty(name="Normal", default=True, description="Tangent space normal map")
    use_ao: BoolProperty(name="AO", default=True, description="Ambient occlusion")
    use_curvature: BoolProperty(name="Curvature", default=False,
                                description="Convex edges light, concave ones dark (needs enough polygons)")
    use_position: BoolProperty(name="Position", default=False, description="Position within the mesh's bounds")
    use_thickness: BoolProperty(name="Thickness", default=False,
                                description="How thick the mesh is (closed meshes only)")
    use_id: BoolProperty(name="ID", default=False,
                         description="One flat colour for each material of the high poly (for each mesh when they have one material): "
                                     "pick a part of the model by its colour in a mask")
    resolution: EnumProperty(name="Resolution", default='1024', items=SIZES)
    margin: IntProperty(name="Margin", default=16, min=0, max=64, subtype='PIXEL',
                        description="Pixels the baked detail is extended past the UV shells")
    extrusion: FloatProperty(name="Extrusion", default=0.02, min=0.0, soft_max=1.0, unit='LENGTH',
                             description="Distance the rays start from the low-poly surface")
    ray_distance: FloatProperty(name="Max Ray Distance", default=0.0, min=0.0, soft_max=1.0, unit='LENGTH',
                                description="Longest distance a ray travels to the high-poly mesh (0: no limit)")
    samples: IntProperty(name="Samples", default=32, min=1, soft_max=512,
                         description="Samples for ambient occlusion and thickness")
    thickness_distance: FloatProperty(name="Thickness Distance", default=0.25, min=0.001, soft_max=10.0, unit='LENGTH',
                                      description="Where the mesh is thicker than this the map is white, where it is thinner "
                                      "it gets darker")
    multires_level: IntProperty(name="Low Level", default=0, min=0, soft_max=6,
                                description="Multires level the detail is baked onto (0: the base mesh). The levels above it "
                                            "are the detail")
    use_multires_normal: BoolProperty(name="Normal", default=True, description="Tangent space normal map of the Multires detail")
    use_multires_displacement: BoolProperty(
        name="Displacement", default=False, description="How far the Multires detail is from the low level (grey is no distance)")
    baked: StringProperty(description="Maps of the last bake, separated by |")


# -----------------------------------------------------------------------------
# Safety: painted images are saved or packed with the file

def modified_images():
    skip = {m3d_uv.CHECKER, L.SCRATCH}
    return [i for i in bpy.data.images if i.is_dirty and i.source in {'GENERATED', 'FILE'} and i.name not in skip]


def save_images():
    """Write every changed image to its file, or pack it into the .blend when it has none. Returns (saved, packed)."""
    saved = packed = 0
    for image in modified_images():
        if image.source == 'FILE' and not image.packed_file and image.filepath_raw:
            try:
                image.save()
                saved += 1
                continue
            except RuntimeError:
                pass   # An unwritable path: keep the work in the file instead.
        image.pack()
        packed += 1
    return saved, packed


@bpy.app.handlers.persistent
def save_pre(*_args):
    save_images()


# -----------------------------------------------------------------------------
# Operators

def paint_mesh(context):
    ob = mesh_of(context)
    return ob if ob is not None and ob.mode == 'TEXTURE_PAINT' and ob.active_material is not None else None


class M3D_OT_tex_channel(Operator):
    """Paint a channel: make it the active paint slot (the slot is added first when the material has none)"""
    bl_idname = "m3d.tex_channel"
    bl_label = "Paint Channel"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(items=CHANNEL_ITEMS)

    @classmethod
    def description(cls, _context, props):
        return "Paint %s (adds the paint slot if the material has none)" % CHANNEL_BY_ID[props.channel].label

    @classmethod
    def poll(cls, context):
        return paint_mesh(context) is not None

    def execute(self, context):
        ob = paint_mesh(context)
        if m3d_uv.CHECKER in ob:
            self.report({'WARNING'}, "Turn the checker map off first")
            return {'CANCELLED'}
        if not ob.data.uv_layers:
            self.report({'WARNING'}, "This mesh has no UVs: use Auto Unwrap")
            return {'CANCELLED'}
        try:
            image = ensure_channel(context, ob, CHANNEL_BY_ID[self.channel])
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        if image is None:
            self.report({'WARNING'}, "Could not add the %s slot" % CHANNEL_BY_ID[self.channel].label)
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_tex_channel_cycle(Operator):
    """Paint the next (or previous) channel the material has"""
    bl_idname = "m3d.tex_channel_cycle"
    bl_label = "Cycle Paint Channel"
    bl_options = {'REGISTER', 'UNDO'}

    delta: IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Paint the %s channel of the material" % ("next" if props.delta > 0 else "previous")

    @classmethod
    def poll(cls, context):
        return paint_mesh(context) is not None

    def execute(self, context):
        mat = paint_mesh(context).active_material
        found = channel_slots(mat)
        order = [ch.id for ch in CHANNELS if ch.id in found]
        if not order:
            self.report({'INFO'}, "No channels yet: add one in the Layers tab")
            return {'CANCELLED'}
        now = active_channel(mat)
        i = (order.index(now) + self.delta) % len(order) if now in order else 0
        select_channel(mat, order[i])
        self.report({'INFO'}, "Painting " + CHANNEL_BY_ID[order[i]].label)
        return {'FINISHED'}


class M3D_OT_tex_add_material(Operator):
    """Give the active mesh a new material (a Principled shader the paint slots plug into)"""
    bl_idname = "m3d.tex_add_material"
    bl_label = "Add Material"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        mat = bpy.data.materials.new(ob.name + "_Material")
        mat.use_nodes = True
        with m3d_pair.quiet(context):   # (a new material is no edit of the mesh: a baked group stays baked)
            if ob.material_slots:
                ob.material_slots[ob.active_material_index].material = mat
            else:
                ob.data.materials.append(mat)
        return {'FINISHED'}


class M3D_OT_tex_unwrap(Operator):
    """Auto Unwrap the active mesh (cut at sharp edges, unfold, lay out), then go back to the mode it was in"""
    bl_idname = "m3d.tex_unwrap"
    bl_label = "Auto Unwrap"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        mode = ob.mode
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            res = bpy.ops.m3d.uv_auto()
        finally:
            bpy.ops.object.mode_set(mode=mode)
        return res


class M3D_OT_tex_save_all(Operator):
    """Save every changed image: to its file, or into the .blend when it has none"""
    bl_idname = "m3d.tex_save_all"
    bl_label = "Save All Images"

    def execute(self, _context):
        saved, packed = save_images()
        self.report({'INFO'}, "%d images saved, %d packed into the file" % (saved, packed))
        return {'FINISHED'}


_view_memory = {}


def channel_view_on(shading):
    return shading.type == 'SOLID' and shading.light == 'FLAT' and shading.color_type == 'TEXTURE'


class M3D_OT_tex_channel_view(Operator):
    """Show the active paint channel alone in the 3D view (flat, no lighting); again to go back to the old view"""
    bl_idname = "m3d.tex_channel_view"
    bl_label = "Channel View"
    bl_options = {'REGISTER', 'UNDO'}

    channel: StringProperty(description="Channel to show (empty: the active one)")

    @classmethod
    def poll(cls, context):
        return viewport(context) is not None

    def execute(self, context):
        shading = viewport(context).shading
        on = channel_view_on(shading)
        if self.channel:
            ob = mesh_of(context)
            found = channel_slots(ob.active_material) if ob is not None and ob.active_material else {}
            if self.channel not in found:
                self.report({'WARNING'}, "No %s channel yet" % CHANNEL_BY_ID[self.channel].label)
                return {'CANCELLED'}
            select_channel(ob.active_material, self.channel)
        if on and not self.channel:
            shading.type, shading.light, shading.color_type = _view_memory.pop("shading", ('MATERIAL', 'STUDIO', 'MATERIAL'))
        elif not on:
            _view_memory["shading"] = (shading.type, shading.light, shading.color_type)
            shading.type, shading.light, shading.color_type = 'SOLID', 'FLAT', 'TEXTURE'
        return {'FINISHED'}


class M3D_OT_tex_apply_material(Operator):
    """Put this material on the active mesh (replacing the active material slot)"""
    bl_idname = "m3d.tex_apply_material"
    bl_label = "Apply Material"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty()

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob, mat = mesh_of(context), bpy.data.materials.get(self.name)
        if mat is None:
            return {'CANCELLED'}
        with m3d_pair.quiet(context):
            if ob.material_slots:
                ob.material_slots[ob.active_material_index].material = mat
            else:
                ob.data.materials.append(mat)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Bake

BAKE_MAPS = (   # (id, label, flag in M3D_BakeSettings)
    ('NORMAL', "Normal", "use_normal"), ('AO', "AO", "use_ao"), ('CURVATURE', "Curvature", "use_curvature"),
    ('POSITION', "Position", "use_position"), ('THICKNESS', "Thickness", "use_thickness"), ('ID', "ID", "use_id"),
)
BAKE_TYPES = {'NORMAL': 'NORMAL', 'AO': 'AO', 'CURVATURE': 'EMIT', 'POSITION': 'POSITION', 'THICKNESS': 'EMIT', 'ID': 'EMIT',
              'WORLDNORMAL': 'EMIT'}   # The last is only for mask effects (Top-down): the world space normal, n * 0.5 + 0.5.


def bake_material(image=None, emission=None, distance=1.0, color=(0.0, 0.0, 0.0)):
    """Temporary material for a bake: an Image Texture node holding `image` (the bake target, active), and for
    Curvature / Thickness an emission shader showing the map (Pointiness, or ambient occlusion from inside), for ID one
    flat `color`."""
    mat = bpy.data.materials.new("m3dBake")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    if emission:
        nodes.clear()
        out, emit = nodes.new("ShaderNodeOutputMaterial"), nodes.new("ShaderNodeEmission")
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
        if emission == 'ID':
            emit.inputs["Color"].default_value = (*color, 1.0)
        elif emission == 'CURVATURE':   # Pointiness is 0.5 on flat areas: widen 0.45-0.55 to the whole range.
            geo, rng = nodes.new("ShaderNodeNewGeometry"), nodes.new("ShaderNodeMapRange")
            rng.inputs["From Min"].default_value, rng.inputs["From Max"].default_value = 0.45, 0.55
            links.new(geo.outputs["Pointiness"], rng.inputs["Value"])
            links.new(rng.outputs["Result"], emit.inputs["Color"])
        elif emission == 'WORLDNORMAL':
            geo, vec = nodes.new("ShaderNodeNewGeometry"), nodes.new("ShaderNodeVectorMath")
            vec.operation = 'MULTIPLY_ADD'
            vec.inputs[1].default_value = vec.inputs[2].default_value = (0.5, 0.5, 0.5)
            links.new(geo.outputs["Normal"], vec.inputs[0])
            links.new(vec.outputs["Vector"], emit.inputs["Color"])
        else:   # Ambient occlusion from inside the mesh: the shorter the way out, the darker.
            ao = nodes.new("ShaderNodeAmbientOcclusion")
            ao.inside, ao.samples = True, 16
            ao.inputs["Distance"].default_value = distance
            links.new(ao.outputs["AO"], emit.inputs["Color"])
    if image:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        nodes.active = tex
    return mat


@contextmanager
def materials_swapped(ob, mat):
    """`mat` on every material slot of `ob` (a slot is added when it has none), or a list of materials, one for each slot;
    the old materials come back after, and the temporary ones are removed."""
    saved = [slot.material for slot in ob.material_slots]
    new = list(mat) if isinstance(mat, (list, tuple)) else [mat] * max(len(saved), 1)
    if saved:
        for slot, m in zip(ob.material_slots, new):
            slot.material = m
    else:
        ob.data.materials.append(new[0])
    try:
        yield
    finally:
        if saved:
            for slot, old in zip(ob.material_slots, saved):
                slot.material = old
        else:
            ob.data.materials.clear()
        for m in set(new):
            bpy.data.materials.remove(m)


def id_materials(colors, image=None):
    """Emission materials in flat colours, one for each of `colors` (for `materials_swapped`); with `image`, each also holds
    the bake target."""
    return [bake_material(image, 'ID', color=color) for color in colors]


def meshes_of(obs):
    """A list of meshes from None, one mesh or a list."""
    return [] if obs is None else [obs] if isinstance(obs, bpy.types.Object) else list(obs)


def texture_set(ob):
    """(name, low polys) of the texture set `ob` is baked into. Low polys of bake groups that share a material share its
    maps: the images are named after the material (Sword_Normal) and every low poly adds its own UV islands to them. Any
    other mesh has maps of its own, named after the mesh (Cube_Normal), which is what files from before bake groups have."""
    mat = ob.active_material
    if m3d_pair.grouped(ob) and ob.m3d_pair.role == 'LOW' and mat is not None and mat.users > 1:
        lows = sorted((o for o in bpy.context.view_layer.objects
                       if o.type == 'MESH' and o.m3d_pair.role == 'LOW' and o.m3d_pair.group and o.active_material == mat),
                      key=lambda o: o.name)
        if len(lows) > 1:
            return mat.name, lows
    return ob.name, [ob]


def bake_owner(ob):
    """The mesh whose Bake tab settings (maps, size, margin, samples) apply to `ob`: the first low poly by name of its
    texture set, for a high poly the first low poly of its group."""
    if m3d_pair.grouped(ob) and ob.m3d_pair.role == 'HIGH':
        lows = m3d_pair.group_of(bpy.context, ob.m3d_pair.group)[0]
        ob = lows[0] if lows else ob
    return texture_set(ob)[1][0]


def map_image(ob, label):
    """The baked map `label` ("AO") of `ob`: the texture set's image, else the one named after the mesh, else None."""
    images = bpy.data.images
    image = images.get("%s_%s" % (texture_set(ob)[0], label))
    return image if image is not None else images.get("%s_%s" % (ob.name, label))


def rename_maps(ob, old, new):
    """The low poly `ob` was renamed from `old` to `new`: its maps (named after the mesh) and the records of them follow."""
    if old == new:
        return
    images = bpy.data.images
    for label in dict.fromkeys([*(label for _key, label, _flag in BAKE_MAPS), *MK.MAP_LABELS.values(), *(m[1] for m in MULTIRES_MAPS)]):
        image = images.get("%s_%s" % (old, label))
        if image is not None and images.get("%s_%s" % (new, label)) is None:
            image.name = "%s_%s" % (new, label)
    for image in images:
        parts = image.get("m3d_parts")
        if parts and old in parts.split("|"):
            image["m3d_parts"] = "|".join(new if name == old else name for name in parts.split("|"))
    ob.m3d_bake.baked = "|".join(("%s_%s" % (new, name[len(old) + 1:]) if name.startswith(old + "_") else name)
                                 for name in ob.m3d_bake.baked.split("|") if name)


def bake_image(name, label, size, float_buffer):
    """The image a map is baked into: the earlier one of this name (resized) or a new one."""
    name = "%s_%s" % (name, label)
    image = bpy.data.images.get(name)
    if image is None or image.source != 'GENERATED':
        image = bpy.data.images.new(name, size, size, alpha=False, float_buffer=float_buffer, is_data=True)
        image.use_half_precision = False   # (float maps keep all 32 bits, in the file too)
    elif tuple(image.size) != (size, size):
        image.generated_width = image.generated_height = size   # (scale() would not stick: the bake clears to this size)
        image["m3d_parts"] = ""
    image.use_fake_user = True   # Nothing uses it yet: keep it in the file.
    if image.colorspace_settings.name != 'Non-Color':   # (setting it drops the pixels of a generated image, even to the same value)
        image.colorspace_settings.name = 'Non-Color'
    image["m3d_bake"] = label
    return image


def forget_parts(name, labels):
    """The next bake into the maps `name`_<label> starts them over (the first low poly clears the image)."""
    for label in labels:
        image = bpy.data.images.get("%s_%s" % (name, label))
        if image is not None:
            image["m3d_parts"] = ""


def world_bounds(obs):
    """(min, max) corner of the bounding boxes of a mesh or a list of them, in world space."""
    corners = np.array([o.matrix_world @ Vector(c) for o in meshes_of(obs) for c in o.bound_box])
    return corners.min(axis=0), corners.max(axis=0)


def normalise_position(image, obs, owner):
    """Position bakes world coordinates: scale them to 0-1 within the bounds of the mesh(es) `obs` so any image format
    keeps them. The bounds and the inverse matrix of `owner` (the baked mesh) stay with the image: mask effects turn the
    map back into object space coordinates with them."""
    lo, hi = world_bounds(obs)
    image["m3d_bounds"] = [float(x) for x in (*lo, *hi)]
    image["m3d_inv"] = [float(x) for row in owner.matrix_world.inverted() for x in row]
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    rgba = px.reshape(-1, 4)
    rgba[:, :3] = np.clip((rgba[:, :3] - lo) / np.maximum(hi - lo, 1e-6), 0.0, 1.0)
    rgba[:, 3] = 1.0
    image.pixels.foreach_set(px)
    image.update()


RENDERED = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME', 'GREASEPENCIL'}   # object types that cast shadows


@contextmanager
def bake_scene(context, ob, highs=None, hide=(), cycles=True):
    """Cycles on (the bake needs it; `cycles` False: the engine stays), the low-poly mesh active and the high-poly meshes
    `highs` (one, a list or None) selected with it, Object Mode; `hide`: meshes that are not rendered meanwhile (Cycles
    bakes ambient occlusion against everything it renders, except the low poly itself). Everything is put back afterwards,
    also after an error. A mesh that is hidden is shown inside: the redraw does not happen before it is hidden again."""
    scene, layer = context.scene, context.view_layer
    highs = meshes_of(highs)
    objs = [ob, *highs]
    if any(o.name not in layer.objects for o in objs):
        raise RuntimeError("Both meshes have to be in the view layer")
    active = layer.objects.active
    state = dict(engine=scene.render.engine, samples=scene.cycles.samples, mode=active.mode if active else 'OBJECT',
                 active=active, selected=[o for o in layer.objects if o.select_get()],
                 flags=[(o, o.hide_get(), o.hide_viewport, o.hide_render, o.hide_select) for o in objs],
                 hidden=[(o, o.hide_render) for o in hide])
    if state["mode"] != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    try:
        for o in hide:
            o.hide_render = True
        for o in objs:   # (a mesh that is parked is shown for the bake and hidden again before anything is drawn)
            o.hide_viewport = o.hide_render = o.hide_select = False
            o.hide_set(False)
        for o in state["selected"]:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        layer.objects.active = ob
        if cycles:
            scene.render.engine = 'CYCLES'
        yield
    finally:
        scene.render.engine, scene.cycles.samples = state["engine"], state["samples"]
        for o, hide_render in state["hidden"]:
            o.hide_render = hide_render
        for o, hidden, hide_viewport, hide_render, hide_select in state["flags"]:
            o.hide_set(hidden)
            o.hide_viewport, o.hide_render, o.hide_select = hide_viewport, hide_render, hide_select
        for o in objs:
            o.select_set(False)
        for o in state["selected"]:
            o.select_set(True)
        layer.objects.active = state["active"]
        if state["mode"] != 'OBJECT' and state["active"] is not None:
            try:
                bpy.ops.object.mode_set(mode=state["mode"])
            except RuntimeError:
                pass   # (the mode can't be entered any more: this must not hide the error that got us here)


def id_color(i):
    """The i-th ID colour: hues a golden ratio apart, so that any run of them is far apart; the ninth to sixteenth are darker."""
    return colorsys.hsv_to_rgb((i * 0.61803398875) % 1.0, 0.8, 1.0 - 0.4 * ((i // 8) % 2))


def id_plan(obs):
    """({name: colour}, {mesh name: [colour of each material slot]}) for the ID map of the meshes `obs`: a colour for each
    material when they have more than one between them, else a colour for each mesh. The colours follow the names in order, so
    a new bake gives the same ones; a slot without a material is black (the colour of the background)."""
    mats = sorted({slot.material.name for o in obs for slot in o.material_slots if slot.material})
    colors = {name: id_color(i) for i, name in enumerate(mats if len(mats) > 1 else sorted(o.name for o in obs))}

    def slots(o):
        if len(mats) > 1:
            return [colors[slot.material.name] if slot.material else (0.0, 0.0, 0.0) for slot in o.material_slots] or [(0.0, 0.0, 0.0)]
        return [colors[o.name]] * max(len(o.material_slots), 1)

    return colors, {o.name: slots(o) for o in obs}


def bake_maps(context, ob, high, s, maps, name=None, extrusion=None, ray_distance=None, cage=None, others=(), normalise=True):
    """Bake the ticked maps of `ob` (from `high`, a mesh or a list, when set) into images named `name`_<Map> (default: the
    name of `ob`). `extrusion`, `ray_distance` and `cage` (a mesh with the faces of `ob`) are the group's, `s` has the
    rest. `others`: names of the other low polys that share the images: their islands stay, the image is cleared only
    when it holds none of them. `normalise`: Position is scaled to 0-1 (not when more low polys follow). Returns the images."""
    size, images, highs = int(s.resolution), [], meshes_of(high)
    name = name or ob.name
    for key, label, _flag in maps:
        # The Position pass adds up its samples instead of averaging them: one sample, and it is exact anyway. The ID colours
        # are flat: one sample keeps the edges between them hard (the margin only extends them).
        context.scene.cycles.samples = 1 if key in {'POSITION', 'ID'} else s.samples
        image = bake_image(name, label, size, key in {'POSITION', 'WORLDNORMAL'})
        held = set(filter(None, str(image.get("m3d_parts", "")).split("|"))) & (set(others) - {ob.name})
        emission = key if BAKE_TYPES[key] == 'EMIT' else None
        ids = id_plan(highs or [ob]) if key == 'ID' else None   # (colours of the high polys, or of the mesh itself)
        # Without a high-poly mesh the low-poly one carries both the emission and the bake target.
        if ids is not None:
            target = bake_material(image) if highs else id_materials(ids[1][ob.name], image)
        else:
            target = bake_material(image, None if highs else emission, s.thickness_distance)
        with ExitStack() as stack:
            stack.enter_context(materials_swapped(ob, target))
            if highs and emission:
                for h in highs:
                    stack.enter_context(materials_swapped(h, id_materials(ids[1][h.name]) if ids is not None else
                                                          bake_material(emission=emission, distance=s.thickness_distance)))
            bpy.ops.object.bake(
                type=BAKE_TYPES[key], margin=s.margin, use_selected_to_active=bool(highs),
                cage_extrusion=s.extrusion if extrusion is None else extrusion,
                max_ray_distance=s.ray_distance if ray_distance is None else ray_distance, normal_space='TANGENT',
                use_cage=cage is not None, cage_object=cage.name if cage is not None else "",
                use_clear=not held, target='IMAGE_TEXTURES', save_mode='INTERNAL')
        image["m3d_parts"] = "|".join(sorted({*held, ob.name}))
        if ids is not None:   # (which colour is which, for the Color ID mask)
            prefix = ob.m3d_pair.group + ": " if m3d_pair.grouped(ob) else ""
            image["m3d_ids"] = {**(image["m3d_ids"].to_dict() if held and "m3d_ids" in image else {}),
                                **{prefix + n: list(c) for n, c in ids[0].items()}}
        if key == 'POSITION' and normalise:
            normalise_position(image, highs or ob, ob)
        image["m3d_map"] = size   # Baked at this size: mask effects reuse it until the resolution changes.
        image["m3d_stamp"] = MK.new_uid()
        images.append(image)
    return images


def ensure_maps(context, ob, keys, force=False):
    """The baked maps (MK.MAP_LABELS keys) mask effects read, as {key: image}: the ones the mesh has at the Bake tab's
    resolution are reused, the others are baked (together, in one go; `force`: all of them again). The low poly of a bake
    group bakes from its group, together with the other low polys of its texture set."""
    in_group = m3d_pair.grouped(ob) and ob.m3d_pair.role == 'LOW'
    s = bake_owner(ob).m3d_bake
    size = int(s.resolution)
    todo = []
    for key in keys:
        image = map_image(ob, MK.MAP_LABELS[key])
        if force or image is None or image.get("m3d_map") != size:
            todo.append((key, MK.MAP_LABELS[key], None))
    if todo:
        wm = context.window_manager
        wm.progress_begin(0, 1)
        try:
            if in_group:
                import m3d_bakegroups
                m3d_bakegroups.bake_set(context, texture_set(ob)[1], todo)
            else:
                with bake_scene(context, ob, s.high):
                    bake_maps(context, ob, s.high, s, todo)
        finally:
            wm.progress_end()
        name = texture_set(ob)[0]
        s.baked = "|".join(dict.fromkeys([*filter(None, s.baked.split("|")), *("%s_%s" % (name, label) for _k, label, _f in todo)]))
    return {key: map_image(ob, MK.MAP_LABELS[key]) for key in keys}


def multires_ready(ob):
    """A low poly, or a mesh without a role, that has Multires levels and no high poly: the Bake tab offers to bake from them."""
    mod = multires_of(ob) if m3d_pair.is_mesh(ob) else None
    if mod is None or mod.total_levels < 1 or ob.m3d_pair.role == 'HIGH':
        return False
    if m3d_pair.grouped(ob):
        return not m3d_pair.group_of(bpy.context, ob.m3d_pair.group)[1]
    return ob.m3d_bake.high is None


MULTIRES_MAPS = (   # (id, label, type of Blender's multires baker, flag in M3D_BakeSettings)
    ('NORMAL', "Normal", 'NORMALS', "use_multires_normal"),
    ('DISPLACEMENT', "Displacement", 'DISPLACEMENT', "use_multires_displacement"),
)


@contextmanager
def multires_settings(bake, **values):
    """The multires settings of the scene (`scene.render.bake`: use_multires, type, margin, use_clear ...) are `values`
    inside; everything that is named here is put back after, also after an error."""
    saved = {name: getattr(bake, name) for name in values}
    try:
        for name, value in values.items():
            setattr(bake, name, value)
        yield bake
    finally:
        for name, value in saved.items():
            setattr(bake, name, value)


def bake_multires(context, ob, s, kinds, name, others=()):
    """Bake the maps `kinds` (entries of MULTIRES_MAPS) of `ob` from its Multires levels with Blender's own baker: what the
    levels above the Low Level (`ob.m3d_bake`) add to it. The images are named `name`_<Map> like the other maps; `s` has
    the size and the margin, `others` is as in `bake_maps`. The render settings and the level of the modifier are put back,
    also after an error. Returns the images."""
    mod, size, images = multires_of(ob), int(s.resolution), []
    level = mod.levels
    try:
        with bake_scene(context, ob, cycles=False), multires_settings(
                context.scene.render.bake, use_multires=True, type='NORMALS', margin=s.margin, use_clear=True,
                use_lores_mesh=False) as bake:
            mod.levels = min(ob.m3d_bake.multires_level, mod.total_levels - 1)
            for key, label, bake_type, _flag in kinds:
                image = bake_image(name, label, size, key == 'DISPLACEMENT')
                held = set(filter(None, str(image.get("m3d_parts", "")).split("|"))) & (set(others) - {ob.name})
                bake.type, bake.use_clear = bake_type, not held
                with materials_swapped(ob, bake_material(image)):
                    bpy.ops.object.bake_image()
                image["m3d_parts"] = "|".join(sorted({*held, ob.name}))
                image["m3d_map"] = size
                image["m3d_stamp"] = MK.new_uid()
                images.append(image)
    finally:
        mod.levels = level
    return images


class M3D_OT_tex_bake_multires(Operator):
    """Bake the detail of the Multires levels of the active mesh above its Low Level into a normal map and / or a displacement
    map, with Blender's own Multires baker (no high poly needed). The mesh needs UVs, and the Multires modifier has to be the
    last modifier"""
    bl_idname = "m3d.tex_bake_multires"
    bl_label = "Bake Multires"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return multires_ready(mesh_of(context))

    def execute(self, context):
        ob = mesh_of(context)
        kinds = [m for m in MULTIRES_MAPS if getattr(ob.m3d_bake, m[3])]
        if not kinds:
            self.report({'WARNING'}, "Tick Normal or Displacement")
            return {'CANCELLED'}
        name, every = texture_set(ob)
        owner = bake_owner(ob).m3d_bake
        wm = context.window_manager
        wm.progress_begin(0, 1)
        try:
            with m3d_pair.quiet(context):
                images = bake_multires(context, ob, owner, kinds, name, [o.name for o in every])
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            wm.progress_end()
        owner.baked = "|".join(dict.fromkeys([*filter(None, owner.baked.split("|")), *(image.name for image in images)]))
        if m3d_pair.grouped(ob):
            import m3d_bakegroups
            m3d_bakegroups.bake_groups_done(context, m3d_pair.all_groups(context), [ob.m3d_pair.group])
        self.report({'INFO'}, "Baked %s from Multires at %s px" % (", ".join(m[1] for m in kinds), owner.resolution))
        return {'FINISHED'}


class M3D_OT_tex_bake_pick(Operator):
    """Use the other selected mesh as the high-poly mesh of the active one"""
    bl_idname = "m3d.tex_bake_pick"
    bl_label = "Use Selected as High Poly"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        other = next((o for o in context.selected_objects if o.type == 'MESH' and o != ob), None)
        if other is None:
            self.report({'WARNING'}, "Select the high-poly mesh as well (the low-poly one stays active)")
            return {'CANCELLED'}
        ob.m3d_bake.high = other
        return {'FINISHED'}


class M3D_OT_tex_bake(Operator):
    """Bake the ticked maps of the active mesh into images (from the high-poly mesh when set; a mesh in a bake group bakes its
    group). Cycles is used for the bake and switched back; the mesh's materials are not changed"""
    bl_idname = "m3d.tex_bake"
    bl_label = "Bake"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and (bool(ob.data.uv_layers) or m3d_pair.grouped(ob))

    def execute(self, context):
        ob = mesh_of(context)
        if m3d_pair.grouped(ob):
            if not bpy.ops.m3d.bg_bake.poll():
                self.report({'WARNING'}, "%s has no low poly to bake onto" % ob.m3d_pair.group)
                return {'CANCELLED'}
            return bpy.ops.m3d.bg_bake('EXEC_DEFAULT', group=ob.m3d_pair.group)
        s = ob.m3d_bake
        maps = [m for m in BAKE_MAPS if getattr(s, m[2])]
        if not maps:
            self.report({'WARNING'}, "Tick at least one map")
            return {'CANCELLED'}
        wm = context.window_manager
        wm.progress_begin(0, 1)
        try:
            with bake_scene(context, ob, s.high):
                images = bake_maps(context, ob, s.high, s, maps)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            wm.progress_end()
        s.baked = "|".join(img.name for img in images)
        self.report({'INFO'}, "Baked %s at %s px" % (", ".join(m[1] for m in maps), s.resolution))
        return {'FINISHED'}


class M3D_OT_tex_show_image(Operator):
    """Show an image in the 2D view"""
    bl_idname = "m3d.tex_show_image"
    bl_label = "Show Image"
    bl_options = {'INTERNAL'}

    name: StringProperty()

    def execute(self, context):
        image = bpy.data.images.get(self.name)
        areas = [a for a in context.screen.areas if a.type == 'IMAGE_EDITOR']
        if image is None or not areas:
            return {'CANCELLED'}
        max(areas, key=lambda a: a.width * a.height).spaces.active.image = image
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Export

def constant(mat, socket, default):
    bsdf = principled_of(mat)
    return float(bsdf.inputs[socket].default_value) if bsdf is not None else default


def write_png(path, array, srgb, alpha=False):
    """Save a (size, size, 4) array as a PNG. Pixels are stored as they are (no colour conversion)."""
    size = array.shape[0]
    image = bpy.data.images.new("m3dExport", size, size, alpha=alpha, is_data=not srgb)
    try:
        image.pixels.foreach_set(np.ascontiguousarray(array, np.float32).ravel())
        image.filepath_raw, image.file_format = path, 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


def export_folder(context):
    """The folder of the Export tab, made when it is not there (it may start with // once the file is saved)."""
    s = context.scene.m3d_tex
    if s.export_folder.startswith("//") and not bpy.data.filepath:
        raise RuntimeError("Save the file first, or pick a folder that does not start with //")
    folder = bpy.path.abspath(s.export_folder)
    os.makedirs(folder, exist_ok=True)
    return folder


def export_textures(context, ob):
    """Write the active mesh's channels in the format of the Export preset. Returns the files written. With layers,
    each channel is the flattened visible stack (the layers are not touched)."""
    s = context.scene.m3d_tex
    folder = export_folder(context)
    name = bpy.path.clean_name(ob.name)
    mat = ob.active_material
    stacked = bool(mat.m3d_layers)
    if stacked:
        L.prepare(context, mat)
    found = {ch: img for ch, (_i, img) in channel_slots(mat).items()}
    present = set(L.content_channels(mat)) if stacked else set(found)
    native = L.stack_size(mat) if stacked else max((max(img.size) for img in found.values()), default=0)
    if s.export_preset == 'GLTF':
        return [export_gltf(context, ob, os.path.join(folder, name + ".glb"), native or 1024)]
    size = int(s.export_size) if s.export_size != 'SAME' else native or 1024
    ao_image = bpy.data.images.get(ob.name + "_AO")
    ones = np.ones((size, size, 4), np.float32)

    def pixels(channel):
        if channel not in present:
            return None
        return L.flatten_channel(mat, channel, size) if stacked else pixels_of(found[channel], size)

    def map_of(channel, socket, default):
        px = pixels(channel)
        return px if px is not None else ones * np.float32(constant(mat, socket, default))

    unreal = s.export_preset == 'UNREAL'
    names = dict(base=("T_%s_BC" if unreal else "%s_Albedo"), normal=("T_%s_N" if unreal else "%s_Normal"),
                 pack=("T_%s_ORM" if unreal else "%s_MetallicSmoothness"), emit=("T_%s_E" if unreal else "%s_Emission"),
                 ao="%s_Occlusion")
    paths = []

    def out(key, array, srgb, alpha=False):
        path = os.path.join(folder, names[key] % name + ".png")
        write_png(path, array, srgb, alpha)
        paths.append(path)

    if 'BASE_COLOR' in present:
        out("base", pixels('BASE_COLOR'), True, alpha=True)
    if 'NORMAL' in present:
        normal = pixels('NORMAL').copy()
        if unreal:
            normal[..., 1] = 1.0 - normal[..., 1]   # Unreal reads normal maps with the green channel flipped.
        out("normal", normal, False)
    if 'EMISSION' in present:
        out("emit", pixels('EMISSION'), True)
    rough, metal = map_of('ROUGHNESS', "Roughness", 0.5), map_of('METALLIC', "Metallic", 0.0)
    ao = pixels_of(ao_image, size) if ao_image is not None else ones
    packed = np.ones((size, size, 4), np.float32)
    if unreal:
        packed[..., 0], packed[..., 1], packed[..., 2] = ao[..., 0], rough[..., 0], metal[..., 0]
    else:   # Metallic in red, smoothness in alpha.
        packed[..., :3] = metal[..., :1]
        packed[..., 3] = 1.0 - rough[..., 0]
    out("pack", packed, False, alpha=not unreal)
    if not unreal and ao_image is not None:
        out("ao", ao, False)
    return paths


def export_gltf(context, ob, path, size):
    """The mesh with its material as a .glb (the glTF exporter reads the paint images from the material; a layer
    stack is exported as a temporary copy of the material with one flattened image per channel)."""
    if not hasattr(bpy.ops.export_scene, "gltf"):
        raise RuntimeError("The glTF exporter is not enabled")
    layer = context.view_layer
    state = [o for o in layer.objects if o.select_get()], layer.objects.active
    for o in state[0]:
        o.select_set(False)
    ob.select_set(True)
    layer.objects.active = ob
    try:
        with m3d_pair.quiet(context), \
                L.flattened_material(ob, ob.active_material, size) if ob.active_material.m3d_layers else nullcontext():
            bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True)
    finally:
        ob.select_set(False)
        for o in state[0]:
            o.select_set(True)
        layer.objects.active = state[1]
    return path


def bake_mesh_set(context, ob):
    """(name, low polys, high polys) that the Bake meshes option writes for the bake group of `ob`: the low polys of its texture
    set with the high polys of their groups, named after the material when the set has several low polys, else after the group.
    None when `ob` has no group with a low poly."""
    lows = m3d_pair.pair_of(context, ob)[0]
    if not lows:
        return None
    name, every = texture_set(lows[0])
    highs = [h for group in dict.fromkeys(o.m3d_pair.group for o in every) for h in m3d_pair.group_of(context, group)[1]]
    return (name if len(every) > 1 else lows[0].m3d_pair.group), every, highs


@contextmanager
def named_for_export(context, obs):
    """The meshes `obs` have the names of the _low / _high style inside (the object and its mesh: Sword_low, Sword_high,
    Sword_high_bolts), so that a tool that matches by name finds the pairs. Their own names come back after."""
    todo = [(ob, new) for ob, new in m3d_pair.renamed(context, 'LOW_HIGH') if ob in obs and ob.library is None]
    old = [(ob, ob.name, ob.data, ob.data.name) for ob, _new in todo]
    with m3d_pair.quiet(context):
        try:
            for ob, new in todo:
                ob.name = new
                if ob.data.users == 1:
                    ob.data.name = new
            yield
        finally:
            for ob, name, data, data_name in reversed(old):
                ob.name, data.name = name, data_name


def export_bake_meshes(context, ob):
    """Write the low polys and the high polys of `bake_mesh_set` as `name`_low.fbx and `name`_high.fbx in the Export folder.
    A high poly that is parked is shown for the export only (never drawn). Returns the files written."""
    if not hasattr(bpy.ops.export_scene, "fbx"):
        raise RuntimeError("The FBX exporter is not enabled")
    name, lows, highs = bake_mesh_set(context, ob)
    folder, paths = export_folder(context), []
    with m3d_pair.quiet(context), named_for_export(context, [*lows, *highs]):
        for suffix, obs in (("low", lows), ("high", highs)):
            if obs:
                path = os.path.join(folder, "%s_%s.fbx" % (bpy.path.clean_name(name), suffix))
                with bake_scene(context, obs[0], obs[1:], cycles=False):
                    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={'MESH'}, bake_anim=False)
                paths.append(path)
    return paths


class M3D_OT_tex_export(Operator):
    """Write the channels of the active mesh as texture files for the chosen engine (Export tab), and with Bake meshes the
    low polys and high polys of its bake groups as FBX files"""
    bl_idname = "m3d.tex_export"
    bl_label = "Export"

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and ob.active_material is not None

    def execute(self, context):
        ob = mesh_of(context)
        if context.scene.m3d_tex.export_bake_meshes and bake_mesh_set(context, ob) is None:
            self.report({'ERROR'}, "Bake meshes needs a mesh of a bake group that has a low poly")
            return {'CANCELLED'}
        try:
            paths = export_textures(context, ob)
            if context.scene.m3d_tex.export_bake_meshes:
                paths += export_bake_meshes(context, ob)
        except (RuntimeError, OSError) as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        context.scene.m3d_tex.export_files = "|".join(paths)
        self.report({'INFO'}, "Exported %d files to %s" % (len(paths), os.path.dirname(paths[0])))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

class _Page(_PagePanel):
    """Panel that needs `need` (see `NEEDS`)."""
    need = 'PAINT'

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.need)


class _BrushPage(_PagePanel):
    """Panel for the active brush; the stock mixin classes (falloff, stroke ...) add their own poll."""
    @classmethod
    def page_poll(cls, context):
        stock = super(_PagePanel, cls)
        return ready(context, 'PAINT') and UnifiedPaintPanel.get_brush_mode(context) is not None and (
            not hasattr(stock, "poll") or stock.poll(context))


def _gate(page, need):
    """The panel a page shows instead of its own when something is missing: what to do next."""
    def draw(self, context):
        draw_fixes(self.layout, context, need)
    return type("PROPERTIES_PT_m3d_tx_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Texture", "bl_options": {'HIDE_HEADER'}, "page": "tex_" + page,
        "page_poll": classmethod(lambda cls, context: not ready(context, need)), "draw": draw})


def paint_settings(context):
    return context.tool_settings.image_paint


# --- Left tray: brushes

class PROPERTIES_PT_m3d_tx_canvas(_Page, Panel):
    page = "tex_brushes"
    bl_label = "Canvas"

    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and not paint_slots(mesh_of(context).active_material)

    def draw(self, context):
        layout = self.layout
        layout.label(text="No paint slots yet")
        layout.prop(context.scene.m3d_tex, "resolution")
        op = layout.operator("m3d.tex_channel", text="Add Base Color", icon='ADD')
        op.channel = 'BASE_COLOR'


class PROPERTIES_PT_m3d_tx_brush(_BrushPage, BrushSelectPanel, Panel):
    page = "tex_brushes"


class PROPERTIES_PT_m3d_tx_grid(_Page, Panel):
    page = "tex_brushes"
    bl_label = "Brushes"

    def draw(self, context):
        brush_tiles(self.layout, context, BRUSH_ASSET, BRUSHES)


class PROPERTIES_PT_m3d_tx_tuning(_Page, Panel):
    page = "tex_brushes"
    bl_label = "Size, Strength and Color"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        settings = paint_settings(context)
        brush = settings.brush
        if brush is None:
            layout.label(text="Pick a brush above")
            return
        col = layout.column()
        UnifiedPaintPanel.prop_unified(col, context, brush, "size", unified_name="use_unified_size", text="Size",
                                       pressure_name="use_pressure_size", slider=True)
        UnifiedPaintPanel.prop_unified(col, context, brush, "strength", unified_name="use_unified_strength",
                                       pressure_name="use_pressure_strength", slider=True)
        if not brush.image_paint_capabilities.has_color:
            return
        UnifiedPaintPanel.prop_unified_color_picker(layout, context, brush, "color")
        row = layout.row(align=True)
        UnifiedPaintPanel.prop_unified_color(row, context, brush, "color", text="")
        UnifiedPaintPanel.prop_unified_color(row, context, brush, "secondary_color", text="")
        row.operator("paint.brush_colors_flip", icon='ARROW_LEFTRIGHT', text="")
        layout.prop(brush, "blend", text="Blend Mode")


class PROPERTIES_PT_m3d_tx_projection(_Page, Panel):
    page = "tex_brushes"
    bl_label = "Stencil and Projection"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ipaint = paint_settings(context)
        col = layout.column(heading="Stencil")
        col.prop(ipaint, "use_stencil_layer", text="Use Stencil")
        if ipaint.use_stencil_layer:
            col.template_ID(ipaint, "stencil_image", new="image.new", open="image.open")
        col = layout.column(heading="Projection")
        col.prop(ipaint, "use_occlude", text="Occlude")
        col.prop(ipaint, "use_backface_culling", text="Backface Culling")
        col.prop(ipaint, "use_normal_falloff", text="Normal Falloff")


class PROPERTIES_PT_m3d_tx_more(_BrushPage, Panel):
    page = "tex_brushes"
    bl_label = "Brush Settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        split_props(self.layout)
        brush_settings(self.layout.column(), context, paint_settings(context).brush, popover=True)


class PROPERTIES_PT_m3d_tx_advanced(_BrushPage, Panel):
    page = "tex_brushes"
    bl_label = "Advanced"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        split_props(self.layout)
        settings = paint_settings(context)
        brush_settings_advanced(self.layout.column(), context, settings, settings.brush, self.is_popover)


# --- Layers: the stack, the active layer, its mask; the channels

def has_active_layer(mat):
    return principled_of(mat) is not None and active_layer(mat) is not None


class PROPERTIES_PT_m3d_tx_stack(_Page, Panel):
    page = "tex_layers"
    bl_label = "Layers"

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mat = ob.active_material
        if len(ob.material_slots) > 1:
            layout.template_list("MATERIAL_UL_matslots", "layers", ob, "material_slots", ob, "active_material_index",
                                 rows=2)
        if principled_of(mat) is None:
            reason(layout, "Layers need a Principled BSDF in the material")
            return
        layer = active_layer(mat)
        row = layout.row(align=True)
        row.operator("m3d.layer_add", text="Paint Layer", icon='ADD').kind = 'PAINT'
        row.operator("m3d.layer_add", text="Fill Layer", icon='COLOR').kind = 'FILL'
        row.operator("m3d.layer_folder_add", text="New Folder", icon='FILE_FOLDER')
        if layer is None:
            n = len(paint_slots(mat))
            reason(layout, "The %d paint slots become the Base layer" % n if n else "Add a layer to start painting")
            return
        if layer.kind == 'FILL' and L.paint_effect(layer) is None and context.mode == 'PAINT_TEXTURE':
            # A fill layer is normal; only say where strokes can go while painting.
            row = layout.row(align=True)
            row.label(text="Fill layer: paint its Mask, or", icon='INFO')
            row.operator("m3d.layer_convert", text="Convert to Paint", icon='IMAGE_DATA')
        row = layout.row()
        row.template_list("M3D_UL_layers", "", mat, "m3d_layers", mat, "m3d_layer_index", rows=8,
                          sort_reverse=True, sort_lock=True)
        col = row.column(align=True)
        col.operator("m3d.layer_move", text="", icon='TRIA_UP').delta = 1
        col.operator("m3d.layer_move", text="", icon='TRIA_DOWN').delta = -1
        col.separator()
        col.operator("m3d.layer_duplicate", text="", icon='DUPLICATE')
        col.operator("m3d.layer_remove", text="", icon='TRASH')
        row = layout.row(align=True)
        row.operator("m3d.layer_merge_down", icon='TRIA_DOWN_BAR')
        row.operator("m3d.layer_flatten", icon='IMAGE_DATA')
        row = layout.row(align=True)
        row.operator("m3d.layer_folder_add", text="Group", icon='FILE_FOLDER').group = True
        row.operator_menu_enum("m3d.layer_move_into", "folder", text="Move In", icon='TRIA_RIGHT')
        row.operator("m3d.layer_move_out", text="Move Out", icon='TRIA_LEFT')
        effect = L.paint_effect(layer)
        if L.in_frozen(layer):
            reason(layout, "Frozen with its folder: nothing to paint")
        elif layer.kind == 'FOLDER' and effect is None:
            reason(layout, "A folder holds layers: pick one to paint")
        else:
            target = layer.name + (" mask" if effect is not None and (layer.paint_mask or layer.kind != 'PAINT')
                                   else ": " + CHANNEL_BY_ID[mat.m3d_channel].label)
            reason(layout, "Painting " + target)
        equivalent = L.memory_equivalent(mat)
        row = layout.row()
        row.alert = equivalent > L.MEMORY_WARN
        row.label(text="Layer images use %d MB" % (L.memory_bytes(mat) >> 20), icon='ERROR' if row.alert else 'INFO')
        if row.alert:
            reason(layout, "That is %d images of 4K: use smaller sizes or merge layers" % equivalent)


def frozen_banner(layout, mat, layer):
    """For a layer inside a frozen folder: what it is, an Unfreeze button, and the layout to draw its (off) properties in."""
    if not L.in_frozen(layer):
        return layout
    frozen = L.frozen_root(layer)
    row = layout.row(align=True)
    row.label(text="Frozen with " + frozen.name, icon='FREEZE')
    row.operator("m3d.layer_unfreeze", text="Unfreeze").index = L.index_of(mat, frozen.uid)
    layout = layout.column()
    layout.enabled = False
    return layout


def draw_folder(layout, layer):
    """The Layer panel of a folder: name, blend, opacity, visibility, Freeze / Unfreeze, Merge Folder."""
    layout.prop(layer, "name")
    layout.prop(layer, "blend")
    layout.prop(layer, "opacity", slider=True)
    layout.prop(layer, "visible")
    layout.label(text="%d layers inside" % len([l for l in L.descendants(layer) if l.kind != 'FOLDER']), icon='FILE_FOLDER')
    row = layout.row(align=True)
    if layer.frozen:
        row.operator("m3d.layer_unfreeze", icon='FREEZE', depress=True)
        for ch in CHANNELS:
            image = entry_of(layer, ch.id).image
            if image is not None:
                w, h = L.image_size(image)
                layout.label(text="%s: %d x %d" % (ch.label, w, h), icon='IMAGE_DATA')
        reason(layout, "Frozen: the layers inside are kept and cannot be edited")
    else:
        row.operator("m3d.layer_freeze", icon='FREEZE')
        reason(layout, "Freeze bakes the folder into one image per channel")
    row.operator("m3d.layer_merge_folder", icon='TRIA_DOWN_BAR')


class PROPERTIES_PT_m3d_tx_layer(_Page, Panel):
    page = "tex_layers"
    bl_label = "Layer"

    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and has_active_layer(mesh_of(context).active_material)

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        mat = mesh_of(context).active_material
        layer = active_layer(mat)
        layout = frozen_banner(layout, mat, layer)
        layout.operator("m3d.library_save", text="Save to Library", icon='ASSET_MANAGER').kind = 'MATERIAL'
        if layer.kind == 'FOLDER':
            draw_folder(layout, layer)
            return
        layout.prop(layer, "name")
        layout.prop(layer, "blend")
        layout.prop(layer, "opacity", slider=True)
        layout.prop(layer, "visible")
        if layer.kind == 'PAINT':
            layout.prop(layer, "use_alpha")
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for ch in CHANNELS:
            flow.prop(entry_of(layer, ch.id), "use", text=ch.label, toggle=True)
        if layer.kind == 'PAINT':
            for ch in CHANNELS:
                e = entry_of(layer, ch.id)
                if e.image is not None:
                    w, h = L.image_size(e.image)
                    layout.label(text="%s: %d x %d" % (ch.label, w, h))
            return
        for ch in CHANNELS:
            e = entry_of(layer, ch.id)
            if not e.use:
                continue
            if ch.id == 'NORMAL':
                layout.label(text="Normal: flat")
            elif ch.id in L.SCALARS:
                layout.prop(e, "value", text=ch.label, slider=True)
            else:
                layout.prop(e, "color", text=ch.label)


MASK_HELP = "White shows the layer, black hides it. Effects combine from the bottom up."


class M3D_MT_mask_add(Menu):
    bl_label = "Add Mask Effect"

    def draw(self, _context):
        layout = self.layout

        def add(kind, text=None, **props):
            o = layout.operator("m3d.mask_effect_add", text=text or MK.KIND_BY_ID[kind].label,
                                icon=MK.KIND_BY_ID[kind].icon)
            o.kind = kind
            for key, value in props.items():
                setattr(o, key, value)

        layout.label(text="Paint and Fill")
        add('PAINT', "Paint (White)", fill='WHITE')
        add('PAINT', "Paint (Black)", fill='BLACK')
        add('FILL')
        layout.separator()
        layout.label(text="Generators (from the mesh)")
        for kind in ('EDGES', 'CAVITY', 'TOPDOWN', 'THICKNESS', 'COLORID', 'NOISE'):
            add(kind)
        layout.separator()
        layout.label(text="Filters (change everything below)")
        for kind in ('LEVELS', 'BLUR', 'INVERT', 'SHARPEN'):
            add(kind)


class PROPERTIES_PT_m3d_tx_mask(_Page, Panel):
    page = "tex_layers"
    bl_label = "Mask"

    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and has_active_layer(mesh_of(context).active_material)

    def draw(self, context):
        layout = self.layout
        mat = mesh_of(context).active_material
        layer = active_layer(mat)
        layout = frozen_banner(layout, mat, layer)
        first, _dot, second = MASK_HELP.partition(". ")   # (two lines: the dock can be narrow)
        reason(layout, first + ".")
        layout.label(text=second)
        if not layer.mask_stack:
            row = layout.row(align=True)
            row.operator("m3d.layer_mask_add", text="White (Show All)", icon='ADD').fill = 'WHITE'
            row.operator("m3d.layer_mask_add", text="Black (Hide All)", icon='ADD').fill = 'BLACK'
            layout.menu("M3D_MT_mask_add", icon='ADD')
            reason(layout, "No mask: the layer shows everywhere")
            return
        row = layout.row()
        row.template_list("M3D_UL_mask_effects", "", layer, "mask_stack", layer, "mask_index", rows=4,
                          sort_reverse=True, sort_lock=True)
        col = row.column(align=True)
        col.operator("m3d.mask_effect_move", text="", icon='TRIA_UP').delta = 1
        col.operator("m3d.mask_effect_move", text="", icon='TRIA_DOWN').delta = -1
        col.separator()
        col.operator("m3d.mask_effect_duplicate", text="", icon='DUPLICATE')
        col.operator("m3d.mask_effect_remove", text="", icon='TRASH')
        layout.menu("M3D_MT_mask_add", icon='ADD')
        layout.operator("m3d.library_save", text="Save to Library", icon='ASSET_MANAGER').kind = 'MASK'
        row = layout.row(align=True)
        row.operator("m3d.layer_paint_mask", text="Paint Mask", icon='BRUSH_DATA', depress=layer.paint_mask)
        row.prop(mat, "m3d_show_mask", text="Show Mask", toggle=True, icon='HIDE_OFF')
        row = layout.row(align=True)
        row.operator("m3d.mask_rebake", icon='FILE_REFRESH')
        row.operator("m3d.layer_mask_invert", icon='ARROW_LEFTRIGHT',
                     depress=layer.mask_stack[len(layer.mask_stack) - 1].kind == 'INVERT')
        row.operator("m3d.layer_mask_remove", text="", icon='X')
        for e, key in MK.missing_maps(layer):
            reason(layout, "%s needs the %s map: Rebake maps" % (e.name, MK.MAP_LABELS[key]))
        effect = L.active_effect(layer)
        if effect is None:
            return
        box = layout.box()
        kind = MK.KIND_BY_ID[effect.kind]
        box.label(text=effect.name, icon=kind.icon)
        col = box.column()
        split_props(col)
        if effect.kind in {'PAINT', 'BLUR'} and effect.image is not None:
            w, h = L.image_size(effect.image)
            col.label(text="%s  %d x %d" % (effect.image.name, w, h), icon='IMAGE_DATA')
        for prop, label in MK.PARAM_UI.get(effect.kind, ()):
            col.prop(effect, prop, text=label, slider=prop not in {"direction", "space", "invert", "seed", "color"})
        if effect.kind == 'PAINT':
            reason(col, "Turn on Paint Mask to paint it")
        elif effect.kind == 'BLUR':
            reason(col, "Blurs the stack below; it follows brush strokes after a moment")
        elif effect.kind == 'INVERT':
            reason(col, "Opacity sets how much is swapped")
        elif effect.kind == 'COLORID':
            ids = MK.id_colors(effect.image)
            for name in list(ids)[:12]:
                col.operator("m3d.mask_id_pick", text=name, icon='COLOR').name = name
            reason(col, "Pick a colour, or the one of the ID map in the picker" if ids else "Bake the ID map first (Rebake Maps)")


class PROPERTIES_PT_m3d_tx_channels(_Page, Panel):
    page = "tex_layers"
    bl_label = "Channels"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mat = ob.active_material
        found, now = channel_slots(mat), active_channel(mat)
        col = layout.column(align=True)
        for ch in CHANNELS:
            split = col.split(factor=0.55, align=True)
            o = split.operator("m3d.tex_channel", text=ch.label, icon='ADD' if ch.id not in found else 'NONE',
                               depress=ch.id in found and ch.id == now)
            o.channel = ch.id
            if ch.id in found:
                w, h = found[ch.id][1].size
                split.label(text="%d x %d" % (w, h))
            else:
                split.label(text="Add")
        layout.prop(context.scene.m3d_tex, "resolution", text="New Size")
        layout.operator("m3d.tex_save_all", icon='FILE_TICK')
        reason(layout, "C / Shift+C: next / previous channel")


class PROPERTIES_PT_m3d_tx_slots(_Page, Panel):
    page = "tex_layers"
    bl_label = "All Paint Slots"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mat = ob.active_material
        layout.prop(paint_settings(context), "mode", text="Canvas")
        row = layout.row()
        row.template_list("TEXTURE_UL_texpaintslots", "", mat, "texture_paint_slots", mat, "paint_active_slot", rows=3)
        row.operator_menu_enum("paint.add_texture_paint_slot", "type", icon='ADD', text="")


# --- Brush: the stock brush panels

class _Brush(_BrushPage):
    page = "tex_brush"


class PROPERTIES_PT_m3d_tx_stroke(_Brush, StrokePanel, Panel):
    pass


class PROPERTIES_PT_m3d_tx_stabilize(_Brush, SmoothStrokePanel, Panel):
    bl_parent_id = "PROPERTIES_PT_m3d_tx_stroke"


class PROPERTIES_PT_m3d_tx_falloff(_Brush, FalloffPanel, Panel):
    pass


class PROPERTIES_PT_m3d_tx_texture(_Brush, Panel):
    bl_label = "Texture"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def page_poll(cls, context):
        brush = paint_settings(context).brush
        return super().page_poll(context) and getattr(brush, "image_brush_type", None) == 'DRAW'

    def draw(self, context):
        brush = paint_settings(context).brush
        col = self.layout.column()
        col.template_ID_preview(brush.texture_slot, "texture", new="texture.new", rows=3, cols=8)
        brush_texture_settings(col, brush, None)


class PROPERTIES_PT_m3d_tx_mask_texture(_Brush, TextureMaskPanel, Panel):
    pass


class PROPERTIES_PT_m3d_tx_stencil(_Page, Panel):
    page = "tex_brush"
    bl_label = "Stencil"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(paint_settings(context), "use_stencil_layer", text="")

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ipaint = paint_settings(context)
        mesh = mesh_of(context).data
        col = layout.column()
        col.active = ipaint.use_stencil_layer
        col.template_ID(ipaint, "stencil_image", new="image.new", open="image.open")
        col.menu("VIEW3D_MT_tools_projectpaint_stencil", text=mesh.uv_layer_stencil.name if mesh.uv_layer_stencil else "UV Map",
                 translate=False)
        row = col.row(align=True)
        row.prop(ipaint, "stencil_color", text="Display Color")
        row.prop(ipaint, "invert_stencil", text="", icon='IMAGE_ALPHA')


class PROPERTIES_PT_m3d_tx_clone(_Brush, ClonePanel, Panel):
    pass


class PROPERTIES_PT_m3d_tx_options(_Page, Panel):
    page = "tex_brush"
    bl_label = "Options"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ipaint = paint_settings(context)
        layout.prop(ipaint, "seam_bleed")
        layout.prop(ipaint, "dither", slider=True)
        layout.prop(ipaint, "use_cavity", text="Cavity Mask")
        if ipaint.use_cavity:
            layout.template_curve_mapping(ipaint, "cavity_curve", brush=True)


class PROPERTIES_PT_m3d_tx_cursor(_Brush, DisplayPanel, Panel):
    bl_label = "Cursor"


class PROPERTIES_PT_m3d_tx_palette(_Brush, ColorPalettePanel, Panel):
    pass


# --- Bake

class _Bake(_Page):
    page = "tex_bake"
    need = 'BAKE'


class PROPERTIES_PT_m3d_tx_bake_high(_Bake, Panel):
    bl_label = "High Poly"

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.need) and not m3d_pair.grouped(mesh_of(context))   # (a group has its own high polys)

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        s = mesh_of(context).m3d_bake
        layout.prop(s, "high", text="Mesh")
        layout.operator("m3d.tex_bake_pick", icon='EYEDROPPER')
        if s.high is None:
            reason(layout, "No high poly: the mesh bakes itself")
        else:
            layout.operator("m3d.hp_make_pair", icon='LINKED')
            reason(layout, "Make Pair: bake groups can have several high polys")


class PROPERTIES_PT_m3d_tx_bake_maps(_Bake, Panel):
    bl_label = "Maps"

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        owner = bake_owner(ob)
        s = owner.m3d_bake
        grid_ = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for _key, _label, flag in BAKE_MAPS:
            grid_.prop(s, flag, toggle=True)
        split_props(layout)
        layout.prop(s, "resolution")
        layout.prop(s, "margin")
        name, lows = texture_set(owner)
        if len(lows) > 1:
            reason(layout, "Texture set %s: %s" % (name, ", ".join(o.name for o in lows)))
        elif owner != ob:
            reason(layout, "Set on %s" % owner.name)
        if s.use_curvature:
            reason(layout, "Curvature needs enough polygons")
        if s.use_thickness:
            reason(layout, "Thickness is for closed meshes")


class PROPERTIES_PT_m3d_tx_bake_multires(_Bake, Panel):
    bl_label = "Multires"

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.need) and multires_ready(mesh_of(context))

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        s = ob.m3d_bake
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for _key, _label, _type, flag in MULTIRES_MAPS:
            flow.prop(s, flag, toggle=True)
        split_props(layout)
        layout.prop(s, "multires_level")
        layout.operator("m3d.tex_bake_multires", icon='MOD_MULTIRES')
        total = multires_of(ob).total_levels
        low = min(s.multires_level, total - 1)
        reason(layout, "The detail of levels %d to %d is baked onto level %d" % (low + 1, total, low))
        reason(layout, "No high poly needed; the maps are named like the others")


class PROPERTIES_PT_m3d_tx_bake_settings(_Bake, Panel):
    bl_label = "Settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        ob = mesh_of(context)
        s = bake_owner(ob).m3d_bake
        if not m3d_pair.grouped(ob):   # (a group has its own extrusion and ray distance: Group Settings)
            layout.prop(s, "extrusion")
            layout.prop(s, "ray_distance")
        layout.prop(s, "samples")
        if s.use_thickness:
            layout.prop(s, "thickness_distance")
        world = context.scene.world
        if world is not None:
            layout.prop(world.light_settings, "distance", text="AO Distance")


class PROPERTIES_PT_m3d_tx_bake_run(_Bake, Panel):
    bl_label = "Bake"

    @classmethod
    def page_poll(cls, context):
        ob = mesh_of(context)   # (a group has no button here: only its images, once it has some)
        return ready(context, cls.need) and (not m3d_pair.grouped(ob) or bool(bake_owner(ob).m3d_bake.baked))

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        s = bake_owner(ob).m3d_bake
        if not m3d_pair.grouped(ob):   # (a group is baked from the Bake Groups panel)
            row = layout.row()
            row.scale_y = 1.6
            row.operator("m3d.tex_bake", icon='RENDER_STILL')
            reason(layout, "Uses Cycles; the window waits until it is done")
        for name in filter(None, s.baked.split("|")):
            row = layout.row(align=True)
            row.label(text=name, icon='IMAGE_DATA')
            row.operator("m3d.tex_show_image", text="", icon='HIDE_OFF').name = name


# --- Export

class _Export(_Page):
    page = "tex_export"
    need = 'EXPORT'


EXPORT_NOTES = {
    'GLTF': "One .glb with the mesh, the material and its textures",
    'UNREAL': "T_Name_BC, _N (DirectX), _ORM (R occlusion, G roughness, B metallic), _E",
    'UNITY': "Name_Albedo, _Normal, _MetallicSmoothness (smoothness in alpha), _Occlusion, _Emission",
}


class PROPERTIES_PT_m3d_tx_export_preset(_Export, Panel):
    bl_label = "Preset"

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_tex
        layout.row().prop(s, "export_preset", expand=True)
        reason(layout, EXPORT_NOTES[s.export_preset])
        split_props(layout)
        layout.prop(s, "export_folder")
        if s.export_preset != 'GLTF':
            layout.prop(s, "export_size")
        layout.prop(s, "export_bake_meshes")
        if s.export_bake_meshes:
            reason(layout, "<name>_low.fbx and <name>_high.fbx, meshes named Part_low, Part_high")


class PROPERTIES_PT_m3d_tx_export_run(_Export, Panel):
    bl_label = "Export"

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_tex
        row = layout.row()
        row.scale_y = 1.6
        row.operator("m3d.tex_export", icon='EXPORT')
        layout.operator("m3d.tex_save_all", icon='FILE_TICK')
        for path in filter(None, s.export_files.split("|")):
            layout.label(text=os.path.basename(path), icon='FILE_IMAGE')


# --- Display

class _Display(_Page):
    page = "tex_display"
    need = None


class PROPERTIES_PT_m3d_tx_environment(_Display, Panel):
    bl_label = "Environment"

    def draw(self, context):
        layout = self.layout
        space = viewport(context)
        if space is None:
            reason(layout, "No 3D Viewport in this workspace")
            return
        shading = space.shading
        layout.row().prop(shading, "type", expand=True)
        if shading.type != 'MATERIAL':
            reason(layout, "The HDRI is for Material Preview")
            return
        split_props(layout)
        layout.prop(shading, "use_scene_lights")
        layout.prop(shading, "use_scene_world")
        if not shading.use_scene_world:
            layout.template_icon_view(shading, "studio_light", scale=3)
            layout.prop(shading, "studiolight_rotate_z", text="Rotation")
            layout.prop(shading, "studiolight_intensity", text="Intensity")
            layout.prop(shading, "studiolight_background_alpha", text="Background")


class PROPERTIES_PT_m3d_tx_channel_view(_Display, Panel):
    bl_label = "Channel View"

    def draw(self, context):
        layout = self.layout
        space = viewport(context)
        ob = mesh_of(context)
        found = channel_slots(ob.active_material) if ob is not None and ob.active_material else {}
        now = active_channel(ob.active_material) if found else None
        on = space is not None and channel_view_on(space.shading)
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for ch in CHANNELS:
            sub = flow.row(align=True)
            sub.enabled = ch.id in found
            sub.operator("m3d.tex_channel_view", text=ch.label, depress=on and ch.id == now).channel = ch.id
        layout.operator("m3d.tex_channel_view", text="Back to the Material" if on else "Show Active Channel",
                        icon='IMAGE_RGB').channel = ''


class PROPERTIES_PT_m3d_tx_checker(_Display, Panel):
    bl_label = "UV Checker"

    def draw(self, context):
        layout = self.layout
        layout.operator("m3d.uv_checker", text="Checker Map", icon='TEXTURE', depress=m3d_uv.checker_on(context))
        reason(layout, "Replaces the material while it is on")
        space = viewport(context)
        if space is not None:
            layout.prop(space.overlay, "show_wireframes", text="Wireframe")


GATES = {"brushes": 'PAINT', "layers": 'PAINT', "brush": 'PAINT', "bake": 'BAKE', "export": 'EXPORT'}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page, need) for page, need in GATES.items())


# -----------------------------------------------------------------------------
# Status Line

def draw_status_line(layout, context):
    """Texture Status Line: file, modes, paint channels, symmetry, viewport display, channel view, new slot size,
    Save All."""
    from m3d_ui import _call, draw_file_buttons, draw_workspace_picker
    draw_file_buttons(layout)
    row = layout.row(align=True)
    _call(row, "object.mode_set", 'OBJECT_DATAMODE', "Object Mode", depress=context.mode == 'OBJECT', mode='OBJECT')
    _call(row, "object.mode_set", 'TPAINT_HLT', "Texture Paint Mode", depress=context.mode == 'PAINT_TEXTURE',
          mode='TEXTURE_PAINT')
    note = m3d_pair.big_note(context)
    if note:
        layout.label(text=note, icon='ERROR')
    ob = mesh_of(context)
    if ob is None:
        draw_workspace_picker(layout, context)
        return
    found = channel_slots(ob.active_material) if ob.active_material else {}
    now = active_channel(ob.active_material) if found else None
    row = layout.row(align=True)
    for ch in CHANNELS:
        sub = row.row(align=True)
        sub.active = ch.id in found
        sub.operator("m3d.tex_channel", text=ch.label, depress=ch.id == now).channel = ch.id
    row = layout.row(align=True)
    for axis in "xyz":
        row.prop(ob.data, "use_mirror_" + axis, text=axis.upper(), toggle=True)
    space = viewport(context)
    if space is not None:
        row = layout.row(align=True)
        for shading, icon, label in (('MATERIAL', 'SHADING_TEXTURE', "Material Preview"),
                                     ('SOLID', 'SHADING_SOLID', "Solid"), ('RENDERED', 'SHADING_RENDERED', "Rendered")):
            _call(row, "wm.context_set_enum", icon, label, depress=space.shading.type == shading and
                  not channel_view_on(space.shading), data_path="space_data.shading.type", value=shading)
        row.operator("m3d.tex_channel_view", text="", icon='IMAGE_RGB', depress=channel_view_on(space.shading))
    layout.prop(context.scene.m3d_tex, "resolution", text="")
    layout.operator("m3d.tex_save_all", text="Save All", icon='FILE_TICK')
    draw_workspace_picker(layout, context)


# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

SHELF_BRUSHES = [
    ("object.mode_set", 'TPAINT_HLT', {"mode": 'TEXTURE_PAINT'}),
    None,
    *(brush_item(label, name) for label, name in BRUSHES),
    None,
    ("paint.brush_colors_flip", 'ARROW_LEFTRIGHT', {}),
]
SHELF_CHANNELS = [
    *(("m3d.tex_channel", 'ADD', {"channel": ch.id}, ch.label) for ch in CHANNELS),
    None,
    ("m3d.tex_unwrap", 'MOD_UVPROJECT', {}, "Auto Unwrap"),
    ("m3d.tex_add_material", 'MATERIAL', {}, "Add Material"),
]
SHELF_OUTPUT = [
    ("m3d.tex_bake", 'RENDER_STILL', {}, "Bake"),
    ("m3d.tex_export", 'EXPORT', {}, "Export"),
    ("m3d.tex_save_all", 'FILE_TICK', {}, "Save All"),
]


# -----------------------------------------------------------------------------

classes = (
    M3D_TexSettings,
    M3D_BakeSettings,
    M3D_OT_tex_channel,
    M3D_OT_tex_channel_cycle,
    M3D_OT_tex_add_material,
    M3D_OT_tex_unwrap,
    M3D_OT_tex_save_all,
    M3D_OT_tex_channel_view,
    M3D_OT_tex_apply_material,
    M3D_OT_tex_bake_multires,
    M3D_OT_tex_bake_pick,
    M3D_OT_tex_bake,
    M3D_OT_tex_show_image,
    M3D_OT_tex_export,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_tx_canvas,
    PROPERTIES_PT_m3d_tx_brush,
    PROPERTIES_PT_m3d_tx_grid,
    PROPERTIES_PT_m3d_tx_tuning,
    PROPERTIES_PT_m3d_tx_projection,
    PROPERTIES_PT_m3d_tx_more,
    PROPERTIES_PT_m3d_tx_advanced,
    PROPERTIES_PT_m3d_tx_stack,
    PROPERTIES_PT_m3d_tx_layer,
    M3D_MT_mask_add,
    PROPERTIES_PT_m3d_tx_mask,
    PROPERTIES_PT_m3d_tx_channels,
    PROPERTIES_PT_m3d_tx_slots,
    PROPERTIES_PT_m3d_tx_stroke,
    PROPERTIES_PT_m3d_tx_stabilize,
    PROPERTIES_PT_m3d_tx_falloff,
    PROPERTIES_PT_m3d_tx_texture,
    PROPERTIES_PT_m3d_tx_mask_texture,
    PROPERTIES_PT_m3d_tx_stencil,
    PROPERTIES_PT_m3d_tx_clone,
    PROPERTIES_PT_m3d_tx_options,
    PROPERTIES_PT_m3d_tx_cursor,
    PROPERTIES_PT_m3d_tx_palette,
    PROPERTIES_PT_m3d_tx_bake_high,
    PROPERTIES_PT_m3d_tx_bake_maps,
    PROPERTIES_PT_m3d_tx_bake_multires,
    PROPERTIES_PT_m3d_tx_bake_settings,
    PROPERTIES_PT_m3d_tx_bake_run,
    PROPERTIES_PT_m3d_tx_export_preset,
    PROPERTIES_PT_m3d_tx_export_run,
    PROPERTIES_PT_m3d_tx_environment,
    PROPERTIES_PT_m3d_tx_channel_view,
    PROPERTIES_PT_m3d_tx_checker,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_tex = PointerProperty(type=M3D_TexSettings)
    bpy.types.Object.m3d_bake = PointerProperty(type=M3D_BakeSettings)
    bpy.app.handlers.save_pre.append(save_pre)


def unregister():
    bpy.app.handlers.save_pre.remove(save_pre)
    del bpy.types.Object.m3d_bake
    del bpy.types.Scene.m3d_tex
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
