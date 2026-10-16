# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Texture sets for Maelstrom3D's Texture workspace (F4): the Texture Set Settings tab (General, Channels, Mesh Maps), the Export
Textures dialog and the New Texture Project dialog.

A texture set is a material: its layer stack (m3d_layers.py) and its channels. The channels of a set are the ones of
CHANNELS that are not removed (Material.m3d_off): removing one keeps the layers' images but builds, paints and exports nothing
for it until it is added again. The channels that are not sRGB colors can be stored as 16 bit float (Material.m3d_depth), and
the set has one size (Material.m3d_size): changing it scales every image of the set. The mesh maps are the images a bake makes,
named <texture set>_<map> (m3d_texture.py), or ones picked from a file. The Texture Set List, Bake Mesh Maps and the export
engine (templates, file types, padding) are in m3d_texture.py; this module has what the settings tab and the dialogs add.
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Menu, Operator, Panel

import m3d_layers as L
import m3d_masks as MK
import m3d_pair
import m3d_texture as T
import m3d_workspace as W
from m3d_sculpt import mesh_of, reason, split_props
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Texture Set Settings: General, Channels, Mesh Maps


class _Settings(T._Page):
    page = "tex_settings"


def active_material(context):
    ob = mesh_of(context)
    return ob.active_material if ob is not None else None


class M3D_OT_tex_channel_add(Operator):
    """Add a channel to the texture set again: its layers show what they hold for it (their images were kept)"""
    bl_idname = "m3d.tex_channel_add"
    bl_label = "Add Channel"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(items=L.CHANNEL_ITEMS)

    @classmethod
    def poll(cls, context):
        return active_material(context) is not None

    def execute(self, context):
        L.set_channel_off(context, active_material(context), self.channel, False)
        return {'FINISHED'}


class M3D_OT_tex_channel_remove(Operator):
    """Remove a channel from the texture set. The layers keep their images (they come back when the channel is added again), but
    nothing is built, painted or exported for it meanwhile"""
    bl_idname = "m3d.tex_channel_remove"
    bl_label = "Remove Channel"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(items=L.CHANNEL_ITEMS)

    @classmethod
    def poll(cls, context):
        return active_material(context) is not None

    def execute(self, context):
        mat = active_material(context)
        if len(L.set_channels(mat)) <= 1:
            self.report({'WARNING'}, "A texture set needs at least one channel")
            return {'CANCELLED'}
        L.set_channel_off(context, mat, self.channel, True)
        return {'FINISHED'}


class M3D_OT_tex_channel_format(Operator):
    """Store the images of a channel as 8 bit or as 16 bit float (the pixels are kept; new images follow). The color channels stay
    8 bit sRGB: a float image stores linear light, which the layer math of the colors does not read"""
    bl_idname = "m3d.tex_channel_format"
    bl_label = "Channel Format"
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(items=L.CHANNEL_ITEMS)
    depth: EnumProperty(name="Format", default='8', items=(('8', "8 bit", "One byte for each value"),
                                                           ('16', "16 bit float", "Half float: no banding in Height and Normal")))

    @classmethod
    def poll(cls, context):
        return active_material(context) is not None

    def execute(self, context):
        if self.channel not in L.DEPTH_CHANNELS:
            self.report({'WARNING'}, "%s stays 8 bit sRGB" % L.CHANNEL_BY_ID[self.channel].label)
            return {'CANCELLED'}
        L.set_depth(context, active_material(context), self.channel, int(self.depth))
        return {'FINISHED'}


class M3D_MT_tex_channel_add(Menu):
    bl_label = "Add Channel"

    def draw(self, context):
        mat = active_material(context)
        gone = [ch for ch in L.CHANNELS if mat is not None and L.channel_off(mat, ch.id)]
        for ch in gone:
            self.layout.operator("m3d.tex_channel_add", text=ch.label, icon='ADD').channel = ch.id
        if not gone:
            self.layout.label(text="Every channel is in the set")


def painted_images(mat):
    """The images of the texture set that hold pixels (a generated image that was never painted only has a size)."""
    return [img for img in dict.fromkeys(img for layer in mat.m3d_layers for img in L.layer_images(layer))
            if not (img.source == 'GENERATED' and not img.has_data)]


class M3D_OT_tex_set_size(Operator):
    """Another size for the texture set: every image of it is scaled. A smaller size asks first: the painted detail it loses
    does not come back"""
    bl_idname = "m3d.tex_set_size"
    bl_label = "Texture Set Size"
    bl_options = {'REGISTER', 'UNDO'}

    size: EnumProperty(name="Size", items=T.SIZES)

    @classmethod
    def poll(cls, context):
        return active_material(context) is not None

    def invoke(self, context, event):
        mat = active_material(context)
        count = len(painted_images(mat))
        if int(self.size) < L.set_size(context, mat) and count:
            return context.window_manager.invoke_confirm(
                self, event, title="Scale Down %s" % mat.name, confirm_text="Scale Down",
                message="Its %d images go down to %s px: the detail they lose is gone for good, Undo does not bring it back"
                        % (count, self.size))
        return self.execute(context)

    def execute(self, context):
        L.resize_set(context, active_material(context), int(self.size))
        return {'FINISHED'}


class PROPERTIES_PT_m3d_tx_set_general(_Settings, Panel):
    bl_label = "General"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        mat = active_material(context)
        tex = context.scene.m3d_tex
        split_props(layout)
        layout.prop(mat, "name", text="Name")
        row = layout.row(align=True)
        row.use_property_split = False
        split = row.split(factor=0.4, align=True)
        sub = split.row()
        sub.alignment = 'RIGHT'
        sub.label(text="Size")
        split.operator_menu_enum("m3d.tex_set_size", "size", text="%d px" % L.set_size(context, mat))
        row.label(text="", icon='LOCKED')
        layout.prop(tex, "normal_format")
        reason(layout, "Square sizes: masks and export need them")


class PROPERTIES_PT_m3d_tx_set_channels(_Settings, Panel):
    bl_label = "Channels"
    bl_order = 20

    def draw(self, context):
        layout = self.layout
        mat = active_material(context)
        found, now = T.channel_slots(mat), T.active_channel(mat)
        col = layout.column(align=True)
        for ch in L.set_channels(mat):
            row = col.row(align=True)
            row.operator("m3d.tex_channel", text=ch.label, depress=ch.id in found and ch.id == now).channel = ch.id
            sub = row.row(align=True)
            sub.scale_x = 0.8
            if ch.id in L.DEPTH_CHANNELS:
                depth = L.channel_depth(mat, ch.id)
                sub.operator_menu_enum("m3d.tex_channel_format", "depth", text="16 bit float" if depth == 16 else "8 bit").channel = ch.id
            else:
                sub.label(text="8 bit sRGB")
            row.operator("m3d.tex_channel_remove", text="", icon='X').channel = ch.id
        if any(L.channel_off(mat, ch.id) for ch in L.CHANNELS):
            layout.menu("M3D_MT_tex_channel_add", text="Add Channel", icon='ADD')
        col = layout.column(align=True)   # (Save All Images is in the File menu)
        reason(col, "A removed channel keeps its images")
        reason(col, "C / Shift+C: next / previous channel")


class M3D_OT_tex_map_load(Operator):
    """Use an image file as a mesh map of the texture set (instead of a baked one)"""
    bl_idname = "m3d.tex_map_load"
    bl_label = "Load Mesh Map"
    bl_options = {'REGISTER', 'UNDO'}

    label: EnumProperty(items=[(label, text, "") for label, text in T.MESH_MAPS])
    filepath: StringProperty(subtype='FILE_PATH')
    filter_image: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None and mesh_of(context).active_material is not None

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        ob = mesh_of(context)
        try:
            image = bpy.data.images.load(self.filepath, check_existing=False)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        owner = T.bake_owner(ob)
        s = owner.m3d_bake
        name = "%s_%s" % (T.texture_set(owner)[0], self.label)
        old = bpy.data.images.get(name)
        if old is not None:
            L.remove_image(old)   # (the baked map, if there was one: the mask effects that read it get this one below)
        image.name = name
        image.colorspace_settings.name = 'Non-Color'
        image.use_fake_user = True
        image["m3d_bake"], image["m3d_map"], image["m3d_stamp"] = self.label, T.map_size(s), MK.new_uid()
        if self.label == "Normal":   # (a file is taken to follow the project's normal map format: the shader reads the green channel so)
            image["m3d_nfmt"] = context.scene.m3d_tex.normal_format
        if self.label == "Position":   # (a file of positions is taken to be scaled to the bounds of the mesh, as the bake does)
            lo, hi = T.world_bounds(ob)
            image["m3d_bounds"] = [float(x) for x in (*lo, *hi)]
            image["m3d_inv"] = [float(x) for row in owner.matrix_world.inverted() for x in row]
        s.baked = "|".join(dict.fromkeys([*filter(None, s.baked.split("|")), name]))
        L.use_baked_maps(context, [ob])   # (a Normal or AO map is in the shader of the texture sets at once)
        return {'FINISHED'}


class M3D_OT_tex_map_clear(Operator):
    """Clear a mesh map slot: the image is removed from the file (bake it again or pick another file)"""
    bl_idname = "m3d.tex_map_clear"
    bl_label = "Clear Mesh Map"
    bl_options = {'REGISTER', 'UNDO'}

    label: EnumProperty(items=[(label, text, "") for label, text in T.MESH_MAPS])

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        image = dict(T.mesh_maps(ob)).get(self.label)
        if image is None:
            return {'CANCELLED'}
        s = T.bake_owner(ob).m3d_bake
        s.baked = "|".join(n for n in s.baked.split("|") if n and n != image.name)
        L.remove_image(image)
        L.use_baked_maps(context, [ob])   # (the shader goes back to what the layers say)
        return {'FINISHED'}


MAP_SLOTS = ("Normal", "WorldNormal", "ID", "AO", "Curvature", "Position", "Thickness")   # (the order of the slots)


class PROPERTIES_PT_m3d_tx_set_maps(_Settings, Panel):
    bl_label = "Mesh Maps"
    bl_order = 30

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        have = dict(T.mesh_maps(ob))
        col = layout.column(align=True)
        for label in (*MAP_SLOTS, *(l for l in ("Displacement",) if l in have)):
            image = have.get(label)
            row = col.row(align=True)
            sub = row.row(align=True)
            sub.scale_x = 1.3
            if image is not None:
                icon = L.thumb_icon("map:%s:%s" % (ob.name, label), ('IMAGE', image.name, True))
                sub.operator("m3d.tex_view_mode", text="", icon_value=icon).mode = "MAP:" + label
            else:
                sub.label(text="", icon='BLANK1')
            row.label(text=T.MAP_TEXT[label], translate=False)
            sub = row.row(align=True)
            sub.active = image is not None
            sub.label(text=image.name if image is not None else "Empty", translate=False)
            row.operator("m3d.tex_map_load", text="", icon='FILE_FOLDER').label = label
            sub = row.row(align=True)
            sub.enabled = image is not None
            sub.operator("m3d.tex_map_clear", text="", icon='X').label = label
        row = layout.row()
        row.scale_y = 1.6
        row.operator("m3d.tex_bake_mode", text="Bake Mesh Maps", icon='RENDER_STILL').on = True
        reason(layout, "A folder icon loads a file into a slot")


# -----------------------------------------------------------------------------
# Export Textures dialog

def export_sets_of(context):
    """[(material, mesh)] the dialog exports: the texture sets that are ticked."""
    return [(mat, ob) for mat, ob in T.texture_sets(context) if mat.m3d_set_export]


def write_bake_meshes(context, sets):
    """The Bake meshes option: the low and high polys of the bake groups of the sets, once for each texture set name."""
    paths, done = [], set()
    for ob in dict.fromkeys(o for _m, o in sets):
        found = T.bake_mesh_set(context, ob)
        if found is not None and found[0] not in done:
            done.add(found[0])
            paths += T.export_bake_meshes(context, ob)
    if not done:
        raise RuntimeError("Bake meshes needs a mesh of a bake group that has a low poly")
    return paths


class M3D_OT_tex_export_dialog(Operator):
    """Export Textures: pick the texture sets, the template (the engine the files are for), the file type, size and padding,
    and write the maps; a list of the files written follows"""
    bl_idname = "m3d.tex_export_dialog"
    bl_label = "Export Textures"

    @classmethod
    def description(cls, context, _props):
        from m3d_ui import with_key
        return with_key(context, " ".join(cls.__doc__.split()), "Image Paint", "m3d.tex_export_dialog")

    @classmethod
    def poll(cls, context):
        return bool(T.texture_sets(context))

    def invoke(self, context, _event):
        tex = context.scene.m3d_tex
        T.sync_export_maps(tex)
        return context.window_manager.invoke_props_dialog(self, width=640, title="Export Textures", confirm_text="Export")

    def draw(self, context):
        layout = self.layout
        tex = context.scene.m3d_tex
        sets = T.texture_sets(context)
        split = layout.split(factor=0.46)
        left = split.column()
        left.label(text="Texture Sets")
        box = left.box().column(align=True)
        for mat, ob in sets:
            box.prop(mat, "m3d_set_export", text=mat.name if ob == mesh_of(context) else "%s (%s)" % (mat.name, ob.name), translate=False)
        template = T.TEMPLATES[tex.export_preset]
        left.label(text="Output Maps")
        box = left.box().column(align=True)
        example = T.export_name(context, sets[0][1], sets[0][0]) if sets else "Name"   # (the files of the first set)
        if not template[2]:
            box.label(text="One .glb file for each texture set, with its meshes")
            sub = box.row()
            sub.active = False
            sub.label(text=example + ".glb", translate=False)
        prefix = tex.export_preset + "."
        keys = {m.key: m for m in tex.export_maps}
        for om in template[2]:
            item = keys.get(prefix + om.key)
            if item is not None:
                row = box.row(align=True)
                row.prop(item, "use", text=om.label, translate=False)
                sub = row.row(align=True)
                sub.active = False
                sub.label(text=om.name % example + T.EXPORT_EXT[tex.export_format], translate=False)
        right = split.column()
        right.label(text="Settings")
        T.draw_export_options(right.box().column(), context, width=640 * 0.54 * (context.preferences.system.ui_scale or 1.0))
        ticked = export_sets_of(context)
        T.draw_stale(layout, context, ticked)
        maps = len([1 for om in template[2] if om.key not in T.export_skipped(tex)])
        row = layout.row()
        row.label(text="%d texture sets, %d maps each" % (len(ticked), maps) if template[2] else "%d texture sets" % len(ticked))
        row.label(text="The meshes and animation too:")
        row.operator("m3d.export_engine", text="Export to Engine...", icon='EXPORT')

    def execute(self, context):
        sets, tex = export_sets_of(context), context.scene.m3d_tex
        if not sets:
            self.report({'WARNING'}, "Tick at least one texture set")
            return {'CANCELLED'}
        if tex.export_bake_meshes and not any(T.bake_mesh_set(context, ob) for _mat, ob in sets):
            self.report({'ERROR'}, "Bake meshes needs a mesh of a bake group that has a low poly")
            return {'CANCELLED'}
        try:
            paths = T.export_sets(context, sets)
            if tex.export_bake_meshes:
                paths += write_bake_meshes(context, sets)
        except (RuntimeError, OSError) as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        if not paths:
            self.report({'WARNING'}, "Nothing to write: the template has no map that these texture sets have the channels or mesh maps for")
            return {'CANCELLED'}
        tex.export_files = "|".join(paths)
        self.report({'INFO'}, "Exported %d files to %s" % (len(paths), os.path.dirname(paths[0])))
        if not bpy.app.background:
            bpy.app.timers.register(_show_summary, first_interval=0.1)   # (a dialog cannot open another one: the next event loop does)
        return {'FINISHED'}


def _show_summary():
    wm = bpy.context.window_manager
    if wm.windows:
        win = wm.windows[0]
        with bpy.context.temp_override(window=win, screen=win.screen):
            bpy.ops.m3d.tex_export_summary('INVOKE_DEFAULT')


class M3D_OT_tex_export_summary(Operator):
    """The files the last Export Textures wrote"""
    bl_idname = "m3d.tex_export_summary"
    bl_label = "Exported Textures"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=420, title="Exported Textures", confirm_text="OK")

    def draw(self, context):
        files = [f for f in context.scene.m3d_tex.export_files.split("|") if f]
        col = self.layout.column(align=True)
        col.label(text="%d files written to %s" % (len(files), os.path.dirname(files[0]) if files else "-"), translate=False)
        for path in files:
            col.label(text=os.path.basename(path), icon='FILE_IMAGE', translate=False)

    def execute(self, _context):
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# New Texture Project dialog

PROJECT_CHANNELS = {
    'DEFAULT': ("Base Color, Roughness, Metallic, Normal, Height", ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL', 'HEIGHT')),
    'EMISSION': ("Base Color, Roughness, Metallic, Normal, Height, Emission",
                 ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL', 'HEIGHT', 'EMISSION')),
    'MINIMAL': ("Minimal: Base Color, Roughness, Metallic", ('BASE_COLOR', 'ROUGHNESS', 'METALLIC')),
}


def project_candidates(context):
    """The selected meshes (the active mesh when none is selected)."""
    found = [o for o in context.selected_objects if o.type == 'MESH']
    ob = mesh_of(context)
    return found or ([ob] if ob is not None else [])


def texture_workspace(context):
    """The Texture workspace (its face limit is the one a project goes by), else the current one."""
    return next((w for w in bpy.data.workspaces if W.workspace_kind(w) == 'TEXTURE'), context.workspace)


def skipped_meshes(context):
    """[(mesh, why)] of the selected meshes a new project leaves out: the high polys (their detail is baked, not painted; a mesh
    without a role named Crate_high is one too) and the meshes over the face limit of the Texture workspace (painting, and
    unwrapping, them would take long)."""
    ws, out = texture_workspace(context), []
    for ob in project_candidates(context):
        role = ob.m3d_pair.role
        if role == 'HIGH' or role == 'NONE' and m3d_pair.split_role(ob.name)[1] == 'HIGH':
            out.append((ob, "high poly"))
        elif ws is not None and m3d_pair.too_big(ws, ob):
            out.append((ob, "%s faces, over the face limit" % m3d_pair.format_count(m3d_pair.face_count(ob))))
    return out


def project_meshes(context):
    """The meshes of a new project: the selected ones (the active mesh when none is selected), without the `skipped_meshes`."""
    skipped = {ob for ob, _why in skipped_meshes(context)}
    return [ob for ob in project_candidates(context) if ob not in skipped]


def new_set(context, mat, size, channels):
    """Make the material a texture set: a Base layer of `size` px with an image for each of the `channels` (ids), the other channels
    are not in the set. Returns False when it has layers already."""
    if mat.m3d_layers or L.principled_of(mat) is None:
        return False
    mat.m3d_size = size
    mat.m3d_off = "|".join(ch.id for ch in L.CHANNELS if ch.id not in channels)
    with MK.muted():
        layer = L.add_layer(mat, 'PAINT', "Base", base=True)
        for ch in L.CHANNELS:
            e = L.entry_of(layer, ch.id)
            e.use = ch.id in channels
            if e.use:
                e.image = L.make_channel_image(mat, layer, ch, size, opaque=True)
        mat.m3d_layer_index = 0
        mat.m3d_channel = 'BASE_COLOR'
        mat.m3d_row_channel = 'BASE_COLOR'
    L.rebuild_all(mat)
    return True


class M3D_OT_tex_project(Operator):
    """New Texture Project: make the selected meshes ready to paint. Each material gets a Base layer (its texture set) with the
    channels of the template at the document resolution; a mesh without UVs is unwrapped, a mesh without a material gets one"""
    bl_idname = "m3d.tex_project"
    bl_label = "New Texture Project"
    bl_options = {'REGISTER', 'UNDO'}

    resolution: EnumProperty(name="Document Resolution", default='1024', items=T.SIZES,
                             description="Size of the images of every texture set (square): the baked maps and the texel size of "
                                         "the UV tools follow it")
    normal_format: EnumProperty(name="Normal Map Format", default='OPENGL', items=(
        ('OPENGL', "OpenGL (Unity, Blender)", "Green up"), ('DIRECTX', "DirectX (Unreal)", "Green down")),
        description="How the green channel of the normal map points: used by the Normal bake and by the export templates that "
                    "follow the project")
    unwrap: BoolProperty(name="Auto Unwrap Missing UVs", default=True,
                         description="Unwrap the meshes that have no UV map (cut at sharp edges, unfold, lay out)")
    template: EnumProperty(name="Channels", default='DEFAULT', items=[(k, name, "") for k, (name, _ch) in PROJECT_CHANNELS.items()],
                           description="The channels of each texture set")
    bake_after: BoolProperty(name="Bake Mesh Maps Next", default=False,
                             description="Open Bake Mesh Maps when the project is made, to pick the high poly and bake (the Layers "
                                         "come back when the bake is done). Off: the Layers show")

    @classmethod
    def poll(cls, context):
        return bool(project_candidates(context))

    def invoke(self, context, _event):
        tex = context.scene.m3d_tex
        self.normal_format, self.resolution = tex.normal_format, tex.resolution
        return context.window_manager.invoke_props_dialog(self, width=420, title="New Texture Project", confirm_text="OK")

    def draw(self, context):
        layout = self.layout
        meshes, skipped = project_meshes(context), skipped_meshes(context)
        layout.label(text="Mesh")
        box = layout.box().column(align=True)
        for ob in meshes[:6]:
            sets = [slot.material for slot in ob.material_slots if slot.material]
            box.label(text="%s: %s" % (ob.name, plural_sets(len(sets) or 1)), icon='MESH_DATA', translate=False)
        if len(meshes) > 6:
            box.label(text="and %d more" % (len(meshes) - 6))
        if not meshes:
            box.label(text="No mesh to paint: select the low poly", icon='ERROR')
        for ob, why in skipped[:3]:
            box.label(text="Left out: %s (%s)" % (ob.name, why), icon='CANCEL', translate=False)
        if len(skipped) > 3:
            box.label(text="and %d more left out" % (len(skipped) - 3))
        split_props(layout)
        layout.prop(self, "resolution")
        layout.prop(self, "normal_format")
        layout.prop(self, "template")
        layout.prop(self, "unwrap")
        layout.prop(self, "bake_after")

    def execute(self, context):
        meshes = project_meshes(context)
        if not meshes:
            self.report({'WARNING'}, "No mesh to paint: %s" % ", ".join("%s is a %s" % (ob.name, why) if why == "high poly" else
                                                                        "%s has %s" % (ob.name, why) for ob, why in skipped_meshes(context)))
            return {'CANCELLED'}
        size, channels = int(self.resolution), PROJECT_CHANNELS[self.template][1]
        mode = context.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        tex = context.scene.m3d_tex
        tex.resolution, tex.normal_format = self.resolution, self.normal_format
        context.scene.m3d_uv.texture_size = 'SET'   # (one size: the bake and the UV tools follow the sets)
        for ob in meshes:
            T.bake_owner(ob).m3d_bake.resolution = 'SET'
        layer, active, selected = context.view_layer, context.view_layer.objects.active, list(context.selected_objects)
        made, first = [], None
        for ob in meshes:
            if self.unwrap and not ob.data.uv_layers:
                for other in selected:
                    other.select_set(False)
                ob.select_set(True)
                layer.objects.active = ob
                bpy.ops.m3d.tex_unwrap()
            if not any(slot.material for slot in ob.material_slots):
                mat = bpy.data.materials.new(ob.name + "_Material")
                mat.use_nodes = True
                if ob.material_slots:
                    ob.material_slots[0].material = mat
                else:
                    ob.data.materials.append(mat)
            for slot in ob.material_slots:
                if slot.material is not None:
                    if slot.material.node_tree is None:
                        slot.material.use_nodes = True
                    if new_set(context, slot.material, size, channels):
                        made.append(slot.material.name)
                        first = first or (ob, slot.material)
        for other in context.selected_objects:
            other.select_set(False)
        for ob in selected:
            ob.select_set(True)
        layer.objects.active = active
        if not made:
            self.report({'WARNING'}, "Nothing new: the materials have layers already, or are not Principled")
            return {'CANCELLED'}
        T.activate_set(context, *first)
        if mode == 'PAINT_TEXTURE':
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
        self.open_texture(context)
        self.report({'INFO'}, "Texture project: %s at %d px" % (", ".join(made), size))
        return {'FINISHED'}

    def open_texture(self, context):
        """The Texture workspace (when this is another one) shows the new sets, with the Layers in its dock; Bake Mesh Maps opens when
        asked for."""
        ws = next((w for w in bpy.data.workspaces if W.workspace_kind(w) == 'TEXTURE'), None)
        if ws is None:
            return
        ws.m3d_page_right = "tex_bake" if self.bake_after else "tex_layers"
        if context.workspace != ws and context.window is not None:
            try:
                bpy.ops.m3d.workspace(kind='TEXTURE')
            except RuntimeError:
                pass   # (no window to switch)


def plural_sets(count):
    return "%d texture set%s" % (count, "" if count == 1 else "s")


# -----------------------------------------------------------------------------

classes = (
    M3D_OT_tex_channel_add,
    M3D_OT_tex_channel_remove,
    M3D_OT_tex_channel_format,
    M3D_OT_tex_set_size,
    M3D_MT_tex_channel_add,
    M3D_OT_tex_map_load,
    M3D_OT_tex_map_clear,
    M3D_OT_tex_export_dialog,
    M3D_OT_tex_export_summary,
    M3D_OT_tex_project,
    PROPERTIES_PT_m3d_tx_set_general,
    PROPERTIES_PT_m3d_tx_set_channels,
    PROPERTIES_PT_m3d_tx_set_maps,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
