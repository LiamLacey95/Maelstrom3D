# SPDX-License-Identifier: GPL-2.0-or-later
"""
Screenshots of workspaces (real window, saved with bpy.ops.screen.screenshot).

    blender --factory-startup --python tools/m3d/screenshot.py -- <png prefix> [name ...]

Each name is a workspace name or kind (MODEL, SCULPT, ...); writes <prefix><name>.png and quits. Default: the first workspace.
`KIND/page` also shows that dock page (e.g. SCULPT/sculpt_mask). Setup steps (no picture): `+sphere` / `+cube` add a
mesh, `+unwrap` runs Auto Unwrap (Edit Mode, UV workspace), `+checker` toggles the checker map, `+distortion` shows
the UV Editor's distortion, `+paint` (Texture workspace: a material, four painted channels), `+bake` (bakes Normal and
AO at 128 px), `+layers` (like `+paint`, then a paint layer with a mask and a fill layer), `+fillsel` (select the fill layer), `+folders` (like `+paint`, then a folder of three layers, open, and a folder of two layers, frozen), `+monkey` (a smooth Suzanne, unwrapped; use it before `+paint`), `+masks` (`+paint`, then a rust Fill layer
whose mask is Fill, Edges, Noise and Levels, with the maps baked at 128 px), `+maskshow` (Show Mask on), `+frame` (frame the object in the 3D view), `+rig` (Rigging workspace: a cylinder bound to a spine and two legs, control shapes on the
legs, a Driven Key, a saved pose), `+rigedit` / `+rigpose` / `+rigweight` / `+rigobject` (the mode buttons), `+anim` (the rig keyed over 48 frames with a camera;
then F6 shows it in Pose Mode), `+toolkit` / `+chanbox` (the Animation dock on its pages / the Channel Box), `+inputs` (a cube with its INPUTS in the Channel Box), `+graph` / `+dope` (the
bottom editor), `+paths` (motion path of the active bone), `+animlayers` (push down + additive layer), `+animobject` (Object Mode), `+render` (Rendering workspace: a lit scene with a
camera, three lights, an HDRI and a 480 x 270 render), `+ipr` (the viewport renders: IPR), `+renderblank` (nothing selected),
`+hplp` (a low poly sword with its high poly, parked: hidden, the low poly active), `+hpwire` (Show Low Poly on), `+hpmouse` /
`+hpmenu` (the High / Low Poly menu opens at the viewport; needs --enable-event-simulate), `+retopo` (a smooth Suzanne that is the live surface, with a
low poly drawn over part of its face in Edit Mode: use it before `+angle`, `+frame` and the Modeling workspace), `+autolow` (Auto Low Poly on a smooth Suzanne, the low poly
next to the high poly, drawn with its edges), `+angle` (a three-quarter view), `+bakegroups` (three bake groups: a
sword with two floaters that is not baked, a shield that is baked and a pommel that is stale; use it before `TEXTURE/tex_bake`,
`+frame` and `TEXTURE/tex_bake` again), `+bakeresult` (like `+bakegroups`, then Bake All, a normal-mapped material on each low poly and
the sword's normal map in the paint view).
"""

import sys
from types import SimpleNamespace

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
PREFIX, NAMES = args[0], args[1:] or [None]
steps = []


def distortion():
    area = next(a for a in bpy.context.window_manager.windows[0].screen.areas if a.type == 'IMAGE_EDITOR')
    area.spaces.active.uv_editor.show_stretch = True


def paint():
    import numpy as np
    bpy.ops.m3d.tex_add_material()
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    bpy.context.scene.m3d_tex.resolution = '512'
    for channel in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL', 'BASE_COLOR'):
        bpy.ops.m3d.tex_channel(channel=channel)
    from m3d_texture import channel_slots
    base = channel_slots(bpy.context.active_object.active_material)['BASE_COLOR'][1]
    ramp = np.linspace(0.0, 1.0, 512, dtype=np.float32)
    px = np.ones((512, 512, 4), np.float32)
    px[..., 0], px[..., 1], px[..., 2] = 0.8, 0.25 + 0.5 * ramp[None, :], 0.1 + 0.2 * ramp[:, None]
    base.pixels.foreach_set(px.ravel())
    base.update()


def layers():
    import numpy as np
    import m3d_layers as L
    paint()
    mat = bpy.context.active_object.active_material
    bpy.ops.m3d.layer_add(kind='PAINT')
    stripes = mat.m3d_layers[1]
    stripes.name, stripes.blend, stripes.opacity = "Scratches", 'MULTIPLY', 0.8
    image = L.entry_of(stripes, 'BASE_COLOR').image
    n = image.size[0]
    ys, xs = np.mgrid[0:n, 0:n]
    px = np.zeros((n, n, 4), np.float32)
    px[..., :3] = 0.25
    px[..., 3] = (((xs + ys) // 24) % 3 == 0)
    L.write_pixels(image, px)
    bpy.ops.m3d.layer_mask_add(fill='WHITE')
    mask = L.paint_effect(mat.m3d_layers[1]).image
    ramp = np.ones((n, n, 4), np.float32)
    ramp[..., :3] = np.clip(1.6 - 1.6 * xs[..., None] / n, 0.0, 1.0)
    L.write_pixels(mask, ramp)
    bpy.ops.m3d.layer_add(kind='FILL')
    tint = mat.m3d_layers[2]
    tint.name, tint.blend, tint.opacity = "Tint", 'OVERLAY', 0.6
    tint.channels[0].color = (0.1, 0.45, 0.9, 1.0)
    mat.m3d_layer_index = 1


def folders():
    import numpy as np
    import m3d_layers as L
    paint()
    mat = bpy.context.active_object.active_material

    def named(name):
        return next(l for l in mat.m3d_layers if l.name == name)

    def new(kind, name, **props):
        bpy.ops.m3d.layer_add(kind=kind)
        layer = L.active_layer(mat)
        layer.name = name
        for key, value in props.items():
            setattr(layer, key, value)
        return layer

    def pattern(name, rgb, period, share):
        image = L.entry_of(named(name), 'BASE_COLOR').image
        n = image.size[0]
        ys, xs = np.mgrid[0:n, 0:n]
        px = np.zeros((n, n, 4), np.float32)
        px[..., :3] = rgb
        px[..., 3] = (((xs + ys) // period) % 3 == 0) * share
        L.write_pixels(image, px)

    new('PAINT', "Scratches", blend='MULTIPLY', opacity=0.8)
    pattern("Scratches", 0.2, 24, 1.0)
    new('FILL', "Tint", blend='OVERLAY', opacity=0.6).channels[0].color = (0.1, 0.45, 0.9, 1.0)
    new('PAINT', "Stains", opacity=0.7)
    pattern("Stains", (0.35, 0.22, 0.1), 61, 0.8)
    bpy.ops.m3d.layer_folder_add()
    weathering = L.active_layer(mat)
    weathering.name, weathering.opacity = "Weathering", 0.85
    for name in ("Scratches", "Tint", "Stains"):
        L.move_into(mat, named(name), named("Weathering"))
    new('PAINT', "Stripes", opacity=0.9)
    pattern("Stripes", (0.9, 0.85, 0.2), 40, 1.0)
    new('PAINT', "Logo")
    pattern("Logo", (0.95, 0.95, 0.95), 97, 1.0)
    bpy.ops.m3d.layer_folder_add()
    named("Folder").name = "Decals"
    for name in ("Stripes", "Logo"):
        L.move_into(mat, named(name), named("Decals"))
    mat.m3d_layer_index = L.index_of(mat, named("Decals").uid)
    bpy.ops.m3d.layer_freeze()
    mat.m3d_layer_index = L.index_of(mat, named("Weathering").uid)


def fillsel():
    bpy.context.active_object.active_material.m3d_layer_index = 2


def monkey():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_monkey_add()
    bpy.ops.object.shade_smooth()
    bpy.ops.m3d.tex_unwrap()


def masks():
    import m3d_layers as L
    paint()
    ob = bpy.context.active_object
    mat = ob.active_material
    ob.m3d_bake.resolution, ob.m3d_bake.samples = '128', 16
    bpy.ops.m3d.layer_add(kind='FILL')
    import numpy as np
    base = L.entry_of(mat.m3d_layers[0], 'BASE_COLOR').image
    L.write_pixels(base, np.tile(np.array([0.55, 0.62, 0.7, 1.0], np.float32), (base.size[0] * base.size[1], 1)))
    rust = mat.m3d_layers[-1]
    rust.name = "Rust"
    rust.channels[0].color = (0.32, 0.1, 0.03, 1.0)
    bpy.ops.m3d.mask_effect_add(kind='FILL')
    bpy.ops.m3d.mask_effect_add(kind='EDGES')
    bpy.ops.m3d.mask_effect_add(kind='NOISE')
    bpy.ops.m3d.mask_effect_add(kind='LEVELS')
    fill, edges, noise, levels = rust.mask_stack
    edges.blend, edges.amount, edges.softness = 'ADD', 0.75, 0.25
    noise.scale, noise.noise_contrast, noise.detail = 9.0, 3.5, 4.0
    levels.black_in, levels.white_in = 0.25, 0.7
    rust.mask_index = 1


def maskshow():
    bpy.context.active_object.active_material.m3d_show_mask = True


def frame():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
                bpy.ops.view3d.view_all(center=True)


def angle():
    """A three-quarter view in the 3D views (then `+frame` fits the model)."""
    from mathutils import Euler
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            r3d = area.spaces.active.region_3d
            r3d.view_perspective = 'PERSP'
            r3d.view_rotation = Euler((1.15, 0.0, 0.5)).to_quaternion()
    frame()


def rig():
    import bmesh
    import m3d_rig as R
    from mathutils import Vector
    bpy.ops.m3d.add_primitive(kind='CYLINDER')
    body = bpy.context.active_object
    body.name = "Body"
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24, radius1=0.32, radius2=0.32, depth=2.0,
                          matrix=__import__("mathutils").Matrix.Translation((0, 0, 1.0)))
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.5], cuts=8, use_grid_fill=True)
    bm.to_mesh(body.data)
    bm.free()
    body.data.shade_smooth()
    rig_ob = R.new_armature(bpy.context, "Armature")
    R.leave_modes(bpy.context)
    R._select_only(bpy.context, rig_ob)
    bpy.ops.object.mode_set(mode='EDIT')
    rig_ob.data.use_mirror_x = True
    for base, points in (("Spine", [(0, 0, 0.9), (0, 0, 1.2), (0, 0, 1.55), (0, 0, 1.9)]),
                         ("Leg", [(0.15, 0, 0.9), (0.15, -0.05, 0.5), (0.15, 0, 0.08)])):
        chain = R.JointChain(rig_ob.name, base)
        for p in points:
            chain.add(Vector(p))
        if base == "Leg":
            chain.mirror()
    rig_ob.data.use_mirror_x = False
    R.orient_bones(rig_ob, list(rig_ob.data.edit_bones), '-Y', 'Z')
    bpy.ops.object.mode_set(mode='OBJECT')
    R._select_only(bpy.context, body)
    bpy.context.scene.m3d_rig.skin_method = 'AUTO'
    R.bind(bpy.context, rig_ob, [body], 'AUTO')
    bpy.ops.m3d.rig_mode(mode='POSE')
    for name in ("Leg.L", "Leg.R"):
        for pb in rig_ob.pose.bones:
            pb.select = pb.name == name
        rig_ob.data.bones.active = rig_ob.data.bones[name]
        bpy.ops.m3d.rig_control(shape='CIRCLE')
    for name in ("Leg.001.L", "Leg.001.R"):
        pb = rig_ob.pose.bones[name]
        pb.rotation_mode = 'XYZ'
    s = bpy.context.scene.m3d_rig
    s.dk_driver_object, s.dk_driver_bone, s.dk_driver_channel = rig_ob, "Leg.001.L", 'ROT_X'
    s.dk_driven_object, s.dk_driven_bone, s.dk_driven_channel = rig_ob, "Leg.L", 'SCL_Y'
    s.dk_interp = 'LINEAR'
    for angle, value in ((0.0, 1.0), (1.2, 1.4)):
        rig_ob.pose.bones["Leg.001.L"].rotation_euler[0] = angle
        s.dk_value = value
        bpy.ops.m3d.rig_driven_key(action='KEY')
    rig_ob.pose.bones["Leg.001.L"].rotation_euler[0] = 0.6
    for pb in rig_ob.pose.bones:
        pb.select = pb.name in {"Leg.001.L", "Leg.001.R"}
    rig_ob.data.bones.active = rig_ob.data.bones["Leg.001.L"]
    bpy.ops.m3d.rig_pose_save()
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    win = bpy.context.window_manager.windows[0]
    view = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    with bpy.context.temp_override(window=win, screen=win.screen, area=view, region=next(r for r in view.regions if r.type == 'WINDOW')):
        bpy.ops.view3d.view_all(center=False)


def anim():
    """The Rigging test rig, keyed over 48 frames (legs swing, spine twists, a breakdown), with a camera."""
    rig()
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 48
    bpy.ops.object.camera_add(location=(5.0, -6.0, 2.4), rotation=(1.3, 0, 0.84))
    scene.camera = bpy.context.active_object
    rig_ob = bpy.data.objects["Armature"]
    bpy.context.view_layer.objects.active = rig_ob
    bpy.ops.m3d.rig_mode(mode='POSE')
    for pb in rig_ob.pose.bones:
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (0, 0, 0)
    rig_ob.pose.bones["Spine.001"]["IK_FK"] = 0.5
    swing = ((1, 0.0), (13, 0.7), (25, 0.0), (37, -0.7), (48, 0.0))
    for name, sign in (("Leg.L", 1), ("Leg.R", -1)):
        pb = rig_ob.pose.bones[name]
        for frame, angle in swing:
            pb.rotation_euler[0] = angle * sign
            pb.keyframe_insert("rotation_euler", index=0, frame=frame)
    for name in ("Leg.001.L", "Leg.001.R"):
        pb = rig_ob.pose.bones[name]
        for frame, angle in swing:
            pb.rotation_euler[0] = max(0.0, -angle) * 1.2
            pb.keyframe_insert("rotation_euler", index=0, frame=frame)
    spine = rig_ob.pose.bones["Spine.002"]
    for frame, angle in ((1, 0.0), (25, 0.35), (48, 0.0)):
        spine.rotation_euler[2] = angle
        spine.keyframe_insert("rotation_euler", index=2, frame=frame)
        spine.location[0] = angle * 0.2
        spine.keyframe_insert("location", index=0, frame=frame)
    fc = next(f for f in rig_ob.animation_data.action.layers[0].strips[0].channelbags[0].fcurves if "Leg.L" in f.data_path)
    key = fc.keyframe_points.insert(7, 0.35, keyframe_type='BREAKDOWN')
    key.type = 'BREAKDOWN'
    for pb in rig_ob.pose.bones:
        pb.select = pb.name in {"Leg.L", "Leg.001.L"}
    rig_ob.data.bones.active = rig_ob.data.bones["Leg.001.L"]
    scene.frame_set(18)
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    bpy.context.view_layer.objects.active = rig_ob
    scene.m3d_anim.sets.add().name = "Legs"
    scene.m3d_anim.sets[0].items.add().object = rig_ob


def anim_editor(editor):
    return lambda: bpy.ops.m3d.anim_editor(editor=editor)


def anim_dock(context_name):
    def run():
        for area in bpy.context.window_manager.windows[0].screen.areas:
            if area.type == 'PROPERTIES':
                area.spaces.active.context = context_name
    return run


def inputs():
    bpy.ops.m3d.add_primitive(kind='CUBE')
    inp = bpy.context.active_object.m3d_input
    inp.width, inp.sub_width, inp.sub_height = 2, 3, 2
    anim_dock('CHANNEL_BOX')()


def anim_paths():
    bpy.ops.m3d.anim_paths(action='CALCULATE')


def anim_layers():
    rig_ob = bpy.data.objects["Armature"]
    bpy.ops.m3d.rig_mode(mode='OBJECT')
    bpy.context.view_layer.objects.active = rig_ob
    bpy.ops.m3d.anim_layer(action='ADD_ADDITIVE')
    pb = rig_ob.pose.bones["Spine.002"]
    pb.rotation_euler[2] = 0.5
    pb.keyframe_insert("rotation_euler", index=2, frame=10)


def render():
    """A small lit scene: floor, three objects with materials, a camera, key / fill / rim lights, an HDRI, a render."""
    import math
    import m3d_render
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)

    def material(name, color, metallic, roughness):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        return mat

    bpy.ops.mesh.primitive_plane_add(size=12)
    bpy.context.active_object.name = "Floor"
    bpy.context.active_object.data.materials.append(material("Floor", (0.55, 0.55, 0.6, 1), 0.0, 0.5))
    for name, make, loc, mat in (
            ("Ball", lambda: bpy.ops.mesh.primitive_uv_sphere_add(radius=0.9, location=(-1.8, 0, 0.9)), None, material("Ball", (0.9, 0.2, 0.15, 1), 1.0, 0.25)),
            ("Head", lambda: bpy.ops.mesh.primitive_monkey_add(size=1.6, location=(0, 0, 0.8)), None, material("Head", (0.85, 0.7, 0.4, 1), 0.0, 0.4)),
            ("Block", lambda: bpy.ops.mesh.primitive_cube_add(size=1.4, location=(1.9, 0.2, 0.7)), None, material("Block", (0.2, 0.55, 0.3, 1), 0.0, 0.7))):
        make()
        ob = bpy.context.active_object
        ob.name = name
        bpy.ops.object.shade_smooth()
        ob.data.materials.append(mat)
    bpy.ops.object.camera_add(location=(5.5, -6.5, 3.2), rotation=(math.radians(68), 0, math.radians(40)))
    scene.camera = bpy.context.active_object
    scene.camera.name = "ShotCamera"
    scene.camera.data.dof.use_dof = True
    scene.camera.data.dof.focus_object = bpy.data.objects["Head"]
    scene.camera.data.show_composition_thirds = True
    scene.cursor.location = (0, 0, 0)
    for kind, name, pos, power, color in (('AREA', "Key", (3, -2, 4), 900.0, (1.0, 0.85, 0.7)), ('POINT', "Fill", (-4, -3, 2), 400.0, (0.55, 0.7, 1.0)),
                                          ('SPOT', "Rim", (-1, 4, 4), 1200.0, (1.0, 1.0, 1.0))):
        bpy.ops.m3d.render_light_add(kind=kind)
        ob = bpy.context.active_object
        ob.name, ob.location = name, pos
        ob.data.energy, ob.data.color = power, color
        if kind == 'AREA':
            ob.data.size = 3.0
    bpy.ops.m3d.render_light(name="Rim", action='VISIBLE')   # hidden: the table shows it greyed
    bpy.ops.m3d.hdri_setup()
    scene.m3d_render.hdri_strength = 0.6
    bpy.ops.m3d.render_preset(preset='MEDIUM')
    scene.render.resolution_x, scene.render.resolution_y = 480, 270
    scene.render.resolution_percentage = 100
    scene.eevee.taa_render_samples = 16
    bpy.ops.m3d.render()
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = bpy.data.objects["Head"]
    bpy.data.objects["Head"].select_set(True)
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    ws = bpy.data.workspaces["Rendering"]
    m3d_render.show_render_result(SimpleNamespace(workspace=ws, screen=ws.screens[0]))


def render_ipr():
    bpy.ops.m3d.render_ipr()
    win = bpy.context.window_manager.windows[0]
    view = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    with bpy.context.temp_override(window=win, screen=win.screen, area=view, region=next(r for r in view.regions if r.type == 'WINDOW')):
        bpy.ops.view3d.view_camera()


def render_blank():
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = None


def rig_mode(mode):
    return lambda: bpy.ops.m3d.rig_mode(mode=mode)


def sword():
    """A low poly sword (blade, guard, grip, pommel as one mesh) and its high poly (Create High Poly, 3 Multires levels), parked."""
    import bmesh
    from mathutils import Matrix
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bm = bmesh.new()
    for scale, z in (((0.16, 0.03, 1.5), 0.95), ((0.5, 0.07, 0.09), 0.18), ((0.07, 0.07, 0.4), -0.04), ((0.13, 0.13, 0.12), -0.3)):
        bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.LocRotScale((0, 0, z), None, scale))
    mesh = bpy.data.meshes.new("Sword_low")
    bm.to_mesh(mesh)
    bm.free()
    low = bpy.data.objects.new("Sword_low", mesh)
    bpy.context.scene.collection.objects.link(low)
    bpy.context.view_layer.objects.active = low
    low.select_set(True)
    bpy.ops.m3d.hp_create(detail='MULTIRES', levels=3)
    bpy.ops.object.shade_smooth()
    bpy.ops.m3d.hp_park()
    frame()


def sword_wire():
    bpy.context.scene.m3d_show_low = True


def monkey_high(subdivisions):
    """A smooth Suzanne, `subdivisions` levels, named Monkey_high."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_monkey_add()
    high = bpy.context.active_object
    high.name = "Monkey_high"
    mod = high.modifiers.new("s", 'SUBSURF')
    mod.levels = subdivisions
    bpy.ops.object.modifier_apply(modifier="s")
    bpy.ops.object.shade_smooth()
    return high


def retopo():
    """Make Live and New Low Poly on a smooth Suzanne, then a patch of quads for the low poly, each point on the surface of the
    face (rays along the direction of the `+angle` view, so the patch looks like a regular grid). Quad Draw and Edit Mode start
    from a timer a moment later."""
    import bmesh
    from mathutils import Euler, Vector
    high = monkey_high(3)
    bpy.ops.m3d.hp_new_low()
    low = bpy.context.active_object
    rot = Euler((1.15, 0.0, 0.5)).to_quaternion()
    look, right, up = rot @ Vector((0, 0, -1)), rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    centre = Vector((0.35, -0.75, 0.45))
    bm = bmesh.new()
    grid = []
    for v in (0.4, 0.13, -0.13, -0.4):
        row = []
        for u in (-0.6, -0.3, 0.0, 0.3, 0.6):
            hit, co, _no, _i = high.ray_cast(centre - look * 5 + right * u + up * v, look)
            row.append(bm.verts.new(co) if hit else None)
        grid.append(row)
    for r in range(len(grid) - 1):
        for c in range(len(grid[0]) - 1):
            quad = (grid[r][c], grid[r][c + 1], grid[r + 1][c + 1], grid[r + 1][c])
            if all(quad):
                bm.faces.new(quad)
    bm.to_mesh(low.data)
    bm.free()


def autolow():
    """Auto Low Poly (QuadriFlow, 700 faces) on a smooth Suzanne: the low poly stands next to the high poly, which stays shown,
    and is drawn with its edges."""
    high = monkey_high(3)
    bpy.ops.m3d.hp_auto_low(method='QUADRIFLOW', faces=700)
    low = bpy.context.active_object
    low.location.x += 3.0
    low.show_wire = low.show_all_edges = True
    bpy.context.view_layer.update()
    for ob in bpy.data.objects:
        ob.select_set(ob == low)


def mouse_to_viewport():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=area.x + area.width // 2 - 100, y=area.y + area.height // 2 + 80)


def sword_menu():
    """Open the High / Low Poly menu at the pointer and take its picture a moment later (a popup closes when the pointer moves)."""
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
        bpy.ops.wm.call_menu(name="M3D_MT_hplp")

    def picture():
        with bpy.context.temp_override(window=win, screen=win.screen, area=win.screen.areas[0]):
            bpy.ops.screen.screenshot(filepath="%smenu.png" % PREFIX, check_existing=False)
    bpy.app.timers.register(picture, first_interval=0.3)


def bake_groups():
    """Three groups: Sword (a low poly, a high poly and two floaters; not baked), Shield (baked) and Pommel (baked, then its
    high poly was moved: stale). The high polys are parked, the sword's low poly is active."""
    import math
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)

    def part(kind, name, x, scale, **kw):
        getattr(bpy.ops.mesh, "primitive_%s_add" % kind)(location=(x, 0, 0), **kw)
        ob = bpy.context.active_object
        ob.name, ob.scale = name, scale
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        return ob

    lows = [part("cube", "Sword_low", -1.6, (0.14, 0.05, 1.1)), part("cylinder", "Shield_low", 0.0, (0.8, 0.8, 0.07), vertices=12),
            part("uv_sphere", "Pommel_low", 1.5, (0.3, 0.3, 0.3), segments=8, ring_count=6)]
    lows[1].rotation_euler.x = math.pi / 2
    for low in lows:
        for ob in bpy.data.objects:
            ob.select_set(ob == low)
        bpy.context.view_layer.objects.active = low
        bpy.ops.m3d.hp_create(detail='MULTIRES', levels=2)
        bpy.ops.object.shade_smooth()
    for i, z in enumerate((0.5, -0.5)):
        bpy.ops.mesh.primitive_uv_sphere_add(location=(-1.6, -0.08, z), radius=0.07)
        bpy.context.active_object.name = "Sword_high_bolts"
        bpy.ops.object.shade_smooth()
    bpy.ops.m3d.hp_auto_pair()
    for low in lows:
        s = low.m3d_bake
        s.resolution, s.margin, s.samples, s.extrusion = '128', 4, 8, 0.3
    import m3d_pair
    m3d_pair.park_all(bpy.context)
    for low in lows[1:]:
        for ob in bpy.data.objects:
            ob.select_set(ob == low)
        bpy.context.view_layer.objects.active = low
        bpy.ops.m3d.bg_bake()
    bpy.data.objects["Pommel_high"].location.x += 0.04
    for ob in bpy.data.objects:
        ob.select_set(ob == lows[0])
    bpy.context.view_layer.objects.active = lows[0]
    bpy.context.view_layer.update()


def bake_result():
    """Bake All, then the low polys use their baked normal maps (Material Preview shows the detail of the high polys) and the
    paint view shows the sword's."""
    import m3d_pair
    bake_groups()
    bpy.ops.m3d.bg_bake_all()
    colors = {"Sword": (0.55, 0.57, 0.62, 1.0), "Shield": (0.5, 0.22, 0.12, 1.0), "Pommel": (0.75, 0.6, 0.2, 1.0)}
    for name, color in colors.items():
        low = bpy.data.objects[name + "_low"]
        mat = bpy.data.materials.new(name + "_Material")
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.4
        bsdf.inputs["Metallic"].default_value = 0.8
        tex, normal = nodes.new("ShaderNodeTexImage"), nodes.new("ShaderNodeNormalMap")
        tex.image = bpy.data.images[name + "_low_Normal"]
        links.new(tex.outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
        with m3d_pair.quiet(bpy.context):   # (a material is no edit of the mesh: the groups stay baked)
            low.data.materials.append(mat)

    def show():
        win = bpy.context.window_manager.windows[0]
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = bpy.data.images["Sword_low_Normal"]
    bpy.app.timers.register(show, first_interval=2.0)


def bake():
    ob = bpy.context.active_object
    ob.m3d_bake.resolution, ob.m3d_bake.samples = '128', 8
    bpy.ops.m3d.tex_bake()


SETUP = {
    "+paint": paint,
    "+bake": bake,
    "+bakegroups": bake_groups,
    "+bakeresult": bake_result,
    "+layers": layers,
    "+folders": folders,
    "+fillsel": fillsel,
    "+monkey": monkey,
    "+masks": masks,
    "+maskshow": maskshow,
    "+frame": frame,
    "+angle": angle,
    "+rig": rig,
    "+rigedit": rig_mode('EDIT'),
    "+rigpose": rig_mode('POSE'),
    "+rigweight": rig_mode('WEIGHT_PAINT'),
    "+rigobject": rig_mode('OBJECT'),
    "+anim": anim,
    "+toolkit": anim_dock('MODELING_TOOLKIT'),
    "+chanbox": anim_dock('CHANNEL_BOX'),
    "+inputs": inputs,
    "+graph": anim_editor('GRAPH'),
    "+dope": anim_editor('DOPESHEET'),
    "+paths": anim_paths,
    "+animlayers": anim_layers,
    "+animobject": lambda: bpy.ops.m3d.rig_mode(mode='OBJECT'),
    "+render": render,
    "+ipr": render_ipr,
    "+renderblank": render_blank,
    "+hplp": sword,
    "+hpwire": sword_wire,
    "+hpmouse": mouse_to_viewport,
    "+hpmenu": sword_menu,
    "+retopo": retopo,
    "+autolow": autolow,
    "+sphere": lambda: bpy.ops.m3d.add_primitive(kind='SPHERE'),
    "+cube": lambda: bpy.ops.m3d.add_primitive(kind='CUBE'),
    "+unwrap": lambda: bpy.ops.m3d.uv_auto(),
    "+checker": lambda: bpy.ops.m3d.uv_checker(),
    "+distortion": distortion,
}


def switch(name):
    wm = bpy.context.window_manager
    name, _slash, page = (name or "").partition("/")
    if not name:
        return
    if name in SETUP:
        SETUP[name]()
    elif name.isupper():
        bpy.ops.m3d.workspace(kind=name)
    else:
        wm.windows[0].workspace = bpy.data.workspaces[name]
    if page:
        from m3d_workspace import DOCK_TABS
        win = wm.windows[0]
        left = {t.page for t in DOCK_TABS[name]['LEFT']}
        setattr(win.workspace, "m3d_page_" + ("left" if page in left else "right"), page)
        for area in win.screen.areas:
            area.tag_redraw()


def shot(name):
    win = bpy.context.window_manager.windows[0]
    if name and name.startswith("+"):
        return
    with bpy.context.temp_override(window=win, screen=win.screen, area=win.screen.areas[0]):
        bpy.ops.screen.screenshot(filepath="%s%s.png" % (PREFIX, (name or "default").replace("/", "_")),
                                  check_existing=False)


for name in NAMES:
    steps.append(lambda n=name: switch(n))
    steps.append(lambda: None)  # Let the workspace change and redraw.
    steps.append(lambda: None)
    steps.append(lambda n=name: shot(n))
steps.append(bpy.ops.wm.quit_blender)


def run_next():
    steps.pop(0)()
    return 0.6 if steps else None


bpy.app.timers.register(run_next, first_interval=3.0)
