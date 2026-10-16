# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Pipeline I/O for Maelstrom3D: Export to Engine (the low polys, their textures and the animation for a game engine in one
pass, repeatable in one click), File > Import... (one file picker for every format, with studio units), references (Create
Reference: a linked file whose skeletons can be posed at once; the Reference Editor) and projects (Set / New Project: the
folders scenes, renders, playblasts and exports start in, kept in m3d_user.json with the recent projects).
"""

import os
import re
from contextlib import ExitStack, contextmanager

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import Menu, Operator, OperatorFileListElement, Panel, PropertyGroup
from mathutils import Matrix, Vector

import m3d_pair
import m3d_user
from m3d_sculpt import draw_lines, reason, split_props
from m3d_workspace import _PagePanel


# -----------------------------------------------------------------------------
# Projects: a folder with scenes/, sourceimages/, images/ (renders), playblasts/, export/ and cache/

FOLDERS = ("scenes", "sourceimages", "images", "playblasts", "export", "cache")
RECENT = 8   # recent projects kept
DEFAULT_RENDER = ("/tmp/", "//render/")   # the render output of a new file (Blender's, Maelstrom3D's: m3d_render.DEFAULT_OUTPUT)
DEFAULT_TEXTURES = "//textures/"          # the Export Textures folder of a new file (m3d_texture)


def project():
    """The folder of the current project ("" without one, or when it is gone)."""
    path = m3d_user.data().get("project")
    return path if isinstance(path, str) and path and os.path.isdir(path) else ""


def project_folder(name):
    """The path of one of the project's FOLDERS ("" without a project)."""
    root = project()
    return os.path.join(root, name) if root else ""


def project_tip():
    """The project for a tooltip: " Project: Name (path)", or "" without one."""
    root = project()
    return " Project: %s (%s)" % (os.path.basename(os.path.normpath(root)), root) if root else ""


def recent_projects():
    found = m3d_user.data().get("recent_projects")
    return [p for p in found if isinstance(p, str)] if isinstance(found, list) else []


def set_project(path, create=False):
    """Make `path` the project ("" for none; `create`: make its folders first). The paths of a new file follow it."""
    path = os.path.normpath(bpy.path.abspath(path)) if path else ""
    if create:
        for name in FOLDERS:
            os.makedirs(os.path.join(path, name), exist_ok=True)
    root = m3d_user.data()
    root["project"] = path
    if path:
        root["recent_projects"] = ([path] + [p for p in recent_projects() if os.path.normcase(p) != os.path.normcase(path)])[:RECENT]
    m3d_user.save()
    project_defaults()


def folder_path(name):
    """A project folder as an output path (made when missing, ends with a separator)."""
    folder = project_folder(name)
    os.makedirs(folder, exist_ok=True)
    return folder + os.sep


@bpy.app.handlers.persistent
def project_defaults(*_args):
    """A file that was never saved renders into the project's images/ and exports its textures into export/ (a saved file keeps
    its paths; without a project Blender's and Maelstrom3D's defaults stay)."""
    if bpy.data.filepath or not project():
        return
    for scene in bpy.data.scenes:
        scene_defaults(scene)


def scene_defaults(scene):
    """The render output and the Export Textures folder of `scene` in the project, where they are still the defaults."""
    if scene.render.filepath.replace("\\", "/") in DEFAULT_RENDER:
        scene.render.filepath = folder_path("images")
    tex = getattr(scene, "m3d_tex", None)
    if tex is not None and tex.export_folder == DEFAULT_TEXTURES:
        tex.export_folder = folder_path("export")


class M3D_OT_project_set(Operator):
    """Set Project: the folder scenes are opened and saved in, and renders, playblasts and exports go to"""
    bl_idname = "m3d.project_set"
    bl_label = "Set Project"

    directory: StringProperty(subtype='DIR_PATH', options={'SKIP_SAVE'})
    create: BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        if props.create:
            return "New Project: make scenes, sourceimages, images, playblasts, export and cache folders in a folder and use it"
        if props.is_property_set("directory"):
            return ("Use this project: %s" % props.directory) if props.directory else "Work without a project"
        return cls.__doc__ + "." + project_tip()

    def invoke(self, context, _event):
        if self.is_property_set("directory"):   # (a recent project, or No Project)
            return self.execute(context)
        root = project()
        self.directory = (os.path.dirname(root) if self.create else root) + os.sep if root else ""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, _context):
        if self.directory and not os.path.isdir(self.directory) and not self.create:
            self.report({'ERROR'}, "The folder is not there: %s" % self.directory)
            return {'CANCELLED'}
        try:
            set_project(self.directory, create=self.create and bool(self.directory))
        except OSError as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        root = project()
        self.report({'INFO'}, "Project: %s" % root if root else "No project")
        return {'FINISHED'}


class M3D_MT_recent_projects(Menu):
    bl_idname = "M3D_MT_recent_projects"
    bl_label = "Recent Projects"

    def draw(self, _context):
        layout = self.layout
        current = os.path.normcase(project())
        for path in recent_projects():
            o = layout.operator("m3d.project_set", text=os.path.basename(os.path.normpath(path)) or path, translate=False,
                                icon='CHECKMARK' if os.path.normcase(path) == current else 'FILE_FOLDER')
            o.directory = path
        if not recent_projects():
            layout.label(text="No projects yet")
        layout.separator()
        layout.operator("m3d.project_set", text="No Project", icon='X').directory = ""


class M3D_OT_open_scene(Operator):
    """Open a scene file"""
    bl_idname = "m3d.open_scene"
    bl_label = "Open Scene"

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.blend", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, _props):
        return "Open a scene file (Ctrl+O): it starts in the project's scenes folder." + project_tip() if project() else \
            "Open a scene file (Ctrl+O)"

    def invoke(self, context, _event):
        if not project():
            bpy.ops.wm.open_mainfile('INVOKE_DEFAULT')
            return {'FINISHED'}
        self.filepath = folder_path("scenes")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path, win = self.filepath, context.window or context.window_manager.windows[0]

        def open_file():   # (after this operator: the file it runs in is replaced; unsaved changes are asked about first)
            with bpy.context.temp_override(window=win):
                bpy.ops.wm.open_mainfile('INVOKE_DEFAULT', filepath=path, display_file_selector=False)
        bpy.app.timers.register(open_file, first_interval=0.0)
        return {'FINISHED'}


class M3D_OT_save_scene(Operator):
    """Save the scene"""
    bl_idname = "m3d.save_scene"
    bl_label = "Save Scene"

    as_new: BoolProperty(options={'SKIP_SAVE'}, description="Save under another name (Save Scene As)")

    @classmethod
    def description(cls, _context, props):
        text = "Save the scene under another name (Ctrl+Shift+S)" if props.as_new else "Save the scene (Ctrl+S)"
        return text + (": a new scene is saved in the project's scenes folder." + project_tip() if project() else "")

    def invoke(self, _context, _event):
        images = {"show_save_modified_images_dialog": True}   # (as Blender's keys: painted images are offered too)
        if project() and not bpy.data.filepath:
            bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', filepath=os.path.join(folder_path("scenes"), "untitled.blend"), **images)
        elif self.as_new:
            bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', **images)
        else:
            bpy.ops.wm.save_mainfile('INVOKE_DEFAULT', **images)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# File > Import...: one picker for every format, the importer chosen by the extension

IMPORT_GLOB = "*.fbx;*.obj;*.gltf;*.glb;*.usd;*.usda;*.usdc;*.usdz;*.abc;*.blend"
UNITS = (
    ('FILE', "Metres (as in the file)", "OBJ and Alembic files are read as metres: 1 unit is 1 m"),
    ('STUDIO', "Studio (centimetres, Y up)", "OBJ and Alembic files from a studio that works in centimetres with Y up: 100 units are "
     "1 m (read at scale 1 they come in 100 times too big)"),
)


def append_all(context, path):
    """The objects of another scene file, appended into a new collection named after it. Returns the objects."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    coll = bpy.data.collections.new(bpy.path.display_name_from_filepath(path))
    context.scene.collection.children.link(coll)
    obs = [ob for ob in dst.objects if ob is not None]
    for ob in obs:
        coll.objects.link(ob)
    return obs


def import_file(context, path, units='FILE'):
    """Read `path` with the importer of its extension. OBJ and Alembic carry no units: Studio reads them as centimetres (FBX, glTF
    and USD say their units and axes themselves)."""
    ext = os.path.splitext(path)[1].lower()
    scale = 0.01 if units == 'STUDIO' else 1.0
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path, global_scale=scale, forward_axis='NEGATIVE_Z', up_axis='Y')
    elif ext in {".gltf", ".glb"}:
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext in {".usd", ".usda", ".usdc", ".usdz"}:
        bpy.ops.wm.usd_import(filepath=path)
    elif ext == ".abc":
        bpy.ops.wm.alembic_import(filepath=path, scale=scale, as_background_job=False)
    elif ext == ".blend":
        append_all(context, path)
    else:
        raise RuntimeError("not a file Import reads (FBX, OBJ, glTF, USD, Alembic, .blend)")


class M3D_OT_import_file(Operator):
    """Import a file: FBX, OBJ, glTF, USD, Alembic or the objects of a scene file (.blend), each with its own importer"""
    bl_idname = "m3d.import_file"
    bl_label = "Import"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    files: CollectionProperty(type=OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    filter_glob: StringProperty(default=IMPORT_GLOB, options={'HIDDEN', 'SKIP_SAVE'})
    units: EnumProperty(name="Units", items=UNITS, default='FILE',
                        description="How OBJ and Alembic files are read (they carry no units; FBX, glTF and USD do)")

    def invoke(self, context, _event):
        remembered = m3d_user.data().get("import_units")
        self.units = remembered if remembered in {k for k, _l, _d in UNITS} else 'FILE'
        if project():
            self.filepath = folder_path("scenes")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, _context):
        layout = self.layout
        layout.label(text="Units")
        layout.prop(self, "units", text="")
        col = layout.column(align=True)
        for line in ("OBJ and Alembic have no units:", "Studio reads them as cm.", "FBX, glTF and USD say theirs."):
            col.label(text=line)

    def execute(self, context):
        paths = [os.path.join(self.directory, f.name) for f in self.files if f.name] or [self.filepath]
        m3d_user.data()["import_units"] = self.units
        m3d_user.save()
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        done = 0
        for path in paths:
            try:
                import_file(context, path, self.units)
                done += 1
            except (RuntimeError, OSError, AttributeError) as err:
                self.report({'ERROR'}, "%s: %s" % (os.path.basename(path), str(err).strip()))
        if not done:
            return {'CANCELLED'}
        self.report({'INFO'}, "Imported %s" % (os.path.basename(paths[0]) if done == 1 else "%d files" % done))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Export to Engine: the low polys (never a high poly or a cage), their textures and the animation, for one engine

FBX_COMMON = dict(   # every FBX of Export to Engine
    use_selection=True, use_mesh_modifiers=True, mesh_smooth_type='FACE', add_leaf_bones=False, use_armature_deform_only=True,
    apply_unit_scale=True, global_scale=1.0, axis_forward='-Z', axis_up='Y', primary_bone_axis='Y', secondary_bone_axis='X',
    bake_anim_use_all_bones=True, bake_anim_force_startend_keying=True, bake_anim_step=1.0, bake_anim_simplify_factor=0.0,
    path_mode='AUTO')
ENGINES = {   # id -> (label, what it writes, Export Textures templates for it (the first is the default), FBX settings)
    'UNREAL': ("Unreal Engine", "FBX in centimetres (1 m = 100 units), smoothing groups; the skeleton named Armature (no extra "
               "root bone); textures T_Name_BC, _N, _ORM", ('UNREAL',), dict(apply_scale_options='FBX_SCALE_NONE')),
    'UNITY': ("Unity", "FBX with its scale applied (1 m = 1 unit, scale 1 in Unity), smoothing groups; textures Name_Albedo, "
              "_Normal, _MetallicSmoothness (or HDRP's)", ('UNITY', 'HDRP'), dict(apply_scale_options='FBX_SCALE_ALL')),
    'GLTF': ("glTF (other engines)", "One .glb for each file with its meshes, materials and textures (animation: pick Unreal or "
             "Unity)", ('GLTF',), None),
}
ROOT_MOTION = (
    ('NONE', "As Animated", "The hips move over the ground as they are keyed"),
    ('ROOT', "Root Motion", "The hips' motion over the ground goes to the root bone (the engine moves the character by it)"),
    ('IN_PLACE', "In Place", "The hips' motion over the ground is taken out: the character walks on the spot"),
)
_HIPS = re.compile(r"(^|[^a-z])(hips|pelvis)$", re.IGNORECASE)
_BONE_PATH = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)*)"\]')


class M3D_ExportSettings(PropertyGroup):
    """Export to Engine options (Scene.m3d_export, kept with the file): Repeat Last Export runs them again."""
    engine: EnumProperty(name="Engine", default='UNREAL', items=[(k, v[0], v[1]) for k, v in ENGINES.items()],
                         description="The engine the files are for: axes, units, smoothing and the texture template follow it")
    folder: StringProperty(name="Folder", subtype='DIR_PATH', default="", options={'PATH_SUPPORTS_BLEND_RELATIVE'},
                           description="Where the files go (empty: the project's export folder, else an export folder next to "
                                       "the saved scene)")
    meshes: BoolProperty(name="Meshes", default=True, description="Write the low polys (high polys and cages are never written)")
    textures: BoolProperty(name="Textures", default=True,
                           description="Write the texture sets of the meshes with Export Textures' settings and the engine's template")
    animation: BoolProperty(name="Animation", default=True, description="Write the animation of the skeletons of the meshes")
    selected_only: BoolProperty(name="Selected Only", default=False,
                                description="Only the selected meshes and skeletons (else every visible mesh, parked low polys too)")
    one_file: BoolProperty(name="One File", default=False,
                           description="All meshes in one file (else a file for each mesh, or each skeleton with its meshes)")
    prefix: StringProperty(name="Prefix", default="", description="Put before the mesh names and their files (SM_ for static "
                           "meshes, SK_ for skinned ones). A name is the group's (Crate_low: Crate)")
    to_origin: BoolProperty(name="Move to Origin", default=False,
                            description="Each file's meshes (or skeleton) are written at the world origin, wherever they are in the scene")
    triangulate: BoolProperty(name="Triangulate", default=True,
                              description="Write triangles: the engine shades the faces as the baked normal map expects")
    clips: EnumProperty(name="Clips", default='CURRENT', items=(
        ('CURRENT', "What Plays", "The animation as it plays (every layer) over the range, one clip"),
        ('ACTIONS', "Each Action", "Every action of the skeleton (its own and its layers'), each over its keys")),
        description="What the animation clips are")
    clip_files: BoolProperty(name="A File per Clip", default=False,
                             description="Each clip in a file of its own (else one file with a take for each clip)")
    anim_range: EnumProperty(name="Range", default='PLAYBACK', items=(
        ('PLAYBACK', "Playback Range", "The preview range when it is on, else the scene range"),
        ('SCENE', "Scene Range", ""), ('KEYS', "Keys", "From the first to the last key")),
        description="The frames What Plays is baked over (Each Action uses each action's keys)")
    root_motion: EnumProperty(name="Root Motion", default='NONE', items=ROOT_MOTION,
                              description="What happens to the hips' motion over the ground")
    last_files: StringProperty(description="Files of the last Export to Engine, separated by |")


def export_dir(context):
    """The folder of Export to Engine, made when it is not there."""
    s = context.scene.m3d_export
    folder = s.folder or (folder_path("export") if project() else "//export/")
    if folder.startswith("//") and not bpy.data.filepath:
        raise RuntimeError("Save the scene first, set a project, or pick a folder")
    folder = bpy.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    return folder


def cages(context):
    """Meshes that are a cage: a bake group's own cage, the cage preview's objects."""
    import m3d_bakegroups
    return {g.cage for g in context.scene.m3d_bake_groups if g.cage is not None} | set(m3d_bakegroups.cage_objects())


def mesh_name(ob, prefix=""):
    """The name of a low poly in the engine: its group's without the role suffix (Crate_low: Crate; a floater Panel_low_bolts:
    Panel_bolts), after the prefix."""
    base, _role, extra = m3d_pair.parse_name(ob.name)
    return bpy.path.clean_name(prefix + base + extra)


def rig_of_mesh(ob):
    import m3d_rig
    rig = m3d_rig.armature_of(ob)
    return rig if rig is not ob else None


def export_plan(context):
    """(files, rigs, high polys left out) of Export to Engine: files [(name, meshes, rigs)] (a file for each mesh, or for each
    skeleton with the meshes it deforms; one with One File), the skeletons whose animation is written."""
    s = context.scene.m3d_export
    layer = context.view_layer
    pool = [o for o in layer.objects if o.select_get()] if s.selected_only else \
        [o for o in layer.objects if o.visible_get() or o.m3d_pair.parked]
    picked_rigs = [o for o in pool if o.type == 'ARMATURE']
    meshes = [o for o in pool if o.type == 'MESH']
    if s.selected_only:   # (a selected skeleton brings its meshes)
        meshes += [o for o in layer.objects if o.type == 'MESH' and o not in meshes and rig_of_mesh(o) in picked_rigs]
    left_out = cages(context)
    highs = [o for o in meshes if o.m3d_pair.role == 'HIGH']
    meshes = sorted((o for o in meshes if o.m3d_pair.role != 'HIGH' and o not in left_out), key=lambda o: o.name)
    files = {}
    for ob in meshes:
        rig = rig_of_mesh(ob)
        key = "" if s.one_file else rig.name if rig is not None else mesh_name(ob)
        entry = files.setdefault(key, ([], []))
        entry[0].append(ob)
        if rig is not None and rig not in entry[1]:
            entry[1].append(rig)
    one = bpy.path.clean_name(bpy.path.display_name_from_filepath(bpy.data.filepath) or context.scene.name)
    named = [(bpy.path.clean_name(s.prefix + (key or one)), obs, rigs) for key, (obs, rigs) in files.items()]
    rigs = list(dict.fromkeys([r for _n, _o, rr in named for r in rr] + [r for r in picked_rigs if r.animation_data]))
    if not s.selected_only:
        rigs += [o for o in layer.objects if o.type == 'ARMATURE' and o.visible_get() and o.animation_data and o not in rigs]
    return named, rigs, highs


def texture_sets_of(context, meshes):
    """[(material, mesh)] of the Texture Set List whose meshes are written."""
    import m3d_texture as T
    meshes = set(meshes)
    return [(mat, ob) for mat, ob in T.texture_sets(context) if meshes.intersection(T.meshes_with(context, mat) or [ob])]


@contextmanager
def renamed(pairs):
    """The objects of [(object, name)] have those names inside (their mesh or skeleton too when nothing else uses it), and get
    their own back after. An object outside that has one of the names steps aside meanwhile."""
    done = []   # [(ID, old name)] in the order to undo
    try:
        for ob, name in pairs:
            other = bpy.data.objects.get(name)
            if other is not None and other is not ob and other.library is None:
                done.append((other, other.name))
                other.name = name + "_m3d_aside"
            if ob.name != name:
                done.append((ob, ob.name))
                ob.name = name
            if ob.data is not None and ob.data.users == 1 and ob.data.library is None and ob.data.name != name:
                done.append((ob.data, ob.data.name))
                ob.data.name = name
        yield
    finally:
        for id_, name in reversed(done):
            id_.name = name


@contextmanager
def placed(obs, to_origin):
    """The objects `obs` where the engine gets them: back from an Explode (m3d_bakegroups), and with `to_origin` moved so the first
    skeleton (else the first mesh) is at the world origin. They go back after."""
    top = [o for o in obs if o.parent not in obs]
    saved = [(o, o.matrix_world.copy()) for o in top]
    news = {o: mat.copy() for o, mat in saved}
    for o, new in news.items():
        if o.type == 'MESH':
            new.translation -= Vector(o.m3d_pair.explode_offset)
    anchor = next((o for o in top if o.type == 'ARMATURE'), top[0] if top else None)
    shift = -news[anchor].translation if to_origin and anchor is not None else None
    try:
        for o, new in news.items():
            if shift is not None:
                new.translation += shift
            o.matrix_world = new
        bpy.context.view_layer.update()
        yield
    finally:
        for o, mat in saved:
            o.matrix_world = mat
        bpy.context.view_layer.update()


@contextmanager
def only_selected(context, obs):
    """`obs` selected and nothing else (a hidden one, a parked low poly, shown meanwhile), the first active; put back after."""
    layer = context.view_layer
    before, active = [o for o in layer.objects if o.select_get()], layer.objects.active
    hidden = [(o, o.hide_get(), o.hide_viewport, o.hide_select) for o in obs]
    try:
        for o in before:
            o.select_set(False)
        for o in obs:
            o.hide_viewport = o.hide_select = False
            o.hide_set(False)
            o.select_set(True)
        layer.objects.active = obs[0]
        yield
    finally:
        for o in obs:
            o.select_set(False)
        for o, hide, viewport, select in hidden:
            o.hide_set(hide)
            o.hide_viewport, o.hide_select = viewport, select
        for o in before:
            o.select_set(True)
        layer.objects.active = active


def texture_template(context, engine):
    """The Export Textures template for the engine: the one chosen when it is made for it (HDRP for Unity), else the engine's."""
    preset = context.scene.m3d_tex.export_preset
    return preset if preset in ENGINES[engine][2] else ENGINES[engine][2][0]


@contextmanager
def engine_textures(context, engine, folder):
    """Export Textures' template and folder are the engine's meanwhile."""
    tex = context.scene.m3d_tex
    old = tex.export_preset, tex.export_folder
    try:
        tex.export_preset = texture_template(context, engine)
        tex.export_folder = folder
        yield
    finally:
        tex.export_preset, tex.export_folder = old


def fbx_settings(engine, rigs):
    """The FBX exporter's settings for the engine. Unity gets the axes applied to the objects when there is no skeleton (the
    exporter's Apply Transform is not made for skeletons)."""
    return {**FBX_COMMON, **ENGINES[engine][3], "bake_space_transform": engine == 'UNITY' and not rigs}


def engine_names(s, obs, rigs):
    """[(object, name in the engine)]: the meshes after the group with the prefix; for Unreal the skeleton is Armature."""
    return [*((o, mesh_name(o, s.prefix)) for o in obs), *((r, "Armature") for r in rigs[:1] if s.engine == 'UNREAL')]


def write_meshes(context, path, obs, rigs):
    """The meshes `obs` (with their skeletons `rigs`) as one file: modifiers applied with Smooth Preview off, names for the engine."""
    import m3d_texture as T
    s = context.scene.m3d_export
    with ExitStack() as stack:
        stack.enter_context(renamed(engine_names(s, obs, rigs)))
        stack.enter_context(placed([*obs, *rigs], s.to_origin))
        if s.engine == 'GLTF':
            return T.export_gltf(context, obs, path)   # (Smooth Preview off, layers flattened, modifiers applied: as Export Textures)
        stack.enter_context(T.plain_lows(obs))
        stack.enter_context(only_selected(context, [*obs, *rigs]))
        bpy.ops.export_scene.fbx(filepath=path, object_types={'MESH', 'ARMATURE'}, use_triangles=s.triangulate, bake_anim=False,
                                 **fbx_settings(s.engine, rigs))
    return path


# --- Animation: each clip baked to keys on every frame, then written as a take

def hips_and_root(rig):
    """(hips, root) bones of a skeleton: the bone called hips or pelvis (else the first deforming bone at the top), and the bone at
    the top above it (None when the hips are the top)."""
    bones = rig.data.bones
    hips = next((b for b in bones if _HIPS.search(b.name)), None) or \
        next((b for b in bones if b.use_deform and (b.parent is None or not b.parent.use_deform)), None)
    return hips, (hips.parent_recursive[-1] if hips is not None and hips.parent is not None else None)


def root_problem(rig, motion):
    """Why Root Motion / In Place can't work on the skeleton, or ""."""
    if motion == 'NONE':
        return ""
    hips, root = hips_and_root(rig)
    if hips is None:
        return "%s has no hips bone (a bone called hips or pelvis)" % rig.name
    if motion == 'ROOT' and root is None:
        return "Root Motion needs a root bone above %s (the hips are the top bone of %s)" % (hips.name, rig.name)
    return ""


def rig_actions(rig):
    """The actions of a skeleton: its own, then its layers' (NLA strips), without pose assets."""
    ad = rig.animation_data
    if ad is None:
        return []
    found = [ad.action] + [strip.action for track in ad.nla_tracks for strip in track.strips]
    return [a for a in dict.fromkeys(found) if a is not None and a.asset_data is None]


def clips_of(context, rig):
    """[(name, action or None for what plays, first frame, last frame)] of a skeleton."""
    s, scene = context.scene.m3d_export, context.scene
    if s.clips == 'ACTIONS':
        return [(a.name, a, int(a.frame_range[0]), int(a.frame_range[1])) for a in rig_actions(rig)]
    ad = rig.animation_data
    if ad is None or (ad.action is None and not ad.nla_tracks):
        return []
    if s.anim_range == 'KEYS':
        ranges = [a.frame_range for a in rig_actions(rig)]
        first, last = (min(r[0] for r in ranges), max(r[1] for r in ranges)) if ranges else (scene.frame_start, scene.frame_end)
    elif s.anim_range == 'PLAYBACK' and scene.use_preview_range:
        first, last = scene.frame_preview_start, scene.frame_preview_end
    else:
        first, last = scene.frame_start, scene.frame_end
    return [(ad.action.name if ad.action is not None else "Animation", None, int(first), int(last))]


@contextmanager
def playing(rig, action):
    """`action` plays on its own on the skeleton meanwhile (its layers muted); None: what plays stays."""
    ad = rig.animation_data
    if action is None or ad is None:
        yield
        return
    saved = ad.action, ad.action_slot, ad.use_tweak_mode, [(t, t.mute) for t in ad.nla_tracks]
    try:
        ad.use_tweak_mode = False
        for t, _mute in saved[3]:
            t.mute = True
        ad.action = action
        yield
    finally:
        ad.action = saved[0]
        if saved[0] is not None and saved[1] is not None:
            ad.action_slot = saved[1]
        for t, mute in saved[3]:
            t.mute = mute
        ad.use_tweak_mode = saved[2]


def bake_clip(context, rig, clip, motion):
    """A new action with every bone of `rig` keyed on every frame of the clip as it plays (constraints and layers included, so
    what the engine gets is what you see), the hips' motion over the ground moved to the root bone ('ROOT') or taken out
    ('IN_PLACE'). The skeleton is left as it was."""
    name, action, first, last = clip
    scene = context.scene
    frames = range(first, last + 1)
    poses = []   # per frame {bone: matrix in skeleton space}
    with playing(rig, action):
        for f in frames:
            scene.frame_set(f)
            poses.append({pb.name: pb.matrix.copy() for pb in rig.pose.bones})
    if motion != 'NONE':
        hips, root = hips_and_root(rig)
        start = poses[0][hips.name].translation.copy()
        for pose in poses:
            ground = pose[hips.name].translation - start
            ground.z = 0.0
            if motion == 'ROOT':
                pose[root.name] = Matrix.Translation(ground) @ pose[root.name]
            else:   # (every bone but the root goes back by it)
                for bone in pose:
                    if root is None or bone != root.name:
                        pose[bone] = Matrix.Translation(-ground) @ pose[bone]
    ad = rig.animation_data_create()
    old, old_slot = ad.action, ad.action_slot
    baked = bpy.data.actions.new("%s_%s" % (rig.name, name))
    ad.action = baked   # (the curves are made for the skeleton's slot)
    try:
        for pb in rig.pose.bones:
            bone = pb.bone
            # ponytail: assumes the bone inherits its parent's rotation and scale (the default); other inherit modes bake off.
            rest = bone.parent.matrix_local.inverted() @ bone.matrix_local if bone.parent else bone.matrix_local
            channels = {"location": [], "scale": []}
            rot_path = {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(pb.rotation_mode, "rotation_euler")
            channels[rot_path] = []
            prev_q = prev_e = None
            for pose in poses:
                parent = pose[bone.parent.name] @ rest if bone.parent else rest
                loc, quat, scale = (parent.inverted_safe() @ pose[pb.name]).decompose()
                if prev_q is not None:
                    quat.make_compatible(prev_q)
                prev_q = quat
                if rot_path == "rotation_quaternion":
                    rot = tuple(quat)
                elif rot_path == "rotation_axis_angle":
                    axis, angle = quat.to_axis_angle()
                    rot = (angle, *axis)
                else:
                    prev_e = quat.to_euler(pb.rotation_mode, prev_e) if prev_e is not None else quat.to_euler(pb.rotation_mode)
                    rot = tuple(prev_e)
                channels["location"].append(tuple(loc))
                channels["scale"].append(tuple(scale))
                channels[rot_path].append(rot)
            base = 'pose.bones["%s"].' % bpy.utils.escape_identifier(pb.name)
            for path, rows in channels.items():
                for index in range(len(rows[0])):
                    fc = baked.fcurve_ensure_for_datablock(rig, base + path, index=index, group_name=pb.name)
                    fc.keyframe_points.add(len(rows))
                    fc.keyframe_points.foreach_set("co", [v for f, row in zip(frames, rows) for v in (f, row[index])])
                    fc.update()
    finally:
        ad.action = old
        if old is not None and old_slot is not None:
            ad.action_slot = old_slot
    return baked


@contextmanager
def as_takes(rig, takes):
    """The baked clips [(name, action)] are the skeleton's only animation meanwhile: one NLA strip each, one after the other (the
    FBX exporter writes a take for each strip), its own layers muted and its constraints off (the keys hold their result)."""
    ad = rig.animation_data_create()
    saved = ad.action, ad.action_slot, ad.use_tweak_mode, [(t, t.mute) for t in ad.nla_tracks]
    muted = [(c, c.mute) for pb in rig.pose.bones for c in pb.constraints]
    track = None
    try:
        ad.use_tweak_mode = False
        for t, _mute in saved[3]:
            t.mute = True
        for c, _mute in muted:
            c.mute = True
        ad.action = None
        track = ad.nla_tracks.new()
        start = 0
        for name, action in takes:
            strip = track.strips.new(name, start, action)
            strip.name = name
            start = int(strip.frame_end) + 1
        yield
    finally:
        if track is not None:
            ad.nla_tracks.remove(track)
        ad.action = saved[0]
        if saved[0] is not None and saved[1] is not None:
            ad.action_slot = saved[1]
        for t, mute in saved[3]:
            t.mute = mute
        ad.use_tweak_mode = saved[2]
        for c, mute in muted:
            c.mute = mute


def write_animation(context, folder, rig):
    """The clips of a skeleton as FBX files (a take for each clip, in one file or a file each). Returns the files written."""
    s, scene = context.scene.m3d_export, context.scene
    clips = clips_of(context, rig)
    if not clips:
        return []
    problem = root_problem(rig, s.root_motion)
    if problem:
        raise RuntimeError(problem)
    frame = scene.frame_current
    baked = []
    try:
        for clip in clips:
            baked.append((clip[0], bake_clip(context, rig, clip, s.root_motion)))
        scene.frame_set(frame)
        groups = [[b] for b in baked] if s.clip_files or len(baked) == 1 else [baked]
        paths, base = [], rig.name
        with renamed(engine_names(s, [], [rig])), placed([rig], s.to_origin):
            for takes in groups:
                name = "%s_%s" % (base, takes[0][0] if len(takes) == 1 else "Animations")
                path = os.path.join(folder, bpy.path.clean_name(name) + ".fbx")
                with as_takes(rig, takes), only_selected(context, [rig]):
                    bpy.ops.export_scene.fbx(filepath=path, object_types={'ARMATURE'}, bake_anim=True, bake_anim_use_nla_strips=True,
                                             bake_anim_use_all_actions=False, **fbx_settings(s.engine, [rig]))
                paths.append(path)
        return paths
    finally:
        for _name, action in baked:
            bpy.data.actions.remove(action)
        scene.frame_set(frame)


def export_engine(context):
    """Export to Engine with the scene's settings. Returns the files written."""
    import m3d_texture as T
    s = context.scene.m3d_export
    if s.engine != 'GLTF' and not hasattr(bpy.ops.export_scene, "fbx"):
        raise RuntimeError("The FBX exporter is not enabled")
    files, rigs, _highs = export_plan(context)
    folder = export_dir(context)
    m3d_pair.leave_modes(context)
    paths = []
    with m3d_pair.quiet(context):
        if s.meshes:
            for name, obs, file_rigs in files:
                paths.append(write_meshes(context, os.path.join(folder, name + (".glb" if s.engine == 'GLTF' else ".fbx")),
                                          obs, file_rigs))
        if s.textures and s.engine != 'GLTF':
            sets = texture_sets_of(context, [o for _n, obs, _r in files for o in obs])
            if sets:
                with engine_textures(context, s.engine, folder):
                    paths += T.export_sets(context, sets)
        if s.animation and s.engine != 'GLTF':
            for rig in rigs:
                paths += write_animation(context, folder, rig)
    return paths


_checked = {}   # skeleton name -> Check Rig problems, made when the dialog opens


def draw_export(layout, context, width):
    """The Export to Engine dialog's settings, what it writes and what may go wrong."""
    import m3d_texture as T
    s = context.scene.m3d_export
    files, rigs, highs = export_plan(context)
    layout.row().prop(s, "engine", expand=True)
    draw_lines(layout, context, ENGINES[s.engine][1], width=width)
    row = layout.row()
    row.prop(s, "folder")
    if not s.folder:
        sub = layout.row()
        sub.active = False
        sub.label(text="Empty: %s" % (project_folder("export") or "an export folder next to the scene"), translate=False)
    row = layout.row(align=True)
    for name in ("meshes", "textures", "animation"):
        row.prop(s, name, toggle=True)
    split = layout.split(factor=0.5)
    left, right = split.column(), split.column()
    box = left.box().column()
    box.label(text="Meshes", icon='MESH_DATA')
    box.prop(s, "prefix")
    for name in ("selected_only", "one_file", "to_origin", "triangulate"):
        box.prop(s, name)
    lines = box.column(align=True)
    lines.active = False
    ext = ".glb" if s.engine == 'GLTF' else ".fbx"
    for name, obs, _r in files[:5]:
        lines.label(text="%s%s: %s" % (name, ext, ", ".join(mesh_name(o, s.prefix) for o in obs[:3]) + (" ..." if len(obs) > 3 else "")),
                    icon='FILE_3D', translate=False)
    if len(files) > 5:
        lines.label(text="and %d more files" % (len(files) - 5))
    if not files:
        reason(box, "No mesh to write: show or select the low polys")
    if highs:
        reason(box, "%d high poly(s) left out: only low polys are written" % len(highs))
    box = right.box().column()
    box.label(text="Animation", icon='ARMATURE_DATA')
    if s.engine == 'GLTF':
        reason(box, "glTF writes meshes and textures: pick Unreal or Unity for the animation")
    else:
        sub = box.column()
        split_props(sub)
        for name in ("clips", "anim_range", "root_motion"):
            sub.prop(s, name)
        box.prop(s, "clip_files")
        for rig in rigs:
            clips = clips_of(context, rig)
            box.label(text="%s: %s" % (rig.name, "%d clip(s)" % len(clips) if clips else "no animation"), icon='OUTLINER_OB_ARMATURE',
                      translate=False)
            problems = _checked.get(rig.name, ())
            trouble = [root_problem(rig, s.root_motion)] + [p.text for p in problems]
            for text in filter(None, trouble):
                row = box.row()
                row.alert = True
                row.label(text=text, icon='ERROR', translate=False)
            if problems:
                reason(box, "Check Rig (F5 Rigging) fixes them")
        if not rigs:
            reason(box, "No skeleton with the meshes")
        sets = texture_sets_of(context, [o for _n, obs, _r in files for o in obs])
        box = right.box().column()
        box.label(text="Textures", icon='TEXTURE')
        box.label(text="%d texture set(s), %s" % (len(sets), T.TEMPLATES[texture_template(context, s.engine)][0]), translate=False)
        T.draw_stale(box, context, sets, button=False)
        reason(box, "File type, size and padding: Export Textures")


class M3D_OT_export_engine(Operator):
    """Export to Engine: the low polys, their textures and the animation for Unreal, Unity or glTF in one pass (high polys and
    cages are never written)"""
    bl_idname = "m3d.export_engine"
    bl_label = "Export to Engine"

    repeat: BoolProperty(options={'SKIP_SAVE'}, description="Export again with the last settings, without the dialog")

    @classmethod
    def description(cls, context, props):
        if props.repeat:
            files = [f for f in context.scene.m3d_export.last_files.split("|") if f]
            return "Export again with the same settings (%d files last time, into %s)" % (
                len(files), os.path.dirname(files[0]) if files else "-")
        return " ".join(cls.__doc__.split())

    def invoke(self, context, _event):
        if self.repeat:
            return self.execute(context)
        import m3d_rig
        _checked.clear()
        for rig in export_plan(context)[1]:   # (Check Rig first: its problems show in the dialog)
            _checked[rig.name] = m3d_rig.check_rig(context, rig)
        return context.window_manager.invoke_props_dialog(self, width=660, title="Export to Engine", confirm_text="Export")

    def draw(self, context):
        draw_export(self.layout, context, 660 * (context.preferences.system.ui_scale or 1.0))

    def execute(self, context):
        s = context.scene.m3d_export
        try:
            paths = export_engine(context)
        except (RuntimeError, OSError) as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        if not paths:
            self.report({'WARNING'}, "Nothing to write: no low poly, texture set or animation")
            return {'CANCELLED'}
        s.last_files = "|".join(paths)
        self.report({'INFO'}, "Exported %d files to %s" % (len(paths), os.path.dirname(paths[0])))
        return {'FINISHED'}


def repeat_ready(context):
    return bool(context.scene.m3d_export.last_files)


def draw_export_buttons(layout, context):
    """Export to Engine and, after one, Repeat Last Export."""
    row = layout.row(align=True)
    row.operator("m3d.export_engine", text="Export to Engine...", icon='EXPORT')
    if repeat_ready(context):
        row.operator("m3d.export_engine", text="Repeat", icon='FILE_REFRESH').repeat = True


class PROPERTIES_PT_m3d_an_export(_PagePanel, Panel):
    """Animation workspace, Playback tab: Export to Engine"""
    page = "anim_playback"
    bl_label = "Export to Engine"

    def draw(self, context):
        draw_export_buttons(self.layout, context)
        reason(self.layout, "The meshes, textures and animation for the engine")


# -----------------------------------------------------------------------------
# References: a linked scene file whose skeletons can be posed, and the Reference Editor

def owned(lib, id_):
    """`id_` is from the library `lib`, or overrides data from it."""
    if id_.library == lib:
        return True
    ov = id_.override_library
    return ov is not None and ov.reference is not None and ov.reference.library == lib


def reference_libraries():
    """The libraries the scene has objects or collections from (an asset library's brushes and images are no reference)."""
    return [lib for lib in bpy.data.libraries
            if any(owned(lib, i) for coll in (bpy.data.objects, bpy.data.collections) for i in coll)]


def reference_roots(context, lib):
    """(collections, instancing empties) of the scene that bring `lib` in: its top collections (linked or overridden) and the
    empties that instance one of its collections (a Blender Link)."""
    found = [c for c in context.scene.collection.children_recursive if owned(lib, c)]
    tops = [c for c in found if not any(c in other.children_recursive for other in found if other is not c)]
    empties = [o for o in context.scene.objects if o.instance_type == 'COLLECTION' and o.instance_collection is not None
               and o.instance_collection.library == lib]
    return tops, empties


def layer_collection(layer, coll):
    if layer.collection == coll:
        return layer
    for child in layer.children:
        found = layer_collection(child, coll)
        if found is not None:
            return found
    return None


def is_loaded(context, lib):
    tops, empties = reference_roots(context, lib)
    layers = [layer_collection(context.view_layer.layer_collection, c) for c in tops]
    return any(lc is not None and not lc.exclude for lc in layers) or any(not o.hide_viewport for o in empties) or not (tops or empties)


def keyed_bones(lib):
    """{skeleton: names of its keyed bones} for the skeletons of the reference that are animated."""
    import m3d_rig
    found = {}
    for ob in bpy.data.objects:
        if ob.type == 'ARMATURE' and owned(lib, ob) and ob.animation_data is not None:
            actions = [ob.animation_data.action] + [s.action for t in ob.animation_data.nla_tracks for s in t.strips]
            names = {m.group(1).replace('\\"', '"') for a in actions if a is not None for fc in m3d_rig.action_fcurves(a)
                     for m in [_BONE_PATH.match(fc.data_path)] if m}
            if names:
                found[ob.name] = names
    return found


def gone_bones(before):
    """"; keys of bones that are gone: Arm, Hand" for the bones of `keyed_bones` the reloaded skeletons do not have."""
    gone = sorted({n for ob_name, names in before.items() for ob in [bpy.data.objects.get(ob_name)] if ob is not None
                   for n in names if ob.pose is None or n not in ob.pose.bones})
    return "; keys of bones that are gone: %s" % ", ".join(gone) if gone else ""


def create_reference(context, path):
    """Link the collections of a scene file into the scene as a library override (the reference): its skeletons are editable,
    so they can be posed and keyed at once; the rest follows the file. Returns the new collections."""
    with bpy.data.libraries.load(path, link=True, relative=bool(bpy.data.filepath)) as (src, dst):
        dst.collections = list(src.collections)
    linked = [c for c in dst.collections if c is not None and c.all_objects]   # (an empty collection brings nothing)
    tops = [c for c in linked if not any(c in other.children_recursive for other in linked if other is not c)]
    if not tops:
        raise RuntimeError("%s has no collection to reference (put its objects in one)" % os.path.basename(path))
    made = []
    for coll in tops:
        over = coll.override_hierarchy_create(context.scene, context.view_layer)
        if over.name not in context.scene.collection.children and over not in context.scene.collection.children_recursive:
            context.scene.collection.children.link(over)
        for ob in over.all_objects:
            if ob.type == 'ARMATURE' and ob.override_library is not None:
                ob.override_library.is_system_override = False
        made.append(over)
    return made


class M3D_OT_create_reference(Operator):
    """Create Reference: bring in a scene file that stays linked to it (an edit of that file shows up here on reload); its
    skeletons can be posed and keyed at once (Ctrl+R)"""
    bl_idname = "m3d.create_reference"
    bl_label = "Create Reference"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.blend", options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, _event):
        if project():
            self.filepath = folder_path("scenes")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath.lower().endswith(".blend") or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "Pick a scene file (.blend)")
            return {'CANCELLED'}
        if os.path.normcase(os.path.abspath(self.filepath)) == os.path.normcase(bpy.data.filepath):
            self.report({'ERROR'}, "A scene can't reference itself")
            return {'CANCELLED'}
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            made = create_reference(context, self.filepath)
        except (RuntimeError, OSError) as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        self.report({'INFO'}, "Referenced %s (%s)" % (os.path.basename(self.filepath), ", ".join(c.name for c in made)))
        return {'FINISHED'}


REF_ACTIONS = (
    ('RELOAD', "Reload", "Read the file again (what changed in it shows up here)"),
    ('REPLACE', "Replace", "Use another file for this reference (the same names are matched up)"),
    ('UNLOAD', "Unload", "Take the reference out of the scene for now (it is kept: Load brings it back)"),
    ('LOAD', "Load", "Bring the unloaded reference back"),
    ('REMOVE', "Remove", "Remove the reference and everything it brought in"),
    ('EDITABLE', "Make Editable", "Make every object of the reference editable here (moved, posed, keyed; the rest still follows the file)"),
    ('LOCAL', "Import Objects", "Make the reference's objects part of this scene: they no longer follow the file"),
    ('PATH', "Relative / Absolute", "Store the path relative to this scene, or absolute"),
)


class M3D_OT_reference(Operator):
    """A Reference Editor command on one reference"""
    bl_idname = "m3d.reference"
    bl_label = "Reference"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=REF_ACTIONS)
    library: StringProperty(options={'SKIP_SAVE'})
    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(default="*.blend", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, props):
        return next(d for k, _l, d in REF_ACTIONS if k == props.action)

    def invoke(self, context, _event):
        lib = bpy.data.libraries.get(self.library)
        if self.action == 'REPLACE' and lib is not None:
            self.filepath = bpy.path.abspath(lib.filepath)
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        return self.execute(context)

    def execute(self, context):
        lib = bpy.data.libraries.get(self.library)
        if lib is None:
            self.report({'ERROR'}, "No reference %s" % self.library)
            return {'CANCELLED'}
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            text = getattr(self, "do_" + self.action.lower())(context, lib)
        except (RuntimeError, OSError) as err:
            self.report({'ERROR'}, str(err).strip())
            return {'CANCELLED'}
        self.report({'WARNING'} if "gone" in text else {'INFO'}, text)
        return {'FINISHED'}

    def do_reload(self, _context, lib):
        before = keyed_bones(lib)
        lib.reload()
        return "Reloaded %s" % lib.name + gone_bones(before)

    def do_replace(self, _context, lib):
        if not os.path.isfile(self.filepath):
            raise RuntimeError("Pick a scene file (.blend)")
        before = keyed_bones(lib)
        relative = lib.filepath.startswith("//") and bpy.data.filepath
        lib.filepath = bpy.path.relpath(self.filepath) if relative else self.filepath
        lib.reload()
        return "%s now reads %s" % (lib.name, os.path.basename(self.filepath)) + gone_bones(before)

    def _load(self, context, lib, load):
        tops, empties = reference_roots(context, lib)
        for coll in tops:
            lc = layer_collection(context.view_layer.layer_collection, coll)
            if lc is not None:
                lc.exclude = not load
        for ob in empties:
            ob.hide_viewport = ob.hide_render = not load
        return ("Loaded %s" if load else "Unloaded %s") % lib.name

    def do_unload(self, context, lib):
        return self._load(context, lib, False)

    def do_load(self, context, lib):
        return self._load(context, lib, True)

    def do_remove(self, context, lib):
        tops, empties = reference_roots(context, lib)
        local = {i for coll in (bpy.data.objects, bpy.data.collections) for i in coll if i.library is None and owned(lib, i)}
        bpy.data.batch_remove([*local, *empties])
        name = lib.name
        bpy.data.libraries.remove(lib)
        return "Removed %s" % name

    def do_editable(self, context, lib):
        tops, empties = reference_roots(context, lib)
        for empty in empties:   # (a Blender Link: an empty that instances the collection becomes an override first)
            with context.temp_override(active_object=empty, object=empty, selected_objects=[empty], selected_editable_objects=[empty]):
                bpy.ops.object.make_override_library()
        count = 0
        for i in (*bpy.data.objects, *bpy.data.collections):
            if i.library is None and i.override_library is not None and owned(lib, i) and i.override_library.is_system_override:
                i.override_library.is_system_override = False
                count += 1
        return "%s: %d more editable" % (lib.name, count)

    def do_local(self, context, lib):
        tops, empties = reference_roots(context, lib)
        for coll in tops:
            if coll.override_library is not None:
                coll.override_library.destroy(do_hierarchy=True)
        for empty in empties:
            with context.temp_override(active_object=empty, object=empty, selected_objects=[empty], selected_editable_objects=[empty]):
                bpy.ops.object.duplicates_make_real()
            bpy.data.objects.remove(empty)
        while True:   # (what the scene's own data uses of the file becomes its own, and then what that uses)
            linked = [i for i in bpy.data.user_map() if i.library == lib]
            used = [i for i, users in bpy.data.user_map(subset=linked).items() if any(u.library is None for u in users)]
            if not used:
                break
            for i in used:
                i.make_local()
        name = lib.name
        bpy.data.libraries.remove(lib)   # (the rest of the file: nothing here uses it)
        return "Imported the objects of %s" % name

    def do_path(self, _context, lib):
        if lib.filepath.startswith("//"):
            lib.filepath = bpy.path.abspath(lib.filepath)
        elif not bpy.data.filepath:
            raise RuntimeError("Save the scene first: a relative path starts from it")
        else:
            lib.filepath = bpy.path.relpath(lib.filepath)
        return "%s: %s" % (lib.name, lib.filepath)


class M3D_PT_reference_editor(Panel):
    """Reference Editor: the scene files referenced into this one (Windows menu)"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Reference Editor"
    bl_ui_units_x = 26

    def draw(self, context):
        layout = self.layout
        layout.label(text="Reference Editor", icon='LINK_BLEND')
        libs = reference_libraries()
        if not libs:
            reason(layout, "No references: File > Create Reference brings in a scene file that stays linked")
        for lib in libs:
            box = layout.box().column(align=True)
            row = box.row(align=True)
            loaded = is_loaded(context, lib)
            row.label(text=lib.name + ("" if loaded else " (unloaded)"), icon='LIBRARY_DATA_DIRECT', translate=False)
            row = box.row()
            row.alert = lib.is_missing
            row.label(text=("Missing: " if lib.is_missing else "") + lib.filepath, translate=False)
            row = box.row(align=True)
            for action, icon in (('RELOAD', 'FILE_REFRESH'), ('REPLACE', 'FILEBROWSER'), ('UNLOAD' if loaded else 'LOAD', 'HIDE_OFF' if loaded else 'HIDE_ON'),
                                 ('REMOVE', 'X')):
                o = row.operator("m3d.reference", text=next(label for k, label, _d in REF_ACTIONS if k == action), icon=icon)
                o.action, o.library = action, lib.name
            row = box.row(align=True)
            for action, label in (('EDITABLE', "Make Editable"), ('LOCAL', "Import Objects"),
                                  ('PATH', "Make Absolute" if lib.filepath.startswith("//") else "Make Relative")):
                o = row.operator("m3d.reference", text=label)
                o.action, o.library = action, lib.name
        layout.operator("m3d.create_reference", text="Create Reference...", icon='ADD')


# -----------------------------------------------------------------------------

classes = (
    M3D_OT_project_set,
    M3D_MT_recent_projects,
    M3D_OT_open_scene,
    M3D_OT_save_scene,
    M3D_OT_import_file,
    M3D_ExportSettings,
    M3D_OT_export_engine,
    PROPERTIES_PT_m3d_an_export,
    M3D_OT_create_reference,
    M3D_OT_reference,
    M3D_PT_reference_editor,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_export = PointerProperty(type=M3D_ExportSettings)
    bpy.app.handlers.load_post.append(project_defaults)


def unregister():
    if project_defaults in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(project_defaults)
    del bpy.types.Scene.m3d_export
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
