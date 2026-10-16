# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Rendering workspace (F7) for Maelstrom3D: the dock pages (Camera, Lighting, Materials, Render, Output, Passes & Layers,
Advanced), the Rendering Status Line, the Lights and Render shelves and the operators behind them (quality presets, the
light table, HDRI setup, camera from view, IPR, Render and Render View).
Scene extras: render snapshots (a slot per render), the Scene Materials browser, the Shader Graph in F7's Render View,
background renders and render jobs, the turntable, the missing-textures banner and Save Copy for Sharing.

The layout is built by tools/m3d/build_startup.py (phase6_rendering), the tabs are DOCK_TABS['RENDER'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py.
"""

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup
from mathutils import Vector

from m3d_mode import _button, is_internal_material
from m3d_sculpt import draw_list, draw_lines, draw_object_picks, empty_state, grid, reason, split_props, viewport
from m3d_workspace import _PagePanel, current_kind, workspace_kind

ENGINES = (('CYCLES', "Cycles"), ('BLENDER_EEVEE', "EEVEE"))

# -----------------------------------------------------------------------------
# Quality presets: Draft / Medium / Final

QUALITY = (('DRAFT', "Draft"), ('MEDIUM', "Medium"), ('FINAL', "Final"))


def _quality(percent, cycles, eevee):
    """Values of one preset as paths from the scene: the size, and each engine's. Applying a preset sets both engines, so
    switching the engine afterwards keeps the preset."""
    return {'ALL': {"render.resolution_percentage": percent},
            'CYCLES': {"cycles." + k: v for k, v in cycles.items()},
            'BLENDER_EEVEE': {"eevee." + k.replace("rt_", "ray_tracing_options."): v for k, v in eevee.items()}}


PRESET_VALUES = {
    'DRAFT': _quality(
        50,
        dict(samples=32, use_adaptive_sampling=True, adaptive_threshold=0.05, use_denoising=True, max_bounces=4,
             diffuse_bounces=2, glossy_bounces=2, transmission_bounces=4, volume_bounces=0, transparent_max_bounces=4),
        dict(taa_render_samples=16, use_raytracing=False, rt_resolution_scale='4', shadow_ray_count=1,
             shadow_step_count=6)),
    'MEDIUM': _quality(
        100,
        dict(samples=128, use_adaptive_sampling=True, adaptive_threshold=0.01, use_denoising=True, max_bounces=8,
             diffuse_bounces=3, glossy_bounces=3, transmission_bounces=6, volume_bounces=0, transparent_max_bounces=6),
        dict(taa_render_samples=64, use_raytracing=True, rt_resolution_scale='2', shadow_ray_count=1,
             shadow_step_count=6)),
    'FINAL': _quality(
        100,
        dict(samples=512, use_adaptive_sampling=True, adaptive_threshold=0.005, use_denoising=True, max_bounces=12,
             diffuse_bounces=4, glossy_bounces=4, transmission_bounces=12, volume_bounces=0, transparent_max_bounces=8),
        dict(taa_render_samples=256, use_raytracing=True, rt_resolution_scale='1', shadow_ray_count=2,
             shadow_step_count=12)),
}
PRESET_NOTES = {
    'DRAFT': "Cycles 32 samples, 4 bounces; EEVEE 16 samples, no ray tracing; half size",
    'MEDIUM': "Cycles 128 samples, 8 bounces; EEVEE 64 samples, ray tracing at half resolution",
    'FINAL': "Cycles 512 samples, 12 bounces; EEVEE 256 samples, full ray tracing and shadow rays",
}


def _owner(scene, path):
    *head, name = path.split(".")
    owner = scene
    for part in head:
        owner = getattr(owner, part)
    return owner, name


def _same(a, b):
    return math.isclose(a, b, abs_tol=1e-6) if isinstance(b, float) else a == b


PRESET_PATHS = [path for values in PRESET_VALUES['MEDIUM'].values() for path in values]   # what a preset of the user's keeps


def user_presets():
    """{name: values} of the presets the user saved (m3d_user.json "render_presets": {name: {path: value}}; only the paths a
    preset has are read)."""
    import m3d_user
    found = m3d_user.data().get("render_presets")
    presets = {}
    for name, flat in (found.items() if isinstance(found, dict) else ()):
        if isinstance(flat, dict):
            flat = {path: flat[path] for path in PRESET_PATHS if path in flat}
            presets[name] = {part: {path: value for path, value in flat.items() if path in paths}
                             for part, paths in PRESET_VALUES['MEDIUM'].items()}
    return presets


def preset_values(preset):
    """A preset's values: a built-in one by key, the user's by name (None: there is none)."""
    return PRESET_VALUES.get(preset) or user_presets().get(preset)


def quality_matches(scene, preset, values=None):
    """Do the active engine's settings (and the size) equal the preset's?"""
    values = values or preset_values(preset)
    flat = {**values['ALL'], **values.get(scene.render.engine, {})}
    try:
        return bool(flat) and all(_same(getattr(*_owner(scene, path)), value) for path, value in flat.items())
    except TypeError:   # (a damaged value of the user's)
        return False


def apply_quality(scene, preset):
    for values in preset_values(preset).values():
        for path, value in values.items():
            owner, name = _owner(scene, path)
            try:
                setattr(owner, name, value)
            except (TypeError, ValueError):   # (a damaged value in a preset of the user's: the others still apply)
                pass
    builtin = preset in PRESET_VALUES
    scene.m3d_render.preset, scene.m3d_render.user_preset = (preset, "") if builtin else ('CUSTOM', preset)


def current_quality(scene):
    """The preset the settings match (a built-in key, or the name of one of the user's), else 'CUSTOM' (a value was edited
    since): the preset applied last wins a tie."""
    s = scene.m3d_render
    stored = s.user_preset or s.preset
    if stored != 'CUSTOM' and preset_values(stored) and quality_matches(scene, stored):
        return stored
    found = next((p for p in PRESET_VALUES if quality_matches(scene, p)), None)
    return found or next((name for name, values in sorted(user_presets().items()) if quality_matches(scene, name, values)), 'CUSTOM')


def quality_note(scene):
    """The line under the presets: what the preset does, or why it reads Custom."""
    now = current_quality(scene)
    if now in PRESET_NOTES:
        return PRESET_NOTES[now]
    if now != 'CUSTOM':
        return "Your preset \"%s\"" % now
    s = scene.m3d_render
    return "Custom: a value was edited since the preset" if s.preset != 'CUSTOM' or s.user_preset else "Custom: no preset applied yet"


def use_gpu(context):
    """Cycles renders on the GPU when there is one that passes a test bake (m3d_bakeq.find_gpu; asked once). True when it does."""
    import m3d_bakeq
    if m3d_bakeq.find_gpu(context)[0]:
        context.scene.cycles.device = 'GPU'
        return True
    return False


class M3D_OT_render_preset(Operator):
    """Quality preset for the scene: samples, denoising, bounces / ray tracing and size for Cycles and EEVEE"""
    bl_idname = "m3d.render_preset"
    bl_label = "Quality Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(items=[(k, v, "") for k, v in QUALITY])
    user_preset: StringProperty(options={'SKIP_SAVE'}, description="One of your presets (instead of the built-in one)")

    @classmethod
    def description(cls, _context, props):
        if props.user_preset:
            return "Your preset \"%s\": its samples, bounces / ray tracing and size for Cycles and EEVEE" % props.user_preset
        return "%s quality: %s (Custom shows once you edit one of these values). Cycles renders on the GPU when there is one" % (
            props.preset.title(), PRESET_NOTES[props.preset])

    def execute(self, context):
        preset = self.user_preset or self.preset
        if preset_values(preset) is None:
            self.report({'WARNING'}, "No preset \"%s\"" % preset)
            return {'CANCELLED'}
        apply_quality(context.scene, preset)
        use_gpu(context)
        return {'FINISHED'}


def _taken(name):
    return name.strip().upper() in {*PRESET_VALUES, 'CUSTOM'}


class M3D_OT_render_preset_save(Operator):
    """Save the scene's quality settings (samples, bounces / ray tracing, size, for Cycles and EEVEE) as a preset of your own,
    for every scene"""
    bl_idname = "m3d.render_preset_save"
    bl_label = "Save as Preset"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="My Preset")

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, confirm_text="Save")

    def execute(self, context):
        import m3d_user
        name = self.name.strip()
        if not name or _taken(name):
            self.report({'WARNING'}, "Pick another name: \"%s\" is a built-in preset" % name if name else "The preset needs a name")
            return {'CANCELLED'}
        root = m3d_user.data()
        if not isinstance(root.get("render_presets"), dict):
            root["render_presets"] = {}
        root["render_presets"][name] = {path: getattr(*_owner(context.scene, path)) for path in PRESET_PATHS}
        m3d_user.save()
        context.scene.m3d_render.preset, context.scene.m3d_render.user_preset = 'CUSTOM', name
        self.report({'INFO'}, "Saved the preset \"%s\"" % name)
        return {'FINISHED'}


_preset_items = []   # (kept here: Blender reads the item strings after the callback has returned)


def _user_preset_items(_self, _context):
    _preset_items[:] = [(name, name, "") for name in sorted(user_presets())] or [("", "(no presets)", "")]
    return _preset_items


class M3D_OT_render_preset_delete(Operator):
    """Delete one of your quality presets"""
    bl_idname = "m3d.render_preset_delete"
    bl_label = "Delete Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Preset", items=_user_preset_items)

    def execute(self, context):
        import m3d_user
        name = self.preset   # (read once: the items change when it is gone)
        found = m3d_user.data().get("render_presets")
        if not isinstance(found, dict) or name not in found:
            return {'CANCELLED'}
        del found[name]
        m3d_user.save()
        for scene in bpy.data.scenes:
            if scene.m3d_render.user_preset == name:
                scene.m3d_render.user_preset = ""
        self.report({'INFO'}, "Deleted the preset \"%s\"" % name)
        return {'FINISHED'}


class M3D_MT_render_presets(Menu):
    """Your quality presets: apply, save the scene's settings as one, delete one"""
    bl_label = "Your Presets"

    def draw(self, context):
        layout = self.layout
        names = sorted(user_presets())
        now = current_quality(context.scene)
        for name in names:
            layout.operator("m3d.render_preset", text=name, icon='CHECKMARK' if name == now else 'PRESET').user_preset = name
        if names:
            layout.separator()
        layout.operator("m3d.render_preset_save", text="Save as Preset...", icon='ADD')
        if names:
            layout.operator_menu_enum("m3d.render_preset_delete", "preset", text="Delete Preset", icon='TRASH')


# -----------------------------------------------------------------------------
# HDRI world: Texture Coordinate -> Mapping -> Environment Texture -> Background -> World Output

HDRI_WORLD = "m3dHDRI"
HDRI_NODES = {"coord": "M3D HDRI Coordinates", "mapping": "M3D HDRI Mapping", "env": "M3D HDRI Environment",
              "background": "M3D HDRI Background", "output": "M3D HDRI Output"}
DEFAULT_HDRI = "courtyard.exr"


def hdri_nodes(world):
    """The HDRI setup's nodes of a world, or None when it is not one of ours."""
    tree = world.node_tree if world is not None else None
    found = {k: tree.nodes.get(name) for k, name in HDRI_NODES.items()} if tree is not None else {}
    return found if found and all(found.values()) else None


def bundled_hdris():
    """[(label, path)] of the studio HDRIs Blender ships (and the user's own)."""
    return [(os.path.splitext(s.name)[0].replace("_", " ").title(), s.path)
            for s in bpy.context.preferences.studio_lights if s.type == 'WORLD']


def default_hdri():
    found = bundled_hdris()
    return next((p for _l, p in found if os.path.basename(p) == DEFAULT_HDRI), found[0][1] if found else "")


def build_hdri_world(image, rotation=0.0, strength=1.0):
    """The world "m3dHDRI" (made again when it exists) with the image as environment."""
    world = bpy.data.worlds.get(HDRI_WORLD) or bpy.data.worlds.new(HDRI_WORLD)
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    made = {}
    for key, idname, x in (("coord", 'ShaderNodeTexCoord', -900), ("mapping", 'ShaderNodeMapping', -650),
                           ("env", 'ShaderNodeTexEnvironment', -380), ("background", 'ShaderNodeBackground', -100),
                           ("output", 'ShaderNodeOutputWorld', 150)):
        node = tree.nodes.new(idname)
        node.name, node.label, node.location = HDRI_NODES[key], HDRI_NODES[key][5:], (x, 0)
        made[key] = node
    made["env"].image = image
    made["mapping"].inputs["Rotation"].default_value[2] = rotation
    made["background"].inputs["Strength"].default_value = strength
    links = tree.links
    links.new(made["coord"].outputs["Generated"], made["mapping"].inputs["Vector"])
    links.new(made["mapping"].outputs["Vector"], made["env"].inputs["Vector"])
    links.new(made["env"].outputs["Color"], made["background"].inputs["Color"])
    links.new(made["background"].outputs["Background"], made["output"].inputs["Surface"])
    return world


def _hdri_get(default, read):
    def get(self):
        nodes = hdri_nodes(self.id_data.world)
        return read(nodes) if nodes else default
    return get


def _hdri_set(write):
    def set_(self, value):
        nodes = hdri_nodes(self.id_data.world)
        if nodes:
            write(nodes, value)
    return set_


def _set_rotation(nodes, value):
    nodes["mapping"].inputs["Rotation"].default_value[2] = value


def _set_strength(nodes, value):
    nodes["background"].inputs["Strength"].default_value = value


class M3D_RenderSettings(PropertyGroup):
    """Rendering workspace options (Scene.m3d_render)."""
    preset: EnumProperty(name="Quality", default='CUSTOM', items=[*[(k, v, "") for k, v in QUALITY], ('CUSTOM', "Custom", "")],
                         description="The quality preset applied last (Custom once a value was edited)")
    user_preset: StringProperty(name="Your Preset", description="The preset of yours applied last (empty: a built-in one)")
    hdri_path: StringProperty(name="HDRI File", subtype='FILE_PATH', options={'PATH_SUPPORTS_BLEND_RELATIVE'},
                              description="An .exr or .hdr image for the sky")
    hdri_rotation: FloatProperty(
        name="Rotation", subtype='ANGLE', unit='ROTATION', soft_min=-math.pi, soft_max=math.pi, description=
        "Turn the sky around the vertical axis",
        get=_hdri_get(0.0, lambda n: n["mapping"].inputs["Rotation"].default_value[2]),
        set=_hdri_set(_set_rotation))
    hdri_strength: FloatProperty(
        name="Strength", min=0.0, soft_max=10.0, description="Brightness of the sky",
        get=_hdri_get(1.0, lambda n: n["background"].inputs["Strength"].default_value),
        set=_hdri_set(_set_strength))
    previous_world: PointerProperty(type=bpy.types.World, description="The world the scene had before the HDRI")
    keep_renders: BoolProperty(
        name="Keep Each Render", default=True, description=
        "Each render goes into a slot of its own in the Render View (named with the time, the preset and the engine), so "
        "the ones before stay: flip through them with Left / Right or J / Shift+J over the Render View")
    save_stills: BoolProperty(
        name="Save Each Still", default=False, description=
        "Save every still render as render/stills/<scene>_v001.png, v002... next to the saved file")
    browser_material: StringProperty(name="Picked Material", description="The material picked in Scene Materials")


class M3D_OT_hdri_setup(Operator):
    """Light the scene with an HDRI: a new world (Environment Texture, Mapping, Background) is assigned. The world you had
is kept: Back to Previous World puts it back"""
    bl_idname = "m3d.hdri_setup"
    bl_label = "HDRI Sky"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'},
                             description="Image to use (empty: the file picked in the Lighting tab, else a studio HDRI)")

    def execute(self, context):
        scene = context.scene
        s = scene.m3d_render
        path = bpy.path.abspath(self.filepath or s.hdri_path) or default_hdri()
        if not os.path.isfile(path):
            self.report({'ERROR'}, "HDRI file not found: %s" % (path or "no file picked"))
            return {'CANCELLED'}
        try:
            image = bpy.data.images.load(path, check_existing=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        # Rotation and strength carry over when the HDRI world is rebuilt for another image.
        old = hdri_nodes(bpy.data.worlds.get(HDRI_WORLD))
        rotation = old["mapping"].inputs["Rotation"].default_value[2] if old else 0.0
        strength = old["background"].inputs["Strength"].default_value if old else 1.0
        world = build_hdri_world(image, rotation, strength)
        if scene.world != world:
            s.previous_world = scene.world
        scene.world = world
        s.hdri_path = path
        relative_hdri(scene)
        show_world(True)
        return {'FINISHED'}


def is_bundled(path):
    """One of the studio HDRIs of the install (found again by name when the install moves: relink_hdris)."""
    folder = os.path.normcase(os.path.dirname(os.path.abspath(bpy.path.abspath(path))))
    return any(os.path.normcase(os.path.dirname(p)) == folder for _l, p in bundled_hdris())


def _relative(path):
    """`path` relative to the saved file (unchanged: an unsaved file, a bundled HDRI, another drive)."""
    if not bpy.data.filepath or path.startswith("//") or is_bundled(path):
        return path
    try:
        return bpy.path.relpath(path)
    except ValueError:
        return path


def relative_hdri(scene):
    """The scene's HDRI is stored relative to the saved file (Blender makes every path relative when an unsaved file is first
    saved; afterwards a new HDRI would stay absolute)."""
    s = scene.m3d_render
    s.hdri_path = _relative(s.hdri_path)
    nodes = hdri_nodes(scene.world)
    image = nodes["env"].image if nodes else None
    if image is not None and image.library is None and not image.packed_file:
        image.filepath = _relative(image.filepath)


def relink_hdris():
    """A bundled HDRI whose file isn't there (the install moved, another computer): the studio HDRI of the same name in this
    install. The number of images found again."""
    bundled = {os.path.basename(p).lower(): p for _l, p in bundled_hdris()}
    found = 0
    for image in bpy.data.images:
        if image.source != 'FILE' or image.packed_file or image.library is not None or not image.filepath:
            continue
        new = bundled.get(os.path.basename(image.filepath.replace("\\", "/")).lower())
        if new and not os.path.isfile(bpy.path.abspath(image.filepath)):
            image.filepath = new
            found += 1
    for scene in bpy.data.scenes:
        s = scene.m3d_render
        new = bundled.get(os.path.basename(s.hdri_path.replace("\\", "/")).lower())
        if new and not os.path.isfile(bpy.path.abspath(s.hdri_path)):
            s.hdri_path = new
    return found


class M3D_OT_hdri_clear(Operator):
    """Put the world back that the scene had before the HDRI"""
    bl_idname = "m3d.hdri_clear"
    bl_label = "Back to Previous World"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hdri_nodes(context.scene.world) is not None

    def execute(self, context):
        s = context.scene.m3d_render
        context.scene.world = s.previous_world
        s.previous_world = None
        show_world(False)
        return {'FINISHED'}


# --- Files: textures not found after a file loads (a banner in the status bar), Save Copy for Sharing

def image_file(image):
    """The file an image reads (a UDIM image: its first tile), or "" when it reads none (packed, generated, a render)."""
    if image.source not in {'FILE', 'SEQUENCE', 'TILED', 'MOVIE'} or image.packed_file or not image.filepath:
        return ""
    path = bpy.path.abspath(image.filepath, library=image.library)
    if "<UDIM>" in path and len(image.tiles):
        path = path.replace("<UDIM>", str(image.tiles[0].number))
    return path


def missing_images():
    """Names of the images whose file isn't there."""
    return [im.name for im in bpy.data.images if image_file(im) and not os.path.exists(image_file(im))]


_missing = []   # images not found when the file was loaded (the banner shows those still missing)


def still_missing():
    return [name for name in _missing if name in bpy.data.images and image_file(bpy.data.images[name])
            and not os.path.exists(image_file(bpy.data.images[name]))]


def draw_status(layout):
    """Status bar (bl_ui/space_statusbar.py): a background render's progress, the textures a loaded file didn't find."""
    draw_background_status(layout)
    missing = still_missing() if _missing else []
    if not missing:
        return
    from m3d_ui import status_narrow
    row = layout.row(align=True)
    row.label(text="%d texture%s not found" % (len(missing), "" if len(missing) == 1 else "s"), icon='ERROR')
    row.operator("file.find_missing_files", text="" if status_narrow(bpy.context, 1700) else "Find Missing Files...",
                 icon='VIEWZOOM')
    row.operator("m3d.missing_textures", text="Show List")
    row.operator("m3d.missing_textures", text="", icon='X', emboss=False).dismiss = True


class M3D_OT_missing_textures(Operator):
    """The textures this file didn't find: their names and where they were looked for"""
    bl_idname = "m3d.missing_textures"
    bl_label = "Textures Not Found"

    dismiss: BoolProperty(options={'SKIP_SAVE'}, description="Hide the note (File > External Data still finds them)")

    @classmethod
    def description(cls, _context, props):
        return "Hide this note (File > External Data > Find Missing Files still finds them)" if props.dismiss else \
            "The textures this file didn't find: their names and where they were looked for"

    def invoke(self, context, _event):
        if self.dismiss:
            return self.execute(context)
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, _context):
        col = self.layout.column()
        missing = still_missing()
        col.label(text="%d textures not found" % len(missing), icon='ERROR')
        for name in missing[:30]:
            col.label(text="%s:  %s" % (name, image_file(bpy.data.images[name])), translate=False)
        if len(missing) > 30:
            col.label(text="%d more" % (len(missing) - 30))
        col.operator("file.find_missing_files", text="Find Missing Files...", icon='VIEWZOOM')

    def execute(self, _context):
        if self.dismiss:
            _missing.clear()
            import m3d_help
            m3d_help._redraw_status()
        return {'FINISHED'}


@bpy.app.handlers.persistent
def _check_files(*_args):
    """After a file loads: bundled HDRIs found again in this install, then the banner for the textures still missing."""
    relink_hdris()
    _missing[:] = missing_images()
    if _missing:
        print("Maelstrom3D: %d textures not found: %s" % (len(_missing), ", ".join(_missing[:10])))


@bpy.app.handlers.persistent
def _file_saved(*_args):
    for scene in bpy.data.scenes:
        relative_hdri(scene)


def sharing_notes():
    """What stock Blender (5.2 or newer) won't show of this file: lines for the Save Copy for Sharing report."""
    notes = []
    if any(ws.m3d_kind for ws in bpy.data.workspaces):
        notes.append("Workspaces F1-F7 open as plain workspaces, without the F-keys, shelves and menu sets")
    docks = sum(1 for screen in bpy.data.screens for area in screen.areas if area.type == 'PROPERTIES'
                and area.spaces.active.context in {'CHANNEL_BOX', 'MODELING_TOOLKIT'})
    if docks:
        notes.append("%d docks show Maelstrom3D tabs (Channel Box, toolkits): stock Blender shows them empty, so open the "
                     "file there with Load UI off (File > Open, gear menu)" % docks)
    notes.append("Maelstrom3D settings (render presets, texture sets, layers) are kept in the file but not used; "
                 "the scene, materials and renders are plain Blender")
    return notes


def packable(image):
    """An image whose file Save Copy for Sharing can pack: there, not packed, not edited since (packing that would keep the
    edit in the copy but unpacking it again would reload the file: the edit would be lost here)."""
    path = image_file(image)
    return bool(path) and image.source in {'FILE', 'TILED'} and image.library is None and not image.is_dirty and os.path.isfile(path)


class M3D_OT_save_for_sharing(Operator):
    """Save a copy of the scene to give to someone else: the textures go into the file (or stay beside it with relative
    paths), with a note of what stock Blender doesn't show. This scene stays as it is"""
    bl_idname = "m3d.save_for_sharing"
    bl_label = "Save Copy for Sharing"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.blend", options={'HIDDEN'})
    textures: EnumProperty(name="Textures", items=(
        ('PACK', "Pack Into the File", "The textures go into the .blend: one file to send"),
        ('RELATIVE', "Keep Beside It", "The textures stay files, found relative to the .blend: send the folder")))

    def invoke(self, context, _event):
        name = bpy.path.display_name_from_filepath(bpy.data.filepath) or "scene"
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
        self.filepath = os.path.join(folder, bpy.path.clean_name(name) + "_shared.blend")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = bpy.path.ensure_ext(self.filepath, ".blend")
        if bpy.data.filepath and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(bpy.data.filepath)):
            self.report({'ERROR'}, "Pick another name: this is the scene's own file")
            return {'CANCELLED'}
        packed, kept = [], {}
        try:
            if self.textures == 'PACK':
                for image in bpy.data.images:
                    if packable(image):
                        image.pack()
                        packed.append(image)
            elif bpy.data.filepath:
                # Absolute paths relative to this file for the copy (Blender then rebases them to the copy's folder).
                for image in bpy.data.images:
                    if image_file(image) and image.library is None and not image.filepath.startswith("//"):
                        try:
                            kept[image] = image.filepath
                            image.filepath_raw = bpy.path.relpath(image.filepath)
                        except ValueError:
                            del kept[image]   # (another drive: stays absolute)
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, relative_remap=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            for image in packed:
                image.unpack(method='REMOVE')   # (the packed data goes, the path stays: as before)
            for image, old in kept.items():
                image.filepath_raw = old
        missing = missing_images()
        edited = [im.name for im in bpy.data.images if im.is_dirty and image_file(im)]
        lines = ["Saved %s" % path]
        if self.textures == 'PACK':
            lines.append("%d textures packed into the file" % len(packed))
        if missing:
            lines.append("%d textures not found, not in the copy: %s" % (len(missing), ", ".join(missing[:3])))
        if edited:
            lines.append("%d edited textures are in the copy as last saved: save them first (%s)" % (len(edited), ", ".join(edited[:3])))
        lines += sharing_notes()
        self.report({'INFO'}, "; ".join(lines[:2]))
        if not bpy.app.background and context.window is not None:
            def draw(menu, _context):
                for line in lines[1:]:
                    menu.layout.label(text=line, translate=False)
                menu.layout.operator("wm.path_open", text="Open Folder", icon='FILE_FOLDER').filepath = os.path.dirname(path)
            context.window_manager.popup_menu(draw, title=lines[0], icon='FILE_TICK')
        return {'FINISHED'}


def render_views():
    """The 3D views of the Rendering workspace (F7)."""
    return [a.spaces.active for ws in bpy.data.workspaces if workspace_kind(ws) == 'RENDER' for screen in ws.screens
            for a in screen.areas if a.type == 'VIEW_3D']


def show_world(on):
    """The sky lights the Material Preview of F7's 3D view (HDRI Sky), or the studio light does again (Back to Previous
    World: a plain world is dark)."""
    for space in render_views():
        space.shading.use_scene_world = on


RENDER_LAYOUT = 1   # Workspace.m3d_layout of the Rendering workspace: 1 lights its Material Preview with the scene's lights


def show_scene_lights(ws):
    """Once for a Rendering workspace (startup, or an older file): its Material Preview shows the scene's lights (afterwards the
    choice is the user's: the Lighting menu)."""
    if ws.m3d_layout < RENDER_LAYOUT:
        for screen in ws.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.spaces.active.shading.use_scene_lights = True
        ws.m3d_layout = RENDER_LAYOUT


class M3D_OT_view_lighting(Operator):
    """Lighting of the 3D view"""
    bl_idname = "m3d.view_lighting"
    bl_label = "Viewport Lighting"
    bl_options = {'REGISTER'}

    LIGHTING = (('DEFAULT', "Use Default Lighting", "Light the view with the studio light (not the scene's lights or sky)"),
                ('FLAT', "Use Flat Lighting", "Flat colors, no lighting (Solid shading)"),
                ('ALL', "Use All Lights", "Light the view with the scene's lights (Material Preview)"))
    lighting: EnumProperty(items=LIGHTING)

    @classmethod
    def description(cls, _context, props):
        return {key: text for key, _label, text in cls.LIGHTING}[props.lighting]

    def execute(self, context):
        space = context.space_data if context.space_data is not None and context.space_data.type == 'VIEW_3D' else viewport(context)
        if space is None:
            self.report({'WARNING'}, "No 3D Viewport here")
            return {'CANCELLED'}
        shading = space.shading
        if self.lighting == 'ALL':
            if shading.type not in {'MATERIAL', 'RENDERED'}:
                shading.type = 'MATERIAL'
            shading.use_scene_lights = shading.use_scene_lights_render = True
        elif self.lighting == 'FLAT':
            shading.type, shading.light = 'SOLID', 'FLAT'
        else:
            shading.light = 'STUDIO'
            shading.use_scene_lights = shading.use_scene_world = False
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Camera

class M3D_OT_render_camera_from_view(Operator):
    """Camera from the viewport: a new camera at the current view (it becomes the scene camera), or the scene camera
moved to the view"""
    bl_idname = "m3d.render_camera_from_view"
    bl_label = "Camera from View"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('NEW', "New Camera from View", "Add a camera at this view and make it the scene camera"),
                              ('MATCH', "Match Camera to View", "Move the scene camera to this view")))

    @classmethod
    def description(cls, _context, props):
        return {'NEW': "Add a camera at the current view and make it the scene camera",
                'MATCH': "Move the scene camera to the current view"}[props.mode]

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and viewport(context) is not None

    def execute(self, context):
        space, scene = viewport(context), context.scene
        rv3d = space.region_3d
        old = scene.camera if scene.camera is not None and scene.camera.type == 'CAMERA' else None
        looking = rv3d.view_perspective == 'CAMERA' and old is not None
        if self.mode == 'MATCH' and looking:
            self.report({'INFO'}, "The view is the camera already: orbit away first")
            return {'CANCELLED'}
        matrix = old.matrix_world.copy() if looking else rv3d.view_matrix.inverted()
        if self.mode == 'NEW' or old is None:
            data = bpy.data.cameras.new("Camera")
            # The viewport lens assumes a 72 mm sensor.
            data.lens = old.data.lens if looking else space.lens * data.sensor_width / 72.0
            old = bpy.data.objects.new("Camera", data)
            context.collection.objects.link(old)
            scene.camera = old
            for ob in context.selected_objects:
                ob.select_set(False)
            old.select_set(True)
            context.view_layer.objects.active = old
        old.matrix_world = matrix
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Render, Render View, IPR

def render_view_area(screen):
    """The Image Editor of the Rendering workspace: the Render View."""
    found = [a for a in screen.areas if a.type == 'IMAGE_EDITOR'] if screen else []
    return max(found, key=lambda a: a.width * a.height) if found else None


GRAPH = 'ShaderNodeTree'   # the ui_type F7's middle area shows instead of the Render View


def middle_area(screen):
    """F7's middle area: the Render View, or the Shader Graph it was switched to (the area keeps what it shows, so each
    Rendering workspace remembers it)."""
    found = [a for a in screen.areas if a.type == 'IMAGE_EDITOR' or a.ui_type == GRAPH] if screen else []
    return max(found, key=lambda a: a.width * a.height) if found else None


def graph_shown(screen):
    area = middle_area(screen)
    return area is not None and area.ui_type == GRAPH


def render_view_back(screen):
    """The Shader Graph of F7's middle area goes back to the Render View (a render shows there)."""
    area = middle_area(screen)
    if area is not None and area.ui_type == GRAPH:
        area.ui_type = 'IMAGE_EDITOR'


class M3D_OT_render_graph(Operator):
    """Shader Graph: F7's Render View shows the active material's shader graph instead (click again, or Render View, for the
    render)"""
    bl_idname = "m3d.render_graph"
    bl_label = "Shader Graph"

    show: EnumProperty(name="Show", default='TOGGLE', options={'SKIP_SAVE'}, items=(
        ('TOGGLE', "Toggle", "Switch between the Render View and the Shader Graph"),
        ('GRAPH', "Shader Graph", "Show the active material's shader graph"),
        ('RENDER', "Render View", "Show the render")))

    def execute(self, context):
        area = middle_area(context.screen) if current_kind(context) == 'RENDER' else None
        if area is None:   # (not in F7: the Shader Editor in a window of its own)
            return bpy.ops.m3d.open_editor(ui_type=GRAPH)
        graph = area.ui_type != GRAPH if self.show == 'TOGGLE' else self.show == 'GRAPH'
        if graph:
            new = not any(space.type == 'NODE_EDITOR' for space in area.spaces)
            area.ui_type = GRAPH
            if new:   # (the first time: no sidebar, the graph framed once it has been drawn)
                area.spaces.active.show_region_ui = False
                key = area.as_pointer()
                bpy.app.timers.register(lambda: frame_graph(key), first_interval=0.2)
        else:
            area.ui_type = 'IMAGE_EDITOR'
            show_render_result(context)
        return {'FINISHED'}


def frame_graph(key):
    """Frame the whole graph in the area `key` (a pointer)."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() == key and area.type == 'NODE_EDITOR':
                region = next(r for r in area.regions if r.type == 'WINDOW')
                with bpy.context.temp_override(window=win, area=area, region=region):
                    if bpy.ops.node.view_all.poll():   # (an object without a material: no graph to frame)
                        bpy.ops.node.view_all()
    return None


def show_render_result(context):
    """Point the Rendering workspace's Image Editor at the Render Result (a render then shows there, not in a new window).
    False when this is another workspace or nothing has been rendered yet."""
    area = render_view_area(context.screen) if current_kind(context) == 'RENDER' else None
    image = next((i for i in bpy.data.images if i.type == 'RENDER_RESULT'), None)
    if area is None or image is None:
        return False
    if area.spaces.active.image != image:
        area.spaces.active.image = image
    area.tag_redraw()
    return True


def follow(wm):
    """Workspace timer: a Rendering workspace with an empty Render View (just reset, or from an older file) shows the Render
    Result as soon as there is one; its Material Preview gets the scene's lights once (show_scene_lights)."""
    win = wm.windows[0] if wm.windows else None
    if win is not None and workspace_kind(win.workspace) == 'RENDER':
        show_scene_lights(win.workspace)
        area = render_view_area(win.screen)
        if area is not None and area.spaces.active.image is None:
            show_render_result(SimpleNamespace(workspace=win.workspace, screen=win.screen))


def render_view_empty(context):
    """Is this Image Editor the Rendering workspace's Render View with nothing to show (no image, or a Render Result without a
    render: renders are not saved in the file)?"""
    space = context.space_data
    if current_kind(context) != 'RENDER' or space is None or space.type != 'IMAGE_EDITOR' or space.mode != 'VIEW':
        return False
    image = space.image
    return image is None or (image.type == 'RENDER_RESULT' and not _rendered[0])


_rendered = [False]   # a render was started in this session (the Render Result has pixels; Python can't ask the image)


@bpy.app.handlers.persistent
def _render_started(*_args):
    _rendered[0] = True


@bpy.app.handlers.persistent
def _file_loaded(*_args):
    _rendered[0] = False   # (a file has no render in it)
    _slots.clear()
    _compare["slot"] = None
    image = render_result()
    for i, slot in enumerate(image.render_slots if image is not None else ()):
        if SLOT_NAME.match(slot.name):   # (our names say what a render was; the file has none)
            slot.name = "Slot %d" % (i + 1)


def empty_hint(context):
    """The line an empty Render View shows: how to render, with the key from the user's keymap."""
    from m3d_ui import key_text
    key = key_text(context, "Screen Editing", "m3d.render", {"animation": False})
    return "Nothing rendered yet: Render%s to see it here" % (" (%s)" % key if key else "")


def draw_empty_hint():
    """Draw handler of the Image Editors: the empty Render View's hint, centred (a line over the checkerboard)."""
    context = bpy.context
    if not render_view_empty(context):
        return
    import blf
    from m3d_sculpt import ui_scale_factor
    region, text = context.region, empty_hint(context)
    font, scale = 0, ui_scale_factor(context)
    blf.size(font, 13 * scale)
    width, height = blf.dimensions(font, text)
    blf.color(font, 0.85, 0.85, 0.85, 1.0)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 5, 0.0, 0.0, 0.0, 1.0)
    blf.position(font, (region.width - width) / 2, (region.height - height) / 2, 0)
    blf.draw(font, text)
    blf.disable(font, blf.SHADOW)


_draw_handlers = []


# --- Before a render: the camera it renders from, the frames that are there already

_camera_ok = set()   # cameras the first-render question was answered for in this session (by name)


def hidden_camera(context):
    """The scene camera when the render would come from a camera nobody sees (the hidden "persp" of a new scene, or another
    hidden one) and the view doesn't look through it, the first time in this session; else None."""
    import m3d_user
    cam, space = context.scene.camera, viewport(context)
    if cam is None or cam.name in _camera_ok or m3d_user.data().get("render_camera_ask") is False:
        return None
    if space is not None and space.region_3d is not None and space.region_3d.view_perspective == 'CAMERA':
        return None
    return cam if not cam.visible_get(view_layer=context.view_layer) else None


def name_frames(scene):
    """Frames named after the scene: an output path that is only a folder ("//render/") gets "<scene>_" (else the frames are
    0001.png, 0002.png...)."""
    r = scene.render
    if r.filepath and r.filepath[-1] in "/\\":
        r.filepath += bpy.path.clean_name(scene.name) + "_"


def frame_numbers(scene):
    return range(scene.frame_start, scene.frame_end + 1, max(scene.frame_step, 1))


def existing_frames(scene):
    """Frames of the range whose files are there already (a video: its one file)."""
    r = scene.render
    if r.image_settings.media_type == 'VIDEO':
        return [scene.frame_start] if os.path.isfile(r.frame_path(frame=scene.frame_start)) else []
    return [f for f in frame_numbers(scene) if os.path.isfile(r.frame_path(frame=f))]


def output_folder(scene):
    return os.path.dirname(scene.render.frame_path(frame=scene.frame_start))


VERSION_FOLDER = re.compile(r"^v(\d{3,})$")


def next_version(path):
    """The output path in the next version folder that isn't there yet: render/shot_ -> render/v002/shot_,
    render/v002/shot_ -> render/v003/shot_ (the frames of the first render are version 1)."""
    relative = path.startswith("//")
    folder, _sep, name = path[2 if relative else 0:].replace("\\", "/").rpartition("/")
    parent, _sep, last = folder.rpartition("/")
    found = VERSION_FOLDER.match(last)
    base, number = (parent, int(found.group(1)) + 1) if found else (folder, 2)
    prefix = ("//" if relative else "") + (base + "/" if base else "")
    while os.path.exists(bpy.path.abspath("%sv%03d" % (prefix, number))):
        number += 1
    return "%sv%03d/%s" % (prefix, number, name)


_animation = {"scene": None, "frames": 0}   # the animation render that runs (the report after it)


def animation_done():
    """Timer while an animation renders: then say how many frames are where, with Open Folder."""
    if bpy.app.is_job_running('RENDER'):
        return 0.5
    scene = bpy.data.scenes.get(_animation["scene"] or "")
    _animation["scene"] = None
    if scene is None:
        return None
    text = render_report(scene, _animation["frames"])
    import m3d_bakeq
    m3d_bakeq.report_later('INFO', text)
    wm = bpy.context.window_manager
    folder = output_folder(scene)
    if wm.windows and not bpy.app.background:
        def draw(menu, _context):
            menu.layout.operator("wm.path_open", text="Open Folder", icon='FILE_FOLDER').filepath = folder
        win = wm.windows[0]
        with bpy.context.temp_override(window=win, screen=win.screen):
            wm.popup_menu(draw, title=text, icon='RENDER_ANIMATION')
    return None


def render_report(scene, frames):
    found = len(existing_frames(scene)) if scene.render.image_settings.media_type != 'VIDEO' else frames
    done = "%d frames" % found if found == frames else "%d of %d frames" % (found, frames)
    return "Rendered %s to %s" % (done, output_folder(scene))


# --- Render snapshots: each still in a slot of its own (Keep Each Render), named with the time, the preset and the engine

MAX_SLOTS = 16   # slots the Render Result grows to; then the oldest render makes room (each slot holds a whole render)
SLOT_NAME = re.compile(r"^\d\d:\d\d ")   # a slot named by us (a file keeps the names, not the renders)
_slots = []      # Render Result slots holding a render of this session, oldest first
_compare = {"slot": None}   # the slot A/B flips to


def render_result():
    return next((i for i in bpy.data.images if i.type == 'RENDER_RESULT'), None)


def slot_label(scene):
    """"14:32 Medium EEVEE": when, which preset, which engine."""
    now = current_quality(scene)
    preset = dict(QUALITY).get(now) or ("Custom" if now == 'CUSTOM' else now)
    engine = dict(ENGINES).get(scene.render.engine) or scene.render.engine.replace("BLENDER_", "").title()
    return "%s %s %s" % (time.strftime("%H:%M"), preset, engine)


def pick_slot(image):
    """Keep Each Render: the next render goes into the first slot without a render of this session, else a new slot (up to
    MAX_SLOTS), else the oldest one's. The one shown before is what A/B flips back to."""
    slots = image.render_slots
    _compare["slot"] = slots.active_index
    free = next((i for i in range(len(slots)) if i not in _slots), None)
    if free is None and len(slots) < MAX_SLOTS:
        slots.new()
        free = len(slots) - 1
    slots.active_index = _slots[0] if free is None else free


def name_slot(image, scene):
    """The slot the render went into gets its name and is the newest of this session."""
    index = image.render_slots.active_index
    if index in _slots:
        _slots.remove(index)
    _slots.append(index)
    image.render_slots[index].name = slot_label(scene)


def still_path(scene):
    """render/stills/<scene>_v###.png next to the saved file, the next number that isn't there yet."""
    folder = bpy.path.abspath("//render/stills/")
    base = bpy.path.clean_name(scene.name)
    found = [int(m.group(1)) for name in (os.listdir(folder) if os.path.isdir(folder) else ())
             for m in [re.match(re.escape(base) + r"_v(\d+)\.png$", name)] if m]
    return os.path.join(folder, "%s_v%03d.png" % (base, max(found, default=0) + 1))


def save_still(scene):
    """Save Each Still: the Render Result's slot as a PNG (whatever the output type is; the settings are put back). The path,
    or None (no render, an unsaved file)."""
    image = render_result()
    if image is None or not bpy.data.filepath:
        return None
    path = still_path(scene)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = scene.render.image_settings
    before = [("media_type", im.media_type), ("file_format", im.file_format), ("color_mode", im.color_mode),
              ("color_depth", im.color_depth)]
    try:
        im.media_type, im.file_format = 'IMAGE', 'PNG'
        image.save_render(path, scene=scene)
    finally:
        for name, value in before:
            try:
                setattr(im, name, value)
            except (TypeError, ValueError):
                pass   # (a value the format before has no more: its default)
    return path


_still = {"scene": None, "cancelled": False}   # the still render that runs (Save Each Still after it)


def still_done():
    """Timer while a still renders: then Save Each Still."""
    if bpy.app.is_job_running('RENDER'):
        return 0.5
    scene = bpy.data.scenes.get(_still["scene"] or "")
    _still["scene"] = None
    if scene is not None and not _still["cancelled"]:
        path = save_still(scene)
        if path:
            import m3d_bakeq
            m3d_bakeq.report_later('INFO', "Saved the still to " + path)
    return None


@bpy.app.handlers.persistent
def _render_cancelled(*_args):
    _still["cancelled"] = True


class M3D_OT_render_compare(Operator):
    """A/B: flip the Render View to the render before; again flips back (Left / Right or J / Shift+J go through all of them)"""
    bl_idname = "m3d.render_compare"
    bl_label = "A/B"

    @classmethod
    def poll(cls, context):
        image = render_result()
        return image is not None and len(_slots) > 1

    def execute(self, _context):
        image = render_result()
        slots = image.render_slots
        now = slots.active_index
        other = _compare["slot"]
        if other is None or other == now or other >= len(slots) or other not in _slots:
            other = next((i for i in reversed(_slots) if i != now), now)
        slots.active_index, _compare["slot"] = other, now
        image.update_tag()
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.tag_redraw()
        return {'FINISHED'}


def slots_only(context, image):
    """Does the Render View's header need only the slot dropdown (the Render Result of a scene with one render layer and no
    passes; else Blender's slot / layer / pass dropdowns)?"""
    scene = context.scene
    return image.type == 'RENDER_RESULT' and len(scene.view_layers) == 1 and not extra_passes(scene)


class M3D_MT_render_slots(Menu):
    """The Render View's slots: each render of this session (Keep Each Render), Left / Right or J / Shift+J flip through them"""
    bl_label = "Render Slots"

    def draw(self, _context):
        image = render_result()
        for i, slot in enumerate(image.render_slots if image is not None else ()):
            o = self.layout.operator("wm.context_set_int", text=slot.name, translate=False,
                                     icon='CHECKMARK' if i == image.render_slots.active_index else 'BLANK1')
            o.data_path, o.value = "space_data.image.render_slots.active_index", i
        others = [im for im in bpy.data.images if im.type != 'RENDER_RESULT' and not is_internal_material(im)]
        if others:   # (to show another image instead: its own picker comes back with it)
            self.layout.separator()
            self.layout.label(text="Show Another Image")
            for im in others[:20]:
                o = self.layout.operator("wm.context_set_id", text=im.name, translate=False, icon='IMAGE_DATA')
                o.data_path, o.value = "space_data.image", im.name


def draw_slot_menu(layout, image):
    slot = image.render_slots.active
    sub = layout.row()
    sub.ui_units_x = 7
    sub.menu("M3D_MT_render_slots", text=slot.name if slot is not None else "Slot", icon='RENDER_RESULT')


def draw_render_view_header(layout, context):
    """The Render View's header (bl_ui/space_image.py), beside its menus: the slot dropdown (when it needs no layer / pass
    dropdowns), A/B and Save Render (an icon: the header is narrow; Keep Each Render is in the Output tab and the Render menu)."""
    image = context.space_data.image
    if slots_only(context, image):
        draw_slot_menu(layout, image)
    row = layout.row(align=True)
    row.operator("m3d.render_compare", text="A/B")
    row.operator("image.save_as", text="", icon='FILE_TICK').copy = False


class M3D_OT_render(Operator):
    """Render the scene: a still, or the whole animation. The result shows in the Render View"""
    bl_idname = "m3d.render"
    bl_label = "Render"

    animation: BoolProperty(default=False, options={'SKIP_SAVE'}, description="Render the whole frame range")
    existing: EnumProperty(name="Frames There", default='ASK', options={'SKIP_SAVE'}, items=(
        ('ASK', "Ask", "Render over them as Blender does (the Overwrite setting)"),
        ('OVERWRITE', "Overwrite", "Render over the frames that are there"),
        ('VERSION', "New Version Folder", "Render into the next version folder (v002, v003...): the frames there stay")))
    camera: EnumProperty(name="Camera", default='ASK', options={'SKIP_SAVE'}, items=(
        ('ASK', "Ask", "Render from the scene camera"),
        ('MATCH', "Match Camera to View", "Move the scene camera to this view, then render"),
        ('ANYWAY', "Render Anyway", "Render from the scene camera as it is")))
    dont_ask: BoolProperty(name="Don't ask again", options={'SKIP_SAVE'},
                           description="Never ask about a hidden camera again (on this computer)")
    asked_camera: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    asked_frames: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    interactive: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return "Render the animation (Ctrl+Shift+F12)" if props.animation else "Render the current frame (Shift+F12)"

    def invoke(self, context, _event):
        scene = context.scene
        if self.animation and not bpy.data.filepath and scene.render.filepath.startswith("//"):
            self.report({'WARNING'}, "Save the scene first: the frames go into a folder next to it")
            bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
            return {'CANCELLED'}
        self.interactive = True
        cam = hidden_camera(context)
        if self.animation:
            name_frames(scene)
        self.asked_camera = cam.name if cam is not None else ""
        self.asked_frames = self.animation and bool(existing_frames(scene))
        if not (self.asked_camera or self.asked_frames):
            return self.execute(context)
        if self.asked_camera:
            self.camera = 'MATCH'
        if self.asked_frames:
            self.existing = 'VERSION'
        return context.window_manager.invoke_props_dialog(self, width=420, title="Render Animation" if self.animation
                                                          else "Render", confirm_text="Render")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        if self.asked_camera:
            layout.label(text="Rendering from camera \"%s\", not this view" % self.asked_camera, icon='CAMERA_DATA')
            row = layout.row(align=True)
            for key in ('MATCH', 'ANYWAY'):
                row.prop_enum(self, "camera", key)
            layout.prop(self, "dont_ask")
        if self.asked_frames:
            layout.label(text="%d frames are in %s already" % (len(existing_frames(scene)), output_folder(scene)),
                         icon='FILE_FOLDER')
            row = layout.row(align=True)
            for key in ('VERSION', 'OVERWRITE'):
                row.prop_enum(self, "existing", key)

    def answer(self, context):
        """What the dialog asked (or the properties say)."""
        scene = context.scene
        if self.camera != 'ASK' and scene.camera is not None:
            _camera_ok.add(scene.camera.name)
            if self.camera == 'MATCH':
                if bpy.ops.m3d.render_camera_from_view.poll():
                    bpy.ops.m3d.render_camera_from_view(mode='MATCH')
                else:
                    self.report({'WARNING'}, "Match Camera to View needs Object Mode and a 3D view: rendering from the camera as it is")
        if self.dont_ask:
            import m3d_user
            m3d_user.data()["render_camera_ask"] = False
            m3d_user.save()
        if self.animation:
            name_frames(scene)
            if self.existing == 'VERSION':
                scene.render.filepath = next_version(scene.render.filepath)
            elif self.existing == 'OVERWRITE':
                scene.render.use_overwrite = True
        if scene.render.engine == 'CYCLES' and scene.cycles.device == 'GPU':
            import m3d_bakeq
            if not m3d_bakeq.find_gpu(context)[0]:   # (sets Cycles' preferences up for the GPU: asked once)
                self.report({'WARNING'}, "No GPU passed a test bake: Cycles renders on the CPU")

    def execute(self, context):
        self.answer(context)
        scene = context.scene
        image = render_result()
        if not self.animation and image is not None and scene.m3d_render.keep_renders:
            pick_slot(image)
        if self.interactive:
            # The Rendering workspace has its Render View: while it shows the Render Result, no render window opens (the
            # preference "Render In" is put back as soon as the render has started).
            view = context.preferences.view
            display = view.render_display_type
            render_view_back(context.screen if current_kind(context) == 'RENDER' else None)
            if show_render_result(context):
                view.render_display_type = 'NONE'
            try:
                bpy.ops.render.render('INVOKE_DEFAULT', animation=self.animation, use_viewport=True)
            except RuntimeError as err:
                self.report({'ERROR'}, str(err).strip())
                return {'CANCELLED'}
            finally:
                view.render_display_type = display
            if self.animation:
                _animation["scene"], _animation["frames"] = scene.name, len(frame_numbers(scene))
                if not bpy.app.timers.is_registered(animation_done):
                    bpy.app.timers.register(animation_done, first_interval=1.0)
            else:
                self.after_still(scene, later=True)
            return {'FINISHED'}
        try:
            result = bpy.ops.render.render(animation=self.animation, use_viewport=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        if self.animation:
            self.report({'INFO'}, render_report(scene, len(frame_numbers(scene))))
        else:
            self.after_still(scene, later=False)
        return result

    def after_still(self, scene, later):
        """The still's slot is named; Save Each Still saves it (`later`: once the render job is over)."""
        image = render_result()
        if image is not None:
            name_slot(image, scene)
        if not scene.m3d_render.save_stills:
            return
        if not bpy.data.filepath:
            self.report({'WARNING'}, "Save Each Still: save the scene first (the stills go next to it)")
        elif later:
            _still["scene"], _still["cancelled"] = scene.name, False
            if not bpy.app.timers.is_registered(still_done):
                bpy.app.timers.register(still_done, first_interval=1.0)
        else:
            path = save_still(scene)
            if path:
                self.report({'INFO'}, "Saved the still to " + path)


# --- Render Sequence in Background: a copy of the scene renders in another Blender (low priority) while you work on

_bg = {"proc": None, "reader": None, "scene": "", "total": 0, "saved": 0, "frame": None, "folder": "", "temp": "", "error": "",
       "state": None}   # state: None, 'RUNNING', 'DONE', 'CANCELLED', 'FAILED'
# The job's log lines ("00:01.469  render | Saved: '...'"; older builds: "Fra:12 ...", "Saved: '...'").
SAVED_LINE = re.compile(r"(^|\| )(Saved: |Append frame )")
FRAME_LINE = re.compile(r"Rendering frame (\d+)|Fra:(\d+)")
ERROR_LINE = re.compile(r"(^|\| )(ERROR|Error)\b")


def job_command(blend, scene):
    """The command that renders `blend`'s scene's animation with this Blender, headless (no crash dialog either)."""
    return [bpy.app.binary_path, "--console-crash-handler", "-b", blend, "-S", scene.name, "-a"]


def save_job_copy(scene, path):
    """Save a copy of the file (unsaved changes too) at `path` for a render job: the output path is made absolute, so the
    frames go where this scene says."""
    r = scene.render
    before = r.filepath
    r.filepath = bpy.path.abspath(r.filepath)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, relative_remap=True)
    finally:
        r.filepath = before


def _read_output(proc):
    """Thread: the job's output, line by line, into _bg (the frame it is on, frames saved, the last error)."""
    for line in proc.stdout:
        line = line.strip()
        found = FRAME_LINE.search(line)
        if found:
            _bg["frame"] = int(found.group(1) or found.group(2))
        if SAVED_LINE.search(line):
            _bg["saved"] += 1
        elif ERROR_LINE.search(line):
            _bg["error"] = line.rpartition("| ")[2]


def background_tick():
    """Timer while the job runs: the status bar redraws; at the end, the report and the temporary copy goes."""
    import m3d_help
    m3d_help._redraw_status()
    proc = _bg["proc"]
    if proc is None:
        return None
    if proc.poll() is None or _bg["reader"].is_alive():   # (the last lines may still be on their way)
        return 0.5
    _bg["proc"] = None
    shutil.rmtree(_bg["temp"], ignore_errors=True)
    if _bg["state"] == 'RUNNING':
        _bg["state"] = 'DONE' if proc.returncode == 0 and _bg["saved"] else 'FAILED'
    import m3d_bakeq
    m3d_bakeq.report_later('INFO' if _bg["state"] == 'DONE' else 'WARNING', background_text())
    return None


def background_text():
    b = _bg
    if b["state"] == 'RUNNING':
        return "Rendering in the background: frame %s, %d of %d saved" % (b["frame"] or "-", b["saved"], b["total"])
    if b["state"] == 'DONE':
        return "Background render done: %d frames to %s" % (b["saved"], b["folder"])
    if b["state"] == 'CANCELLED':
        return "Background render cancelled: %d of %d frames saved" % (b["saved"], b["total"])
    return "Background render stopped%s: %d of %d frames saved" % (": " + b["error"] if b["error"] else "", b["saved"], b["total"])


def draw_background_status(layout):
    """The background render's progress, Cancel and Open Folder (status bar); after it, the result until closed."""
    if _bg["state"] is None:
        return
    row = layout.row(align=True)
    if _bg["state"] == 'RUNNING':
        from m3d_ui import status_narrow
        narrow = status_narrow(bpy.context, 1700)
        bar = row.row(align=True)
        bar.ui_units_x = 7 if narrow else 11   # (the whole text)
        bar.progress(factor=min(_bg["saved"] / max(_bg["total"], 1), 1.0), type='BAR',
                     text=("%d / %d frames" if narrow else "Background render: %d / %d frames") % (_bg["saved"], _bg["total"]))
        row.operator("m3d.render_background_stop", text="Cancel", icon='CANCEL')
    else:
        row.label(text=background_text(), icon='CHECKMARK' if _bg["state"] == 'DONE' else 'ERROR')
    if os.path.isdir(_bg["folder"]):
        row.operator("wm.path_open", text="", icon='FILE_FOLDER').filepath = _bg["folder"]
    if _bg["state"] != 'RUNNING':
        row.operator("m3d.render_background_stop", text="", icon='X', emboss=False)


class _JobOutput:
    """The checks before an animation goes to another Blender: a saved file for an output next to it, frames there already."""
    existing: EnumProperty(name="Frames There", default='ASK', options={'SKIP_SAVE'}, items=(
        ('ASK', "Ask", "Render over them as Blender does (the Overwrite setting)"),
        ('OVERWRITE', "Overwrite", "Render over the frames that are there"),
        ('VERSION', "New Version Folder", "Render into the next version folder (v002, v003...): the frames there stay")))

    def invoke(self, context, _event):
        scene = context.scene
        if not bpy.data.filepath and scene.render.filepath.startswith("//"):
            self.report({'WARNING'}, "Save the scene first: the frames go into a folder next to it")
            bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
            return {'CANCELLED'}
        name_frames(scene)
        if self.ask_frames() and existing_frames(scene):
            self.existing = 'VERSION'
            return context.window_manager.invoke_props_dialog(self, width=420, confirm_text=self.bl_label)
        return self.start(context)

    def ask_frames(self):
        return True

    def draw(self, context):
        scene = context.scene
        self.layout.label(text="%d frames are in %s already" % (len(existing_frames(scene)), output_folder(scene)),
                          icon='FILE_FOLDER')
        row = self.layout.row(align=True)
        for key in ('VERSION', 'OVERWRITE'):
            row.prop_enum(self, "existing", key)

    def execute(self, context):
        return self.start(context)

    def prepare(self, context):
        scene = context.scene
        if not bpy.data.filepath and scene.render.filepath.startswith("//"):
            self.report({'WARNING'}, "Save the scene first: the frames go into a folder next to it")
            return False
        name_frames(scene)
        if self.existing == 'VERSION':
            scene.render.filepath = next_version(scene.render.filepath)
        elif self.existing == 'OVERWRITE':
            scene.render.use_overwrite = True
        return True


class M3D_OT_render_background(_JobOutput, Operator):
    """Render the animation in the background: a copy of the scene renders in another Blender (low priority) while you go on
    working; the status bar shows the frames, with Cancel and Open Folder"""
    bl_idname = "m3d.render_background"
    bl_label = "Render Sequence in Background"

    def start(self, context):
        if _bg["state"] == 'RUNNING':
            self.report({'WARNING'}, "A background render is running: cancel it first (status bar)")
            return {'CANCELLED'}
        if not self.prepare(context):
            return {'CANCELLED'}
        scene = context.scene
        temp = tempfile.mkdtemp(prefix="m3d_bgrender_")
        blend = os.path.join(temp, bpy.path.clean_name(bpy.path.display_name_from_filepath(bpy.data.filepath) or "scene") + ".blend")
        try:
            save_job_copy(scene, blend)
        except RuntimeError as err:
            shutil.rmtree(temp, ignore_errors=True)
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        options = {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW} \
            if sys.platform == "win32" else {"preexec_fn": lambda: os.nice(10)}
        try:
            proc = subprocess.Popen(job_command(blend, scene), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", **options)
        except OSError as err:
            shutil.rmtree(temp, ignore_errors=True)
            self.report({'ERROR'}, "Could not start the render: %s" % err)
            return {'CANCELLED'}
        _bg.update(proc=proc, scene=scene.name, total=len(frame_numbers(scene)), saved=0, frame=None,
                   folder=output_folder(scene), temp=temp, error="", state='RUNNING')
        _bg["reader"] = threading.Thread(target=_read_output, args=(proc,), daemon=True)
        _bg["reader"].start()
        if not bpy.app.timers.is_registered(background_tick):
            bpy.app.timers.register(background_tick, first_interval=0.5)
        self.report({'INFO'}, "Rendering %d frames in the background to %s" % (_bg["total"], _bg["folder"]))
        return {'FINISHED'}


class M3D_OT_render_background_stop(Operator):
    """Cancel the background render (the frames saved so far stay); after it: close its note"""
    bl_idname = "m3d.render_background_stop"
    bl_label = "Cancel Background Render"

    def execute(self, _context):
        proc = _bg["proc"]
        if proc is not None and proc.poll() is None:
            _bg["state"] = 'CANCELLED'
            proc.kill()
            proc.wait(timeout=10)
            _bg["reader"].join(timeout=5)
            background_tick()
        else:
            _bg["state"] = None
        import m3d_help
        m3d_help._redraw_status()
        return {'FINISHED'}


class M3D_OT_render_job_export(_JobOutput, Operator):
    """Export Render Job: a copy of the scene and a script (.bat on Windows, .sh elsewhere) that renders its animation with
    this Blender, to run later or on another computer with Maelstrom3D in the same place"""
    bl_idname = "m3d.render_job_export"
    bl_label = "Export Render Job"

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.bat;*.sh", options={'HIDDEN'})

    def ask_frames(self):
        return False   # (the job runs later: the frames there now may be gone by then)

    def invoke(self, context, event):
        if not self.filepath:
            name = bpy.path.clean_name(bpy.path.display_name_from_filepath(bpy.data.filepath) or "scene")
            folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
            self.filepath = os.path.join(folder, name + "_render" + (".bat" if sys.platform == "win32" else ".sh"))
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        return super().invoke(context, event)

    def start(self, context):
        if not self.prepare(context):
            return {'CANCELLED'}
        scene = context.scene
        windows = sys.platform == "win32"
        script = bpy.path.ensure_ext(os.path.splitext(self.filepath)[0], ".bat" if windows else ".sh")
        blend = os.path.splitext(script)[0] + ".blend"
        try:
            save_job_copy(scene, blend)
            command = " ".join('"%s"' % part for part in job_command(blend, scene))
            with open(script, "w", encoding="utf-8", newline="\r\n" if windows else "\n") as fh:
                if windows:
                    fh.write("@echo off\nrem Maelstrom3D render job: %s, frames %d-%d into %s\n" % (
                        scene.name, scene.frame_start, scene.frame_end, output_folder(scene)))
                    fh.write('start "" /low /wait /b %s\n' % command)
                else:
                    fh.write("#!/bin/sh\n# Maelstrom3D render job: %s, frames %d-%d into %s\nnice -n 10 %s\n" % (
                        scene.name, scene.frame_start, scene.frame_end, output_folder(scene), command))
            if not windows:
                os.chmod(script, 0o755)
        except (OSError, RuntimeError) as err:
            self.report({'ERROR'}, "Could not write the render job: %s" % err)
            return {'CANCELLED'}
        self.report({'INFO'}, "Render job: run %s (it renders %s)" % (script, os.path.basename(blend)))
        return {'FINISHED'}


# --- Turntable: a camera on a pivot at the selection's centre, once around over the frame range (or the sky turns instead)

TURNTABLE = "m3d_turntable"   # custom property of the pivot: 'CAMERA' or 'HDRI'
ELEVATION = math.radians(15)


def turntable_pivot(scene):
    return next((o for o in scene.objects if TURNTABLE in o), None)


def bounds(obs):
    """(centre, radius) of the objects' bounding boxes in world space."""
    corners = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
    lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    centre = (lo + hi) / 2
    return centre, max(max((c - centre).length for c in corners), 0.01)


def make_linear(owner, data_path):
    """The keys of `owner`'s F-curves on `data_path` run at an even speed (no ease in / out)."""
    from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
    ad = owner.animation_data
    bag = animdata_get_channelbag_for_assigned_slot(ad) if ad is not None and ad.action is not None else None
    for fc in bag.fcurves if bag is not None else ():
        if fc.data_path == data_path:
            for key in fc.keyframe_points:
                key.interpolation = 'LINEAR'


def spin(owner, struct, prop, start, scene):
    """Index 2 (Z) of `struct.prop` keyed from `start` on the first frame to a full turn more one frame after the last (the
    loop has no repeated frame); `owner` is the ID that holds the keys."""
    for frame, value in ((scene.frame_start, start), (scene.frame_end + 1, start + 2 * math.pi)):
        getattr(struct, prop)[2] = value
        struct.keyframe_insert(prop, index=2, frame=frame)
    make_linear(owner, struct.path_from_id(prop))


def remove_turntable(scene):
    """Remove the turntable: its pivot and camera go, the scene camera and the sky's rotation are as before. False without one."""
    pivot = turntable_pivot(scene)
    if pivot is None:
        return False
    if pivot[TURNTABLE] == 'HDRI':
        nodes = hdri_nodes(scene.world)
        if nodes is not None:
            tree, socket = scene.world.node_tree, nodes["mapping"].inputs["Rotation"]
            path = socket.path_from_id("default_value")
            ad = tree.animation_data
            if ad is not None and ad.action is not None:
                from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
                bag = animdata_get_channelbag_for_assigned_slot(ad)
                for fc in [fc for fc in bag.fcurves if fc.data_path == path] if bag is not None else ():
                    bag.fcurves.remove(fc)
            socket.default_value[2] = pivot.get("m3d_sky_rotation", 0.0)
    before = bpy.data.objects.get(pivot.get("m3d_camera_before", ""))
    for ob in [*pivot.children, pivot]:
        data = ob.data
        bpy.data.objects.remove(ob)
        if data is not None and not data.users:
            bpy.data.cameras.remove(data)
    if scene.camera is None and before is not None:
        scene.camera = before
    return True


class M3D_OT_turntable(Operator):
    """Create Turntable: a camera that goes once around the selection over the frame range (the selection's centre is the
    pivot); render it or playblast it. Again: a new one in its place"""
    bl_idname = "m3d.turntable"
    bl_label = "Create Turntable"
    bl_options = {'REGISTER', 'UNDO'}

    turn: EnumProperty(name="Turn", items=(
        ('CAMERA', "Camera Around", "The camera goes around the model (the lights stay)"),
        ('HDRI', "Sky Around", "The camera stays, the HDRI sky turns: the reflections and the lighting move over the model")))

    def execute(self, context):
        scene = context.scene
        before = scene.camera
        if turntable_pivot(scene) is not None:
            before = bpy.data.objects.get(turntable_pivot(scene).get("m3d_camera_before", ""))
            remove_turntable(scene)
        obs = [o for o in context.selected_objects if o.type in MATERIAL_TYPES] or \
              [o for o in context.visible_objects if o.type in MATERIAL_TYPES]
        if not obs:
            self.report({'WARNING'}, "Nothing to turn around: select a model")
            return {'CANCELLED'}
        centre, radius = bounds(obs)
        pivot = bpy.data.objects.new("Turntable", None)
        pivot.empty_display_type, pivot.empty_display_size = 'CIRCLE', radius
        pivot.location = centre
        pivot[TURNTABLE] = self.turn
        pivot["m3d_camera_before"] = before.name if before is not None else ""
        data = bpy.data.cameras.new("Turntable Camera")
        cam = bpy.data.objects.new("Turntable Camera", data)
        for ob in (pivot, cam):
            scene.collection.objects.link(ob)
        cam.parent = pivot
        # The distance that fits the bounding sphere in the narrower side of the picture.
        r = scene.render
        aspect = (r.resolution_x * r.pixel_aspect_x) / max(r.resolution_y * r.pixel_aspect_y, 1)
        narrow = 2 * math.atan(math.tan(data.angle / 2) * min(aspect, 1 / aspect))
        distance = radius / math.sin(narrow / 2) * 1.05
        offset = Vector((0.0, -math.cos(ELEVATION), math.sin(ELEVATION))) * distance
        cam.location = offset
        cam.rotation_euler = (-offset).to_track_quat('-Z', 'Y').to_euler()
        data.clip_start, data.clip_end = min(data.clip_start, distance / 100), max(data.clip_end, distance + radius * 4)
        scene.camera = cam
        if self.turn == 'HDRI':
            if hdri_nodes(scene.world) is None:
                bpy.ops.m3d.hdri_setup()
            nodes = hdri_nodes(scene.world)
            if nodes is None:
                self.report({'WARNING'}, "No HDRI sky to turn: the camera goes around instead")
                pivot[TURNTABLE] = 'CAMERA'
            else:
                socket = nodes["mapping"].inputs["Rotation"]
                pivot["m3d_sky_rotation"] = socket.default_value[2]
                spin(scene.world.node_tree, socket, "default_value", socket.default_value[2], scene)
        if pivot[TURNTABLE] == 'CAMERA':
            spin(pivot, pivot, "rotation_euler", 0.0, scene)
        self.report({'INFO'}, "Turntable: once around over frames %d-%d (Render Animation or Playblast)" % (
            scene.frame_start, scene.frame_end))
        return {'FINISHED'}


class M3D_OT_turntable_remove(Operator):
    """Remove Turntable: its camera and pivot go, the scene camera (and the sky) are as before"""
    bl_idname = "m3d.turntable_remove"
    bl_label = "Remove Turntable"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return turntable_pivot(context.scene) is not None

    def execute(self, context):
        remove_turntable(context.scene)
        return {'FINISHED'}


def draw_turntable(layout, context):
    """Create / Remove Turntable, Playblast, Render Animation (Sculpt's Display tab, F7's Render tab)."""
    pivot = turntable_pivot(context.scene)
    row = layout.row(align=True)
    row.operator_menu_enum("m3d.turntable", "turn", text="Create Turntable" if pivot is None else "New Turntable",
                           icon='FILE_REFRESH')
    if pivot is None:
        reason(layout, "A camera goes once around the selection over the frame range")
        return
    row.operator("m3d.turntable_remove", text="", icon='X')
    reason(layout, "%s, frames %d-%d" % ("The sky turns" if pivot[TURNTABLE] == 'HDRI' else "The camera goes around",
                                         context.scene.frame_start, context.scene.frame_end))
    row = layout.row(align=True)
    row.operator("m3d.playblast", text="Playblast", icon='RENDER_ANIMATION')
    row.operator("m3d.render", text="Render Animation", icon='RENDER_ANIMATION').animation = True


class M3D_OT_render_view(Operator):
    """Show the last render in the Render View (Alt+F12)"""
    bl_idname = "m3d.render_view"
    bl_label = "Render View"

    def execute(self, context):
        if current_kind(context) == 'RENDER':
            render_view_back(context.screen)
        if current_kind(context) == 'RENDER' and render_view_area(context.screen) is not None:
            if not show_render_result(context):
                self.report({'INFO'}, "Nothing rendered yet: Render (Shift+F12)")
            return {'FINISHED'}
        return bpy.ops.render.view_show('INVOKE_DEFAULT')


_ipr_before = {}   # viewport (pointer) -> the shading it showed before IPR


class M3D_OT_render_ipr(Operator):
    """IPR: the viewport renders the scene as you work (Rendered shading); click again for the shading it had before"""
    bl_idname = "m3d.render_ipr"
    bl_label = "IPR"

    def execute(self, context):
        space = viewport(context)
        if space is None:
            self.report({'WARNING'}, "No 3D Viewport in this workspace")
            return {'CANCELLED'}
        key = space.as_pointer()
        if space.shading.type == 'RENDERED':
            space.shading.type = _ipr_before.pop(key, 'MATERIAL')
        else:
            _ipr_before[key] = space.shading.type
            space.shading.type = 'RENDERED'
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Lights and the light table

LIGHT_TYPES = (('POINT', "Point", 'LIGHT_POINT'), ('SPOT', "Spot", 'LIGHT_SPOT'), ('AREA', "Area", 'LIGHT_AREA'),
               ('SUN', "Sun", 'LIGHT_SUN'))
LIGHT_ICONS = {kind: icon for kind, _label, icon in LIGHT_TYPES}
TABLE_ROWS = 40   # Lights drawn in the table


def scene_lights(scene):
    """Every light object of the scene, hidden ones and ones in excluded collections too."""
    return sorted((o for o in scene.objects if o.type == 'LIGHT'), key=lambda o: o.name.lower())


def light_state(layer, ob):
    """'OK', 'HIDDEN' (hidden or disabled in the viewport, or its collection is hidden) or 'EXCLUDED' (its collection is
    excluded from the view layer)."""
    if layer.objects.get(ob.name) is None:
        return 'EXCLUDED'
    return 'OK' if ob.visible_get(view_layer=layer) else 'HIDDEN'


class M3D_OT_render_light_add(Operator):
    """Add a light above the 3D cursor (the sun is tilted)"""
    bl_idname = "m3d.render_light_add"
    bl_label = "Add Light"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=[(k, label, "") for k, label, _icon in LIGHT_TYPES])

    @classmethod
    def description(cls, _context, props):
        return "Add a %s light above the 3D cursor" % props.kind.lower()

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        tilt = (math.radians(50), 0.0, math.radians(30)) if self.kind == 'SUN' else (0.0, 0.0, 0.0)
        bpy.ops.object.light_add(type=self.kind, location=context.scene.cursor.location + Vector((0, 0, 4)), rotation=tilt)
        return {'FINISHED'}


class M3D_OT_render_light(Operator):
    """Light table buttons: show or hide a light in the viewport, select it, make its light data its own"""
    bl_idname = "m3d.render_light"
    bl_label = "Light"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty()
    action: EnumProperty(items=(('VISIBLE', "Show / Hide", ""), ('SELECT', "Select", ""), ('SINGLE', "Make Single User", "")))

    @classmethod
    def description(cls, _context, props):
        return {'VISIBLE': "Show or hide this light in the viewport",
                'SELECT': "Select this light",
                'SINGLE': "This light's settings are shared with other lights: editing one changes them all. Click to "
                          "give this light its own copy"}[props.action]

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        layer = context.view_layer
        if ob is None or ob.type != 'LIGHT':
            return {'CANCELLED'}
        if self.action == 'SINGLE':
            ob.data = ob.data.copy()
            return {'FINISHED'}
        if light_state(layer, ob) == 'EXCLUDED':
            self.report({'WARNING'}, "%s is in a collection that is excluded from the view layer" % ob.name)
            return {'CANCELLED'}
        if self.action == 'VISIBLE':
            if ob.visible_get(view_layer=layer):
                ob.hide_set(True, view_layer=layer)
                return {'FINISHED'}
            ob.hide_viewport = False
            ob.hide_set(False, view_layer=layer)
            if not ob.visible_get(view_layer=layer):
                self.report({'WARNING'}, "%s is shown, but its collection is hidden" % ob.name)
            return {'FINISHED'}
        for other in context.selected_objects:
            other.select_set(False)
        if not ob.visible_get(view_layer=layer):
            self.report({'WARNING'}, "%s is hidden in the viewport: click its eye first" % ob.name)
            return {'CANCELLED'}
        ob.select_set(True)
        layer.objects.active = ob
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Material helpers

MATERIAL_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME', 'CURVES', 'POINTCLOUD'}


def material_object(context):
    ob = context.active_object
    return ob if ob is not None and ob.type in MATERIAL_TYPES else None


def principled(mat):
    """The Principled shader that feeds the material's output (else any Principled node), or None."""
    tree = mat.node_tree if mat is not None else None
    if tree is None:   # (a material has a node tree unless it is linked data or a legacy file's)
        return None
    out = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    if out is not None and out.inputs["Surface"].is_linked:
        node = out.inputs["Surface"].links[0].from_node
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def normal_strength_node(bsdf):
    """The Normal Map / Bump node plugged into the shader's Normal, or None."""
    sock = bsdf.inputs["Normal"]
    node = sock.links[0].from_node if sock.is_linked else None
    return node if node is not None and node.type in {'NORMAL_MAP', 'BUMP'} else None


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

def engine(context):
    return context.scene.render.engine


def _gate(page, ok, draw_fix):
    """The panel a page shows instead of its own when there is nothing to work on."""
    def draw(self, context):
        draw_fix(self.layout, context)
    return type("PROPERTIES_PT_m3d_rn_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Rendering", "bl_options": {'HIDE_HEADER'}, "page": "render_" + page,
        "page_poll": classmethod(lambda cls, context: not ok(context)), "draw": draw})


def _material_fix(layout, context):
    """No object that can have a material is active: pick one of the scene's (a camera or a light has none), else add one."""
    ob = context.active_object
    meshes = [o for o in context.view_layer.objects if o.type in MATERIAL_TYPES and o.visible_get()]
    if not meshes:
        empty_state(layout, context, "Nothing in the scene can have a material yet",
                    ("Add Sphere", "m3d.add_primitive", 'MESH_UVSPHERE', {"kind": 'SPHERE'}))
        return
    text = "Select an object to edit its material" if ob is None else "%s has no material: select an object" % ob.type.title()
    draw_object_picks(empty_state(layout, context, text), meshes)


PAGE_GATES = (_gate("materials", lambda c: material_object(c) is not None, _material_fix),)


def _size_text(scene):
    r = scene.render
    return "%d x %d px" % (r.resolution_x * r.resolution_percentage // 100, r.resolution_y * r.resolution_percentage // 100)


# --- Camera

class _Camera(_PagePanel):
    page = "render_camera"


class _SceneCamera(_Camera):
    @classmethod
    def page_poll(cls, context):
        cam = context.scene.camera
        return cam is not None and cam.type == 'CAMERA'


# The camera fixes (the Animation workspace's no-camera card uses NEW_CAMERA too)
NEW_CAMERA = ("New Camera from View", "m3d.render_camera_from_view", 'ADD', {"mode": 'NEW'})
SCENE_CAMERA = ("Selected Camera as Scene Camera", "view3d.object_as_camera", 'OUTLINER_OB_CAMERA', {})


class PROPERTIES_PT_m3d_rn_camera(_Camera, Panel):
    bl_label = "Camera"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        ob = context.active_object
        picked = ob if ob is not None and ob.type == 'CAMERA' and ob != scene.camera else None
        if scene.camera is None:   # (the selected camera, else a new one)
            empty_state(layout, context, "No scene camera: the render is empty",
                        SCENE_CAMERA if picked is not None else NEW_CAMERA)
        split_props(layout)
        layout.prop(scene, "camera")
        if scene.camera is None:
            return
        col = layout.column(align=True)
        _button(col, context, *NEW_CAMERA)
        o = col.operator("m3d.render_camera_from_view", text="Match Camera to View", icon='CAMERA_DATA')
        o.mode = 'MATCH'
        _button(col, context, "Look Through Camera", "view3d.view_camera", 'VIEW_CAMERA', {})
        if picked is not None:
            _button(col, context, *SCENE_CAMERA)


class PROPERTIES_PT_m3d_rn_lens(_SceneCamera, Panel):
    bl_label = "Lens"

    def draw(self, context):
        layout = self.layout
        cam = context.scene.camera.data
        split_props(layout)
        layout.prop(cam, "type")
        layout.prop(cam, "ortho_scale" if cam.type == 'ORTHO' else "lens", text="Scale" if cam.type == 'ORTHO' else "Focal Length")
        col = layout.column(align=True)
        col.prop(cam, "clip_start", text="Clip Start")
        col.prop(cam, "clip_end", text="End")


class PROPERTIES_PT_m3d_rn_dof(_SceneCamera, Panel):
    bl_label = "Depth of Field"

    def draw_header(self, context):
        self.layout.prop(context.scene.camera.data.dof, "use_dof", text="")

    def draw(self, context):
        layout = self.layout
        dof = context.scene.camera.data.dof
        split_props(layout)
        layout.active = dof.use_dof
        layout.prop(dof, "focus_object", text="Focus Object")
        if dof.focus_object is None:   # (a focus object sets the distance)
            layout.prop(dof, "focus_distance", text="Distance")
        layout.prop(dof, "aperture_fstop", text="F-Stop")
        layout.prop(dof, "aperture_blades", text="Blades")


class PROPERTIES_PT_m3d_rn_resolution(_Camera, Panel):
    bl_label = "Resolution"

    def draw(self, context):
        layout = self.layout
        r = context.scene.render
        split_props(layout)
        col = layout.column(align=True)
        col.prop(r, "resolution_x", text="Width")
        col.prop(r, "resolution_y", text="Height")
        layout.prop(r, "resolution_percentage", text="Scale", slider=True)
        layout.label(text="Renders at " + _size_text(context.scene))


class PROPERTIES_PT_m3d_rn_guides(_SceneCamera, Panel):
    bl_label = "Safe Areas and Guides"

    def draw(self, context):
        layout = self.layout
        cam = context.scene.camera.data
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        flow.prop(cam, "show_safe_areas", text="Safe Areas", toggle=True)
        flow.prop(cam, "show_safe_center", text="Center Cut", toggle=True)
        flow.prop(cam, "show_composition_thirds", text="Thirds", toggle=True)
        flow.prop(cam, "show_composition_center", text="Center", toggle=True)
        flow.prop(cam, "show_composition_golden", text="Golden Ratio", toggle=True)
        flow.prop(cam, "show_passepartout", text="Passepartout", toggle=True)
        if cam.show_passepartout:
            split_props(layout)
            layout.prop(cam, "passepartout_alpha", text="Darkness", slider=True)


class PROPERTIES_PT_m3d_rn_border(_Camera, Panel):
    bl_label = "Render Border"

    def draw(self, context):
        layout = self.layout
        r = context.scene.render
        split_props(layout)
        layout.prop(r, "use_border", text="Render Only the Border")
        if r.use_border:
            layout.prop(r, "use_crop_to_border", text="Crop to Border")
        row = layout.row(align=True)
        _button(row, context, "Set", "view3d.render_border", 'SELECT_SET', {})
        _button(row, context, "Clear", "view3d.clear_render_border", 'X', {})
        reason(layout, "Set: look through the camera, then drag a rectangle")


# --- Lighting

class _Lighting(_PagePanel):
    page = "render_lighting"


class PROPERTIES_PT_m3d_rn_add_light(_Lighting, Panel):
    bl_label = "Add Light"

    def draw(self, context):
        grid(self.layout, context, (
            *((label, "m3d.render_light_add", icon, {"kind": kind}) for kind, label, icon in LIGHT_TYPES),
            ("HDRI Sky", "m3d.hdri_setup", 'WORLD', {}),
        ), columns=3)


def _cell(row, units):
    sub = row.row(align=True)
    sub.ui_units_x = units
    return sub


# Widths (UI units) of the light table's columns; the name takes the rest.
CELLS = {"view": 1.3, "render": 1.3, "color": 2.2, "power": 3.4, "shadow": 2.4, "shared": 1.8, "select": 1.3}


class PROPERTIES_PT_m3d_rn_lights(_Lighting, Panel):
    bl_label = "Light Editor"

    def draw(self, context):
        layout = self.layout
        layer = context.view_layer
        lights = scene_lights(context.scene)
        if not lights:
            reason(layout, "No lights in the scene: add one above")
            return
        head = layout.row(align=True)
        _cell(head, CELLS["view"]).label(text="", icon='HIDE_OFF')
        _cell(head, CELLS["render"]).label(text="", icon='RESTRICT_RENDER_OFF')
        head.row(align=True).label(text="Name")   # (a row, like the name fields below: it takes the rest of the width)
        _cell(head, CELLS["color"]).label(text="Color")
        _cell(head, CELLS["power"]).label(text="Power")
        _cell(head, CELLS["shadow"]).label(text="Shadow")
        _cell(head, CELLS["shared"]).label(text="")
        _cell(head, CELLS["select"]).label(text="")
        col = layout.column(align=True)
        for ob in lights[:TABLE_ROWS]:
            light, state = ob.data, light_state(layer, ob)
            row = col.row(align=True)
            sub = _cell(row, CELLS["view"])
            sub.enabled = state != 'EXCLUDED'
            o = sub.operator("m3d.render_light", text="", icon='HIDE_ON' if state != 'OK' else 'HIDE_OFF', emboss=False)
            o.name, o.action = ob.name, 'VISIBLE'
            _cell(row, CELLS["render"]).prop(ob, "hide_render", text="", emboss=False,
                                             icon='RESTRICT_RENDER_ON' if ob.hide_render else 'RESTRICT_RENDER_OFF')
            sub = row.row(align=True)
            sub.active = state == 'OK'
            sub.prop(ob, "name", text="", icon=LIGHT_ICONS.get(light.type, 'LIGHT'))
            _cell(row, CELLS["color"]).prop(light, "color", text="")
            _cell(row, CELLS["power"]).prop(light, "energy", text="")
            _cell(row, CELLS["shadow"]).prop(light, "use_shadow", text="")
            sub = _cell(row, CELLS["shared"])
            if light.users > 1:
                o = sub.operator("m3d.render_light", text="x%d" % light.users, icon='LINKED')
                o.name, o.action = ob.name, 'SINGLE'
            else:
                sub.label(text="")
            sub = _cell(row, CELLS["select"])
            sub.enabled = state != 'EXCLUDED'
            o = sub.operator("m3d.render_light", text="", icon='RESTRICT_SELECT_OFF', depress=state != 'EXCLUDED' and
                             ob.select_get(view_layer=layer))
            o.name, o.action = ob.name, 'SELECT'
        if len(lights) > TABLE_ROWS:
            layout.label(text="%d more lights not shown" % (len(lights) - TABLE_ROWS))
        if any(light_state(layer, o) != 'OK' for o in lights):
            reason(layout, "Greyed: hidden, or in a collection that is hidden or excluded")
        if any(o.data.users > 1 for o in lights):
            reason(layout, "xN: N lights share these settings (click to give one its own)")


class PROPERTIES_PT_m3d_rn_hdri(_Lighting, Panel):
    bl_label = "HDRI Sky"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        s = scene.m3d_render
        found = bundled_hdris()
        flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for label, path in found:
            o = flow.operator("m3d.hdri_setup", text=label)
            o.filepath = path
        split_props(layout)
        layout.prop(s, "hdri_path", text="File")
        layout.operator("m3d.hdri_setup", text="Load File", icon='FILE_IMAGE').filepath = ""
        nodes = hdri_nodes(scene.world)
        if nodes is None:
            reason(layout, "Pick a sky, or load a file: the scene gets its own world")
            return
        env = nodes["env"].image
        layout.label(text="Sky: " + (env.name if env else "none"), icon='WORLD')
        layout.prop(s, "hdri_rotation")
        layout.prop(s, "hdri_strength")
        layout.operator("m3d.hdri_clear", icon='LOOP_BACK')
        if s.previous_world is not None:
            reason(layout, "Kept: world \"%s\"" % s.previous_world.name)


class PROPERTIES_PT_m3d_rn_exposure(_Lighting, Panel):
    bl_label = "Exposure"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        view = context.scene.view_settings
        layout.prop(view, "exposure")
        layout.prop(view, "gamma")


# --- Materials

class _Materials(_PagePanel):
    page = "render_materials"

    @classmethod
    def page_poll(cls, context):
        return material_object(context) is not None


class PROPERTIES_PT_m3d_rn_slots(_Materials, Panel):
    bl_label = "Material Slots"

    def draw(self, context):
        layout = self.layout
        ob = material_object(context)
        if not any(slot.material for slot in ob.material_slots):
            empty_state(layout, context, "%s has no material yet" % ob.name,
                        ("Assign New Material", "m3d.assign_material", 'MATERIAL', {}))
            return
        row = layout.row()
        row.template_list("MATERIAL_UL_matslots", "", ob, "material_slots", ob, "active_material_index",
                          rows=min(len(ob.material_slots), 6), show_handles=False)
        col = row.column(align=True)
        col.operator("object.material_slot_add", icon='ADD', text="")
        col.operator("object.material_slot_remove", icon='REMOVE', text="")
        layout.template_ID(ob, "active_material", new="material.new")


class PROPERTIES_PT_m3d_rn_surface(_Materials, Panel):
    bl_label = "Surface"

    @classmethod
    def page_poll(cls, context):   # (without a material the Material Slots card says what to do)
        ob = material_object(context)
        return ob is not None and any(slot.material for slot in ob.material_slots)

    def draw(self, context):
        layout = self.layout
        mat = material_object(context).active_material
        if mat is None:
            reason(layout, "No material in this slot: New (above) adds one")
            return
        bsdf = principled(mat)
        if bsdf is None:
            reason(layout, "No Principled shader in this material")
        else:
            split_props(layout)
            normal = normal_strength_node(bsdf)
            for label, name in (("Base Color", "Base Color"), ("Metallic", "Metallic"), ("Roughness", "Roughness"),
                                ("Emission Color", "Emission Color"), ("Emission Strength", "Emission Strength")):
                sock = bsdf.inputs[name]
                if sock.is_linked:
                    layout.label(text="%s: from %s" % (label, sock.links[0].from_node.name), icon='NODE')
                else:
                    layout.prop(sock, "default_value", text=label)
            if normal is not None:
                layout.prop(normal.inputs["Strength"], "default_value", text="Normal Strength")
            else:
                reason(layout, "Normal Strength needs a Normal Map or Bump node")
        # (the graph in the Render View's place; the stock Shading workspace stays in the workspace menu)
        layout.operator("m3d.render_graph", text="Edit Graph", icon='NODE_MATERIAL').show = 'GRAPH'


# --- Scene Materials: every material of the file as a preview grid (Maelstrom3D's own left out)

def scene_materials():
    return sorted((m for m in bpy.data.materials if not is_internal_material(m) and not m.is_grease_pencil),
                  key=lambda m: m.name.lower())


def picked_material(scene):
    mat = bpy.data.materials.get(scene.m3d_render.browser_material)
    return mat if mat is not None and not is_internal_material(mat) else None


def unused_materials():
    """Materials no object uses (a fake user alone doesn't count), not linked from another file."""
    return [m for m in scene_materials() if m.library is None and m.users - int(m.use_fake_user) == 0]


def material_users(context, mat):
    return [o for o in context.view_layer.objects if any(slot.material == mat for slot in o.material_slots)]


class M3D_OT_scene_material(Operator):
    """Scene Materials buttons"""
    bl_idname = "m3d.scene_material"
    bl_label = "Scene Material"
    bl_options = {'REGISTER', 'UNDO'}

    ACTIONS = (('PICK', "Pick", "Pick this material: the buttons below act on it"),
               ('SELECT', "Select Objects Using", "Select the objects that use this material"),
               ('DUPLICATE', "Duplicate", "A copy of this material to change on its own (kept when the file is saved, "
                                          "used or not)"),
               ('RENAME', "Rename", "Rename this material"),
               ('NEW', "New", "A new material (kept when the file is saved, used or not)"),
               ('DELETE_UNUSED', "Delete Unused", "Delete the materials no object uses"))
    action: EnumProperty(items=ACTIONS)
    name: StringProperty(options={'SKIP_SAVE'})
    new_name: StringProperty(name="Name", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return {key: text for key, _label, text in cls.ACTIONS}[props.action]

    def invoke(self, context, event):
        if self.action == 'RENAME':
            self.new_name = self.name
            return context.window_manager.invoke_props_dialog(self, title="Rename Material", confirm_text="Rename")
        if self.action == 'DELETE_UNUSED':
            found = unused_materials()
            if not found:
                self.report({'INFO'}, "Every material is used")
                return {'CANCELLED'}
            return context.window_manager.invoke_confirm(
                self, event, title="Delete Unused Materials", confirm_text="Delete", icon='QUESTION',
                message="Delete %d materials no object uses: %s%s?" % (
                    len(found), ", ".join(m.name for m in found[:4]), "..." if len(found) > 4 else ""))
        return self.execute(context)

    def execute(self, context):
        s = context.scene.m3d_render
        mat = bpy.data.materials.get(self.name)
        if self.action == 'NEW':
            mat = bpy.data.materials.new("standardSurface1")
            mat.use_fake_user = True
        elif self.action == 'DELETE_UNUSED':
            found = unused_materials()
            for m in found:
                bpy.data.materials.remove(m)
            self.report({'INFO'}, "Deleted %d unused materials" % len(found))
            return {'FINISHED'}
        elif mat is None:
            return {'CANCELLED'}
        elif self.action == 'DUPLICATE':
            mat = mat.copy()
            mat.use_fake_user = True
        elif self.action == 'RENAME':
            if mat.library is not None or not self.new_name.strip():
                return {'CANCELLED'}
            mat.name = self.new_name.strip()
        elif self.action == 'SELECT':
            if context.mode != 'OBJECT':
                self.report({'WARNING'}, "Select Objects Using works in Object Mode")
                return {'CANCELLED'}
            found = [o for o in material_users(context, mat) if o.visible_get()]
            for ob in context.selected_objects:
                ob.select_set(False)
            for ob in found:
                ob.select_set(True)
            if found:
                context.view_layer.objects.active = found[0]
            self.report({'INFO'}, "%d objects use %s" % (len(found), mat.name) if found else
                        "No visible object uses %s" % mat.name)
        s.browser_material = mat.name
        return {'FINISHED'}


class M3D_OT_scene_materials_show(Operator):
    """Scene Materials: every material of the file as a preview grid (Rendering workspace, Materials tab)"""
    bl_idname = "m3d.scene_materials_show"
    bl_label = "Scene Materials"

    def execute(self, context):
        from m3d_workspace import find_workspace
        if current_kind(context) != 'RENDER' and context.window is not None:
            bpy.ops.m3d.workspace(kind='RENDER')
        ws = find_workspace('RENDER')
        if ws is None:
            return {'CANCELLED'}
        ws.m3d_page_right = "render_materials"
        for screen in ws.screens:
            docks = [a for a in screen.areas if a.type == 'PROPERTIES']
            if docks:
                max(docks, key=lambda a: a.height).spaces.active.context = 'MODELING_TOOLKIT'
        return {'FINISHED'}


GRID_MAX = 60   # materials drawn in the grid


def _scene_op(layout, action, name="", **kw):
    o = layout.operator("m3d.scene_material", **kw)
    o.action, o.name = action, name
    return o


class PROPERTIES_PT_m3d_rn_scene_materials(_PagePanel, Panel):
    page = "render_materials"
    bl_label = "Scene Materials"

    def draw(self, context):
        layout = self.layout
        mats = scene_materials()
        picked = picked_material(context.scene)
        row = layout.row(align=True)
        _scene_op(row, 'NEW', text="New", icon='ADD')
        unused = len(unused_materials())
        sub = row.row(align=True)
        sub.enabled = unused > 0
        _scene_op(sub, 'DELETE_UNUSED', text="Delete Unused (%d)" % unused if unused else "Delete Unused", icon='TRASH')
        if not mats:
            reason(layout, "No materials yet: New makes one, Assign New Material gives the selection one")
            return
        region = getattr(context, "region", None)
        scale = context.preferences.system.ui_scale or 1.0
        columns = max(2, int((getattr(region, "width", 0) or 300) / (96 * scale)))
        flow = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=False)
        for mat in mats[:GRID_MAX]:
            col = flow.column(align=True)
            col.template_icon(icon_value=layout.icon(mat), scale=3.6)
            _scene_op(col, 'PICK', mat.name, text=mat.name, depress=mat == picked)
        if len(mats) > GRID_MAX:
            layout.label(text="%d more materials not shown" % (len(mats) - GRID_MAX))
        if picked is None:
            reason(layout, "Click a material to pick it")
            return
        box = layout.box()
        users = len(material_users(context, picked))
        box.label(text="%s: %s" % (picked.name, "%d object%s" % (users, "" if users == 1 else "s") if users else "not used"),
                  icon='MATERIAL')
        col = box.column(align=True)
        o = col.operator("m3d.assign_existing_material", text="Assign to Selection", icon='CHECKMARK')
        o.material = picked.name
        _scene_op(col, 'SELECT', picked.name, text="Select Objects Using", icon='RESTRICT_SELECT_OFF')
        row = col.row(align=True)
        _scene_op(row, 'DUPLICATE', picked.name, text="Duplicate", icon='DUPLICATE')
        sub = row.row(align=True)
        sub.enabled = picked.library is None
        _scene_op(sub, 'RENAME', picked.name, text="Rename")


# --- Render

class _Render(_PagePanel):
    page = "render_render"


class _CyclesPanel(_Render):
    @classmethod
    def page_poll(cls, context):
        return engine(context) == 'CYCLES'


class _EeveePanel(_Render):
    @classmethod
    def page_poll(cls, context):
        return engine(context) == 'BLENDER_EEVEE'


class PROPERTIES_PT_m3d_rn_quality(_Render, Panel):
    bl_label = "Engine and Quality"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        row = layout.row(align=True)
        for key, label in ENGINES:
            row.prop_enum(scene.render, "engine", key, text=label)
        now = current_quality(scene)
        row = layout.row(align=True)
        row.scale_y = 1.3
        for key, label in QUALITY:
            row.operator("m3d.render_preset", text=label, depress=now == key).preset = key
        row.menu("M3D_MT_render_presets", text=now if now not in PRESET_VALUES and now != 'CUSTOM' else "",
                 icon='PRESET')
        reason(layout, quality_note(scene))
        split_props(layout)
        layout.prop(scene.render, "resolution_percentage", text="Scale", slider=True)
        layout.label(text="Renders at " + _size_text(scene))
        if scene.render.engine not in dict(ENGINES):
            reason(layout, "This engine has no quality settings here: see All Settings")


def draw_device(layout, context):
    """Cycles' device, and what is known of the GPU (m3d_bakeq.find_gpu: a test bake, asked a moment after the first draw):
    "GPU found ... [Use GPU]" while it renders on the CPU."""
    import m3d_bakeq as Q
    cy = context.scene.cycles
    layout.prop(cy, "device")
    found = Q.known_gpu()
    if found is None:
        Q.check_gpu_soon()
        return
    if cy.device == 'CPU' and found[0]:
        reason(layout, "GPU found: %s (%s)" % (", ".join(found[1]), found[0]))
        o = layout.operator("wm.context_set_enum", text="Use GPU", icon='CHECKMARK')
        o.data_path, o.value = "scene.cycles.device", 'GPU'
    elif cy.device == 'GPU' and not found[0]:
        reason(layout, "Renders on the CPU: " + found[2])


class PROPERTIES_PT_m3d_rn_cycles(_CyclesPanel, Panel):
    bl_label = "Sampling"

    def draw(self, context):
        layout = self.layout
        cy = context.scene.cycles
        split_props(layout)
        draw_device(layout, context)
        layout.prop(cy, "samples", text="Render Samples")
        layout.prop(cy, "preview_samples", text="Viewport Samples")
        layout.prop(cy, "use_adaptive_sampling", text="Noise Threshold")
        if cy.use_adaptive_sampling:
            layout.prop(cy, "adaptive_threshold", text="Threshold")
        layout.prop(cy, "time_limit", text="Time Limit")


class PROPERTIES_PT_m3d_rn_denoise(_CyclesPanel, Panel):
    bl_label = "Denoising"

    def draw_header(self, context):
        self.layout.prop(context.scene.cycles, "use_denoising", text="")

    def draw(self, context):
        layout = self.layout
        cy = context.scene.cycles
        split_props(layout)
        layout.active = cy.use_denoising
        layout.prop(cy, "denoiser")
        layout.prop(cy, "use_preview_denoising", text="In the Viewport")


class PROPERTIES_PT_m3d_rn_eevee(_EeveePanel, Panel):
    bl_label = "Sampling"

    def draw(self, context):
        layout = self.layout
        ev = context.scene.eevee
        split_props(layout)
        layout.prop(ev, "taa_render_samples", text="Render Samples")
        layout.prop(ev, "taa_samples", text="Viewport Samples")


class PROPERTIES_PT_m3d_rn_raytracing(_EeveePanel, Panel):
    bl_label = "Ray Tracing"

    def draw_header(self, context):
        self.layout.prop(context.scene.eevee, "use_raytracing", text="")

    def draw(self, context):
        layout = self.layout
        ev = context.scene.eevee
        split_props(layout)
        layout.active = ev.use_raytracing
        layout.prop(ev, "ray_tracing_method", text="Method")
        layout.prop(ev.ray_tracing_options, "resolution_scale", text="Resolution")
        layout.prop(ev.ray_tracing_options, "use_denoise", text="Denoise")


class PROPERTIES_PT_m3d_rn_shadows(_EeveePanel, Panel):
    bl_label = "Shadows"

    def draw_header(self, context):
        self.layout.prop(context.scene.eevee, "use_shadows", text="")

    def draw(self, context):
        layout = self.layout
        ev = context.scene.eevee
        split_props(layout)
        layout.active = ev.use_shadows
        layout.prop(ev, "shadow_ray_count", text="Rays")
        layout.prop(ev, "shadow_step_count", text="Steps")


# --- Output

class _Output(_PagePanel):
    page = "render_output"


OUTPUT_TYPES = (('IMAGE', "Image Sequence"), ('MULTI_LAYER_IMAGE', "Multilayer EXR"), ('VIDEO', "Video"))


class PROPERTIES_PT_m3d_rn_output(_Output, Panel):
    bl_label = "Output"

    def draw(self, context):
        layout = self.layout
        r = context.scene.render
        im = r.image_settings
        split_props(layout)
        layout.prop(r, "filepath", text="Path")
        if r.filepath.startswith("//") and not bpy.data.filepath:
            reason(layout, "Save the file first: // is the folder of the saved file")
        row = layout.row(align=True)   # (the whole width: the three types fit on a narrow dock)
        row.use_property_split = False
        for key, label in OUTPUT_TYPES:
            row.prop_enum(im, "media_type", key, text=label)
        if im.media_type == 'VIDEO':
            ff = r.ffmpeg
            layout.prop(ff, "format", text="Container")
            layout.prop(ff, "codec", text="Codec")
            if ff.codec in {'H264', 'H265', 'MPEG4', 'WEBM', 'AV1'}:   # (the codecs with a quality setting)
                layout.prop(ff, "constant_rate_factor", text="Quality")
        elif im.media_type == 'MULTI_LAYER_IMAGE':
            layout.prop(im, "color_depth", text="Depth")
            layout.prop(im, "exr_codec", text="Compression")
            reason(layout, "One file per frame with every pass and render layer")
        else:
            layout.prop(im, "file_format", text="Format")
            layout.prop(im, "color_mode", text="Color")
            layout.prop(im, "color_depth", text="Depth")
        layout.prop(r, "use_overwrite", text="Overwrite Existing Frames")
        s = context.scene.m3d_render
        layout.prop(s, "keep_renders")
        layout.prop(s, "save_stills")
        draw_pass_warning(layout, context)


class PROPERTIES_PT_m3d_rn_frames(_Output, Panel):
    bl_label = "Frame Range"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        split_props(layout)
        col = layout.column(align=True)
        col.prop(scene, "frame_start", text="Start")
        col.prop(scene, "frame_end", text="End")
        layout.prop(scene, "frame_step", text="Step")
        layout.prop(scene.render, "fps")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("m3d.render", text="Render", icon='RENDER_STILL')
        row.operator("m3d.render", text="Render Animation", icon='RENDER_ANIMATION').animation = True
        row = layout.row(align=True)
        row.operator("m3d.render_background", text="Render in Background", icon='TIME')
        row.operator("m3d.render_job_export", text="", icon='EXPORT')
        folder = output_folder(scene)
        if (bpy.data.filepath or not scene.render.filepath.startswith("//")) and os.path.isdir(folder):
            layout.operator("wm.path_open", text="Open Render Folder", icon='FILE_FOLDER').filepath = folder


class PROPERTIES_PT_m3d_rn_color(_Output, Panel):
    bl_label = "Color Management"

    def draw(self, context):
        layout = self.layout
        view = context.scene.view_settings
        split_props(layout)
        layout.prop(view, "view_transform", text="View Transform")
        layout.prop(view, "look")
        layout.prop(view, "exposure")
        layout.prop(view, "gamma")


# --- Passes & Layers

class _Passes(_PagePanel):
    page = "render_passes"


class M3D_OT_render_layer_from_selection(Operator):
    """New Render Layer from Selection: a render layer with only the selected objects (and the scene's lights): they go into a
    collection of their own (they stay in theirs too), the other collections are left out of the new layer"""
    bl_idname = "m3d.render_layer_from_selection"
    bl_label = "New Render Layer from Selection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        scene, picked = context.scene, list(context.selected_objects)
        active = context.active_object if context.active_object in picked else picked[0]
        name = active.name + " Layer"
        coll = bpy.data.collections.new(name)
        scene.collection.children.link(coll)
        for ob in {*picked, *(o for o in scene.objects if o.type == 'LIGHT')}:
            coll.objects.link(ob)
        layer = scene.view_layers.new(coll.name)
        for lc in layer.layer_collection.children:
            lc.exclude = lc.collection != coll
        if context.window is not None:
            context.window.view_layer = layer
        loose = [o for o in scene.collection.objects if o not in picked and o.type != 'LIGHT']
        if loose:
            self.report({'WARNING'}, "Render layer \"%s\": %d objects in no collection render in it too (%s)" % (
                layer.name, len(loose), ", ".join(o.name for o in loose[:3])))
        else:
            self.report({'INFO'}, "Render layer \"%s\": %d objects and the scene's lights" % (layer.name, len(picked)))
        return {'FINISHED'}


class PROPERTIES_PT_m3d_rn_view_layers(_Passes, Panel):
    bl_label = "Render Layers"

    def draw(self, context):
        layout = self.layout
        layout.template_search(context.window, "view_layer", context.scene, "view_layers", new="scene.view_layer_add",
                               unlink="scene.view_layer_remove")
        layout.prop(context.view_layer, "use", text="Render This Layer")
        if M3D_OT_render_layer_from_selection.poll(context):
            layout.operator("m3d.render_layer_from_selection", icon='RENDERLAYERS')
        else:
            reason(layout, "Select objects (Object Mode) for a New Render Layer from Selection")


PASSES = [("Combined", "use_pass_combined"), ("Depth", "use_pass_z"), ("Mist", "use_pass_mist"),
          ("Normal", "use_pass_normal"), ("Position", "use_pass_position"), ("Vector", "use_pass_vector"),
          ("Diffuse Direct", "use_pass_diffuse_direct"), ("Diffuse Color", "use_pass_diffuse_color"),
          ("Glossy Direct", "use_pass_glossy_direct"), ("Glossy Color", "use_pass_glossy_color"),
          ("Emission", "use_pass_emit"), ("Environment", "use_pass_environment"),
          ("Ambient Occlusion", "use_pass_ambient_occlusion"), ("Shadow", "use_pass_shadow")]
CYCLES_PASSES = [("Diffuse Indirect", "use_pass_diffuse_indirect"), ("Glossy Indirect", "use_pass_glossy_indirect"),
                 ("Transmission", "use_pass_transmission_direct")]
CRYPTOMATTE = (("Object", "use_pass_cryptomatte_object"), ("Material", "use_pass_cryptomatte_material"),
               ("Asset", "use_pass_cryptomatte_asset"))


def extra_passes(scene):
    """Does a render layer that renders make passes besides Combined (passes, Cryptomatte, AOVs, light groups)?"""
    names = [name for _label, name in (*PASSES[1:], *CRYPTOMATTE)]
    cycles = scene.render.engine == 'CYCLES'
    return any(any(getattr(vl, name) for name in names) or len(vl.aovs) or (cycles and (
        len(vl.lightgroups) or any(getattr(vl, name) for _label, name in CYCLES_PASSES) or vl.cycles.use_pass_shadow_catcher))
        for vl in scene.view_layers if vl.use)


def draw_pass_warning(layout, context):
    """Passes are written only into a Multilayer EXR: say so, with the switch, while the output is another type."""
    scene = context.scene
    if scene.render.image_settings.media_type != 'MULTI_LAYER_IMAGE' and extra_passes(scene):
        box = layout.box()
        box.label(text="Passes are saved only in a Multilayer EXR", icon='ERROR')
        o = box.operator("wm.context_set_enum", text="Switch Output to Multilayer EXR", icon='RENDERLAYERS')
        o.data_path, o.value = "scene.render.image_settings.media_type", 'MULTI_LAYER_IMAGE'


class PROPERTIES_PT_m3d_rn_passes(_Passes, Panel):
    bl_label = "Passes"

    def draw(self, context):
        layout = self.layout
        vl = context.view_layer
        cycles = engine(context) == 'CYCLES'
        draw_pass_warning(layout, context)
        rows = list(PASSES)
        if cycles:
            rows[8:8] = CYCLES_PASSES
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for label, name in rows:
            flow.prop(vl, name, text=label, toggle=True)
        if cycles:
            flow.prop(vl.cycles, "use_pass_shadow_catcher", text="Shadow Catcher", toggle=True)
        layout.label(text="Cryptomatte")
        flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for label, name in CRYPTOMATTE:
            flow.prop(vl, name, text=label, toggle=True)


class PROPERTIES_PT_m3d_rn_aov(_Passes, Panel):
    bl_label = "AOVs"

    def draw(self, context):
        layout = self.layout
        vl = context.view_layer
        draw_list(layout, "VIEWLAYER_UL_aov", vl, "aovs", vl, "active_aov_index", "scene.view_layer_add_aov",
                  "scene.view_layer_remove_aov", "+ adds an AOV; an AOV Output node in a material fills it", "aovs")
        if vl.active_aov and not vl.active_aov.is_valid:
            layout.label(text="Conflicts with another pass of the same name", icon='ERROR')


class PROPERTIES_PT_m3d_rn_lightgroups(_Passes, Panel):
    bl_label = "Light Groups"

    @classmethod
    def page_poll(cls, context):
        return engine(context) == 'CYCLES'

    def draw(self, context):
        layout = self.layout
        vl = context.view_layer
        col = draw_list(layout, "UI_UL_list", vl, "lightgroups", vl, "active_lightgroup_index",
                        "scene.view_layer_add_lightgroup", "scene.view_layer_remove_lightgroup",
                        "+ adds a light group", "lightgroups")
        col.menu("VIEWLAYER_MT_lightgroup_sync", icon='DOWNARROW_HLT', text="")
        reason(layout, "A light joins a group in its Object properties (Shading, Light Group)")


def layer_collections(lc, depth=0):
    for child in lc.children:
        yield child, depth
        yield from layer_collections(child, depth + 1)


class PROPERTIES_PT_m3d_rn_holdout(_Passes, Panel):
    bl_label = "Collections in This Render Layer"

    def draw(self, context):
        layout = self.layout
        found = list(layer_collections(context.view_layer.layer_collection))
        if not found:
            reason(layout, "No collections: every object is in every render layer")
            return
        head = layout.row(align=True)
        head.label(text="Collection")
        for text in ("In Layer", "Holdout", "Indirect"):
            _cell(head, 3.2).label(text=text)
        col = layout.column(align=True)
        for lc, depth in found[:TABLE_ROWS]:
            row = col.row(align=True)
            sub = row.row(align=True)
            sub.active = not lc.exclude
            sub.label(text="    " * depth + lc.name, icon='OUTLINER_COLLECTION')
            _cell(row, 3.2).prop(lc, "exclude", text="", invert_checkbox=True)
            if lc.exclude:   # (left out: holdout and indirect don't apply)
                _cell(row, 6.4).label(text="")
                continue
            _cell(row, 3.2).prop(lc, "holdout", text="", icon='HOLDOUT_ON' if lc.holdout else 'HOLDOUT_OFF')
            _cell(row, 3.2).prop(lc, "indirect_only", text="",
                                 icon='INDIRECT_ONLY_ON' if lc.indirect_only else 'INDIRECT_ONLY_OFF')
        if len(found) > TABLE_ROWS:
            layout.label(text="%d more collections not shown" % (len(found) - TABLE_ROWS))


class _ActiveObject(_Passes):
    @classmethod
    def page_poll(cls, context):
        return context.active_object is not None


class PROPERTIES_PT_m3d_rn_light_linking(_ActiveObject, Panel):
    bl_label = "Light Linking"

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        ll = ob.light_linking
        layout.label(text="Active: " + ob.name)
        for prop_name, title, new, link in (
                ("receiver_collection", "Light: the objects this light shines on", "object.light_linking_receiver_collection_new",
                 "object.light_linking_receivers_link"),
                ("blocker_collection", "Shadows: the objects that block this light", "object.light_linking_blocker_collection_new",
                 "object.light_linking_blockers_link")):
            layout.label(text=title)
            layout.template_ID(ll, prop_name, new=new)
            if getattr(ll, prop_name):
                row = layout.row()
                row.template_light_linking_collection(row, ll, prop_name)
                sub = row.column(align=True)
                sub.operator(link, icon='ADD', text="").link_state = 'INCLUDE'
                sub.operator("object.light_linking_unlink_from_collection", icon='REMOVE', text="")


class PROPERTIES_PT_m3d_rn_object_flags(_ActiveObject, Panel):
    bl_label = "Shadow Catcher and Holdout"

    @classmethod
    def page_poll(cls, context):   # (surfaces only: a light or a camera catches no shadow)
        return material_object(context) is not None

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        split_props(layout)
        layout.prop(ob, "is_shadow_catcher", text="Shadow Catcher")
        layout.prop(ob, "is_holdout", text="Holdout")
        if engine(context) != 'CYCLES':
            reason(layout, "Shadow catcher renders in Cycles")


# --- Advanced

class _Advanced(_PagePanel):
    page = "render_advanced"


class PROPERTIES_PT_m3d_rn_paths(_Advanced, Panel):
    bl_label = "Light Paths"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        split_props(layout)
        if engine(context) == 'CYCLES':
            cy = scene.cycles
            col = layout.column(align=True)
            col.prop(cy, "max_bounces", text="Total")
            for name, label in (("diffuse_bounces", "Diffuse"), ("glossy_bounces", "Glossy"),
                                ("transmission_bounces", "Transmission"), ("volume_bounces", "Volume"),
                                ("transparent_max_bounces", "Transparent")):
                col.prop(cy, name, text=label)
            col = layout.column(align=True)
            col.prop(cy, "sample_clamp_direct", text="Clamp Direct")
            col.prop(cy, "sample_clamp_indirect", text="Indirect")
            col = layout.column(align=True)
            col.prop(cy, "caustics_reflective", text="Reflective Caustics")
            col.prop(cy, "caustics_refractive", text="Refractive Caustics")
        elif engine(context) == 'BLENDER_EEVEE':
            ev = scene.eevee
            layout.prop(ev, "use_fast_gi", text="Fast GI")
            if ev.use_fast_gi:
                layout.prop(ev, "fast_gi_method", text="Method")
                layout.prop(ev, "fast_gi_ray_count", text="Rays")
                layout.prop(ev, "fast_gi_step_count", text="Steps")
                layout.prop(ev, "fast_gi_distance", text="Distance")
            layout.prop(ev, "gi_diffuse_bounces", text="Diffuse Bounces")
        else:
            reason(layout, "This engine has no light paths")


class PROPERTIES_PT_m3d_rn_film(_Advanced, Panel):
    bl_label = "Film"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        split_props(layout)
        layout.prop(scene.render, "film_transparent", text="Transparent Background")
        layout.prop(scene.render, "filter_size", text="Pixel Filter")
        if engine(context) == 'CYCLES':
            layout.prop(scene.cycles, "film_exposure", text="Exposure")
        layout.prop(scene.render, "use_motion_blur", text="Motion Blur")
        if scene.render.use_motion_blur:
            layout.prop(scene.render, "motion_blur_shutter", text="Shutter")


class PROPERTIES_PT_m3d_rn_performance(_Advanced, Panel):
    bl_label = "Performance"

    def draw(self, context):
        layout = self.layout
        r = context.scene.render
        split_props(layout)
        layout.prop(r, "threads_mode", text="Threads")
        if r.threads_mode == 'FIXED':
            layout.prop(r, "threads")
        layout.prop(r, "use_persistent_data", text="Keep Scene in Memory")
        if engine(context) == 'CYCLES':
            cy = context.scene.cycles
            layout.prop(cy, "use_auto_tile", text="Tiles")
            if cy.use_auto_tile:
                layout.prop(cy, "tile_size")


class PROPERTIES_PT_m3d_rn_simplify(_Advanced, Panel):
    bl_label = "Simplify"

    def draw_header(self, context):
        self.layout.prop(context.scene.render, "use_simplify", text="")

    def draw(self, context):
        layout = self.layout
        r = context.scene.render
        split_props(layout)
        layout.active = r.use_simplify
        layout.prop(r, "simplify_subdivision_render", text="Max Subdivision")
        layout.prop(r, "simplify_child_particles_render", text="Child Particles")
        if engine(context) == 'CYCLES':
            layout.prop(context.scene.cycles, "texture_limit_render", text="Texture Limit")


# -----------------------------------------------------------------------------
# Status Line

def draw_status_line(layout, context):
    """Rendering Status Line: file, engine, scene camera, quality preset, Render, Render Animation, IPR, Render View."""
    from m3d_ui import draw_file_buttons, draw_workspace_picker
    scene = context.scene
    draw_file_buttons(layout)
    row = layout.row(align=True)
    for key, label in ENGINES:
        row.prop_enum(scene.render, "engine", key, text=label)
    layout.separator()
    row = layout.row(align=True)
    row.scale_x = 1.4
    row.prop(scene, "camera", text="")
    now = current_quality(scene)
    layout.separator()
    row = layout.row(align=True)
    for key, label in QUALITY:
        row.operator("m3d.render_preset", text=label, depress=now == key).preset = key
    if now not in PRESET_VALUES:
        layout.label(text="Custom" if now == 'CUSTOM' else now)   # (settings of no built-in preset: the state, beside the presets)
    layout.separator()
    row = layout.row(align=True)
    row.operator("m3d.render", text="Render", icon='RENDER_STILL')
    row.operator("m3d.render", text="Render Animation", icon='RENDER_ANIMATION').animation = True
    space = viewport(context)
    layout.separator()
    row = layout.row(align=True)
    row.operator("m3d.render_ipr", text="IPR", icon='SHADING_RENDERED', depress=space is not None and space.shading.type == 'RENDERED')
    row.operator("m3d.render_view", text="Render View", icon='IMAGE', depress=not graph_shown(context.screen))
    row.operator("m3d.render_graph", text="Shader Graph", icon='NODE_MATERIAL', depress=graph_shown(context.screen))
    draw_workspace_picker(layout, context)


# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

SHELF_LIGHTS = [
    *(("m3d.render_light_add", icon, {"kind": kind}, label) for kind, label, icon in LIGHT_TYPES),
    ("m3d.hdri_setup", 'WORLD', {}, "HDRI Sky"),
    None,
    ("m3d.hdri_clear", 'LOOP_BACK', {}, "Previous World"),
]
SHELF_RENDER = [
    ("m3d.render", 'RENDER_STILL', {}, "Render"),
    ("m3d.render", 'RENDER_ANIMATION', {"animation": True}, "Animation"),
    ("m3d.render_view", 'IMAGE', {}, "Render View"),
    ("m3d.render_background", 'TIME', {}, "Background"),
    None,
    ("m3d.render_camera_from_view", 'CAMERA_DATA', {"mode": 'NEW'}, "Camera from View"),
    ("m3d.turntable", 'FILE_REFRESH', {"turn": 'CAMERA'}, "Turntable"),
    ("view3d.view_camera", 'VIEW_CAMERA', {}, "Look Through"),
    None,
    *(("m3d.render_preset", 'NONE', {"preset": key}, label) for key, label in QUALITY),
]


# -----------------------------------------------------------------------------

classes = (
    M3D_RenderSettings,
    M3D_OT_render_preset,
    M3D_OT_hdri_setup,
    M3D_OT_hdri_clear,
    M3D_OT_render_camera_from_view,
    M3D_OT_render,
    M3D_OT_render_view,
    M3D_OT_render_ipr,
    M3D_OT_render_light_add,
    M3D_OT_render_light,
    M3D_OT_render_preset_save,
    M3D_OT_render_preset_delete,
    M3D_MT_render_presets,
    M3D_OT_view_lighting,
    M3D_OT_render_layer_from_selection,
    M3D_OT_render_compare,
    M3D_MT_render_slots,
    M3D_OT_render_graph,
    M3D_OT_scene_material,
    M3D_OT_scene_materials_show,
    M3D_OT_missing_textures,
    M3D_OT_save_for_sharing,
    M3D_OT_render_background,
    M3D_OT_render_background_stop,
    M3D_OT_render_job_export,
    M3D_OT_turntable,
    M3D_OT_turntable_remove,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_rn_camera,
    PROPERTIES_PT_m3d_rn_lens,
    PROPERTIES_PT_m3d_rn_dof,
    PROPERTIES_PT_m3d_rn_resolution,
    PROPERTIES_PT_m3d_rn_guides,
    PROPERTIES_PT_m3d_rn_border,
    PROPERTIES_PT_m3d_rn_add_light,
    PROPERTIES_PT_m3d_rn_lights,
    PROPERTIES_PT_m3d_rn_hdri,
    PROPERTIES_PT_m3d_rn_exposure,
    PROPERTIES_PT_m3d_rn_slots,
    PROPERTIES_PT_m3d_rn_surface,
    PROPERTIES_PT_m3d_rn_scene_materials,
    PROPERTIES_PT_m3d_rn_quality,
    PROPERTIES_PT_m3d_rn_cycles,
    PROPERTIES_PT_m3d_rn_denoise,
    PROPERTIES_PT_m3d_rn_eevee,
    PROPERTIES_PT_m3d_rn_raytracing,
    PROPERTIES_PT_m3d_rn_shadows,
    PROPERTIES_PT_m3d_rn_output,
    PROPERTIES_PT_m3d_rn_frames,
    PROPERTIES_PT_m3d_rn_color,
    PROPERTIES_PT_m3d_rn_view_layers,
    PROPERTIES_PT_m3d_rn_passes,
    PROPERTIES_PT_m3d_rn_aov,
    PROPERTIES_PT_m3d_rn_lightgroups,
    PROPERTIES_PT_m3d_rn_holdout,
    PROPERTIES_PT_m3d_rn_light_linking,
    PROPERTIES_PT_m3d_rn_object_flags,
    PROPERTIES_PT_m3d_rn_paths,
    PROPERTIES_PT_m3d_rn_film,
    PROPERTIES_PT_m3d_rn_performance,
    PROPERTIES_PT_m3d_rn_simplify,
)


DEFAULT_OUTPUT = "//render/"


@bpy.app.handlers.persistent
def render_path_default(*_args):
    """A new file (the startup file, File > New) renders into a render folder next to the file once it is saved, not into
    Blender's /tmp/ (a scene of a saved file keeps its path)."""
    if bpy.data.filepath:
        return
    for scene in bpy.data.scenes:
        if scene.render.filepath.replace("\\", "/") == "/tmp/":
            scene.render.filepath = DEFAULT_OUTPUT


@bpy.app.handlers.persistent
def quality_default(*_args):
    """A new file starts at Medium quality, not "Custom" (Cycles' own defaults match no preset)."""
    for scene in bpy.data.scenes:
        apply_quality(scene, 'MEDIUM')


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_render = PointerProperty(type=M3D_RenderSettings)
    bpy.app.handlers.load_factory_startup_post.append(quality_default)
    bpy.app.handlers.load_post.append(render_path_default)
    for handlers, fn in HANDLERS:
        handlers.append(fn)
    if not bpy.app.background:
        _draw_handlers.append(bpy.types.SpaceImageEditor.draw_handler_add(draw_empty_hint, (), 'WINDOW', 'POST_PIXEL'))


HANDLERS = ((bpy.app.handlers.load_post, _file_loaded), (bpy.app.handlers.load_post, _check_files),
            (bpy.app.handlers.save_post, _file_saved), (bpy.app.handlers.render_init, _render_started),
            (bpy.app.handlers.render_cancel, _render_cancelled))


def unregister():
    while _draw_handlers:
        bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handlers.pop(), 'WINDOW')
    for handlers, fn in HANDLERS:
        if fn in handlers:
            handlers.remove(fn)
    if render_path_default in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(render_path_default)
    if quality_default in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(quality_default)
    del bpy.types.Scene.m3d_render
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
