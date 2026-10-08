# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Rendering workspace (F7) for Maelstrom3D: the dock pages (Camera, Lighting, Materials, Render, Output, Passes & Layers,
Advanced), the Rendering Status Line, the Lights and Render shelves and the operators behind them (quality presets, the
light table, HDRI setup, camera from view, IPR, Render and Render View).

The layout is built by tools/m3d/build_startup.py (phase6_rendering), the tabs are DOCK_TABS['RENDER'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py.
"""

import math
import os
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector

from m3d_mode import _button
from m3d_sculpt import grid, reason, split_props, viewport
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


def quality_matches(scene, preset):
    """Do the active engine's settings (and the size) equal the preset's?"""
    values = {**PRESET_VALUES[preset]['ALL'], **PRESET_VALUES[preset].get(scene.render.engine, {})}
    return all(_same(getattr(*_owner(scene, path)), value) for path, value in values.items())


def apply_quality(scene, preset):
    for values in PRESET_VALUES[preset].values():
        for path, value in values.items():
            owner, name = _owner(scene, path)
            setattr(owner, name, value)
    scene.m3d_render.preset = preset


def current_quality(scene):
    """The preset the settings match, else 'CUSTOM' (a value was edited since): the preset applied last wins a tie."""
    stored = scene.m3d_render.preset
    if stored in PRESET_VALUES and quality_matches(scene, stored):
        return stored
    return next((p for p in PRESET_VALUES if quality_matches(scene, p)), 'CUSTOM')


class M3D_OT_render_preset(Operator):
    """Quality preset for the scene: samples, denoising, bounces / ray tracing and size for Cycles and EEVEE"""
    bl_idname = "m3d.render_preset"
    bl_label = "Quality Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(items=[(k, v, "") for k, v in QUALITY])

    @classmethod
    def description(cls, _context, props):
        return "%s quality: %s (Custom shows once you edit one of these values)" % (
            props.preset.title(), PRESET_NOTES[props.preset])

    def execute(self, context):
        apply_quality(context.scene, self.preset)
        return {'FINISHED'}


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
    hdri_path: StringProperty(name="HDRI File", subtype='FILE_PATH', description="An .exr or .hdr image for the sky")
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
        return {'FINISHED'}


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
    Result as soon as there is one."""
    win = wm.windows[0] if wm.windows else None
    if win is not None and workspace_kind(win.workspace) == 'RENDER':
        area = render_view_area(win.screen)
        if area is not None and area.spaces.active.image is None:
            show_render_result(SimpleNamespace(workspace=win.workspace, screen=win.screen))


class M3D_OT_render(Operator):
    """Render the scene: a still, or the whole animation. The result shows in the Render View"""
    bl_idname = "m3d.render"
    bl_label = "Render"

    animation: BoolProperty(default=False, options={'SKIP_SAVE'}, description="Render the whole frame range")

    @classmethod
    def description(cls, _context, props):
        return "Render the animation (Ctrl+Shift+F12)" if props.animation else "Render the current frame (Shift+F12)"

    def invoke(self, context, _event):
        # The Rendering workspace has its Render View: while it shows the Render Result, no render window opens (the
        # preference "Render In" is put back as soon as the render has started).
        view = context.preferences.view
        display = view.render_display_type
        if show_render_result(context):
            view.render_display_type = 'NONE'
        try:
            bpy.ops.render.render('INVOKE_DEFAULT', animation=self.animation, use_viewport=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        finally:
            view.render_display_type = display
        return {'FINISHED'}

    def execute(self, context):
        try:
            return bpy.ops.render.render(animation=self.animation, use_viewport=True)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}


class M3D_OT_render_view(Operator):
    """Show the last render in the Render View (Alt+F12)"""
    bl_idname = "m3d.render_view"
    bl_label = "Render View"

    def execute(self, context):
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
    col = layout.column(align=True)
    col.label(text="Select an object to edit its material")
    _button(col, context, "Add Sphere", "m3d.add_primitive", 'MESH_UVSPHERE', {"kind": 'SPHERE'})


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


class PROPERTIES_PT_m3d_rn_camera(_Camera, Panel):
    bl_label = "Camera"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        split_props(layout)
        layout.prop(scene, "camera")
        ob = context.active_object
        col = layout.column(align=True)
        o = col.operator("m3d.render_camera_from_view", text="New Camera from View", icon='ADD')
        o.mode = 'NEW'
        o = col.operator("m3d.render_camera_from_view", text="Match Camera to View", icon='CAMERA_DATA')
        o.mode = 'MATCH'
        _button(col, context, "Look Through Camera", "view3d.view_camera", 'VIEW_CAMERA', {})
        sub = col.row(align=True)
        sub.enabled = ob is not None and ob.type == 'CAMERA'
        _button(sub, context, "Selected Camera as Scene Camera", "view3d.object_as_camera", 'OUTLINER_OB_CAMERA', {})
        if scene.camera is None:
            reason(layout, "No scene camera: New Camera from View adds one")


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
        sub = layout.row()
        sub.active = dof.focus_object is None
        sub.prop(dof, "focus_distance", text="Distance")
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
        sub = layout.row()
        sub.active = r.use_border
        sub.prop(r, "use_crop_to_border", text="Crop to Border")
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
        row = layout.row()
        row.template_list("MATERIAL_UL_matslots", "", ob, "material_slots", ob, "active_material_index", rows=3)
        col = row.column(align=True)
        col.operator("object.material_slot_add", icon='ADD', text="")
        col.operator("object.material_slot_remove", icon='REMOVE', text="")
        layout.template_ID(ob, "active_material", new="material.new")


class PROPERTIES_PT_m3d_rn_surface(_Materials, Panel):
    bl_label = "Surface"

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
        if "Shading" in bpy.data.workspaces:
            o = layout.operator("wm.context_set_id", text="Edit Nodes in the Shading Workspace", icon='NODE_MATERIAL')
            o.data_path, o.value = "window.workspace", "Shading"


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
        layout.label(text=PRESET_NOTES[now] if now in PRESET_NOTES else "Custom: a value was edited since the preset")
        split_props(layout)
        layout.prop(scene.render, "resolution_percentage", text="Scale", slider=True)
        layout.label(text="Renders at " + _size_text(scene))
        if scene.render.engine not in dict(ENGINES):
            reason(layout, "This engine has no quality settings here: see All Settings")


class PROPERTIES_PT_m3d_rn_cycles(_CyclesPanel, Panel):
    bl_label = "Sampling"

    def draw(self, context):
        layout = self.layout
        cy = context.scene.cycles
        split_props(layout)
        layout.prop(cy, "device")
        layout.prop(cy, "samples", text="Render Samples")
        layout.prop(cy, "preview_samples", text="Viewport Samples")
        layout.prop(cy, "use_adaptive_sampling", text="Noise Threshold")
        sub = layout.row()
        sub.active = cy.use_adaptive_sampling
        sub.prop(cy, "adaptive_threshold", text="Threshold")
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


class PROPERTIES_PT_m3d_rn_output(_Output, Panel):
    bl_label = "Output"

    def draw(self, context):
        layout = self.layout
        r = context.scene.render
        im = r.image_settings
        split_props(layout)
        layout.prop(r, "filepath", text="Path")
        layout.prop(im, "file_format", text="Format")
        layout.prop(im, "color_mode", text="Color")
        layout.prop(im, "color_depth", text="Depth")
        layout.prop(r, "use_overwrite")


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


class PROPERTIES_PT_m3d_rn_view_layers(_Passes, Panel):
    bl_label = "View Layers"

    def draw(self, context):
        layout = self.layout
        layout.template_search(context.window, "view_layer", context.scene, "view_layers", new="scene.view_layer_add",
                               unlink="scene.view_layer_remove")
        layout.prop(context.view_layer, "use", text="Render This Layer")


class PROPERTIES_PT_m3d_rn_passes(_Passes, Panel):
    bl_label = "Passes"

    def draw(self, context):
        layout = self.layout
        vl = context.view_layer
        cycles = engine(context) == 'CYCLES'
        rows = [("Combined", "use_pass_combined"), ("Depth", "use_pass_z"), ("Mist", "use_pass_mist"),
                ("Normal", "use_pass_normal"), ("Position", "use_pass_position"), ("Vector", "use_pass_vector"),
                ("Diffuse Direct", "use_pass_diffuse_direct"), ("Diffuse Color", "use_pass_diffuse_color"),
                ("Glossy Direct", "use_pass_glossy_direct"), ("Glossy Color", "use_pass_glossy_color"),
                ("Emission", "use_pass_emit"), ("Environment", "use_pass_environment"),
                ("Ambient Occlusion", "use_pass_ambient_occlusion"), ("Shadow", "use_pass_shadow")]
        if cycles:
            rows[8:8] = [("Diffuse Indirect", "use_pass_diffuse_indirect"), ("Glossy Indirect", "use_pass_glossy_indirect"),
                         ("Transmission", "use_pass_transmission_direct")]
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for label, name in rows:
            flow.prop(vl, name, text=label, toggle=True)
        if cycles:
            flow.prop(vl.cycles, "use_pass_shadow_catcher", text="Shadow Catcher", toggle=True)
        layout.label(text="Cryptomatte")
        flow = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for label, name in (("Object", "use_pass_cryptomatte_object"), ("Material", "use_pass_cryptomatte_material"),
                            ("Asset", "use_pass_cryptomatte_asset")):
            flow.prop(vl, name, text=label, toggle=True)


class PROPERTIES_PT_m3d_rn_aov(_Passes, Panel):
    bl_label = "AOVs"

    def draw(self, context):
        layout = self.layout
        vl = context.view_layer
        row = layout.row()
        row.template_list("VIEWLAYER_UL_aov", "aovs", vl, "aovs", vl, "active_aov_index", rows=3)
        col = row.column(align=True)
        col.operator("scene.view_layer_add_aov", icon='ADD', text="")
        col.operator("scene.view_layer_remove_aov", icon='REMOVE', text="")
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
        row = layout.row()
        row.template_list("UI_UL_list", "lightgroups", vl, "lightgroups", vl, "active_lightgroup_index", rows=3)
        col = row.column(align=True)
        col.operator("scene.view_layer_add_lightgroup", icon='ADD', text="")
        col.operator("scene.view_layer_remove_lightgroup", icon='REMOVE', text="")
        col.menu("VIEWLAYER_MT_lightgroup_sync", icon='DOWNARROW_HLT', text="")
        reason(layout, "A light joins a group in its Object properties (Shading, Light Group)")


def layer_collections(lc, depth=0):
    for child in lc.children:
        yield child, depth
        yield from layer_collections(child, depth + 1)


class PROPERTIES_PT_m3d_rn_holdout(_Passes, Panel):
    bl_label = "Holdout and Indirect Only"

    def draw(self, context):
        layout = self.layout
        found = list(layer_collections(context.view_layer.layer_collection))
        if not found:
            reason(layout, "No collections: objects in the scene collection cannot be held out")
            return
        head = layout.row(align=True)
        head.label(text="Collection")
        _cell(head, 3.2).label(text="Holdout")
        _cell(head, 3.2).label(text="Indirect")
        col = layout.column(align=True)
        for lc, depth in found[:TABLE_ROWS]:
            row = col.row(align=True)
            row.label(text="    " * depth + lc.name, icon='OUTLINER_COLLECTION')
            _cell(row, 3.2).prop(lc, "holdout", text="", icon='HOLDOUT_ON' if lc.holdout else 'HOLDOUT_OFF')
            _cell(row, 3.2).prop(lc, "indirect_only", text="",
                                 icon='INDIRECT_ONLY_ON' if lc.indirect_only else 'INDIRECT_ONLY_OFF')


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
            sub = layout.column()
            sub.active = ev.use_fast_gi
            sub.prop(ev, "fast_gi_method", text="Method")
            sub.prop(ev, "fast_gi_ray_count", text="Rays")
            sub.prop(ev, "fast_gi_step_count", text="Steps")
            sub.prop(ev, "fast_gi_distance", text="Distance")
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
        sub = layout.row()
        sub.active = scene.render.use_motion_blur
        sub.prop(scene.render, "motion_blur_shutter", text="Shutter")


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
            sub = layout.row()
            sub.active = cy.use_auto_tile
            sub.prop(cy, "tile_size")


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
    row = layout.row(align=True)
    row.scale_x = 1.4
    row.prop(scene, "camera", text="")
    now = current_quality(scene)
    row = layout.row(align=True)
    for key, label in QUALITY:
        row.operator("m3d.render_preset", text=label, depress=now == key).preset = key
    if now == 'CUSTOM':
        row.label(text="Custom")
    row = layout.row(align=True)
    row.operator("m3d.render", text="Render", icon='RENDER_STILL')
    row.operator("m3d.render", text="Render Animation", icon='RENDER_ANIMATION').animation = True
    space = viewport(context)
    row = layout.row(align=True)
    row.operator("m3d.render_ipr", text="IPR", icon='SHADING_RENDERED', depress=space is not None and space.shading.type == 'RENDERED')
    row.operator("m3d.render_view", text="Render View", icon='IMAGE')
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
    None,
    ("m3d.render_camera_from_view", 'CAMERA_DATA', {"mode": 'NEW'}, "Camera from View"),
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


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_render = PointerProperty(type=M3D_RenderSettings)


def unregister():
    del bpy.types.Scene.m3d_render
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
