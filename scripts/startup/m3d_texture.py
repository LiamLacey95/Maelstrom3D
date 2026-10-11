# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Texture workspace (F4) for Maelstrom3D: the tool strip, the Texture Set List, the Layers | Texture Set Settings dock (and
the Bake page behind Bake Mesh Maps), Properties, the dock strip (popovers), the context toolbar (the Texture Status
Line), the display modes of the 3D and 2D views, the painting keys, shelf items, paint channels, Bake and Export, and the
save handler that keeps painted images.

The layout is built by tools/m3d/build_startup.py (phase3_texture): one Properties editor for each part, told apart by where
it sits (m3d_workspace.texture_role). The tabs are DOCK_TABS['TEXTURE'] in m3d_workspace.py, the menus and shelves in
m3d_ui.py. Brush, stroke, falloff and texture controls are Blender's own panel classes re-used on the pages. A channel is a
paint slot of the active material (Base Color, Roughness, Metallic, Normal, Height, Emission). The Layers tab is the layer
stack (data, node chains and operators: m3d_layers.py); a material without layers works on its paint slots directly, and
gets its slots as the bottom layer on the first layer operation. The Assets panel (materials, smart materials and masks,
brushes, alphas, environments, your own items) is m3d_library.py.

A file saved with the old layout (a brush tray and a dock with six tabs; Workspace.m3d_layout 0) keeps working: its pages
(OLD_PAGES) draw the same panels, until Reset Workspace brings the new layout.
"""

import colorsys
import math
import os
from contextlib import ExitStack, contextmanager, nullcontext

import bpy
import numpy as np
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import Menu, Operator, Panel, PropertyGroup
from bl_ui.properties_paint_common import (
    BrushSelectPanel, ClonePanel, ColorPalettePanel, DisplayPanel, FalloffPanel, SmoothStrokePanel,
    StrokePanel, TextureMaskPanel, UnifiedPaintPanel, brush_settings, brush_settings_advanced, brush_texture_settings)
from mathutils import Vector

import m3d_layers as L
import m3d_masks as MK
import m3d_pair
import m3d_sculpt as S
import m3d_uv
import m3d_workspace as W
from m3d_layers import (CHANNEL_BY_ID, CHANNEL_ITEMS, CHANNELS, active_layer, entry_of, pixels_of, principled_of,
                        set_channel_space)
from m3d_mode import _button
from m3d_sculpt import (active_brush_id, brush_tiles, mesh_of, multires_of, reason, split_props, ui_scale_factor,
                        viewport)
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

def _brush_toggled(cid):
    """Update of a channel toggle of the brush material: the paint layer gets the channel when it is turned on, then the
    brush is aimed again (which makes the images the stroke needs)."""
    def update(self, context):
        if MK._muted[0]:
            return
        ob = mesh_of(context)
        mat = ob.active_material if ob is not None else None
        if mat is None or not len(mat.m3d_layers):
            return
        layer = active_layer(mat)
        if getattr(self, "use_" + cid.lower()) and layer is not None and layer.kind == 'PAINT' and not L.in_frozen(layer):
            with MK.muted():
                entry_of(layer, cid).use = True
            L.rebuild_all(mat)
        L.sync_target(context, mat, True)
    return update


def _brush_value_changed(self, context):
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    if not MK._muted[0] and mat is not None and len(mat.m3d_layers):
        L.sync_target(context, mat, True)


class M3D_BrushMaterial(PropertyGroup):
    """What one brush stroke paints (Scene.m3d_tex.brush): the channels of the paint layer that are on, each with its own value.
    Base Color is painted with the brush color. The Eraser erases all the channels that are on."""
    use_base_color: BoolProperty(name="Base Color", default=True, update=_brush_toggled('BASE_COLOR'),
                                 description="Paint the Base Color of the layer with the brush color")
    use_height: BoolProperty(name="Height", default=False, update=_brush_toggled('HEIGHT'),
                             description="Paint the Height of the layer with the value below (grey: 0.5 is flat, more is "
                             "higher)")
    use_roughness: BoolProperty(name="Roughness", default=False, update=_brush_toggled('ROUGHNESS'),
                                description="Paint the Roughness of the layer with the value below")
    use_metallic: BoolProperty(name="Metallic", default=False, update=_brush_toggled('METALLIC'),
                               description="Paint the Metallic of the layer with the value below")
    use_emission: BoolProperty(name="Emission", default=False, update=_brush_toggled('EMISSION'),
                               description="Paint the Emission of the layer with the color below")
    height: FloatProperty(name="Height", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=_brush_value_changed,
                          description="Value painted into Height (0.5 is flat)")
    roughness: FloatProperty(name="Roughness", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
                             update=_brush_value_changed, description="Value painted into Roughness")
    metallic: FloatProperty(name="Metallic", default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_brush_value_changed,
                            description="Value painted into Metallic")
    emission: FloatVectorProperty(name="Emission", size=3, subtype='COLOR', min=0.0, max=1.0, default=(0.0, 0.0, 0.0),
                                  update=_brush_value_changed, description="Color painted into Emission")
    # What the previews of Properties show: a scalar channel's value as a grey (read only).
    swatch_height: FloatVectorProperty(name="Height", size=3, subtype='COLOR', get=lambda self: (self.height,) * 3,
                                       description="Value painted into Height (0.5 is flat)")
    swatch_roughness: FloatVectorProperty(name="Roughness", size=3, subtype='COLOR', get=lambda self: (self.roughness,) * 3,
                                          description="Value painted into Roughness")
    swatch_metallic: FloatVectorProperty(name="Metallic", size=3, subtype='COLOR', get=lambda self: (self.metallic,) * 3,
                                         description="Value painted into Metallic")


class M3D_TexSettings(PropertyGroup):
    """Texture workspace options (Scene.m3d_tex): new slot size, the brush material and the Export tab."""
    resolution: EnumProperty(name="Resolution", default='2048', items=SIZES,
                             description="Size of new paint slots (bigger images use more memory)")
    brush: PointerProperty(type=M3D_BrushMaterial)
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
    fill_mode: EnumProperty(name="Fill", default='POLYGON', items=(
        ('POLYGON', "Polygon", "The polygon under the cursor"),
        ('ISLAND', "UV Island", "The UV island under the cursor: every polygon that is connected to it in the UV map"),
        ('MESH', "Mesh", "Every polygon of the mesh")), description="What a click with the Polygon Fill tool fills")
    props_mode: EnumProperty(name="Properties", default='AUTO', items=(
        ('AUTO', "Auto", "Properties show the active layer's settings: Paint, Fill or Mask"),
        ('LAYER', "Layer", "Properties show the layer's own settings"),
        ('MASK', "Mask", "Properties show the layer's mask")), description="What the Properties editor shows for the active layer")


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
        if mat.m3d_layers:
            try:
                L.paint_channel(context, paint_mesh(context), CHANNEL_BY_ID[order[i]])   # (that channel alone)
            except RuntimeError as err:
                self.report({'WARNING'}, str(err).strip())
                return {'CANCELLED'}
        else:
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


def channel_view_set(shading, on):
    """Show the active paint channel alone (flat, no lighting), or go back to the view before."""
    if on and not channel_view_on(shading):
        _view_memory["shading"] = (shading.type, shading.light, shading.color_type)
        shading.type, shading.light, shading.color_type = 'SOLID', 'FLAT', 'TEXTURE'
    elif not on and channel_view_on(shading):
        shading.type, shading.light, shading.color_type = _view_memory.pop("shading", ('MATERIAL', 'STUDIO', 'MATERIAL'))


def view3d_space(context):
    """The 3D view the operator was run in (a key or a header button), else the main one."""
    space = context.space_data
    return space if space is not None and space.type == 'VIEW_3D' else viewport(context)


class M3D_OT_tex_channel_view(Operator):
    """Show the active paint channel alone in the 3D view (flat, no lighting); again to go back to the old view"""
    bl_idname = "m3d.tex_channel_view"
    bl_label = "Channel View"
    bl_options = {'REGISTER', 'UNDO'}

    channel: StringProperty(description="Channel to show (empty: the active one)")

    @classmethod
    def poll(cls, context):
        return view3d_space(context) is not None

    def execute(self, context):
        shading = view3d_space(context).shading
        on = channel_view_on(shading)
        if self.channel:
            ob = mesh_of(context)
            found = channel_slots(ob.active_material) if ob is not None and ob.active_material else {}
            if self.channel not in found:
                self.report({'WARNING'}, "No %s channel yet" % CHANNEL_BY_ID[self.channel].label)
                return {'CANCELLED'}
            select_channel(ob.active_material, self.channel)
        channel_view_set(shading, not (on and not self.channel))
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
# Tools: the tool strip. Blender's texture painting has one brush tool, and the brush decides what a stroke does, so a tool
# of the strip is a brush (and a few settings) picked in one click; `tool_of` reads the tool back from the brush.

TOOLS = (   # (id, label, key, icon, what it does)
    ('PAINT', "Paint", '1', 'BRUSH_DATA', "Paint with the brush: the Draw tool with the last Paint brush you used"),
    ('ERASER', "Eraser", '2', 'EVENT_TABLET_ERASER', "Erase paint back to transparent: a Draw brush that erases alpha"),
    ('PROJECTION', "Projection", '3', 'IMAGE_PLANE', "Paint the brush texture projected through the screen; S (stencil) "
     "and the stencil keys move and scale it"),
    ('POLYFILL', "Polygon Fill", '4', 'FACESEL', "Fill polygons, UV islands or the whole mesh with one click (the Fill brush "
     "on the faces under the cursor: Face Selection masking)"),
    ('SMUDGE', "Smudge", '5', 'MOD_SMOOTH', "Smear the paint that is there (the Smear brush)"),
    ('CLONE', "Clone", '6', 'DUPLICATE', "Paint with another place as the source (the Clone brush)"),
    ('PICKER', "Picker", 'P', 'EYEDROPPER', "Pick the color under the cursor and go on with the same tool; hold P over the "
     "model, or click here and then on the model"),
)
TOOL_BY_ID = {t[0]: t for t in TOOLS}
TOOL_BRUSHES = {'PAINT': "Paint Hard", 'PROJECTION': "Paint Hard", 'ERASER': "Erase Hard", 'POLYFILL': "Fill", 'SMUDGE': "Smear",
                'CLONE': "Clone"}   # the brush asset a tool picks (Paint and Eraser: the one they used last)
BRUSH_TOOLS = {'DRAW': 'PAINT', 'SMEAR': 'SMUDGE', 'CLONE': 'CLONE', 'FILL': 'POLYFILL'}   # Brush.image_brush_type -> tool
_tool_state = {"last": {}, "mapping": None, "face_mask": None}   # last Paint / Eraser brush; what Projection and Polygon Fill set


def image_brush(context):
    paint = context.tool_settings.image_paint
    return paint.brush if paint is not None else None


def brush_name(context):
    """Name of the active texture brush asset ("Paint Hard"), empty without one."""
    return active_brush_id(context).rpartition("/")[2]


def tool_of(context):
    """The tool of the strip that the active brush is: Eraser for a Draw brush that erases alpha, Projection for one whose
    texture is mapped as a Stencil, Paint for any other Draw brush. None for brushes the strip has no tool for (Blur, Mask)."""
    brush = image_brush(context)
    if brush is None:
        return None
    tool = BRUSH_TOOLS.get(brush.image_brush_type)
    if tool == 'PAINT':
        if brush.blend == 'ERASE_ALPHA':
            return 'ERASER'
        if brush.texture is not None and brush.texture_slot.map_mode == 'STENCIL':
            return 'PROJECTION'
    return tool


def stencil_on(brush):
    return brush is not None and brush.texture is not None and brush.texture_slot.map_mode == 'STENCIL'


def stencil_toggle(brush):
    """Map the brush texture as a Stencil (screen space, moved with the stencil keys), or back to how it was. Without a texture
    the Clouds alpha is used (and taken off again with the stencil). Returns True when the stencil is on."""
    if stencil_on(brush):
        release_stencil(brush)
        return False
    added = brush.texture is None
    if added:
        tex = S.link_alpha("Clouds")
        if tex is None:
            raise RuntimeError("Pick a texture for the brush first (Assets > Alphas)")
        brush.texture = tex
        brush.texture_slot.map_mode = 'VIEW_PLANE'
    _tool_state["mapping"] = (brush.name, brush.texture_slot.map_mode, added)
    brush.texture_slot.map_mode = 'STENCIL'
    return True


def set_stencil_texture(brush, texture):
    """Make `texture` the stencil of the brush: its Texture, mapped as a Stencil (the mapping before is remembered, as
    stencil_toggle does). None takes the stencil off."""
    if texture is None:
        if stencil_on(brush):
            release_stencil(brush)
        return
    if not stencil_on(brush):
        _tool_state["mapping"] = (brush.name, brush.texture_slot.map_mode, brush.texture is None)
        brush.texture_slot.map_mode = 'STENCIL'
    brush.texture = texture


def release_stencil(brush):
    """The brush's texture mapping as it was before the stencil (and no texture, when the stencil brought it)."""
    name, before, added = _tool_state["mapping"] or (brush.name, 'VIEW_PLANE', False)
    brush.texture_slot.map_mode = before
    if added:
        brush.texture = None
    _tool_state["mapping"] = None


def release_tool(context):
    """Undo what the last tool set besides its brush: a Stencil mapping (Projection) and Face Selection masking (Polygon Fill)."""
    mapping = _tool_state["mapping"]
    # (a brush from the asset library is linked data: look it up in the list, `brushes.get(name)` finds only local ones)
    brush = next((b for b in bpy.data.brushes if mapping is not None and b.name == mapping[0] and stencil_on(b)), None)
    if brush is not None:
        release_stencil(brush)
    _tool_state["mapping"] = None
    ob = mesh_of(context)
    if _tool_state["face_mask"] is not None and ob is not None:
        ob.data.use_paint_mask = _tool_state["face_mask"]
    _tool_state["face_mask"] = None


def set_tool(context, tool):
    """Make `tool` the active one (in Texture Paint Mode): pick its brush, and set what it needs. Returns a note for the Status
    Bar, empty when all is well."""
    before = tool_of(context)
    if before in {'PAINT', 'ERASER'} and brush_name(context):
        _tool_state["last"][before] = brush_name(context)   # (Paint comes back to the Airbrush you left it for)
    release_tool(context)
    name = _tool_state["last"].get(tool, TOOL_BRUSHES[tool])
    # From the tool strip (a Properties editor) or a timer there is no tool of the editor: the brush goes to the 3D view's.
    screen = context.screen
    areas = sorted((a for a in screen.areas if a.type == 'VIEW_3D'), key=lambda a: -a.width * a.height) if screen else []
    region = next((r for r in areas[0].regions if r.type == 'WINDOW'), None) if areas else None
    if region is not None and context.area != areas[0]:
        with context.temp_override(area=areas[0], region=region):
            bpy.ops.brush.asset_activate(**brush_props(name))
    brush = image_brush(context)
    if brush is None:
        return "No texture brush"
    ob = mesh_of(context)
    if tool == 'PROJECTION':
        stencil_toggle(brush)
    elif tool == 'POLYFILL' and ob is not None:
        _tool_state["face_mask"] = ob.data.use_paint_mask
        ob.data.use_paint_mask = True
    return ""


class M3D_OT_tex_tool(Operator):
    """Pick a painting tool: Paint (1), Eraser (2), Projection (3), Polygon Fill (4), Smudge (5), Clone (6), Picker (P)"""
    bl_idname = "m3d.tex_tool"
    bl_label = "Painting Tool"
    bl_options = {'INTERNAL'}

    tool: EnumProperty(items=[(t[0], t[1], t[4]) for t in TOOLS])

    @classmethod
    def description(cls, _context, props):
        _id, label, key, _icon, what = TOOL_BY_ID[props.tool]
        return "%s (%s): %s" % (label, key, what)

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None and context.mode in {'OBJECT', 'PAINT_TEXTURE'}

    def execute(self, context):
        ob = mesh_of(context)
        if context.mode != 'PAINT_TEXTURE':
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')   # (a click on a tool is a click on painting)
        if self.tool == 'PICKER':
            return self.pick(context)
        try:
            note = set_tool(context, self.tool)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        if note:
            self.report({'WARNING'}, note)
            return {'CANCELLED'}
        if self.tool == 'POLYFILL':
            self.report({'INFO'}, "Polygon Fill: click a polygon, UV island or mesh (the Fill mode is in the toolbar)")
        elif self.tool == 'PROJECTION' and not ob.data.uv_layers:
            self.report({'WARNING'}, "This mesh has no UVs")
        return {'FINISHED'}

    def pick(self, context):
        areas = [a for a in context.screen.areas if a.type == 'VIEW_3D'] if context.screen else []
        if not areas:
            self.report({'WARNING'}, "No 3D view to pick in")
            return {'CANCELLED'}
        area = max(areas, key=lambda a: a.width * a.height)
        region = next(r for r in area.regions if r.type == 'WINDOW')
        try:
            with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                bpy.ops.paint.sample_color('INVOKE_DEFAULT')
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        self.report({'INFO'}, "Picker: move over the model and click to pick a color")
        return {'FINISHED'}


def uv_island(mesh, start):
    """Indices of the polygons in the UV island of polygon `start`: the ones reached over edges whose two ends have the same UV
    coordinates on both sides."""
    import bmesh
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        layer = bm.loops.layers.uv.active
        if layer is None or not 0 <= start < len(bm.faces):
            return [start]
        bm.faces.ensure_lookup_table()
        seen, stack = {start}, [bm.faces[start]]
        while stack:
            face = stack.pop()
            for loop in face.loops:
                for other in loop.edge.link_loops:
                    if other.face.index in seen:
                        continue
                    a0, a1 = loop[layer].uv, loop.link_loop_next[layer].uv
                    if other.vert == loop.vert:
                        b0, b1 = other[layer].uv, other.link_loop_next[layer].uv
                    else:
                        b0, b1 = other.link_loop_next[layer].uv, other[layer].uv
                    if (a0 - b0).length < 1e-5 and (a1 - b1).length < 1e-5:
                        seen.add(other.face.index)
                        stack.append(other.face)
        return sorted(seen)
    finally:
        bm.free()


def select_faces(mesh, indices):
    """Face Selection masking selects these polygons only."""
    selected = np.zeros(len(mesh.polygons), np.bool_)
    selected[list(indices)] = True
    mesh.polygons.foreach_set("select", selected)
    mesh.update()


class M3D_OT_tex_polyfill(Operator):
    """Polygon Fill: a click selects the polygon, UV island or mesh under the cursor (the Fill mode of the toolbar) and fills it
    with the brush color, using the Fill brush with Face Selection masking"""
    bl_idname = "m3d.tex_polyfill"
    bl_label = "Polygon Fill"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'PAINT_TEXTURE' and context.area is not None and context.area.type == 'VIEW_3D'
                and context.region_data is not None and tool_of(context) == 'POLYFILL')

    def invoke(self, context, event):
        from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
        ob, mode = mesh_of(context), context.scene.m3d_tex.fill_mode
        co = (event.mouse_region_x, event.mouse_region_y)
        inv = ob.matrix_world.inverted()
        origin = inv @ region_2d_to_origin_3d(context.region, context.region_data, co)
        vec = (inv.to_3x3() @ region_2d_to_vector_3d(context.region, context.region_data, co)).normalized()
        hit, _loc, _normal, index = ob.ray_cast(origin, vec)
        if mode != 'MESH' and not hit:
            return {'CANCELLED'}   # (a click beside the model fills nothing)
        faces = range(len(ob.data.polygons)) if mode == 'MESH' else uv_island(ob.data, index) if mode == 'ISLAND' else [index]
        ob.data.use_paint_mask = True
        select_faces(ob.data, faces)
        return bpy.ops.paint.image_paint('INVOKE_DEFAULT')   # (the fill is done when the button is released)


# -----------------------------------------------------------------------------
# Texture sets: one for each material (m3d_layers keeps the layers of a material). The list shows the materials of the active
# mesh and the materials with layers of the other meshes.

def texture_sets(context):
    """[(material, mesh object)] of the Texture Set List: each material of the active mesh once, then the materials with layers
    of the other meshes of the view layer (a material that two meshes share is listed under the first)."""
    ob = mesh_of(context)
    found, seen = [], set()
    others = sorted((o for o in context.view_layer.objects if o.type == 'MESH' and o != ob), key=lambda o: o.name)
    for mesh in ([ob] if ob is not None else []) + others:
        for slot in mesh.material_slots:
            mat = slot.material
            if mat is not None and mat.name not in seen and (mesh == ob or mat.m3d_layers):
                seen.add(mat.name)
                found.append((mat, mesh))
    return found


def hidden_sets(ob):
    """Names of the materials whose polygons are hidden on this mesh (the eye of the Texture Set List)."""
    return set(ob.data.get("m3d_hidden_sets", ()))


def apply_hidden(ob, names):
    """Hide the polygons of the materials `names` on the mesh, show the others (one pass over the polygons, in numpy)."""
    mesh = ob.data
    slots = np.array([s.material.name if s.material else "" for s in ob.material_slots] or [""], dtype=object)
    index = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("material_index", index)
    hide = np.isin(slots[np.clip(index, 0, len(slots) - 1)], list(names))
    mesh.polygons.foreach_set("hide", hide)
    mesh.update()
    if names:
        mesh["m3d_hidden_sets"] = sorted(names)
    elif "m3d_hidden_sets" in mesh:
        del mesh["m3d_hidden_sets"]


def activate_set(context, ob, mat):
    """Make `mat` the active material of `ob` and `ob` the active mesh (Texture Paint Mode goes with it). False when `ob` has
    no slot with the material."""
    slots = [s.material for s in ob.material_slots]
    if mat not in slots:
        return False
    if ob != context.active_object:
        mode = context.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for other in context.selected_objects:
            other.select_set(False)
        ob.hide_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        if mode == 'PAINT_TEXTURE':
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    ob.active_material_index = slots.index(mat)
    if mat.m3d_layers:
        L.sync_target(context, mat, False)
    return True


class _SetOp:
    object: StringProperty(description="Mesh of the texture set")
    material: StringProperty(description="Material of the texture set")

    def target(self):
        ob, mat = bpy.data.objects.get(self.object), bpy.data.materials.get(self.material)
        return (ob, mat) if ob is not None and ob.type == 'MESH' and mat is not None else (None, None)


class M3D_OT_tex_set(_SetOp, Operator):
    """Paint this texture set: its material becomes the active one and the Layers show it"""
    bl_idname = "m3d.tex_set"
    bl_label = "Texture Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob, mat = self.target()
        if ob is None or not activate_set(context, ob, mat):
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_tex_set_visible(_SetOp, Operator):
    """Show or hide this texture set in the 3D view (its polygons, or its mesh when it is not the active one)"""
    bl_idname = "m3d.tex_set_visible"
    bl_label = "Show / Hide Texture Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob, mat = self.target()
        if ob is None:
            return {'CANCELLED'}
        if mat.name in hidden_sets(ob):
            names = hidden_sets(ob) - {mat.name}
        else:
            names = hidden_sets(ob) | {mat.name}
        if ob.mode == 'EDIT':
            return {'CANCELLED'}
        apply_hidden(ob, names)
        return {'FINISHED'}


class M3D_OT_tex_isolate(Operator):
    """Isolate the active texture set (Alt+Q): only its polygons are shown, and the other meshes are hidden; again shows
    everything"""
    bl_idname = "m3d.tex_isolate"
    bl_label = "Isolate Texture Set"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and ob.active_material is not None and ob.mode != 'EDIT'

    def execute(self, context):
        ob, scene = mesh_of(context), context.scene
        mat = ob.active_material
        iso = scene.get("m3d_isolated")
        if iso is not None:   # again: show what was hidden
            for name in iso:
                other = bpy.data.objects.get(name)
                if other is not None:
                    other.hide_set(False)
            del scene["m3d_isolated"]
            for o in {*context.view_layer.objects, ob}:
                if o.type == 'MESH' and o.data.get("m3d_hidden_sets") is not None:
                    apply_hidden(o, set())
            self.report({'INFO'}, "All texture sets shown")
            return {'FINISHED'}
        slots = {s.material.name for s in ob.material_slots if s.material} - {mat.name}
        apply_hidden(ob, slots)
        hid = [o.name for o in context.view_layer.objects if o.type == 'MESH' and o != ob and not o.hide_get()]
        for name in hid:
            bpy.data.objects[name].hide_set(True)
        scene["m3d_isolated"] = hid
        self.report({'INFO'}, "Only %s is shown (Alt+Q shows all)" % mat.name)
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
# Display modes of the 3D and 2D views: the material, one channel on its own, a baked mesh map, the mask of the active layer.
# A mode is a string: "MATERIAL", "CHANNEL:<channel id>", "MAP:<image label>", "MASK". In the 3D view the material's own
# nodes show them (m3d_layers: channel view, Show Mask, Show Map); in the 2D view the image shown is the one.

MESH_MAPS = (("Normal", "Normal"), ("AO", "Ambient Occlusion"), ("Curvature", "Curvature"), ("Position", "Position"),
             ("Thickness", "Thickness"), ("ID", "ID"), ("WorldNormal", "World Normal"), ("Displacement", "Displacement"))
# (the label of the image `Name_<label>` a bake makes, its text)
MAP_TEXT = dict(MESH_MAPS)


def mesh_maps(ob):
    """[(label, image)] of the baked mesh maps the mesh has (its texture set's images, see map_image; a bake marks its images, so
    a paint channel image that happens to be called Cube_Normal is not one)."""
    found = [(label, map_image(ob, label)) for label, _text in MESH_MAPS] if ob is not None else []
    return [(label, image) for label, image in found if image is not None and image.get("m3d_bake") == label]


def mode_label(mode):
    kind, _, key = mode.partition(":")
    if kind == 'CHANNEL':
        return CHANNEL_BY_ID[key].label
    if kind == 'MAP':
        return MAP_TEXT.get(key, key)
    return {'MATERIAL': "Material", 'MASK': "Mask"}[kind]


def mode_icon(mode):
    return {'MATERIAL': 'SHADING_TEXTURE', 'CHANNEL': 'IMAGE_RGB', 'MAP': 'MESH_DATA', 'MASK': 'MOD_MASK'}[mode.partition(":")[0]]


def layer_image(mat, layer, channel):
    """The image a layer paints for a channel (Paint layers), None for the others."""
    return entry_of(layer, channel).image if layer is not None and layer.kind == 'PAINT' else None


def channel_image(mat, channel):
    """The image of `channel` that is painted: the active layer's (a stack), else the material's paint slot."""
    if mat.m3d_layers:
        return layer_image(mat, active_layer(mat), channel)
    found = channel_slots(mat)
    return found[channel][1] if channel in found else None


def material_image(context, mat):
    """The image the brush paints on now (the 2D view's Material mode)."""
    if mat.m3d_layers:
        return L.target_image(context, mat, False)
    slots = list(mat.texture_paint_images)
    return slots[mat.paint_active_slot] if 0 <= mat.paint_active_slot < len(slots) else None


def view_mode_3d(context, space):
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    if mat is not None and mat.m3d_show_mask:
        return 'MASK'
    if mat is not None and mat.m3d_show_map:
        image = bpy.data.images.get(mat.m3d_show_map)
        if image is not None:
            return "MAP:" + image.get("m3d_bake", "")
    if mat is not None and channel_view_on(space.shading) and active_channel(mat):
        return "CHANNEL:" + active_channel(mat)
    return 'MATERIAL'


_shown_2d = {}   # 2D view (its pointer) -> the mode last set there: the image alone can't tell Material from the channel being painted


def image_of_mode(context, mode):
    """The image the 2D view shows for `mode` (None when there is none)."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    if mat is None:
        return None
    kind, _, key = mode.partition(":")
    if kind == 'MAP':
        return dict(mesh_maps(ob)).get(key)
    if kind == 'MASK':
        layer = active_layer(mat)
        effect = L.paint_effect(layer) if layer is not None else None
        return effect.image if effect is not None else None
    return channel_image(mat, key) if kind == 'CHANNEL' else material_image(context, mat)


def space_key(space):
    return space.as_pointer() if hasattr(space, "as_pointer") else id(space)


def view_mode_2d(context, space):
    """The mode the 2D view shows: the one set there last when its image is still the one shown, else the first mode whose
    image is it."""
    ob = mesh_of(context)
    if space.image is None or ob is None or ob.active_material is None:
        return 'MATERIAL'
    want = _shown_2d.get(space_key(space))
    if want is not None and image_of_mode(context, want) == space.image:
        return want
    modes = ['MATERIAL', *("MAP:" + label for label, _image in mesh_maps(ob)), 'MASK', *("CHANNEL:" + ch.id for ch in CHANNELS)]
    return next((mode for mode in modes if image_of_mode(context, mode) == space.image), 'MATERIAL')


def show_in_3d(context, space, mode):
    """Show `mode` in the 3D view `space`. Returns what is missing, empty when done."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    kind, _, key = mode.partition(":")
    image = None
    if kind == 'CHANNEL':
        if mat is None or key not in channel_slots(mat):
            return "No %s channel yet" % CHANNEL_BY_ID[key].label
        select_channel(mat, key)
    elif kind == 'MAP':
        image = dict(mesh_maps(ob)).get(key)
        if image is None:
            return "No %s map yet: bake the mesh maps" % MAP_TEXT.get(key, key)
    elif kind == 'MASK' and (mat is None or active_layer(mat) is None):
        return "Pick a layer to see its mask"
    if mat is not None:
        L.show_view(mat, mask=kind == 'MASK', map_name=image.name if image is not None else "")
    channel_view_set(space.shading, kind == 'CHANNEL')
    if kind != 'CHANNEL' and space.shading.type == 'SOLID':
        space.shading.type = 'MATERIAL'   # (the mask and the maps are shown by the material: Solid would not draw them)
    return ""


def show_in_2d(context, space, mode):
    """Show `mode` in the 2D view `space` (an Image Editor): the image of the channel, the map or the mask."""
    kind, _, key = mode.partition(":")
    ob = mesh_of(context)
    if ob is None or ob.active_material is None:
        return "Select a mesh with a material"
    if kind == 'CHANNEL' and key in channel_slots(ob.active_material):
        select_channel(ob.active_material, key)   # (the channel is the one painted, like in the 3D view)
    image = image_of_mode(context, mode)
    if image is None:
        return "Nothing to show here: %s" % ("the %s map is not baked" % MAP_TEXT.get(key, key) if kind == 'MAP'
                                            else "the layer has no image for it")
    space.image = image
    space.ui_mode = 'PAINT'   # (the painting keys only work in Paint mode: a map shown here is painted like any image: Undo)
    _shown_2d[space_key(space)] = mode
    return ""


def modes_of(context, kind):
    """The display modes a key cycles through: the material first, then the channels the material has ('CHANNEL') or the
    mesh maps it has ('MAP')."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    if kind == 'MAP':
        return ['MATERIAL'] + ["MAP:" + label for label, _image in mesh_maps(ob)]
    found = channel_slots(mat) if mat is not None else {}
    return ['MATERIAL'] + ["CHANNEL:" + ch.id for ch in CHANNELS if ch.id in found]


def view_target(context):
    """('3D' or '2D', its area) the display mode keys and the dropdown act on: the view under the mouse, else the 3D view."""
    area = context.area
    if area is not None and area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
        return ('3D' if area.type == 'VIEW_3D' else '2D'), area
    view, image = view_areas(context.screen)
    return ('3D', view) if view is not None else ('2D', image)


def view_areas(screen):
    """(3D area, 2D area) of the screen: the larger of each, None for a missing one (a maximized view hides the other)."""
    areas = screen.areas if screen is not None else []
    pick = lambda kind: max((a for a in areas if a.type == kind), key=lambda a: a.width * a.height, default=None)
    return pick('VIEW_3D'), pick('IMAGE_EDITOR')


def set_view_mode(context, mode):
    """Show `mode` in the view under the mouse (or the 3D view). Returns what is missing, empty when done."""
    where, area = view_target(context)
    if area is None:
        return "No 3D or 2D view here"
    space = area.spaces.active
    return show_in_3d(context, space, mode) if where == '3D' else show_in_2d(context, space, mode)


class M3D_OT_tex_view_mode(Operator):
    """Show the material, a channel on its own, a baked mesh map or the mask of the active layer in this view"""
    bl_idname = "m3d.tex_view_mode"
    bl_label = "Display Mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: StringProperty(default='MATERIAL', description="MATERIAL, CHANNEL:<channel>, MAP:<map> or MASK")

    @classmethod
    def description(cls, _context, props):
        return "Show: " + mode_label(props.mode)

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        try:
            note = set_view_mode(context, self.mode)
        except (KeyError, ValueError):
            return {'CANCELLED'}
        if note:
            self.report({'WARNING'}, note)
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_tex_view_cycle(Operator):
    """Show the next (or previous) channel (C) or baked mesh map (B) in the view under the mouse; after the last one the
    material is shown again"""
    bl_idname = "m3d.tex_view_cycle"
    bl_label = "Cycle Display Mode"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=(('CHANNEL', "Channels", ""), ('MAP', "Mesh Maps", "")))
    delta: IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Show the %s %s in this view" % ("next" if props.delta > 0 else "previous",
                                                "channel" if props.kind == 'CHANNEL' else "mesh map")

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        modes = modes_of(context, self.kind)
        where, area = view_target(context)
        if area is None:
            return {'CANCELLED'}
        space = area.spaces.active
        now = view_mode_3d(context, space) if where == '3D' else view_mode_2d(context, space)
        i = (modes.index(now) + self.delta) % len(modes) if now in modes else 1 if self.delta > 0 else len(modes) - 1
        if len(modes) == 1:
            self.report({'INFO'}, "No %s yet: add a channel in Texture Set Settings" % ("channels" if self.kind == 'CHANNEL'
                                                                                           else "mesh maps (Bake Mesh Maps)"))
            return {'CANCELLED'}
        note = set_view_mode(context, modes[i])
        if note:
            self.report({'WARNING'}, note)
            return {'CANCELLED'}
        self.report({'INFO'}, "Showing " + mode_label(modes[i]))
        return {'FINISHED'}


class M3D_MT_tex_view_mode(Menu):
    """Display mode of this view"""
    bl_label = "Display Mode"

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mat = ob.active_material if ob is not None else None
        found = channel_slots(mat) if mat is not None else {}
        have = {label for label, _image in mesh_maps(ob)}

        def add(mode, enabled=True):
            sub = layout.row()
            sub.enabled = enabled
            sub.operator("m3d.tex_view_mode", text=mode_label(mode), icon=mode_icon(mode)).mode = mode

        add('MATERIAL')
        layout.separator()
        layout.label(text="Channels (C)")
        for ch in CHANNELS:
            add("CHANNEL:" + ch.id, ch.id in found)
        layout.separator()
        layout.label(text="Mesh maps (B)")
        for label, _text in MESH_MAPS:
            add("MAP:" + label, label in have)
        layout.separator()
        add('MASK', mat is not None and active_layer(mat) is not None)


def draw_view_mode(layout, context):
    """The display mode dropdown at the top right of the 3D view and the 2D view of the Texture workspace."""
    area = context.area
    ob = mesh_of(context)
    if area is None or ob is None or area.type not in {'VIEW_3D', 'IMAGE_EDITOR'}:
        return
    space = area.spaces.active
    mode = view_mode_3d(context, space) if area.type == 'VIEW_3D' else view_mode_2d(context, space)
    row = layout.row()
    row.ui_units_x = 7   # (room for the longest names: Ambient Occlusion, Displacement)
    row.menu("M3D_MT_tex_view_mode", text=mode_label(mode), icon=mode_icon(mode))


# -----------------------------------------------------------------------------
# Painting keys (Image Paint keymap, see presets/keyconfig/Maelstrom3D.py): Lazy Mouse, Symmetry, Stencil, brush values by dragging,
# the environment, framing, the layout of the views, Bake Mesh Maps.

class _PaintOp:
    @classmethod
    def poll(cls, context):
        return context.mode == 'PAINT_TEXTURE' and image_brush(context) is not None


class M3D_OT_tex_lazy(_PaintOp, Operator):
    """Lazy Mouse (D): the stroke follows the cursor with a delay, which smooths it"""
    bl_idname = "m3d.tex_lazy"
    bl_label = "Lazy Mouse"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        brush = image_brush(context)
        brush.use_smooth_stroke = not brush.use_smooth_stroke
        self.report({'INFO'}, "Lazy Mouse " + ("on" if brush.use_smooth_stroke else "off"))
        return {'FINISHED'}


class M3D_OT_tex_symmetry(_PaintOp, Operator):
    """Symmetry (L): paint on both sides of the mesh's X axis"""
    bl_idname = "m3d.tex_symmetry"
    bl_label = "Symmetry"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None and context.mode == 'PAINT_TEXTURE'

    def execute(self, context):
        mesh = mesh_of(context).data
        mesh.use_mirror_x = not mesh.use_mirror_x
        self.report({'INFO'}, "Symmetry (X) " + ("on" if mesh.use_mirror_x else "off"))
        return {'FINISHED'}


class M3D_OT_tex_stencil(_PaintOp, Operator):
    """Stencil (S): project the brush texture through the screen; the stencil keys of the Image Paint keymap move, scale and
    turn it. Again to paint it as an ordinary texture"""
    bl_idname = "m3d.tex_stencil"
    bl_label = "Stencil"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            on = stencil_toggle(image_brush(context))
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        self.report({'INFO'}, "Stencil on: RMB moves it, Shift+RMB scales it, Ctrl+RMB turns it" if on else "Stencil off")
        return {'FINISHED'}


def drag_brush(mode, size_owner, flow_owner, brush, slot, start, dx, dy):
    """Set what a Ctrl+drag changes, `dx` and `dy` pixels (at UI scale 1) from where the drag began, from the `start` values
    (size, hardness, flow, angle). Ctrl+RMB: size by the width of the drag, hardness by its height; Ctrl+LMB: flow by the width,
    the angle of the alpha or texture `slot` by the height. Returns the text for the Status Bar."""
    size, hardness, flow, angle = start
    if mode == 'SIZE_HARDNESS':
        size_owner.size = int(min(max(size + dx, 1), 2000))
        brush.hardness = min(max(hardness + dy / 300.0, 0.0), 1.0)
        return "Size %d px   Hardness %.2f" % (size_owner.size, brush.hardness)
    flow_owner.strength = min(max(flow + dx / 300.0, 0.0), 1.0)
    if slot is not None:
        slot.angle = angle + dy * 0.01
    return "Flow %.2f   Angle %d" % (flow_owner.strength, round(math.degrees(slot.angle)) if slot is not None else 0)


class M3D_OT_tex_brush_drag(_PaintOp, Operator):
    """Ctrl+RMB drag: sideways changes the brush size, up and down its hardness. Ctrl+LMB drag: sideways changes the flow,
    up and down the angle of the alpha or texture. With a stencil on, Ctrl+RMB turns the stencil instead"""
    bl_idname = "m3d.tex_brush_drag"
    bl_label = "Adjust Brush"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(items=(('SIZE_HARDNESS', "Size and Hardness", "Ctrl+RMB drag: sideways the size, up and down the hardness"),
                              ('FLOW_ANGLE', "Flow and Angle", "Ctrl+LMB drag: sideways the flow, up and down the angle")))

    @classmethod
    def description(cls, _context, props):
        return ("Drag: sideways the size, up and down the hardness" if props.mode == 'SIZE_HARDNESS'
                else "Drag: sideways the flow, up and down the angle")

    def invoke(self, context, event):
        brush = image_brush(context)
        if self.mode == 'SIZE_HARDNESS' and stencil_on(brush):   # (Ctrl+RMB turns a stencil: Blender's key)
            bpy.ops.brush.stencil_control('INVOKE_DEFAULT', mode='ROTATION')
            return {'FINISHED'}
        ups = context.tool_settings.image_paint.unified_paint_settings
        self.brush, self.ups = brush, ups
        self.start = (event.mouse_x, event.mouse_y)
        self.scale = ui_scale_factor(context)
        self.release = 'RIGHTMOUSE' if self.mode == 'SIZE_HARDNESS' else 'LEFTMOUSE'
        self.size_owner = ups if ups.use_unified_size else brush
        self.flow_owner = ups if ups.use_unified_strength else brush
        slot = brush.mask_texture_slot if brush.mask_texture is not None else brush.texture_slot if brush.texture is not None else None
        self.slot = slot
        self.values = (self.size_owner.size, brush.hardness, self.flow_owner.strength, slot.angle if slot is not None else 0.0)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def apply(self, context, event):
        dx, dy = (event.mouse_x - self.start[0]) / self.scale, (event.mouse_y - self.start[1]) / self.scale
        context.workspace.status_text_set(drag_brush(self.mode, self.size_owner, self.flow_owner, self.brush, self.slot, self.values, dx, dy))

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self.apply(context, event)
        elif event.type == self.release and event.value == 'RELEASE':
            context.workspace.status_text_set(None)
            return {'FINISHED'}
        elif event.type == 'ESC' and event.value == 'PRESS':
            size, hardness, flow, angle = self.values
            self.size_owner.size, self.brush.hardness, self.flow_owner.strength = int(size), hardness, flow
            if self.slot is not None:
                self.slot.angle = angle
            context.workspace.status_text_set(None)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class M3D_OT_tex_env_rotate(Operator):
    """Shift+RMB drag: turn the Material Preview environment around the model. With a stencil on, Shift+RMB scales the stencil
    instead"""
    bl_idname = "m3d.tex_env_rotate"
    bl_label = "Rotate Environment"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'PAINT_TEXTURE' and view3d_space(context) is not None

    def invoke(self, context, event):
        if stencil_on(image_brush(context)):
            bpy.ops.brush.stencil_control('INVOKE_DEFAULT', mode='SCALE')
            return {'FINISHED'}
        self.shading = view3d_space(context).shading
        self.start, self.angle = event.mouse_x, self.shading.studiolight_rotate_z
        self.shading.use_scene_world = False if self.shading.type == 'MATERIAL' else self.shading.use_scene_world
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self.shading.studiolight_rotate_z = self.angle + (event.mouse_x - self.start) * 0.01 / ui_scale_factor(context)
        elif event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        elif event.type == 'ESC' and event.value == 'PRESS':
            self.shading.studiolight_rotate_z = self.angle
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class M3D_OT_tex_frame(Operator):
    """Frame the model in the 3D view, or the whole image in the 2D view (F)"""
    bl_idname = "m3d.tex_frame"
    bl_label = "Frame"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        area = context.area
        if area is not None and area.type == 'IMAGE_EDITOR':
            return bpy.ops.image.view_all(fit_view=True)
        ob = mesh_of(context)
        return bpy.ops.view3d.view_selected() if ob is not None and ob.select_get() else bpy.ops.view3d.view_all(center=False)


_fit = {"workspace": None, "seen": {}}   # the Texture workspace the 2D views were framed in; 2D view (pointer) -> {(image, size)} it framed


def fit_view(win, area, region, space):
    """Frame the whole image in a 2D view (image.view_all, fit)."""
    try:
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region, space_data=space):
            bpy.ops.image.view_all(fit_view=True)
    except RuntimeError:
        pass   # (a timer that raises is removed: the view is framed with F instead)


def follow(wm):
    """Timer (m3d_workspace._follow_workspace): the 2D view of the Texture workspace frames its image (image.view_all, fit) when
    the workspace opens, when a view is new, and the first time it shows an image (or one of another size, or none): Blender keeps
    the view of each image (a new one is shown 1:1, a small square in a big empty area), so an image framed once keeps the
    view you gave it when it comes back."""
    win = wm.windows[0] if wm.windows else None
    if win is None:
        return
    ws = win.workspace
    if W.workspace_kind(ws) != 'TEXTURE':
        _fit["workspace"] = None
        return
    if _fit["workspace"] != ws.name:
        _fit["workspace"], _fit["seen"] = ws.name, {}
    for area in win.screen.areas:
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area.type == 'IMAGE_EDITOR' else None
        if region is None or region.width < 100 or region.height < 100:   # (no 2D view, or not drawn yet)
            continue
        space = area.spaces.active
        image = space.image
        token = (image.session_uid, L.image_size(image)) if image is not None else (0, (0, 0))
        seen = _fit["seen"].setdefault(space.as_pointer(), set())
        if token not in seen:
            seen.add(token)
            fit_view(win, area, region, space)


class M3D_OT_tex_layout(Operator):
    """View layout: the 3D view and the 2D view side by side, or one of them on the whole window (the other panels are hidden
    while it is maximized)"""
    bl_idname = "m3d.tex_layout"
    bl_label = "View Layout"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(items=(('BOTH', "3D | 2D", "The 3D view and the 2D view side by side"),
                              ('3D', "3D Only", "Maximize the 3D view"), ('2D', "2D Only", "Maximize the 2D view")))

    @classmethod
    def description(cls, _context, props):
        return {'BOTH': "3D and 2D views side by side", '3D': "3D view only (maximized)", '2D': "2D view only (maximized)"}[props.mode]

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.screen is not None

    def execute(self, context):
        window = context.window
        view, image = view_areas(context.screen)
        if (view is None) != (image is None):   # one view is maximized: back to the layout first
            with context.temp_override(window=window, screen=context.screen, area=view or image):
                bpy.ops.screen.back_to_previous()
            view, image = view_areas(window.screen)
        if self.mode != 'BOTH':
            area = view if self.mode == '3D' else image
            if area is not None:
                region = next(r for r in area.regions if r.type == 'WINDOW')
                with context.temp_override(window=window, screen=window.screen, area=area, region=region):
                    bpy.ops.screen.screen_full_area(use_hide_panels=False)
        _fit["seen"].clear()   # (the 2D view has another size now: it frames its image again)
        return {'FINISHED'}


class M3D_OT_tex_bake_mode(Operator):
    """Bake Mesh Maps (Ctrl+Shift+B): the Layers dock shows the Bake page; Back to Painting returns to the Layers"""
    bl_idname = "m3d.tex_bake_mode"
    bl_label = "Bake Mesh Maps"

    on: BoolProperty(default=True, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return ("Bake mesh maps: set them up and bake in the Bake page of the Layers dock (Ctrl+Shift+B)" if props.on
                else "Back to painting: show the Layers again")

    def execute(self, context):
        context.workspace.m3d_page_right = "tex_bake" if self.on else "tex_layers"
        for area in context.screen.areas:
            area.tag_redraw()
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
    page = "tex_brush_grid"   # (the old tray only: the Assets panel has the brushes)
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


MATERIAL_BUTTONS = (   # (channel, button text, short text): the channels of the brush material, in the order of the buttons
    ('BASE_COLOR', "color", "C"), ('HEIGHT', "height", "H"), ('ROUGHNESS', "rough", "R"), ('METALLIC', "metal", "M"),
    ('EMISSION', "emit", "E"))


def paint_layer_active(context):
    """The active layer when a stroke paints the channels of the brush material (a paint layer that is not frozen, with
    Paint Mask off), else None."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    layer = active_layer(mat) if mat is not None and principled_of(mat) is not None else None
    return layer if layer is not None and layer.kind == 'PAINT' and not layer.paint_mask and not L.in_frozen(layer) else None


def draw_material_toggles(layout, context, short=False):
    """One button per channel of the brush material: the channels one stroke paints."""
    brush = context.scene.m3d_tex.brush
    row = layout.row(align=True)
    for cid, text, initial in MATERIAL_BUTTONS:
        row.prop(brush, "use_" + cid.lower(), text=initial if short else text, toggle=True)
    return row


def draw_material(layout, context, values=True):
    """The brush material: the channel buttons and (`values`) a value for each channel that is on; or what to do first."""
    if paint_layer_active(context) is None:
        reason(layout, "Add a Paint Layer to paint several channels with one stroke")
        return
    brush = context.scene.m3d_tex.brush
    row = draw_material_toggles(layout, context)
    row.scale_y = 1.2
    if values:
        col = layout.column(align=True)
        split_props(col)
        ibrush = image_brush(context)
        for cid, _text, _initial in MATERIAL_BUTTONS:
            if not getattr(brush, "use_" + cid.lower()):
                continue
            label = CHANNEL_BY_ID[cid].label
            if cid == 'BASE_COLOR':
                if ibrush is not None:
                    UnifiedPaintPanel.prop_unified_color(col, context, ibrush, "color", text=label)
            elif cid in L.SCALARS:
                col.prop(brush, cid.lower(), text=label, slider=True)
            else:
                col.prop(brush, cid.lower(), text=label)
    if not L.brush_channels(context):
        reason(layout, "None on: the channel shown (C) is painted alone")
    else:
        reason(layout, "One stroke paints every channel that is on; the Eraser erases them all")


class PROPERTIES_PT_m3d_tx_material(_Page, Panel):
    page = "tex_brushes"
    bl_label = "Material"

    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and props_context(context) == 'PAINT'

    def draw(self, context):
        draw_material(self.layout, context)


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


# --- Properties - Paint: the sections for the tool (page tex_paint_props). Each control is a property of Blender's brush, of its
# alpha (Texture Mask) or stencil (Texture) slot, or of the Project Paint settings; what Blender has no counterpart for is left out
# (Stroke Opacity: Flow is the brush strength, and Accumulate says whether a stroke may go past it; Size and Flow jitter; the
# alpha's Tangent and UV alignments: a stamp is always placed in screen space).

PAINT_PAGE = "tex_paint_props"
ALL_TOOLS = {'PAINT', 'ERASER', 'PROJECTION', 'POLYFILL', 'SMUDGE', 'CLONE', 'OTHER'}
BRUSH_TOOLS_SET = ALL_TOOLS - {'POLYFILL'}   # the tools that have a brush section ('OTHER': a brush the strip has no tool for)


def paint_tool(context):
    """The tool the Paint sections follow: the tool of the strip, 'OTHER' for a brush that has none (Blur, Mask), None without a
    texture brush."""
    brush = image_brush(context)
    return None if brush is None else tool_of(context) or 'OTHER'


def unified(context, brush, flag):
    """Where a brush setting lives: in the Unified Paint Settings when `flag` ("use_unified_size") is on, else in the brush."""
    ups = paint_settings(context).unified_paint_settings
    return ups if getattr(ups, flag) else brush


class _PaintPage(_Page):
    """A section of Properties - Paint (also of Properties - Mask while the mask is painted), drawn for the tools in `tools`."""
    page = PAINT_PAGE
    tools = ALL_TOOLS

    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and paint_tool(context) in cls.tools


class _PaintStock(_BrushPage):
    """The same for a section made of one of Blender's brush panels (Clone, Cursor): its own poll comes with it."""
    page = PAINT_PAGE
    tools = BRUSH_TOOLS_SET

    @classmethod
    def page_poll(cls, context):
        return super().page_poll(context) and paint_tool(context) in cls.tools


def draw_swatches(layout, context):
    """One swatch for each channel of the brush material: the brush color, the value of each scalar channel as a grey, the
    emission color; the channels that are off are dimmed."""
    brush, ibrush = context.scene.m3d_tex.brush, image_brush(context)
    row = layout.row(align=True)
    for cid, _text, _initial in MATERIAL_BUTTONS:
        sub = row.row(align=True)
        sub.active = getattr(brush, "use_" + cid.lower())
        if cid == 'BASE_COLOR':
            sub.prop(unified(context, ibrush, "use_unified_color"), "color", text="")
        else:
            sub.prop(brush, "swatch_" + cid.lower() if cid in L.SCALARS else cid.lower(), text="")


def draw_previews(layout, context):
    """The brush (its thumbnail from the brush library) with the name of the tool, and the material swatches."""
    tool, name = paint_tool(context), brush_name(context)
    icon = S.brush_icons(BRUSH_ASSET, [name]).get(name, 0) if name else 0
    split = layout.split(factor=0.3)
    if icon:
        split.template_icon(icon_value=icon, scale=3.0)
    else:
        split.label(text="", icon='BRUSH_DATA')
    col = split.column(align=True)
    col.label(text=TOOL_BY_ID[tool][1] if tool in TOOL_BY_ID else name)
    col.label(text=name)
    if paint_layer_active(context) is not None and tool not in {'SMUDGE', 'CLONE'}:
        draw_swatches(col, context)


def draw_brush(layout, context):
    """Size, Hardness, Flow (Accumulate), Spacing, Size Space; Angle, Follow Path and the jitters; the Project Paint options."""
    split_props(layout)
    brush, ipaint = image_brush(context), paint_settings(context)
    ups = ipaint.unified_paint_settings
    col = layout.column()
    size_owner = unified(context, brush, "use_unified_size")
    UnifiedPaintPanel.prop_unified(col, context, brush, "unprojected_size" if size_owner.use_locked_size == 'SCENE' else "size",
                                   unified_paint_settings_override=ups, unified_name="use_unified_size",
                                   pressure_name="use_pressure_size", text="Size", slider=True)
    col.prop(brush, "hardness", slider=True)
    UnifiedPaintPanel.prop_unified(col, context, brush, "strength", unified_paint_settings_override=ups,
                                   unified_name="use_unified_strength", pressure_name="use_pressure_strength", text="Flow",
                                   slider=True)
    if brush.image_paint_capabilities.has_accumulate:
        col.prop(brush, "use_accumulate", text="Accumulate")
    row = col.row(align=True)
    row.prop(brush, "spacing", slider=True)
    row.prop(brush, "use_pressure_spacing", text="")
    col.row().prop(size_owner, "use_locked_size", text="Size Space", expand=True)
    slot = brush.mask_texture_slot if brush.mask_texture is not None else None
    if slot is not None and slot.has_texture_angle:
        col.prop(slot, "angle", text="Angle")
        if slot.has_texture_angle_source:
            col.prop(slot, "use_rake", text="Follow Path")
    col.separator()
    row = col.row(align=True)
    row.prop(brush, "jitter" if brush.jitter_unit == 'BRUSH' else "jitter_absolute", text="Position Jitter", slider=True)
    row.prop(brush, "use_pressure_jitter", text="")
    if slot is not None and slot.has_texture_angle_source and brush.brush_capabilities.has_random_texture_angle:
        col.prop(slot, "use_random", text="Angle Jitter")
        if slot.use_random:
            col.prop(slot, "random_angle", text="Amount")
    col.separator()
    col = layout.column(heading="Projection")
    col.prop(ipaint, "use_occlude", text="Occlude")
    col.prop(ipaint, "use_backface_culling", text="Backface Culling")
    col.prop(ipaint, "use_normal_falloff", text="Normal Falloff")
    sub = col.column()
    sub.active = ipaint.use_normal_falloff
    sub.prop(ipaint, "normal_angle", text="Falloff Angle")


def draw_alpha_grid(layout, context, brush, stencil):
    """The alpha library as small tiles: None, then every alpha. They give the brush its alpha (its Texture Mask), or with
    `stencil` its stencil (its Texture, mapped as a Stencil)."""
    names = S.alpha_names()
    icons = S.alpha_icons(names)
    texture = (brush.texture if stencil_on(brush) else None) if stencil else brush.mask_texture
    active = texture.name if texture is not None else ""
    flow = S.tile_grid(layout, context, columns=9)   # (None and the eight starter alphas in one row)
    o = flow.operator("m3d.alpha_pick", text="None", depress=not active)
    o.name, o.stencil = "", stencil
    for name in names:
        o = flow.operator("m3d.alpha_pick", text="" if name in icons else name, icon_value=icons.get(name, 0), depress=active == name)
        o.name, o.stencil = name, stencil


def draw_alpha(layout, context):
    """The alpha of the brush (its Texture Mask): thumbnail, name, Load Alpha, how it is placed, and the library to pick from."""
    brush = image_brush(context)
    texture = brush.mask_texture
    icon = S.alpha_icons([texture.name]).get(texture.name, 0) if texture is not None else 0
    row = layout.row(align=True)
    if icon:
        row.template_icon(icon_value=icon, scale=3.0)
    col = row.column(align=True)
    col.label(text=texture.name if texture is not None else "No alpha: a soft round dab")
    sub = col.row(align=True)
    sub.operator("m3d.alpha_load", text="Load Alpha...", icon='FILE_FOLDER').stencil = False
    if texture is not None:
        o = sub.operator("m3d.alpha_pick", text="", icon='X')
        o.name, o.stencil = "", False
        sub = col.row(align=True)   # Camera: the stamp is laid over the screen (Blender's View Plane mapping)
        for mode, text in (('VIEW_PLANE', "Camera"), ('TILED', "Tiled"), ('RANDOM', "Random"), ('STENCIL', "Stencil")):
            sub.prop_enum(brush.mask_texture_slot, "mask_map_mode", mode, text=text)
    draw_alpha_grid(layout, context, brush, False)


def draw_stencil(layout, context):
    """The stencil: the brush's Texture mapped in screen space. S shows it, RMB moves, Shift+RMB scales, Ctrl+RMB turns it."""
    brush = image_brush(context)
    on = stencil_on(brush)
    row = layout.row(align=True)
    row.operator("m3d.tex_stencil", text="Stencil", icon='IMAGE_PLANE', depress=on)
    sub = row.row(align=True)
    sub.enabled = on
    sub.operator("brush.stencil_reset_transform", text="Reset").mask = False
    sub.operator("brush.stencil_fit_image_aspect", text="Fit").mask = False
    col = layout.column()
    split_props(col)
    col.prop(brush, "texture_overlay_alpha", text="Opacity", slider=True)
    draw_alpha_grid(layout, context, brush, True)
    layout.operator("m3d.alpha_load", text="Load Stencil...", icon='FILE_FOLDER').stencil = True
    reason(layout, "S: show it. RMB moves, Shift+RMB scales, Ctrl+RMB turns it")


def draw_advanced(layout, context):
    """What a stroke is made of (method, falloff, stabilizer, input samples), the seams and dithering, and the settings of the
    brushes that have their own (Blur, Mask)."""
    split_props(layout)
    brush, ipaint = image_brush(context), paint_settings(context)
    col = layout.column()
    col.prop(brush, "stroke_method")
    if brush.stroke_method == 'AIRBRUSH':
        col.prop(brush, "rate", slider=True)
    if brush.image_paint_capabilities.has_space_attenuation:
        col.prop(brush, "use_space_attenuation")
    if brush.brush_capabilities.has_smooth_stroke:
        col.prop(brush, "smooth_stroke_factor", text="Stabilizer", slider=True)
    col.prop(brush, "curve_distance_falloff_preset", text="Falloff")
    if brush.curve_distance_falloff_preset == 'CUSTOM':
        layout.template_curve_mapping(brush, "curve_distance_falloff", brush=True, use_negative_slope=True, show_presets=True)
    UnifiedPaintPanel.prop_unified(col, context, brush, "input_samples", unified_paint_settings_override=ipaint.unified_paint_settings,
                                   unified_name="use_unified_input_samples", slider=True)
    col.prop(ipaint, "seam_bleed")
    col.prop(ipaint, "dither", slider=True)
    col.prop(ipaint, "use_cavity", text="Cavity Mask")
    if ipaint.use_cavity:
        layout.template_curve_mapping(ipaint, "cavity_curve", brush=True)
    if brush.image_brush_type == 'SOFTEN':
        col.row().prop(brush, "direction", expand=True)
        col.prop(brush, "sharp_threshold")
        col.prop(brush, "blur_mode")
    elif brush.image_brush_type == 'MASK':
        col.prop(brush, "weight", text="Mask Value", slider=True)


class PROPERTIES_PT_m3d_tx_pp_canvas(_Page, Panel):
    page = PAINT_PAGE
    bl_label = "Canvas"
    bl_order = 19

    @classmethod
    def page_poll(cls, context):
        mat = mesh_of(context).active_material if ready(context, 'PAINT') else None
        return mat is not None and not paint_slots(mat) and not len(mat.m3d_layers)

    def draw(self, context):
        layout = self.layout
        layout.label(text="No paint slots yet")
        layout.prop(context.scene.m3d_tex, "resolution")
        layout.operator("m3d.tex_channel", text="Add Base Color", icon='ADD').channel = 'BASE_COLOR'


class PROPERTIES_PT_m3d_tx_pp_preview(_PaintPage, Panel):
    bl_label = "Preview"
    bl_options = {'HIDE_HEADER'}
    bl_order = 20

    def draw(self, context):
        draw_previews(self.layout, context)


class PROPERTIES_PT_m3d_tx_pp_projection(_PaintPage, Panel):
    """The Projection tool is a stencil: its section comes first."""
    bl_label = "Projection"
    bl_order = 21
    tools = {'PROJECTION'}

    def draw(self, context):
        draw_stencil(self.layout, context)


class PROPERTIES_PT_m3d_tx_pp_polyfill(_PaintPage, Panel):
    bl_label = "Polygon Fill"
    bl_order = 21
    tools = {'POLYFILL'}

    def draw(self, context):
        layout = self.layout
        layout.row().prop(context.scene.m3d_tex, "fill_mode", expand=True)
        reason(layout, "Click the model: the polygon, UV island or mesh is filled with the material")


class PROPERTIES_PT_m3d_tx_pp_brush(_PaintPage, Panel):
    bl_label = "Brush"
    bl_options = {'DEFAULT_CLOSED'}   # (the toolbar has the controls used all the time)
    bl_order = 22
    tools = BRUSH_TOOLS_SET

    def draw(self, context):
        draw_brush(self.layout, context)


class PROPERTIES_PT_m3d_tx_pp_alpha(_PaintPage, Panel):
    bl_label = "Alpha"
    bl_order = 23
    tools = {'PAINT', 'ERASER', 'OTHER'}

    def draw(self, context):
        draw_alpha(self.layout, context)


class PROPERTIES_PT_m3d_tx_pp_stencil(_PaintPage, Panel):
    bl_label = "Stencil"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 24
    tools = {'PAINT', 'ERASER', 'OTHER'}

    def draw(self, context):
        draw_stencil(self.layout, context)


class PROPERTIES_PT_m3d_tx_pp_clone(_PaintStock, ClonePanel, Panel):
    bl_order = 25


class PROPERTIES_PT_m3d_tx_pp_material(_PaintPage, Panel):
    bl_label = "Material"
    bl_order = 26
    tools = {'PAINT', 'ERASER', 'PROJECTION', 'POLYFILL'}

    @classmethod
    def page_poll(cls, context):
        return super().page_poll(context) and props_context(context) == 'PAINT'

    def draw(self, context):
        draw_material(self.layout, context, values=paint_tool(context) != 'ERASER')


class PROPERTIES_PT_m3d_tx_pp_gray(_PaintPage, Panel):
    """What painting a mask paints: its grays, the brush colors (X swaps them)."""
    bl_label = "Grayscale"
    bl_order = 26
    tools = {'PAINT', 'ERASER', 'PROJECTION', 'POLYFILL'}

    @classmethod
    def page_poll(cls, context):
        return super().page_poll(context) and props_context(context) == 'MASK'

    def draw(self, context):
        layout = self.layout
        brush = image_brush(context)
        row = layout.row(align=True)
        row.prop(unified(context, brush, "use_unified_color"), "color", text="")
        row.prop(unified(context, brush, "use_unified_color"), "secondary_color", text="")
        row.operator("paint.brush_colors_flip", icon='ARROW_LEFTRIGHT', text="")
        reason(layout, "White shows the layer, black hides it")


class PROPERTIES_PT_m3d_tx_pp_advanced(_PaintPage, Panel):
    bl_label = "Advanced"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 27
    tools = BRUSH_TOOLS_SET

    def draw(self, context):
        draw_advanced(self.layout, context)


class PROPERTIES_PT_m3d_tx_pp_cursor(_PaintStock, DisplayPanel, Panel):
    bl_label = "Cursor"
    bl_order = 28


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
        if len(ob.material_slots) > 1 and W.tabs_kind(context) == 'TEXTURE_OLD':   # (the Texture Set List lists them)
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
            channels = [ch.label for ch, _image in L.target_set(context, mat, False)[1]] or [CHANNEL_BY_ID[mat.m3d_channel].label]
            target = layer.name + (" mask" if effect is not None and (layer.paint_mask or layer.kind != 'PAINT')
                                   else ": " + ", ".join(channels))
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
    page = "tex_layer"
    bl_label = "Layer"
    bl_order = 10   # (after the stack in the old Layers tab, after the brush panels in Properties)

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


def draw_mask_stack(layout, context, mat, layer, explain=True):
    """The mask of a layer: how it works (`explain`; always while it has no effects), its effects (list, order, add, remove, save),
    Paint Mask, Show Mask, Rebake Maps, Invert. False when it has no effects yet (the buttons to make one are drawn)."""
    if explain or not layer.mask_stack:
        first, _dot, second = MASK_HELP.partition(". ")   # (two lines: the dock can be narrow)
        reason(layout, first + ".")
        layout.label(text=second)
    if not layer.mask_stack:
        row = layout.row(align=True)
        row.operator("m3d.layer_mask_add", text="White (Show All)", icon='ADD').fill = 'WHITE'
        row.operator("m3d.layer_mask_add", text="Black (Hide All)", icon='ADD').fill = 'BLACK'
        layout.menu("M3D_MT_mask_add", icon='ADD')
        reason(layout, "No mask: the layer shows everywhere")
        return False
    row = layout.row()
    row.template_list("M3D_UL_mask_effects", "", layer, "mask_stack", layer, "mask_index", rows=4,
                      sort_reverse=True, sort_lock=True)
    col = row.column(align=True)
    col.operator("m3d.mask_effect_move", text="", icon='TRIA_UP').delta = 1
    col.operator("m3d.mask_effect_move", text="", icon='TRIA_DOWN').delta = -1
    col.separator()
    col.operator("m3d.mask_effect_duplicate", text="", icon='DUPLICATE')
    col.operator("m3d.mask_effect_remove", text="", icon='TRASH')
    row = layout.row(align=True)
    row.menu("M3D_MT_mask_add", icon='ADD')
    row.operator("m3d.library_save", text="", icon='ASSET_MANAGER').kind = 'MASK'
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
    return True


def draw_effect(layout, effect):
    """The settings of a mask effect (its kind decides which: MK.PARAM_UI), and a note on what it does."""
    col = layout.column()
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


class PROPERTIES_PT_m3d_tx_mask(_Page, Panel):
    page = "tex_mask"
    bl_label = "Mask"
    bl_order = 11

    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and has_active_layer(mesh_of(context).active_material)

    def draw(self, context):
        mat = mesh_of(context).active_material
        layer = active_layer(mat)
        layout = frozen_banner(self.layout, mat, layer)
        if not draw_mask_stack(layout, context, mat, layer):
            return
        effect = L.active_effect(layer)
        if effect is None:
            return
        box = layout.box()
        box.label(text=effect.name, icon=MK.KIND_BY_ID[effect.kind].icon)
        draw_effect(box, effect)


# --- Properties - Fill, Folder and Mask: the layer's own sections (pages tex_fill_props, tex_folder_props, tex_mask_props)

FILL_PAGE, FOLDER_PAGE, MASK_PAGE = "tex_fill_props", "tex_folder_props", "tex_mask_props"
FILL_BUTTONS = (*MATERIAL_BUTTONS, ('NORMAL', "nrm", "N"))   # the channels a fill layer can have: the brush material's, and Normal
EFFECT_TYPES = {'PAINT': "Paint", 'FILL': "Fill", 'EDGES': "Generator", 'CAVITY': "Generator", 'TOPDOWN': "Generator",
                'THICKNESS': "Generator", 'NOISE': "Generator", 'COLORID': "Generator", 'LEVELS': "Levels", 'BLUR': "Filter",
                'INVERT': "Filter", 'SHARPEN': "Filter"}


class _LayerPage(_Page):
    """A section for the active layer."""
    @classmethod
    def page_poll(cls, context):
        return ready(context, 'PAINT') and has_active_layer(mesh_of(context).active_material)


def draw_fill(layout, layer):
    """Fill: the projection (UV: a texture follows the UV map) and the UV transform of the layer's textures."""
    col = layout.column(align=True)
    col.active = any(L.has_texture(layer, ch.id) for ch in CHANNELS)
    for prop, text in (("uv_tiling", "Tiling"), ("uv_rotation", "Rotation"), ("uv_offset", "Offset")):
        split = col.split(factor=0.3, align=True)
        split.label(text=text)
        split.row(align=True).prop(layer, prop, text="")   # (the two numbers of Tiling and Offset side by side)
    layout.operator("m3d.layer_fill_reset", icon='LOOP_BACK')
    reason(layout, "UV projection: textures follow the UV map")


def draw_fill_material(layout, layer):
    """Material of a fill layer: a button for each channel it can have, then for each channel it has the value, or the texture
    that replaces it."""
    row = layout.row(align=True)
    row.scale_y = 1.2
    for cid, text, _initial in FILL_BUTTONS:
        row.prop(entry_of(layer, cid), "use", text=text, toggle=True)
    for cid, _text, _initial in FILL_BUTTONS:
        e = entry_of(layer, cid)
        if not e.use:
            continue
        ch = CHANNEL_BY_ID[cid]
        layout.separator(factor=0.5)
        col = layout.column(align=True)
        sub = col.column(align=True)
        sub.active = e.texture is None
        if cid == 'NORMAL':
            sub.label(text="Normal: flat")
        elif cid in L.SCALARS:
            sub.prop(e, "value", text=ch.label, slider=True)
        else:
            sub.prop(e, "color", text=ch.label)
        col.template_ID(e, "texture", open="image.open")
    reason(layout, "A texture replaces the value of its channel")


class PROPERTIES_PT_m3d_tx_fl_fill(_LayerPage, Panel):
    page = FILL_PAGE
    bl_label = "Fill"
    bl_order = 20

    def draw(self, context):
        mat = mesh_of(context).active_material
        draw_fill(frozen_banner(self.layout, mat, active_layer(mat)), active_layer(mat))


class PROPERTIES_PT_m3d_tx_fl_material(_LayerPage, Panel):
    page = FILL_PAGE
    bl_label = "Material"
    bl_order = 21

    def draw(self, context):
        mat = mesh_of(context).active_material
        draw_fill_material(frozen_banner(self.layout, mat, active_layer(mat)), active_layer(mat))


class PROPERTIES_PT_m3d_tx_fd_folder(_LayerPage, Panel):
    page = FOLDER_PAGE
    bl_label = "Folder"
    bl_order = 10

    def draw(self, context):
        mat = mesh_of(context).active_material
        layer = active_layer(mat)
        layout = frozen_banner(self.layout, mat, layer)
        split_props(layout)
        draw_folder(layout, layer)


class PROPERTIES_PT_m3d_tx_mk_stack(_LayerPage, Panel):
    page = MASK_PAGE
    bl_label = "Mask"
    bl_order = 11

    def draw(self, context):
        mat = mesh_of(context).active_material
        layer = active_layer(mat)
        draw_mask_stack(frozen_banner(self.layout, mat, layer), context, mat, layer, explain=False)


class PROPERTIES_PT_m3d_tx_mk_effect(_LayerPage, Panel):
    """The selected effect: its name and type, then its settings."""
    page = MASK_PAGE
    bl_label = "Effect"
    bl_order = 12

    @classmethod
    def page_poll(cls, context):
        return super().page_poll(context) and L.active_effect(active_layer(mesh_of(context).active_material)) is not None

    def draw(self, context):
        mat = mesh_of(context).active_material
        layer = active_layer(mat)
        layout = frozen_banner(self.layout, mat, layer)
        effect = L.active_effect(layer)
        kind = MK.KIND_BY_ID[effect.kind]
        split_props(layout)
        layout.prop(effect, "name", text="", icon=kind.icon)
        kind_text = EFFECT_TYPES[effect.kind]
        layout.label(text=kind_text if kind_text == kind.label else "%s: %s" % (kind_text, kind.label))
        draw_effect(layout, effect)


class PROPERTIES_PT_m3d_tx_channels(_Page, Panel):
    page = "tex_settings"
    bl_label = "Channels"
    bl_order = 20

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
        reason(layout, "C / Shift+C: show the next / previous channel")


class PROPERTIES_PT_m3d_tx_slots(_Page, Panel):
    page = "tex_settings"
    bl_label = "All Paint Slots"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 22

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        mat = ob.active_material
        layout.prop(paint_settings(context), "mode", text="Canvas")
        row = layout.row()
        row.template_list("TEXTURE_UL_texpaintslots", "", mat, "texture_paint_slots", mat, "paint_active_slot", rows=3)
        row.operator_menu_enum("paint.add_texture_paint_slot", "type", icon='ADD', text="")


class PROPERTIES_PT_m3d_tx_maps(_Page, Panel):
    page = "tex_settings"
    bl_label = "Mesh Maps"
    bl_order = 21

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        have = dict(mesh_maps(ob))
        col = layout.column(align=True)
        for label, text in MESH_MAPS:
            image = have.get(label)
            if image is None and label in {"WorldNormal", "Displacement"}:
                continue   # (those two only show once baked: the Bake page has the other maps)
            row = col.row(align=True)
            row.label(text=text, icon='IMAGE_DATA' if image is not None else 'BLANK1')
            sub = row.row(align=True)
            sub.enabled = image is not None
            if image is not None:
                row.label(text="%d x %d" % tuple(image.size))
                sub.operator("m3d.tex_view_mode", text="", icon='HIDE_OFF').mode = "MAP:" + label
                sub.operator("m3d.tex_show_image", text="", icon='IMAGE_DATA').name = image.name
            else:
                row.label(text="Not baked")
        row = layout.row()
        row.scale_y = 1.6
        row.operator("m3d.tex_bake_mode", text="Bake Mesh Maps", icon='RENDER_STILL').on = True
        reason(layout, "Ctrl+Shift+B: set the maps up and bake them in the Bake page")


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


class PROPERTIES_PT_m3d_tx_bake_back(_PagePanel, Panel):
    page = "tex_bake"
    bl_label = "Bake Mesh Maps"
    bl_options = {'HIDE_HEADER'}
    bl_order = -10

    def draw(self, context):
        row = self.layout.row()
        row.scale_y = 1.4
        row.operator("m3d.tex_bake_mode", text="Back to Painting", icon='LOOP_BACK').on = False


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
    bl_order = -5   # (right under Back to Painting: the Bake page is for baking, and the other panels are long)

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


def draw_export_preset(layout, context):
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


def draw_export_run(layout, context):
    s = context.scene.m3d_tex
    row = layout.row()
    row.scale_y = 1.6
    row.operator("m3d.tex_export", icon='EXPORT')
    layout.operator("m3d.tex_save_all", icon='FILE_TICK')
    for path in filter(None, s.export_files.split("|")):
        layout.label(text=os.path.basename(path), icon='FILE_IMAGE')


class PROPERTIES_PT_m3d_tx_export_preset(_Export, Panel):
    bl_label = "Preset"

    def draw(self, context):
        draw_export_preset(self.layout, context)


class PROPERTIES_PT_m3d_tx_export_run(_Export, Panel):
    bl_label = "Export"

    def draw(self, context):
        draw_export_run(self.layout, context)


# --- Display

class _Display(_Page):
    page = "tex_display"
    need = None


def draw_environment(layout, context):
    space = viewport(context)
    if space is None:
        reason(layout, "No 3D Viewport in this workspace")
        return
    shading = space.shading
    layout.row().prop(shading, "type", expand=True)
    if shading.type != 'MATERIAL':
        reason(layout, "The environment is for Material Preview")
        return
    split_props(layout)
    layout.prop(shading, "use_scene_lights")
    layout.prop(shading, "use_scene_world")
    if not shading.use_scene_world:
        layout.prop(shading, "studiolight_rotate_z", text="Rotation")
        layout.prop(shading, "studiolight_intensity", text="Intensity")
        layout.prop(shading, "studiolight_background_alpha", text="Background")
        reason(layout, "Pick the environment in Assets > Environments; Shift+RMB drag turns it")


def draw_channel_view(layout, context):
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


def draw_checker(layout, context):
    layout.operator("m3d.uv_checker", text="Checker Map", icon='TEXTURE', depress=m3d_uv.checker_on(context))
    reason(layout, "Replaces the material while it is on")
    space = viewport(context)
    if space is not None:
        layout.prop(space.overlay, "show_wireframes", text="Wireframe")


class PROPERTIES_PT_m3d_tx_environment(_Display, Panel):
    bl_label = "Environment"

    def draw(self, context):
        draw_environment(self.layout, context)


class PROPERTIES_PT_m3d_tx_channel_view(_Display, Panel):
    bl_label = "Channel View"

    def draw(self, context):
        draw_channel_view(self.layout, context)


class PROPERTIES_PT_m3d_tx_checker(_Display, Panel):
    bl_label = "UV Checker"

    def draw(self, context):
        draw_checker(self.layout, context)


# --- Tool strip, Texture Set List, dock strip (one Properties editor each, see m3d_workspace.texture_role)

def square_scale(context, padding=14):
    """scale_y that makes the icon buttons of a column as tall as the column is wide (a button is 20 units tall at scale 1)."""
    ui = context.preferences.system.ui_scale or 1.0
    width = context.region.width if context.region else 40 * ui
    return max((width - padding * ui) / (20 * ui), 1.0)


class PROPERTIES_PT_m3d_tx_tools(_PagePanel, Panel):
    page = "tex_tools"
    bl_label = "Tools"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = square_scale(context)
        active = tool_of(context) if context.mode == 'PAINT_TEXTURE' else None
        for tool, _label, _key, icon, _what in TOOLS:
            col.operator("m3d.tex_tool", text="", icon=icon, depress=tool == active).tool = tool
            col.separator(factor=0.15)


class PROPERTIES_PT_m3d_tx_sets(_PagePanel, Panel):
    page = "tex_sets"
    bl_label = "Texture Sets"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        sets = texture_sets(context)
        if not sets:
            reason(layout, "Select a mesh with a material")
            return
        ob = mesh_of(context)
        active = ob.active_material
        iso = context.scene.get("m3d_isolated") is not None
        col = layout.column(align=True)
        for mat, owner in sets:
            row = col.row(align=True)
            hidden = mat.name in hidden_sets(owner) if owner == ob else owner.hide_get()
            sub = row.row(align=True)
            sub.enabled = not iso
            o = sub.operator("m3d.tex_set_visible", text="", icon='HIDE_ON' if hidden else 'HIDE_OFF', emboss=False)
            o.object, o.material = owner.name, mat.name
            o = row.operator("m3d.tex_set", text=mat.name if owner == ob else "%s (%s)" % (mat.name, owner.name),
                             depress=owner == ob and mat == active, translate=False)
            o.object, o.material = owner.name, mat.name


# The popovers of the dock strip: (panel, icon). History and Log have a panel and a window; Export Textures is Ctrl+Shift+E.
DOCK_STRIP = (("M3D_PT_tex_display", 'SHADING_TEXTURE'), ("M3D_PT_tex_shader", 'MATERIAL'),
              ("M3D_PT_tex_history", 'RECOVER_LAST'), ("M3D_PT_tex_export", 'EXPORT'))


class PROPERTIES_PT_m3d_tx_dockbar(_PagePanel, Panel):
    page = "tex_dockbar"
    bl_label = "Dock"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = square_scale(context)
        for panel, icon in DOCK_STRIP:
            col.popover(panel=panel, text="", icon=icon)
            col.separator(factor=0.15)
        col.operator("m3d.open_editor", text="", icon='TEXT').ui_type = 'INFO'


class M3D_PT_tex_display(Panel):
    """Display Settings: the viewport's shading, environment, channel view and UV checker"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Display Settings"
    bl_ui_units_x = 16

    def draw(self, context):
        layout = self.layout
        for label, draw, closed in (("Environment", draw_environment, False), ("Channel View", draw_channel_view, True),
                                    ("UV Checker", draw_checker, True)):
            header, body = layout.panel("m3d_tex_display_" + label.split()[0].lower(), default_closed=closed)
            header.label(text=label)
            if body:
                draw(body, context)


class M3D_PT_tex_shader(Panel):
    """Shader Settings: the Principled shader of the active material and its displacement"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Shader Settings"
    bl_ui_units_x = 20

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and ob.active_material is not None

    def draw(self, context):
        from bl_ui.properties_material import panel_node_draw
        layout = self.layout
        mat = mesh_of(context).active_material
        if mat.node_tree is None:
            layout.label(text="The material has no nodes")
            return
        layout.label(text=mat.name, icon='MATERIAL')
        panel_node_draw(layout, mat.node_tree, 'OUTPUT_MATERIAL', "Surface")
        split_props(layout)
        layout.separator()
        layout.label(text="Displacement")
        panel_node_draw(layout, mat.node_tree, 'OUTPUT_MATERIAL', "Displacement")
        layout.prop(mat, "displacement_method", text="Method")


class M3D_PT_tex_history(Panel):
    """History: the undo steps, a click goes back to that step"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "History"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("ed.undo", icon='LOOP_BACK')
        row.operator("ed.redo", icon='LOOP_FORWARDS')
        layout.menu_contents("TOPBAR_MT_undo_history")


class M3D_PT_tex_export(Panel):
    """Export Textures: the files for Unreal, Unity or glTF (Ctrl+Shift+E)"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Export Textures"
    bl_ui_units_x = 20

    def draw(self, context):
        if mesh_of(context) is None or mesh_of(context).active_material is None:
            reason(self.layout, "Select a mesh with a material")
            return
        draw_export_preset(self.layout, context)
        draw_export_run(self.layout, context)


# --- Which pages the Properties editor draws (m3d_workspace.PAGE_SETS), and the headers of the editors

PAGE_NEEDS = {"tex_brushes": 'PAINT', "tex_layers": 'PAINT', "tex_brush": 'PAINT', "tex_settings": 'PAINT',
              "tex_props": 'PAINT', "tex_bake": 'BAKE', "tex_export": 'EXPORT'}   # pages that show what is missing instead
# The old layout's pages: the tray, and the Layers tab with the panels the new layout spreads over its editors.
OLD_PAGES = {"tex_layers": {"tex_layers", "tex_layer", "tex_mask", "tex_settings"},
             "tex_brushes": {"tex_brushes", "tex_brush_grid"}, "tex_library": {"tex_library", "tex_assets"}}
PROPS_TITLES = {'PAINT': "Paint", 'FILL': "Fill", 'MASK': "Mask", 'FOLDER': "Folder", 'LAYER': "Layer"}


def props_context(context):
    """What Properties shows, and says in its title: the settings of the active paint layer's brush (PAINT), of a fill layer
    (FILL), of a folder (FOLDER), of the layer's mask (MASK: when its mask is painted, or asked for with Properties > Mask), or
    only the layer's own (LAYER, asked for). Without a layer it is the brush."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    layer = active_layer(mat) if mat is not None and principled_of(mat) is not None else None
    if layer is None:
        return 'PAINT'
    mode = context.scene.m3d_tex.props_mode
    if mode == 'LAYER':
        return 'LAYER'
    if mode == 'MASK' or layer.paint_mask:
        return 'MASK'
    return {'FOLDER': 'FOLDER', 'FILL': 'FILL'}.get(layer.kind, 'PAINT')


def props_pages(context):
    """The pages Properties draws for what is selected: Paint (the tool's sections), Fill, Folder (with its mask), Mask (with the
    Paint sections while the mask is painted), or the layer's own settings."""
    kind = props_context(context)
    if kind == 'PAINT':
        return {PAINT_PAGE}
    if kind == 'MASK':
        layer = active_layer(mesh_of(context).active_material)
        return {MASK_PAGE, *({PAINT_PAGE} if layer.paint_mask else ())}
    return {'FILL': {FILL_PAGE}, 'FOLDER': {FOLDER_PAGE, MASK_PAGE}}.get(kind, {"tex_layer"})


def pages_new(context, active):
    need = PAGE_NEEDS.get(active)
    if need and not ready(context, need):
        return {active}
    return props_pages(context) if active == "tex_props" else {active}


def pages_old(context, active):
    need = PAGE_NEEDS.get(active)
    if need and not ready(context, need):
        return {active}
    return OLD_PAGES.get(active, {active})


def draw_header_sets(layout, context):
    layout.label(text="Texture Sets")
    layout.separator_spacer()
    layout.operator("m3d.tex_isolate", text="", icon='ZOOM_SELECTED', depress=context.scene.get("m3d_isolated") is not None)


def draw_header_assets(layout, _context):
    layout.label(text="Assets")


def draw_header_props(layout, context):
    ready_ = ready(context, 'PAINT')
    layout.label(text="Properties - " + PROPS_TITLES[props_context(context) if ready_ else 'PAINT'])
    layout.separator_spacer()
    if ready_ and active_layer(mesh_of(context).active_material) is not None:
        layout.row(align=True).prop(context.scene.m3d_tex, "props_mode", expand=True)


def draw_header_dock(layout, context):
    if W.active_page(context) == "tex_bake":
        layout.label(text="Bake Mesh Maps", icon='RENDER_STILL')
    else:
        W.draw_tab_row(layout, context)


def draw_header_blank(layout, _context):
    layout.label(text="")


W.PAGE_SETS['TEXTURE'], W.PAGE_SETS['TEXTURE_OLD'] = pages_new, pages_old
W.HEADERS.update({('TEXTURE', 'SETS'): draw_header_sets, ('TEXTURE', 'ASSETS'): draw_header_assets,
                  ('TEXTURE', 'PROPS'): draw_header_props, ('TEXTURE', 'RIGHT'): draw_header_dock,
                  ('TEXTURE', 'TOOLS'): draw_header_blank, ('TEXTURE', 'DOCKBAR'): draw_header_blank})


GATES = {"brushes": 'PAINT', "layers": 'PAINT', "brush": 'PAINT', "settings": 'PAINT', "props": 'PAINT', "bake": 'BAKE',
         "export": 'EXPORT'}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page, need) for page, need in GATES.items())


# -----------------------------------------------------------------------------
# Context toolbar (the Texture Status Line)

def layout_mode(context):
    """'BOTH' with the 3D view and the 2D view in the window, '3D' or '2D' when one is maximized."""
    view, image = view_areas(context.screen)
    return 'BOTH' if view is not None and image is not None else '3D' if view is not None else '2D'


def header_tier(context):
    """How much of the toolbar fits: 2 on a wide window (labels and all controls), 1 for the controls, 0 for narrow ones.
    Measured in pixels at UI scale 1."""
    region = context.region
    width = region.width / ui_scale_factor(context) if region else 2000
    return 2 if width >= 2300 else 1 if width >= 1700 else 0


def draw_brush_controls(layout, context, brush, tier):
    """Size (with its pressure toggle), Flow (the brush strength, with pressure), Spacing and Lazy Mouse with its distance."""
    ups = context.tool_settings.image_paint.unified_paint_settings   # (the toolbar has no brush tool: pass it in)
    row = layout.row(align=True)
    for units, prop, unified, pressure, text in ((8.5, "size", "use_unified_size", "use_pressure_size", "Size"),
                                                 (8.5, "strength", "use_unified_strength", "use_pressure_strength", "Flow")):
        owner = ups if getattr(ups, unified) else brush
        name = "unprojected_size" if prop == "size" and owner.use_locked_size == 'SCENE' else prop
        sub = row.row(align=True)
        sub.ui_units_x = units
        UnifiedPaintPanel.prop_unified(sub, context, brush, name, unified_paint_settings_override=ups, unified_name=unified,
                                       pressure_name=pressure, text=text, slider=True, header=True)
    if tier:
        sub = layout.row(align=True)
        sub.ui_units_x = 6.5
        sub.prop(brush, "spacing", text="Spacing", slider=True)
    row = layout.row(align=True)
    row.prop(brush, "use_smooth_stroke", text="Lazy Mouse" if tier == 2 else "", icon='MOD_SMOOTH', toggle=True)
    sub = row.row(align=True)
    sub.active = brush.use_smooth_stroke
    sub.ui_units_x = 5
    sub.prop(brush, "smooth_stroke_radius", text="Distance" if tier == 2 else "", slider=True)


def draw_stencil_controls(layout, brush, tier):
    """Projection: the display opacity of the stencil, Reset and Fit (S shows it; RMB, Shift+RMB and Ctrl+RMB place it)."""
    row = layout.row(align=True)
    if tier:
        sub = row.row(align=True)
        sub.ui_units_x = 6.5
        sub.prop(brush, "texture_overlay_alpha", text="Stencil", slider=True)
    row.operator("brush.stencil_reset_transform", text="Reset" if tier == 2 else "", icon='LOOP_BACK').mask = False
    row.operator("brush.stencil_fit_image_aspect", text="Fit" if tier == 2 else "", icon='FULLSCREEN_ENTER').mask = False


def draw_fill_controls(layout, layer, tier):
    """A fill layer is selected: the UV transform of its textures (Tiling, Rotation, Offset) and Reset."""
    for prop, text, units in (("uv_tiling", "Tiling", 9), ("uv_rotation", "Rotation", 7), ("uv_offset", "Offset", 9)):
        row = layout.row(align=True)
        row.ui_units_x = units if tier else units - 3
        row.prop(layer, prop, text=text if tier == 2 else "")
    layout.operator("m3d.layer_fill_reset", text="Reset" if tier == 2 else "", icon='LOOP_BACK')


def fill_selected(context):
    """Is a fill layer the active layer, with no painting of its mask? Its UV transform is then the toolbar's (the brush has no
    canvas on it)."""
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    layer = active_layer(mat) if mat is not None and principled_of(mat) is not None else None
    return layer is not None and layer.kind == 'FILL' and not layer.paint_mask and ready(context, 'PAINT')


def draw_status_line(layout, context):
    """Texture context toolbar: file buttons, modes, the controls of the active tool (Size, Flow, Spacing, Lazy Mouse; the Fill
    mode for Polygon Fill, the stencil for Projection; the UV transform when a fill layer is selected), Symmetry; on the right the
    view layout, perspective / orthographic, Bake Mesh Maps, Export Textures, the workspace picker."""
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
    tier = header_tier(context)
    brush = image_brush(context) if ob is not None and context.mode == 'PAINT_TEXTURE' else None
    if ob is not None and fill_selected(context):
        layout.label(text="Fill Layer" if tier == 2 else "", icon='COLOR')
        draw_fill_controls(layout, active_layer(ob.active_material), tier)
    elif brush is not None:
        tool = tool_of(context)
        layout.label(text=TOOL_BY_ID[tool][1] if tool else brush_name(context), icon=TOOL_BY_ID[tool][3] if tool else 'BRUSH_DATA')
        if tool == 'POLYFILL':
            layout.row(align=True).prop(context.scene.m3d_tex, "fill_mode", expand=True)
        elif tool != 'PICKER':
            draw_brush_controls(layout, context, brush, tier)
        if tool == 'PROJECTION':
            draw_stencil_controls(layout, brush, tier)
        if tool in {'PAINT', 'ERASER', 'PROJECTION', 'POLYFILL'} and paint_layer_active(context) is not None:
            draw_material_toggles(layout, context, short=tier < 2)   # (Smudge and Clone work on one channel)
    if ob is not None:
        row = layout.row(align=True)
        row.label(text="Symmetry" if tier == 2 else "", icon='MOD_MIRROR')
        for axis in "xyz":
            row.prop(ob.data, "use_mirror_" + axis, text=axis.upper(), toggle=True)

    def right(layout):
        row = layout.row(align=True)
        now = layout_mode(context)
        for mode, icon in (('BOTH', 'SPLIT_VERTICAL'), ('3D', 'VIEW3D'), ('2D', 'IMAGE_DATA')):
            row.operator("m3d.tex_layout", text="", icon=icon, depress=now == mode).mode = mode
        space = viewport(context)
        persp = space is None or space.region_3d is None or space.region_3d.is_perspective
        _call(layout, "view3d.view_persportho", 'VIEW_PERSPECTIVE' if persp else 'VIEW_ORTHO', "Perspective / Orthographic")
        layout.operator("m3d.tex_bake_mode", text="Bake Mesh Maps" if tier else "", icon='RENDER_STILL').on = True
        layout.popover("M3D_PT_tex_export", text="Export Textures" if tier else "", icon='EXPORT')
    draw_workspace_picker(layout, context, extra=right)


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
    M3D_BrushMaterial,
    M3D_TexSettings,
    M3D_BakeSettings,
    M3D_OT_tex_channel,
    M3D_OT_tex_channel_cycle,
    M3D_OT_tex_add_material,
    M3D_OT_tex_unwrap,
    M3D_OT_tex_save_all,
    M3D_OT_tex_channel_view,
    M3D_OT_tex_apply_material,
    M3D_OT_tex_tool,
    M3D_OT_tex_polyfill,
    M3D_OT_tex_set,
    M3D_OT_tex_set_visible,
    M3D_OT_tex_isolate,
    M3D_OT_tex_view_mode,
    M3D_OT_tex_view_cycle,
    M3D_MT_tex_view_mode,
    M3D_OT_tex_lazy,
    M3D_OT_tex_symmetry,
    M3D_OT_tex_stencil,
    M3D_OT_tex_brush_drag,
    M3D_OT_tex_env_rotate,
    M3D_OT_tex_frame,
    M3D_OT_tex_layout,
    M3D_OT_tex_bake_mode,
    M3D_OT_tex_bake_multires,
    M3D_OT_tex_bake_pick,
    M3D_OT_tex_bake,
    M3D_OT_tex_show_image,
    M3D_OT_tex_export,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_tx_tools,
    PROPERTIES_PT_m3d_tx_sets,
    PROPERTIES_PT_m3d_tx_dockbar,
    M3D_PT_tex_display,
    M3D_PT_tex_shader,
    M3D_PT_tex_history,
    M3D_PT_tex_export,
    PROPERTIES_PT_m3d_tx_canvas,
    PROPERTIES_PT_m3d_tx_brush,
    PROPERTIES_PT_m3d_tx_grid,
    PROPERTIES_PT_m3d_tx_tuning,
    PROPERTIES_PT_m3d_tx_material,
    PROPERTIES_PT_m3d_tx_projection,
    PROPERTIES_PT_m3d_tx_more,
    PROPERTIES_PT_m3d_tx_advanced,
    PROPERTIES_PT_m3d_tx_pp_canvas,
    PROPERTIES_PT_m3d_tx_pp_preview,
    PROPERTIES_PT_m3d_tx_pp_projection,
    PROPERTIES_PT_m3d_tx_pp_polyfill,
    PROPERTIES_PT_m3d_tx_pp_brush,
    PROPERTIES_PT_m3d_tx_pp_alpha,
    PROPERTIES_PT_m3d_tx_pp_stencil,
    PROPERTIES_PT_m3d_tx_pp_clone,
    PROPERTIES_PT_m3d_tx_pp_material,
    PROPERTIES_PT_m3d_tx_pp_gray,
    PROPERTIES_PT_m3d_tx_pp_advanced,
    PROPERTIES_PT_m3d_tx_pp_cursor,
    PROPERTIES_PT_m3d_tx_stack,
    PROPERTIES_PT_m3d_tx_layer,
    M3D_MT_mask_add,
    PROPERTIES_PT_m3d_tx_mask,
    PROPERTIES_PT_m3d_tx_fl_fill,
    PROPERTIES_PT_m3d_tx_fl_material,
    PROPERTIES_PT_m3d_tx_fd_folder,
    PROPERTIES_PT_m3d_tx_mk_stack,
    PROPERTIES_PT_m3d_tx_mk_effect,
    PROPERTIES_PT_m3d_tx_channels,
    PROPERTIES_PT_m3d_tx_maps,
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
    PROPERTIES_PT_m3d_tx_bake_back,
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
        if getattr(cls, "page", "") in {"tex_brushes", "tex_brush", "tex_brush_grid"}:
            cls.bl_order = 20   # (Properties - Mask: the mask's panel, then the brush)
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
