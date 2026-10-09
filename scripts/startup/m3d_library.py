# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Library of the Texture workspace (F4) for Maelstrom3D: materials (whole layer setups), mask presets, brushes and alphas
in one tile browser, and your own items.

An item is a JSON description of layers, so applying one is making the layers again with m3d_layers / m3d_masks (no
data is appended from a .blend):

    material  {"format": 1, "type": "MATERIAL", "name": ..., "description": ..., "layer": <layer>}
    mask      {"format": 1, "type": "MASK", "name": ..., "description": ..., "mask": [<effect>, ...]}
    layer     {"name", "kind": PAINT | FILL | FOLDER, "visible", "opacity", "blend", "use_alpha",
               "channels": {channel id: color list | value | file name | null}, "layers": [<layer>, ...] (folders),
               "mask": [<effect>, ...]}
    effect    {"kind", "name", "visible", "opacity", "blend", the settings of its kind, "image": file name (Paint)}

A material is a folder: applying it adds that folder on top of the layer stack, named after the item. A Fill Layer's
channel is its value (linear color for Base Color / Emission, a number for Roughness / Metallic / Height, null for
Normal), a Paint Layer's is the PNG next to the item (or null: no image yet). The starter items are plain data
(m3d_library_data.py); yours are a folder each in the user library (<user datafiles>/m3d_library/user/<name>/item.json,
its paint images as PNG and thumb.png). Thumbnails of the starter items are cached in m3d_library/thumbs.

Thumbnails are small Cycles renders of a grooved sphere with the item applied (a mask preset is shown as the mask on
the sphere). They are made one step at a time on a timer once the Library tab is first drawn: the preview scene is made,
the maps the generators read are baked on its sphere once, then one item is rendered per step.
"""

import hashlib
import json
import math
import os
import re
import shutil
import time
import traceback
import uuid
from collections import namedtuple
from types import SimpleNamespace

import bmesh
import bpy
import bpy.utils.previews
import numpy as np
from bpy.props import EnumProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from bl_ui.properties_paint_common import BrushAssetShelf

import m3d_layers as L
import m3d_library_data as DATA
import m3d_masks as MK
import m3d_sculpt as S
import m3d_texture as T
from m3d_sculpt import mesh_of, reason
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Items

Entry = namedtuple("Entry", "ref item directory")   # ref: "starter:<slug>" or "user:<slug>"; directory: a user item's folder


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "item"


STARTERS = tuple(Entry("starter:" + slug(item["name"]), item, None) for item in (*DATA.MATERIALS, *DATA.MASKS))


def f32(value):
    """The shortest decimal that is the same float32: a saved value comes back exactly."""
    return float(np.format_float_positional(np.float32(value), unique=True, trim='-'))


def library_dir(create=False):
    return bpy.utils.user_resource('DATAFILES', path="m3d_library", create=create)


def user_root():
    base = library_dir()
    return os.path.join(base, "user") if base else ""


_user = {"entries": None}   # the user's items, read from the folder when first needed


def user_entries():
    if _user["entries"] is None:
        found, root = [], user_root()
        for name in sorted(os.listdir(root)) if root and os.path.isdir(root) else ():
            folder = os.path.join(root, name)
            try:
                with open(os.path.join(folder, "item.json"), encoding="utf-8") as fh:
                    item = json.load(fh)
                if item["type"] == 'MATERIAL':
                    valid = isinstance(item["layer"], dict)
                else:
                    valid = item["type"] == 'MASK' and isinstance(item["mask"], list)
                if valid and isinstance(item["name"], str):
                    found.append(Entry("user:" + name, item, folder))
            except (OSError, ValueError, KeyError, TypeError):
                print("Library: skipping the damaged item", folder)
        _user["entries"] = found
    return _user["entries"]


def entries(kind=None):
    """Every item, starters first (kind: 'MATERIAL' or 'MASK' for only those)."""
    return [e for e in (*STARTERS, *user_entries()) if kind in {None, e.item["type"]}]


def find_entry(ref):
    return next((e for e in entries() if e.ref == ref), None)


# -----------------------------------------------------------------------------
# Describing layers (saving)

class Files(dict):
    """The images an item keeps next to its JSON: file name -> (image, is it sRGB)."""

    def add(self, image, srgb):
        name = "image%d.png" % (len(self) + 1)
        self[name] = (image, srgb)
        return name


def describe_effect(e, files):
    out = {"kind": e.kind, "name": e.name}
    if not e.visible:
        out["visible"] = False
    out["opacity"], out["blend"] = f32(e.opacity), e.blend
    for prop, _label in MK.PARAM_UI.get(e.kind, ()):
        value = getattr(e, prop)
        out[prop] = [f32(x) for x in value] if hasattr(value, "__len__") and not isinstance(value, str) \
            else f32(value) if isinstance(value, float) else value
    if e.kind == 'PAINT' and e.image is not None:
        out["image"] = files.add(e.image, False)
    return out


def describe_layer(layer, files):
    out = {"name": layer.name, "kind": layer.kind}
    if not layer.visible:
        out["visible"] = False
    if layer.opacity != 1.0:
        out["opacity"] = f32(layer.opacity)
    if layer.blend != 'MIX':
        out["blend"] = layer.blend
    if layer.kind == 'FOLDER':
        out["layers"] = [describe_layer(kid, files) for kid in L.children(layer)]
    else:
        if not layer.use_alpha:
            out["use_alpha"] = False
        channels = {}
        for ch in L.CHANNELS:
            e = L.entry_of(layer, ch.id)
            if not e.use:
                continue
            if layer.kind == 'PAINT':
                channels[ch.id] = files.add(e.image, ch.srgb) if e.image is not None else None
            elif ch.id in L.SCALARS:
                channels[ch.id] = f32(e.value)
            else:
                channels[ch.id] = None if ch.id == 'NORMAL' else [f32(x) for x in e.color]
        out["channels"] = channels
    if layer.mask_stack:
        out["mask"] = [describe_effect(e, files) for e in layer.mask_stack]
    return out


def describe_material(name, layer, files):
    """The item for a layer: a folder as it is, any other layer inside a folder of its own."""
    spec = describe_layer(layer, files)
    if layer.kind != 'FOLDER':
        spec = {"name": name, "kind": 'FOLDER', "layers": [spec]}
    spec["name"] = name
    return {"format": DATA.FORMAT, "type": 'MATERIAL', "name": name, "layer": spec}


def describe_mask(name, layer, files):
    return {"format": DATA.FORMAT, "type": 'MASK', "name": name, "mask": [describe_effect(e, files) for e in layer.mask_stack]}


def save_png(image, srgb, path):
    """Write an image to a PNG exactly as its pixels are (no color conversion)."""
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    w, h = image.size
    out = bpy.data.images.new("m3dLibrarySave", w, h, alpha=image.depth in {32, 128}, is_data=not srgb)
    try:
        out.pixels.foreach_set(px)
        out.filepath_raw, out.file_format = path, 'PNG'
        out.save()
    finally:
        bpy.data.images.remove(out)


def unique_slug(root, name):
    base, n = slug(name), 1
    while os.path.exists(os.path.join(root, base if n == 1 else "%s_%d" % (base, n))):
        n += 1
    return base if n == 1 else "%s_%d" % (base, n)


def save_user_item(item, files):
    """Write the item to the user library (a folder with item.json and its images). -> its ref"""
    base = library_dir(create=True)
    if not base:
        raise RuntimeError("The user data folder cannot be made")
    root = os.path.join(base, "user")
    folder = os.path.join(root, unique_slug(root, item["name"]))
    try:
        os.makedirs(folder)
        for name, (image, srgb) in files.items():
            save_png(image, srgb, os.path.join(folder, name))
        with open(os.path.join(folder, "item.json"), "w", encoding="utf-8") as fh:
            json.dump(item, fh, indent=1)
    except (OSError, RuntimeError) as err:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError("Can't write to the library folder %s: %s" % (root, err))
    _user["entries"] = None
    _gen["done"] = False   # (a new thumbnail to make)
    return "user:" + os.path.basename(folder)


# -----------------------------------------------------------------------------
# Making layers from a description (applying)

def load_image(directory, filename, name, srgb):
    """A generated image (as the layer stack's own) holding the pixels of a PNG of the item's folder."""
    if directory is None or filename != os.path.basename(filename):
        raise ValueError("no image folder")
    src = bpy.data.images.load(os.path.join(directory, filename), check_existing=False)
    try:
        w, h, alpha = src.size[0], src.size[1], src.depth in {32, 128}
        px = np.empty(len(src.pixels), np.float32)
        src.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(src)
    image = bpy.data.images.new(name[:60], w, h, alpha=alpha, is_data=not srgb)
    image.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'   # (before the pixels: it resets them)
    image.pixels.foreach_set(px)
    image.update()
    return image


def add_effects(layer, specs, directory, first, made, skip=0):
    """Add mask effects at the end of the layer's stack. `first`: the blend of the first one when it has none or
    mixes ('MIX' for an empty stack, 'MULTIPLY' to combine with a mask that is there). `skip`: the first effects of the
    stack are about to go, their names are free."""
    for i, spec in enumerate(specs):
        kind = spec["kind"]
        taken = {e.name for e in list(layer.mask_stack)[skip:]}
        base = spec.get("name") or MK.KIND_BY_ID[kind].label
        name = next(n for n in (base, *("%s %d" % (base, k) for k in range(2, 10000))) if n not in taken)
        e = L.add_effect(layer, kind, name)
        e.visible = spec.get("visible", True)
        e.opacity = spec.get("opacity", 1.0)
        blend = spec.get("blend") or ('MIX' if i == 0 else 'MULTIPLY')
        if i == 0 and blend == 'MIX':
            blend = first
        if kind not in MK.FILTERS:
            e.blend = blend
        for key, value in spec.items():
            if key in MK.PARAM_PROPS:
                setattr(e, key, value)
        if kind == 'PAINT' and spec.get("image"):
            e.image = load_image(directory, spec["image"], L.image_name(layer.id_data, layer, "Mask"), False)
            made.images.append(e.image)
    if specs:
        layer.mask_index = len(layer.mask_stack) - 1


def add_layer_spec(mat, spec, parent, directory, made, name=None):
    """Make a layer (a folder: the layers inside first, so each folder follows its layers) at the end of the stack.
    -> its uid"""
    uid, kind = uuid.uuid4().hex[:6], spec["kind"]
    if kind == 'FOLDER':
        for kid in spec.get("layers", ()):
            add_layer_spec(mat, kid, uid, directory, made)
    layer = L.add_layer(mat, kind, name or spec["name"])
    made.uids.append(uid)
    layer.uid, layer.parent = uid, parent
    layer.visible, layer.opacity = spec.get("visible", True), spec.get("opacity", 1.0)
    layer.blend, layer.use_alpha = spec.get("blend", 'MIX'), spec.get("use_alpha", True)
    channels = spec.get("channels", {})
    for ch in L.CHANNELS if kind != 'FOLDER' else ():
        e = L.entry_of(layer, ch.id)
        e.use = ch.id in channels
        value = channels.get(ch.id)
        if not e.use or value is None:
            continue
        if kind == 'FILL':
            if ch.id in L.SCALARS:
                e.value = value
            else:
                e.color = value
        else:
            e.image = load_image(directory, value, L.image_name(mat, layer, ch.label), ch.srgb)
            e.image["m3d_channel"] = ch.id   # (not set_channel_space: choosing the color space again blanks a generated image)
            made.images.append(e.image)
    add_effects(layer, spec.get("mask", ()), directory, 'MIX', made)
    return uid


def discard(mat, made):
    """Take back what a failed build made."""
    L.remove_layers(mat, set(made.uids))
    for image in made.images:
        if image.name in bpy.data.images:
            bpy.data.images.remove(image)


def build_material(mat, item, directory):
    """The item's folder on top of the stack, without rebuilding the nodes. -> (uid of the folder, what was made)"""
    spec = item["layer"]
    if spec.get("kind") != 'FOLDER':
        spec = {"name": item["name"], "kind": 'FOLDER', "layers": [spec]}
    made = SimpleNamespace(uids=[], images=[])
    try:
        with MK.muted():
            uid = add_layer_spec(mat, spec, "", directory, made, name=L.unique_name(mat, item["name"]))
    except (KeyError, TypeError, ValueError, AttributeError, RuntimeError) as err:
        discard(mat, made)
        raise RuntimeError("The item %s is damaged (%s)" % (item.get("name", "?"), err))
    return uid, made


def map_ready(ob, key):
    """Does the mesh have this baked map at the Bake tab's resolution (ensure_maps reuses it)?"""
    image = bpy.data.images.get("%s_%s" % (ob.name, MK.MAP_LABELS[key]))
    return image is not None and image.get("m3d_map") == int(ob.m3d_bake.resolution)


def bake_missing(context, ob, layers):
    """Bake (once, together) the maps the generators of `layers` still miss; a map the mesh has is reused."""
    keys = sorted({key for layer in layers for _e, key in MK.missing_maps(layer)})
    if keys:
        if not ob.data.uv_layers and not all(map_ready(ob, key) for key in keys):
            raise RuntimeError("This mesh has no UVs: use Auto Unwrap")
        T.ensure_maps(context, ob, keys)


def apply_material(context, ob, mat, item, directory):
    """Add the item as a folder on top of the stack and make it the active layer (the caller rebuilds). -> its name"""
    L.migrate(mat)
    uid, made = build_material(mat, item, directory)
    try:
        bake_missing(context, ob, [L.layer_by_uid(mat, u) for u in made.uids])
    except RuntimeError:
        discard(mat, made)
        raise
    L.activate(mat, uid)
    return L.layer_by_uid(mat, uid).name


def trim_effects(layer, keep):
    """Remove the effects above the first `keep` ones."""
    with MK.muted():
        while len(layer.mask_stack) > keep:
            layer.mask_stack.remove(len(layer.mask_stack) - 1)


def apply_mask(context, ob, mat, item, directory, replace):
    """Give the active layer the item's mask effects (`replace`: instead of its mask, else on top of it; the caller
    rebuilds). -> the images the replaced mask owned, for the caller to release after the rebuild"""
    layer = L.active_layer(mat)
    before, made = len(layer.mask_stack), SimpleNamespace(uids=[], images=[])

    def undo():
        trim_effects(layer, before)
        for image in made.images:
            bpy.data.images.remove(image)
    try:
        with MK.muted():
            add_effects(layer, item["mask"], directory, 'MIX' if replace or not before else 'MULTIPLY', made,
                        skip=before if replace else 0)
    except (KeyError, TypeError, ValueError, AttributeError, RuntimeError) as err:
        undo()
        raise RuntimeError("The item %s is damaged (%s)" % (item.get("name", "?"), err))
    try:
        bake_missing(context, ob, [layer])
    except RuntimeError:
        undo()
        raise
    old = []
    if replace and before:
        with MK.muted():
            old = [e.image for e in list(layer.mask_stack)[:before] if e.kind in MK.OWNED and e.image is not None]
            for _i in range(before):
                layer.mask_stack.remove(0)
            layer.mask_index, layer.paint_mask = len(layer.mask_stack) - 1, False
    return old


# -----------------------------------------------------------------------------
# Thumbnails: small Cycles renders of a grooved sphere with the item applied, made one step at a time

RIG = "m3dLibraryPreview"   # name of the preview scene, its sphere, material, world and baked maps
RIG_VERSION = "1"           # part of a starter thumbnail's file name: change it to have them made again
THUMB, MAP_SIZE = 128, 256

_gen = {"running": False, "done": False, "stage": None, "jobs": [], "maps": [], "failed": set(), "made": 0, "time": 0.0}
_version = {}   # ref -> how often its thumbnail was made (a new preview icon each time)


def thumb_path(entry):
    if entry.directory:
        return os.path.join(entry.directory, "thumb.png")
    base = library_dir()
    if not base:
        return ""
    digest = hashlib.md5((RIG_VERSION + json.dumps(entry.item, sort_keys=True)).encode()).hexdigest()[:8]
    return os.path.join(base, "thumbs", "%s_%s.png" % (entry.ref.partition(":")[2], digest))


def pending():
    """The items that have no thumbnail yet (and did not fail to get one)."""
    return [e for e in entries() if thumb_path(e) and e.ref not in _gen["failed"] and not os.path.isfile(thumb_path(e))]


def effect_specs(item):
    """Every mask effect of an item."""
    def layers(spec):
        for kid in spec.get("layers", ()):
            yield from layers(kid)
        yield from spec.get("mask", ())
    return list(layers(item["layer"])) if item["type"] == 'MATERIAL' else list(item["mask"])


def maps_of(item):
    """The baked maps the item's generators read."""
    keys = set()
    for spec in effect_specs(item):
        kind = MK.KIND_BY_ID.get(spec.get("kind"))
        if kind is not None:
            keys.update(('POSITION',) if kind.id == 'NOISE' and spec.get("space") == 'OBJECT' else kind.maps)
    return keys


def preview_hdri():
    """The HDRI that lights the preview: Blender's courtyard (the first studio HDRI without it)."""
    found = [s for s in bpy.context.preferences.studio_lights if s.type == 'WORLD']
    return next((s.path for s in found if s.name.startswith("courtyard")), found[0].path if found else "")


def make_sphere():
    """A sphere with a ridge and three grooves around it: convex edges, cavities and a top, which is what the
    generators need to show something."""
    mesh = bpy.data.meshes.new(RIG)
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_uvsphere(bm, u_segments=128, v_segments=64, radius=1.0, calc_uvs=True)
    for v in bm.verts:
        def band(centre, depth, width):
            return depth * math.exp(-((v.co.z - centre) / width) ** 2)
        v.co *= 1.0 - band(0.0, 0.22, 0.05) + band(0.45, 0.11, 0.035) - band(0.66, 0.18, 0.03) - band(-0.55, 0.18, 0.03)
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    return mesh


def make_rig():
    """The preview scene: the sphere with a material, a camera and an HDRI world; Cycles, 128 px, transparent."""
    scene = bpy.data.scenes.new(RIG)
    r, c = scene.render, scene.cycles
    r.engine, c.device, c.samples, c.use_denoising, c.denoiser = 'CYCLES', 'CPU', 24, True, 'OPENIMAGEDENOISE'
    r.resolution_x = r.resolution_y = THUMB
    r.resolution_percentage, r.film_transparent = 100, True
    r.image_settings.file_format, r.image_settings.color_mode, r.image_settings.color_depth = 'PNG', 'RGBA', '8'
    ob = bpy.data.objects.new(RIG + "Sphere", make_sphere())
    ob.rotation_euler = (math.radians(30), 0.0, math.radians(15))
    mat = bpy.data.materials.new(RIG)
    mat.use_nodes = True
    ob.data.materials.append(mat)
    cam = bpy.data.objects.new(RIG + "Camera", bpy.data.cameras.new(RIG))
    cam.data.lens, cam.location, cam.rotation_euler = 85.0, (0.0, -5.4, 0.0), (math.pi / 2, 0.0, 0.0)
    for o in (ob, cam):
        scene.collection.objects.link(o)
    scene.camera = cam
    world = bpy.data.worlds.new(RIG)
    world.use_nodes = True
    world.light_settings.distance = 0.35   # (the Ambient Occlusion bake)
    nodes, path = world.node_tree.nodes, preview_hdri()
    if path:
        env = nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(path, check_existing=False)
        env.image.name = RIG + "HDRI"
        world.node_tree.links.new(env.outputs["Color"], nodes["Background"].inputs["Color"])
    scene.world = world
    scene.view_layers[0].update()
    s = ob.m3d_bake
    s.resolution, s.margin, s.samples, s.thickness_distance = str(MAP_SIZE), 8, 16, 1.5


def rig_parts():
    """(scene, sphere, material, a context for the bake) of the preview scene, None when it is not there."""
    scene, ob, mat = bpy.data.scenes.get(RIG), bpy.data.objects.get(RIG + "Sphere"), bpy.data.materials.get(RIG)
    if scene is None or ob is None or mat is None:
        return None
    return scene, ob, mat, SimpleNamespace(scene=scene, view_layer=scene.view_layers[0],
                                          window_manager=bpy.context.window_manager)


def rig_override(scene, ob):
    """Operators (bake, render) see the preview scene as the scene, its sphere the active object."""
    return bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0], active_object=ob, object=ob,
                                     selected_objects=[ob], selected_editable_objects=[ob])


def clear_rig(mat):
    images = L.stack_images(mat)
    with MK.muted():
        mat.m3d_layers.clear()
        mat.m3d_layer_index = 0
        mat.m3d_show_mask = False
    L.rebuild_all(mat)
    L.release(images)


def teardown_rig():
    mat = bpy.data.materials.get(RIG)
    if mat is not None:
        clear_rig(mat)
    scene = bpy.data.scenes.get(RIG)
    if scene is not None:
        bpy.data.scenes.remove(scene)
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.cameras, bpy.data.materials, bpy.data.worlds,
                       bpy.data.images):
        for datablock in [d for d in collection if d.name.startswith(RIG)]:   # (also the maps: m3dLibraryPreviewSphere_AO ...)
            collection.remove(datablock)


def build_preview(ctx, ob, mat, entry):
    """Put the item on the sphere's material: a material as its folder, a mask preset as the mask of a layer that is
    shown on its own."""
    if entry.item["type"] == 'MATERIAL':
        add_layer_spec(mat, DATA.fill("Preview Base", "#454545", rough=0.6, metal=0.0), "", None, SimpleNamespace(uids=[], images=[]))
        _uid, made = build_material(mat, entry.item, entry.directory)
        layers = [L.layer_by_uid(mat, u) for u in made.uids]
    else:
        layer = L.add_layer(mat, 'FILL', "Preview")
        made = SimpleNamespace(uids=[layer.uid], images=[])
        with MK.muted():
            L.entry_of(layer, 'BASE_COLOR').color = (0.8, 0.8, 0.8, 1.0)
            add_effects(layer, entry.item["mask"], entry.directory, 'MIX', made)
            mat.m3d_show_mask = True
        layers = [layer]
    bake_missing(ctx, ob, layers)
    L.link_maps(mat, ob)
    L.rebuild_all(mat)


def render_entry(entry):
    """Render the item's thumbnail (the preview scene is there, its maps baked)."""
    scene, ob, mat, ctx = rig_parts()
    path = thumb_path(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path[:-4] + "_tmp.png"
    clear_rig(mat)
    with rig_override(scene, ob):
        build_preview(ctx, ob, mat, entry)
        scene.view_settings.view_transform = 'Standard' if entry.item["type"] == 'MASK' else 'AgX'
        scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True, scene=RIG)
    os.replace(tmp, path)
    _version[entry.ref] = _version.get(entry.ref, 0) + 1


def redraw_library():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


def finish_generation():
    g = _gen
    teardown_rig()
    g.update(stage=None, running=False, jobs=[], maps=[])
    g["done"] = not pending()


def step():
    """One unit of thumbnail work: the queue, the preview scene, a baked map, a rendered item. False when there is
    nothing more to do (the preview scene is gone then)."""
    g = _gen
    if g["stage"] is None:
        g["jobs"] = pending()
        if not g["jobs"]:
            finish_generation()
            return False
        g.update(stage='RIG', made=0, time=time.perf_counter())
        return True
    if g["stage"] != 'RIG' and rig_parts() is None:
        g["stage"] = 'RIG'   # (an undo took the preview scene away: make it again for the items left)
    try:
        if g["stage"] == 'RIG':
            teardown_rig()
            make_rig()
            g["maps"] = sorted(set().union(*(maps_of(e.item) for e in g["jobs"])))
            g["stage"] = 'MAPS'
        elif g["stage"] == 'MAPS':
            if g["maps"]:
                scene, ob, _mat, ctx = rig_parts()
                with rig_override(scene, ob):
                    T.ensure_maps(ctx, ob, [g["maps"].pop(0)])
            else:
                g["stage"] = 'JOBS'
        elif g["jobs"]:
            entry = g["jobs"].pop(0)
            try:
                render_entry(entry)
                g["made"] += 1
            except Exception as err:   # a damaged item or a failed render: no thumbnail for this one, the others go on
                if isinstance(err, RuntimeError):
                    print("Library: no thumbnail for %s (%s)" % (entry.ref, err))
                else:
                    traceback.print_exc()
                g["failed"].add(entry.ref)
            redraw_library()
        else:
            finish_generation()
            return False
    except Exception:
        traceback.print_exc()
        g["failed"].update(e.ref for e in g["jobs"])
        finish_generation()
        return False
    return True


def generate_pending():
    """Make every missing thumbnail now (the timer does the same, a step at a time). -> how many were made"""
    _gen.update(running=True, stage=None, made=0)
    while step():
        pass
    return _gen["made"]


def _tick():
    if bpy.app.is_job_running('RENDER') or bpy.app.is_job_running('OBJECT_BAKE'):
        return 1.0   # (a render or a bake of the user's own: later)
    return 0.1 if step() else None


def start_thumbnails():
    """Start making the missing thumbnails, a step at a time (called when the Library is drawn; once, and again after
    a new item)."""
    g = _gen
    if g["running"] or g["done"] or not library_dir():
        return
    g.update(running=True, stage=None)
    bpy.app.timers.register(_tick, first_interval=0.5)


# Icons: the thumbnail files as preview icons; a shaded disc in the item's color while its thumbnail is made.

_icons = [None]


def icons():
    if _icons[0] is None:
        _icons[0] = bpy.utils.previews.new()
    return _icons[0]


def look_of(item):
    """(linear base color, metallic, roughness) a material item mostly looks like: its first fill with a color."""
    fills = []

    def walk(spec):
        for kid in spec.get("layers", ()):
            walk(kid)
        if spec.get("kind") == 'FILL' and isinstance(spec.get("channels", {}).get("BASE_COLOR"), list):
            fills.append(spec)
    try:
        walk(item["layer"])
        base = next((f for f in fills if not f.get("mask")), fills[0] if fills else None)
        channels = base["channels"] if base else {}
        color = [float(c) for c in channels.get("BASE_COLOR", [0.3, 0.3, 0.3])[:3]]
        return color, float(channels.get("METALLIC") or 0.0), float(channels.get("ROUGHNESS") or 0.5)
    except (KeyError, TypeError, ValueError, AttributeError):   # (a damaged item still gets a tile)
        return [0.3, 0.3, 0.3], 0.0, 0.5


def disc_pixels(color, metal, rough, n=64):
    """A shaded disc (diffuse and a highlight) as n x n RGBA floats: the tile of an item whose thumbnail is not made yet."""
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2.0 - 1.0   # (the first row of an icon is its bottom)
    r2 = x * x + y * y
    z = np.sqrt(np.clip(1.0 - r2, 0.0, 1.0))
    light = np.array([-0.4, 0.5, 0.77])
    light /= np.linalg.norm(light)
    half = light + np.array([0.0, 0.0, 1.0])
    half /= np.linalg.norm(half)
    n_dot_l = np.clip(x * light[0] + y * light[1] + z * light[2], 0.0, 1.0)
    n_dot_h = np.clip(x * half[0] + y * half[1] + z * half[2], 0.0, 1.0)
    spec = (n_dot_h ** min(2.0 / max(rough * rough, 0.02), 200.0))[..., None] * (1.0 - 0.6 * rough)
    base = np.array(color, np.float32)
    out = np.ones((n, n, 4), np.float32)
    out[..., :3] = L.to_srgb(base * (1.0 - metal * 0.8) * (0.25 + 0.75 * n_dot_l[..., None])
                             + spec * (base * metal + (1.0 - metal) * 0.8))
    out[..., 3] = np.clip((0.96 - np.sqrt(r2)) * n * 0.5, 0.0, 1.0)
    return out


def placeholder_icon(entry):
    coll, key = icons(), "ph:" + entry.ref
    if key not in coll:
        color, metal, rough = look_of(entry.item) if entry.item["type"] == 'MATERIAL' else ([0.2, 0.2, 0.2], 0.0, 0.6)
        thumb = coll.new(key)
        thumb.image_size = (64, 64)
        thumb.image_pixels_float.foreach_set(np.ascontiguousarray(disc_pixels(color, metal, rough), np.float32).ravel())
    return coll[key].icon_id


def thumb_icon(entry):
    """Icon id of the item's thumbnail; the placeholder while it is not made. (The pixels are copied into the preview:
    a preview loaded from a file is only read when it is first drawn, which leaves its first draw empty.)"""
    coll, path = icons(), thumb_path(entry)
    key = "t:%s:%d" % (entry.ref, _version.get(entry.ref, 0))
    if key not in coll and path and os.path.isfile(path):
        try:
            image = bpy.data.images.load(path, check_existing=False)
        except RuntimeError:
            return placeholder_icon(entry)
        try:
            w, h = image.size
            px = np.empty(len(image.pixels), np.float32)
            image.pixels.foreach_get(px)
        finally:
            bpy.data.images.remove(image)
        thumb = coll.new(key)
        thumb.image_size = (w, h)
        thumb.image_pixels_float.foreach_set(px)
    return coll[key].icon_id if key in coll else placeholder_icon(entry)


# -----------------------------------------------------------------------------
# Operators

def usable_material(ob):
    """The mesh's active material (a new one when it has none), which has to be a Principled BSDF the layers plug into."""
    if ob.active_material is None:
        bpy.ops.m3d.tex_add_material()
    mat = ob.active_material
    if mat is None or L.principled_of(mat) is None:
        raise RuntimeError("Layers need a Principled BSDF in the material")
    return mat


class M3D_OT_library_apply(Operator):
    """Apply a library item to the active mesh: a material is added as a new folder on top of the layer stack, a mask
    preset goes to the active layer's mask"""
    bl_idname = "m3d.library_apply"
    bl_label = "Apply Library Item"
    bl_options = {'UNDO'}

    item: StringProperty(options={'SKIP_SAVE'}, description="Which item: starter:<name> or user:<name>")
    mode: EnumProperty(name="Mask", default='REPLACE', items=(
        ('REPLACE', "Replace", "Use the preset instead of the layer's mask"),
        ('ADD', "Add on Top", "Add the preset's effects above the layer's mask: they combine with it")))

    @classmethod
    def description(cls, _context, props):
        entry = find_entry(props.item)
        if entry is None:
            return "Apply a library item"
        mask = entry.item["type"] == 'MASK'
        return "%s: %s. %s" % (entry.item["name"], entry.item.get("description") or ("Mask preset" if mask else "Material"),
                               "Goes to the active layer's mask" if mask else "Added as a new folder on top of the layers")

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        entry = find_entry(self.item)
        if entry is None:
            self.report({'WARNING'}, "That item is not in the library any more")
            return {'CANCELLED'}
        ob, old = mesh_of(context), []
        try:
            if entry.item["type"] == 'MATERIAL':
                mat = usable_material(ob)
                what = "the folder " + apply_material(context, ob, mat, entry.item, entry.directory)
            else:
                mat = ob.active_material
                layer = L.active_layer(mat) if mat is not None else None
                if layer is None or L.in_frozen(layer):
                    raise RuntimeError("Pick a layer that is not frozen: a mask preset goes to the active layer")
                old = apply_mask(context, ob, mat, entry.item, entry.directory, self.mode == 'REPLACE')
                what = "the mask of " + layer.name
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        L.refresh(context, mat)
        L.release(old)
        self.report({'INFO'}, "Added %s" % what if entry.item["type"] == 'MATERIAL' else "Set %s" % what)
        return {'FINISHED'}


class M3D_OT_library_save(Operator):
    """Save the active layer (a folder with everything in it) as a material of your library, or its mask as a mask
    preset"""
    bl_idname = "m3d.library_save"
    bl_label = "Save to Library"

    kind: EnumProperty(items=(('MATERIAL', "Material", "The active layer or folder"), ('MASK', "Mask", "The active layer's mask")),
                       options={'SKIP_SAVE'})
    name: StringProperty(name="Name", default="")

    @classmethod
    def description(cls, _context, props):
        return ("Save the active layer's mask effects as a mask preset in your library" if props.kind == 'MASK' else
                "Save the active layer, or the active folder with its layers, as a material in your library")

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        mat = ob.active_material if ob is not None else None
        return mat is not None and L.principled_of(mat) is not None and L.active_layer(mat) is not None

    def invoke(self, context, _event):
        layer = L.active_layer(mesh_of(context).active_material)
        if self.kind == 'MASK' and not layer.mask_stack:
            self.report({'WARNING'}, "The active layer has no mask")
            return {'CANCELLED'}
        self.name = layer.name + (" Mask" if self.kind == 'MASK' else "")
        return context.window_manager.invoke_props_dialog(self, confirm_text="Save")

    def execute(self, context):
        layer = L.active_layer(mesh_of(context).active_material)
        name, files = self.name.strip()[:60], Files()
        if not name:
            self.report({'WARNING'}, "Give the item a name")
            return {'CANCELLED'}
        if self.kind == 'MASK' and not layer.mask_stack:
            self.report({'WARNING'}, "The active layer has no mask")
            return {'CANCELLED'}
        try:
            item = (describe_mask if self.kind == 'MASK' else describe_material)(name, layer, files)
            save_user_item(item, files)
        except RuntimeError as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        self.report({'INFO'}, "Saved %s to your library (Mine)" % name)
        return {'FINISHED'}


def user_entry(ref):
    """A user item by ref (None for anything else: the starter items are read-only)."""
    return next((e for e in user_entries() if e.ref == ref), None)


class M3D_OT_library_rename(Operator):
    """Rename one of your library items"""
    bl_idname = "m3d.library_rename"
    bl_label = "Rename Library Item"
    bl_options = {'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})
    name: StringProperty(name="Name")

    def invoke(self, context, _event):
        entry = user_entry(self.item)
        if entry is None:
            self.report({'WARNING'}, "Only your own items can be renamed")
            return {'CANCELLED'}
        self.name = entry.item["name"]
        return context.window_manager.invoke_props_dialog(self, confirm_text="Rename")

    def execute(self, context):
        entry, name = user_entry(self.item), self.name.strip()[:60]
        if entry is None or not name:
            self.report({'WARNING'}, "Only your own items can be renamed, to a name")
            return {'CANCELLED'}
        item = dict(entry.item, name=name)
        if item["type"] == 'MATERIAL':
            item["layer"] = dict(item["layer"], name=name)
        try:
            with open(os.path.join(entry.directory, "item.json"), "w", encoding="utf-8") as fh:
                json.dump(item, fh, indent=1)
        except OSError as err:
            self.report({'ERROR'}, "Can't write to the library: %s" % err)
            return {'CANCELLED'}
        _user["entries"] = None
        return {'FINISHED'}


class M3D_OT_library_delete(Operator):
    """Delete one of your library items (the starter items cannot be deleted)"""
    bl_idname = "m3d.library_delete"
    bl_label = "Delete Library Item"
    bl_options = {'INTERNAL'}

    item: StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, _context):
        entry = user_entry(self.item)
        root = os.path.normpath(user_root())
        if entry is None or os.path.dirname(os.path.normpath(entry.directory)) != root:
            self.report({'WARNING'}, "Only your own items can be deleted")
            return {'CANCELLED'}
        shutil.rmtree(entry.directory, ignore_errors=True)
        _user["entries"] = None
        return {'FINISHED'}


class M3D_OT_library_refresh(Operator):
    """Make the previews again (and read your items from the library folder again)"""
    bl_idname = "m3d.library_refresh"
    bl_label = "Refresh Previews"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        _user["entries"] = None
        _gen["failed"].clear()
        for e in entries():
            path = thumb_path(e)
            if path and os.path.isfile(path):
                os.remove(path)
        icons().clear()
        _gen["done"] = False
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# The tab

CATEGORIES = (('MATERIALS', "Materials", "Whole layer setups: added as a folder on top of the layers"),
              ('MASKS', "Masks", "Mask presets for the active layer"),
              ('BRUSHES', "Brushes", "The texture paint brushes"),
              ('ALPHAS', "Alphas", "Stamp textures for the active brush"),
              ('MINE', "Mine", "The items you saved"))


class M3D_LibrarySettings(PropertyGroup):
    """Scene.m3d_library: what the Library tab shows."""
    category: EnumProperty(name="Category", default='MATERIALS', items=CATEGORIES)
    search: StringProperty(name="Search", options={'TEXTEDIT_UPDATE'}, description="Show the items whose name has this text")
    mask_mode: EnumProperty(name="Mask Presets", default='REPLACE', items=(
        ('REPLACE', "Replace", "A preset replaces the layer's mask"),
        ('ADD', "Add on Top", "A preset is added above the layer's mask: they combine")))


def matching(items, text, name=lambda x: x):
    return [x for x in items if text.lower() in name(x).lower()]


def tile_rows(layout, context, cells, min_px=58):
    """Square tiles with the name under each one. `cells` are (name, draw) pairs: draw(flow) adds the tile's button to
    the grid row (the buttons are children of the grid, which is what makes an icon-only button fill its cell). Row by
    row: a grid of tiles, a grid of names; the last row is padded so its tiles are as wide as the others."""
    ui_scale = context.preferences.system.ui_scale or 1.0   # 0 without a window
    avail = (context.region.width if context.region else 300) - 24 * ui_scale
    columns = min(max(int(avail // (min_px * ui_scale)), 3), 8)
    for i in range(0, len(cells), columns):
        row = cells[i:i + columns]
        tiles = layout.grid_flow(row_major=True, columns=columns, even_columns=True, even_rows=True, align=True)
        tiles.scale_y = avail / columns / (20 * ui_scale)
        names = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=True)
        for name, draw in row:
            draw(tiles)
            names.label(text=name)
        for _pad in range(columns - len(row)):
            tiles.label(text="")
            names.label(text="")


def item_tiles(layout, context, s, found):
    if not found:
        layout.label(text="Nothing here")
        return

    def cell(entry):
        def draw(flow):
            o = flow.operator("m3d.library_apply", text="", icon_value=thumb_icon(entry))
            o.item, o.mode = entry.ref, s.mask_mode
        return entry.item["name"], draw
    tile_rows(layout, context, [cell(e) for e in found])


def draw_mask_mode(layout, context, s):
    layout.row(align=True).prop(s, "mask_mode", expand=True)
    mat = mesh_of(context).active_material if mesh_of(context) is not None else None
    layer = L.active_layer(mat) if mat is not None else None
    if layer is None:
        reason(layout, "Pick a layer: a preset goes to its mask")
    elif L.in_frozen(layer):
        reason(layout, "That layer is frozen with its folder")


def draw_materials(layout, context, s):
    if mesh_of(context) is None:
        reason(layout, "Select a mesh to apply a material")
    item_tiles(layout, context, s, matching([e for e in STARTERS if e.item["type"] == 'MATERIAL'], s.search,
                                            lambda e: e.item["name"]))
    reason(layout, "A click adds the material as a folder on top of the layers")


def draw_masks(layout, context, s):
    draw_mask_mode(layout, context, s)
    item_tiles(layout, context, s, matching([e for e in STARTERS if e.item["type"] == 'MASK'], s.search,
                                            lambda e: e.item["name"]))
    reason(layout, "Generators bake their maps once (Rebake Maps in the Mask panel)")


def draw_brushes(layout, context, s):
    if context.mode != 'PAINT_TEXTURE':
        reason(layout, "Enter Texture Paint Mode to pick a brush")
        return
    BrushAssetShelf.draw_popup_selector(layout, context, T.paint_settings(context).brush)
    shown = matching((*T.BRUSHES, *T.MORE_BRUSHES), s.search, lambda b: b[0])
    icons_ = S.brush_icons(T.BRUSH_ASSET, [name for _label, name in shown])
    active = S.active_brush_id(context)

    def cell(label, name):
        def draw(flow):
            icon = icons_.get(name, 0)
            flow.operator("m3d.brush_pick", text="" if icon else label, icon_value=icon,
                          depress=T.BRUSH_ASSET + name == active).identifier = T.BRUSH_ASSET + name
        return label, draw
    tile_rows(layout, context, [cell(label, name) for label, name in shown])
    reason(layout, "Favorites: in the brush library above")


def draw_alphas(layout, context, s):
    brush = T.paint_settings(context).brush if context.mode == 'PAINT_TEXTURE' else None
    if brush is None:
        reason(layout, "Enter Texture Paint Mode to pick an alpha")
        return
    names = matching(S.alpha_names(), s.search)
    icons_ = S.alpha_icons(names)
    active = brush.mask_texture.name if brush.mask_texture else ""

    def cell(name):
        def draw(flow):
            flow.operator("m3d.alpha_pick", text="" if name in icons_ else name or "None", icon_value=icons_.get(name, 0),
                          depress=active == name).name = name
        return name or "None", draw
    tile_rows(layout, context, [cell(n) for n in ([] if s.search else [""]) + names])
    layout.operator("m3d.alpha_load", text="Load Alpha...", icon='FILE_FOLDER')
    reason(layout, "The alpha is the brush's Texture Mask: angle and mapping in the Brush tab")


def draw_mine(layout, context, s):
    ob = mesh_of(context)
    mat = ob.active_material if ob is not None else None
    layer = L.active_layer(mat) if mat is not None and L.principled_of(mat) is not None else None
    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.enabled = layer is not None
    sub.operator("m3d.library_save", text="Save Layer", icon='ADD').kind = 'MATERIAL'
    sub = row.row(align=True)
    sub.enabled = layer is not None and bool(layer.mask_stack)
    sub.operator("m3d.library_save", text="Save Mask", icon='ADD').kind = 'MASK'
    mine = matching(user_entries(), s.search, lambda e: e.item["name"])
    materials, masks = [e for e in mine if e.item["type"] == 'MATERIAL'], [e for e in mine if e.item["type"] == 'MASK']
    if materials:
        layout.label(text="Materials")
        item_tiles(layout, context, s, materials)
    if masks:
        layout.label(text="Mask presets")
        draw_mask_mode(layout, context, s)
        item_tiles(layout, context, s, masks)
    if not mine:
        reason(layout, "Nothing saved yet: Save Layer keeps the active layer or folder, Save Mask its mask")


DRAW = {'MATERIALS': draw_materials, 'MASKS': draw_masks, 'BRUSHES': draw_brushes, 'ALPHAS': draw_alphas, 'MINE': draw_mine}


class _Lib(_PagePanel):
    page = "tex_library"


class PROPERTIES_PT_m3d_lib_browse(_Lib, Panel):
    bl_label = "Library"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.m3d_library
        start_thumbnails()
        layout.row().prop(s, "category", expand=True)
        layout.prop(s, "search", icon='VIEWZOOM', text="")
        DRAW[s.category](layout, context, s)


class PROPERTIES_PT_m3d_lib_manage(_Lib, Panel):
    bl_label = "Your Items"

    @classmethod
    def page_poll(cls, context):
        return context.scene.m3d_library.category == 'MINE' and bool(user_entries())

    def draw(self, context):
        layout = self.layout
        for entry in matching(user_entries(), context.scene.m3d_library.search, lambda e: e.item["name"]):
            row = layout.row(align=True)
            row.label(text=entry.item["name"], icon='MATERIAL' if entry.item["type"] == 'MATERIAL' else 'MOD_MASK')
            row.operator("m3d.library_rename", text="", icon='GREASEPENCIL').item = entry.ref
            row.operator("m3d.library_delete", text="", icon='X').item = entry.ref
        layout.operator("m3d.library_refresh", icon='FILE_REFRESH')


class PROPERTIES_PT_m3d_lib_assets(_Lib, Panel):
    """The materials of this file that are marked as assets (applied as Blender materials, replacing the slot): only
    there when the file has some."""
    bl_label = "Material Assets"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def page_poll(cls, context):
        return context.scene.m3d_library.category == 'MATERIALS' and any(m.asset_data is not None for m in bpy.data.materials)

    def draw(self, context):
        col = self.layout.column(align=True)
        for mat in [m for m in bpy.data.materials if m.asset_data is not None]:
            icon = mat.preview.icon_id if mat.preview else 0
            if icon:
                o = col.operator("m3d.tex_apply_material", text=mat.name, icon_value=icon)
            else:
                o = col.operator("m3d.tex_apply_material", text=mat.name, icon='MATERIAL')
            o.name = mat.name


# -----------------------------------------------------------------------------

@bpy.app.handlers.persistent
def load_pre(*_args):
    """A new file: the preview scene and the user's items are not this file's business any more."""
    _gen.update(running=False, stage=None, jobs=[], maps=[], done=False)
    _user["entries"] = None


@bpy.app.handlers.persistent
def save_pre(*_args):
    """Saving while the thumbnails are made (or after an undo brought the preview scene back): it must not go into
    the file."""
    if _gen["stage"] is not None or RIG in bpy.data.scenes:
        teardown_rig()
        _gen.update(stage=None)   # (the next step makes it again)


classes = (
    M3D_OT_library_apply,
    M3D_OT_library_save,
    M3D_OT_library_rename,
    M3D_OT_library_delete,
    M3D_OT_library_refresh,
    M3D_LibrarySettings,
    PROPERTIES_PT_m3d_lib_browse,
    PROPERTIES_PT_m3d_lib_manage,
    PROPERTIES_PT_m3d_lib_assets,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.m3d_library = PointerProperty(type=M3D_LibrarySettings)
    bpy.app.handlers.load_pre.append(load_pre)
    bpy.app.handlers.save_pre.append(save_pre)


def unregister():
    bpy.app.handlers.save_pre.remove(save_pre)
    bpy.app.handlers.load_pre.remove(load_pre)
    del bpy.types.Scene.m3d_library
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if _icons[0] is not None:
        bpy.utils.previews.remove(_icons[0])
        _icons[0] = None
