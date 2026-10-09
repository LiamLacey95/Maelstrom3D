# Self-check for Maelstrom3D's Python layer. Run: blender -b --factory-startup --python-exit-code 1 --python tools/m3d/test_m3d.py
import bpy, os, sys, tempfile
# Settings written by the tests (m3d_user.json) go to a temp folder, never to the real config.
TEST_CONFIG = tempfile.mkdtemp(prefix="m3d_test_")
os.environ["BLENDER_USER_RESOURCES"] = TEST_CONFIG
fails = []
def check(cond, msg):
    if not cond: fails.append(msg)

# Icons used in m3d_mode exist.
import re, m3d_mode
icons = set(bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items.keys())
import m3d_layers, m3d_library, m3d_marking, m3d_masks, m3d_sculpt, m3d_texture, m3d_ui as _maya_ui, m3d_uv as _maya_uv
src = "".join(open(m.__file__).read() for m in (m3d_mode, m3d_layers, m3d_library, m3d_marking, m3d_masks, m3d_sculpt, m3d_texture, _maya_ui, _maya_uv))
for ic in set(re.findall(r"icon='([A-Z_0-9]+)'", src)):
    check(ic in icons, "missing icon " + ic)

# Every Maya menu / shelf entry points at a real operator, property, menu and icon.
import m3d_ui, m3d_workspace, m3d_user

def op_ok(idname, props):
    mod, name = idname.split(".")
    try:
        rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except (KeyError, AttributeError):
        return False
    return all(k in rna.properties for k in props)

# Menus defined in C, invisible to bpy.types.
C_MENUS = {"TOPBAR_MT_file_open_recent", "OBJECT_MT_move_to_collection"}

ROOTS = {"space_data": bpy.types.SpaceView3D, "tool_settings": bpy.types.ToolSettings,
         "scene": bpy.types.Scene, "screen": bpy.types.Screen, "area": bpy.types.Area}

def path_ok(path):
    head, *rest = path.split(".")
    rna = ROOTS[head].bl_rna
    for part in rest:
        p = rna.properties.get(part)
        if p is None:
            return False
        rna = getattr(p, "fixed_type", None) or rna
    return True

for mid, (label, entries) in m3d_ui.MENUS.items():
    for e in entries:
        where = mid + ": " + e.get("label", "")
        kind = e["kind"]
        if kind == 'OP':
            check(op_ok(e["idname"], e["props"]), "bad op " + where + " " + e["idname"])
        elif kind == 'ENUM':
            check(op_ok(e["idname"], [e["prop"]]), "bad enum op " + where)
        elif kind in {'MENU', 'STOCK'} and e["idname"] not in C_MENUS:
            check(hasattr(bpy.types, e["idname"]), "bad submenu " + where + " " + e["idname"])
        elif kind == 'PROP':
            check(path_ok(e["path"]), "bad prop " + where + " " + e["path"])
        if e.get("icon", 'NONE') != 'NONE':
            check(e["icon"] in icons, "bad icon " + where + " " + e["icon"])
for _, menus in m3d_ui.MENU_SETS.values():
    for mid in menus:
        check(hasattr(bpy.types, mid), "menu set refers to missing " + mid)
for tab, (label, items, kinds) in m3d_ui.SHELVES.items():
    check(kinds and kinds <= set(m3d_workspace.KINDS), "shelf kinds " + tab)
    for it in filter(None, items):
        if callable(it):
            continue
        check(op_ok(it[0], it[2]), "bad shelf op %s %s" % (tab, it[0]))
        check(it[1] in icons, "bad shelf icon %s %s" % (tab, it[1]))

import m3d_uv
for label, items in [*m3d_mode.COMPONENT_TOOLS.values(), *m3d_uv.UV_TOOLKIT_SECTIONS]:
    for item_label, idname, icon, props in items:
        check(op_ok(idname, props), "bad tool %s / %s %s" % (label, item_label, idname))
        check(icon in icons, "bad tool icon %s / %s %s" % (label, item_label, icon))
for group in (m3d_mode.MTK_SELECT_TOOLS, m3d_mode.MTK_MESH, m3d_mode.MTK_COMPONENTS, m3d_mode.MTK_TOOLS):
    for label, idname, icon, props in group:
        check(op_ok(idname, props), "bad toolkit op %s %s" % (label, idname))
        check(icon in icons, "bad toolkit icon %s %s" % (label, icon))

# Keymap loads and overrides land.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
def find(km, idname, type, **mods):
    return [k for k in kc.keymaps[km].keymap_items if k.idname == idname and k.type == type
            and all(getattr(k, m) == v for m, v in mods.items())]
check(find("Object Mode", "wm.call_menu_pie", "RIGHTMOUSE", shift=False), "rmb pie object")
check(find("Mesh", "wm.call_menu_pie", "RIGHTMOUSE", shift=True), "shift rmb pie mesh")
check(not [k for k in kc.keymaps["Frames"].keymap_items if k.type == 'SPACE'], "space still plays")
check(find("3D View", "wm.context_set_enum", "FOUR"), "4 wireframe")
check(find("Object Mode", "m3d.smooth_preview", "THREE"), "3 smooth")
check(not find("Object Mode", "object.mode_set_with_submode", "ONE"), "1 still edit-mode")
check(find("Object Mode", "m3d.group", "G", ctrl=True), "ctrl g group")
check(find("Mesh", "mesh.select_mode", "F10"), "F10 edge")
check(find("3D View", "m3d.dock_tab", "A", ctrl=True), "ctrl a dock toggle")
check(find("Mesh", "m3d.delete_components", "DEL"), "delete components")
check(find("Mesh", "view3d.edit_mesh_extrude_move_normal", "E", ctrl=True), "ctrl e extrude")
check(find("Frames", "screen.keyframe_jump", "PERIOD", shift=False, alt=False), ". next key")
check(find("3D View", "m3d.snap_hold", "V"), "hold v snap")
check(find("3D View", "m3d.space_hotbox", "SPACE", ctrl=False), "space hotbox")
check(find("Object Mode", "m3d.pivot_hold", "D", shift=False, ctrl=False), "d pivot object")
check(find("Mesh", "m3d.pivot_hold", "D", shift=False, ctrl=False), "d pivot mesh")
check(find("Object Mode", "m3d.duplicate", "D", shift=True), "shift d duplicate with transform")
check(find("Generic Gizmo Maybe Drag", "m3d.gizmo_shift_drag", "LEFTMOUSE", shift=True, ctrl=False),
      "shift drag extrude/duplicate")
check(find("Generic Gizmo Maybe Drag", "m3d.gizmo_slide", "LEFTMOUSE", shift=True, ctrl=True), "ctrl shift drag slide")
for kind, (wname, key, mode, mset) in m3d_workspace.KINDS.items():
    item = find("Window", "m3d.workspace", key, shift=False, ctrl=False, alt=False)
    check(item and item[0].properties.kind == kind, "%s = %s workspace" % (key, kind))
    check(mset in m3d_ui.MENU_SETS, "menu set " + mset)
check(not find("Window", "wm.context_set_enum", "F2") and not find("Window", "wm.call_menu", "F1"), "old F1-F6 gone")
check(find("Mesh", "m3d.workspace", "F12")[0].properties.kind == 'UV', "F12 = UV workspace")
check(not find("Image", "image.view_zoom_ratio", "F1", shift=False, ctrl=False), "F1 is not an image zoom in the UV editor")
for km in ("Object Mode", "Mesh"):
    for key, menu in (("Q", "M3D_MT_select_mm"), ("W", "M3D_MT_move_mm"), ("E", "M3D_MT_rotate_mm"),
                      ("R", "M3D_MT_scale_mm")):
        items = find(km, "m3d.key_marking_menu", key, shift=False, ctrl=False)
        check(items and items[0].properties.menu == menu and hasattr(bpy.types, menu), f"{km} {key}+LMB marking menu")
check(find("Object Mode", "wm.call_menu_pie", "RIGHTMOUSE", shift=True), "shift rmb context menu")
check(find("3D View", "wm.call_menu_pie", "RIGHTMOUSE", ctrl=True, shift=True), "ctrl shift rmb transform menu")
check(find("3D View", "m3d.view_history", "LEFT_BRACKET"), "[ view undo")
check(find("Window", "ed.redo", "Y", ctrl=True), "ctrl y redo")
check(find("Mesh", "mesh.knife_tool", "X", ctrl=True, shift=True), "ctrl shift x multi-cut")
check(find("UV Editor", "wm.call_menu_pie", "RIGHTMOUSE", shift=False), "uv marking menu")
check(find("Mesh", "mesh.select_mode", "F11", ctrl=True), "ctrl f11 convert to faces")
ctrl_click = [k for k in kc.keymaps["3D View"].keymap_items if k.idname == "view3d.select" and k.type == 'LEFTMOUSE'
              and k.ctrl and not k.shift and not k.alt]
check(ctrl_click and ctrl_click[0].properties.deselect, "ctrl click deselects")

# Operators.
bpy.ops.m3d.reset_transformations()
bpy.ops.m3d.add_primitive(kind='CUBE')
ob = bpy.context.active_object
bpy.ops.m3d.smooth_preview(level='SMOOTH'); check("SmoothPreview" in ob.modifiers, "smooth on")
bpy.ops.m3d.smooth_preview(level='OFF'); check("SmoothPreview" not in ob.modifiers, "smooth off")
for kind in ('CUBE','SPHERE','CYLINDER','CONE','PLANE','TORUS'):
    bpy.ops.m3d.add_primitive(kind=kind)
bpy.ops.object.select_all(action='SELECT')
n = len(bpy.context.selected_objects)
bpy.ops.m3d.group()
g = bpy.context.active_object
check(g.type == 'EMPTY' and len(g.children) == n, "group children %d" % len(g.children))
gname = g.name
bpy.ops.m3d.ungroup()
check(gname not in bpy.data.objects and all(o.parent is None for o in bpy.data.objects), "ungroup")
bpy.ops.object.select_all(action='DESELECT')
a, b = [o for o in bpy.data.objects if o.type == 'MESH'][:2]
a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active = b
bpy.ops.m3d.boolean(operation='DIFFERENCE')
check(any(m.type == 'BOOLEAN' and m.object == b for m in a.modifiers), "boolean A - B")
# Maya Delete / Fill Hole on a cube.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.m3d.add_primitive(kind='CUBE')
cube = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
bpy.context.tool_settings.mesh_select_mode = (False, False, True)
bpy.ops.mesh.select_all(action='DESELECT')
import bmesh
bm = bmesh.from_edit_mesh(cube.data); bm.faces.ensure_lookup_table(); bm.faces[0].select = True
bmesh.update_edit_mesh(cube.data)
bpy.ops.m3d.delete_components()
bpy.ops.object.mode_set(mode='OBJECT')
check(len(cube.data.polygons) == 5, "delete face")
bpy.ops.m3d.fill_hole()
check(len(cube.data.polygons) == 6, "fill hole")
# Connect with Divisions (options box): 3 loops around the four vertical edges.
bpy.ops.object.mode_set(mode='EDIT')
bpy.context.tool_settings.mesh_select_mode = (False, True, False)
bm = bmesh.from_edit_mesh(cube.data)
for e in bm.edges:
    e.select_set(abs((e.verts[0].co - e.verts[1].co).normalized().z) > 0.99)
bmesh.update_edit_mesh(cube.data)
bpy.ops.m3d.connect(divisions=3)
bpy.ops.object.mode_set(mode='OBJECT')
check(len(cube.data.polygons) == 18, "connect divisions (%d faces)" % len(cube.data.polygons))
# Maya Shift+D repeats the last duplicate's offset.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.m3d.add_primitive(kind='SPHERE')
first = bpy.context.active_object
bpy.ops.m3d.duplicate()
second = bpy.context.active_object
second.location.x += 2.0
bpy.context.view_layer.update()
bpy.ops.m3d.duplicate(with_transform=True)
check(abs(bpy.context.active_object.location.x - 4.0) < 1e-4, "shift d offset")

# UV workflow: cut, unfold, layout, checker on/off.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.m3d.add_primitive(kind='CUBE')
cube = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.m3d.uv_cut()
bpy.ops.m3d.uv_unfold()
bpy.ops.object.mode_set(mode='OBJECT')
check(any(e.use_seam for e in cube.data.edges), "uv cut marks seams")
bpy.ops.m3d.uv_checker()
check(cube.data.materials[0].name == "m3dUVChecker", "checker on")
bpy.ops.m3d.uv_checker()
check(len(cube.data.materials) == 0, "checker off restores materials")
# maya.cmds and MEL in the command line.
import m3d.cmds as cmds, _console_mel
bpy.ops.object.select_all(action='DESELECT')
cube, node = cmds.polyCube(w=2, h=1, d=1, n="box")
check(cube == "box" and node.startswith("polyCube"), "cmds.polyCube names")
check(abs(bpy.data.objects["box"].dimensions.x - 2) < 1e-4, "cmds.polyCube width")
cmds.move(0, 0, 3, cube)
cmds.move(1, 0, 0, cube, r=True)
check(tuple(cmds.xform(cube, q=True, t=True)) == (1.0, 0.0, 3.0), "cmds.move absolute + relative")
cmds.setAttr(cube + ".rotateZ", 90)
check(abs(cmds.getAttr(cube + ".rz") - 90) < 1e-4, "cmds.setAttr / getAttr degrees")
grp = cmds.group(cube, n="grp1")
check(bpy.data.objects[cube].parent.name == grp, "cmds.group")
_console_mel.run("polySphere -r 2 -n ball; select -cl; select -add ball; move -r 0 0 1;")
check(bpy.data.objects["ball"].location.z == 1 and cmds.ls(sl=True) == ["ball"], "MEL run")
check(set(cmds.ls("b*")) >= {"box", "ball"}, "cmds.ls wildcard")

# Live primitive inputs (Channel Box > INPUTS): exact counts, sizes, UVs, materials, freezing, duplicate, cmds.
import m3d_inputs as I
import numpy as np
objects_before = set(bpy.data.objects)

def new_prim(kind):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.m3d.add_primitive(kind=kind)
    return bpy.context.active_object

def counts(ob):
    return len(ob.data.vertices), len(ob.data.polygons)

def expect(kind, p):
    a, h, c = p.sub_axis, p.sub_height, p.sub_caps
    if kind == 'CUBE':
        x, y, z = p.sub_width, p.sub_depth, p.sub_height
        return (x + 1) * (y + 1) * (z + 1) - (x - 1) * (y - 1) * (z - 1), 2 * (x * y + y * z + x * z)
    if kind == 'SPHERE':
        return a * (h - 1) + 2, a * h
    if kind == 'CYLINDER':
        if c < 2:
            return a * (h + 1), a * h + 2 * c
        return a * (h + 1) + 2 * (1 + a * (c - 1)), a * h + 2 * a * c
    if kind == 'CONE':
        if c < 2:
            return a * h + 1, a * h + c
        return a * h + 2 + a * (c - 1), a * h + a * c
    if kind == 'PLANE':
        return (p.sub_width + 1) * (h + 1), p.sub_width * h
    return a * h, a * h   # Torus

def volume(ob):
    me = ob.data
    me.calc_loop_triangles()
    return sum(me.vertices[t.vertices[0]].co.dot(me.vertices[t.vertices[1]].co.cross(me.vertices[t.vertices[2]].co)) / 6
               for t in me.loop_triangles)

STEPS = {"sub_axis": (3, 4, 9), "sub_caps": (0, 1, 2, 4)}
for kind, (_label, props) in I.KINDS.items():
    ob = new_prim(kind)
    inp = ob.m3d_input
    check(inp.kind == kind and not inp.frozen and counts(ob) == expect(kind, inp), f"{kind} default inputs build {counts(ob)}")
    for name in (n for n in props if n.startswith("sub_")):
        values = STEPS.get(name) or ((2, 3, 6) if kind == 'SPHERE' and name == "sub_height" else
                                     (3, 4, 6) if kind == 'TORUS' and name == "sub_height" else (1, 2, 5))
        for value in values:
            setattr(inp, name, value)
            check(counts(ob) == expect(kind, inp), f"{kind} {name}={value}: {counts(ob)} not {expect(kind, inp)}")
            check(len(ob.data.uv_layers) == 1, f"{kind} {name}={value} keeps one UV layer")
            if kind != 'PLANE' and not (kind in {'CYLINDER', 'CONE'} and inp.sub_caps == 0):
                check(volume(ob) > 0, f"{kind} {name}={value} faces point outwards")
        setattr(inp, name, I.DEFAULTS[kind][name])
    uv = np.empty(2 * len(ob.data.loops), np.float32)
    ob.data.uv_layers[0].uv.foreach_get("vector", uv)
    check(uv.min() >= -1e-5 and uv.max() <= 1 + 1e-5 and np.ptp(uv[::2]) > 0.2 and np.ptp(uv[1::2]) > 0.2, f"{kind} UVs fill 0..1")
SIZES = {
    'CUBE': (dict(width=2, height=3, depth=4), (2, 4, 3)),
    'SPHERE': (dict(radius=2, sub_axis=8, sub_height=8), (4, 4, 4)),
    'CYLINDER': (dict(radius=2, height=5, sub_axis=8), (4, 4, 5)),
    'CONE': (dict(radius=2, height=5, sub_axis=8), (4, 4, 5)),
    'PLANE': (dict(width=3, height=2), (3, 2, 0)),
    'TORUS': (dict(radius=2, section_radius=0.5, sub_axis=8, sub_height=8), (5, 5, 1)),
}
for kind, (values, size) in SIZES.items():
    ob = new_prim(kind)
    for name, value in values.items():
        setattr(ob.m3d_input, name, value)
    bpy.context.view_layer.update()
    check(all(abs(a - b) < 1e-4 for a, b in zip(ob.dimensions, size)), f"{kind} size {tuple(ob.dimensions)} not {size}")
ob = new_prim('SPHERE')
ob.m3d_input.sub_axis = 10000
check(ob.m3d_input.sub_axis == 200 and counts(ob) == (200 * 19 + 2, 200 * 20), "huge subdivision clamps to 200")

# Material slots, transform, Shade Smooth survive a rebuild; face materials reset to the first slot.
ob = new_prim('CUBE')
me = ob.data
me.materials.append(bpy.data.materials.new("inpA")); me.materials.append(bpy.data.materials.new("inpB"))
me.polygons.foreach_set("material_index", [1] * len(me.polygons))
ob.location, ob.rotation_euler, ob.scale = (1, 2, 3), (0.1, 0.2, 0.3), (2, 1, 0.5)
loc, rot, scl = tuple(ob.location), tuple(ob.rotation_euler), tuple(ob.scale)
me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
ob.m3d_input.sub_width = 3
check(len(me.materials) == 2 and ob.data is me and all(p.material_index == 0 for p in me.polygons), "rebuild keeps material slots, resets face materials, same mesh")
check((tuple(ob.location), tuple(ob.rotation_euler), tuple(ob.scale)) == (loc, rot, scl), "rebuild keeps the transform")
check(all(p.use_smooth for p in me.polygons), "rebuild keeps Shade Smooth")
check(not ob.m3d_input.frozen and not I.is_frozen(ob), "a rebuild does not freeze")

# Editing the mesh freezes the inputs: component edit, Edit Mode round trip (no change: not frozen), modifier.
ob = new_prim('CUBE')
ob.m3d_input.sub_width = 3
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.object.mode_set(mode='OBJECT')
check(not I.is_frozen(ob), "an Edit Mode round trip without changes is not an edit")
n_before = counts(ob)
ob.data.vertices[0].co.x += 0.1
ob.data.update()
check(I.is_frozen(ob) and not ob.m3d_input.frozen, "a moved vertex is detected (read only)")
ob.m3d_input.sub_width = 5
x_moved = ob.data.vertices[0].co.x
check(ob.m3d_input.frozen and counts(ob) == n_before and ob.data.vertices[0].co.x == x_moved, "frozen: no rebuild")
bpy.ops.m3d.delete_history()
check(ob.m3d_input.kind == 'NONE' and not ob.m3d_input.frozen and counts(ob) == n_before, "Delete History clears the inputs, keeps the mesh")
ob.m3d_input.sub_width = 7
check(counts(ob) == n_before, "no inputs: nothing rebuilds")
ob = new_prim('CUBE')
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(ob.data); bm.verts.ensure_lookup_table(); bm.verts[0].co.z += 0.2; bmesh.update_edit_mesh(ob.data)
bpy.ops.object.mode_set(mode='OBJECT')
check(I.is_frozen(ob), "an Edit Mode move freezes the inputs")
ob = new_prim('CYLINDER')
ob.modifiers.new("sub", 'SUBSURF')
bpy.ops.object.modifier_apply(modifier="sub")
check(I.is_frozen(ob), "applying a modifier freezes the inputs")
ob = new_prim('SPHERE')
ob.modifiers.new("sub", 'SUBSURF')
bpy.ops.m3d.delete_history(modifiers=True)
check(ob.m3d_input.kind == 'NONE' and not ob.modifiers and len(ob.data.vertices) > 382, "Delete All History: inputs cleared, modifiers applied")

# Duplicate: the copy rebuilds its own mesh.
a = new_prim('CUBE')
a.m3d_input.sub_width = 2
bpy.ops.m3d.duplicate()
b = bpy.context.active_object
check(b is not a and b.data is not a.data and b.m3d_input.kind == 'CUBE' and b.m3d_input.sub_width == 2 and not I.is_frozen(b), "duplicate keeps the inputs")
b.m3d_input.sub_width = 4
check(counts(b) == expect('CUBE', b.m3d_input) and counts(a) == expect('CUBE', a.m3d_input) and a.m3d_input.sub_width == 2, "the copy rebuilds its own mesh")
a.m3d_input.sub_height = 3
check(counts(b) == expect('CUBE', b.m3d_input) and counts(a) == expect('CUBE', a.m3d_input) and not (I.is_frozen(a) or I.is_frozen(b)), "...and the original its own")

# cmds flags, setAttr / getAttr, MEL.
def prim_ok(name, kind, **dims):
    ob = bpy.data.objects[name]
    p = ob.m3d_input
    bpy.context.view_layer.update()
    check(p.kind == kind and counts(ob) == expect(kind, p) and not I.is_frozen(ob), f"cmds {name} builds {counts(ob)} {expect(kind, p)}")
    for attr, size in dims.items():
        check(abs(getattr(ob.dimensions, attr) - size) < 1e-4, f"cmds {name} dimension {attr}={getattr(ob.dimensions, attr)} not {size}")
    return ob
cmds.polyCube(w=2, h=3, d=4, sx=2, sy=3, sz=4, n="icube")
ob = prim_ok("icube", 'CUBE', x=2, y=4, z=3)
check((ob.m3d_input.sub_width, ob.m3d_input.sub_height, ob.m3d_input.sub_depth) == (2, 3, 4), "polyCube sx / sy / sz = width / height / depth divisions")
cmds.polySphere(r=2, sa=8, sh=4, n="isphere"); prim_ok("isphere", 'SPHERE', x=4)
cmds.polyCylinder(r=1, h=3, sa=6, sh=2, sc=2, n="icyl"); prim_ok("icyl", 'CYLINDER', x=2, z=3)
cmds.polyCone(r=1, h=3, sa=7, sh=3, sc=0, n="icone"); prim_ok("icone", 'CONE', z=3)
cmds.polyPlane(w=3, h=2, sx=3, sy=2, n="iplane"); prim_ok("iplane", 'PLANE', x=3, y=2)
cmds.polyTorus(r=2, sr=0.5, sa=10, sh=4, n="itorus"); prim_ok("itorus", 'TORUS', z=1)
cmds.polyCube(width=1, subdivisionsWidth=3, name="ilong"); prim_ok("ilong", 'CUBE')
cmds.polyPlane(n="iplane0"); check(counts(bpy.data.objects["iplane0"]) == (121, 100), "polyPlane keeps its 10 x 10 default")
cmds.polyCylinder(n="icyl0"); check(counts(bpy.data.objects["icyl0"]) == (40, 22), "polyCylinder default as before")
cmds.setAttr("icube.subdivisionsWidth", 5); cmds.setAttr("icube.height", 1); cmds.setAttr("icube.subdivisionsDepth", 1)
ob = prim_ok("icube", 'CUBE', z=1)
check(cmds.getAttr("icube.subdivisionsWidth") == 5 and cmds.getAttr("icube.height") == 1 and cmds.getAttr("icube.depth") == 4, "setAttr / getAttr on the inputs")
cmds.setAttr("isphere.subdivisionsAxis", 12); cmds.setAttr("isphere.radius", 1.5)
prim_ok("isphere", 'SPHERE', x=3)
cmds.setAttr("itorus.sectionRadius", 0.25)
check(abs(cmds.getAttr("itorus.sectionRadius") - 0.25) < 1e-6, "sectionRadius")
cmds.setAttr("icyl.subdivisionsCaps", 1); prim_ok("icyl", 'CYLINDER')
for bad in ("isphere.depth", "iplane.subdivisionsCaps"):
    try:
        cmds.getAttr(bad)
        check(False, "getAttr " + bad + " should fail")
    except ValueError:
        pass
_console_mel.run("polyCylinder -r 2 -h 4 -sa 12 -sc 0 -n mcyl; setAttr mcyl.subdivisionsHeight 3;")
ob = prim_ok("mcyl", 'CYLINDER', x=4, z=4)
check(ob.m3d_input.sub_height == 3 and counts(ob) == (48, 36), "MEL flags and setAttr")
check(_console_mel.run("polyCube -w 2 -sx 3 -n mcube; getAttr mcube.subdivisionsWidth;") == 3, "MEL getAttr on an input")
cmds.setAttr("icube.rotateZ", 30); prim_ok("icube", 'CUBE')   # Other attributes still work.
bpy.data.objects["icube"].data.vertices[0].co.x += 0.1
cmds.setAttr("icube.width", 4)
check(bpy.data.objects["icube"].m3d_input.frozen and abs(bpy.data.objects["icube"].dimensions.x - 4) > 1e-3, "setAttr on an edited mesh does not rebuild")
cmds.delete("icyl", ch=True)
check(bpy.data.objects["icyl"].m3d_input.kind == 'NONE', "delete -ch clears the inputs")
for ob in [o for o in bpy.data.objects if o not in objects_before]:
    bpy.data.objects.remove(ob)

# Tangents, hide / show last hidden.
bpy.ops.object.select_all(action='DESELECT')
ball = bpy.data.objects["ball"]
ball.select_set(True); bpy.context.view_layer.objects.active = ball
ball.keyframe_insert("location", frame=1); ball.keyframe_insert("location", frame=10)
bpy.ops.m3d.set_tangents(kind='STEPPED')
from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
bag = animdata_get_channelbag_for_assigned_slot(ball.animation_data)
check(all(k.interpolation == 'CONSTANT' for fc in bag.fcurves for k in fc.keyframe_points), "stepped tangents")
bpy.ops.m3d.hide_selection()
check(ball.hide_get(), "ctrl h hides")
bpy.ops.m3d.show_hidden(which='LAST')
check(not ball.hide_get(), "ctrl shift h shows last hidden")
check(find("Object Mode", "m3d.key_marking_menu", "S", shift=True)[0].properties.menu_mmb == "M3D_MT_tangent_mm",
      "shift s middle click tangents")

# ----------------------------------------------------------------------------------------------------
# Phase 0: workspace kinds, pages, personalization.
from types import SimpleNamespace as NS
W = m3d_workspace


# Kind resolution: saved kind, current and older names, numbered copies; other workspaces have none.
class FakeWS:
    def __init__(self, name, kind=""): self.name, self.m3d_kind = name, kind


for name, kind in (("Modeling", 'MODEL'), ("Classic", 'MODEL'), ("Maya Classic", 'MODEL'), ("Modeling - Standard", 'MODEL'),
                   ("Sculpt", 'SCULPT'), ("Sculpting", 'SCULPT'), ("UV", 'UV'), ("UV Editing", 'UV'), ("Texture", 'TEXTURE'),
                   ("3D Paint", 'TEXTURE'), ("Rigging", 'RIG'), ("Animation", 'ANIM'), ("Rendering", 'RENDER'),
                   ("Sculpt.001", 'SCULPT'), ("Shading", None), ("Compositing", None), ("My Layout", None)):
    check(W.workspace_kind(FakeWS(name)) == kind, "kind of %r is %r" % (name, W.workspace_kind(FakeWS(name))))
check(W.workspace_kind(FakeWS("Whatever", 'RIG')) == 'RIG', "saved kind wins over the name")
check(W.workspace_kind(FakeWS("Sculpt", 'BOGUS')) == 'SCULPT', "bad saved kind falls back to the name")
check(W.workspace_kind(None) is None, "no workspace, no kind")

# The startup file: names, order, kinds, entry modes.
names = [w.name for w in bpy.data.workspaces]
check(sorted(names) == sorted(W.WORKSPACE_ORDER), "startup workspaces: %s" % names)  # Tab order: gui_test.py
for kind, (wname, key, mode, mset) in W.KINDS.items():
    ws = bpy.data.workspaces.get(wname)
    check(ws is not None and ws.m3d_kind == kind, "startup workspace %s has kind %s" % (wname, kind))
    check(ws is not None and ws.object_mode == mode, "startup workspace %s mode %s (is %s)" % (
        wname, mode, ws and ws.object_mode))
    check(W.find_workspace(kind) is ws, "find_workspace " + kind)
check("Modeling - Standard" not in names, "Modeling - Standard dropped")

# m3d.workspace sets the matching menu set (the window switch itself is checked in gui_test.py).
for kind, (wname, key, mode, mset) in W.KINDS.items():
    bpy.ops.m3d.workspace(kind=kind)
    check(bpy.context.window_manager.m3d_menu_set == mset, "menu set after " + kind)
# ...and the menu set / shelf follow a workspace change made any other way.
wm = bpy.context.window_manager
W._state["kind"] = 'MODEL'
W.workspace_changed(wm, bpy.data.workspaces["Sculpt"])
check(wm.m3d_menu_set == 'SCULPTING' and wm.m3d_shelf == 'SCULPT_BRUSHES', "menu set and shelf follow a workspace switch")
W.workspace_changed(wm, bpy.data.workspaces["Modeling"])
check(wm.m3d_menu_set == 'MODELING' and wm.m3d_shelf == 'POLY', "shelf tab is remembered per kind")

# Shelf tabs and status line per kind.
check(m3d_ui.shelves_for('SCULPT') == ['SCULPT_BRUSHES', 'SCULPT_REMESH', 'SCULPT_MASK', 'CUSTOM']
      and 'POLY' in m3d_ui.shelves_for('MODEL') and m3d_ui.shelves_for('MODEL')[-1] == 'CUSTOM', "shelf tabs per kind")
check(set(m3d_ui.STATUS_LINES) == set(W.KINDS), "every kind has its own status line")

# Page panels: only on their page, per workspace and side.
ws = bpy.data.workspaces["Modeling"]
ctx = lambda area_x=1500, ws=ws: NS(workspace=ws, area=NS(x=area_x, width=500), window=NS(width=2000))
check(W.side_of(ctx(1500)) == 'RIGHT' and W.side_of(ctx(0)) == 'LEFT', "dock side from the area position")
check(W.active_page(ctx()) == "modeling_toolkit", "default page")
check(m3d_mode.PROPERTIES_PT_m3d_mtk_selection.poll(ctx()), "toolkit panel shows on its page")
ws.m3d_page_right = "elsewhere"
check(W.active_page(ctx()) == "modeling_toolkit", "unknown stored page falls back to the first page")
saved = W.DOCK_TABS['MODEL']
W.DOCK_TABS['MODEL'] = {'RIGHT': (*saved['RIGHT'], W.Tab("test", "Test", 'MODELING_TOOLKIT', "test_page")),
                        'LEFT': (W.Tab("lt", "Left", 'MODELING_TOOLKIT', "left_page"),)}


class TestPage(W._PagePanel, bpy.types.Panel):
    bl_label = "Test page"
    page = "test_page"


ws.m3d_page_right = "test_page"
check(W.active_page(ctx()) == "test_page" and TestPage.poll(ctx()), "test page active on the right")
check(not m3d_mode.PROPERTIES_PT_m3d_mtk_selection.poll(ctx()), "toolkit panel hidden on another page")
check(W.active_page(ctx(0)) == "left_page" and not TestPage.poll(ctx(0)), "left tray has its own page")
other = bpy.data.workspaces["Shading"]
check(other.m3d_page_right == "" and W.active_page(ctx(1500, other)) == "modeling_toolkit",
      "pages are stored per workspace")
W.DOCK_TABS['MODEL'] = saved
ws.m3d_page_right = ""
for tab in W.DOCK_TABS['MODEL']['RIGHT']:
    check(tab.page is None or tab.context == 'MODELING_TOOLKIT', "page tabs use the toolkit context " + tab.id)

# Custom shelf / hidden tabs store: round trip through m3d_user.json in the (temp) config folder.
import json, shutil
m3d_user.reset_cache()
safe = os.path.normcase(m3d_user._path(create=True)).startswith(os.path.normcase(TEST_CONFIG))
check(safe, "tests write to a temp config folder, not the real one")
if not safe:
    print("FAILS:", fails)
    sys.exit(1)
check(m3d_user.shelf_items('MODEL') == [], "empty custom shelf without a file")
class FakeProps:
    """What a button's operator looks like to the Add to Shelf menu (the real one only exists in a UI)."""
    def __init__(self, real, **values):
        self.bl_rna, self._values = real.bl_rna, values

    def is_property_set(self, name):
        return name in self._values

    def __getattr__(self, name):
        return self._values[name]


real = bpy.context.window_manager.operator_properties_last("mesh.bevel")
item = m3d_user.item_from_operator(FakeProps(real, offset_type='PERCENT', segments=3, affect='VERTICES'))
check(item and item["idname"] == "mesh.bevel" and item["props"] == {"offset_type": 'PERCENT', "segments": 3,
      "affect": 'VERTICES'} and item["label"] == "Bevel", "item from operator: %r" % item)
check(json.loads(json.dumps(item)) == item, "item is JSON data")
bpy.ops.m3d.shelf_add(item=json.dumps(item))
bpy.ops.m3d.shelf_add(item=json.dumps({"idname": "object.mode_set", "props": {"mode": 'OBJECT'},
                                       "icon": "OBJECT_DATAMODE", "label": "Object Mode"}))
path = m3d_user._path()
check(path and os.path.exists(path), "m3d_user.json written")
m3d_user.reset_cache()
check([i["idname"] for i in m3d_user.shelf_items('MODEL')] == ["mesh.bevel", "object.mode_set"], "custom shelf round trip")
check(m3d_user.shelf_items('SCULPT') == [], "custom shelf is per kind")
bpy.ops.m3d.shelf_edit(action='RIGHT', index=0)
bpy.ops.m3d.shelf_edit(action='REMOVE', index=0)
m3d_user.reset_cache()
check([i["idname"] for i in m3d_user.shelf_items('MODEL')] == ["mesh.bevel"], "shelf move right then remove")
check(m3d_user._py_props("mesh.bevel", {"offset_type": 'PERCENT', "nope": 1}) == {"offset_type": 'PERCENT'}, "stored props")
m3d_user.toggle_tab('MODEL', "tool")
m3d_user.reset_cache()
check(m3d_user.hidden_tabs('MODEL') == {"tool"} and m3d_user.hidden_tabs('RIG') == set(), "hidden tabs round trip")
m3d_user.toggle_tab('MODEL', "tool")
check(m3d_user.hidden_tabs('MODEL') == set(), "tab shown again")
# A damaged or odd file never raises.
for text in ("{not json", "[]", '{"shelf": 5, "hidden_tabs": {"MODEL": 3}}', '{"shelf": {"MODEL": [1, {"idname": 7}, null]}}'):
    with open(path, "w") as fh:
        fh.write(text)
    m3d_user.reset_cache()
    try:
        m3d_user.shelf_items('MODEL'); m3d_user.hidden_tabs('MODEL')
        m3d_user.toggle_tab('MODEL', "x"); m3d_user.toggle_tab('MODEL', "x")
        ok = True
    except Exception as err:
        ok = False
        print("damaged file:", text, repr(err))
    check(ok, "damaged m3d_user.json: " + text)

# Maya dolly: Alt+RMB drag right zooms in (horizontal axis, not inverted). Fresh preferences get it from the factory
# handler; saved ones from a one-time migration that is recorded in m3d_user.json.
inputs_ = bpy.context.preferences.inputs
def dolly_prefs():
    return inputs_.view_zoom_method, inputs_.view_zoom_axis, inputs_.invert_mouse_zoom
inputs_.view_zoom_axis, inputs_.invert_mouse_zoom = 'VERTICAL', True
m3d_mode.m3d_preferences()
check(dolly_prefs() == ('DOLLY', 'HORIZONTAL', False), "factory preferences: Maya dolly %s" % (dolly_prefs(),))
inputs_.view_zoom_method, inputs_.view_zoom_axis, inputs_.invert_mouse_zoom = 'CONTINUE', 'VERTICAL', True
m3d_user.reset_cache()
check(m3d_user.data().get("prefs_version") is None, "no preferences version before the migration")
m3d_mode.migrate_preferences()
check(dolly_prefs() == ('DOLLY', 'HORIZONTAL', False), "migration: Maya dolly %s" % (dolly_prefs(),))
m3d_user.reset_cache()
check(m3d_user.data().get("prefs_version") == m3d_mode.PREFS_VERSION, "migration records the version in m3d_user.json")
inputs_.view_zoom_axis, inputs_.invert_mouse_zoom = 'VERTICAL', True   # The user changes their mind...
m3d_mode.migrate_preferences()
check(dolly_prefs() == ('DOLLY', 'VERTICAL', True), "...and the migration does not run again (%s)" % (dolly_prefs(),))
inputs_.view_zoom_axis, inputs_.invert_mouse_zoom = 'HORIZONTAL', False
m3d_user.reset_cache()

# Shift+drag on Scale / Rotate: the gizmo table matches the group's 19 gizmos, and the macros extrude / duplicate and
# then scale / rotate as one operator (the drags themselves are in gui_test.py).
kinds_ = [kind for kind, _axes in m3d_marking._XFORM_GIZMOS]
check(len(kinds_) == 19 and kinds_.count('resize') == 7 and kinds_.count('translate') == 7 and kinds_.count('rotate') == 4
      and kinds_.count('trackball') == 1, "transform gizmo table: %s" % (kinds_,))
mesh_ = bpy.data.meshes.new("m3dMacro")
bm_ = bmesh.new()
bmesh.ops.create_cube(bm_, size=1.0)
bm_.to_mesh(mesh_)
bm_.free()
ob_ = bpy.data.objects.new("m3dMacro", mesh_)
bpy.context.scene.collection.objects.link(ob_)
for other_ in bpy.context.view_layer.objects:
    other_.select_set(False)
bpy.context.view_layer.objects.active = ob_
ob_.select_set(True)
resize_ = {"value": (3, 1, 1), "constraint_axis": (True, False, False)}
n_objects_ = len(bpy.data.objects)
check(bpy.ops.m3d.duplicate_resize('EXEC_DEFAULT', TRANSFORM_OT_resize=resize_) == {'FINISHED'}
      and len(bpy.data.objects) == n_objects_ + 1 and abs(bpy.context.active_object.scale.x - 3) < 1e-4
      and bpy.context.active_object.scale.y == 1, "Duplicate and Scale duplicates and scales along X")
bpy.context.active_object.rotation_euler = (0, 0, 0)
check(bpy.ops.m3d.duplicate_rotate('EXEC_DEFAULT', TRANSFORM_OT_rotate={"value": 0.5, "orient_axis": 'Z'}) == {'FINISHED'}
      and abs(bpy.context.active_object.rotation_euler.z - 0.5) < 1e-4, "Duplicate and Rotate duplicates and rotates")
for dup_ in [o for o in bpy.data.objects if o != ob_ and o.name.startswith("m3dMacro")]:
    bpy.data.objects.remove(dup_)
bpy.context.view_layer.objects.active = ob_
ob_.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
check(bpy.ops.m3d.extrude_resize('EXEC_DEFAULT', TRANSFORM_OT_resize=resize_) == {'FINISHED'}, "Extrude and Scale runs")
bm_ = bmesh.from_edit_mesh(ob_.data)
xs_ = [v.co.x for v in bm_.verts if v.select]
check(len(bm_.faces) == 12 and abs(max(xs_) - min(xs_) - 3.0) < 1e-4, "Extrude and Scale: new faces %d, X extent %s" % (
      len(bm_.faces), max(xs_) - min(xs_)))
check(bpy.ops.m3d.extrude_rotate('EXEC_DEFAULT', TRANSFORM_OT_rotate={"value": 0.5, "orient_axis": 'Z'}) == {'FINISHED'}
      and len(bmesh.from_edit_mesh(ob_.data).faces) == 18, "Extrude and Rotate runs")
bpy.ops.object.mode_set(mode='OBJECT')
bpy.data.objects.remove(ob_)
bpy.data.meshes.remove(mesh_)
m3d_user.reset_cache()
shutil.rmtree(TEST_CONFIG, ignore_errors=True)

# ----------------------------------------------------------------------------------------------------
# Phase 1: Sculpt workspace (tabs, pages, brushes, buttons, keys).
import m3d_sculpt as S
from ast import literal_eval
from bl_ui.properties_paint_common import UnifiedPaintPanel
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
sculpt_ws = bpy.data.workspaces["Sculpt"]
sc_tabs = W.DOCK_TABS['SCULPT']
check([t.label for t in sc_tabs['RIGHT']] == ["Geometry", "Mask", "Face Sets", "Deform", "Paint", "Display", "Objects"],
      "Sculpt dock tabs")
check([t.label for t in sc_tabs['LEFT']] == ["Brushes"], "Sculpt left tray tab")
check(W.dock_tabs('SCULPT', 'LEFT') == sc_tabs['LEFT'] and W.dock_tabs('SCULPT', 'RIGHT') == sc_tabs['RIGHT'], "dock_tabs")
for tab in (*sc_tabs['RIGHT'], *sc_tabs['LEFT']):
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id, "Sculpt page tab " + tab.id)
pages = {t.page for side in sc_tabs.values() for t in side}
check({c.page for c in S.classes if hasattr(c, "page")} == pages, "every Sculpt page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in S.classes), "Sculpt classes registered")

# Brush grid and Shift+1..7 resolve to assets in the essentials file.
asset_file = os.path.join(bpy.utils.system_resource('DATAFILES'), "assets", "brushes", "essentials_brushes-mesh_sculpt.blend")
with bpy.data.libraries.load(asset_file, assets_only=True) as (src, _dst):
    asset_names = set(src.brushes)
for label, name in (*S.BRUSHES, *S.PAINT_BRUSHES):
    check(name in asset_names, "brush asset %r" % name)
check(len(S.BRUSHES) >= 14 and set(S.BRUSH_KEYS) <= {n for _l, n in S.BRUSHES}, "brush grid and hotkey brushes")
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
for key, name in zip(('ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN'), S.BRUSH_KEYS):
    item = find("Sculpt", "brush.asset_activate", key, shift=True, ctrl=False, alt=False)
    check(item and item[0].properties.relative_asset_identifier == S.BRUSH_ASSET + name, "Shift+%s picks %s" % (key, name))
    check(not [k for km in kc.keymaps for k in km.keymap_items if k.type == key and k.shift and not k.ctrl and not k.alt
               and km.name in {"Sculpt", "3D View", "3D View Generic", "Window", "Screen", "Frames", "Object Non-modal"}
               and k.idname != "brush.asset_activate"], "Shift+%s is free in Sculpt" % key)

# Page panels: gate messages without a mesh / outside Sculpt Mode, every page panel with a sculpt mesh.
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)


class SCtx:
    """Context of a Sculpt dock: the real one with this workspace, side and a Properties editor."""
    def __init__(self, side='RIGHT'):
        self.workspace = sculpt_ws
        self.area = NS(x=1500 if side == 'RIGHT' else 0, width=500, type='PROPERTIES')
        self.window = NS(width=2000)
        self.space_data = NS(type='PROPERTIES', context='MODELING_TOOLKIT')
        self.region = NS(type='WINDOW', width=300)

    def __getattr__(self, name):
        return getattr(bpy.context, name)


# The stock brush panels look for an active brush tool and a 3D viewport: pretend there is one (no UI here).
ToolSelectPanelHelper.tool_active_from_context = staticmethod(lambda ctx: NS(use_brushes=True, idname="builtin.brush"))


def page_panels(page):
    return [c for c in S.classes if getattr(c, "page", None) == page and hasattr(c, "poll")]


def shown(page):
    side = 'LEFT' if page == "sculpt_brushes" else 'RIGHT'
    ctx = SCtx(side)
    setattr(sculpt_ws, "m3d_page_" + side.lower(), page)
    return [c.__name__ for c in page_panels(page) if c.poll(ctx) and c is not S.PROPERTIES_PT_m3d_sc_custom]   # (Custom is always there.)


for page in S.GATES:
    names = shown(page)
    check(len(names) == 1 and names[0].endswith("_gate"), "%s without a mesh shows its message only: %s" % (page, names))
bpy.ops.m3d.sculpt_add_mesh(kind='CUBE')
check(bpy.context.mode == 'SCULPT' and bpy.context.active_object.type == 'MESH', "Add Sphere / Cube starts sculpting")
bpy.ops.object.mode_set(mode='OBJECT')
names = shown("sculpt_geometry")
check(names and not any(n.endswith("_gate") for n in names), "Geometry works on a mesh in Object Mode: %s" % names)
check(shown("sculpt_mask") == ["PROPERTIES_PT_m3d_sc_mask_gate"], "Mask asks for Sculpt Mode in Object Mode")
check(shown("sculpt_objects") and shown("sculpt_display"), "Objects and Display need no mesh")
bpy.ops.object.mode_set(mode='SCULPT')
for page in pages:
    names = shown(page)
    check(names and not any(n.endswith("_gate") for n in names), "%s panels in Sculpt Mode: %s" % (page, names))
sculpt_ws.m3d_page_right = sculpt_ws.m3d_page_left = ""


class Rec:
    """A layout that records its calls (the real one needs a window)."""
    def __init__(self, log, kind="", args=(), kw=None):
        self._log, self._kind, self._args, self._kw = log, kind, args, kw or {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name == "panel":
            return lambda *a, **k: (Rec(self._log), Rec(self._log))

        def call(*a, **k):
            rec = Rec(self._log, name, a, k)
            self._log.append(rec)
            return rec
        return call

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return True

    def values(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def check_calls(where, log):
    for rec in log:
        if rec._kind == "operator":
            idname, values = rec._args[0], rec.values()
            if idname == "m3d.call":
                inner = literal_eval(values["props"])
                check(op_ok(values["idname"], inner), "%s: m3d.call %s %s" % (where, values["idname"], inner))
            elif idname == "m3d.sculpt_tool":
                check(not values["op"] or op_ok(values["op"], literal_eval(values["props"])), "%s: tool %s" % (where, values))
            else:
                check(op_ok(idname, values), "%s: operator %s %s" % (where, idname, values))
        elif rec._kind == "prop":
            owner, name = rec._args[0], rec._args[1]
            check(name.startswith("[") or name in owner.bl_rna.properties, "%s: %r has no property %s" % (where, owner, name))
        elif rec._kind == "popover":
            check(hasattr(bpy.types, rec._kw.get("panel", rec._args[0] if rec._args else "")), "%s: popover" % where)


def draw_stub(cls, ctx):
    log = []
    inst = type("Inst", (UnifiedPaintPanel,), {})()
    inst.layout, inst.is_popover = Rec(log), False
    cls.draw(inst, ctx)
    return log


ctx = SCtx()
for cls in S.classes:
    if issubclass(cls, bpy.types.Panel) and hasattr(cls, "draw"):
        try:
            check_calls(cls.__name__, draw_stub(cls, ctx))
        except Exception as err:
            check(False, "%s draw: %r" % (cls.__name__, err))
log = []
S.draw_status_line(Rec(log), ctx)
check_calls("status line", log)
check(any(r._kind == "popover" for r in log), "status line has the Auto-Masking popover")
for key in ('SCULPT_BRUSHES', 'SCULPT_REMESH', 'SCULPT_MASK', 'CUSTOM'):
    log = []
    ctx.window_manager.m3d_shelf = key
    m3d_ui.draw_shelf(Rec(log), ctx)
    check_calls("shelf " + key, log)
log = []
S.draw_brush_column(Rec(log))
check_calls("hotbox brushes", log)
check(len([r for r in log if r._kind == "operator"]) == len(S.BRUSHES), "hotbox has every brush")

# Brushes activate (and the shelf / tray know which one is active).
for label, name in S.BRUSHES:
    bpy.ops.brush.asset_activate(**S.brush_props(name))
    check(S.active_brush_id(bpy.context) == S.BRUSH_ASSET + name, "brush %s active (is %r)" % (name, S.active_brush_id(bpy.context)))
    check(S.is_active(bpy.context, "brush.asset_activate", S.brush_props(name)), "is_active " + name)
check(not S.is_active(bpy.context, "brush.asset_activate", S.brush_props("Draw")), "only the last brush is active")
bpy.ops.m3d.brush_pick(identifier=S.BRUSH_ASSET + "Clay Strips")
check(S.active_brush_id(bpy.context) == S.BRUSH_ASSET + "Clay Strips", "brush tile picks the brush")
check(S.M3D_OT_brush_pick.description(None, NS(identifier=S.BRUSH_ASSET + "Clay Strips")) == "Clay Strips", "tile tooltip is the name")

# Multires buttons: add, levels, delete higher; Dyntopo and Multires exclude each other.
ob = bpy.context.active_object
bpy.ops.m3d.multires_subdivide(mode='CATMULL_CLARK')
bpy.ops.m3d.multires_subdivide(mode='SIMPLE')
mod = S.multires_of(ob)
check(mod and mod.total_levels == 2 and mod.sculpt_levels == 2, "multires subdivide adds the modifier and levels")
bpy.ops.m3d.multires_level(delta=-1)
check(mod.sculpt_levels == 1 and mod.levels == 1, "multires level down")
bpy.ops.m3d.multires_level(delta=-5)
check(mod.sculpt_levels == 0, "multires level stops at 0")
bpy.ops.m3d.multires_level(delta=5)
check(mod.sculpt_levels == 2, "multires level stops at the top")
bpy.ops.m3d.multires_level(delta=-1)
bpy.ops.m3d.multires_edit(action='DELETE_HIGHER')
check(mod.total_levels == 1, "delete higher levels")
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.m3d.multires_edit(action='APPLY_BASE')
bpy.ops.object.modifier_remove(modifier=mod.name)
bpy.ops.object.voxel_remesh()   # Operators that need the sculpt session only run in a window (gui_test.py).
bpy.ops.object.mode_set(mode='SCULPT')
bpy.ops.sculpt.dynamic_topology_toggle()
check(ob.use_dynamic_topology_sculpting, "dyntopo on")
check(bpy.ops.m3d.multires_subdivide(mode='SIMPLE') == {'CANCELLED'} and S.multires_of(ob) is None,
      "multires refuses while Dyntopo is on")
bpy.ops.sculpt.dynamic_topology_toggle()

# Mask / Face Set / Deform buttons: operators and options exist (they run in gui_test.py).
for group in (S.MASK_FILL, S.MASK_FILTERS, S.MASK_CREATE, S.HIDE_MASKED, S.FACE_SET_INIT, S.FACE_SET_CREATE,
              S.FACE_SET_VISIBILITY, S.PIVOT_BUTTONS):
    for label, idname, icon, props in group:
        check(op_ok(idname, props), "button %s %s %s" % (label, idname, props))
for group in (S.MESH_FILTERS, S.MASK_TOOLS, S.TRIM_TOOLS, S.FACE_SET_EDIT, S.COLOR_FILTERS):
    for label, tool, op, props in group:
        check(not op or op_ok(op, props), "tool option %s %s" % (label, op))

# Objects tab: pick, hide, solo, duplicate.
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.m3d.add_primitive(kind='SPHERE')
second = bpy.context.active_object
bpy.ops.object.mode_set(mode='SCULPT')
bpy.ops.m3d.sculpt_object(name=ob.name, action='SELECT')
check(bpy.context.active_object == ob and bpy.context.mode == 'SCULPT', "Objects: pick a mesh keeps Sculpt Mode")
bpy.ops.m3d.sculpt_object(name=second.name, action='VISIBLE')
check(second.hide_get(), "Objects: hide")
bpy.ops.m3d.sculpt_object(name=second.name, action='VISIBLE')
check(not second.hide_get(), "Objects: show")
bpy.ops.m3d.sculpt_object(name=ob.name, action='SOLO')
check(second.hide_get() and not ob.hide_get(), "Objects: solo hides the others")
bpy.ops.m3d.sculpt_object(name=ob.name, action='SOLO')
check(not second.hide_get(), "Objects: solo again shows them")
count = len([o for o in bpy.data.objects if o.type == 'MESH'])
bpy.ops.m3d.sculpt_object(name=ob.name, action='DUPLICATE')
check(len([o for o in bpy.data.objects if o.type == 'MESH']) == count + 1 and bpy.context.mode == 'SCULPT'
      and bpy.context.active_object not in {ob, second}, "Objects: duplicate")

# ----------------------------------------------------------------------------------------------------
# Phase 1b: Ctrl gestures (mask / hide), Add / Subtract, Status Line brush controls, Remesh popover, matcap /
# stroke / alpha pickers, Lazy Mouse.


def phase1b():
    import numpy as np

    # Ctrl+LMB in the Sculpt keymap: one m3d.sculpt_ctrl per Alt / Shift combination, nothing else on Ctrl+LMB.
    sculpt_km = kc.keymaps["Sculpt"]
    for mode, mods in (('MASK', dict(shift=False, alt=False)), ('UNMASK', dict(shift=False, alt=True)),
                       ('HIDE_OUTSIDE', dict(shift=True, alt=False)), ('HIDE_INSIDE', dict(shift=True, alt=True))):
        item = find("Sculpt", "m3d.sculpt_ctrl", "LEFTMOUSE", ctrl=True, **mods)
        check(len(item) == 1 and item[0].value == 'PRESS' and item[0].properties.mode == mode, "Ctrl gesture %s: %s" % (mode, item))
        check(mode in S.BOX_OPS and mode in {m for m, _l, _d in S.CTRL_MODES}, "Ctrl gesture %s has its rectangle operator" % mode)
    ctrl_lmb = [k for k in sculpt_km.keymap_items if k.type == 'LEFTMOUSE' and k.ctrl]
    check(len(ctrl_lmb) == 4 and all(k.idname == "m3d.sculpt_ctrl" for k in ctrl_lmb),
          "Ctrl+LMB in Sculpt is only the gesture operator: %s" % [(k.idname, k.shift, k.alt) for k in ctrl_lmb])
    check(not [k for k in sculpt_km.keymap_items if k.idname == "sculpt.brush_stroke" and k.ctrl], "no inverted / mask stroke on Ctrl")
    plain = [k for k in sculpt_km.keymap_items if k.idname == "sculpt.brush_stroke" and not k.ctrl]
    check(sorted((k.shift, k.properties.mode if not k.shift else k.properties.brush_toggle) for k in plain)
          == [(False, 'NORMAL'), (True, 'SMOOTH')], "plain and Shift strokes are as before")
    toggle = find("Sculpt", "wm.context_toggle_enum", "N", shift=False, ctrl=False, alt=False)
    check(len(toggle) == 1 and toggle[0].properties.data_path == "tool_settings.sculpt.brush.direction"
          and {toggle[0].properties.value_1, toggle[0].properties.value_2} == {'ADD', 'SUBTRACT'}, "N toggles Add / Subtract")
    check(not [k for name in ("3D View", "3D View Generic", "Window", "Screen", "Screen Editing", "Frames", "Object Non-modal")
               for k in kc.keymaps[name].keymap_items if k.type == 'N' and not (k.shift or k.ctrl or k.alt or k.oskey)],
          "N is free outside the Sculpt keymap")
    seen = {}
    for k in sculpt_km.keymap_items:
        if k.active:
            seen.setdefault((k.type, k.value, k.shift, k.ctrl, k.alt, k.oskey, k.any, k.key_modifier), []).append(k.idname)
    dupes = {key: names for key, names in seen.items() if len(names) > 1}
    # Blender's own pairs, told apart by their polls: Ctrl+D (Dyntopo flood fill / Voxel Remesh), Ctrl+Shift+D (their size
    # edits), Shift+RMB (set pivot / stencil), RMB (stencil / context panel).
    STOCK_PAIRS = {('D', 'PRESS', False, True, False, False, False, 'NONE'), ('D', 'PRESS', True, True, False, False, False, 'NONE'),
                   ('RIGHTMOUSE', 'PRESS', True, False, False, False, False, 'NONE'), ('RIGHTMOUSE', 'PRESS', False, False, False, False, False, 'NONE')}
    check(set(dupes) <= STOCK_PAIRS,
          "no conflicting items left in the Sculpt keymap: %s" % dupes)
    check(all(S.CTRL_MODES[i][2] == S.M3D_OT_sculpt_ctrl.description(None, NS(mode=S.CTRL_MODES[i][0])) for i in range(4)), "gesture tooltips")
    for mode, (op, options) in S.BOX_OPS.items():
        rna = getattr(getattr(bpy.ops, op.split(".")[0]), op.split(".")[1]).get_rna_type()
        check(all(k in rna.properties for k in (*options, "xmin", "xmax", "ymin", "ymax")), "rectangle operator %s for %s" % (op, mode))
        if "area" in options:
            check(options["area"] in rna.properties["area"].enum_items.keys(), "hide area %s exists" % options["area"])
    check(op_ok("paint.mask_flood_fill", {"mode": 'INVERT'}) and op_ok("sculpt.mask_filter", {"filter_type": 'SMOOTH'})
          and op_ok("sculpt.face_set_change_visibility", {"mode": 'TOGGLE'}) and op_ok("paint.hide_show_all", {"action": 'SHOW'}),
          "gesture click operators")
    check(S.ui_scale_factor(bpy.context) > 0, "UI scale factor without a window")

    # Mask tab: a big Invert button first, Clear and Fill, the Ctrl hints.
    check([b[0] for b in S.MASK_FILL] == ["Invert", "Clear", "Fill"], "Mask buttons")
    log = []
    ctx = SCtx()
    S.PROPERTIES_PT_m3d_sc_mask.draw(type("Inst", (), {"layout": Rec(log)})(), ctx)
    def op_props(r):
        """Options of a recorded button: its m3d.call props, or the operator's own."""
        v = r.values()
        return literal_eval(v["props"]) if "props" in v else v


    ops_ = [r for r in log if r._kind == "operator"]
    check(op_props(ops_[0]).get("mode") == 'INVERT' and "Invert" in ops_[0]._kw["text"], "Mask tab starts with Invert Mask")
    check(any(r._kind == "row" and r.values().get("scale_y", 1) > 1.4 for r in log), "the Invert button is big")
    check(len([o for o in ops_ if "Clear" in o._kw["text"] or "Fill" in o._kw["text"]]) == 2, "Clear and Fill follow")
    check(any(r._kind == "label" and "Ctrl+drag" in r._kw["text"] for r in log), "Mask tab lists the Ctrl gestures")
    log = []
    S.PROPERTIES_PT_m3d_sc_mask_hide.draw(type("Inst", (), {"layout": Rec(log)})(), ctx)
    check(any(r._kind == "label" and "Ctrl+Shift" in r._kw["text"] for r in log), "Hide panel lists the Ctrl+Shift gestures")

    # Status Line: the brush controls by width, Unified Size / Strength aware, the popovers.
    sculpt_brush_ = lambda: bpy.context.tool_settings.sculpt.brush
    brush = sculpt_brush_()
    ups = bpy.context.tool_settings.sculpt.unified_paint_settings


    def status(width, unified=False):
        c = SCtx()
        c.region = NS(type='TOOL_HEADER', width=width)
        c.space_data = NS(type='TOPBAR')   # (the header has no brush tool: the stock brush helpers find no paint settings)
        ups.use_unified_size = ups.use_unified_strength = unified
        log = []
        S.draw_status_line(Rec(log), c)
        check_calls("status line %d" % width, log)
        props = [(r._args[0], r._args[1]) for r in log if r._kind == "prop"]
        popovers = [r._args[0] for r in log if r._kind == "popover"]
        return log, props, popovers


    for width, tier in ((3200, 2), (1800, 1), (1000, 0)):
        check(S.header_tier(type("C", (), {"region": NS(width=width), "preferences": bpy.context.preferences})()) == tier,
              "Status Line tier of %d px" % width)
        log, props, popovers = status(width)
        names = {name for _owner, name in props}
        check({"size", "strength"} <= names or {"unprojected_size", "strength"} <= names, "Status Line %d: Size and Strength" % width)
        check(any(o == brush and n in {"size", "unprojected_size"} for o, n in props), "Status Line %d: Size is the brush's" % width)
        check(any(r._kind == "prop_enum" and r._args[1] == "direction" for r in log), "Status Line %d: Add / Subtract" % width)
        check(("hardness" in names) == (tier == 2) and ("remesh_voxel_size" in names) == (tier == 2), "Status Line %d: wide extras" % width)
        check({"M3D_PT_sculpt_brush", "M3D_PT_sculpt_remesh", "M3D_PT_sculpt_shading", "M3D_PT_sculpt_automasking"} <= set(popovers),
              "Status Line %d: popovers %s" % (width, popovers))
        check(any(r._kind == "prop" and r._args[1] == "use_smooth_stroke" for r in log), "Status Line %d: Lazy Mouse" % width)
    log, props, _popovers = status(1800, unified=True)
    check(any(o == ups and n in {"size", "unprojected_size"} for o, n in props) and any(o == ups and n == "strength" for o, n in props),
          "Status Line sliders follow Unified Size / Strength")
    ups.use_unified_size = ups.use_unified_strength = False
    # A color brush shows its two colors and Swap in the Status Line.
    bpy.ops.brush.asset_activate(**S.brush_props("Paint Soft"))
    check(sculpt_brush_().sculpt_capabilities.has_color, "Paint Soft is a color brush")
    log, props, _popovers = status(3200)
    check([n for o, n in props if n in {"color", "secondary_color"}] == ["color", "secondary_color"]
          and any(r._kind == "operator" and r._args[0] == "paint.brush_colors_flip" for r in log), "Status Line: the colors of a color brush")
    bpy.ops.brush.asset_activate(**S.brush_props("Draw"))
    brush = sculpt_brush_()   # (activating a brush again may give a new data-block)
    for pname in ("M3D_PT_sculpt_brush", "M3D_PT_sculpt_remesh", "M3D_PT_sculpt_shading"):
        check(getattr(bpy.types, pname).bl_space_type == 'TOPBAR', pname + " is a Status Line popover")
    log = []
    S.M3D_PT_sculpt_remesh.draw(type("Inst", (), {"layout": Rec(log)})(), ctx)
    check_calls("remesh popover", log)
    check(any(r._kind == "prop" and r._args[1] == "remesh_voxel_size" for r in log), "Remesh popover: Voxel size")
    check(any(r._kind == "operator" and "voxel_remesh" in str(r.values().get("idname", r._args)) for r in log), "Remesh popover: Voxel Remesh button")
    check(not [r for r in log if r._kind == "operator" and r._args[0] == "m3d.multires_level"], "no Multires level buttons without a Multires modifier")
    log = []
    ctx_mr = SCtx()
    mr_ob = bpy.context.active_object
    bpy.ops.m3d.multires_subdivide(mode='SIMPLE')
    S.draw_multires(Rec(log), ctx_mr)
    check({r.values()["delta"] for r in log if r._kind == "operator" and r._args[0] == "m3d.multires_level"} == {-1, 1},
          "Multires Lower / Higher buttons")
    log = []
    S.draw_status_line(Rec(log), ctx_mr)
    check(len([r for r in log if r._kind == "operator" and r._args[0] == "m3d.multires_level"]) == 2, "Status Line: Multires level arrows")
    mr_ob.modifiers.remove(S.multires_of(mr_ob))

    # Add / Subtract: both buttons exist on the brush, a tile click and the direction toggle flip it.
    check({i.identifier for i in bpy.types.Brush.bl_rna.properties["direction"].enum_items} == {'ADD', 'SUBTRACT'}, "brush directions")
    brush.direction = 'SUBTRACT'
    bpy.ops.wm.context_toggle_enum(data_path="tool_settings.sculpt.brush.direction", value_1='ADD', value_2='SUBTRACT')
    check(brush.direction == 'ADD', "the N key's toggle goes back to Add")

    # Lazy Mouse: the toggle, radius and factor are brush properties.
    for prop in ("use_smooth_stroke", "smooth_stroke_radius", "smooth_stroke_factor"):
        check(prop in brush.bl_rna.properties, "Lazy Mouse property " + prop)
    brush.use_smooth_stroke = True
    brush.smooth_stroke_radius = 120
    check(brush.use_smooth_stroke and brush.smooth_stroke_radius == 120, "Lazy Mouse settings stick")
    log = []
    S.draw_lazy(Rec(log), brush)
    check({r._args[1] for r in log if r._kind == "prop"} == {"use_smooth_stroke", "smooth_stroke_radius"}, "draw_lazy")
    log = []
    S.PROPERTIES_PT_m3d_sc_lazy.draw_header(type("Inst", (), {"layout": Rec(log)})(), ctx)
    check(any(r._kind == "prop" and r._args[1] == "use_smooth_stroke" for r in log), "Lazy Mouse panel header toggle")
    brush.use_smooth_stroke = False

    # Stroke type tiles.
    check({k for k, _l, _d in S.STROKES} == {i.identifier for i in bpy.types.Brush.bl_rna.properties["stroke_method"].enum_items},
          "a stroke tile for every stroke type")
    icons = S.stroke_icons()
    check(len(icons) == 7 and all(isinstance(i, int) for i in icons.values()), "stroke thumbnails %s" % icons)
    pics = [S.stroke_pixels(k) for k, _l, _d in S.STROKES]
    check(all(p.shape == (64, 64, 4) and 0 <= p.min() and p.max() <= 1 for p in pics)
          and len({p.tobytes() for p in pics}) == 7 and all(p[..., :3].std() > 0.05 for p in pics), "stroke pictures are drawn and differ")
    for kind, _label, _desc in S.STROKES:
        bpy.ops.m3d.stroke_pick(stroke=kind)
        check(brush.stroke_method == kind, "stroke tile " + kind)
        check(S.M3D_OT_stroke_pick.description(None, NS(stroke=kind)).startswith(S.STROKES[[k for k, _l, _d in S.STROKES].index(kind)][1]), "stroke tooltip " + kind)
    bpy.ops.m3d.stroke_pick(stroke='SPACE')
    log = []
    S.stroke_tiles(Rec(log), ctx, brush)
    tiles = [r for r in log if r._kind == "operator"]
    check(len(tiles) == 7 and sum(bool(r._kw.get("depress")) for r in tiles) == 1, "stroke tiles: one pressed")

    # Matcap tiles.
    matcaps = S.studio_lights(bpy.context, 'MATCAP')
    check(len(matcaps) >= 10 and all(sl.type == 'MATCAP' for sl in matcaps) and "basic_bright.exr" in {sl.name for sl in matcaps},
          "matcap list (%d)" % len(matcaps))
    check(S.studio_lights(bpy.context, 'STUDIO'), "studio light list")
    shading = S.viewport(bpy.context).shading
    shading.light = 'MATCAP'
    shading.studio_light = matcaps[2].name
    log = []
    S.light_tiles(Rec(log), ctx, shading, 16)
    tiles = [r for r in log if r._kind == "operator"]
    check(len(tiles) == len(matcaps) and sum(bool(r._kw.get("depress")) for r in tiles) == 1
          and [r.values()["name"] for r in tiles if r._kw.get("depress")] == [matcaps[2].name], "matcap tiles: the picked one is pressed")
    for sl in (matcaps[5], matcaps[0]):
        bpy.ops.m3d.light_pick(name=sl.name, kind='MATCAP')
        check(shading.light == 'MATCAP' and shading.studio_light == sl.name, "matcap pick " + sl.name)
    bpy.ops.m3d.light_pick(name=S.studio_lights(bpy.context, 'STUDIO')[1].name, kind='STUDIO')
    check(shading.light == 'STUDIO', "studio light pick")
    check(S.M3D_OT_light_pick.description(None, NS(name="clay_brown.exr")) == "Clay Brown", "matcap tooltip")
    log = []
    S.draw_shading(Rec(log), ctx, 16)
    check_calls("shading", log)
    shading.light = 'MATCAP'

    # Alpha library: the starter set is made on first use and linked (a brush asset is linked data and can only point
    # at linked data), loaded images join it, None clears.
    import shutil
    alpha_folder = tempfile.mkdtemp(prefix="m3d_alpha_")
    S.alpha_dir = lambda create=False: alpha_folder
    check(S.alpha_names() == list(S.STARTER_ALPHAS), "alphas before any is made")
    pix = [S.alpha_pixels(n, 64) for n in S.STARTER_ALPHAS]
    check(all(p.shape == (64, 64, 4) and 0 <= p.min() and p.max() <= 1 and p[..., 0].std() > 0.05 for p in pix)
          and len({p.tobytes() for p in pix}) == len(pix), "starter alphas are drawn and differ")
    check(np.array_equal(S.alpha_pixels("Clouds", 64), S.alpha_pixels("Clouds", 64)), "starter alphas are the same each time")
    check(len(S.alpha_icons(S.alpha_names())) == len(S.STARTER_ALPHAS), "starter alpha thumbnails")
    check(brush.library is not None, "the sculpt brush is linked data (why the alphas are linked)")
    for name in S.STARTER_ALPHAS:
        bpy.ops.m3d.alpha_pick(name=name)
        tex = brush.texture
        check(tex is not None and tex.name == name and tex.library is not None and tex.image is not None and tex.image.size[0] == S.ALPHA_SIZE
              and tex.extension == 'CLIP' and brush.texture_slot.map_mode == 'AREA_PLANE', "alpha pick " + name)
    import os
    check(all(os.path.isfile(os.path.join(alpha_folder, n + ext)) for n in S.STARTER_ALPHAS for ext in (".blend", ".png")), "alphas are in the library folder")
    bpy.ops.m3d.alpha_pick(name="Clouds")
    check(brush.texture.name == "Clouds" and len([t for t in bpy.data.textures if t.name == "Clouds"]) == 1, "picking again re-uses the linked alpha")
    # Load Alpha: an image file becomes an alpha.
    img = bpy.data.images.new("src", 48, 48)
    gradient = np.ones((48, 48, 4), np.float32)
    gradient[..., :3] = np.linspace(0, 1, 48, dtype=np.float32)[None, :, None]
    img.pixels.foreach_set(gradient.ravel())
    png = os.path.join(alpha_folder, "ramp_source.png")
    img.filepath_raw, img.file_format = png, 'PNG'
    img.save()
    bpy.data.images.remove(img)
    check(bpy.ops.m3d.alpha_load(filepath=png) == {'FINISHED'}, "Load Alpha runs")
    tex = brush.texture
    check(tex is not None and tex.name == "ramp_source" and tex.library is not None and tex.image.size[0] == 48 and tex.image.packed_file is not None
          and brush.texture_slot.map_mode == 'AREA_PLANE' and tex.image.colorspace_settings.name == 'Non-Color', "Load Alpha sets the brush texture")
    check(S.alpha_names()[-1] == "ramp_source" and "ramp_source" in S.alpha_icons(S.alpha_names()), "the loaded alpha is a tile with a thumbnail")
    check(bpy.ops.m3d.alpha_load(filepath=os.path.join(alpha_folder, "nothing.png")) == {'CANCELLED'}, "Load Alpha: a missing file is refused")
    log = []
    S.alpha_tiles(Rec(log), ctx, brush)
    tiles = [r for r in log if r._kind == "operator"]
    check(len(tiles) == len(S.STARTER_ALPHAS) + 2 and sum(bool(r._kw.get("depress")) for r in tiles) == 1
          and tiles[-1].values()["name"] == "ramp_source" and tiles[-1]._kw.get("depress"), "alpha tiles: None, the starter set, the loaded one")
    bpy.ops.m3d.alpha_pick(name="")
    check(brush.texture is None, "None alpha")
    log = []
    S.PROPERTIES_PT_m3d_sc_alpha.draw(type("Inst", (), {"layout": Rec(log)})(), ctx)
    check_calls("alpha panel", log)
    check(any(r._kind == "operator" and r._args[0] == "m3d.alpha_load" for r in log), "Alpha panel has Load Alpha")
    shutil.rmtree(alpha_folder, ignore_errors=True)

    # The tray: essentials first (open), the rest closed.
    tray = [c for c in S.classes if getattr(c, "page", None) == "sculpt_brushes" and hasattr(c, "poll")]
    order = [c.bl_label for c in tray if c.__name__.startswith("PROPERTIES_PT_m3d_sc_") and not c.__name__.endswith("_gate")]
    check(order[:6] == ["Brush Asset", "Brushes", "Size and Strength", "Lazy Mouse", "Stroke Type", "Alpha"], "tray order: %s" % order)
    closed = {c.bl_label for c in tray if 'DEFAULT_CLOSED' in getattr(c, "bl_options", ())}
    check({"Alpha Settings", "Brush Settings", "Falloff", "Stroke Options", "Advanced", "Custom"} <= closed
          and not closed & {"Brushes", "Size and Strength", "Lazy Mouse", "Stroke Type", "Alpha"}, "tray: closed panels %s" % closed)
    bpy.ops.object.mode_set(mode='OBJECT')


phase1b()

# ----------------------------------------------------------------------------------------------------
# Phase 2: UV workspace (tabs, pages, buttons, texel density, Auto Unwrap, checker, keys).
import m3d_uv as U
import math
from mathutils import Vector

uv_ws = bpy.data.workspaces["UV"]
uv_tabs = W.DOCK_TABS['UV']
check([t.label for t in uv_tabs['RIGHT']] == ["Unwrap", "Arrange", "Check", "Create", "UDIM"], "UV dock tabs")
check(uv_tabs['LEFT'] == () and W.dock_tabs('UV', 'LEFT') == uv_tabs['RIGHT'], "UV has no left tray")
for tab in uv_tabs['RIGHT']:
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("uv_"), "UV page tab " + tab.id)
uv_pages = {t.page for t in uv_tabs['RIGHT']}
check({c.page for c in U.classes if hasattr(c, "page")} == uv_pages, "every UV page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in U.classes if c is not U.M3D_UVSettings),
      "UV classes registered")
check(m3d_ui.shelves_for('UV') == ['UV', 'CUSTOM'] and 'UV' in m3d_ui.STATUS_LINES,
      "UV shelf tabs and Status Line")
check([it[3] for it in m3d_ui.SHELVES['UV'][1] if it] == ["Cut", "Sew", "Unfold", "Optimize", "Layout", "Auto Unwrap"],
      "UV shelf buttons")

# Buttons outside the UV Editor run in it (m3d.call with editor), the 3D view keeps its own.
def target(area, screen_types, idname):
    """Editors are 'TYPE' or 'TYPE:MODE' (an Image Editor is in UV mode unless it says otherwise)."""
    def fake(t):
        kind, _, mode = t.partition(":")
        return NS(type=kind, spaces=NS(active=NS(mode=mode or 'UV')))
    ctx = NS(area=NS(type=area), screen=NS(areas=[fake(t) for t in screen_types]))
    return m3d_ui.call_target(ctx, idname)
check(target('PROPERTIES', ['VIEW_3D', 'IMAGE_EDITOR'], "uv.align") == 'IMAGE_EDITOR', "dock button runs in the UV Editor")
check(target('TOPBAR', ['VIEW_3D', 'IMAGE_EDITOR'], "m3d.uv_cut") == 'IMAGE_EDITOR', "shelf button runs in the UV Editor")
check(target('PROPERTIES', ['IMAGE_EDITOR'], "image.tile_add") == 'IMAGE_EDITOR', "tile buttons run in the UV Editor")
check(target('IMAGE_EDITOR', ['IMAGE_EDITOR'], "uv.align") is None, "UV Editor button runs in place")
check(target('PROPERTIES', ['VIEW_3D', 'IMAGE_EDITOR'], "uv.project_from_view") == 'VIEW_3D', "Planar needs the 3D view")
check(target('VIEW_3D', ['VIEW_3D'], "mesh.bevel") is None and target('PROPERTIES', ['VIEW_3D'], "mesh.bevel") == 'VIEW_3D',
      "3D view routing is unchanged")
check(target('TOPBAR', ['VIEW_3D'], "uv.smart_project") != 'IMAGE_EDITOR', "no UV Editor: the old route")
# The Texture workspace's Image Editor is in Paint mode: UV tools and image.new do not go there.
check(target('PROPERTIES', ['VIEW_3D', 'IMAGE_EDITOR:PAINT'], "uv.align") != 'IMAGE_EDITOR'
      and target('PROPERTIES', ['VIEW_3D', 'IMAGE_EDITOR:PAINT'], "m3d.uv_cut") != 'IMAGE_EDITOR'
      and target('PROPERTIES', ['VIEW_3D', 'IMAGE_EDITOR:PAINT'], "image.new") != 'IMAGE_EDITOR', "paint view is no UV Editor")
check(target('PROPERTIES', ['VIEW_3D', 'IMAGE_EDITOR:PAINT', 'IMAGE_EDITOR'], "uv.align") == 'IMAGE_EDITOR',
      "a UV Editor next to a paint view is still the target")

# Sidebar UV Toolkit: only where the workspace has no dock for it.
toolkit = U.IMAGE_PT_m3d_uvtk_selection
check(not toolkit.poll(NS(space_data=NS(show_uvedit=True), workspace=uv_ws)) and
      toolkit.poll(NS(space_data=NS(show_uvedit=True), workspace=bpy.data.workspaces["Modeling"])),
      "UV Toolkit sidebar is not in the UV workspace")

# Keys: UV Editor keymap only, free in the keymaps around it.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
for idname, key, mods, props in (("m3d.uv_layout", 'P', dict(alt=True), {}),
                                 ("m3d.uv_unfold", 'U', dict(ctrl=True, shift=True), {}),
                                 ("m3d.uv_checker", 'C', dict(alt=True), {}),
                                 ("m3d.uv_texel_density", 'T', dict(shift=True), {"mode": 'SET'}),
                                 ("wm.context_toggle", 'S', dict(alt=True), {"data_path": "tool_settings.use_uv_select_sync"})):
    want = {"shift": False, "ctrl": False, "alt": False, **mods}
    item = find("UV Editor", idname, key, **want)
    check(item and all(getattr(item[0].properties, k) == v for k, v in props.items()), "UV key %s %s" % (key, mods))
    others = [(km.name, k.idname) for km in kc.keymaps for k in km.keymap_items
              if k.type == key and all(getattr(k, m) == v for m, v in want.items()) and not k.oskey
              and (km.name, k.idname) != ("UV Editor", idname)
              and km.name in {"Window", "Screen", "Screen Editing", "Frames", "Image", "UV Editor", "Property Editor"}]
    check(not others, "UV key %s %s is free: %s" % (key, mods, others))

# Page panels: gate messages without a mesh / outside Edit Mode, every page panel in Edit Mode.
bpy.ops.object.mode_set(mode='OBJECT')
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)


class UCtx(SCtx):
    """Context of the UV dock: the real one with the UV workspace."""
    def __init__(self):
        super().__init__('RIGHT')
        self.workspace = uv_ws


def uv_page_panels(page):
    return [c for c in U.classes if getattr(c, "page", None) == page and hasattr(c, "poll")]


def uv_shown(page):
    ctx = UCtx()
    uv_ws.m3d_page_right = page
    return [c.__name__ for c in uv_page_panels(page) if c.poll(ctx)]


for page in U.GATES:
    names = uv_shown("uv_" + page)
    check(len(names) == 1 and names[0].endswith("_gate"), "uv_%s without a mesh shows its message only: %s" % (page, names))
check(uv_shown("uv_udim") == ["PROPERTIES_PT_m3d_uv_image"], "UDIM tab without a mesh: %s" % uv_shown("uv_udim"))
bpy.ops.m3d.add_primitive(kind='CUBE')
cube = bpy.context.active_object
for page in U.GATES:
    check(uv_shown("uv_" + page) == ["PROPERTIES_PT_m3d_uv_%s_gate" % page], "uv_%s asks for Edit Mode in Object Mode" % page)
bpy.ops.object.mode_set(mode='EDIT')
for page in uv_pages:
    names = uv_shown(page)
    check(names and not any(n.endswith("_gate") for n in names), "%s panels in Edit Mode: %s" % (page, names))

ctx = UCtx()
for page in sorted(uv_pages):
    for cls in uv_page_panels(page):
        uv_ws.m3d_page_right = page
        if cls.poll(ctx):
            try:
                check_calls(cls.__name__, draw_stub(cls, ctx))
            except Exception as err:
                check(False, "%s draw: %r" % (cls.__name__, err))
log = []
m3d_ui.draw_status_line(Rec(log), ctx)
check_calls("UV status line", log)
props_drawn = {r._args[1] for r in log if r._kind == "prop"}
check({"use_uv_select_sync", "use_uv_select_island", "texture_size"} <= props_drawn
      and any(r._kind == "operator" and r._args[0] == "m3d.uv_checker" for r in log), "UV status line controls")
for key in m3d_ui.shelves_for('UV'):
    log = []
    ctx.window_manager.m3d_shelf = key
    m3d_ui.draw_shelf(Rec(log), ctx)
    check_calls("shelf " + key, log)
for table in (U.UVTK_CUT_SEW, U.UVTK_UNFOLD, U.UV_PIN_PAGE, U.UV_SELECT_PAGE, U.UV_SHELVES, U.UV_TILES, U.UVTK_TRANSFORM,
              U.UVTK_CREATE):
    for label, idname, icon, props in table:
        check(op_ok(idname, props) and icon in icons, "UV button %s %s" % (label, idname))

# Operators. Unfold / Optimize / Layout on a cut cube.
S2 = bpy.context.scene.m3d_uv
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.m3d.uv_cut()
check(bpy.ops.m3d.uv_unfold() == {'FINISHED'} and bpy.ops.m3d.uv_optimize() == {'FINISHED'} and
      bpy.ops.m3d.uv_layout() == {'FINISHED'}, "Unfold, Optimize, Layout run")
S2.method = 'CONFORMAL'
check(bpy.ops.m3d.uv_unfold() == {'FINISHED'}, "Unfold with Conformal")
S2.method = 'ANGLE_BASED'
S2.rotate = 'OFF'
check(bpy.ops.m3d.uv_layout() == {'FINISHED'}, "Layout without rotation")
S2.rotate = 'CARDINAL'


def edit_bm(ob):
    bm = bmesh.from_edit_mesh(ob.data)
    return bm, bm.loops.layers.uv.verify()


def shell_boxes(ob):
    bm, uv = edit_bm(ob)
    boxes = []
    for shell in U.uv_shells(list(bm.faces), uv):
        pts = [loop[uv].uv for f in shell for loop in f.loops]
        boxes.append((min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts)))
    return boxes


def overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1e-6 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-6


# Texel density on a unit cube: every face its own shell, side 0.5 -> sqrt(0.25 / 1) x 1024 = 512 px/unit.
S2.texture_size = '1024'
bm, uv = edit_bm(cube)
corners = ((0, 0), (1, 0), (1, 1), (0, 1))
for i, f in enumerate(bm.faces):
    for loop, (cx, cy) in zip(f.loops, corners):
        loop[uv].uv = ((i % 3) * 0.6 + cx * 0.5, (i // 3) * 0.6 + cy * 0.5)
bmesh.update_edit_mesh(cube.data)
check(len(U.uv_shells(list(bm.faces), uv)) == 6, "six shells on the test cube")
check(abs(U.uv_area(bm.faces[0], uv) - 0.25) < 1e-6 and abs(U.world_area(bm.faces[0], cube.matrix_world) - 1.0) < 1e-6,
      "face areas")
bpy.ops.m3d.uv_texel_density(mode='READ')
check(abs(S2.density_read - 512.0) < 1e-3, "texel density read %s (want 512)" % S2.density_read)
S2.density = 1024.0
bpy.ops.m3d.uv_texel_density(mode='SET')
bm, uv = edit_bm(cube)
pts = [loop[uv].uv for loop in bm.faces[0].loops]
side = max(p.x for p in pts) - min(p.x for p in pts)
centre = ((max(p.x for p in pts) + min(p.x for p in pts)) / 2, (max(p.y for p in pts) + min(p.y for p in pts)) / 2)
check(abs(side - 1.0) < 1e-5 and abs(centre[0] - 0.25) < 1e-5 and abs(centre[1] - 0.25) < 1e-5,
      "set scales the shell about its centre (side %s, centre %s)" % (side, centre))
bpy.ops.m3d.uv_texel_density(mode='READ')
check(abs(S2.density_read - 1024.0) < 1e-3, "texel density after set %s" % S2.density_read)
cube.scale = (2, 2, 2)
bpy.context.view_layer.update()
bpy.ops.m3d.uv_texel_density(mode='READ')
check(abs(S2.density_read - 512.0) < 1e-3, "world scale halves the density: %s" % S2.density_read)
cube.scale = (1, 1, 1)
bpy.context.view_layer.update()
# Match: shrink one shell, make another face active, everything follows the active shell.
bm, uv = edit_bm(cube)
U.scale_shell([bm.faces[0]], uv, 0.5)
bm.faces.active = bm.faces[1]
bmesh.update_edit_mesh(cube.data)
bpy.ops.m3d.uv_texel_density(mode='MATCH')
check(abs(S2.density - 1024.0) < 1e-3 and abs(S2.density_read - 1024.0) < 1e-3, "match target %s" % S2.density)
bpy.ops.m3d.uv_texel_density(mode='READ')
check(abs(S2.density_read - 1024.0) < 1e-3, "match: every shell at the active density (%s)" % S2.density_read)
bpy.context.tool_settings.use_uv_select_sync = False
bpy.ops.m3d.uv_texel_density(mode='READ')
check(abs(S2.density_read - 1024.0) < 1e-3, "texel density with sync off")
bpy.context.tool_settings.use_uv_select_sync = True

# Auto Unwrap: a cube gets 12 seams and six shells inside 0-1 that do not overlap (sync on and off); a sphere is projected.
for sync in (True, False):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(bpy.context.active_object)
    bpy.ops.m3d.add_primitive(kind='CUBE')
    cube = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.tool_settings.use_uv_select_sync = sync
    check(bpy.ops.m3d.uv_auto() == {'FINISHED'}, "Auto Unwrap runs (sync %s)" % sync)
    check(bpy.context.tool_settings.use_uv_select_sync == sync, "Auto Unwrap leaves UV Sync as it was")
    bm, uv = edit_bm(cube)
    check(sum(e.seam for e in bm.edges) == 12, "cube seams %d" % sum(e.seam for e in bm.edges))
    boxes = shell_boxes(cube)
    check(len(boxes) == 6, "cube shells (sync %s): %d" % (sync, len(boxes)))
    check(all(b[0] >= -1e-6 and b[1] >= -1e-6 and b[2] <= 1 + 1e-6 and b[3] <= 1 + 1e-6 for b in boxes),
          "shells inside 0-1: %s" % boxes)
    check(not any(overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:]), "shells overlap: %s" % boxes)
bpy.context.tool_settings.use_uv_select_sync = True
bpy.ops.object.mode_set(mode='OBJECT')
bpy.data.objects.remove(bpy.context.active_object)
bpy.ops.m3d.add_primitive(kind='SPHERE')
ball = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
check(bpy.ops.m3d.uv_auto() == {'FINISHED'}, "Auto Unwrap on a smooth sphere")
bm, uv = edit_bm(ball)
xs = [loop[uv].uv for f in bm.faces for loop in f.loops]
check(min(p.x for p in xs) >= -1e-6 and max(p.x for p in xs) <= 1 + 1e-6 and max(p.y for p in xs) <= 1 + 1e-6,
      "sphere projected into 0-1")
bpy.ops.object.mode_set(mode='OBJECT')

# F3 (m3d.workspace) with a light active and a mesh selected: the mesh becomes the active object, so Edit Mode can be entered.
ball = bpy.context.active_object
bpy.ops.object.light_add(type='POINT')
light = bpy.context.active_object
ball.select_set(True)
bpy.ops.m3d.workspace(kind='UV')
check(bpy.context.active_object == ball, "F3 picks the selected mesh when a light is active (%s)" % bpy.context.active_object.name)
light.select_set(True)
ball.select_set(False)
bpy.context.view_layer.objects.active = light
bpy.ops.m3d.workspace(kind='UV')
check(bpy.context.active_object == light, "F3 with no mesh selected leaves the active object alone")
bpy.ops.m3d.workspace(kind='MODEL')
bpy.data.objects.remove(light)
bpy.context.view_layer.objects.active = ball

# Checker: slots keep their face numbers; the save handlers take it off the file and bring it back.
bpy.data.objects.remove(bpy.context.active_object)
bpy.ops.m3d.add_primitive(kind='CUBE')
box = bpy.context.active_object
box.name = "CheckerBox"
for name in ("MatA", "MatB"):
    box.data.materials.append(bpy.data.materials.new(name))
box.data.polygons[0].material_index = 1
bpy.ops.m3d.add_primitive(kind='CUBE')
bare = bpy.context.active_object
bare.name = "CheckerBare"
bpy.ops.object.select_all(action='SELECT')
bpy.ops.m3d.uv_checker()
check([s.material.name for s in box.material_slots] == [U.CHECKER] * 2 and box.data.polygons[0].material_index == 1,
      "checker on keeps the slots and face numbers")
check(len(bare.material_slots) == 1 and bare.material_slots[0].material.name == U.CHECKER, "checker on a mesh without materials")
check(U.checker_on(bpy.context), "checker_on")
check(U.checker_save_pre in bpy.app.handlers.save_pre and U.checker_save_post in bpy.app.handlers.save_post, "save handlers")
saved = os.path.join(tempfile.mkdtemp(prefix="m3d_test_"), "checker.blend")
bpy.ops.wm.save_as_mainfile(filepath=saved, copy=True)
check(all(U.CHECKER in ob for ob in (box, bare)), "checker is back after saving")
check([s.material.name for s in box.material_slots] == [U.CHECKER] * 2, "checker slots restored after saving")
bpy.ops.m3d.uv_checker()
check([s.material.name for s in box.material_slots] == ["MatA", "MatB"] and len(bare.material_slots) == 0, "checker off")
check(box.data.polygons[0].material_index == 1, "face numbers survive the checker")
bpy.ops.m3d.uv_checker()
bpy.ops.wm.open_mainfile(filepath=saved)
box = bpy.data.objects["CheckerBox"]
check(bpy.data.materials.get(U.CHECKER) is None and bpy.data.images.get(U.CHECKER) is None, "saved file has no checker material or image")
check(U.CHECKER not in box and [s.material.name for s in box.material_slots] == ["MatA", "MatB"] and
      len(bpy.data.objects["CheckerBare"].material_slots) == 0, "saved file has the original materials")

# ----------------------------------------------------------------------------------------------------
# Phase 3a: Texture workspace (tabs, pages, gates, channels, saving, bake, export, keys).
import m3d_texture as T
import numpy as np

tex_ws = bpy.data.workspaces["Texture"]
tex_tabs = W.DOCK_TABS['TEXTURE']
check([t.label for t in tex_tabs['RIGHT']] == ["Layers", "Brush", "Library", "Bake", "Export", "Display"], "Texture dock tabs")
check([t.label for t in tex_tabs['LEFT']] == ["Brushes"], "Texture left tray tab")
for tab in (*tex_tabs['RIGHT'], *tex_tabs['LEFT']):
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("tex_"), "Texture page tab " + tab.id)
tex_pages = {t.page for side in tex_tabs.values() for t in side}
check({c.page for c in (*T.classes, *m3d_library.classes) if hasattr(c, "page")} == tex_pages, "every Texture page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in T.classes
          if not issubclass(c, bpy.types.PropertyGroup)), "Texture classes registered")
check(m3d_ui.shelves_for('TEXTURE') == ['TEXTURE_BRUSHES', 'TEXTURE_CHANNELS', 'TEXTURE_OUTPUT', 'CUSTOM']
      and 'TEXTURE' in m3d_ui.STATUS_LINES, "Texture shelf tabs and Status Line")
check(W.KIND_MODES_IN_MENU_BAR['TEXTURE'] == {'TEXTURE_PAINT'}, "Texturing menu set covers the paint header")
check(len(T.BRUSHES) == 10 and [n for _l, n in T.BRUSHES][:3] == ["Paint Soft", "Paint Hard", "Airbrush"], "brush grid")
check([ch.label for ch in T.CHANNELS] == ["Base Color", "Roughness", "Metallic", "Normal", "Height", "Emission"], "channels")

# Brush assets exist in the essentials file.
asset_file = os.path.join(bpy.utils.system_resource('DATAFILES'), "assets", "brushes", "essentials_brushes-mesh_texture.blend")
with bpy.data.libraries.load(asset_file, assets_only=True) as (src, _dst):
    tex_asset_names = set(src.brushes)
for label, name in (*T.BRUSHES, *T.MORE_BRUSHES):
    check(name in tex_asset_names, "texture brush asset %r" % name)

# Keys: Image Paint keymap only, free in the keymaps around it.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
for idname, key, mods, props in (("paint.brush_colors_flip", 'X', dict(shift=True), {}),
                                 ("m3d.tex_channel_cycle", 'C', dict(), {"delta": 1}),
                                 ("m3d.tex_channel_cycle", 'C', dict(shift=True), {"delta": -1})):
    want = {"shift": False, "ctrl": False, "alt": False, **mods}
    item = find("Image Paint", idname, key, **want)
    check(item and all(getattr(item[0].properties, k) == v for k, v in props.items()), "Texture key %s %s" % (key, mods))
    others = [(km.name, k.idname) for km in kc.keymaps for k in km.keymap_items
              if k.type == key and all(getattr(k, m) == v for m, v in want.items()) and not k.oskey
              and (km.name, k.idname) != ("Image Paint", idname)
              and km.name in {"Window", "Screen", "Screen Editing", "Frames", "Property Editor", "Image Paint"}]
    check(not others, "Texture key %s %s is free: %s" % (key, mods, others))
check(not find("Image Paint", "paint.brush_colors_flip", 'X', shift=False), "plain X no longer swaps colors in Image Paint")
check(find("Image Paint", "brush.scale_size", 'LEFT_BRACKET') and find("Image Paint", "brush.scale_size", 'RIGHT_BRACKET'),
      "[ and ] change the brush size in Image Paint")

# Menus of the Texturing set have real entries.
for mid in ("M3D_MT_paint", "M3D_MT_layers", "M3D_MT_bake", "M3D_MT_export"):
    check(len(m3d_ui.MENUS[mid][1]) >= 2, "Texturing menu has entries: " + mid)
check(sum(e.get("idname") == "m3d.tex_channel" for e in m3d_ui.MENUS["M3D_MT_layers"][1]) == 6, "Layers menu has every channel")

# Gates: page panels without a mesh, in Object Mode, without UVs / material.
for ob in list(bpy.data.objects):
    if ob.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(ob)


class TCtx(SCtx):
    """Context of a Texture dock: the real one with this workspace."""
    def __init__(self, side='RIGHT'):
        super().__init__(side)
        self.workspace = tex_ws


def tex_panels(page):
    return [c for c in (*T.classes, *m3d_library.classes) if getattr(c, "page", None) == page and hasattr(c, "poll")]


def tex_shown(page):
    side = 'LEFT' if page == "tex_brushes" else 'RIGHT'
    setattr(tex_ws, "m3d_page_" + side.lower(), page)
    ctx = TCtx(side)
    return [c.__name__ for c in tex_panels(page) if c.poll(ctx)]


def tex_gated(page):
    names = tex_shown(page)
    return len(names) == 1 and names[0].endswith("_gate")


for page in T.GATES:
    check(tex_gated("tex_" + page), "tex_%s without a mesh shows its message only: %s" % (page, tex_shown("tex_" + page)))
check(not any(n.endswith("_gate") for n in tex_shown("tex_library") + tex_shown("tex_display")), "Library and Display need no mesh")
check(T.missing(bpy.context) == ['MESH'], "missing without a mesh")
bpy.ops.m3d.add_primitive(kind='CUBE')
cube = bpy.context.active_object
check(T.missing(bpy.context) == ['MATERIAL', 'MODE'], "a new cube has UVs, but no material, and is in Object Mode: %s" % T.missing(bpy.context))
check(tex_gated("tex_layers") and not tex_gated("tex_bake") and tex_gated("tex_export"), "gates in Object Mode")
cube.data.uv_layers.remove(cube.data.uv_layers[0])
check(T.missing(bpy.context) == ['UV', 'MATERIAL', 'MODE'] and tex_gated("tex_bake"),
      "missing UVs gate the Bake tab: %s" % T.missing(bpy.context))
check(bpy.ops.m3d.tex_unwrap() == {'FINISHED'} and len(cube.data.uv_layers) == 1 and cube.mode == 'OBJECT',
      "Auto Unwrap fix adds UVs and keeps the mode")
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
check(T.missing(bpy.context) == ['MATERIAL'] and bpy.context.mode == 'PAINT_TEXTURE', "only the material is missing: %s" % T.missing(bpy.context))
check(tex_gated("tex_layers") and tex_gated("tex_brushes") and tex_gated("tex_brush"), "no material gates the paint pages")
check(not bpy.ops.m3d.tex_channel.poll(), "no channel without a material")
check(bpy.ops.m3d.tex_unwrap() == {'FINISHED'} and cube.mode == 'TEXTURE_PAINT', "Auto Unwrap from Texture Paint Mode keeps it")
check(bpy.ops.m3d.tex_add_material() == {'FINISHED'} and cube.active_material is not None and T.missing(bpy.context) == [],
      "Add Material fix")
for page in tex_pages:
    names = tex_shown(page)
    check(names and not any(n.endswith("_gate") for n in names), "%s panels in Texture Paint Mode: %s" % (page, names))
check([n for n in tex_shown("tex_brushes") if n.endswith("_canvas")], "tray offers Add Base Color without paint slots")

# Channels: every channel adds its slot with the right color space; a second click only selects it.
T_scene = bpy.context.scene
T_scene.m3d_tex.resolution = '128'
mat = cube.active_material
want_space = {ch.id: 'sRGB' if ch.srgb else 'Non-Color' for ch in T.CHANNELS}
for ch in T.CHANNELS:
    check(bpy.ops.m3d.tex_channel(channel=ch.id) == {'FINISHED'}, "add channel " + ch.id)
    found = T.channel_slots(mat)
    img = found[ch.id][1] if ch.id in found else None
    check(img is not None and tuple(img.size) == (128, 128), "%s slot is 128 px" % ch.id)
    check(img is not None and img.colorspace_settings.name == want_space[ch.id],
          "%s color space %s" % (ch.id, img and img.colorspace_settings.name))
    check(T.active_channel(mat) == ch.id, "%s is the active channel (%s)" % (ch.id, T.active_channel(mat)))
    if img is not None and ch.id != 'EMISSION':
        check(all(abs(a - b) < 1e-3 for a, b in zip(img.generated_color, ch.color)),
              "%s starts as %s (%s)" % (ch.id, ch.color, tuple(img.generated_color)))
check(len(mat.texture_paint_slots) == 6, "six paint slots: %d" % len(mat.texture_paint_slots))
check(mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value == 1.0, "emission lights the shader")
bpy.ops.m3d.tex_channel(channel='ROUGHNESS')
check(len(mat.texture_paint_slots) == 6 and T.active_channel(mat) == 'ROUGHNESS', "clicking an existing channel only selects it")
bpy.ops.m3d.tex_channel_cycle(delta=1)
check(T.active_channel(mat) == 'METALLIC', "next channel")
bpy.ops.m3d.tex_channel_cycle(delta=-1)
bpy.ops.m3d.tex_channel_cycle(delta=-1)
check(T.active_channel(mat) == 'BASE_COLOR', "previous channel")
bpy.ops.m3d.tex_channel_cycle(delta=-1)
check(T.active_channel(mat) == 'EMISSION', "channels wrap around")
check(T.channel_of(mat, T.channel_slots(mat)['HEIGHT'][1]) == 'HEIGHT', "Height is found through the Bump node")
check(T.channel_of(mat, T.channel_slots(mat)['NORMAL'][1]) == 'NORMAL', "Normal is found through the Normal Map node")
# The checker map gates painting and refuses channel changes.
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.m3d.uv_checker()
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
check('CHECKER' in T.missing(bpy.context) and tex_gated("tex_layers") and bpy.ops.m3d.tex_channel(channel='BASE_COLOR') == {'CANCELLED'},
      "the checker map gates painting: %s" % T.missing(bpy.context))
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.m3d.uv_checker()
check(not U.checker_on(bpy.context) and T.missing(bpy.context) == ['MODE'], "checker off: %s" % T.missing(bpy.context))
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')

# Every page panel draws (recorded calls name real operators, properties and icons).
ctx = TCtx()
for page in sorted(tex_pages):
    setattr(tex_ws, "m3d_page_" + ("left" if page == "tex_brushes" else "right"), page)
    for cls in tex_panels(page):
        if cls.poll(TCtx('LEFT' if page == "tex_brushes" else 'RIGHT')):
            try:
                check_calls(cls.__name__, draw_stub(cls, ctx))
            except Exception as err:
                check(False, "%s draw: %r" % (cls.__name__, err))
# ...also the gates and the panels that do not need paint mode, in Object Mode too.
for mode in ('OBJECT', 'TEXTURE_PAINT'):
    bpy.ops.object.mode_set(mode=mode)
    for cls in (*T.PAGE_GATES, m3d_library.PROPERTIES_PT_m3d_lib_browse, m3d_library.PROPERTIES_PT_m3d_lib_assets,
                T.PROPERTIES_PT_m3d_tx_channel_view, T.PROPERTIES_PT_m3d_tx_checker):
        try:
            check_calls(cls.__name__ + " " + mode, draw_stub(cls, ctx))
        except Exception as err:
            check(False, "%s draw in %s: %r" % (cls.__name__, mode, err))
log = []
T.draw_status_line(Rec(log), ctx)
check_calls("Texture status line", log)
props_drawn = {r._args[1] for r in log if r._kind == "prop"}
channels_drawn = [r.values().get("channel") for r in log if r._kind == "operator" and r._args[0] == "m3d.tex_channel"]
check({"use_mirror_x", "use_mirror_y", "use_mirror_z", "resolution"} <= props_drawn and channels_drawn == [c.id for c in T.CHANNELS],
      "Texture status line controls: %s %s" % (props_drawn, channels_drawn))
check(len([r for r in log if r._kind == "operator" and r._args[0] == "m3d.call"]) >= 5, "status line mode and display buttons")
for key in m3d_ui.shelves_for('TEXTURE'):
    log = []
    ctx.window_manager.m3d_shelf = key
    m3d_ui.draw_shelf(Rec(log), ctx)
    check_calls("shelf " + key, log)

# Brushes activate; the tray knows which is active.
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
for label, name in (*T.BRUSHES, *T.MORE_BRUSHES):
    bpy.ops.brush.asset_activate(**T.brush_props(name))
    check(S.active_brush_id(bpy.context) == T.BRUSH_ASSET + name, "texture brush %s active (is %r)" % (name, S.active_brush_id(bpy.context)))

# Images the user painted are kept with the file: packed when they have no file, written when they have one.
base, rough, metal = (T.channel_slots(mat)[c][1] for c in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC'))
base_name = base.name
ramp = np.tile(np.linspace(0.0, 1.0, 128, dtype=np.float32), 128)   # left to right
ramp_back = ramp[::-1]


def paint(image, values):
    """Fill an image with one color (a tuple) or a grey ramp (an array)."""
    px = np.ones((128 * 128, 4), np.float32)
    px[:, :3] = np.asarray(values, np.float32).reshape(-1, 1) if np.size(values) > 3 else values
    image.pixels.foreach_set(px.ravel())
    image.update()
    return px


def read(image):
    px = np.empty(len(image.pixels), np.float32)
    image.pixels.foreach_get(px)
    return px.reshape(-1, 4)


paint(base, (0.6, 0.3, 0.1))
paint(rough, ramp)
paint(metal, (0.8, 0.8, 0.8))
check(base.is_dirty and rough.is_dirty and base in T.modified_images(), "painted images are modified")
check(T.save_pre in bpy.app.handlers.save_pre, "save_pre handler is registered")
disk_path = os.path.join(tempfile.mkdtemp(prefix="m3d_test_"), "disk.png")
tmp = bpy.data.images.new("m3dTmp", 8, 8)
tmp.filepath_raw, tmp.file_format = disk_path, 'PNG'
tmp.save()
bpy.data.images.remove(tmp)
disk = bpy.data.images.load(disk_path)
disk.pixels.foreach_set(np.full(8 * 8 * 4, 0.5, np.float32))
disk.update()
check(disk.is_dirty and disk.source == 'FILE' and disk in T.modified_images(), "an image with a file is modified")
with open(disk_path, "rb") as fh:
    before = fh.read()
saved_n, packed_n = T.save_images()
with open(disk_path, "rb") as fh:
    after = fh.read()
check(saved_n == 1 and packed_n == 3 and base.packed_file is not None and disk.packed_file is None,
      "saved %d, packed %d" % (saved_n, packed_n))
check(before != after, "the image with a file was written to it")
check(not T.modified_images(), "nothing is left modified: %s" % [i.name for i in T.modified_images()])
# ...and through a real save: a repainted image comes back from the file.
paint(base, (0.25, 0.5, 0.75))
saved = os.path.join(tempfile.mkdtemp(prefix="m3d_test_"), "paint.blend")
bpy.ops.wm.save_as_mainfile(filepath=saved)
bpy.ops.wm.open_mainfile(filepath=saved)
T_scene = bpy.context.scene
back = bpy.data.images.get(base_name)
check(back is not None and back.packed_file is not None and abs(read(back)[0, 0] - 0.25) < 2 / 255 + 1e-4
      and back.colorspace_settings.name == 'sRGB', "the repainted image is in the saved file")

# Bake: all five maps on a small sphere; Cycles, the selection and the material are put back.
bpy.ops.object.mode_set(mode='OBJECT')
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
bpy.ops.m3d.add_primitive(kind='SPHERE')
ball = bpy.context.active_object
ball.name = "BakeBall"
bpy.ops.m3d.tex_add_material()
ball_mat = ball.active_material
nodes_before = sorted(n.name for n in ball_mat.node_tree.nodes)
mats_before = len(bpy.data.materials)
sets = ball.m3d_bake
sets.resolution, sets.margin, sets.samples = '128', 4, 4
for flag in ("use_normal", "use_ao", "use_curvature", "use_position", "use_thickness"):
    setattr(sets, flag, True)
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
T_scene.render.engine = 'BLENDER_EEVEE'
T_scene.cycles.samples = 77
check(bpy.ops.m3d.tex_bake() == {'FINISHED'}, "Bake runs")
check(T_scene.render.engine == 'BLENDER_EEVEE' and T_scene.cycles.samples == 77, "Cycles and its samples are put back")
check(ball.mode == 'TEXTURE_PAINT' and bpy.context.view_layer.objects.active == ball and ball.select_get(), "mode and selection restored")
check(ball.active_material == ball_mat and sorted(n.name for n in ball_mat.node_tree.nodes) == nodes_before
      and len(bpy.data.materials) == mats_before and len(ball.material_slots) == 1, "the material is unchanged after the bake")
for label in ("Normal", "AO", "Curvature", "Position", "Thickness"):
    img = bpy.data.images.get("BakeBall_" + label)
    check(img is not None and tuple(img.size) == (128, 128) and img.colorspace_settings.name == 'Non-Color'
          and img.use_fake_user, "baked %s map" % label)
    if img is not None:
        px = read(img)
        check(np.isfinite(px).all() and px[:, :3].max() > 0.0 and px[:, :3].max() <= 1.0 + 1e-4,
              "%s has content in 0-1 (max %s)" % (label, px[:, :3].max()))
check(sets.baked.split("|") == ["BakeBall_" + l for l in ("Normal", "AO", "Curvature", "Position", "Thickness")], "baked list: %s" % sets.baked)
check(bpy.data.images["BakeBall_Position"].is_float, "Position is baked in float")
bpy.ops.m3d.tex_bake()
check(len([i for i in bpy.data.images if i.name.startswith("BakeBall_")]) == 5, "baking again reuses the images")
for flag in ("use_normal", "use_ao", "use_curvature", "use_position", "use_thickness"):
    setattr(sets, flag, False)
check(bpy.ops.m3d.tex_bake() == {'CANCELLED'}, "no map ticked: no bake")

# Bake from a high-poly mesh: the rounded cube's edges show in the low-poly cube's normal map; the hidden
# high-poly mesh comes back hidden.
bpy.ops.object.mode_set(mode='OBJECT')
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
bpy.ops.m3d.add_primitive(kind='CUBE')
low = bpy.context.active_object
low.name = "Low"
bpy.ops.m3d.add_primitive(kind='CUBE')
high = bpy.context.active_object
high.name = "High"
bpy.ops.object.modifier_add(type='SUBSURF')
high.modifiers[0].levels = 3
bpy.ops.object.modifier_apply(modifier=high.modifiers[0].name)
check(len(high.data.polygons) > 100, "high-poly mesh has %d faces" % len(high.data.polygons))
bpy.context.view_layer.objects.active = low
for ob in (low, high):
    ob.select_set(ob is high)
sets = low.m3d_bake
check(bpy.ops.m3d.tex_bake_pick() == {'FINISHED'} and sets.high == high, "Use Selected as High Poly")
sets.resolution, sets.margin, sets.samples = '128', 4, 4
sets.use_normal = True
sets.use_ao = sets.use_curvature = sets.use_thickness = sets.use_position = False
high.hide_set(True)
check(bpy.ops.m3d.tex_bake() == {'FINISHED'}, "Bake from a high-poly mesh")
check(high.hide_get() and bpy.context.view_layer.objects.active == low and not high.select_get() and not low.select_get(),
      "high-poly visibility and selection restored: hidden %s, active %s, high selected %s, low selected %s" % (
          high.hide_get(), bpy.context.view_layer.objects.active.name, high.select_get(), low.select_get()))
normal_px = read(bpy.data.images["Low_Normal"])[:, :3]
check(normal_px[:, 0].std() > 0.01 or normal_px[:, 1].std() > 0.01, "the normal map shows the high-poly detail (std %s)" % normal_px.std(axis=0))
check(len(low.material_slots) == 0 and not [m for m in bpy.data.materials if m.name.startswith("m3dBake")],
      "a mesh without materials gets none, and no temporary material is left")
sets.high = None
sets.use_ao = True
check(bpy.ops.m3d.tex_bake() == {'FINISHED'}, "Bake without a high-poly mesh from the cube itself")
ao_img = bpy.data.images["Low_AO"]
paint(ao_img, (0.9, 0.9, 0.9))   # A known occlusion map for the export below.

# Export: Unreal / Unity / glTF files; the packed channels match the source maps.
bpy.ops.object.mode_set(mode='OBJECT')
bpy.data.objects.remove(high)
bpy.ops.m3d.tex_add_material()
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
T_scene.m3d_tex.resolution = '128'
for cid in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC', 'NORMAL', 'EMISSION'):
    bpy.ops.m3d.tex_channel(channel=cid)
slots = {c: i for c, (_n, i) in T.channel_slots(low.active_material).items()}
paint(slots['BASE_COLOR'], (0.6, 0.3, 0.1))
paint(slots['ROUGHNESS'], ramp)
paint(slots['METALLIC'], ramp_back)
paint(slots['NORMAL'], (0.5, 0.7, 1.0))
paint(slots['EMISSION'], (0.2, 0.4, 0.6))
out_dir = tempfile.mkdtemp(prefix="m3d_export_")
tx = T_scene.m3d_tex
tx.export_folder, tx.export_size, tx.export_preset = out_dir, 'SAME', 'UNREAL'
check(bpy.ops.m3d.tex_export() == {'FINISHED'}, "Unreal export runs")
files = sorted(os.listdir(out_dir))
check(files == ["T_Low_BC.png", "T_Low_E.png", "T_Low_N.png", "T_Low_ORM.png"], "Unreal files: %s" % files)
check(sorted(os.path.basename(p) for p in tx.export_files.split("|")) == files, "export list is kept")


def load_png(folder, name):
    img = bpy.data.images.load(os.path.join(folder, name))
    img.colorspace_settings.name = 'Non-Color'
    return read(img), img


tol = 2.0 / 255 + 1e-4
orm, orm_img = load_png(out_dir, "T_Low_ORM.png")
check(tuple(orm_img.size) == (128, 128), "ORM is 128 px")
check(np.abs(orm[:, 0] - 0.9).max() < tol, "ORM red is the occlusion map (error %s)" % np.abs(orm[:, 0] - 0.9).max())
check(np.abs(orm[:, 1] - ramp).max() < tol, "ORM green is the roughness map (error %s)" % np.abs(orm[:, 1] - ramp).max())
check(np.abs(orm[:, 2] - ramp_back).max() < tol, "ORM blue is the metallic map (error %s)" % np.abs(orm[:, 2] - ramp_back).max())
normal_out, _ = load_png(out_dir, "T_Low_N.png")
check(abs(normal_out[0, 1] - 0.3) < tol and abs(normal_out[0, 0] - 0.5) < tol, "Unreal normal map has the green channel flipped: %s" % normal_out[0])
base_out, _ = load_png(out_dir, "T_Low_BC.png")
check(np.abs(base_out[:, :3] - np.array([0.6, 0.3, 0.1])).max() < tol, "base color file matches the paint")
# Unity at a smaller size, without an occlusion map.
bpy.data.images.remove(ao_img)
out_dir2 = tempfile.mkdtemp(prefix="m3d_export_")
tx.export_preset, tx.export_size, tx.export_folder = 'UNITY', '64', out_dir2
check(bpy.ops.m3d.tex_export() == {'FINISHED'}, "Unity export runs")
files = sorted(os.listdir(out_dir2))
check(files == ["Low_Albedo.png", "Low_Emission.png", "Low_MetallicSmoothness.png", "Low_Normal.png"], "Unity files: %s" % files)
ms_px, ms = load_png(out_dir2, "Low_MetallicSmoothness.png")
check(tuple(ms.size) == (64, 64), "export size 64 resamples the maps")
cols = np.arange(64) * 2
small_rough, small_metal = ramp[None, cols].repeat(64, 0).ravel(), ramp_back[None, cols].repeat(64, 0).ravel()
visible = ms_px[:, 3] > 0.05   # Fully transparent pixels may lose their color in a PNG.
check(np.abs(ms_px[visible, 0] - small_metal[visible]).max() < tol and np.abs(ms_px[:, 3] - (1 - small_rough)).max() < tol,
      "Unity metallic in red and smoothness in alpha")
tx.export_preset = 'GLTF'
out_dir3 = tempfile.mkdtemp(prefix="m3d_export_")
tx.export_folder = out_dir3
check(bpy.ops.m3d.tex_export() == {'FINISHED'} and os.path.exists(os.path.join(out_dir3, "Low.glb"))
      and os.path.getsize(os.path.join(out_dir3, "Low.glb")) > 1000, "glTF export writes a .glb: %s" % os.listdir(out_dir3))
tx.export_preset, tx.export_folder = 'UNITY', "//textures/"
check(bpy.ops.m3d.tex_export() == {'FINISHED'} and os.path.isdir(os.path.join(os.path.dirname(saved), "textures")),
      "a // folder is next to the saved file")
bpy.ops.object.mode_set(mode='OBJECT')
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
check(not bpy.ops.m3d.tex_export.poll(), "nothing to export without a mesh")
bpy.ops.wm.read_homefile(app_template="")
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
bpy.ops.m3d.add_primitive(kind='CUBE')
bpy.ops.m3d.tex_add_material()
try:
    res = bpy.ops.m3d.tex_export()
except RuntimeError as err:   # An operator that reports an error raises it in Python.
    res = str(err)
check(not bpy.data.filepath and "Save the file first" in str(res), "a // folder needs a saved file: %s" % res)

# ----------------------------------------------------------------------------------------------------
# Phase 3b: the paint layer stack (data, node chains, paint target, merge, flatten, export, safety).
import m3d_layers as LY

check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in LY.classes
          if not issubclass(c, bpy.types.PropertyGroup)), "layer classes registered")
check(hasattr(bpy.types.Material, "m3d_layers") and hasattr(bpy.types.Material, "m3d_layer_index")
      and hasattr(bpy.types.Material, "m3d_channel"), "Material layer properties")
check(T.CHANNELS is LY.CHANNELS and T.principled_of is LY.principled_of, "channels live in m3d_layers")
check([b for b, _l in LY.BLENDS] == ['MIX', 'MULTIPLY', 'ADD', 'OVERLAY', 'SCREEN', 'SOFT_LIGHT', 'SUBTRACT', 'DIFFERENCE',
                                      'COLOR', 'DARKEN', 'LIGHTEN'], "blend modes")
node_blends = {i.identifier for i in bpy.types.ShaderNodeMix.bl_rna.properties['blend_type'].enum_items}
check({b for b, _l in LY.BLENDS} <= node_blends and set(LY.BLEND_FUNCTIONS) == {b for b, _l in LY.BLENDS},
      "every blend mode is a Mix node blend type with numpy math")
layer_ops = {e.get("idname") for e in m3d_ui.MENUS["M3D_MT_layers"][1]}
check({"m3d.layer_add", "m3d.layer_duplicate", "m3d.layer_remove", "m3d.layer_move", "m3d.layer_visible",
       "m3d.layer_mask_add", "m3d.layer_mask_remove", "m3d.layer_mask_invert", "m3d.layer_paint_mask",
       "m3d.layer_merge_down", "m3d.layer_flatten", "m3d.layer_convert"} <= layer_ops, "Layers menu has the layer operators")


def clean_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def fill_rgb(image, rgb):
    w, h = image.size
    LY.write_pixels(image, np.tile(np.array([*rgb, 1.0], np.float32), (w * h, 1)))


def blend_py(mode, b, s):
    """One channel of what the Mix node does before the factor (worked out by hand, independent of the numpy code)."""
    if mode == 'MIX':
        return s
    if mode == 'MULTIPLY':
        return b * s
    if mode == 'ADD':
        return b + s
    if mode == 'OVERLAY':
        return 2 * b * s if b < 0.5 else 1 - 2 * (1 - b) * (1 - s)
    raise KeyError(mode)


def over_py(b, s, a, mode):
    return min(1.0, max(0.0, b + a * (blend_py(mode, b, s) - b)))


def srgb_py(v):
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def linear_py(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def fresh_cube(name, size='64'):
    """A clean scene with one cube (UVs, material), channel size `size`, in Texture Paint Mode."""
    clean_scene()
    bpy.ops.m3d.add_primitive(kind='CUBE')
    o = bpy.context.active_object
    o.name = name
    bpy.ops.m3d.tex_add_material()
    bpy.context.scene.m3d_tex.resolution = size
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    return o, o.active_material


def level(mat, ch_id):
    """The Mix nodes of a channel's chain, bottom to top, followed from the Principled BSDF."""
    bsdf = LY.principled_of(mat)
    if ch_id in LY.SOCKETS:
        links = bsdf.inputs[LY.SOCKETS[ch_id]].links
        node = links[0].from_node if links else None
    else:
        node = bsdf.inputs["Normal"].links[0].from_node
        if node.type == 'BUMP' and ch_id == 'HEIGHT':
            node = node.inputs["Height"].links[0].from_node
        else:
            if node.type == 'BUMP':
                node = node.inputs["Normal"].links[0].from_node
            node = node.inputs["Color"].links[0].from_node
    out = []
    while node is not None and node.type == 'MIX':
        out.append(node)
        links = node.inputs[6].links
        node = links[0].from_node if links else None
    return out[::-1]


def expect_chain(mat, ch_id, msg):
    """The chain of `ch_id` has one Mix per layer with content, in stack order, with each layer's blend mode."""
    layers = [l for l in mat.m3d_layers if LY.has_content(l, ch_id)]
    got = level(mat, ch_id) if layers else []
    want = [LY.part(ch_id, l.uid, "mix") for l in layers]
    check([n.name for n in got] == want, "%s: %s chain is %s, want %s" % (msg, ch_id, [n.name for n in got], want))
    modes = [('MIX' if ch_id == 'NORMAL' else l.blend) for l in layers]
    check([n.blend_type for n in got] == modes, "%s: %s blend modes %s" % (msg, ch_id, [n.blend_type for n in got]))
    for l, n in zip(layers, got):
        opv = mat.node_tree.nodes[LY.part(ch_id, l.uid, "opv")].inputs[1].default_value
        check(abs(opv - (l.opacity if l.visible else 0.0)) < 1e-5, "%s: %s opacity node of %s is %s" % (msg, ch_id, l.name, opv))
    return got


def slot_image(mat):
    images = list(mat.texture_paint_images)
    return images[mat.paint_active_slot] if mat.paint_active_slot < len(images) else None


def small(name, values, srgb=False, alpha=True):
    """A 4 x 4 image: `values` is (4, 4, 4) RGBA."""
    im = bpy.data.images.new(name, 4, 4, alpha=alpha, is_data=not srgb)
    LY.write_pixels(im, np.asarray(values, np.float32))
    return im


def set_mask(layer, image, invert=False):
    """The layer's mask: a Paint effect holding `image` (and an Invert effect on top)."""
    with LY.muted():
        LY.add_effect(layer, 'PAINT').image = image
        if invert:
            LY.add_effect(layer, 'INVERT')


# --- Migration: the 3a paint slots become the Base layer, nothing painted is lost
cube, mat = fresh_cube("Stack")
for cid in ('BASE_COLOR', 'ROUGHNESS', 'NORMAL', 'HEIGHT', 'EMISSION'):
    bpy.ops.m3d.tex_channel(channel=cid)
legacy = {c: img for c, (_i, img) in T.channel_slots(mat).items()}
check(len(legacy) == 5 and not mat.m3d_layers, "five 3a channels, no layers: %s" % sorted(legacy))
fill_rgb(legacy['BASE_COLOR'], (0.6, 0.3, 0.1))
fill_rgb(legacy['ROUGHNESS'], (0.2, 0.2, 0.2))
base_px = {c: read(img).copy() for c, img in legacy.items()}
base_names = {c: img.name for c, img in legacy.items()}
check(LY.rebuild_all(mat) is False and not any(LY.TAG in n.keys() for n in mat.node_tree.nodes),
      "rebuilding a material without layers adds nothing")
check(bpy.ops.m3d.layer_add(kind='PAINT') == {'FINISHED'}, "Add Paint Layer on a material with slots")
check([l.name for l in mat.m3d_layers] == ["Base", "Paint Layer"] and mat.m3d_layer_index == 1, "Base and the new layer: %s" % [l.name for l in mat.m3d_layers])
base = mat.m3d_layers[0]
check({c: e.image.name for c in legacy for e in [LY.entry_of(base, c)] if e.image} == base_names
      and all(LY.entry_of(base, c).use == (c in legacy) for c in LY.CHANNEL_BY_ID), "the 3a images are the Base layer's: %s" % base_names)
check(all(np.array_equal(read(LY.entry_of(base, c).image), base_px[c]) for c in legacy), "no pixel of the old slots changed")
direct = [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and LY.TAG not in n.keys()]
check(not direct and not [n for n in mat.node_tree.nodes if n.type in {'NORMAL_MAP', 'BUMP'} and LY.TAG not in n.keys()],
      "the old image, Normal Map and Bump nodes are gone: %s" % [n.name for n in direct])
for cid in legacy:
    expect_chain(mat, cid, "after migration")
top = mat.m3d_layers[1]
check(sum(e.image is not None for e in top.channels) == 1 and LY.entry_of(top, T.active_channel(mat)).image is not None,
      "the new layer only has the image of the active channel (%s): %s" % (T.active_channel(mat),
                                                                        [e.channel for e in top.channels if e.image]))
check(LY.entry_of(top, 'EMISSION').image is not None and LY.entry_of(top, 'EMISSION').image.depth == 32
      and tuple(LY.entry_of(top, 'EMISSION').image.generated_color) == (0.0, 0.0, 0.0, 0.0), "layers above the base start transparent")
check(slot_image(mat) == LY.entry_of(top, 'EMISSION').image, "the brush paints the new layer's Emission image")
check(bpy.ops.m3d.tex_channel(channel='BASE_COLOR') == {'FINISHED'} and LY.entry_of(top, 'BASE_COLOR').image is not None
      and slot_image(mat) == LY.entry_of(top, 'BASE_COLOR').image and T.active_channel(mat) == 'BASE_COLOR'
      and LY.entry_of(top, 'BASE_COLOR').image.colorspace_settings.name == 'sRGB'
      and LY.entry_of(top, 'BASE_COLOR').image.size[0] == 64, "choosing a channel makes the layer's image for it")
check(sum(e.image is not None for e in top.channels) == 2, "images are made one channel at a time")
check(set(T.channel_slots(mat)) == set(legacy), "channel_slots follows the stack: %s" % sorted(T.channel_slots(mat)))
bpy.ops.m3d.tex_channel_cycle(delta=1)
check(T.active_channel(mat) == 'ROUGHNESS' and LY.entry_of(top, 'ROUGHNESS').image is not None
      and slot_image(mat) == LY.entry_of(top, 'ROUGHNESS').image, "C cycles channels on the active layer")
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')

# --- Node chains: blend, opacity, visibility, order, duplicate, delete
bsdf = LY.principled_of(mat)
chain = expect_chain(mat, 'BASE_COLOR', "two layers")
check(len(chain) == 2 and not chain[0].inputs[6].links and chain[0].inputs[6].default_value[0] > 0
      and bsdf.inputs["Base Color"].links[0].from_node == chain[1], "bottom Mix starts from the channel color, the top feeds the shader")
check(bsdf.inputs["Normal"].links[0].from_node.type == 'BUMP'
      and bsdf.inputs["Normal"].links[0].from_node.inputs["Normal"].links[0].from_node.type == 'NORMAL_MAP', "Normal Map feeds Bump feeds the shader")
check(bsdf.inputs["Emission Strength"].default_value == 1.0, "emission lights the shader")
frames = [n for n in mat.node_tree.nodes if n.type == 'FRAME']
check(len(frames) == 5 and all(n.get(LY.TAG) for n in frames) and all(n.parent in frames for n in mat.node_tree.nodes
      if n.type == 'MIX'), "one frame per channel holds its chain")
nodes_ptr = {n.name: n.as_pointer() for n in mat.node_tree.nodes}
top.blend = 'MULTIPLY'
top.opacity = 0.4
expect_chain(mat, 'BASE_COLOR', "blend and opacity")
check({n.name: n.as_pointer() for n in mat.node_tree.nodes} == nodes_ptr, "blend and opacity only change values (no node is remade)")
top.visible = False
expect_chain(mat, 'BASE_COLOR', "hidden")
check(len(level(mat, 'BASE_COLOR')) == 2, "a hidden layer keeps its nodes (opacity 0)")
top.visible = True
top.blend = 'MIX'
top.opacity = 1.0
check(bpy.ops.m3d.layer_move(delta=-1) == {'FINISHED'} and [l.name for l in mat.m3d_layers] == ["Paint Layer", "Base"]
      and mat.m3d_layer_index == 0, "Move Down")
expect_chain(mat, 'BASE_COLOR', "moved down")
expect_chain(mat, 'ROUGHNESS', "moved down")
check(bpy.ops.m3d.layer_move(delta=-1) == {'CANCELLED'}, "cannot move below the bottom")
check(bpy.ops.m3d.layer_move(delta=1) == {'FINISHED'} and mat.m3d_layers[1].name == "Paint Layer", "Move Up")
expect_chain(mat, 'BASE_COLOR', "moved up")
check(slot_image(mat) == LY.entry_of(mat.m3d_layers[1], 'BASE_COLOR').image, "the paint target follows the moved layer")
# Duplicate: images are copies.
check(bpy.ops.m3d.layer_duplicate() == {'FINISHED'} and [l.name for l in mat.m3d_layers] == ["Base", "Paint Layer", "Paint Layer Copy"]
      and mat.m3d_layer_index == 2, "Duplicate: %s" % [l.name for l in mat.m3d_layers])
orig, dup = mat.m3d_layers[1], mat.m3d_layers[2]
check(orig.uid != dup.uid and all((LY.entry_of(orig, c).image is None) == (LY.entry_of(dup, c).image is None) for c in LY.CHANNEL_BY_ID)
      and all(LY.entry_of(dup, c).image != LY.entry_of(orig, c).image for c in LY.CHANNEL_BY_ID if LY.entry_of(orig, c).image),
      "the copy has its own images")
for cid in legacy:
    expect_chain(mat, cid, "duplicated")
check(slot_image(mat) == LY.entry_of(dup, 'BASE_COLOR').image, "the copy is the paint target")
# Delete removes the copy's images, nothing else.
dup_images = [e.image.name for e in dup.channels if e.image]
n_images = len(bpy.data.images)
check(bpy.ops.m3d.layer_remove() == {'FINISHED'} and [l.name for l in mat.m3d_layers] == ["Base", "Paint Layer"]
      and mat.m3d_layer_index == 1, "Delete")
check(not [n for n in dup_images if n in bpy.data.images] and len(bpy.data.images) == n_images - len(dup_images),
      "the deleted layer's images are gone: %s" % dup_images)
check(sum(e.image is not None for e in mat.m3d_layers[1].channels) == len(dup_images)
      and all(e.image.name in bpy.data.images for e in mat.m3d_layers[1].channels if e.image), "the other layers keep theirs")
for cid in legacy:
    expect_chain(mat, cid, "after delete")

# --- Delete keeps images something else uses
shared = bpy.data.images.new("m3dShared", 4, 4)
LY.add_layer(mat, 'PAINT', "Extra")
e_extra = LY.entry_of(mat.m3d_layers[2], 'ROUGHNESS')
e_extra.image = shared
e_other = LY.entry_of(mat.m3d_layers[1], 'METALLIC')
e_other.image, e_other.use = shared, True
user_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
user_tex.name = "UserTex"
user_tex.image = bpy.data.images.new("m3dUserImage", 4, 4)
LY.entry_of(mat.m3d_layers[2], 'METALLIC').image = user_tex.image
LY.entry_of(mat.m3d_layers[2], 'METALLIC').use = True
mat.m3d_layer_index = 2
check(bpy.ops.m3d.layer_remove() == {'FINISHED'} and "m3dShared" in bpy.data.images, "a shared image survives Delete")
check("m3dUserImage" in bpy.data.images and mat.node_tree.nodes["UserTex"].image.name == "m3dUserImage",
      "an image a user node uses survives Delete")
LY.entry_of(mat.m3d_layers[1], 'METALLIC').image = None
LY.entry_of(mat.m3d_layers[1], 'METALLIC').use = False
bpy.data.images.remove(shared)
mat.node_tree.nodes.remove(user_tex)
bpy.data.images.remove(bpy.data.images["m3dUserImage"])

# --- User nodes are left alone by every rebuild
noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
noise.name, noise.location = "UserNoise", (-1234, 567)
noise.inputs["Scale"].default_value = 7.0
mat.node_tree.links.new(noise.outputs["Fac"], bsdf.inputs["Alpha"])
ptr = noise.as_pointer()
bsdf.inputs["Specular IOR Level"].default_value = 0.77
for fn in (lambda: bpy.ops.m3d.layer_add(kind='FILL'), lambda: bpy.ops.m3d.layer_move(delta=1), lambda: LY.rebuild_all(mat),
           lambda: bpy.ops.m3d.layer_duplicate(), lambda: bpy.ops.m3d.layer_remove(), lambda: bpy.ops.m3d.layer_remove()):
    fn()
un = mat.node_tree.nodes.get("UserNoise")
check(un is not None and un.as_pointer() == ptr and tuple(un.location) == (-1234, 567) and un.inputs["Scale"].default_value == 7.0
      and bsdf.inputs["Alpha"].links and bsdf.inputs["Alpha"].links[0].from_node == un
      and abs(bsdf.inputs["Specular IOR Level"].default_value - 0.77) < 1e-6, "user nodes, links and values survive rebuilds")
check(not [n for n in mat.node_tree.nodes if n.get(LY.TAG) and n.name.split(".")[0] != LY.TAG], "our nodes carry our prefix")
mat.node_tree.nodes.remove(un)
check([l.name for l in mat.m3d_layers] == ["Base", "Paint Layer"], "back to two layers: %s" % [l.name for l in mat.m3d_layers])

# --- Fill layers, masks, the paint target
mat.m3d_layer_index = 1
n_before = len(mat.m3d_layers)
check(bpy.ops.m3d.layer_add(kind='FILL') == {'FINISHED'} and mat.m3d_layers[2].kind == 'FILL' and mat.m3d_layers[2].name == "Fill Layer"
      and mat.m3d_layer_index == 2, "Add Fill Layer above the active layer")
fill = mat.m3d_layers[2]
check([e.channel for e in fill.channels if e.use] == ['BASE_COLOR'] and not any(e.image for e in fill.channels),
      "a fill layer has Base Color and no images")
fill.channels[0].color = (0.2, 0.4, 0.6, 1.0)
mix = expect_chain(mat, 'BASE_COLOR', "fill")[-1]
check(not mix.inputs[7].links and all(abs(a - b) < 1e-5 for a, b in zip(mix.inputs[7].default_value, (0.2, 0.4, 0.6, 1.0))),
      "the fill color is the Mix node's second color")
fill.channels[0].color = (0.9, 0.1, 0.1, 1.0)
check(abs(mix.inputs[7].default_value[0] - 0.9) < 1e-5, "changing the fill only sets the value")
check(slot_image(mat) is not None and slot_image(mat).name == LY.SCRATCH and slot_image(mat) not in LY.stack_images(mat),
      "a fill layer without a mask aims the brush at the scratch image, not at a layer image")
check(bpy.ops.m3d.tex_channel(channel='ROUGHNESS') == {'CANCELLED'}, "painting a fill layer is refused")
check(slot_image(mat).name == LY.SCRATCH and slot_image(mat) not in LY.stack_images(mat), "...and the brush stays on the scratch image")
scratch_node = mat.node_tree.nodes["%s.scratch" % LY.TAG]
check(not scratch_node.inputs["Vector"].links and not scratch_node.outputs[0].links and scratch_node[LY.TAG] == "SCRATCH"
      and not slot_image(mat).use_fake_user, "the scratch node is tagged and connects to nothing")
LY.write_pixels(slot_image(mat), np.ones(8 * 8 * 4, np.float32))
check(slot_image(mat) not in T.modified_images() and tuple(slot_image(mat).size) == (8, 8), "the scratch image is never saved")
LY.rebuild_all(mat)
check(mat.node_tree.nodes.get("%s.scratch" % LY.TAG) is not None, "rebuilds keep the scratch node")
check(all(i not in LY.stack_images(mat) for i in [mat.texture_paint_images[mat.paint_active_slot]]), "paint_active_slot is not a layer image")
check(T.active_channel(mat) == 'ROUGHNESS' and not LY.entry_of(fill, 'ROUGHNESS').image, "a fill layer never gets an image")
check(not (bpy.ops.m3d.layer_mask_remove.poll()), "no mask to remove yet")
check(bpy.ops.m3d.layer_mask_add(fill='BLACK') == {'FINISHED'} and [e.kind for e in fill.mask_stack] == ['PAINT'] and fill.paint_mask
      and LY.paint_effect(fill).image.colorspace_settings.name == 'Non-Color' and LY.paint_effect(fill).image.size[0] == 64, "Add Mask (black)")
fmask = LY.paint_effect(fill).image
check(read(fmask)[:, :3].max() == 0.0, "a black mask hides the layer")
check(slot_image(mat) == fmask, "Paint Mask: the brush paints the mask of the fill layer")
mix = expect_chain(mat, 'BASE_COLOR', "masked")[-1]
mask_nodes = [n for n in mat.node_tree.nodes if n.get(LY.TAG) == "MASK" and n.get("m3d_mask") == fill.uid]
check(any(n.type == 'TEX_IMAGE' and n.image == fmask for n in mask_nodes), "the mask's Paint effect is an image node in its chain")
check(bpy.ops.m3d.layer_mask_invert() == {'FINISHED'} and fill.mask_stack[-1].kind == 'INVERT'
      and any(n.type == 'GROUP' and n.node_tree.name == "m3d_mask.invert" for n in mat.node_tree.nodes if n.get("m3d_mask") == fill.uid),
      "Invert Mask adds an Invert effect (a node group in the mask chain)")
check(not bpy.ops.m3d.layer_mask_add.poll(), "Add Mask is for a layer without a mask")
check(bpy.ops.m3d.layer_paint_mask() == {'FINISHED'} and not fill.paint_mask and slot_image(mat) == fmask,
      "Paint Mask toggles off, but a fill layer's only paintable image is its mask's Paint effect")
check(bpy.ops.m3d.tex_channel(channel='METALLIC') == {'FINISHED'} and slot_image(mat) == fmask and T.active_channel(mat) == 'METALLIC',
      "channels can be picked while a masked fill layer is active")
# A paint layer: mask target vs channel target.
mat.m3d_layer_index = 1
paint_layer = mat.m3d_layers[1]
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
check(slot_image(mat) == LY.entry_of(paint_layer, 'BASE_COLOR').image, "target: active layer, active channel")
bpy.ops.m3d.layer_mask_add(fill='WHITE')
pmask = LY.paint_effect(paint_layer).image
pmask_name = pmask.name
check(slot_image(mat) == pmask and read(pmask)[:, :3].min() == 1.0, "target: the layer's mask after Add Mask")
bpy.ops.m3d.tex_channel(channel='ROUGHNESS')
check(not paint_layer.paint_mask and slot_image(mat) == LY.entry_of(paint_layer, 'ROUGHNESS').image,
      "picking a channel goes back to painting the channel")
paint_layer.paint_mask = True
mat.m3d_layer_index = 0
check(slot_image(mat) == LY.entry_of(mat.m3d_layers[0], 'ROUGHNESS').image, "target: another layer, same channel")
mat.m3d_layer_index = 1
check(slot_image(mat) == pmask, "target: Paint Mask is remembered per layer")
check(bpy.ops.m3d.layer_mask_remove() == {'FINISHED'} and not paint_layer.mask_stack and not paint_layer.paint_mask
      and not [n for n in mat.node_tree.nodes if n.get("m3d_mask") == paint_layer.uid] and pmask_name not in bpy.data.images, "Remove Mask")
check(slot_image(mat) == LY.entry_of(paint_layer, 'ROUGHNESS').image, "...and the brush is back on the channel")
check(bpy.ops.m3d.layer_convert.poll() is False, "Convert needs a fill layer")
mat.m3d_layer_index = 2
check(bpy.ops.m3d.layer_convert() == {'FINISHED'} and fill.kind == 'PAINT' and LY.entry_of(fill, 'BASE_COLOR').image is not None,
      "Convert to Paint Layer")
conv = read(LY.entry_of(fill, 'BASE_COLOR').image)
check(np.abs(conv[0, :3] - [srgb_py(0.9), srgb_py(0.1), srgb_py(0.1)]).max() < 2 / 255 and conv[:, 3].min() == 1.0,
      "the converted layer holds the fill color: %s" % conv[0])
bpy.ops.m3d.layer_remove()
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')

# --- Numbers: Merge Down and Flatten against pixels worked out by hand
cx = np.array([0.1, 0.4, 0.6, 0.9])          # base: left to right
ry = np.array([0.2, 0.5, 0.7, 1.0])          # layer: top to bottom
ay = np.array([1.0, 0.5, 1.0, 0.25])         # layer alpha per row


def grid_rgba(f, alpha):
    out = np.ones((4, 4, 4), np.float32)
    for y in range(4):
        for x in range(4):
            out[y, x, :3] = f(x, y)
            out[y, x, 3] = alpha(y)
    return out


def two_layers(ch_id, mode, opacity, srgb=False):
    """A scene whose stack is a 4 x 4 opaque base and a layer with `mode`, opacity and per-row alpha."""
    o, m = fresh_cube("Merge")
    m.m3d_channel = ch_id
    base_img = small("lowImg", grid_rgba(lambda x, y: (cx[x],) * 3, lambda y: 1.0), srgb)
    top_img = small("topImg", grid_rgba(lambda x, y: (ry[y],) * 3, lambda y: ay[y]), srgb)
    for name, img in (("Low", base_img), ("High", top_img)):
        layer = LY.add_layer(m, 'PAINT', name)
        e = LY.entry_of(m.m3d_layers[len(m.m3d_layers) - 1], ch_id)
        e.image, e.use = img, True
    hi = m.m3d_layers[1]
    hi.blend, hi.opacity = mode, opacity
    LY.rebuild_all(m)
    return o, m, base_img, top_img


for mode in ('MIX', 'MULTIPLY', 'ADD', 'OVERLAY'):
    for ch_id, srgb in (('ROUGHNESS', False), ('BASE_COLOR', True)):
        o, m, low_img, high_img = two_layers(ch_id, mode, 0.5, srgb)
        lo_px, hi_px = read(low_img).reshape(4, 4, 4), read(high_img).reshape(4, 4, 4)   # What was stored (8 bit).
        want = np.zeros((4, 4))
        for y in range(4):
            for x in range(4):
                b, s = lo_px[y, x, 0], hi_px[y, x, 0]
                if srgb:
                    b, s = linear_py(b), linear_py(s)
                v = over_py(b, s, 0.5 * hi_px[y, x, 3], mode)
                want[y, x] = srgb_py(v) if srgb else v
        high_name = high_img.name
        m.m3d_layer_index = 1
        check(bpy.ops.m3d.layer_merge_down() == {'FINISHED'}, "Merge Down %s %s" % (mode, ch_id))
        got = read(low_img).reshape(4, 4, 4)
        err = np.abs(got[..., 0] - want).max()
        check(err <= 1.5 / 255 and np.abs(got[..., 1] - got[..., 0]).max() < 1e-6 and np.abs(got[..., 3] - 1).max() < 1e-6,
              "Merge Down %s on %s matches the hand-worked pixels (error %.4f)" % (mode, ch_id, err))
        check([l.name for l in m.m3d_layers] == ["Low"] and high_name not in bpy.data.images
              and m.m3d_layers[0].opacity == 1.0 and m.m3d_layer_index == 0, "Merge Down leaves the lower layer only")
        expect_chain(m, ch_id, "merged")

# Merge Down with a mask, a fill layer and a hidden layer.
o, m, low_img, high_img = two_layers('ROUGHNESS', 'MULTIPLY', 1.0)
mask_vals = np.array([1.0, 0.5, 0.0, 1.0])
mask_img = small("maskImg", grid_rgba(lambda x, y: (mask_vals[x],) * 3, lambda y: 1.0), alpha=False)
set_mask(m.m3d_layers[1], mask_img)
mask_name = mask_img.name
lo_px, hi_px, mk = read(low_img).reshape(4, 4, 4), read(high_img).reshape(4, 4, 4), read(mask_img).reshape(4, 4, 4)
m.m3d_layer_index = 1
bpy.ops.m3d.layer_merge_down()
got = read(low_img).reshape(4, 4, 4)
want = np.array([[over_py(lo_px[y, x, 0], hi_px[y, x, 0], hi_px[y, x, 3] * mk[y, x, 0], 'MULTIPLY') for x in range(4)] for y in range(4)])
check(np.abs(got[..., 0] - want).max() <= 1.5 / 255 and mask_name not in bpy.data.images, "Merge Down applies the mask of the upper layer (and removes it)")
o, m, low_img, high_img = two_layers('ROUGHNESS', 'ADD', 0.5)
m.m3d_layers[1].visible = False
before = read(low_img).copy()
m.m3d_layer_index = 1
bpy.ops.m3d.layer_merge_down()
check(np.array_equal(read(low_img), before) and len(m.m3d_layers) == 1, "Merge Down of a hidden layer only removes it")
o, m, low_img, high_img = two_layers('ROUGHNESS', 'ADD', 0.5)
m.m3d_layers[1].kind = 'FILL'
LY.entry_of(m.m3d_layers[1], 'ROUGHNESS').value = 0.3
lo_px = read(low_img).reshape(4, 4, 4)
m.m3d_layer_index = 1
bpy.ops.m3d.layer_merge_down()
want = np.array([[over_py(lo_px[y, x, 0], 0.3, 0.5, 'ADD') for x in range(4)] for y in range(4)])
check(np.abs(read(low_img).reshape(4, 4, 4)[..., 0] - want).max() <= 1.5 / 255, "Merge Down of a fill layer")
check(not bpy.ops.m3d.layer_merge_down.poll(), "nothing below the bottom layer")

# Flatten three layers (Mix, Multiply, Add) and compare with the hand-worked chain.
o, m = fresh_cube("Flat")
m.m3d_channel = 'ROUGHNESS'
imgs = [small("f%d" % i, grid_rgba(lambda x, y, i=i: ((cx, ry, cx[::-1])[i][x if i != 1 else y],) * 3, lambda y, i=i: 1.0 if i == 0 else ay[y])) for i in range(3)]
modes, opacities = ('MIX', 'MULTIPLY', 'ADD'), (1.0, 0.8, 0.6)
for i in range(3):
    LY.add_layer(m, 'PAINT', "L%d" % i)
    e = LY.entry_of(m.m3d_layers[i], 'ROUGHNESS')
    e.image, e.use = imgs[i], True
    m.m3d_layers[i].blend, m.m3d_layers[i].opacity = modes[i], opacities[i]
set_mask(m.m3d_layers[1], small("fm", grid_rgba(lambda x, y: (mask_vals[x],) * 3, lambda y: 1.0), alpha=False))
LY.rebuild_all(m)
old_names = [im.name for im in imgs] + ["fm"]
px = [read(im).reshape(4, 4, 4) for im in imgs]
mk = read(LY.paint_effect(m.m3d_layers[1]).image).reshape(4, 4, 4)
want = np.zeros((4, 4))
for y in range(4):
    for x in range(4):
        v = px[0][y, x, 0]
        v = over_py(v, px[1][y, x, 0], 0.8 * px[1][y, x, 3] * mk[y, x, 0], 'MULTIPLY')
        v = over_py(v, px[2][y, x, 0], 0.6 * px[2][y, x, 3], 'ADD')
        want[y, x] = v
flat = LY.flatten_channel(m, 'ROUGHNESS', 4)
check(np.abs(flat[..., 0] - want).max() < 1e-5 and flat.shape == (4, 4, 4), "composite of three layers matches the hand-worked pixels (error %.2e)" % np.abs(flat[..., 0] - want).max())
m.m3d_layer_index = 2
check(bpy.ops.m3d.layer_flatten() == {'FINISHED'} and [l.name for l in m.m3d_layers] == ["Base"], "Flatten leaves one layer")
check(not any(n in bpy.data.images for n in old_names) and not m.m3d_layers[0].mask_stack, "Flatten removes the old images")
fimg = LY.entry_of(m.m3d_layers[0], 'ROUGHNESS').image
check(tuple(fimg.size) == (4, 4) and np.abs(read(fimg).reshape(4, 4, 4)[..., 0] - want).max() <= 1.0 / 255 + 1e-5
      and read(fimg)[:, 3].min() == 1.0, "the flattened layer holds the result")
check(not LY.has_content(m.m3d_layers[0], 'BASE_COLOR'), "Flatten does not invent channels")
expect_chain(m, 'ROUGHNESS', "flattened")
check(not bpy.ops.m3d.layer_flatten.poll(), "one layer is flat already")

# Blend math: every mode's numpy result is what the shader nodes compute (Cycles bake of the chain).
clean_scene()
bpy.ops.mesh.primitive_plane_add()
plane = bpy.context.active_object
plane.name = "NodeCheck"
bpy.ops.m3d.tex_add_material()
pmat = plane.active_material
N = 8
rng = np.random.default_rng(7)


def noise_image(name, srgb, alpha=True, opaque=False):
    im = bpy.data.images.new(name, N, N, alpha=alpha, is_data=not srgb)
    px = rng.random((N, N, 4)).astype(np.float32)
    if opaque:
        px[..., 3] = 1.0
    LY.write_pixels(im, px)
    return im


def bake_out(ob, mat, find, closest=True):
    """Linear pixels of any node output as the shader computes them: Cycles emission bake of the socket `find(copy)`
    returns, in a copy of the material (`closest`: nearest texel everywhere, so the bake's pixel jitter cannot matter)."""
    temp = mat.copy()
    nt = temp.node_tree
    socket = find(temp)
    emit = nt.nodes.new("ShaderNodeEmission")
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    nt.links.new(socket, emit.inputs["Color"])
    nt.links.new(emit.outputs[0], out.inputs["Surface"])
    for n in nt.nodes:
        if n.type == 'TEX_IMAGE' and closest:
            n.interpolation = 'Closest'
    target = bpy.data.images.new("m3dNodeBake", N, N, alpha=False, float_buffer=True, is_data=True)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = target
    nt.nodes.active = tex
    bpy.context.scene.cycles.samples = 1
    with T.bake_scene(bpy.context, ob, None):
        with T.materials_swapped(ob, temp):
            bpy.ops.object.bake(type='EMIT', target='IMAGE_TEXTURES', margin=0, use_clear=True, save_mode='INTERNAL')
    px = read(target).reshape(N, N, 4)[..., :3].copy()
    bpy.data.images.remove(target)
    return px


def bake_chain(ob, mat, ch_id):
    """Linear pixels of a channel's chain as the shader computes them: the output of its top Mix node."""
    return bake_out(ob, mat, lambda t: LY.principled_of(t).inputs[LY.SOCKETS[ch_id]].links[0].from_node.outputs[2])


worst = {True: 0.0, False: 0.0}
for ch_id, srgb in (('BASE_COLOR', True), ('ROUGHNESS', False)):
    for mode, _label in LY.BLENDS:
        with LY.muted():
            pmat.m3d_layers.clear()
            for i in range(3):
                LY.add_layer(pmat, 'PAINT', "N%d" % i)
            for i in range(3):
                layer = pmat.m3d_layers[i]
                e = LY.entry_of(layer, ch_id)
                e.image, e.use = noise_image("nc%d" % i, srgb, opaque=i == 0), True
                layer.blend, layer.opacity = (mode if i else 'MIX'), (0.65 if i == 1 else 0.9)
            set_mask(pmat.m3d_layers[1], noise_image("ncm", False, alpha=False))
            set_mask(pmat.m3d_layers[2], noise_image("ncm2", False, alpha=False), invert=True)
            pmat.m3d_layers[2].blend = 'SCREEN' if mode != 'SCREEN' else 'DARKEN'
        LY.rebuild_all(pmat)
        nodes_lin = bake_chain(plane, pmat, ch_id)
        mine = LY.composite(pmat, ch_id, N)
        err = np.abs(nodes_lin - mine).max()
        worst[srgb] = max(worst[srgb], err)
        check(err < (0.006 if srgb else 2e-4), "numpy %s matches the node chain for %s (error %.5f)" % (mode, ch_id, err))
print("layer blend math vs Cycles bake: worst linear error %.5f (sRGB channel), %.6f (data channel)" % (worst[True], worst[False]))
bpy.data.objects.remove(plane)

# --- Migration keeps the old nodes' settings: tiling through a Mapping node, interpolation, Normal Map strength
clean_scene()
bpy.ops.mesh.primitive_plane_add()
keep = bpy.context.active_object
keep.name = "KeepLook"
bpy.ops.m3d.tex_add_material()
kmat = keep.active_material
bpy.context.scene.m3d_tex.resolution = '64'
knt, ksdf = kmat.node_tree, LY.principled_of(kmat)


def user_image(name, srgb):
    im = bpy.data.images.new(name, 6, 6, alpha=True, is_data=not srgb)
    LY.write_pixels(im, rng.random((6, 6, 4)).astype(np.float32))
    return im


coord, mapping = knt.nodes.new("ShaderNodeTexCoord"), knt.nodes.new("ShaderNodeMapping")
mapping.inputs["Scale"].default_value = (4.0, 4.0, 4.0)
knt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])
tex_base, tex_normal, tex_alpha = (knt.nodes.new("ShaderNodeTexImage") for _ in range(3))
tex_alpha.name = "UserAlphaTex"
tex_base.image, tex_normal.image, tex_alpha.image = user_image("kBase", True), user_image("kNormal", False), user_image("kAlpha", False)
tex_base.interpolation, tex_base.extension = 'Closest', 'EXTEND'
tex_normal.interpolation = 'Closest'
for t in (tex_base, tex_normal):
    knt.links.new(mapping.outputs["Vector"], t.inputs["Vector"])
nmap = knt.nodes.new("ShaderNodeNormalMap")
nmap.inputs["Strength"].default_value = 0.5
knt.links.new(tex_normal.outputs["Color"], nmap.inputs["Color"])
knt.links.new(nmap.outputs["Normal"], ksdf.inputs["Normal"])
knt.links.new(tex_base.outputs["Color"], ksdf.inputs["Base Color"])
knt.links.new(tex_alpha.outputs["Color"], ksdf.inputs["Alpha"])
base_find = lambda t: LY.principled_of(t).inputs["Base Color"].links[0].from_socket
normal_find = lambda t: LY.principled_of(t).inputs["Normal"].links[0].from_socket
before = (bake_out(keep, kmat, base_find, closest=False), bake_out(keep, kmat, normal_find, closest=False))
check(np.ptp(before[0]) > 0.1 and np.ptp(before[1]) > 0.01, "the bake sees the tiled textures (%.2f, %.3f)" % (np.ptp(before[0]), np.ptp(before[1])))
check(bpy.ops.m3d.layer_add(kind='PAINT') == {'FINISHED'} and [l.name for l in kmat.m3d_layers] == ["Base", "Paint Layer"],
      "Add Paint Layer on a material with a Mapping node and a Normal Map")
after = (bake_out(keep, kmat, base_find, closest=False), bake_out(keep, kmat, normal_find, closest=False))
check(np.abs(after[0] - before[0]).max() < 0.004, "Base Color looks the same after the first layer operation (%.5f)" % np.abs(after[0] - before[0]).max())
check(np.abs(after[1] - before[1]).max() < 0.004, "the normal looks the same after the first layer operation (%.5f)" % np.abs(after[1] - before[1]).max())
ours_nm = knt.nodes["%s.NORMAL.map" % LY.TAG]
ours_tex = knt.nodes[LY.part('BASE_COLOR', kmat.m3d_layers[0].uid, "tex")]
check(abs(ours_nm.inputs["Strength"].default_value - 0.5) < 1e-6, "the Normal Map keeps its strength")
check(ours_tex.interpolation == 'Closest' and ours_tex.extension == 'EXTEND' and ours_tex.inputs["Vector"].links
      and ours_tex.inputs["Vector"].links[0].from_node == mapping, "the Base Color node keeps interpolation, extension and the Mapping node")
check(knt.nodes.get("UserAlphaTex") is not None and ksdf.inputs["Alpha"].links and ksdf.inputs["Alpha"].links[0].from_node == tex_alpha
      and mapping.name in knt.nodes and [n for n in knt.nodes if n.type == 'TEX_IMAGE' and LY.TAG not in n.keys()] == [tex_alpha],
      "an image node that feeds no channel stays where it is, linked")
# The settings survive later rebuilds (new layers change the chains), also the ones set on our nodes afterwards.
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
bpy.ops.m3d.tex_channel(channel='HEIGHT')
bump = knt.nodes["%s.HEIGHT.bump" % LY.TAG]
bump.inputs["Strength"].default_value, bump.inputs["Distance"].default_value, bump.invert = 0.7, 0.2, True
ours_nm.inputs["Strength"].default_value = 0.3
ours_nm.uv_map = "UVMap"
bpy.ops.m3d.layer_add(kind='PAINT')       # A Height image on the new layer rebuilds the Height chain
bpy.ops.m3d.tex_channel(channel='NORMAL')   # ...and a Normal image the Normal chain
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')   # ...and a Base Color image the Base Color chain
bump = knt.nodes["%s.HEIGHT.bump" % LY.TAG]
ours_nm = knt.nodes["%s.NORMAL.map" % LY.TAG]
check(len(level(kmat, 'HEIGHT')) == 2 and len(level(kmat, 'NORMAL')) == 2 and len(level(kmat, 'BASE_COLOR')) == 3,
      "the chains were rebuilt with the new layer")
check(abs(bump.inputs["Strength"].default_value - 0.7) < 1e-6 and abs(bump.inputs["Distance"].default_value - 0.2) < 1e-6 and bump.invert,
      "Bump strength, distance and invert survive a rebuild")
check(abs(ours_nm.inputs["Strength"].default_value - 0.3) < 1e-6 and ours_nm.uv_map == "UVMap", "Normal Map strength and UV map survive a rebuild")
ours_tex = knt.nodes[LY.part('BASE_COLOR', kmat.m3d_layers[0].uid, "tex")]
check(ours_tex.interpolation == 'Closest' and ours_tex.inputs["Vector"].links and ours_tex.inputs["Vector"].links[0].from_node == mapping,
      "the Base layer's image node keeps its settings and Mapping link through a rebuild")
check(knt.nodes["%s.HEIGHT.bump" % LY.TAG].inputs["Normal"].links[0].from_node == ours_nm,
      "Normal Map still feeds Bump")

# --- Export flattens the visible stack and leaves the layers alone
exp_ob, exp_mat = fresh_cube("Show", '64')
for cid in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC'):
    bpy.ops.m3d.tex_channel(channel=cid)
fill_rgb(T.channel_slots(exp_mat)['BASE_COLOR'][1], (0.6, 0.3, 0.1))
fill_rgb(T.channel_slots(exp_mat)['ROUGHNESS'][1], (0.2, 0.2, 0.2))
fill_rgb(T.channel_slots(exp_mat)['METALLIC'][1], (0.9, 0.9, 0.9))
bpy.ops.m3d.layer_add(kind='FILL')
fill = exp_mat.m3d_layers[1]
fill.blend, fill.opacity = 'MULTIPLY', 0.5
fill.channels[0].color = (0.5, 0.25, 0.8, 1.0)
LY.entry_of(fill, 'ROUGHNESS').use = True
LY.entry_of(fill, 'ROUGHNESS').value = 0.8
LY.entry_of(fill, 'METALLIC').use = True
LY.entry_of(fill, 'METALLIC').value = 0.0
fill.opacity = 0.5
lay_state = [(l.name, l.blend, l.opacity, l.visible, [(e.channel, e.use, e.image.name if e.image else None) for e in l.channels])
             for l in exp_mat.m3d_layers]
nodes_state = sorted(n.name for n in exp_mat.node_tree.nodes)
images_state = {i.name for i in bpy.data.images}
exp_dir = tempfile.mkdtemp(prefix="m3d_export_")
tx = bpy.context.scene.m3d_tex
tx.export_folder, tx.export_size, tx.export_preset = exp_dir, 'SAME', 'UNREAL'
check(bpy.ops.m3d.tex_export() == {'FINISHED'}, "Unreal export of a stack runs")
check(sorted(os.listdir(exp_dir)) == ["T_Show_BC.png", "T_Show_ORM.png"], "Unreal files of a stack: %s" % sorted(os.listdir(exp_dir)))
orm, _ = load_png(exp_dir, "T_Show_ORM.png")
bc, _ = load_png(exp_dir, "T_Show_BC.png")
want_rough = over_py(0.2, 0.8, 0.5, 'MULTIPLY')
want_metal = over_py(0.9, 0.0, 0.5, 'MULTIPLY')
check(abs(orm[0, 1] - want_rough) < 2.5 / 255 and abs(orm[0, 2] - want_metal) < 2.5 / 255,
      "ORM has the flattened roughness %.3f and metallic %.3f (%s)" % (want_rough, want_metal, orm[0]))
base_lin = [linear_py(0.6), linear_py(0.3), linear_py(0.1)]
fill_lin = (0.5, 0.25, 0.8)
want_bc = [srgb_py(over_py(b, f, 0.5, 'MULTIPLY')) for b, f in zip(base_lin, fill_lin)]
check(np.abs(bc[0, :3] - want_bc).max() < 3 / 255, "BC has the flattened base color (%s, want %s)" % (bc[0, :3], want_bc))
check(lay_state == [(l.name, l.blend, l.opacity, l.visible, [(e.channel, e.use, e.image.name if e.image else None) for e in l.channels])
                    for l in exp_mat.m3d_layers] and nodes_state == sorted(n.name for n in exp_mat.node_tree.nodes)
      and images_state <= {i.name for i in bpy.data.images} and not [i for i in bpy.data.images if i.name.startswith("m3dExport")],
      "export leaves the layers, nodes and images untouched")
fill.visible = False
tx.export_preset, tx.export_folder = 'UNITY', tempfile.mkdtemp(prefix="m3d_export_")
check(bpy.ops.m3d.tex_export() == {'FINISHED'}, "Unity export of a stack runs")
ms, _ = load_png(tx.export_folder, "Show_MetallicSmoothness.png")
check(abs(ms[0, 0] - 0.9) < 2.5 / 255 and abs(ms[0, 3] - 0.8) < 2.5 / 255, "a hidden layer is not exported (metal %.3f, smoothness %.3f)" % (ms[0, 0], ms[0, 3]))
tx.export_preset, tx.export_folder = 'GLTF', tempfile.mkdtemp(prefix="m3d_export_")
fill.visible = True
check(bpy.ops.m3d.tex_export() == {'FINISHED'} and os.path.getsize(os.path.join(tx.export_folder, "Show.glb")) > 1000,
      "glTF export of a stack writes a .glb")
check(lay_state == [(l.name, l.blend, l.opacity, l.visible, [(e.channel, e.use, e.image.name if e.image else None) for e in l.channels])
                    for l in exp_mat.m3d_layers] and exp_ob.active_material == exp_mat
      and sorted(n.name for n in exp_mat.node_tree.nodes) == nodes_state
      and not [i for i in bpy.data.images if i.name.startswith("m3dFlat")]
      and not [m for m in bpy.data.materials if m != exp_mat and m.users == 0 and m.name.startswith(exp_mat.name)],
      "glTF export leaves the layers, nodes and materials as they were")
tx.export_preset, tx.export_folder = 'UNITY', "//textures/"

# --- Safety: layer and mask images are saved with the file
sv_ob, sv_mat = fresh_cube("Safe")
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
bpy.ops.m3d.layer_add(kind='PAINT')
bpy.ops.m3d.layer_mask_add(fill='WHITE')
layer_a, layer_b = sv_mat.m3d_layers[0], sv_mat.m3d_layers[1]
img_a, img_b, mask_b = LY.entry_of(layer_a, 'BASE_COLOR').image, LY.entry_of(layer_b, 'BASE_COLOR').image, LY.paint_effect(layer_b).image
img_b = img_b or LY.entry_of(layer_b, 'BASE_COLOR').image
spare = bpy.data.images.new("m3dSpare", 8, 8)
LY.entry_of(layer_a, 'METALLIC').image = spare
LY.entry_of(layer_a, 'METALLIC').use = False
LY.write_pixels(img_a, np.full(64 * 64 * 4, 0.7, np.float32))
LY.write_pixels(mask_b, np.full(64 * 64 * 4, 0.25, np.float32))
LY.write_pixels(spare, np.full(8 * 8 * 4, 0.4, np.float32))
mod = T.modified_images()
check(img_a in mod and mask_b in mod and spare in mod, "layer, mask and spare images count as modified: %s" % [i.name for i in mod])
layer_b_name = layer_b.name
sv_names = (img_a.name, mask_b.name, spare.name)
sv_path = os.path.join(tempfile.mkdtemp(prefix="m3d_test_"), "layers.blend")
bpy.ops.wm.save_as_mainfile(filepath=sv_path)
check(img_a.packed_file is not None and mask_b.packed_file is not None and spare.packed_file is not None,
      "saving packed the layer, mask and spare images")
bpy.ops.wm.open_mainfile(filepath=sv_path)
sm = bpy.data.materials["Safe_Material"] if "Safe_Material" in bpy.data.materials else bpy.data.objects["Safe"].active_material
check(len(sm.m3d_layers) == 2 and sm.m3d_layers[1].name == layer_b_name and LY.paint_effect(sm.m3d_layers[1]) is not None
      and LY.paint_effect(sm.m3d_layers[1]).image.name == sv_names[1], "layers, names and mask are in the saved file")
check(abs(read(sm.m3d_layers[0].channels[0].image)[0, 0] - 0.7) < 2 / 255 and abs(read(LY.paint_effect(sm.m3d_layers[1]).image)[0, 0] - 0.25) < 2 / 255,
      "painted layer and mask pixels come back")
check(sv_names[2] in bpy.data.images and abs(read(bpy.data.images[sv_names[2]])[0, 0] - 0.4) < 2 / 255,
      "an image only a disabled channel points at is kept")
expect_chain(sm, 'BASE_COLOR', "reloaded")
check(len([i for i in bpy.data.images if i.name == sv_names[0]]) == 1, "reload does not duplicate images")

tex_ws = bpy.data.workspaces["Texture"]   # Opening the file replaced the workspaces.

# --- Many layers: memory estimate
mem_ob, mem_mat = fresh_cube("Heavy")
for i in range(2):
    LY.add_layer(mem_mat, 'PAINT', "H%d" % i)
    LY.entry_of(mem_mat.m3d_layers[i], 'BASE_COLOR').image = bpy.data.images.new("h%d" % i, 4096, 4096)
check(LY.memory_bytes(mem_mat) == 2 * 4096 * 4096 * 4 and LY.memory_equivalent(mem_mat) == 2.0,
      "memory estimate of two 4K images: %d MB" % (LY.memory_bytes(mem_mat) >> 20))
check(LY.memory_equivalent(mem_mat) <= LY.MEMORY_WARN and LY.MEMORY_WARN == 12, "two images are no reason to warn (warns from 12 4K images)")
LY.MEMORY_WARN = 1.5
mem_log = draw_stub(T.PROPERTIES_PT_m3d_tx_stack, TCtx())
LY.MEMORY_WARN = 12
check(any(getattr(r, "alert", False) for r in mem_log if r._kind == "row") and
      any("4K" in str(r._kw.get("text", "")) for r in mem_log if r._kind == "label"), "the Layers tab warns about the memory: %s" % [r._kw for r in mem_log if r._kind == "label"][-2:])

# --- The Layers tab draws, with and without layers
mem_mat.m3d_layers.clear()
for i in range(2):
    bpy.data.images.remove(bpy.data.images["h%d" % i])
bpy.ops.m3d.layer_add(kind='PAINT')
bpy.ops.m3d.layer_add(kind='FILL')
bpy.ops.m3d.layer_mask_add(fill='WHITE')
ctx = TCtx()
tex_ws.m3d_page_right = "tex_layers"
shown_names = [c.__name__ for c in tex_panels("tex_layers") if c.poll(ctx)]
check({"PROPERTIES_PT_m3d_tx_stack", "PROPERTIES_PT_m3d_tx_layer", "PROPERTIES_PT_m3d_tx_mask", "PROPERTIES_PT_m3d_tx_channels"} <= set(shown_names),
      "the Layers tab shows the stack, the layer, the mask and the channels: %s" % shown_names)
for name in shown_names:
    cls = getattr(T, name)
    try:
        check_calls(name, draw_stub(cls, ctx))
    except Exception as err:
        check(False, "%s draw: %r" % (name, err))
for active in (0, 1):   # Paint layer, then the fill layer with a mask
    mem_mat.m3d_layer_index = active
    for cls in (T.PROPERTIES_PT_m3d_tx_stack, T.PROPERTIES_PT_m3d_tx_layer, T.PROPERTIES_PT_m3d_tx_mask):
        try:
            check_calls(cls.__name__, draw_stub(cls, ctx))
        except Exception as err:
            check(False, "%s draw (layer %d): %r" % (cls.__name__, active, err))
log = []
LY.M3D_UL_layers.draw_item(None, ctx, Rec(log), None, mem_mat.m3d_layers[1], 0, None, "", 0)
check_calls("layer list row", log)
check({r._args[1] for r in log if r._kind == "prop"} >= {"visible", "name", "blend", "opacity"}, "the list row shows eye, name, blend and opacity")
log = []
T.draw_status_line(Rec(log), ctx)
check_calls("Texture status line with layers", log)
mem_mat.m3d_layers.clear()
LY.rebuild_all(mem_mat)
check(not [n for n in mem_mat.node_tree.nodes if LY.TAG in n.keys()], "deleting every layer removes the chains")
check(mem_mat.node_tree.nodes.get("%s.scratch" % LY.TAG) is None, "...and the scratch node (its image goes when no material uses it)")
check(not tex_gated("tex_layers") and "PROPERTIES_PT_m3d_tx_stack" in tex_shown("tex_layers")
      and "PROPERTIES_PT_m3d_tx_layer" not in tex_shown("tex_layers"), "no layers: the stack panel offers the add buttons only")

# ----------------------------------------------------------------------------------------------------
# Phase 7a: mask stacks on layers (data, node chains, numpy == nodes, baked maps, Blur caches, Show Mask, migration,
# merge / export, saving).
import m3d_masks as MK

check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in (
    LY.M3D_UL_mask_effects, T.M3D_MT_mask_add, LY.M3D_OT_mask_effect_add, LY.M3D_OT_mask_effect_remove,
    LY.M3D_OT_mask_effect_move, LY.M3D_OT_mask_effect_duplicate, LY.M3D_OT_mask_rebake))
      and "mask_stack" in LY.M3D_Layer.bl_rna.properties and MK.M3D_MaskEffect.bl_rna.properties["kind"].type == 'ENUM', "mask classes registered")
check([k.id for k in MK.KINDS] == ['PAINT', 'FILL', 'EDGES', 'CAVITY', 'TOPDOWN', 'THICKNESS', 'NOISE', 'LEVELS', 'BLUR', 'INVERT',
                                   'SHARPEN'], "mask effect types")
check(all(k.icon in icons for k in MK.KINDS), "mask effect icons exist")
check(all(k.maps == () or all(m in MK.MAP_LABELS for m in k.maps) for k in MK.KINDS), "baked maps of the generators are known")
check([b for b, _l in MK.BLENDS] == ['MIX', 'MULTIPLY', 'ADD', 'SUBTRACT', 'LIGHTEN', 'DARKEN']
      and {b for b, _l in MK.BLENDS} <= node_blends and set(MK.BLEND_FUNCTIONS) == {b for b, _l in MK.BLENDS},
      "mask blend modes are Mix node blend types with numpy math")
check({"m3d.layer_mask_add", "m3d.layer_mask_remove", "m3d.layer_mask_invert", "m3d.layer_paint_mask"} <= {e.get("idname") for e in m3d_ui.MENUS["M3D_MT_layers"][1]},
      "the Layers menu still has the mask operators")

MN = 64
N_saved, N = N, MN       # bake_out and noise_image work on N x N pixels
clean_scene()
bpy.ops.mesh.primitive_plane_add()
mplane = bpy.context.active_object
mplane.name = "MaskPlane"
bpy.ops.m3d.tex_add_material()
mm = mplane.active_material
bpy.context.scene.m3d_tex.resolution = '64'
mplane.m3d_bake.resolution, mplane.m3d_bake.samples = '64', 4
mrng = np.random.default_rng(21)
mnodes = mm.node_tree.nodes


def mimg(name, size=MN):
    im = bpy.data.images.new(name, size, size, alpha=True, float_buffer=True, is_data=True)
    px = mrng.random((size, size, 4)).astype(np.float32)
    px[..., 3] = 1.0
    LY.write_pixels(im, px)
    return im


with LY.muted():
    LY.add_layer(mm, 'PAINT', "Base")
    LY.add_layer(mm, 'FILL', "Top")
    LY.entry_of(mm.m3d_layers[0], 'BASE_COLOR').use = True
    LY.entry_of(mm.m3d_layers[0], 'BASE_COLOR').image = noise_image("mkBase", True, opaque=True)
    mm.m3d_layer_index = 1
LY.rebuild_all(mm)
mtop = mm.m3d_layers[1]
check(not mtop.mask_stack and LY.mask_top(mm.node_tree, mtop) is None and not [n for n in mnodes if n.get(LY.TAG) == "MASK"],
      "a layer without mask effects has no mask nodes")
check(MK.stack_value(mtop, 4).min() == 1.0, "no effects: the mask is white")


def mask_nodes(layer):
    return [n for n in mnodes if n.get(LY.TAG) == "MASK" and n.get("m3d_mask") == layer.uid and n.type != 'FRAME']


def snapshot():
    return {n.name: n.as_pointer() for n in mnodes if LY.TAG in n.keys()}


# --- Add effects with the operator: the nodes of every kind that needs no baked map
for kind in ('PAINT', 'FILL', 'NOISE', 'LEVELS', 'BLUR', 'INVERT', 'SHARPEN'):
    check(bpy.ops.m3d.mask_effect_add(kind=kind) == {'FINISHED'}, "add mask effect " + kind)
stack = mtop.mask_stack
check([e.kind for e in stack] == ['PAINT', 'FILL', 'NOISE', 'LEVELS', 'BLUR', 'INVERT', 'SHARPEN']
      and [e.name for e in stack] == ["Paint", "Fill", "Noise", "Levels", "Blur", "Invert", "Sharpen"] and mtop.mask_index == 6,
      "effects are added above the selected one: %s" % [e.kind for e in stack])
check([e.blend for e in stack] == ['MIX', 'MIX', 'MULTIPLY', 'MIX', 'MIX', 'MIX', 'MIX'], "blend defaults: the first mixes, generators multiply: %s" % [e.blend for e in stack])
check(stack[0].image is not None and stack[0].image.colorspace_settings.name == 'Non-Color' and mtop.paint_mask
      and stack[4].image is not None and stack[4].image.is_float, "Paint and Blur effects have their images")
roles = {e.kind: sorted(n.name.split(".")[-2] for n in mask_nodes(mtop) if n.name.endswith("." + e.uid)) for e in stack}
check(roles == {'PAINT': ['bw', 'mix', 'tex'], 'FILL': ['mix'], 'NOISE': ['coord', 'grp', 'mix'], 'LEVELS': ['grp', 'mix'],
                'BLUR': ['bw', 'mix', 'tex'], 'INVERT': ['grp', 'mix'], 'SHARPEN': ['grp', 'mix']}, "nodes per effect type: %s" % roles)
below = None
for e in stack:
    mix = LY.mask_node(mm.node_tree, mtop, "mix", e)
    first = below is None
    check(mix.type == 'MIX' and mix.data_type == 'RGBA' and mix.clamp_result, "%s: a Mix node (color, clamped)" % e.name)
    check((not mix.inputs[6].links and tuple(mix.inputs[6].default_value) == (1.0, 1.0, 1.0, 1.0)) if first else
          mix.inputs[6].links[0].from_node == below, "%s: mixes over %s" % (e.name, "white" if first else "the effect below"))
    grp = LY.mask_node(mm.node_tree, mtop, "grp", e)
    if e.kind in MK.GROUPED:
        check(grp.node_tree.name == "m3d_mask." + e.kind.lower() and grp.outputs["Value"].links[0].to_node == mix,
              "%s: its node group feeds the Mix node" % e.name)
    if e.kind in MK.FILTERS and e.kind != 'BLUR':
        check((grp.inputs["Value"].default_value == 1.0 and not grp.inputs["Value"].links) if first else
              grp.inputs["Value"].links[0].from_node == below, "%s: the filter reads the result below" % e.name)
    below = mix
mul = mnodes[LY.part('BASE_COLOR', mtop.uid, "maskmul")]
check(mul.inputs[1].links[0].from_node == below and LY.mask_top(mm.node_tree, mtop) == below.outputs[2], "the mask multiplies the layer's factor")
check(mnodes[LY.part('BASE_COLOR', mtop.uid, "opv")].outputs[0].links[0].to_node == mul and mul.outputs[0].links[0].to_node == mnodes[LY.part('BASE_COLOR', mtop.uid, "mix")],
      "...between the layer's opacity and its Mix node")
check(sorted(g.name for g in bpy.data.node_groups if g.name.startswith("m3d_mask.")) == ["m3d_mask.invert", "m3d_mask.levels", "m3d_mask.noise", "m3d_mask.sharpen"],
      "one node group per effect type, made when first used")
frame = mnodes["%s.MASK.%s" % (LY.TAG, mtop.uid)]
check(frame.type == 'FRAME' and all(n.parent == frame for n in mask_nodes(mtop)), "the mask chain lives in one frame per layer")
check(len({n for n in bpy.data.node_groups if n.name == "m3d_mask.noise"}) == 1, "a group exists once")

# --- Values only set node values; structure changes rebuild only the mask frame
before = snapshot()
stack[1].value, stack[1].opacity, stack[1].blend = 0.4, 0.5, 'ADD'
stack[2].scale, stack[2].seed, stack[2].noise_contrast = 9.0, 3, 5.0
stack[3].gamma, stack[3].black_in, stack[3].white_in = 2.0, 0.1, 0.9
stack[5].visible = False
stack[6].amount = 0.9
stack[0].name = "Dirt"
mtop.opacity = 0.5
check(snapshot() == before, "value edits only set node values (no node was made again)")
mix = LY.mask_node(mm.node_tree, mtop, "mix", stack[1])
check(abs(mix.inputs[0].default_value - 0.5) < 1e-6 and mix.blend_type == 'ADD'
      and abs(mix.inputs[7].default_value[0] - 0.4) < 1e-6, "Fill: factor, blend and value are on the Mix node")
grp = LY.mask_node(mm.node_tree, mtop, "grp", stack[2])
check(abs(grp.inputs["Scale"].default_value - 9.0) < 1e-6 and abs(grp.inputs["Contrast"].default_value - 5.0) < 1e-6
      and abs(grp.inputs["Seed Offset"].default_value[0] - 3 * 13.731) < 1e-4, "Noise: its values are on the group node")
grp = LY.mask_node(mm.node_tree, mtop, "grp", stack[3])
check(abs(grp.inputs["Gamma"].default_value - 2.0) < 1e-6 and abs(grp.inputs["White In"].default_value - 0.9) < 1e-6, "Levels: its values are on the group node")
check(LY.mask_node(mm.node_tree, mtop, "mix", stack[5]).inputs[0].default_value == 0.0, "a hidden effect has factor 0")
check(LY.mask_node(mm.node_tree, mtop, "mix", stack[0]).label == "Dirt", "renaming sets the node label")
check(abs(mnodes[LY.part('BASE_COLOR', mtop.uid, "opv")].inputs[1].default_value - 0.5) < 1e-6, "the layer's own opacity is still its own")
mtop.opacity = 1.0

before = snapshot()
mtop.mask_index = 1
check(bpy.ops.m3d.mask_effect_add(kind='SHARPEN') == {'FINISHED'} and [e.kind for e in mtop.mask_stack][:3] == ['PAINT', 'FILL', 'SHARPEN']
      and mtop.mask_index == 2, "a new effect goes above the selected one")
after = snapshot()
check(all(after[k] == before[k] for k in before if ".MASK." not in k) and set(after) > set(before)
      and any(after.get(k) != v for k, v in before.items() if ".MASK." in k), "adding an effect makes the mask chain again, not the layer's chains")
check(LY.mask_top(mm.node_tree, mtop).node == LY.mask_node(mm.node_tree, mtop, "mix", mtop.mask_stack[-1])
      and mnodes[LY.part('BASE_COLOR', mtop.uid, "maskmul")].inputs[1].links[0].from_socket == LY.mask_top(mm.node_tree, mtop), "...and the layer is fed from the new chain")
check(bpy.ops.m3d.mask_effect_move(delta=1) == {'FINISHED'} and [e.kind for e in mtop.mask_stack][:4] == ['PAINT', 'FILL', 'NOISE', 'SHARPEN']
      and mtop.mask_index == 3, "Move Up")
check(LY.mask_node(mm.node_tree, mtop, "grp", mtop.mask_stack[3]).inputs["Value"].links[0].from_node == LY.mask_node(mm.node_tree, mtop, "mix", mtop.mask_stack[2]),
      "...and the nodes follow the new order")
check(bpy.ops.m3d.mask_effect_move(delta=-1) == {'FINISHED'} and bpy.ops.m3d.mask_effect_move(delta=-1) == {'FINISHED'}
      and [e.kind for e in mtop.mask_stack][:3] == ['PAINT', 'SHARPEN', 'FILL'] and mtop.mask_index == 1, "Move Down")
check(bpy.ops.m3d.mask_effect_remove() == {'FINISHED'} and [e.kind for e in mtop.mask_stack][:3] == ['PAINT', 'FILL', 'NOISE']
      and mtop.mask_index == 1, "Remove the selected effect")
mtop.mask_index = 0
paint_name = mtop.mask_stack[0].image.name
check(bpy.ops.m3d.mask_effect_duplicate() == {'FINISHED'} and mtop.mask_stack[1].name == "Dirt Copy" and mtop.mask_index == 1
      and mtop.mask_stack[1].image is not None and mtop.mask_stack[1].image != mtop.mask_stack[0].image
      and mtop.mask_stack[1].uid != mtop.mask_stack[0].uid, "Duplicate copies the effect and its paint image")
copy_name = mtop.mask_stack[1].image.name
check(np.array_equal(read(mtop.mask_stack[1].image), read(mtop.mask_stack[0].image)), "...with the same pixels")
check(bpy.ops.m3d.mask_effect_remove() == {'FINISHED'} and copy_name not in bpy.data.images and paint_name in bpy.data.images,
      "removing a Paint effect deletes its image, only its own")
# Duplicate Layer copies the stack: paint images are copied, blur caches made again, baked maps shared.
check(bpy.ops.m3d.layer_duplicate() == {'FINISHED'}, "Duplicate Layer with a mask stack")
dup = mm.m3d_layers[2]
check([e.kind for e in dup.mask_stack] == [e.kind for e in mtop.mask_stack] and [e.uid for e in dup.mask_stack] != [e.uid for e in mtop.mask_stack]
      and dup.mask_stack[0].image != mtop.mask_stack[0].image and np.array_equal(read(dup.mask_stack[0].image), read(mtop.mask_stack[0].image))
      and all(a.opacity == b.opacity and a.blend == b.blend for a, b in zip(dup.mask_stack, mtop.mask_stack)),
      "...the copy has its own effects and paint image")
blur_dup = next(e for e in dup.mask_stack if e.kind == 'BLUR')
blur_src = next(e for e in mtop.mask_stack if e.kind == 'BLUR')
check(blur_dup.image is not None and blur_dup.image != blur_src.image, "...and its own blur cache")
bpy.ops.m3d.layer_remove()
mm.m3d_layer_index = 1
mtop = mm.m3d_layers[1]
check(len(mm.m3d_layers) == 2, "the copy is gone again")
check(not [n for n in mnodes if n.get(LY.TAG) == "MASK" and n.get("m3d_mask") not in {l.uid for l in mm.m3d_layers}],
      "deleting a layer removes its mask nodes")

# --- numpy == nodes, effect by effect (a Cycles emission bake of the layer's mask, against MK.stack_value)
def mask_socket(temp):
    layer = temp.m3d_layers[1]
    return temp.node_tree.nodes[LY.part("MASK", layer.uid, "mix." + layer.mask_stack[len(layer.mask_stack) - 1].uid)].outputs[2]


def setup(spec):
    """The top layer's mask: [(kind, settings)], with random images for the paint and the maps."""
    with LY.muted():
        mtop.mask_stack.clear()
        for kind, props in spec:
            e = LY.add_effect(mtop, kind)
            for key, value in props.items():
                setattr(e, key, value)
            if kind == 'PAINT':
                e.image = noise_image("mkp_%s" % e.uid, False, alpha=False, opaque=True)
            for key in MK.needed_maps(e):
                LY.assign_map(e, key, mimg("mkm_%s_%s" % (key, e.uid)))
        mtop.mask_index = len(mtop.mask_stack) - 1
    LY.rebuild_all(mm)


def mask_error(label, tol):
    got = bake_out(mplane, mm, mask_socket)[..., 0]
    mine = MK.stack_value(mtop, MN)
    err = float(np.abs(got - mine).max())
    check(err < tol, "numpy matches the node chain for %s (error %.6f, mask range %.2f-%.2f)" % (label, err, mine.min(), mine.max()))
    return err


mask_worst = {}
for label, spec, tol in (
        ("Fill", [('FILL', dict(value=0.3))], 1e-5),
        ("Paint", [('PAINT', {})], 1e-5),
        ("Edges", [('EDGES', dict(amount=0.7, softness=0.2))], 1e-4),
        ("Edges (inverted)", [('EDGES', dict(amount=0.4, softness=0.05, invert=True))], 1e-4),
        ("Cavity", [('CAVITY', dict(amount=0.6, contrast=0.7))], 1e-4),
        ("Cavity (inverted)", [('CAVITY', dict(amount=0.3, contrast=0.2, invert=True))], 1e-4),
        ("Thickness", [('THICKNESS', dict(amount=0.5, contrast=0.9))], 1e-4),
        ("Top-down", [('TOPDOWN', {})], 1e-4),
        ("Top-down (tilted)", [('TOPDOWN', dict(direction=(1, 0.5, 0.7), offset=0.3, softness=0.4, height_falloff=0.8))], 1e-4),
        ("Noise (UV)", [('NOISE', dict(scale=5.0, detail=3.0, noise_contrast=3.0, seed=2))], 2e-3),
        ("Noise (UV, fractional detail)", [('NOISE', dict(scale=3.0, detail=2.5, noise_contrast=1.0))], 2e-3),
        ("Levels", [('PAINT', {}), ('LEVELS', dict(black_in=0.2, white_in=0.8, gamma=2.0, black_out=0.1, white_out=0.9))], 1e-4),
        ("Levels (reversed output)", [('PAINT', {}), ('LEVELS', dict(black_in=0.1, white_in=0.9, gamma=0.5, black_out=0.9, white_out=0.2))], 1e-4),
        ("Invert", [('PAINT', {}), ('INVERT', {})], 1e-4),
        ("Invert at 50%", [('PAINT', {}), ('INVERT', dict(opacity=0.5))], 1e-4),
        ("Sharpen", [('PAINT', {}), ('SHARPEN', dict(amount=0.6))], 1e-4),
        ("Blur", [('PAINT', {}), ('BLUR', dict(amount=0.3))], 1e-4),
        ("Blur at 50% then Sharpen", [('PAINT', {}), ('BLUR', dict(amount=0.5, opacity=0.5)), ('SHARPEN', {})], 1e-4),
        ("Edges hidden, Invert hidden", [('PAINT', {}), ('EDGES', dict(visible=False)), ('CAVITY', {}), ('INVERT', dict(visible=False)),
                                         ('FILL', dict(value=0.8, blend='SUBTRACT', opacity=0.3))], 1e-4)):
    setup(spec)
    mask_worst[label] = mask_error(label, tol)
for mode, _label in MK.BLENDS:
    for opacity in (1.0, 0.45):
        setup([('PAINT', {}), ('FILL', dict(value=0.35, blend=mode, opacity=opacity)), ('EDGES', dict(blend=mode, opacity=opacity))])
        mask_worst["blend %s" % mode] = max(mask_worst.get("blend %s" % mode, 0), mask_error("blend %s at %.2f" % (mode, opacity), 1e-4))
print("mask effects vs Cycles bake: worst error %.6f (Noise), %.6f (every other effect and blend)" % (
    max(v for k, v in mask_worst.items() if k.startswith("Noise")), max(v for k, v in mask_worst.items() if not k.startswith("Noise"))))

# --- Blur: the cache follows what is below it, and is only made again when that changed
setup([('PAINT', {}), ('BLUR', dict(amount=0.3))])
paint_e, blur_e = mtop.mask_stack[0], mtop.mask_stack[1]
cache = blur_e.image
want = MK.blur(MK.sample(paint_e.image, cache.size[0]), 0.3)
check(tuple(cache.size) == (64, 64) and cache.is_float and np.abs(read(cache).reshape(64, 64, 4)[..., 0] - want).max() < 1e-5,
      "the Blur cache holds the blurred paint image")
raw = MK.sample(paint_e.image, 64)
check(np.abs(want - raw).max() > 0.1 and want.std() < raw.std() * 0.6, "...and is really softer than it (std %.3f against %.3f)" % (want.std(), raw.std()))
calls = []
real_blur = MK.blur
MK.blur = lambda a, amount: (calls.append(1), real_blur(a, amount))[1]
LY.rebuild_all(mm)
check(not calls and not MK.refresh_blurs(mtop), "nothing changed: the cache is not made again")
LY.write_pixels(paint_e.image, np.full(64 * 64 * 4, 0.25, np.float32))
LY.rebuild_all(mm)
check(len(calls) == 1 and abs(read(cache)[0, 0] - 64 / 255) < 1e-5, "painting below the Blur makes the cache again")
blur_e.amount = 0.8
check(len(calls) == 2, "so does its amount")
mtop.opacity = 0.5
check(len(calls) == 2, "...but not an edit of the layer")
MK.blur = real_blur
mtop.opacity = 1.0

# --- Migration: a layer's single mask image (and Invert Mask) becomes a Paint effect (and an Invert effect), same look
for invert in (False, True):
    with LY.muted():
        mtop.mask_stack.clear()
        legacy = mimg("mkLegacy%d" % invert)
        mtop.mask, mtop.mask_invert = legacy, invert
        mtop.opacity, mtop.blend = 0.8, 'MULTIPLY'
        mtop.channels[0].color = (0.9, 0.3, 0.1, 1.0)
    lum = read(legacy).reshape(MN, MN, 4)[..., :3] @ MK.LUMA
    want_alpha = np.clip(1.0 - lum if invert else lum, 0.0, 1.0) * 0.8
    base_lin = LY.to_linear(MK.pixels_of(LY.entry_of(mm.m3d_layers[0], 'BASE_COLOR').image, MN)[..., :3])
    old_look = base_lin * (1 - want_alpha[..., None]) + (base_lin * np.array([0.9, 0.3, 0.1], np.float32)) * want_alpha[..., None]
    LY.rebuild_all(mm)
    check(mtop.mask is None and not mtop.mask_invert and [e.kind for e in mtop.mask_stack] == (['PAINT', 'INVERT'] if invert else ['PAINT'])
          and mtop.mask_stack[0].image == legacy and mtop.mask_stack[0].name == "Mask", "migration (invert %s): the mask is a Paint effect%s" % (invert, " and an Invert effect" if invert else ""))
    check(np.abs(MK.stack_value(mtop, MN) - np.clip(1.0 - lum if invert else lum, 0, 1)).max() < 1e-6, "migration (invert %s): same mask" % invert)
    mine = LY.composite(mm, 'BASE_COLOR', MN)
    nodes_look = bake_chain(mplane, mm, 'BASE_COLOR')
    check(np.abs(mine - nodes_look).max() < 1e-4, "migration (invert %s): numpy composite == node bake (%.6f)" % (invert, np.abs(mine - nodes_look).max()))
    check(np.abs(nodes_look - old_look).max() < 1e-4, "migration (invert %s): the look is what the old chain made (%.6f)" % (invert, np.abs(nodes_look - old_look).max()))
    check(not [n for n in mnodes if n.name.endswith("maskinv")], "migration (invert %s): no old nodes are left" % invert)
mtop.opacity, mtop.blend = 1.0, 'MIX'
bpy.ops.m3d.layer_mask_remove()
check(not mtop.mask_stack, "Remove Mask clears the stack")

# --- Baked maps: baked once, reused by every effect and layer, again after Rebake or a new resolution
mplane.rotation_euler.x = math.radians(90)   # the plane faces -Y, and has some height
bpy.context.view_layer.update()
s0 = {k: bpy.data.images.get("MaskPlane_" + label) for k, label in MK.MAP_LABELS.items()}
check(not any(s0.values()), "no baked maps before the first generator")
mats_before = sorted(m.name for m in bpy.data.materials)
slot_before = [s.material for s in mplane.material_slots]
nodes_before = sorted(n.name for n in mnodes)
for kind in ('EDGES', 'CAVITY', 'TOPDOWN', 'THICKNESS'):
    check(bpy.ops.m3d.mask_effect_add(kind=kind) == {'FINISHED'}, "add mask effect " + kind + " (bakes its maps)")
maps = {k: bpy.data.images.get("MaskPlane_" + label) for k, label in MK.MAP_LABELS.items()}
check(all(maps.values()) and all(tuple(i.size) == (64, 64) for i in maps.values()), "the maps are baked at the Bake tab's resolution: %s" % {k: v and tuple(v.size) for k, v in maps.items()})
st = mtop.mask_stack
check(st[0].image == maps['CURVATURE'] and st[1].image == maps['AO'] and st[2].image == maps['WORLDNORMAL'] and st[2].image2 == maps['POSITION']
      and st[3].image == maps['THICKNESS'] and all(i.use_fake_user for i in maps.values()), "effects point at the baked maps (kept in the file)")
check(sorted(m.name for m in bpy.data.materials) == mats_before and [s.material for s in mplane.material_slots] == slot_before
      and set(nodes_before) <= {n.name for n in mnodes}, "baking left the materials alone")
check(maps['POSITION'].is_float and maps['WORLDNORMAL'].is_float and np.asarray(maps['POSITION'].get("m3d_bounds")).shape == (6,)
      and np.asarray(maps['POSITION'].get("m3d_inv")).shape == (16,), "Position and WorldNormal are float maps; the Position map keeps its bounds")
wn = read(maps['WORLDNORMAL']).reshape(64, 64, 4)[..., :3]
decoded = wn[32, 32] * 2 - 1
check(np.abs(decoded - np.array([0, -1, 0])).max() < 0.02, "WorldNormal holds the world normal n * 0.5 + 0.5 (%s)" % decoded)
pos = read(maps['POSITION']).reshape(64, 64, 4)[..., :3]
check(pos.min() >= 0 and pos.max() <= 1.0 + 1e-6 and pos[..., 0].max() > 0.9 and pos[..., 2].max() > 0.9, "Position is within the bounds (0-1)")
stamps = {k: i.get("m3d_stamp") for k, i in maps.items()}
mtop.mask_index = 0
check(bpy.ops.m3d.mask_effect_add(kind='EDGES') == {'FINISHED'} and {k: i.get("m3d_stamp") for k, i in maps.items()} == stamps
      and mtop.mask_stack[1].image == maps['CURVATURE'], "a second Edges effect reuses the baked map (no rebake)")
mplane.m3d_bake.resolution = '128'
check(bpy.ops.m3d.mask_effect_add(kind='CAVITY') == {'FINISHED'} and maps['AO'].get("m3d_stamp") != stamps['AO'] and tuple(maps['AO'].size) == (128, 128)
      and maps['CURVATURE'].get("m3d_stamp") == stamps['CURVATURE'], "a new resolution rebakes the map that is needed, only that one")
check(bpy.ops.m3d.mask_rebake() == {'FINISHED'} and all(i.get("m3d_stamp") != stamps[k] and tuple(i.size) == (128, 128) for k, i in maps.items()),
      "Rebake Maps bakes them all again")
mplane.m3d_bake.resolution = '64'
check(bpy.ops.m3d.mask_rebake() == {'FINISHED'} and all(tuple(i.size) == (64, 64) for i in maps.values()), "...also back to a smaller size")
# The effects read the real baked maps: numpy still equals the nodes.
real_maps_error = mask_error("the real baked maps (Edges, Cavity, Top-down, Thickness)", 1e-4)

# --- Noise in Object space reads the Position map; numpy evaluates the same noise at the same object coordinates
bpy.ops.m3d.layer_mask_remove()
check(bpy.ops.m3d.mask_effect_add(kind='NOISE') == {'FINISHED'}, "add Noise")
nz = mtop.mask_stack[0]
nz.space = 'OBJECT'
nz.scale, nz.detail, nz.noise_contrast = 1.5, 3.0, 3.0
check(nz.image == maps['POSITION'] and not MK.missing_maps(mtop), "switching Noise to Object space picks up the baked Position map")
check(any(n.type == 'TEX_COORD' and n.outputs["Object"].links for n in mask_nodes(mtop)), "...and reads the Object texture coordinates")
object_noise_error = mask_error("Noise (object space)", 4e-3)
mplane.rotation_euler.x = 0
bpy.context.view_layer.update()
bpy.ops.m3d.layer_mask_remove()

# --- Show Mask: the material shows the mask, then is exactly as it was
def material_state(mat):
    nt = mat.node_tree
    return (sorted(n.name for n in nt.nodes),
            sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in nt.links))


setup([('PAINT', {}), ('EDGES', dict(amount=0.5)), ('LEVELS', {})])
state = material_state(mm)
out_node = next(n for n in mnodes if n.type == 'OUTPUT_MATERIAL')
check(out_node.inputs["Surface"].links[0].from_node.type == 'BSDF_PRINCIPLED', "the shader feeds the output")
mm.m3d_show_mask = True
emit = mnodes[LY.MASKVIEW]
check(out_node.inputs["Surface"].links[0].from_node == emit and emit.inputs["Color"].links[0].from_socket == LY.mask_top(mm.node_tree, mtop)
      and emit[LY.TAG] == "MASKVIEW", "Show Mask: the output shows an Emission node fed by the layer's mask")
shown = bake_out(mplane, mm, lambda t: t.node_tree.nodes[LY.MASKVIEW].inputs["Color"].links[0].from_socket)[..., 0]
check(np.abs(shown - MK.stack_value(mtop, MN)).max() < 1e-4, "...which is the numpy mask")
bpy.ops.m3d.mask_effect_add(kind='INVERT')
check(emit.inputs["Color"].links[0].from_socket == LY.mask_top(mm.node_tree, mtop), "an edit of the stack keeps it on the new mask")
other = mm.m3d_layers[0]
mm.m3d_layer_index = 0
check(not emit.inputs["Color"].links and tuple(emit.inputs["Color"].default_value) == (1.0, 1.0, 1.0, 1.0), "a layer without a mask shows white")
mm.m3d_layer_index = 1
check(emit.inputs["Color"].links[0].from_socket == LY.mask_top(mm.node_tree, mtop), "...and the mask returns with the layer")
with LY.flattened_material(mplane, mm, 8) as temp:
    surface = next(n for n in temp.node_tree.nodes if n.type == 'OUTPUT_MATERIAL').inputs["Surface"]
    check(surface.links and surface.links[0].from_node.type == 'BSDF_PRINCIPLED', "an exporter sees the shader, not the mask view")
check(mm.m3d_show_mask and out_node.inputs["Surface"].links[0].from_node == emit, "...and the view is still on afterwards")
mm.m3d_show_mask = False
bpy.ops.m3d.layer_mask_invert()   # the Invert added above is the top effect: this removes it
check(material_state(mm) == state and LY.MASKVIEW not in mnodes and "m3d_maskview" not in mm.keys(),
      "Show Mask off: the material is exactly as it was (nodes and links)")
mm.m3d_show_mask = True
emit = mnodes[LY.MASKVIEW]
bpy.ops.m3d.layer_mask_remove()
check(out_node.inputs["Surface"].links[0].from_node == emit and not emit.inputs["Color"].links, "removing the mask while it is shown keeps the view (white)")
mm.m3d_show_mask = False
check(out_node.inputs["Surface"].links[0].from_node.type == 'BSDF_PRINCIPLED' and LY.MASKVIEW not in mnodes, "...and off restores the shader")
mm.m3d_show_mask = True
mm.m3d_show_mask = False
check(out_node.inputs["Surface"].links[0].from_node.type == 'BSDF_PRINCIPLED', "on and off again: still the shader")

# --- Merge Down and the flattening use the mask stack
setup([('EDGES', dict(amount=0.6, softness=0.3)), ('NOISE', dict(scale=4.0, noise_contrast=2.0, blend='MULTIPLY'))])
mtop.opacity = 0.8
mtop.channels[0].color = (0.2, 0.7, 0.4, 1.0)
mask_now = MK.stack_value(mtop, MN)
base_px = MK.pixels_of(LY.entry_of(mm.m3d_layers[0], 'BASE_COLOR').image, MN)
base_srgb_lin = LY.to_linear(base_px[..., :3])
fill_lin = np.array([0.2, 0.7, 0.4], np.float32)
a = (mask_now * 0.8)[..., None]
want_flat = LY.encode(LY.CHANNEL_BY_ID['BASE_COLOR'], np.clip(base_srgb_lin + a * (fill_lin - base_srgb_lin), 0, 1))
got_flat = LY.flatten_channel(mm, 'BASE_COLOR', MN)
check(np.abs(got_flat - want_flat).max() < 1e-4, "flattening includes the mask stack (error %.6f)" % np.abs(got_flat - want_flat).max())
check(np.abs(got_flat[..., :3] - want_flat[..., :3]).max() < 1e-4 and mask_now.std() > 0.05, "...a mask that varies")
exp_dir2 = tempfile.mkdtemp(prefix="m3d_masks_export_")
tx = bpy.context.scene.m3d_tex
tx.export_folder, tx.export_size, tx.export_preset = exp_dir2, 'SAME', 'UNREAL'
check(bpy.ops.m3d.tex_export() == {'FINISHED'}, "export of a stack with a mask stack runs")
bc2, _ = load_png(exp_dir2, "T_MaskPlane_BC.png")
check(np.abs(bc2.reshape(MN, MN, 4)[..., :3] - want_flat[..., :3]).max() < 3 / 255, "the exported base color has the mask applied (%.4f)" % np.abs(bc2.reshape(MN, MN, 4)[..., :3] - want_flat[..., :3]).max())
tx.export_preset, tx.export_folder = 'UNITY', "//textures/"
mat_images = {i.name for i in LY.stack_images(mm)}
mtop.blend = 'MIX'
mm.m3d_layer_index = 1
check(bpy.ops.m3d.layer_merge_down() == {'FINISHED'} and [l.name for l in mm.m3d_layers] == ["Base"], "Merge Down of a layer with a mask stack")
merged = read(LY.entry_of(mm.m3d_layers[0], 'BASE_COLOR').image).reshape(MN, MN, 4)
check(np.abs(merged[..., :3] - want_flat[..., :3]).max() < 2 / 255 and not mm.m3d_layers[0].mask_stack, "...the pixels have the mask baked in (%.4f)" % np.abs(merged[..., :3] - want_flat[..., :3]).max())

# --- The Mask panel draws for every kind of effect
LY.rebuild_all(mm)
bpy.ops.m3d.layer_add(kind='FILL')
mtop = mm.m3d_layers[1]
bpy.context.view_layer.objects.active = mplane
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
setup([(k.id, {}) for k in MK.KINDS])
mctx = TCtx()
tex_ws.m3d_page_right = "tex_layers"
check("PROPERTIES_PT_m3d_tx_mask" in tex_shown("tex_layers"), "the Mask panel is shown")
shown_kinds = []
for i, e in enumerate(mtop.mask_stack):
    mtop.mask_index = i
    log = draw_stub(T.PROPERTIES_PT_m3d_tx_mask, mctx)
    check_calls("Mask panel (%s)" % e.kind, log)
    props_drawn = [r._args[1] for r in log if r._kind == "prop" and r._args[0] == e]
    check(props_drawn == [p for p, _l in MK.PARAM_UI.get(e.kind, ())], "the Mask panel shows the settings of %s: %s" % (e.kind, props_drawn))
    shown_kinds.append(e.kind)
log = draw_stub(T.PROPERTIES_PT_m3d_tx_mask, mctx)
check(T.MASK_HELP == "White shows the layer, black hides it. Effects combine from the bottom up."
      and {"White shows the layer, black hides it.", "Effects combine from the bottom up."} <= {r._kw.get("text") for r in log if r._kind == "label"},
      "the Mask panel explains how masks work")
check(LY.depsgraph_post in bpy.app.handlers.depsgraph_update_post and LY.load_post in bpy.app.handlers.load_post, "stroke and load handlers are registered")
check(any(r._kind == "template_list" and r._args[0] == "M3D_UL_mask_effects" for r in log) and any(r._kind == "menu" for r in log), "...lists the effects and has the Add menu")
check(any(r._kind == "operator" and r._args[0] == "m3d.mask_rebake" for r in log) and any(r._kind == "prop" and r._args[1] == "m3d_show_mask" for r in log),
      "...has Rebake maps and Show Mask")
log = []
LY.M3D_UL_mask_effects.draw_item(None, mctx, Rec(log), None, mtop.mask_stack[2], 0, None, "", 0)
check_calls("mask effect row", log)
check({r._args[1] for r in log if r._kind == "prop"} >= {"visible", "name", "blend", "opacity"}, "the effect row shows eye, name, blend and opacity")
log = []
LY.M3D_UL_mask_effects.draw_item(None, mctx, Rec(log), None, mtop.mask_stack[8], 0, None, "", 0)
check("blend" not in {r._args[1] for r in log if r._kind == "prop"}, "a filter's row has no blend mode")
log = []
T.M3D_MT_mask_add.draw(NS(layout=Rec(log)), mctx)
added = [r for r in log if r._kind == "operator"]
check({r._kw["text"] if "text" in r._kw else "" for r in added} >= {"Paint (White)", "Paint (Black)", "Edges", "Cavity", "Top-down", "Thickness", "Noise", "Levels", "Blur", "Invert", "Sharpen"},
      "the Add menu lists Paint, Fill, the generators and the filters")
check_calls("mask add menu", log)
mtop.mask_stack.clear()
log = draw_stub(T.PROPERTIES_PT_m3d_tx_mask, mctx)
check(sum(1 for r in log if r._kind == "operator" and r._args[0] == "m3d.layer_mask_add") == 2, "a layer without a mask offers White and Black")
check_calls("Mask panel (no mask)", log)
check(all(isinstance(MK.M3D_MaskEffect.bl_rna.properties[p], bpy.types.Property) for k in MK.PARAM_UI for p, _l in MK.PARAM_UI[k]), "every shown setting exists")
check(all(LY.M3D_OT_mask_effect_add.description(None, NS(kind=k.id, fill='WHITE')) for k in MK.KINDS), "every effect type has a tooltip")

# --- Saving: the stack, its images, the baked maps and the nodes come back as they were
setup([('PAINT', {}), ('EDGES', dict(amount=0.7, invert=True)), ('NOISE', dict(scale=7.0, seed=4, space='UV')), ('BLUR', dict(amount=0.4)),
       ('LEVELS', dict(gamma=1.7)), ('INVERT', dict(opacity=0.6, visible=False))])
mtop.mask_stack[0].name, mtop.mask_index = "Dirt paint", 3
mm.m3d_show_mask = True
keep = [(e.name, e.kind, e.visible, round(e.opacity, 5), e.blend, e.image.name if e.image else None, e.image2.name if e.image2 else None,
         round(e.amount, 5), e.invert, round(e.scale, 5), e.seed, e.space, round(e.gamma, 5)) for e in mtop.mask_stack]
img_keep = {e.name: read(e.image).copy() for e in mtop.mask_stack if e.image is not None and e.kind in {'PAINT', 'BLUR'}}
node_keep = material_state(mm)
fp_keep = mtop.mask_stack[3].image["m3d_fp"]
mask_path = os.path.join(tempfile.mkdtemp(prefix="m3d_masks_save_"), "masks.blend")
bpy.ops.wm.save_as_mainfile(filepath=mask_path)
bpy.ops.wm.open_mainfile(filepath=mask_path)
tex_ws = bpy.data.workspaces["Texture"]
rm = bpy.data.materials["MaskPlane_Material"] if "MaskPlane_Material" in bpy.data.materials else bpy.data.objects["MaskPlane"].active_material
rl = rm.m3d_layers[1]
check([(e.name, e.kind, e.visible, round(e.opacity, 5), e.blend, e.image.name if e.image else None, e.image2.name if e.image2 else None,
        round(e.amount, 5), e.invert, round(e.scale, 5), e.seed, e.space, round(e.gamma, 5)) for e in rl.mask_stack] == keep and rl.mask_index == 3,
      "the mask stack comes back from the file")
check(all(np.abs(read(e.image) - img_keep[e.name]).max() < 1e-6 for e in rl.mask_stack if e.name in img_keep), "...with its paint image and blur cache pixels")
check(material_state(rm) == node_keep and rm.m3d_show_mask, "...and the same nodes and links (Show Mask included)")
rb = rl.mask_stack[3]
check(rb.image["m3d_fp"] == fp_keep and not MK.refresh_blurs(rl), "...the blur cache is still current (nothing is made again)")
check([i for i in bpy.data.images if i.name.startswith("MaskPlane_") and i.get("m3d_map") and i.get("m3d_stamp")], "...and the baked maps with their marks")
check(LY.rebuild_all(rm) is False, "a rebuild after loading changes nothing")
rm.m3d_show_mask = False

# --- A file from before mask stacks (a mask image and Invert Mask on the layer) is upgraded when it opens
with LY.muted():
    rl.mask_stack.clear()
    old_mask = bpy.data.images.new("mkOldFile", 8, 8, alpha=False, is_data=True)
    LY.write_pixels(old_mask, np.concatenate([np.random.default_rng(9).random((8, 8, 3)), np.ones((8, 8, 1))], axis=-1).astype(np.float32))
    rl.mask, rl.mask_invert = old_mask, True
old_lum = read(old_mask)[:, :3] @ MK.LUMA
old_path = os.path.join(tempfile.mkdtemp(prefix="m3d_masks_old_"), "old.blend")
bpy.ops.wm.save_as_mainfile(filepath=old_path)
bpy.ops.wm.open_mainfile(filepath=old_path)
tex_ws = bpy.data.workspaces["Texture"]
om = bpy.data.materials["MaskPlane_Material"] if "MaskPlane_Material" in bpy.data.materials else bpy.data.objects["MaskPlane"].active_material
ol = om.m3d_layers[1]
check(ol.mask is None and not ol.mask_invert and [e.kind for e in ol.mask_stack] == ['PAINT', 'INVERT'] and ol.mask_stack[0].image.name == "mkOldFile",
      "opening an old file turns the layer's mask into a Paint and an Invert effect: %s" % [e.kind for e in ol.mask_stack])
check(np.abs(MK.stack_value(ol, 8).reshape(-1) - np.clip(1.0 - old_lum, 0, 1)).max() < 1e-6, "...which makes the same mask (inverted)")
check(LY.mask_top(om.node_tree, ol) is not None, "...and the nodes are built")
N = N_saved

# ----------------------------------------------------------------------------------------------------
# Phase 7b: layer folders and freezing (data, operators, node chains, numpy == nodes, freeze / unfreeze, merge,
# export, saving, the Layers tab).
import time

check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in (
    LY.M3D_OT_layer_folder_add, LY.M3D_OT_layer_move_into, LY.M3D_OT_layer_move_out, LY.M3D_OT_layer_freeze,
    LY.M3D_OT_layer_unfreeze, LY.M3D_OT_layer_merge_folder)), "folder operators registered")
check({i.identifier for i in LY.M3D_Layer.bl_rna.properties["kind"].enum_items} == {'PAINT', 'FILL', 'FOLDER'}
      and {"parent", "expanded", "frozen"} <= set(LY.M3D_Layer.bl_rna.properties.keys()), "folder properties")
check({"m3d.layer_folder_add", "m3d.layer_move_into", "m3d.layer_move_out", "m3d.layer_freeze", "m3d.layer_unfreeze",
       "m3d.layer_merge_folder"} <= {e.get("idname") for e in m3d_ui.MENUS["M3D_MT_layers"][1]}, "the Layers menu has the folder operators")
check({"FREEZE", "FILE_FOLDER", "TRIA_RIGHT", "TRIA_DOWN"} <= icons, "folder icons exist")
N = 8


def shape(mat, parent=""):
    """The stack as text, bottom to top, a folder with its layers in brackets: "A Folder[B C] D"."""
    return " ".join(l.name + ("[%s]" % shape(mat, l.uid) if l.kind == 'FOLDER' else "") for l in LY.kids_of(mat, parent))


def well_formed(mat):
    """Every folder is listed right after the layers inside it, every parent exists, uids are unique."""
    uids = [l.uid for l in mat.m3d_layers]
    for f in (l for l in mat.m3d_layers if l.kind == 'FOLDER'):
        inside, i = [l.uid for l in LY.descendants(f)], uids.index(f.uid)
        if inside != uids[i - len(inside):i]:
            return False
    return all(not l.parent or l.parent in uids for l in mat.m3d_layers) and len(set(uids)) == len(uids)


def select(mat, name):
    mat.m3d_layer_index = next(i for i, l in enumerate(mat.m3d_layers) if l.name == name)
    return mat.m3d_layers[mat.m3d_layer_index]


def named(mat, name):
    return next(l for l in mat.m3d_layers if l.name == name)


def chain_names(mat, ch_id):
    """Names of the nodes of a channel's chain (the frame and the Normal Map / Bump nodes left out)."""
    return {n.name for n in mat.node_tree.nodes if n.get(LY.TAG) == ch_id and n.type not in {'FRAME', 'NORMAL_MAP', 'BUMP'}}


def expected_nodes(layers, ch_id, root=True):
    """The nodes a chain must have, worked out from the rules: every layer an opacity node (a mask multiply with a mask),
    an image node (a color node for a fill inside a folder); at the top level a Mix per layer; inside a folder the layers
    after the first have the blend, shown, total, share and out nodes."""
    out = set()
    for i, l in enumerate(l for l in layers if LY.has_content(l, ch_id)):
        part = lambda key: LY.part(ch_id, l.uid, key)
        out.add(part("opv"))
        if l.kind == 'FOLDER' and not l.frozen:
            out |= expected_nodes(LY.children(l), ch_id, False)
        elif LY.uses_image(l):
            out.add(part("tex"))
        elif not root:
            out.add(part("fill"))
        if l.mask_stack:
            out.add(part("maskmul"))
        if root:
            out.add(part("mix"))
        elif i:
            out |= {part(k) for k in ("mix", "shown", "total", "share", "out")}
    return out


def rand_image(image, opaque=False):
    w, h = image.size
    px = fold_rng.random((h, w, 4)).astype(np.float32)
    if opaque:
        px[..., 3] = 1.0
    LY.write_pixels(image, px)


fold_rng = np.random.default_rng(31)

# --- Data and operators on a cube: New Folder, Move Into Folder, the arrows, Move Out, collapse, opacity
fo_ob, fo_mat = fresh_cube("Fold", '64')
for name in ("A", "B", "C"):
    bpy.ops.m3d.layer_add(kind='PAINT')
    LY.active_layer(fo_mat).name = name
    for ch_id in ('ROUGHNESS', 'BASE_COLOR') if name != "B" else ('BASE_COLOR',):
        bpy.ops.m3d.tex_channel(channel=ch_id)
        rand_image(LY.entry_of(LY.active_layer(fo_mat), ch_id).image, opaque=name == "A")
check(shape(fo_mat) == "A B C" and all(not l.parent and l.expanded and not l.frozen for l in fo_mat.m3d_layers),
      "old-style layers have no folder: %s" % shape(fo_mat))
flat_sig = repr([(l.uid, l.kind, LY.entry_of(l, 'BASE_COLOR').image.name, False, True) for l in fo_mat.m3d_layers])
check(LY.signature(LY.chain_tree(LY.kids_of(fo_mat), 'BASE_COLOR'), 'BASE_COLOR') == flat_sig,
      "a stack without folders has the chain signature it had before (nothing is made again when a file opens)")
check(chain_names(fo_mat, 'BASE_COLOR') == expected_nodes(fo_mat.m3d_layers, 'BASE_COLOR')
      and chain_names(fo_mat, 'BASE_COLOR') == {LY.part('BASE_COLOR', l.uid, k) for l in fo_mat.m3d_layers for k in ("opv", "mix", "tex")},
      "a stack without folders has the nodes it always had: an opacity node, an image node and a Mix per layer")

check(bpy.ops.m3d.layer_folder_add() == {'FINISHED'}, "New Folder")
fold = LY.active_layer(fo_mat)
check(fold.kind == 'FOLDER' and fold.name == "Folder" and shape(fo_mat) == "A B C Folder[]" and fo_mat.m3d_layer_index == 3
      and well_formed(fo_mat), "New Folder: an empty folder above the active layer (%s)" % shape(fo_mat))
check(not any(LY.has_content(fold, c.id) for c in LY.CHANNELS) and not [n for n in fo_mat.node_tree.nodes if fold.uid in n.name],
      "an empty folder changes nothing and has no nodes")
check(bpy.ops.m3d.layer_move_into.poll() is False, "Move Into Folder: the active folder cannot go into itself")
select(fo_mat, "B")
check(bpy.ops.m3d.layer_move_into.poll() and bpy.ops.m3d.layer_move_into(folder=named(fo_mat, "Folder").uid) == {'FINISHED'}
      and shape(fo_mat) == "A C Folder[B]" and LY.active_layer(fo_mat).name == "B" and well_formed(fo_mat),
      "Move Into Folder: %s" % shape(fo_mat))
select(fo_mat, "C")
check(bpy.ops.m3d.layer_move_into(folder=named(fo_mat, "Folder").uid) == {'FINISHED'} and shape(fo_mat) == "A Folder[B C]"
      and [l.name for l in fo_mat.m3d_layers] == ["A", "B", "C", "Folder"] and well_formed(fo_mat), "...to the top of the folder: %s" % shape(fo_mat))
check(not bpy.ops.m3d.layer_move_into.poll(), "...and a layer cannot be moved into the folder it is in")
fold = named(fo_mat, "Folder")
check([LY.depth_of(l) for l in fo_mat.m3d_layers] == [0, 1, 1, 0] and [l.name for l in LY.descendants(fold)] == ["B", "C"]
      and [a.name for a in LY.ancestors(named(fo_mat, "C"))] == ["Folder"], "depth, descendants and ancestors")

# Node chains: the folder is one more layer of the chain below it, its layers are chained inside it over nothing.
for ch_id in ('BASE_COLOR', 'ROUGHNESS'):
    check(chain_names(fo_mat, ch_id) == expected_nodes(LY.kids_of(fo_mat), ch_id), "%s chain nodes with a folder" % ch_id)
check([n.name for n in level(fo_mat, 'BASE_COLOR')] == [LY.part('BASE_COLOR', named(fo_mat, "A").uid, "mix"), LY.part('BASE_COLOR', fold.uid, "mix")],
      "the folder has a Mix of its own in the chain, over layer A")
nt = fo_mat.node_tree
nd = lambda ch_id, layer, key: nt.nodes[LY.part(ch_id, layer.uid, key)]
b_layer, c_layer = named(fo_mat, "B"), named(fo_mat, "C")
fm = nd('BASE_COLOR', fold, "mix")
check(fm.inputs[7].links[0].from_node == nd('BASE_COLOR', c_layer, "out") and nd('BASE_COLOR', fold, "opv").inputs[0].links[0].from_node == nd('BASE_COLOR', c_layer, "total")
      and fm.blend_type == 'MIX' and fm.clamp_result,
      "the folder's Mix takes the color and the coverage of its top layer")
check(nd('BASE_COLOR', c_layer, "out").inputs[6].links[0].from_node == nd('BASE_COLOR', b_layer, "tex")
      and nd('BASE_COLOR', c_layer, "mix").inputs[6].links[0].from_node == nd('BASE_COLOR', b_layer, "tex")
      and nd('BASE_COLOR', c_layer, "total").inputs[2].links[0].from_node == nd('BASE_COLOR', b_layer, "opv")
      and nd('BASE_COLOR', c_layer, "out").inputs[0].links[0].from_node == nd('BASE_COLOR', c_layer, "share"),
      "inside the folder the second layer is chained over the first (no start value)")
check(not nd('BASE_COLOR', c_layer, "mix").clamp_result and nd('BASE_COLOR', c_layer, "out").clamp_result
      and nd('BASE_COLOR', c_layer, "total").data_type == 'FLOAT' and nd('BASE_COLOR', c_layer, "share").operation == 'DIVIDE',
      "...with the blend and shown Mix unclamped, the result clamped")
check({n.parent.name for n in nt.nodes if n.get(LY.TAG) == 'BASE_COLOR' and n.type != 'FRAME'} == {"%s.BASE_COLOR" % LY.TAG}, "all of it in the channel's frame")
check(not LY.has_content(fold, 'METALLIC') and LY.has_content(fold, 'ROUGHNESS')
      and chain_names(fo_mat, 'ROUGHNESS') == {LY.part('ROUGHNESS', l.uid, k) for l, k in (
          (named(fo_mat, "A"), "opv"), (named(fo_mat, "A"), "mix"), (named(fo_mat, "A"), "tex"), (fold, "opv"), (fold, "mix"),
          (c_layer, "opv"), (c_layer, "tex"))}, "a channel only some layers have: the folder holds just those (a single layer needs no blending nodes)")

# Values only set node values.
nodes_ptr = {n.name: n.as_pointer() for n in nt.nodes}
fold.opacity, fold.blend = 0.5, 'MULTIPLY'
c_layer.opacity, c_layer.blend, c_layer.visible = 0.4, 'OVERLAY', False
check({n.name: n.as_pointer() for n in nt.nodes} == nodes_ptr, "folder and layer values only change node values")
check(abs(nd('BASE_COLOR', fold, "opv").inputs[1].default_value - 0.5) < 1e-6 and fm.blend_type == 'MULTIPLY'
      and nd('BASE_COLOR', c_layer, "opv").inputs[1].default_value == 0.0 and nd('BASE_COLOR', c_layer, "mix").blend_type == 'OVERLAY',
      "...opacity, blend mode and visibility of the folder and of a layer inside it")
fold.opacity, fold.blend, c_layer.opacity, c_layer.blend, c_layer.visible = 1.0, 'MIX', 1.0, 'MIX', True

# The arrows step through the list, in and out of open folders.
select(fo_mat, "C")
steps_expected = [(1, "A Folder[B] C"), (-1, "A Folder[B C]"), (-1, "A Folder[C B]"), (-1, "A C Folder[B]"), (-1, "C A Folder[B]"),
                  (-1, None), (1, "A C Folder[B]"), (1, "A Folder[C B]"), (1, "A Folder[B C]")]
for delta, want in steps_expected:
    res = bpy.ops.m3d.layer_move(delta=delta)
    check((res == {'CANCELLED'}) if want is None else (res == {'FINISHED'} and shape(fo_mat) == want and well_formed(fo_mat)
                                                         and LY.active_layer(fo_mat).name == "C"),
          "Move %s: %s (want %s)" % ("Up" if delta > 0 else "Down", shape(fo_mat), want))
for ch_id in ('BASE_COLOR', 'ROUGHNESS'):
    check(chain_names(fo_mat, ch_id) == expected_nodes(LY.kids_of(fo_mat), ch_id), "%s chain follows the moves" % ch_id)
check(slot_image(fo_mat) == LY.entry_of(named(fo_mat, "C"), 'BASE_COLOR').image, "the paint target follows a layer into and out of a folder")
check(bpy.ops.m3d.layer_move_out.poll() and bpy.ops.m3d.layer_move_out() == {'FINISHED'} and shape(fo_mat) == "A Folder[B] C"
      and not LY.active_layer(fo_mat).parent and not bpy.ops.m3d.layer_move_out.poll(), "Move Out of Folder: above the folder")
check(bpy.ops.m3d.layer_move_into(folder=named(fo_mat, "Folder").uid) == {'FINISHED'} and shape(fo_mat) == "A Folder[B C]", "...and Move Into again")

# Collapse: the list hides the layers inside; the active layer inside moves to the folder.
fold = named(fo_mat, "Folder")
select(fo_mat, "C")
flags = LY.M3D_UL_layers.filter_items(NS(bitflag_filter_item=1 << 30), None, fo_mat, "m3d_layers")[0]
check(flags == [1 << 30] * 4, "an open folder hides nothing in the list")
fold.expanded = False
check(LY.active_layer(fo_mat).name == "Folder", "closing a folder that holds the active layer selects the folder")
flags = LY.M3D_UL_layers.filter_items(NS(bitflag_filter_item=1 << 30), None, fo_mat, "m3d_layers")[0]
check(flags == [1 << 30, 0, 0, 1 << 30], "a closed folder hides the layers inside it: %s" % flags)
select(fo_mat, "A")
check(bpy.ops.m3d.layer_move(delta=1) == {'FINISHED'} and shape(fo_mat) == "Folder[B C] A", "a closed folder is passed as a block: %s" % shape(fo_mat))
check(bpy.ops.m3d.layer_move(delta=-1) == {'FINISHED'} and shape(fo_mat) == "A Folder[B C]", "...also downwards")
fold.expanded = True
check(chain_names(fo_mat, 'BASE_COLOR') == expected_nodes(LY.kids_of(fo_mat), 'BASE_COLOR'), "opening and closing a folder does not touch the nodes")

# Group Active, Duplicate Folder, Delete Folder (images), Show / Hide
select(fo_mat, "A")
check(bpy.ops.m3d.layer_folder_add(group=True) == {'FINISHED'} and shape(fo_mat) == "Folder 2[A] Folder[B C]"
      and LY.active_layer(fo_mat).name == "Folder 2" and well_formed(fo_mat), "Group Active: %s" % shape(fo_mat))
select(fo_mat, "Folder")
images_before = {i.name for i in bpy.data.images}
check(bpy.ops.m3d.layer_duplicate() == {'FINISHED'} and shape(fo_mat) == "Folder 2[A] Folder[B C] Folder Copy[B Copy C Copy]"
      and LY.active_layer(fo_mat).name == "Folder Copy" and well_formed(fo_mat), "Duplicate Folder: %s" % shape(fo_mat))
copy_f = named(fo_mat, "Folder Copy")
new_images = {i.name for i in bpy.data.images} - images_before
check(len(new_images) == 3 and all(np.array_equal(read(LY.entry_of(named(fo_mat, n + " Copy"), c).image), read(LY.entry_of(named(fo_mat, n), c).image))
                                   for n, c in (("B", 'BASE_COLOR'), ("C", 'BASE_COLOR'), ("C", 'ROUGHNESS')))
      and len({l.uid for l in fo_mat.m3d_layers}) == 8, "...its layers' images are copied (%d new images)" % len(new_images))
for ch_id in ('BASE_COLOR', 'ROUGHNESS'):
    check(chain_names(fo_mat, ch_id) == expected_nodes(LY.kids_of(fo_mat), ch_id), "%s chain with the copy" % ch_id)
shared = bpy.data.images.new("m3dFoldShared", 8, 8)
LY.entry_of(named(fo_mat, "C Copy"), 'METALLIC').image = shared
LY.entry_of(named(fo_mat, "A"), 'METALLIC').image = shared
check(bpy.ops.m3d.layer_remove() == {'FINISHED'} and shape(fo_mat) == "Folder 2[A] Folder[B C]" and well_formed(fo_mat)
      and {i.name for i in bpy.data.images} == images_before | {"m3dFoldShared"},
      "Delete Folder removes its layers and their images, but not an image used elsewhere: %s" % shape(fo_mat))
LY.entry_of(named(fo_mat, "A"), 'METALLIC').image = None
bpy.data.images.remove(shared)
check(LY.active_layer(fo_mat).name == "Folder", "...and the layer after it is selected (%s)" % LY.active_layer(fo_mat).name)
fold2 = named(fo_mat, "Folder 2")
fold2.visible = False
check(nd('ROUGHNESS', fold2, "opv").inputs[1].default_value == 0.0, "a hidden folder has factor 0 in the chains")
fold2.visible = True

# Merge Down: a layer onto a leaf below it in the same folder; the layer at the bottom of a folder has none.
select(fo_mat, "B")
check(not bpy.ops.m3d.layer_merge_down.poll(), "Merge Down: the lowest layer of a folder has none below it in the folder")
select(fo_mat, "C")
check(bpy.ops.m3d.layer_merge_down.poll(), "...the one above it can merge down")
select(fo_mat, "Folder")
check(bpy.ops.m3d.layer_merge_down.poll() is False, "...a folder cannot merge down onto a folder (Merge Folder first)")

# --- Nested folders: a folder moved into a folder, copied, deleted, moved out
select(fo_mat, "Folder 2")
check(bpy.ops.m3d.layer_move_into(folder=named(fo_mat, "Folder").uid) == {'FINISHED'} and shape(fo_mat) == "Folder[B C Folder 2[A]]"
      and well_formed(fo_mat) and [LY.depth_of(named(fo_mat, n)) for n in ("Folder", "B", "Folder 2", "A")] == [0, 1, 1, 2],
      "a folder moved into a folder: %s" % shape(fo_mat))
for ch_id in ('BASE_COLOR', 'ROUGHNESS'):
    check(chain_names(fo_mat, ch_id) == expected_nodes(LY.kids_of(fo_mat), ch_id), "%s chain with nested folders" % ch_id)
select(fo_mat, "Folder")
check(not bpy.ops.m3d.layer_move_into.poll(), "a folder cannot be moved into a folder inside it")
check(bpy.ops.m3d.layer_duplicate() == {'FINISHED'}
      and shape(fo_mat) == "Folder[B C Folder 2[A]] Folder Copy[B Copy C Copy Folder 2 Copy[A Copy]]" and well_formed(fo_mat),
      "Duplicate copies nested folders: %s" % shape(fo_mat))
check(bpy.ops.m3d.layer_remove() == {'FINISHED'} and shape(fo_mat) == "Folder[B C Folder 2[A]]" and well_formed(fo_mat)
      and {i.name for i in bpy.data.images} == images_before, "...and Delete removes them with their images")
select(fo_mat, "Folder 2")
check(bpy.ops.m3d.layer_move_out() == {'FINISHED'} and shape(fo_mat) == "Folder[B C] Folder 2[A]" and well_formed(fo_mat),
      "Move Out of Folder: %s" % shape(fo_mat))

# --- Merge Folder: the folder becomes one paint layer holding what its layers made together
select(fo_mat, "Folder")
fold = LY.active_layer(fo_mat)
fold.blend, fold.opacity = 'MULTIPLY', 0.6
bpy.ops.m3d.layer_mask_add(fill='WHITE')
LY.write_pixels(LY.paint_effect(fold).image, np.concatenate([fold_rng.random((64 * 64, 3)), np.ones((64 * 64, 1))], axis=-1).astype(np.float32))
before = {c: LY.composite(fo_mat, c, 64) for c in ('BASE_COLOR', 'ROUGHNESS')}
mask_name, kids_images = LY.paint_effect(fold).image.name, [e.image.name for l in LY.descendants(fold) for e in l.channels if e.image]
check(bpy.ops.m3d.layer_merge_folder() == {'FINISHED'} and shape(fo_mat) == "Folder Folder 2[A]" and well_formed(fo_mat), "Merge Folder: %s" % shape(fo_mat))
merged = named(fo_mat, "Folder")
check(merged.kind == 'PAINT' and merged.blend == 'MULTIPLY' and abs(merged.opacity - 0.6) < 1e-6 and merged.visible and merged.use_alpha
      and LY.paint_effect(merged) is not None and LY.paint_effect(merged).image.name == mask_name and not merged.frozen,
      "...it keeps the folder's name, blend mode, opacity and mask")
check(not [n for n in kids_images if n in bpy.data.images] and len(LY.kids_of(fo_mat)) == 2 and not LY.children(merged), "...the layers inside and their images are gone")
check(LY.has_content(merged, 'BASE_COLOR') and LY.has_content(merged, 'ROUGHNESS') and not LY.has_content(merged, 'METALLIC')
      and LY.entry_of(merged, 'BASE_COLOR').image.colorspace_settings.name == 'sRGB'
      and LY.entry_of(merged, 'ROUGHNESS').image.colorspace_settings.name == 'Non-Color', "...with an image for the channels the layers had")
for ch_id, tol in (('BASE_COLOR', 0.012), ('ROUGHNESS', 0.006)):
    after = LY.composite(fo_mat, ch_id, 64)
    check(np.abs(after - before[ch_id]).max() < tol, "the merged folder looks the same: %s (largest difference %.5f)" % (ch_id, np.abs(after - before[ch_id]).max()))
    check(chain_names(fo_mat, ch_id) == expected_nodes(LY.kids_of(fo_mat), ch_id), "%s chain after Merge Folder" % ch_id)

# --- The Layers tab with folders (data stubs)
tex_ws = bpy.data.workspaces["Texture"]
fo_ctx = TCtx()
select(fo_mat, "Folder 2")
for what, name in (("folder", "Folder 2"), ("layer in a folder", "A")):
    select(fo_mat, name)
    for cls in (T.PROPERTIES_PT_m3d_tx_stack, T.PROPERTIES_PT_m3d_tx_layer, T.PROPERTIES_PT_m3d_tx_mask):
        log = draw_stub(cls, fo_ctx)
        check_calls("%s with the active %s" % (cls.__name__, what), log)
        if cls is T.PROPERTIES_PT_m3d_tx_stack:
            ops = {r._args[0] for r in log if r._kind in {"operator", "operator_menu_enum"}}
            check({"m3d.layer_add", "m3d.layer_folder_add", "m3d.layer_move_into", "m3d.layer_move_out"} <= ops,
                  "the Layers panel has New Folder, Group, Move In and Move Out: %s" % sorted(ops))
            check(sum(1 for r in log if r._kind == "operator" and r._args[0] == "m3d.layer_folder_add") == 2, "...New Folder next to Paint Layer and Fill Layer, and Group")
        if cls is T.PROPERTIES_PT_m3d_tx_layer and what == "folder":
            ops = {r._args[0] for r in log if r._kind == "operator"}
            check({"m3d.layer_freeze", "m3d.layer_merge_folder"} <= ops
                  and {r._args[1] for r in log if r._kind == "prop"} >= {"name", "blend", "opacity", "visible"}, "the Layer panel of a folder: properties, Freeze, Merge Folder")
rows = []
for layer in fo_mat.m3d_layers:
    log = []
    LY.M3D_UL_layers.draw_item(None, fo_ctx, Rec(log), None, layer, 0, None, "", LY.index_of(fo_mat, layer.uid))
    check_calls("layer list row of " + layer.name, log)
    props = {r._args[1] for r in log if r._kind == "prop"}
    check(props >= {"visible", "name", "blend", "opacity"} and ("expanded" in props) == (layer.kind == 'FOLDER'), "list row of %s: %s" % (layer.name, sorted(props)))
    check(any(r._kind == "separator" for r in log) == bool(layer.parent), "...children are indented")
    check(any(r._kind == "operator" and r._args[0] == "m3d.layer_freeze" for r in log) == (layer.kind == 'FOLDER'), "...a folder row has the freeze toggle")
check(bpy.ops.m3d.layer_folder_add.poll(), "New Folder works in Texture Paint Mode")

# --- numpy == nodes with folders (a Cycles emission bake of the chain's top, against LY.composite)
clean_scene()
bpy.ops.mesh.primitive_plane_add()
fplane = bpy.context.active_object
fplane.name = "FolderCheck"
bpy.ops.m3d.tex_add_material()
fpm = fplane.active_material

CH = {'BASE_COLOR': True, 'ROUGHNESS': False}   # channel -> sRGB image


def build_stack(mat, spec, chans=('ROUGHNESS',)):
    """The layers [(name, kind, parent name, settings)] from the bottom, a folder after its layers. Settings are layer
    properties, plus img ('opaque' / 'alpha': noise images for every channel in `chans`), value / color (fills) and mask."""
    with LY.muted():
        mat.m3d_layers.clear()
        for image in [i for i in bpy.data.images if i.name.startswith("fx")]:   # (the images of the stack before)
            bpy.data.images.remove(image)
        for name, kind, _parent, _props in spec:
            LY.add_layer(mat, kind, name)
        by = {l.name: l for l in mat.m3d_layers}
        for name, kind, parent, props in spec:
            l, props = by[name], dict(props)
            l.parent = by[parent].uid if parent else ""
            img, mask = props.pop("img", None), props.pop("mask", False)
            value, color = props.pop("value", 0.3), props.pop("color", (0.7, 0.2, 0.4, 1.0))
            for ch in LY.CHANNELS:
                LY.entry_of(l, ch.id).use = False
            for ch_id in chans:
                e = LY.entry_of(l, ch_id)
                e.use = kind != 'FOLDER'
                e.value, e.color = value, color
                if img:
                    e.image = noise_image("fx_%s_%s_%s" % (name, ch_id, fold_rng.integers(10 ** 6)), CH[ch_id], opaque=img == 'opaque')
            for key, value_ in props.items():
                setattr(l, key, value_)
            if mask:
                set_mask(l, noise_image("fxm_%s_%s" % (name, fold_rng.integers(10 ** 6)), False, alpha=False))
        mat.m3d_layer_index = 0
    LY.rebuild_all(mat)
    return {l.name: l for l in mat.m3d_layers}


def spec_folder(mode, opacity, **over_):
    """Base, a folder (blend mode and opacity as given) of two noise layers and a fill, a layer on top."""
    mode2 = 'OVERLAY' if mode != 'OVERLAY' else 'DARKEN'
    spec = [("Base", 'PAINT', "", dict(img='opaque')),
            ("C1", 'PAINT', "F", dict(img='alpha', opacity=0.8)),
            ("C2", 'PAINT', "F", dict(img='alpha', blend=mode, opacity=0.65)),
            ("C3", 'FILL', "F", dict(blend=mode2, opacity=0.5)),
            ("F", 'FOLDER', "", dict(blend=mode, opacity=opacity)),
            ("Top", 'PAINT', "", dict(img='alpha', blend='MULTIPLY', opacity=0.9))]
    for i, (name, kind, parent, props) in enumerate(spec):
        spec[i] = (name, kind, parent, {**props, **over_.get(name, {})})
    return spec


def bake_error(label, mat, ch_id, tol, store):
    got = bake_chain(fplane, mat, ch_id)
    mine = LY.composite(mat, ch_id, N)
    err = float(np.abs(got - mine).max())
    store.setdefault(ch_id, []).append(err)
    check(err < tol, "numpy matches the node chain with folders: %s (%s, error %.5f)" % (label, ch_id, err))
    return err


fold_worst, fold_srgb_opaque = {}, {}
# Data channels are exact (float rounding). sRGB images with alpha are not: Cycles keeps them with the colour multiplied by
# the alpha in 8 bits, which costs about 1% (a flat stack without folders has the same error, see the layer blend test).
DATA_TOL, SRGB_TOL, SRGB_OPAQUE_TOL = 2e-4, 0.012, 2e-4
for mode, _label in LY.BLENDS:
    for opacity in (1.0, 0.5):
        L_ = build_stack(fpm, spec_folder(mode, opacity))
        check(chain_names(fpm, 'ROUGHNESS') == expected_nodes(LY.kids_of(fpm), 'ROUGHNESS') and well_formed(fpm), "nodes of the folder test stack")
        bake_error("%s at %.1f" % (mode, opacity), fpm, 'ROUGHNESS', DATA_TOL, fold_worst)
for mode in ('MIX', 'MULTIPLY', 'SOFT_LIGHT', 'COLOR'):
    build_stack(fpm, spec_folder(mode, 0.7), chans=('BASE_COLOR',))
    bake_error("%s base color" % mode, fpm, 'BASE_COLOR', SRGB_TOL, fold_worst)
    build_stack(fpm, [(n, k, p_, {**pr, "img": "opaque"} if pr.get("img") else pr) for n, k, p_, pr in spec_folder(mode, 0.7)], chans=('BASE_COLOR',))
    bake_error("%s base color (opaque images)" % mode, fpm, 'BASE_COLOR', SRGB_OPAQUE_TOL, fold_srgb_opaque)
# masks on the folder and on one of its layers, hidden folder / layer / first layer / all layers, a folder over nothing but fills
scenarios = (
    ("folder mask", spec_folder('SCREEN', 0.8, F=dict(mask=True))),
    ("layer mask", spec_folder('ADD', 1.0, C2=dict(mask=True), C1=dict(mask=True))),
    ("both masks", spec_folder('SUBTRACT', 0.6, F=dict(mask=True), C2=dict(mask=True))),
    ("hidden folder", spec_folder('MULTIPLY', 1.0, F=dict(visible=False))),
    ("hidden layer", spec_folder('DIFFERENCE', 1.0, C2=dict(visible=False))),
    ("hidden first layer", spec_folder('LIGHTEN', 0.9, C1=dict(visible=False))),
    ("hidden layers", spec_folder('SOFT_LIGHT', 0.9, C1=dict(visible=False), C2=dict(visible=False), C3=dict(visible=False))),
    ("folder opacity 0", spec_folder('MIX', 0.0)),
)
for label, spec in scenarios:
    for ch_id in ('ROUGHNESS', 'BASE_COLOR'):
        build_stack(fpm, spec, chans=(ch_id,))
        bake_error("%s %s" % (label, ch_id), fpm, ch_id, DATA_TOL if ch_id == 'ROUGHNESS' else SRGB_TOL, fold_worst)
# a folder in a folder, and a folder first in the stack (over the channel's value)
nested = [("Base", 'PAINT', "", dict(img='opaque')),
          ("C1", 'PAINT', "F", dict(img='alpha', opacity=0.8)),
          ("G1", 'PAINT', "G", dict(img='alpha', blend='MULTIPLY', opacity=0.7)),
          ("G2", 'PAINT', "G", dict(img='alpha', blend='SOFT_LIGHT')),
          ("G", 'FOLDER', "F", dict(blend='OVERLAY', opacity=0.75)),
          ("C3", 'FILL', "F", dict(blend='ADD', opacity=0.5)),
          ("F", 'FOLDER', "", dict(blend='COLOR', opacity=0.9)),
          ("Top", 'PAINT', "", dict(img='alpha', opacity=0.9))]
for ch_id in ('ROUGHNESS', 'BASE_COLOR'):
    build_stack(fpm, nested, chans=(ch_id,))
    check(shape(fpm) == "Base F[C1 G[G1 G2] C3] Top" and well_formed(fpm) and chain_names(fpm, ch_id) == expected_nodes(LY.kids_of(fpm), ch_id),
          "a folder in a folder: %s" % shape(fpm))
    bake_error("nested folders", fpm, ch_id, DATA_TOL if ch_id == 'ROUGHNESS' else SRGB_TOL, fold_worst)
    first = [("C1", 'PAINT', "F", dict(img='alpha', opacity=0.8)), ("C2", 'PAINT', "F", dict(img='alpha', blend='MULTIPLY')),
             ("F", 'FOLDER', "", dict(blend='OVERLAY', opacity=0.8)), ("Top", 'PAINT', "", dict(img='alpha', opacity=0.9))]
    build_stack(fpm, first, chans=(ch_id,))
    bake_error("a folder at the bottom", fpm, ch_id, DATA_TOL if ch_id == 'ROUGHNESS' else SRGB_TOL, fold_worst)
print("folders vs Cycles bake: worst linear error %.6f (data channel), %.6f (sRGB, opaque images), %.5f (sRGB with alpha), %d bakes" % (
    max(fold_worst['ROUGHNESS']), max(fold_srgb_opaque['BASE_COLOR']), max(fold_worst['BASE_COLOR']),
    sum(map(len, fold_worst.values())) + sum(map(len, fold_srgb_opaque.values()))))

# --- Freeze: one image per channel, the chain loses the layers' nodes, the look stays, Unfreeze restores everything
CHANS2 = ('BASE_COLOR', 'ROUGHNESS')
fz_spec = spec_folder('OVERLAY', 0.8, F=dict(mask=True), C2=dict(mask=True))
build_stack(fpm, fz_spec, chans=CHANS2)
fold = named(fpm, "F")
live = {c: LY.composite(fpm, c, N) for c in CHANS2}
state_live = material_state(fpm)
count_live, tagged_live = len(fpm.node_tree.nodes), len([n for n in fpm.node_tree.nodes if LY.TAG in n.keys()])
images_live = {i.name for i in bpy.data.images}
kids_before = [(l.name, l.uid, l.opacity, l.visible) for l in LY.descendants(fold)]
t0 = time.perf_counter()
LY.freeze_folder(fpm, LY.index_of(fpm, fold.uid), 16)
freeze_time = time.perf_counter() - t0
fold = named(fpm, "F")
frozen_images = {e.channel: e.image for e in fold.channels if e.image}
check(fold.frozen and set(frozen_images) == set(CHANS2) and all(e.use == (e.channel in CHANS2) for e in fold.channels),
      "Freeze: one image per channel the layers change (%s)" % sorted(frozen_images))
check(all(tuple(img.size) == (8, 8) for img in frozen_images.values()), "...at the largest size of the layers' images (not the default 16)")
check(frozen_images['BASE_COLOR'].colorspace_settings.name == 'sRGB' and frozen_images['ROUGHNESS'].colorspace_settings.name == 'Non-Color'
      and all(img["m3d_channel"] == c for c, img in frozen_images.items()) and all(img.depth == 32 for img in frozen_images.values()),
      "...sRGB for color, Non-Color for data, with alpha, tagged with their channel")
check(all("Frozen" in img.name for img in frozen_images.values()) and fold.use_alpha, "...named after the folder")
check(shape(fpm) == "Base F[C1 C2 C3] Top" and [(l.name, l.uid, l.opacity, l.visible) for l in LY.descendants(fold)] == kids_before
      and all(e.image is not None for l in LY.descendants(fold) for e in l.channels if e.use and l.kind == 'PAINT'),
      "the layers are kept in the data, untouched")
for ch_id in CHANS2:
    check(chain_names(fpm, ch_id) == expected_nodes(LY.kids_of(fpm), ch_id)
          and chain_names(fpm, ch_id) == {LY.part(ch_id, l.uid, k) for l, ks in ((named(fpm, "Base"), ("opv", "mix", "tex")), (fold, ("opv", "mix", "tex", "maskmul")),
                                                                              (named(fpm, "Top"), ("opv", "mix", "tex"))) for k in ks},
          "%s chain after Freeze: the folder is an image node, an opacity node, a mask multiply and a Mix" % ch_id)
check(not [n for n in fpm.node_tree.nodes if any(l.uid in n.name for l in LY.descendants(fold))], "...no node of a frozen layer is left (masks included)")
count_frozen = len(fpm.node_tree.nodes)
check(count_frozen < count_live, "Freeze drops the node count (%d -> %d)" % (count_live, count_frozen))
print("freeze node counts of a small stack (2 channels, 3 layers in the folder, masks): %d -> %d" % (count_live, count_frozen))
check(LY.frozen_root(named(fpm, "C1")) is not None and LY.in_frozen(named(fpm, "C1")) and not LY.in_frozen(fold) and LY.frozen_root(fold).uid == fold.uid, "frozen_root / in_frozen")
frozen_diff = {}
FREEZE_TOL = 0.012   # 8 bit images: what is stored in the frozen images is rounded to 1/255, in colour and in coverage
for ch_id in CHANS2:
    err = float(np.abs(LY.composite(fpm, ch_id, N) - live[ch_id]).max())
    check(err < FREEZE_TOL, "frozen == live in numpy: %s (largest difference %.5f)" % (ch_id, err))
    frozen_diff.setdefault("numpy", []).append(err)
for ch_id, tol in (('ROUGHNESS', DATA_TOL), ('BASE_COLOR', SRGB_TOL)):
    bake_error("frozen", fpm, ch_id, tol, fold_worst)
    err = float(np.abs(bake_chain(fplane, fpm, ch_id) - live[ch_id]).max())
    check(err < FREEZE_TOL, "frozen nodes == live numpy: %s (largest difference %.5f)" % (ch_id, err))
    frozen_diff.setdefault("nodes", []).append(err)
print("frozen vs live: worst linear difference %.5f in numpy, %.5f in node bakes; Freeze of this small folder took %.3f s" % (
    max(frozen_diff["numpy"]), max(frozen_diff["nodes"]), freeze_time))
check(bpy.ops.m3d.layer_freeze.poll(), "Freeze Folder is available")
LY.unfreeze_folder(fpm, LY.index_of(fpm, fold.uid))
fold = named(fpm, "F")
check(not fold.frozen and all(not e.use and e.image is None for e in fold.channels) and {i.name for i in bpy.data.images} == images_live,
      "Unfreeze deletes the frozen images")
check(material_state(fpm) == state_live and len(fpm.node_tree.nodes) == count_live, "Unfreeze restores the live chains: the same nodes and links")
for ch_id in CHANS2:
    check(np.abs(LY.composite(fpm, ch_id, N) - live[ch_id]).max() < 1e-6, "...and the same look: %s" % ch_id)
# Refreshed after an edit: unfreeze, change a layer, freeze again.
rand_image(LY.entry_of(named(fpm, "C1"), 'ROUGHNESS').image)
named(fpm, "C2").opacity = 0.2
live2 = LY.composite(fpm, 'ROUGHNESS', N)
LY.freeze_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid), 16)
check(np.abs(LY.composite(fpm, 'ROUGHNESS', N) - live2).max() < FREEZE_TOL and len(bpy.data.images) == len(images_live) + 2,
      "Freeze again after an edit shows the edit (and makes the same number of images)")
LY.unfreeze_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid))

# Default size when no layer has an image
fills = [("C1", 'FILL', "F", dict(blend='MULTIPLY')), ("C2", 'FILL', "F", dict(value=0.9)), ("F", 'FOLDER', "", dict(opacity=0.5))]
build_stack(fpm, [("Base", 'PAINT', "", dict(img='opaque'))] + fills, chans=('ROUGHNESS',))
LY.freeze_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid), 16)
fimg = LY.entry_of(named(fpm, "F"), 'ROUGHNESS').image
check(tuple(fimg.size) == (16, 16) and LY.has_content(named(fpm, "F"), 'ROUGHNESS') and not LY.has_content(named(fpm, "F"), 'BASE_COLOR'),
      "a folder of fills freezes at the default size: %s" % (tuple(fimg.size),))
check(np.abs(read(fimg).reshape(16, 16, 4)[..., 3] - 1.0).max() < 1e-6, "...fully covered")
LY.unfreeze_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid))

# --- A frozen folder in Merge Down, Merge Folder, Flatten and Export gives what the live folder gives
mode_spec = spec_folder('MULTIPLY', 0.7, F=dict(mask=True), C2=dict(mask=True))
build_stack(fpm, mode_spec, chans=CHANS2)
live_comp = {c: LY.composite(fpm, c, N) for c in CHANS2}
live_flat = {c: LY.flatten_channel(fpm, c, N) for c in CHANS2}
exp_tx = bpy.context.scene.m3d_tex
exp_tx.export_folder, exp_tx.export_size, exp_tx.export_preset = tempfile.mkdtemp(prefix="m3d_fold_live_"), 'SAME', 'UNREAL'
bpy.context.view_layer.objects.active = fplane
exp_live = T.export_textures(bpy.context, fplane)
live_bc, _i1 = load_png(exp_tx.export_folder, "T_FolderCheck_BC.png")
LY.freeze_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid), 16)
for ch_id in CHANS2:
    err = float(np.abs(LY.flatten_channel(fpm, ch_id, N) - live_flat[ch_id]).max())
    check(err < FREEZE_TOL + (0.012 if ch_id == 'BASE_COLOR' else 0), "Flatten of a frozen folder == live: %s (largest difference %.5f)" % (ch_id, err))
exp_tx.export_folder = tempfile.mkdtemp(prefix="m3d_fold_frozen_")
exp_frozen = T.export_textures(bpy.context, fplane)
frozen_bc, _i2 = load_png(exp_tx.export_folder, "T_FolderCheck_BC.png")
live_orm, _i3 = load_png(os.path.dirname(exp_live[0]), "T_FolderCheck_ORM.png")
frozen_orm, _i4 = load_png(exp_tx.export_folder, "T_FolderCheck_ORM.png")
check([os.path.basename(p) for p in exp_live] == [os.path.basename(p) for p in exp_frozen] and len(exp_frozen) == 2
      and np.abs(frozen_bc - live_bc).max() < 5 / 255 and np.abs(frozen_orm - live_orm).max() < 3 / 255,
      "Export of a frozen folder == live (base color %.4f, ORM %.4f)" % (np.abs(frozen_bc - live_bc).max(), np.abs(frozen_orm - live_orm).max()))
want_bc = LY.to_srgb(live_comp['BASE_COLOR']).reshape(-1, 3)
check(np.abs(live_bc[:, :3] - want_bc).max() < 3 / 255, "...and the exported base color is the folder's composite (%.4f)" % np.abs(live_bc[:, :3] - want_bc).max())
for img in (_i1, _i2, _i3, _i4):
    bpy.data.images.remove(img)
# Merge Down of the frozen folder onto the layer below, and Merge Folder of a frozen one (its images are the layer's)
frozen_images = {e.channel: e.image.name for e in named(fpm, "F").channels if e.image}
LY.merge_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid), 16)
check(shape(fpm) == "Base F Top" and named(fpm, "F").kind == 'PAINT' and not named(fpm, "F").frozen
      and {e.channel: e.image.name for e in named(fpm, "F").channels if e.image} == {c: n.replace(" Frozen", "").replace("Frozen", "") for c, n in frozen_images.items()}
      and not any("Frozen" in i.name for i in bpy.data.images) and not [i for i in bpy.data.images if i.name.startswith("fx_C")],
      "Merge Folder of a frozen folder: its images become the paint layer's, the layers inside go (%s)" % shape(fpm))
for ch_id in CHANS2:
    err = float(np.abs(LY.composite(fpm, ch_id, N) - live_comp[ch_id]).max())
    check(err < FREEZE_TOL, "...the same look (%s, %.5f)" % (ch_id, err))
build_stack(fpm, mode_spec, chans=CHANS2)
live_comp = {c: LY.composite(fpm, c, N) for c in CHANS2}
LY.freeze_folder(fpm, LY.index_of(fpm, named(fpm, "F").uid), 16)
# the frozen folder merges down onto the layer below it (Base)
fpm.m3d_layer_index = LY.index_of(fpm, named(fpm, "F").uid)
LY.merge_down(fpm, fpm.m3d_layer_index, 16)
check(shape(fpm) == "Base Top" and not any("Frozen" in i.name for i in bpy.data.images) and not [i for i in bpy.data.images if i.name.startswith("fx_C")],
      "Merge Down of a frozen folder: %s, its images and its layers' images are gone" % shape(fpm))
for ch_id in CHANS2:
    err = float(np.abs(LY.composite(fpm, ch_id, N) - live_comp[ch_id]).max())
    check(err < FREEZE_TOL + 0.01, "...the same look as the live folder (%s, %.5f)" % (ch_id, err))
# Merge Down of a live folder, and of a layer onto a layer below it inside a folder
build_stack(fpm, mode_spec, chans=CHANS2)
live_comp = {c: LY.composite(fpm, c, N) for c in CHANS2}
LY.merge_down(fpm, LY.index_of(fpm, named(fpm, "F").uid), 16)
check(shape(fpm) == "Base Top", "Merge Down of a live folder: %s" % shape(fpm))
for ch_id in CHANS2:
    err = float(np.abs(LY.composite(fpm, ch_id, N) - live_comp[ch_id]).max())
    check(err < 2.5 / 255 + 0.004, "...the same look (%s, %.5f)" % (ch_id, err))
build_stack(fpm, spec_folder('MIX', 0.7, F=dict(mask=True), C2=dict(mask=True, blend='MIX')), chans=CHANS2)
live_comp = {c: LY.composite(fpm, c, N) for c in CHANS2}
LY.merge_down(fpm, LY.index_of(fpm, named(fpm, "C2").uid), 16)   # (C2 has a mask and mixes: C1 and C2 become one layer)
check(shape(fpm) == "Base F[C1 C3] Top" and LY.below_sibling(named(fpm, "C3")).name == "C1", "Merge Down inside a folder: %s" % shape(fpm))
for ch_id in CHANS2:
    err = float(np.abs(LY.composite(fpm, ch_id, N) - live_comp[ch_id]).max())
    check(err < 0.02, "...the look stays (%s, %.5f)" % (ch_id, err))
check(chain_names(fpm, 'ROUGHNESS') == expected_nodes(LY.kids_of(fpm), 'ROUGHNESS'), "chains after Merge Down inside a folder")
# Flatten with a folder
LY.flatten_all(fpm, 16)
check(shape(fpm) == "Base" and not [l for l in fpm.m3d_layers if l.kind == 'FOLDER'], "Flatten with a folder: %s" % shape(fpm))

# --- Frozen layers cannot be edited; strokes go to the scratch image; operators are off (cube, in Texture Paint Mode)
fz_ob, fz_mat = fresh_cube("Frozen", '64')
for name in ("A", "B", "C"):
    bpy.ops.m3d.layer_add(kind='PAINT')
    LY.active_layer(fz_mat).name = name
    rand_image(LY.entry_of(LY.active_layer(fz_mat), 'BASE_COLOR').image, opaque=name == "A")
check(bpy.ops.m3d.layer_folder_add() == {'FINISHED'}, "a folder for the freeze test")
for name in ("B", "C"):
    select(fz_mat, name)
    check(bpy.ops.m3d.layer_move_into(folder=named(fz_mat, "Folder").uid) == {'FINISHED'}, "move %s in" % name)
check(shape(fz_mat) == "A Folder[B C]", "the freeze test stack: %s" % shape(fz_mat))
live_fz = LY.composite(fz_mat, 'BASE_COLOR', 64)
pixels_fz = {i.name: read(i).copy() for i in LY.stack_images(fz_mat)}
count_fz = len(fz_mat.node_tree.nodes)
select(fz_mat, "Folder")
check(bpy.ops.m3d.layer_freeze.poll() and bpy.ops.m3d.layer_freeze() == {'FINISHED'} and named(fz_mat, "Folder").frozen, "Freeze Folder operator")
fz_folder = named(fz_mat, "Folder")
check(np.abs(LY.composite(fz_mat, 'BASE_COLOR', 64) - live_fz).max() < FREEZE_TOL and len(fz_mat.node_tree.nodes) < count_fz,
      "the look is the same and the nodes are fewer (%d -> %d)" % (count_fz, len(fz_mat.node_tree.nodes)))
check(all(np.array_equal(read(bpy.data.images[n]), px_) for n, px_ in pixels_fz.items()), "freezing changed no layer image")
check(bpy.ops.m3d.layer_unfreeze.poll() and not named(fz_mat, "B").frozen and LY.in_frozen(named(fz_mat, "B")), "B is in a frozen folder")
select(fz_mat, "B")
for idname in ("layer_remove", "layer_duplicate", "layer_move", "layer_visible", "layer_mask_add", "layer_merge_down", "layer_move_out",
               "layer_paint_mask", "layer_flatten", "mask_effect_add"):
    check(not getattr(bpy.ops.m3d, idname).poll(), "%s is off for a layer in a frozen folder" % idname)
check(bpy.ops.m3d.tex_channel(channel='BASE_COLOR') == {'CANCELLED'}, "choosing a channel to paint on a frozen layer is refused")
target = fz_mat.texture_paint_images[fz_mat.paint_active_slot]
check(target.name == LY.SCRATCH and target not in LY.stack_images(fz_mat), "the brush is aimed at the scratch image, not at a frozen layer (%s)" % target.name)
check(LY.target_image(bpy.context, fz_mat, True) is None, "a frozen layer has no paint target")
fz_folder.visible = False
check(fz_mat.node_tree.nodes[LY.part('BASE_COLOR', fz_folder.uid, "opv")].inputs[1].default_value == 0.0, "a frozen folder can still be hidden")
fz_folder.visible = True
fz_folder.opacity, fz_folder.blend = 0.4, 'MULTIPLY'
check(fz_mat.node_tree.nodes[LY.part('BASE_COLOR', fz_folder.uid, "mix")].blend_type == 'MULTIPLY'
      and abs(fz_mat.node_tree.nodes[LY.part('BASE_COLOR', fz_folder.uid, "opv")].inputs[1].default_value - 0.4) < 1e-6,
      "...and have its own blend mode and opacity")
select(fz_mat, "Folder")
check(not bpy.ops.m3d.layer_freeze.poll() or bpy.ops.m3d.layer_freeze() == {'CANCELLED'}, "a frozen folder cannot be frozen again")
check(bpy.ops.m3d.layer_remove.poll() and bpy.ops.m3d.layer_mask_add.poll() and bpy.ops.m3d.layer_duplicate.poll(), "...but the folder itself can be edited, masked and copied")
# a frozen layer is also found when something in the list is active: the list row and the panel
ctx_fz = TCtx()
select(fz_mat, "C")
for cls in (T.PROPERTIES_PT_m3d_tx_stack, T.PROPERTIES_PT_m3d_tx_layer):
    log = draw_stub(cls, ctx_fz)
    check_calls("%s with a layer in a frozen folder" % cls.__name__, log)
    if cls is T.PROPERTIES_PT_m3d_tx_layer:
        check(any(r._kind == "operator" and r._args[0] == "m3d.layer_unfreeze" for r in log), "the Layer panel of a frozen layer offers Unfreeze")
log = []
LY.M3D_UL_layers.draw_item(None, ctx_fz, Rec(log), None, named(fz_mat, "C"), 0, None, "", 2)
check_calls("list row of a layer in a frozen folder", log)
check([r for r in log if r._kind == "row"][0].values().get("enabled") is False, "the list row of a frozen layer is off")
select(fz_mat, "Folder")
check(bpy.ops.m3d.layer_unfreeze() == {'FINISHED'} and not named(fz_mat, "Folder").frozen and not LY.in_frozen(named(fz_mat, "B")), "Unfreeze Folder operator")
select(fz_mat, "B")
check(bpy.ops.m3d.layer_remove.poll() and slot_image(fz_mat) == LY.entry_of(named(fz_mat, "B"), 'BASE_COLOR').image, "after Unfreeze a layer is editable and paintable again")
# Freeze from a layer inside, and Unfreeze from a layer inside
check(bpy.ops.m3d.layer_freeze() == {'FINISHED'} and named(fz_mat, "Folder").frozen and LY.active_layer(fz_mat).name == "Folder",
      "Freeze with a layer of the folder active freezes its folder and selects it")
select(fz_mat, "B")
check(bpy.ops.m3d.layer_unfreeze() == {'FINISHED'} and not named(fz_mat, "Folder").frozen, "Unfreeze with a frozen layer active unfreezes its folder")

# --- Saving: a frozen folder, its images (packed by the save handler) and the nodes come back as they were
named(fo_mat, "Folder 2").expanded = False
shape_fo, state_fo = shape(fo_mat), material_state(fo_mat)
expected_fo = [(l.name, l.expanded) for l in fo_mat.m3d_layers if l.kind == 'FOLDER']
bpy.ops.m3d.layer_freeze(index=LY.index_of(fz_mat, named(fz_mat, "Folder").uid))
frozen_names = [e.image.name for e in named(fz_mat, "Folder").channels if e.image]
frozen_px = {n: read(bpy.data.images[n]).copy() for n in frozen_names}
check(len(frozen_names) == 1 and all(bpy.data.images[n] in T.modified_images() for n in frozen_names), "frozen images count as modified")
state_fz = material_state(fz_mat)
fz_path = os.path.join(tempfile.mkdtemp(prefix="m3d_fold_save_"), "fold.blend")
bpy.ops.wm.save_as_mainfile(filepath=fz_path)
check(all(bpy.data.images[n].packed_file is not None for n in frozen_names), "saving packed the frozen images")
bpy.ops.wm.open_mainfile(filepath=fz_path)
tex_ws = bpy.data.workspaces["Texture"]
rz = bpy.data.materials["Frozen_Material"]
check(shape(rz) == "A Folder[B C]" and named(rz, "Folder").frozen and well_formed(rz) and [l.name for l in rz.m3d_layers] == ["A", "B", "C", "Folder"],
      "the folders and the frozen state come back from the file: %s" % shape(rz))
check(all(np.abs(read(bpy.data.images[n]) - frozen_px[n]).max() < 1e-6 for n in frozen_names), "...with the frozen pixels")
check(bpy.data.images[frozen_names[0]].colorspace_settings.name == 'sRGB' and material_state(rz) == state_fz, "...and the same nodes and links")
check(LY.rebuild_all(rz) is False, "a rebuild after loading changes nothing")
rf = bpy.data.materials["Fold_Material"]
check(shape(rf) == shape_fo and well_formed(rf) and material_state(rf) == state_fo and LY.rebuild_all(rf) is False
      and [(l.name, l.expanded) for l in rf.m3d_layers if l.kind == 'FOLDER'] == expected_fo,
      "a live folder, and whether it is open, come back from the file too: %s" % shape(rf))
check(chain_names(rz, 'BASE_COLOR') == expected_nodes(LY.kids_of(rz), 'BASE_COLOR'), "the chain after loading is the expected one")
LY.unfreeze_folder(rz, LY.index_of(rz, named(rz, "Folder").uid))
check(not [i for i in bpy.data.images if i.name.endswith("Frozen")] and not named(rz, "Folder").frozen, "...and Unfreeze after loading removes the frozen images")

# ----------------------------------------------------------------------------------------------------
# Phase 7c: the Library (starter materials and mask presets, your own items, thumbnails, alphas, the tab).
import json
import shutil
import m3d_library as LIB
import m3d_library_data as LD

check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in LIB.classes if not issubclass(c, bpy.types.PropertyGroup)),
      "Library classes registered")
check(hasattr(bpy.types.Scene, "m3d_library") and {"category", "search", "mask_mode"} <= set(LIB.M3D_LibrarySettings.bl_rna.properties.keys())
      and {i.identifier for i in LIB.M3D_LibrarySettings.bl_rna.properties["category"].enum_items} == {'MATERIALS', 'MASKS', 'BRUSHES', 'ALPHAS', 'MINE'},
      "Scene library settings and the five categories")
check(LIB.library_dir().startswith(TEST_CONFIG) and LIB.library_dir().replace("\\", "/").endswith("datafiles/m3d_library"),
      "the library is in the user data folder: %s" % LIB.library_dir())
check('UNDO' in LIB.M3D_OT_library_apply.bl_options, "applying an item is an undo step")
LIB._gen.update(running=False, done=False, stage=None)   # (the page panels drawn earlier started the timer)
if bpy.app.timers.is_registered(LIB._tick):
    bpy.app.timers.unregister(LIB._tick)

# --- The starter items are plain data: names, values and structure
lb_mats = {e.item["name"]: e for e in LIB.STARTERS if e.item["type"] == 'MATERIAL'}
lb_masks = {e.item["name"]: e for e in LIB.STARTERS if e.item["type"] == 'MASK'}
check({"Painted Metal", "Rusty Iron", "Brushed Steel", "Chrome", "Gold", "Copper", "Rubber", "Plastic", "Dirty Plastic", "Concrete", "Dusty",
       "Snow Cover", "Mud"} <= set(lb_mats), "the starter materials: %s" % sorted(lb_mats))
check({"Edge Wear", "Dirt in Cavities", "Top-down Dust", "Noise Breakup", "Thickness Glow"} <= set(lb_masks) and len(lb_masks) >= 5,
      "the starter mask presets: %s" % sorted(lb_masks))
check(len({e.ref for e in LIB.STARTERS}) == len(LIB.STARTERS) and all(e.directory is None for e in LIB.STARTERS), "starter ids are unique, they need no folder")
check(all(json.loads(json.dumps(e.item)) == e.item and e.item["format"] == 1 and e.item.get("description") for e in LIB.STARTERS), "starter items are JSON with a description")
banned = re.compile(r"substance|smart ?material|smart ?mask|adobe|painter|megascans|quixel", re.I)
check(not banned.search(json.dumps([e.item for e in LIB.STARTERS])) and not banned.search(open(LIB.__file__).read() + open(LD.__file__).read()),
      "neutral names only")
KIND_SET = {'PAINT', 'FILL', 'FOLDER'}


def lib_valid_effect(spec):
    ok = spec["kind"] in MK.KIND_BY_ID and set(spec) <= {"kind", "name", "visible", "opacity", "blend", "image"} | set(MK.PARAM_PROPS)
    ok = ok and spec.get("blend", 'MIX') in dict(MK.BLENDS) and 0 <= spec.get("opacity", 1.0) <= 1
    for key in set(spec) & set(MK.PARAM_PROPS):
        prop = MK.M3D_MaskEffect.bl_rna.properties[key]
        if prop.type in {'FLOAT', 'INT'} and not prop.is_array:
            ok = ok and prop.hard_min <= spec[key] <= prop.hard_max
        if prop.type == 'ENUM':
            ok = ok and spec[key] in {i.identifier for i in prop.enum_items}
    return ok


def lib_valid_layer(spec):
    ok = spec["kind"] in KIND_SET and set(spec) <= {"name", "kind", "visible", "opacity", "blend", "use_alpha", "channels", "layers", "mask"}
    ok = ok and spec.get("blend", 'MIX') in dict(LY.BLENDS) and all(lib_valid_effect(e) for e in spec.get("mask", ()))
    for ch, value in spec.get("channels", {}).items():
        ok = ok and ch in LY.CHANNEL_BY_ID and (value is None or isinstance(value, str) or (isinstance(value, list) and len(value) == 4
                                                                                             and all(0 <= c <= 1 for c in value))
                                                or (isinstance(value, float) and 0 <= value <= 1))
    return ok and all(lib_valid_layer(k) for k in spec.get("layers", ()))


check(all(lib_valid_layer(e.item["layer"]) and e.item["layer"]["kind"] == 'FOLDER' for e in lb_mats.values()), "starter materials are folders of valid layers")
check('"image' not in json.dumps([e.item for e in LIB.STARTERS]) and all(isinstance(v, (float, list)) or v is None for e in lb_mats.values()
      for k in e.item["layer"]["layers"] for v in k["channels"].values()), "...made of fills and mask generators, no image files")
check(all(all(lib_valid_effect(x) for x in e.item["mask"]) and e.item["mask"] for e in lb_masks.values()), "starter mask presets hold valid effects")
first = lambda name: lb_mats[name].item["layer"]["layers"][0]["channels"]
check(all(first(n)["METALLIC"] == 1.0 for n in ("Chrome", "Gold", "Copper", "Brushed Steel", "Aluminium"))
      and all(first(n)["METALLIC"] == 0.0 for n in ("Rubber", "Plastic", "Matte Black", "Ceramic", "Concrete"))
      and first("Chrome")["ROUGHNESS"] < 0.1 and first("Plastic")["ROUGHNESS"] < 0.25 and first("Rubber")["ROUGHNESS"] > 0.7
      and first("Concrete")["ROUGHNESS"] > 0.8 and min(first("Gold")["BASE_COLOR"][:3]) < 0.4 < first("Gold")["BASE_COLOR"][0],
      "plausible PBR values: metals metallic, plastics glossy, rubber and concrete rough, gold tinted")
check(sum(1 for e in lb_mats.values() for k in e.item["layer"]["layers"] if k.get("mask")) >= 8
      and all(any(x["kind"] in {'EDGES', 'CAVITY', 'TOPDOWN'} for k in lb_mats[n].item["layer"]["layers"] for x in k.get("mask", ()))
              for n in ("Painted Metal", "Copper", "Dusty", "Snow Cover", "Mud", "Dirty Plastic"))
      and any(x["kind"] == 'NOISE' for k in lb_mats["Concrete"].item["layer"]["layers"] for x in k.get("mask", ())),
      "the generators drive the masks: edges, cavities, top-down, noise")

# --- Apply every starter material on a cube: a folder named after the item with its layers, masks and values, one rebuild
lb_ob, lb_mat = fresh_cube("Lib", '64')
lb_ob.m3d_bake.resolution, lb_ob.m3d_bake.samples, lb_ob.m3d_bake.margin = '128', 4, 4
lb_counts = {"rebuild": 0, "bake": 0}
_rebuild_all, _bake_maps = LY.rebuild_all, T.bake_maps


def _counting_rebuild(m):
    lb_counts["rebuild"] += 1
    return _rebuild_all(m)


def _counting_bake(*args, **kw):
    lb_counts["bake"] += 1
    return _bake_maps(*args, **kw)


LY.rebuild_all, T.bake_maps = _counting_rebuild, _counting_bake


def lib_shape(layer, name=None):
    return (name or layer.name, layer.kind, tuple(e.kind for e in layer.mask_stack), tuple(lib_shape(k) for k in LY.children(layer)))


def lib_spec_shape(spec, name=None):
    return (name or spec["name"], spec["kind"], tuple(e["kind"] for e in spec.get("mask", ())), tuple(lib_spec_shape(k) for k in spec.get("layers", ())))


def lib_values_ok(layer, spec):
    """The fill values and the enabled channels of a layer are the item's; so are blend, opacity and the effect settings."""
    ok = layer.blend == spec.get("blend", 'MIX') and abs(layer.opacity - spec.get("opacity", 1.0)) < 1e-6 and layer.visible == spec.get("visible", True)
    for ch in LY.CHANNELS if layer.kind != 'FOLDER' else ():
        e, value = LY.entry_of(layer, ch.id), spec.get("channels", {}).get(ch.id, "absent")
        ok = ok and e.use == (value != "absent")
        if layer.kind == 'FILL' and isinstance(value, float):
            ok = ok and abs(e.value - value) < 1e-6
        if layer.kind == 'FILL' and isinstance(value, list):
            ok = ok and all(abs(a - b) < 1e-6 for a, b in zip(e.color, value))
    for e, x in zip(layer.mask_stack, spec.get("mask", ())):
        ok = ok and e.name == x.get("name", MK.KIND_BY_ID[x["kind"]].label) and abs(e.opacity - x.get("opacity", 1.0)) < 1e-6
        for key in set(x) & set(MK.PARAM_PROPS):
            v = getattr(e, key)
            ok = ok and (v == x[key] if isinstance(v, (str, bool)) else all(abs(a - b) < 1e-6 for a, b in zip(v, x[key]))
                         if isinstance(x[key], list) else abs(v - x[key]) < 1e-6)
    return ok and all(lib_values_ok(k, s) for k, s in zip(LY.children(layer), spec.get("layers", ())))


lb_times = []
for entry in lb_mats.values():
    spec, name = entry.item["layer"], entry.item["name"]
    layers_before, look_before = len(lb_mat.m3d_layers), LY.composite(lb_mat, 'BASE_COLOR', 64).copy()
    lb_counts.update(rebuild=0, bake=0)
    t0 = time.time()
    res = bpy.ops.m3d.library_apply(item=entry.ref)
    lb_times.append(time.time() - t0)
    folder = LY.active_layer(lb_mat)
    check(res == {'FINISHED'} and folder is not None and folder.name == name and folder.parent == "" and lb_mat.m3d_layers[-1].uid == folder.uid,
          "%s: a folder named after the item on top of the stack" % name)
    check(lib_shape(folder) == lib_spec_shape(spec, name) and lib_values_ok(folder, spec), "%s: the folder holds the item's layers, values, masks and effects" % name)
    check(len(lb_mat.m3d_layers) == layers_before + 1 + len(LY.descendants(folder)) and well_formed(lb_mat), "%s: a well formed stack" % name)
    check(lb_counts["rebuild"] == 1 and lb_counts["bake"] <= 1, "%s: one rebuild and at most one bake (%s)" % (name, lb_counts))
    check(_rebuild_all(lb_mat) is False, "%s: the nodes are in step with the layers" % name)
    check(np.abs(LY.composite(lb_mat, 'BASE_COLOR', 64) - look_before).max() > 1e-3, "%s changes the look" % name)
    check(all(not MK.missing_maps(l) for l in lb_mat.m3d_layers), "%s: the generators have their maps" % name)
check(max(lb_times) < 10.0, "applying is quick (%.2f s at most)" % max(lb_times))
print("library: %d starter materials applied, the first (bakes the maps) %.2f s, the others %.2f s at most" % (len(lb_times), lb_times[0], max(lb_times[1:])))
lb_counts.update(rebuild=0, bake=0)
check(bpy.ops.m3d.library_apply(item="starter:painted_metal") == {'FINISHED'} and LY.active_layer(lb_mat).name == "Painted Metal 2"
      and lb_counts["bake"] == 0 and lb_counts["rebuild"] == 1, "applying twice: a second folder, the maps are not baked again (%s)" % lb_counts)
check(bpy.ops.m3d.library_apply(item="starter:chrome") == {'FINISHED'} and np.abs(LY.composite(lb_mat, 'ROUGHNESS', 16) - 0.02).max() < 1e-3
      and np.abs(LY.composite(lb_mat, 'METALLIC', 16) - 1.0).max() < 1e-3, "Chrome sets roughness 0.02 and metallic 1 over everything below")
lb_ob2, lb_mat2 = fresh_cube("NoUV", '64')
lb_ob2.data.uv_layers.remove(lb_ob2.data.uv_layers[0])
check(bpy.ops.m3d.library_apply(item="starter:rusty_iron") == {'CANCELLED'} and not lb_mat2.m3d_layers, "a generator material on a mesh without UVs is refused and leaves the stack alone")
check(bpy.ops.m3d.library_apply(item="starter:gold") == {'FINISHED'}, "a material without generators needs no UVs")
lb_ob, lb_mat = fresh_cube("Lib", '64')
lb_ob.m3d_bake.resolution, lb_ob.m3d_bake.samples, lb_ob.m3d_bake.margin = '128', 4, 4
for entry in lb_mats.values():
    bpy.ops.m3d.library_apply(item=entry.ref)   # (maps for the cube)

# --- Mask presets: replace or add on top
bpy.ops.m3d.layer_add(kind='FILL')
lb_fill = LY.active_layer(lb_mat)
lb_fill.name = "Target"
for entry in lb_masks.values():
    lb_counts.update(rebuild=0, bake=0)
    res = bpy.ops.m3d.library_apply(item=entry.ref, mode='REPLACE')
    layer = named(lb_mat, "Target")
    check(res == {'FINISHED'} and [e.kind for e in layer.mask_stack] == [x["kind"] for x in entry.item["mask"]] and lib_values_ok(layer, {"mask": entry.item["mask"], "channels": {"BASE_COLOR": None}}),
          "%s replaces the mask with its effects" % entry.item["name"])
    check(layer.mask_stack[0].blend == 'MIX' and layer.mask_index == len(layer.mask_stack) - 1 and lb_counts["rebuild"] == 1 and lb_counts["bake"] <= 1,
          "%s: the first effect sets the mask, one rebuild (%s)" % (entry.item["name"], lb_counts))
    mask = MK.stack_value(layer, 32)
    check(np.isfinite(mask).all() and mask.min() >= 0 and mask.max() <= 1, "%s is a mask" % entry.item["name"])
    check(all(not MK.missing_maps(l) for l in lb_mat.m3d_layers) and _rebuild_all(lb_mat) is False, "%s: maps and nodes are there" % entry.item["name"])
layer = named(lb_mat, "Target")
LY.add_effect(layer, 'PAINT', "Hand")
layer.mask_stack[len(layer.mask_stack) - 1].image = LY.make_mask_image(lb_mat, layer, 16, True)
hand_image = layer.mask_stack[len(layer.mask_stack) - 1].image.name
LY.rebuild_all(lb_mat)
paint_count = len(layer.mask_stack)
check(bpy.ops.m3d.library_apply(item="starter:edge_wear", mode='REPLACE') == {'FINISHED'} and [e.kind for e in layer.mask_stack] == ["EDGES", "NOISE"]
      and [e.name for e in layer.mask_stack] == ["Edges", "Breakup"] and hand_image not in bpy.data.images,
      "Replace removes the old effects, their names are free again and a painted mask's image goes")
check(bpy.ops.m3d.library_apply(item="starter:dirt_in_cavities", mode='ADD') == {'FINISHED'}
      and [e.kind for e in layer.mask_stack] == ["EDGES", "NOISE", "CAVITY", "NOISE"] and [e.name for e in layer.mask_stack] == ["Edges", "Breakup", "Cavity", "Breakup 2"]
      and layer.mask_stack[2].blend == 'MULTIPLY' and layer.mask_index == 3, "Add on Top puts the effects above the mask, combined with it, with free names")
both = MK.stack_value(layer, 32)
only = MK.stack_value(layer, 32, upto=2)
check(np.all(both <= only + 1e-6), "...so the mask can only lose coverage")
bpy.ops.m3d.layer_mask_remove()
check(bpy.ops.m3d.library_apply(item="starter:noise_breakup", mode='ADD') == {'FINISHED'} and layer.mask_stack[0].blend == 'MIX' and len(layer.mask_stack) == 1,
      "Add on Top without a mask is the same as Replace")
check(bpy.ops.m3d.library_apply(item="starter:noise_breakup", mode='REPLACE') == {'FINISHED'} and len(layer.mask_stack) == 1, "Replace with the same preset keeps one effect")
LY.freeze_folder(lb_mat, LY.index_of(lb_mat, named(lb_mat, "Chrome").uid), 32)
select(lb_mat, "Chrome")
check(LY.in_frozen(LY.active_layer(lb_mat)) is False and bpy.ops.m3d.library_apply(item="starter:speckle", mode='ADD') == {'FINISHED'}, "a frozen folder itself can be masked")
lb_mat.m3d_layer_index = LY.index_of(lb_mat, LY.descendants(named(lb_mat, "Chrome"))[0].uid)
check(bpy.ops.m3d.library_apply(item="starter:speckle") == {'CANCELLED'}, "a layer inside a frozen folder is refused")
LY.unfreeze_folder(lb_mat, LY.index_of(lb_mat, named(lb_mat, "Chrome").uid))
check(bpy.ops.m3d.library_apply(item="starter:nothing") == {'CANCELLED'} and bpy.ops.m3d.library_apply(item="user:nothing") == {'CANCELLED'}, "an item that is not there is refused")
LY.rebuild_all, T.bake_maps = _rebuild_all, _bake_maps
lb_ob2, lb_mat2 = fresh_cube("NoLayers", '64')
check(bpy.ops.m3d.library_apply(item="starter:edge_wear") == {'CANCELLED'} and not lb_mat2.m3d_layers, "a mask preset needs a layer")
lb_ob2.data.materials.clear()
check(bpy.ops.m3d.library_apply(item="starter:gold") == {'FINISHED'} and lb_ob2.active_material is not None
      and [l.name for l in lb_ob2.active_material.m3d_layers] == ["Surface", "Gold"], "a mesh without a material gets one")

# --- Save your own: a paint layer, fills, masks (paint, generators, filters) in nested folders; delete it, apply it back: the same pixels
rt_ob, rt_mat = fresh_cube("RT", '64')
rt_ob.m3d_bake.resolution, rt_ob.m3d_bake.samples, rt_ob.m3d_bake.margin = '128', 4, 4
bpy.ops.m3d.layer_add(kind='PAINT')
rt_rock = LY.active_layer(rt_mat)
rt_rock.name = "Rock"
for ch_id in ('BASE_COLOR', 'ROUGHNESS'):
    bpy.ops.m3d.tex_channel(channel=ch_id)
    rand_image(LY.entry_of(rt_rock, ch_id).image, opaque=True)
bpy.ops.m3d.layer_folder_add()
LY.active_layer(rt_mat).name = "Outer"
for kind, name in (('FILL', "Tint"), ('PAINT', "Brush"), ('FILL', "Gold")):
    bpy.ops.m3d.layer_add(kind=kind)
    LY.active_layer(rt_mat).name = name
bpy.ops.m3d.layer_folder_add()
LY.active_layer(rt_mat).name = "Inner"
LY.move_into(rt_mat, named(rt_mat, "Inner"), named(rt_mat, "Outer"))
LY.move_into(rt_mat, named(rt_mat, "Tint"), named(rt_mat, "Inner"))
LY.move_into(rt_mat, named(rt_mat, "Brush"), named(rt_mat, "Inner"))
LY.move_into(rt_mat, named(rt_mat, "Gold"), named(rt_mat, "Outer"))
check(shape(rt_mat) == "Rock Outer[Inner[Tint Brush] Gold]" and well_formed(rt_mat), "the stack to save: %s" % shape(rt_mat))
select(rt_mat, "Brush")
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
rand_image(LY.entry_of(named(rt_mat, "Brush"), 'BASE_COLOR').image)
tint, gold, outer, inner = (named(rt_mat, n) for n in ("Tint", "Gold", "Outer", "Inner"))
with LY.muted():
    LY.entry_of(tint, 'BASE_COLOR').color = (0.1, 0.4, 0.7, 1.0)
    LY.entry_of(tint, 'ROUGHNESS').use = True
    LY.entry_of(tint, 'ROUGHNESS').value = 0.37
    tint.blend, tint.opacity = 'MULTIPLY', 0.7
    for ch_id, value in (('BASE_COLOR', (1.0, 0.77, 0.34, 1.0)), ('ROUGHNESS', 0.21), ('METALLIC', 1.0)):
        LY.entry_of(gold, ch_id).use = True
        if ch_id == 'BASE_COLOR':
            LY.entry_of(gold, ch_id).color = value
        else:
            LY.entry_of(gold, ch_id).value = value
    gold.blend, gold.opacity = 'OVERLAY', 0.8
    outer.blend, outer.opacity, inner.opacity, inner.visible = 'SOFT_LIGHT', 0.9, 0.6, True
LY.rebuild_all(rt_mat)
select(rt_mat, "Tint")
bpy.ops.m3d.mask_effect_add(kind='PAINT', fill='WHITE')
LY.write_pixels(tint.mask_stack[0].image, np.dstack([fold_rng.random((64, 64, 3)), np.ones((64, 64, 1))]).astype(np.float32))
for kind in ('EDGES', 'NOISE', 'LEVELS', 'INVERT'):
    bpy.ops.m3d.mask_effect_add(kind=kind)
with LY.muted():
    for e, settings in zip(tint.mask_stack, ({}, dict(amount=0.37, invert=True, blend='LIGHTEN'), dict(scale=7.5, seed=3, detail=2.5, opacity=0.8),
                                             dict(gamma=1.7, black_in=0.2), dict(opacity=0.6))):
        for key, value in settings.items():
            setattr(e, key, value)
    tint.mask_stack[0].name = "Hand mask"
LY.rebuild_all(rt_mat)
select(rt_mat, "Outer")
bpy.ops.m3d.layer_mask_add(fill='BLACK')
LY.write_pixels(outer.mask_stack[0].image, np.dstack([fold_rng.random((64, 64, 3)) * 0.8 + 0.2, np.ones((64, 64, 1))]).astype(np.float32))


def rt_look():
    return [LY.composite(rt_mat, c, 64).copy() for c in ('BASE_COLOR', 'ROUGHNESS', 'METALLIC')]


def rt_effects(layer):
    return [(e.name, e.kind, e.visible, e.opacity, e.blend, round(e.amount, 6), e.invert, round(e.scale, 6), e.seed, e.space, round(e.gamma, 6),
             round(e.black_in, 6), read(e.image).copy() if e.kind == 'PAINT' else None) for e in layer.mask_stack]


def same_effects(a, b):
    return len(a) == len(b) and all(x[:-1] == y[:-1] and (x[-1] is None) == (y[-1] is None) and (x[-1] is None or np.array_equal(x[-1], y[-1])) for x, y in zip(a, b))


rt_before, rt_tint_fx, rt_tint_mask, rt_outer_fx = rt_look(), rt_effects(tint), MK.stack_value(tint, 64).copy(), rt_effects(outer)
rt_shape, rt_layers = shape(rt_mat), len(rt_mat.m3d_layers)
rt_brush_px = read(LY.entry_of(named(rt_mat, "Brush"), 'BASE_COLOR').image).copy()
check(bpy.ops.m3d.library_save(kind='MATERIAL', name="Outer") == {'FINISHED'}, "Save to Library: the active folder")
rt_entry = next(e for e in LIB.user_entries() if e.item["name"] == "Outer")
rt_files = sorted(os.listdir(rt_entry.directory))
check(rt_entry.ref == "user:outer" and rt_files == ["image1.png", "image2.png", "image3.png", "image4.png", "item.json"],
      "the item is a folder of its JSON and its paint images (two of the Brush layer, two masks): %s" % rt_files)
check(rt_entry.item["type"] == 'MATERIAL' and rt_entry.item["layer"]["kind"] == 'FOLDER' and lib_valid_layer(rt_entry.item["layer"])
      and lib_spec_shape(rt_entry.item["layer"]) == lib_spec_shape({"name": "Outer", "kind": 'FOLDER', "layers": [
          {"name": "Inner", "kind": 'FOLDER', "layers": [{"name": "Tint", "kind": 'FILL', "mask": [{"kind": k} for k in ("PAINT", "EDGES", "NOISE", "LEVELS", "INVERT")]},
                                                       {"name": "Brush", "kind": 'PAINT'}]}, {"name": "Gold", "kind": 'FILL'}], "mask": [{"kind": 'PAINT'}]}),
      "the item describes the folder, its nested folder, layers and masks")
check(json.load(open(os.path.join(rt_entry.directory, "item.json"))) == rt_entry.item, "item.json is what the library reads")
check(shape(rt_mat) == rt_shape and rt_look()[0].tobytes() == rt_before[0].tobytes(), "saving changes nothing in the stack")
select(rt_mat, "Outer")
bpy.ops.m3d.layer_remove()
check(shape(rt_mat) == "Rock" and np.abs(rt_look()[0] - rt_before[0]).max() > 1e-3, "the folder is gone from the scene")
check(bpy.ops.m3d.library_apply(item=rt_entry.ref) == {'FINISHED'}, "...and applied back")
check(shape(rt_mat) == rt_shape and well_formed(rt_mat) and len(rt_mat.m3d_layers) == rt_layers, "the same layers: %s" % shape(rt_mat))
rt_after = rt_look()
check(LIB.describe_material("Outer", named(rt_mat, "Outer"), LIB.Files()) == rt_entry.item, "describing the applied folder gives the saved item again")
check(all(np.abs(a - b).max() < 1e-6 for a, b in zip(rt_before, rt_after)), "the same composite in Base Color, Roughness and Metallic (differences %s)"
      % [float(np.abs(a - b).max()) for a, b in zip(rt_before, rt_after)])
tint2, outer2 = named(rt_mat, "Tint"), named(rt_mat, "Outer")
check(same_effects(rt_tint_fx, rt_effects(tint2)) and same_effects(rt_outer_fx, rt_effects(outer2)), "the mask effects, their settings and their paint images")
check(np.array_equal(rt_tint_mask, MK.stack_value(tint2, 64)), "the same mask values")
check(np.array_equal(rt_brush_px, read(LY.entry_of(named(rt_mat, "Brush"), 'BASE_COLOR').image)), "the paint layer's pixels")
check((outer2.blend, round(outer2.opacity, 5), tint2.blend, round(tint2.opacity, 5), round(named(rt_mat, "Inner").opacity, 5)) == ('SOFT_LIGHT', 0.9, 'MULTIPLY', 0.7, 0.6),
      "blend modes and opacities")
check(_rebuild_all(rt_mat) is False, "the nodes of the applied item are in step")
# a mask preset: the same
select(rt_mat, "Tint")
rt_stack = rt_effects(named(rt_mat, "Tint"))
check(bpy.ops.m3d.library_save(kind='MASK', name="My Mask") == {'FINISHED'}, "Save to Library: the active layer's mask")
rt_mask_entry = next(e for e in LIB.user_entries() if e.item["name"] == "My Mask")
check(rt_mask_entry.item["type"] == 'MASK' and [e["kind"] for e in rt_mask_entry.item["mask"]] == ["PAINT", "EDGES", "NOISE", "LEVELS", "INVERT"]
      and sorted(os.listdir(rt_mask_entry.directory)) == ["image1.png", "item.json"], "the mask preset is its effects and the paint image")
bpy.ops.m3d.layer_mask_remove()
check(bpy.ops.m3d.library_apply(item=rt_mask_entry.ref, mode='REPLACE') == {'FINISHED'}
      and same_effects(rt_stack, rt_effects(named(rt_mat, "Tint"))), "the mask preset applies back as it was")
check(bpy.ops.m3d.library_save(kind='MASK', name="") == {'CANCELLED'} and bpy.ops.m3d.library_save(kind='MASK', name="   ") == {'CANCELLED'}, "a name is needed")
select(rt_mat, "Rock")
check(bpy.ops.m3d.library_save(kind='MASK', name="Nothing") == {'CANCELLED'}, "a layer without a mask has no preset to save")
check(bpy.ops.m3d.library_save(kind='MATERIAL', name="Rock") == {'FINISHED'}
      and next(e for e in LIB.user_entries() if e.item["name"] == "Rock").item["layer"]["layers"][0]["name"] == "Rock",
      "a single layer is saved as a material of one layer in a folder")
check(bpy.ops.m3d.library_apply(item="user:rock") == {'FINISHED'} and LY.active_layer(rt_mat).name == "Rock 2"
      and [l.name for l in LY.children(LY.active_layer(rt_mat))] == ["Rock"], "...which applies as a folder named after it")

# --- Your items persist in the user folder; rename, delete; the starters are read-only
LIB._user["entries"] = None
check(sorted(e.ref for e in LIB.user_entries()) == ["user:my_mask", "user:outer", "user:rock"], "the items are read from the folder again: %s" % [e.ref for e in LIB.user_entries()])
check(next(e for e in LIB.user_entries() if e.ref == "user:outer").item == rt_entry.item, "...as saved")
select(rt_mat, "Outer")
check(bpy.ops.m3d.library_save(kind='MATERIAL', name="Outer") == {'FINISHED'} and sorted(os.listdir(os.path.join(LIB.library_dir(), "user")))
      == ["my_mask", "outer", "outer_2", "rock"], "a second item of the same name gets a folder of its own")
check(bpy.ops.m3d.library_rename(item="user:outer_2", name="Renamed") == {'FINISHED'}
      and next(e for e in LIB.user_entries() if e.ref == "user:outer_2").item["name"] == "Renamed"
      and next(e for e in LIB.user_entries() if e.ref == "user:outer_2").item["layer"]["name"] == "Renamed"
      and json.load(open(os.path.join(LIB.library_dir(), "user", "outer_2", "item.json")))["name"] == "Renamed", "rename (in the file too)")
check(bpy.ops.m3d.library_apply(item="user:outer_2") == {'FINISHED'} and LY.active_layer(rt_mat).name == "Renamed", "a renamed material applies under its new name")
check(bpy.ops.m3d.library_rename(item="user:outer_2", name="  ") == {'CANCELLED'}, "rename needs a name")
check(bpy.ops.m3d.library_delete(item="user:outer_2") == {'FINISHED'} and not os.path.exists(os.path.join(LIB.library_dir(), "user", "outer_2"))
      and "user:outer_2" not in [e.ref for e in LIB.user_entries()] and "user:outer" in [e.ref for e in LIB.user_entries()], "delete removes the folder, not the others")
for op, kw in ((bpy.ops.m3d.library_delete, {}), (bpy.ops.m3d.library_rename, {"name": "x"})):
    check(op(item="starter:chrome", **kw) == {'CANCELLED'} and "starter:chrome" in [e.ref for e in LIB.entries()], "a starter item cannot be changed with %s" % op.idname_py())
check(bpy.ops.m3d.library_delete(item="user:../../datafiles") == {'CANCELLED'} and os.path.isdir(os.path.join(LIB.library_dir(), "user", "outer")),
      "delete only reaches the library's own items")
# a damaged item does not break the library or an apply
bad = os.path.join(LIB.library_dir(), "user", "bad_layer")
os.makedirs(bad)
json.dump({"format": 1, "type": 'MATERIAL', "name": "Bad", "layer": {"name": "Bad", "kind": 'FOLDER', "layers": [{"name": "x", "kind": 'FILL', "blend": "NOPE"}]}}, open(os.path.join(bad, "item.json"), "w"))
os.makedirs(os.path.join(LIB.library_dir(), "user", "bad_json"))
open(os.path.join(LIB.library_dir(), "user", "bad_json", "item.json"), "w").write("{nope")
LIB._user["entries"] = None
check("user:bad_layer" in [e.ref for e in LIB.user_entries()] and "user:bad_json" not in [e.ref for e in LIB.user_entries()], "an item that is not valid JSON is skipped")
rt_n = len(rt_mat.m3d_layers)
check(bpy.ops.m3d.library_apply(item="user:bad_layer") == {'CANCELLED'} and len(rt_mat.m3d_layers) == rt_n and well_formed(rt_mat), "an item with a bad value is refused and leaves the stack as it was")
shutil.rmtree(os.path.join(LIB.library_dir(), "user", "bad_json"))

# --- Thumbnails: made from the item on a preview sphere (a Cycles render), cached in the user folder, the scene put back
LIB.STARTERS, lib_starters = (lb_mats["Chrome"], lb_masks["Edge Wear"]), LIB.STARTERS
LIB._user["entries"] = None
engine_before, scenes_before, objects_before = bpy.context.scene.render.engine, len(bpy.data.scenes), len(bpy.data.objects)
lib_pending = LIB.pending()
check(sorted(e.ref for e in lib_pending) == sorted(["starter:chrome", "starter:edge_wear", "user:bad_layer", "user:my_mask", "user:outer", "user:rock"]),
      "all of them wait for a thumbnail: %s" % [e.ref for e in lib_pending])
check(isinstance(LIB.thumb_icon(lb_mats["Chrome"]), int) and "ph:starter:chrome" in LIB.icons() and "t:starter:chrome:0" not in LIB.icons(), "a placeholder tile meanwhile")
check(LIB.thumb_path(lb_mats["Chrome"]).startswith(os.path.join(LIB.library_dir(), "thumbs")) and LIB.thumb_path(rt_entry) == os.path.join(rt_entry.directory, "thumb.png"),
      "starter thumbnails are cached in thumbs, yours next to the item")
t0 = time.time()
made = LIB.generate_pending()
print("thumbnails:", made, "made in %.1f s" % (time.time() - t0))
check(made == 5 and LIB._gen["failed"] == {"user:bad_layer"}, "five thumbnails made, the damaged item has none (%s, %s)" % (made, LIB._gen["failed"]))
for e in (lb_mats["Chrome"], lb_masks["Edge Wear"], rt_entry, rt_mask_entry):
    path = LIB.thumb_path(e)
    check(os.path.isfile(path), "thumbnail of %s" % e.ref)
    if os.path.isfile(path):
        im = bpy.data.images.load(path)
        px = np.empty(len(im.pixels), np.float32)
        im.pixels.foreach_get(px)
        px = px.reshape(128, 128, 4)
        check(tuple(im.size) == (128, 128) and px[64, 64, 3] > 0.9 and px[0, 0, 3] == 0 and px[..., :3].std() > 0.03, "%s: 128 x 128, a sphere on a transparent background" % e.ref)
        bpy.data.images.remove(im)
check(not [d.name for c in (bpy.data.scenes, bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.worlds, bpy.data.cameras, bpy.data.images)
           for d in c if d.name.startswith(LIB.RIG)] and len(bpy.data.scenes) == scenes_before and len(bpy.data.objects) == objects_before
      and bpy.context.scene.render.engine == engine_before, "the preview scene is gone and the scene is as it was")
lib_thumb_files = os.listdir(os.path.join(LIB.library_dir(), "thumbs"))
check(len(lib_thumb_files) == 2 and not any("_tmp" in f for f in lib_thumb_files), "two starter thumbnails in the cache, no half-written files: %s" % lib_thumb_files)
check(LIB.pending() == [] and LIB._gen["done"] and not LIB._gen["running"] and LIB.generate_pending() == 0, "cached: nothing is made twice")
LIB.thumb_icon(lb_mats["Chrome"]), LIB.thumb_icon(lb_masks["Edge Wear"])
check("t:starter:chrome:1" in LIB.icons() and "t:starter:edge_wear:1" in LIB.icons(), "the tiles show the thumbnails now")
# the timer does the same a step at a time; saving takes the preview scene away
for p in (LIB.thumb_path(lb_mats["Chrome"]), LIB.thumb_path(lb_masks["Edge Wear"])):
    os.remove(p)
LIB._gen["done"] = False
LIB.start_thumbnails()
check(LIB._gen["running"] and bpy.app.timers.is_registered(LIB._tick), "the Library draws: the timer starts")
steps_taken = 0
while steps_taken < 3:
    LIB._tick()
    steps_taken += 1
check(bpy.data.scenes.get(LIB.RIG) is not None and LIB._gen["stage"] in {'MAPS', 'JOBS'}, "the preview scene exists in between")
LIB.save_pre()
check(bpy.data.scenes.get(LIB.RIG) is None and len(bpy.data.scenes) == scenes_before, "saving takes the preview scene away")
while LIB._tick() is not None:
    steps_taken += 1
bpy.app.timers.unregister(LIB._tick)
check(steps_taken >= 5 and LIB.pending() == [] and bpy.data.scenes.get(LIB.RIG) is None and not LIB._gen["running"],
      "a step at a time (%d steps), then it is done and the scene is gone" % steps_taken)
check(bpy.ops.m3d.library_refresh() == {'FINISHED'} and len(LIB.pending()) == 6 and not LIB._gen["done"], "Refresh Previews forgets every thumbnail")
LIB.STARTERS = lib_starters
LIB._gen["failed"].clear()

# --- Alphas and brushes: the Sculpt alpha library, applied to the texture brush
S_alphas = tempfile.mkdtemp(prefix="m3d_alpha_")
S.alpha_dir = lambda create=False: S_alphas
bpy.ops.object.mode_set(mode='OBJECT')
tx_ob, tx_mat = fresh_cube("Alpha", '64')
bpy.ops.brush.asset_activate(**T.brush_props("Paint Soft"))
paint_brush = bpy.context.tool_settings.image_paint.brush
check(bpy.context.mode == 'PAINT_TEXTURE' and S.alpha_brush(bpy.context) == paint_brush and paint_brush.library is not None,
      "in Texture Paint Mode the alpha goes to the paint brush")
check(bpy.ops.m3d.alpha_pick(name="Clouds") == {'FINISHED'} and paint_brush.mask_texture is not None and paint_brush.mask_texture.name == "Clouds"
      and paint_brush.mask_texture.library is not None and paint_brush.mask_texture_slot.mask_map_mode == 'VIEW_PLANE'
      and paint_brush.mask_texture.image.size[0] == S.ALPHA_SIZE and paint_brush.texture is None,
      "a starter alpha is linked from the shared library and is the texture brush's Texture Mask (it follows the cursor)")
check(bpy.ops.m3d.alpha_pick(name="") == {'FINISHED'} and paint_brush.mask_texture is None, "None clears the alpha")
check(all(os.path.isfile(os.path.join(S_alphas, "Clouds" + ext)) for ext in (".blend", ".png")), "...from the same folder the Sculpt tab uses")
lib_png = os.path.join(S_alphas, "tex_source.png")
img = bpy.data.images.new("src", 32, 32)
img.pixels.foreach_set(np.ones(32 * 32 * 4, np.float32) * 0.6)
img.filepath_raw, img.file_format = lib_png, 'PNG'
img.save()
bpy.data.images.remove(img)
check(bpy.ops.m3d.alpha_load(filepath=lib_png) == {'FINISHED'} and paint_brush.mask_texture.name == "tex_source" and "tex_source" in S.alpha_names(),
      "Load Alpha from the Library adds it to the shared list and uses it")
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.object.mode_set(mode='SCULPT')
bpy.ops.brush.asset_activate(**S.brush_props("Draw"))
check(S.alpha_brush(bpy.context) == bpy.context.tool_settings.sculpt.brush and bpy.ops.m3d.alpha_pick(name="tex_source") == {'FINISHED'}
      and bpy.context.tool_settings.sculpt.brush.texture.name == "tex_source", "...and the Sculpt tab uses the same alpha")
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
shutil.rmtree(S_alphas, ignore_errors=True)

# --- The Library tab draws in every category, with and without the mode it needs; Save to Library buttons in the Layer and Mask panels
lctx = TCtx()
lib_s = bpy.context.scene.m3d_library
for mode in ('TEXTURE_PAINT', 'OBJECT'):
    bpy.ops.object.mode_set(mode=mode)
    for cat in ('MATERIALS', 'MASKS', 'BRUSHES', 'ALPHAS', 'MINE'):
        lib_s.category = cat
        for search in ("", "gold", "zzzz"):
            lib_s.search = search
            for cls in tex_panels("tex_library"):
                if cls.poll(lctx):
                    try:
                        log = draw_stub(cls, lctx)
                        check_calls("Library %s %s %r %s" % (cls.__name__, cat, search, mode), log)
                    except Exception as err:
                        check(False, "%s draw (%s, %r, %s): %r" % (cls.__name__, cat, search, mode, err))
lib_s.search = ""
bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
lib_s.category = 'MATERIALS'
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
tiles = [r for r in log if r._kind == "operator" and r._args[0] == "m3d.library_apply"]
check(len(tiles) == len(lb_mats) and {r.values()["item"] for r in tiles} == {e.ref for e in lb_mats.values()}
      and all("icon_value" in r._kw for r in tiles) and all(r._kw.get("text") == "" for r in tiles), "the Materials grid: a tile with a thumbnail icon per material")
check(sum(1 for r in log if r._kind == "label" and r._kw.get("text") in lb_mats) == len(lb_mats), "...with the name under each")
check(any(r._kind == "prop" and r._args[1] == "category" for r in log) and any(r._kind == "prop" and r._args[1] == "search" for r in log), "...the categories and the search field")
lib_s.search = "gold"
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
check([r.values()["item"] for r in log if r._kind == "operator" and r._args[0] == "m3d.library_apply"] == ["starter:gold"], "search filters the tiles")
lib_s.search = ""
lib_s.category = 'MASKS'
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
check(len([r for r in log if r._kind == "operator" and r._args[0] == "m3d.library_apply"]) == len(lb_masks) and any(r._kind == "prop" and r._args[1] == "mask_mode" for r in log),
      "the Masks grid and the Replace / Add on Top choice")
lib_s.mask_mode = 'ADD'
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
check({r.values()["mode"] for r in log if r._kind == "operator" and r._args[0] == "m3d.library_apply"} == {'ADD'}, "...the tiles apply the chosen way")
lib_s.mask_mode = 'REPLACE'
lib_s.category = 'BRUSHES'
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
check(len([r for r in log if r._kind == "operator" and r._args[0] == "m3d.brush_pick"]) == len(T.BRUSHES) + len(T.MORE_BRUSHES), "the Brushes grid: every texture brush")
lib_s.category = 'ALPHAS'
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
check({r.values()["name"] for r in log if r._kind == "operator" and r._args[0] == "m3d.alpha_pick"} == {"", *S.alpha_names()}
      and any(r._kind == "operator" and r._args[0] == "m3d.alpha_load" for r in log), "the Alphas grid: None, the shared alphas, Load Alpha...")
lib_s.category = 'MINE'
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_browse, lctx)
check({r.values()["item"] for r in log if r._kind == "operator" and r._args[0] == "m3d.library_apply"} == {e.ref for e in LIB.user_entries()}
      and {r.values()["kind"] for r in log if r._kind == "operator" and r._args[0] == "m3d.library_save"} == {'MATERIAL', 'MASK'}, "Mine: your items and the Save buttons")
log = draw_stub(LIB.PROPERTIES_PT_m3d_lib_manage, lctx)
check({r.values()["item"] for r in log if r._kind == "operator" and r._args[0] == "m3d.library_rename"} == {e.ref for e in LIB.user_entries()}
      and {r.values()["item"] for r in log if r._kind == "operator" and r._args[0] == "m3d.library_delete"} == {e.ref for e in LIB.user_entries()},
      "Your Items: rename and delete for each of your items, none for a starter")
lib_s.category = 'MATERIALS'
bpy.ops.m3d.library_apply(item="starter:chrome")
log = draw_stub(T.PROPERTIES_PT_m3d_tx_layer, lctx)
check(any(r._kind == "operator" and r._args[0] == "m3d.library_save" and r.values()["kind"] == 'MATERIAL' for r in log), "the Layer panel has Save to Library (for a folder)")
tx_mat.m3d_layer_index = 0
bpy.ops.m3d.library_apply(item="starter:noise_breakup")
log = draw_stub(T.PROPERTIES_PT_m3d_tx_layer, lctx)
check(any(r._kind == "operator" and r._args[0] == "m3d.library_save" and r.values()["kind"] == 'MATERIAL' for r in log), "...and for a layer")
log = draw_stub(T.PROPERTIES_PT_m3d_tx_mask, lctx)
check(any(r._kind == "operator" and r._args[0] == "m3d.library_save" and r.values()["kind"] == 'MASK' for r in log), "the Mask panel has Save to Library")
check(LIB.M3D_OT_library_apply.description(None, NS(item="starter:chrome")).startswith("Chrome: ") and LIB.M3D_OT_library_apply.description(None, NS(item="user:zzz")) == "Apply a library item"
      and all(LIB.M3D_OT_library_apply.description(None, NS(item=e.ref)) for e in LIB.STARTERS), "the tooltip names the item")
check(LIB.load_pre in bpy.app.handlers.load_pre and LIB.save_pre in bpy.app.handlers.save_pre, "library handlers are registered")

# ----------------------------------------------------------------------------------------------------
# Phase 4: Rigging workspace (tabs, pages, gates, modes, Joint tool, Orient Joint, controls, IK, skin, Driven Key, names).
import m3d_rig as R
import math
import addon_utils
from mathutils import Matrix, Vector

rig_ws = bpy.data.workspaces["Rigging"]
rig_tabs = W.DOCK_TABS['RIG']
check([t.label for t in rig_tabs['RIGHT']] == ["Skeleton", "Controls & Constraints", "Skin", "Drive", "Test", "Collections"],
      "Rigging dock tabs")
check([t.label for t in rig_tabs['LEFT']] == ["Bones"], "Rigging left tab")
for tab in (*rig_tabs['RIGHT'], *rig_tabs['LEFT']):
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("rig_"), "Rigging page tab " + tab.id)
rig_pages = {t.page for side in rig_tabs.values() for t in side}
check({c.page for c in R.classes if hasattr(c, "page")} == rig_pages, "every Rigging page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in R.classes if not issubclass(c, bpy.types.PropertyGroup)),
      "Rigging classes registered")
check(m3d_ui.shelves_for('RIG') == ['RIG_SKELETON', 'RIG_CONTROLS', 'RIG_SKIN', 'CUSTOM'] and 'RIG' in m3d_ui.STATUS_LINES, "Rigging shelf tabs and Status Line")
check([it[3] for it in m3d_ui.SHELVES['RIG_SKELETON'][1] if it][:5] == ["Joint", "Extrude", "Mirror", "Orient", "Names L/R"],
      "Skeleton shelf buttons")
check([it[3] for it in m3d_ui.SHELVES['RIG_SKIN'][1] if it] == ["Bind", "Paint Weights", "Normalize", "Mirror Weights"], "Skin shelf buttons")
check(sum(1 for it in m3d_ui.SHELVES['RIG_CONTROLS'][1] if it and not callable(it) and it[1] in {s[1] for s in R.SHAPES.values()}) == 5,
      "Controls shelf has the five shapes")
check(rig_ws.m3d_kind == 'RIG' and rig_ws.object_mode == 'OBJECT', "Rigging workspace kind and entry mode")
check('M3D_MT_rig_names' in {c.__name__ for c in R.classes}, "names pie exists")
for _, icon, _build in R.SHAPES.values():
    check(icon in icons, "shape icon " + icon)
for label, kind, icon in R.CONSTRAINTS:
    check(icon in icons, "constraint icon " + icon)
    check(op_ok("pose.constraint_add_with_targets", {"type": kind}), "constraint type " + kind)
for _l, kind in R.ROLL_PRESETS:
    check(op_ok("armature.calculate_roll", {"type": kind}), "roll preset " + kind)

# No other program's names in the Rigging code.
rig_src = open(R.__file__, encoding="utf-8").read().lower()
for word in ("maya", "autodesk", "mixamo", "accurig", "cascadeur", "houdini", "kinefx", "apex", "mgear", "advanced skeleton"):
    check(word not in rig_src, "Rigging code names " + word)

# Keys: free in the keymaps around them.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
item = find("Armature", "armature.extrude_move", 'E', ctrl=True, shift=False, alt=False)
check(item, "Ctrl+E extrudes a bone in Edit Mode")
check(not find("Armature", "wm.tool_set_by_id", 'E', ctrl=True), "Ctrl+E no longer only switches tools in Edit Mode")
check(find("Armature", "armature.parent_set", 'P', shift=False, ctrl=False), "P parents bones")
check(find("Armature", "armature.parent_clear", 'P', shift=True), "Shift+P unparents bones")
check(find("Window", "wm.read_homefile", 'N', ctrl=True), "Ctrl+N is still New Scene")
for km in ("Armature", "Pose"):
    item = find(km, "wm.call_menu_pie", 'N', shift=True, ctrl=False, alt=False)
    check(item and item[0].properties.name == "M3D_MT_rig_names" and hasattr(bpy.types, "M3D_MT_rig_names"), "Shift+N names menu in " + km)
for key, mods in (('E', dict(ctrl=True)), ('N', dict(shift=True))):
    want = {"shift": False, "ctrl": False, "alt": False, **mods}
    others = [(km.name, k.idname) for km in kc.keymaps for k in km.keymap_items
              if k.type == key and all(getattr(k, m) == v for m, v in want.items()) and not k.oskey
              and km.name in {"Window", "Screen", "Screen Editing", "Frames", "Property Editor", "3D View", "3D View Generic",
                              "Object Non-modal", "Object Mode", "Weight Paint"}]
    check(not others, "Rigging key %s %s is free around Armature / Pose: %s" % (key, mods, others))

# Menus of the Rigging set point at real things (the generic loop at the top checked every entry).
check(len(m3d_ui.MENUS["M3D_MT_skeleton"][1]) >= 10 and any(e.get("idname") == "m3d.rig_joint" for e in m3d_ui.MENUS["M3D_MT_skeleton"][1]),
      "Skeleton menu has the new tools")

# ---- Page panels: gates and drawing in every mode
for ob in list(bpy.data.objects):
    if ob.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(ob)
for mesh_ in list(bpy.data.meshes):
    bpy.data.meshes.remove(mesh_)


class RCtx(SCtx):
    """Context of a Rigging dock: the real one with this workspace."""
    def __init__(self, side='RIGHT'):
        super().__init__(side)
        self.workspace = rig_ws
        self.screen = None


def rig_panels(page):
    return [c for c in R.classes if getattr(c, "page", None) == page and hasattr(c, "poll")]


def rig_shown(page):
    side = 'LEFT' if page == "rig_bones" else 'RIGHT'
    setattr(rig_ws, "m3d_page_" + side.lower(), page)
    ctx = RCtx(side)
    return [c.__name__ for c in rig_panels(page) if c.poll(ctx)]


def rig_gated(page):
    names = rig_shown(page)
    return bool(names) and names[0].endswith("_gate")


for page in R.GATES:
    check(rig_gated("rig_" + page), "rig_%s without a skeleton shows its message first: %s" % (page, rig_shown("rig_" + page)))
check(rig_shown("rig_skeleton") == ["PROPERTIES_PT_m3d_rg_skeleton_gate", "PROPERTIES_PT_m3d_rg_create", "PROPERTIES_PT_m3d_rg_rigify"],
      "Skeleton tab without a skeleton: message, Create, Rigify: %s" % rig_shown("rig_skeleton"))
check(not any(n.endswith("_gate") for n in rig_shown("rig_drive")) and len(rig_shown("rig_drive")) >= 3, "Drive tab needs no skeleton")
check(not R.ready(bpy.context, ('RIG',)) and R.rig_of(bpy.context) is None and R.skin_mesh(bpy.context) is None, "no skeleton, no mesh")

# A cylinder and a 3 bone chain: the test rig. Bones are made through the Joint tool's own class.
bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.3, depth=2.0, location=(0, 0, 1.0), end_fill_type='NGON')
body = bpy.context.active_object
body.name = "Body"
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.subdivide(number_cuts=6)
bpy.ops.object.mode_set(mode='OBJECT')
body.data.shade_smooth()
check(R.missing(bpy.context, ('RIG', 'MESH', 'EDIT')) == ['RIG', 'EDIT'], "a mesh but no skeleton: %s" % R.missing(bpy.context, ('RIG', 'MESH', 'EDIT')))
check(R.enter_mode(bpy.context, 'POSE') == "There is no skeleton: place joints with the Joint tool first", "Pose Mode needs a skeleton")
check(bpy.ops.m3d.rig_mode(mode='POSE') == {'CANCELLED'}, "Pose button without a skeleton cancels")
check(bpy.ops.m3d.rig_mode(mode='EDIT') == {'FINISHED'} and body.mode == 'EDIT', "Edit without a skeleton edits the active mesh")
bpy.ops.object.mode_set(mode='OBJECT')
rig = R.new_armature(bpy.context, "Rig")
check(rig.show_in_front and rig.data.display_type == 'OCTAHEDRAL', "new skeleton: in front, octahedral")
check(R.enter_mode(bpy.context, 'EDIT') is None and rig.mode == 'EDIT' and bpy.context.active_object == rig, "Edit Mode makes the skeleton active")

# --- Joint tool: a chain of joints becomes connected bones
chain = R.JointChain(rig.name, "Joint")
for z in (0.1, 0.7, 1.3, 1.9):
    chain.add(Vector((0, 0, z)))
arm = rig.data
check(len(arm.edit_bones) == 3 and chain.bones == ["Joint", "Joint.001", "Joint.002"], "4 joints make 3 bones: %s" % [b.name for b in arm.edit_bones])
check(arm.edit_bones["Joint.001"].parent == arm.edit_bones["Joint"] and arm.edit_bones["Joint.001"].use_connect
      and arm.edit_bones["Joint"].parent is None, "bones are connected in a chain")
check((arm.edit_bones["Joint.002"].tail - Vector((0, 0, 1.9))).length < 1e-5 and
      (arm.edit_bones["Joint.002"].head - Vector((0, 0, 1.3))).length < 1e-5, "bone ends are the joints")
chain.remove_last()
check(len(arm.edit_bones) == 2 and len(chain.joints) == 3, "Backspace removes the last joint and bone")
chain.add(Vector((0, 0, 1.9)))
check(len(arm.edit_bones) == 3 and arm.edit_bones.active.name == "Joint.002", "...and it can be placed again")
# Continue from the tip of a bone, branch from the start of one.
side = R.JointChain(rig.name, "Branch")
side.add(Vector((0, 0, 1.9)), ("Joint.002", 'TAIL'))
side.add(Vector((0.5, 0, 2.2)))
b = arm.edit_bones["Branch"]
check(b.parent == arm.edit_bones["Joint.002"] and b.use_connect, "a chain started on a tip continues that bone")
branch = R.JointChain(rig.name, "Twig")
branch.add(Vector((0, 0, 0.7)), ("Joint.001", 'HEAD'))
branch.add(Vector((0.4, 0, 0.9)))
t = arm.edit_bones["Twig"]
check(t.parent == arm.edit_bones["Joint"] and t.use_connect, "a chain started on a bone's start branches from its parent")
side.discard()
branch.discard()
check({b.name for b in arm.edit_bones} == {"Joint", "Joint.001", "Joint.002"}, "discard removes a chain: %s" % [b.name for b in arm.edit_bones])

# X-Mirror: a chain on the +X side is named .L and gets a .R copy.
arm.use_mirror_x = True
left = R.JointChain(rig.name, "Arm")
for p in ((0.3, 0, 1.6), (0.8, 0, 1.6), (1.3, 0, 1.4)):
    left.add(Vector(p))
check(left.mirror() is None and {"Arm.L", "Arm.001.L", "Arm.R", "Arm.001.R"} <= {b.name for b in arm.edit_bones}, "X-Mirror: .L chain gets a .R copy: %s" % [b.name for b in arm.edit_bones])
check(arm.edit_bones["Arm.R"].head.x < 0 and abs(arm.edit_bones["Arm.R"].head.x + arm.edit_bones["Arm.L"].head.x) < 1e-5, "the copy is on the -X side")
center = R.JointChain(rig.name, "Mid")
center.add(Vector((-0.2, 0, 0.5)))
center.add(Vector((0.2, 0, 0.5)))
check(center.mirror() == "X-Mirror: the chain crosses the center, so it was not mirrored", "a chain across the center is not mirrored")
center.discard()
for name in ("Arm.L", "Arm.001.L", "Arm.R", "Arm.001.R"):
    arm.edit_bones.remove(arm.edit_bones[name])
arm.use_mirror_x = False

# --- Orient Joint: the chosen side axis follows a world direction, Y runs along the bone
def axes(eb):
    m = eb.matrix.to_3x3()
    return m.col[0], m.col[1], m.col[2]


n = R.orient_bones(rig, list(arm.edit_bones), '-Y', 'Z')
check(n == 3, "Orient Joint touched 3 bones")
for eb in arm.edit_bones:
    x, y, z = axes(eb)
    check((z - Vector((0, -1, 0))).length < 1e-4 and (y - (eb.tail - eb.head).normalized()).length < 1e-4 and abs(x.dot(y)) < 1e-4,
          "%s: Z axis to -Y, Y along the bone, X across: %s %s %s" % (eb.name, x, y, z))
    check(abs(x.cross(y).dot(z) - 1.0) < 1e-4, "%s: right-handed axes" % eb.name)
R.orient_bones(rig, list(arm.edit_bones), '+X', 'X')
for eb in arm.edit_bones:
    x, y, z = axes(eb)
    check((x - Vector((1, 0, 0))).length < 1e-4, "%s: X axis to +X" % eb.name)
# A bone along the direction cannot follow it: -Y is used (+Z for a bone along Y).
lone = arm.edit_bones.new("Fwd")
lone.head, lone.tail = (0.5, 0, 0), (0.5, 1, 0)
check(R.orient_bones(rig, [lone], '+Y', 'Z') == 1 and (axes(lone)[2] - Vector((0, 0, 1))).length < 1e-4, "a bone along Y falls back to +Z")
arm.edit_bones.remove(lone)
slant = arm.edit_bones.new("Slant")
slant.head, slant.tail = (1, 0, 0), (1.5, 0.5, 1.0)
R.orient_bones(rig, [slant], '+Z', 'Z')
x, y, z = axes(slant)
check(z.z > 0.5 and abs(z.dot(y)) < 1e-4, "a slanted bone: Z as close to +Z as it can be (%s)" % z)
arm.edit_bones.remove(slant)
# The operator takes the Skeleton tab's settings and every selected bone.
s = bpy.context.scene.m3d_rig
s.orient_axis, s.orient_dir = 'Z', '+Z'
for eb in arm.edit_bones:
    eb.select = True
tilted = arm.edit_bones.new("Along")
tilted.head, tilted.tail = (1, 0, 0), (2, 0, 0)
check(bpy.ops.m3d.rig_orient() == {'FINISHED'} and (axes(arm.edit_bones["Along"])[2] - Vector((0, 0, 1))).length < 1e-4,
      "Orient Joint operator: arm along X gets Z up")
arm.edit_bones.remove(arm.edit_bones["Along"])
# X-Mirror orients the partner of a selected bone to the mirrored direction.
pair = [arm.edit_bones.new("Leg.L"), arm.edit_bones.new("Leg.R")]
pair[0].head, pair[0].tail = (0.3, 0, 1), (0.3, 0, 0.2)
pair[1].head, pair[1].tail = (-0.3, 0, 1), (-0.3, 0, 0.2)
arm.use_mirror_x = True
R.orient_bones(rig, [pair[0]], '+Y', 'X')
check((axes(arm.edit_bones["Leg.L"])[0] - Vector((0, 1, 0))).length < 1e-4 and abs(arm.edit_bones["Leg.L"].roll) > 0.5
      and abs(arm.edit_bones["Leg.R"].roll + arm.edit_bones["Leg.L"].roll) < 1e-5,
      "X-Mirror: Blender gives the .R bone the mirrored roll (%s %s)" % (arm.edit_bones["Leg.L"].roll, arm.edit_bones["Leg.R"].roll))
arm.use_mirror_x = False
for name in ("Leg.L", "Leg.R"):
    arm.edit_bones.remove(arm.edit_bones[name])

# --- Naming check
names = {}
for name, head, tail in (("Hip.L", (0.2, 0, 1), (0.2, 0, 0.5)), ("Hip.R", (-0.2, 0, 1), (-0.2, 0, 0.5)),
                         ("Arm.L", (0.3, 0, 1.6), (0.8, 0, 1.6)), ("Foot.R", (0.2, 0, 0.1), (0.2, 0.3, 0.1)),
                         ("Hand", (0.9, 0, 1.6), (1.1, 0, 1.6)), ("Hand.R", (-0.9, 0, 1.6), (-1.1, 0, 1.6)),
                         ("Joint.003", (3, 0, 0), (3, 0, 1)), ("Spine", (0, 0, 0), (0, 0, 1))):
    eb = arm.edit_bones.new(name)
    eb.head, eb.tail = head, tail
    names[name] = eb.name
issues = dict((n, m) for n, m in R.name_issues(rig))
check("Arm.L" in issues and "No mirror partner" in issues["Arm.L"], "missing .R partner is found: %s" % issues)
check("Foot.R" in issues and "wrong" not in issues["Foot.R"] and "+X" in issues["Foot.R"], "a .R bone on the +X side is found: %s" % issues)
check("Hand" in issues and "no side" in issues["Hand"], "an unsided bone that mirrors a .R bone is found: %s" % issues)
check(not ({"Hip.L", "Hip.R", "Spine"} & set(issues)), "consistent names are not flagged: %s" % issues)
check(any(n == "Joint.003" and "Numbered duplicate" in m for n, m in R.name_issues(rig)), "a numbered duplicate is found")
check(R.side_of_name("Arm_L") == "L" and R.side_of_name("Arm.right") == "R" and R.side_of_name("Spine") == "" and
      R.side_of_name("Left") == "", "side_of_name")
bpy.ops.object.mode_set(mode='OBJECT')
check(bpy.ops.m3d.rig_name_check() == {'FINISHED'} and rig.data.bones["Arm.L"].name and
      rig.pose.bones["Arm.L"].select and not rig.pose.bones["Spine"].select, "Select Problem Bones selects the flagged bones")
bpy.ops.object.mode_set(mode='EDIT')
for name in names.values():
    arm.edit_bones.remove(arm.edit_bones[name])
bpy.ops.object.mode_set(mode='OBJECT')
check({n for n, _m in R.name_issues(rig)} == {"Joint.001", "Joint.002"}, "numbered default names are listed, nothing else: %s" % R.name_issues(rig))

# --- Modes and the selection each needs
check(R.ready(bpy.context, ('RIG',)) and not R.ready(bpy.context, ('MESH',)) and R.missing(bpy.context, ('EDIT', 'POSE')) == ['EDIT', 'POSE'],
      "needs with a skeleton and no mesh selected")
body.select_set(True)
bpy.context.view_layer.objects.active = body
check(R.ready(bpy.context, ('RIG', 'MESH')), "needs with a skeleton and a mesh")
bpy.context.view_layer.objects.active = rig
for page in ("rig_skeleton", "rig_controls", "rig_test"):
    check(rig_gated(page), "%s is gated in Object Mode: %s" % (page, rig_shown(page)))
check(not rig_gated("rig_skin") and not rig_gated("rig_collections") and not rig_gated("rig_bones"), "Skin, Collections and Bones need no mode")
check(bpy.ops.m3d.rig_mode(mode='POSE') == {'FINISHED'} and rig.mode == 'POSE' and bpy.context.active_object == rig, "Pose button")
check(bpy.ops.m3d.rig_mode(mode='EDIT') == {'FINISHED'} and rig.mode == 'EDIT', "Edit button from Pose Mode")
check(bpy.ops.m3d.rig_mode(mode='OBJECT') == {'FINISHED'} and rig.mode == 'OBJECT', "Object button")

# --- Bind: automatic weights on the cylinder
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
bpy.context.view_layer.objects.active = body
check(not R.is_bound(body) and R.armature_of(body) is None, "the body is not bound yet")
s.skin_method = 'AUTO'
check(bpy.ops.m3d.rig_bind() == {'FINISHED'}, "Bind with one skeleton in the scene")
check(R.is_bound(body) and R.armature_of(body) == rig and body.parent == rig, "bound: modifier and parent")
check([g.name for g in body.vertex_groups] == ["Joint", "Joint.001", "Joint.002"], "one group per bone: %s" % [g.name for g in body.vertex_groups])
check(R.unweighted(body, rig) == 0, "automatic weights reach every vertex")
low = min(body.data.vertices, key=lambda v: v.co.z)
high = max(body.data.vertices, key=lambda v: v.co.z)
w_low = {body.vertex_groups[g.group].name: g.weight for g in low.groups}
w_high = {body.vertex_groups[g.group].name: g.weight for g in high.groups}
check(max(w_low, key=w_low.get) == "Joint" and max(w_high, key=w_high.get) == "Joint.002", "weights follow the bones: %s / %s" % (w_low, w_high))
check(abs(sum(w_low.values()) - 1.0) < 0.2, "weights near the bottom add up to about 1: %s" % w_low)
check(bpy.ops.m3d.rig_unbind() == {'FINISHED'} and not R.is_bound(body) and not body.vertex_groups and body.parent is None, "Unbind")
s.skin_method = 'EMPTY'
check(R.bind(bpy.context, rig, [body], 'EMPTY').startswith("Body bound") and len(body.vertex_groups) == 3
      and R.unweighted(body, rig) == len(body.data.vertices), "Empty Groups: a group per bone, no weights")
R.unbind(body, rig)
check(R.bind(bpy.context, rig, [body], 'ENVELOPE') and len(body.vertex_groups) == 3, "Envelope bind makes groups")
R.unbind(body, rig)
# A vertex that belongs to no bone's reach: automatic weights leave it empty, envelope weights are the fallback.
loose = bpy.data.meshes.new("Loose")
bm_ = bmesh.new()
bmesh.ops.create_cone(bm_, cap_ends=True, cap_tris=False, segments=12, radius1=0.3, radius2=0.3, depth=2.0, matrix=Matrix.Translation((0, 0, 1)))
bm_.verts.new((5.0, 5.0, 5.0))
bm_.to_mesh(loose)
bm_.free()
stray = bpy.data.objects.new("Stray", loose)
bpy.context.collection.objects.link(stray)
message = R.bind(bpy.context, rig, [stray], 'AUTO', fallback=True)
check(R.is_bound(stray) and (R.unweighted(stray, rig) == 0 or "instead" in message or "without weight" in message),
      "Bind reports meshes automatic weights could not reach: %s" % message)
R.unbind(stray, rig)
check(R.bind(bpy.context, rig, [stray], 'AUTO', fallback=False) and R.is_bound(stray), "Bind without the envelope fallback keeps the automatic result")
bpy.data.objects.remove(stray)
bpy.data.meshes.remove(loose)
bpy.context.view_layer.objects.active = body
R.unbind(body, rig)
body.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active = body
s.skin_method = 'AUTO'
res_ = bpy.ops.m3d.rig_bind()
check(res_ == {'FINISHED'} and R.is_bound(body) and R.unweighted(body, rig) == 0, "bind again, mesh and skeleton selected: %s %s %s" % (res_, R.is_bound(body), R.unweighted(body, rig)))

# Modes with the mesh bound: Weight Paint paints the mesh, the skeleton stays in Pose Mode.
check(bpy.ops.m3d.rig_mode(mode='WEIGHT_PAINT') == {'FINISHED'}, "Weight Paint button")
check(body.mode == 'WEIGHT_PAINT' and rig.mode == 'POSE' and bpy.context.active_object == body and rig.select_get() and body.select_get(),
      "mesh in Weight Paint Mode, skeleton in Pose Mode and selected: %s %s" % (body.mode, rig.mode))
check(bpy.context.mode == 'PAINT_WEIGHT' and R.mode_key(bpy.context.view_layer) == 'WEIGHT_PAINT', "mode key: Weight Paint")
check(R.rig_of(bpy.context) == rig and R.skin_mesh(bpy.context) == body, "the skeleton and the mesh are found from the mesh")
check(bpy.ops.m3d.rig_mode(mode='POSE') == {'FINISHED'} and rig.mode == 'POSE' and body.mode == 'OBJECT' and bpy.context.active_object == rig,
      "Pose from Weight Paint: the mesh leaves its mode, the skeleton is active")
check(bpy.ops.m3d.rig_mode(mode='OBJECT') == {'FINISHED'} and rig.mode == body.mode == 'OBJECT', "Object leaves both")
bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
check(bpy.ops.m3d.rig_mode(mode='WEIGHT_PAINT') == {'FINISHED'} and body.mode == 'WEIGHT_PAINT' and bpy.context.active_object == body,
      "Weight Paint with the skeleton active picks its bound mesh")
bpy.ops.m3d.rig_mode(mode='OBJECT')

# Dock tab follows the mode: defaults, and the tab the user picked in a mode comes back in that mode.
check([R.MODE_TABS[k] for k in ('EDIT', 'POSE', 'WEIGHT_PAINT')] == ["rig_skeleton", "rig_controls", "rig_skin"], "default tab per mode")
check(all(any(t.id == tab for t in rig_tabs['RIGHT']) for tab in R.MODE_TABS.values()), "mode tabs exist")
R._state["picked"].clear()
bpy.ops.m3d.rig_mode(mode='POSE')
R.remember_tab(bpy.context, "rig_test")
check(R._state["picked"] == {'POSE': "rig_test"}, "a tab picked in Pose Mode is remembered for Pose Mode")
R.remember_tab(bpy.context, "rig_controls")
check(R._state["picked"]["POSE"] == "rig_controls", "the last pick counts")
bpy.ops.m3d.rig_mode(mode='OBJECT')
R.remember_tab(bpy.context, "rig_drive")   # Object Mode has no tab of its own: nothing is remembered
check(list(R._state["picked"]) == ['POSE'], "Object Mode picks are not remembered")
R._state["picked"].clear()

# Every page panel draws, in every mode, without errors; operators and properties they use exist.
def check_calls_ext(where, log):
    check_calls(where, log)
    for rec in log:
        if rec._kind in {"prop_enum", "prop_search"}:
            owner, name = rec._args[0], rec._args[1]
            if hasattr(owner, "bl_rna"):   # (a collection such as scene.keying_sets_all has none)
                check(name in owner.bl_rna.properties, "%s: %r has no property %s" % (where, owner, name))


def draw_rig_panels(label):
    ctx = RCtx()
    drawn = 0
    for page in rig_pages:
        side = 'LEFT' if page == "rig_bones" else 'RIGHT'
        setattr(rig_ws, "m3d_page_" + side.lower(), page)
        ctx = RCtx(side)
        for cls in rig_panels(page):
            if not cls.poll(ctx):
                continue
            drawn += 1
            try:
                check_calls_ext("%s %s" % (label, cls.__name__), draw_stub(cls, ctx))
            except Exception as err:
                check(False, "%s %s draw: %r" % (label, cls.__name__, err))
    log = []
    R.draw_status_line(Rec(log), RCtx())
    check_calls_ext(label + " status line", log)
    return drawn


body.data.vertices[3].select = True
for mode_name in ('OBJECT', 'EDIT', 'POSE', 'WEIGHT_PAINT'):
    bpy.ops.m3d.rig_mode(mode=mode_name)
    if mode_name == 'EDIT':
        arm.edit_bones.active = arm.edit_bones[0]
    if mode_name == 'POSE':
        rig.data.bones.active = rig.data.bones[1]
    check(draw_rig_panels(mode_name) > 10, "page panels drew in %s mode" % mode_name)
    for key in ('RIG_SKELETON', 'RIG_CONTROLS', 'RIG_SKIN', 'CUSTOM'):
        log = []
        bpy.context.window_manager.m3d_shelf = key
        m3d_ui.draw_shelf(Rec(log), RCtx())
        check_calls_ext("shelf %s in %s" % (key, mode_name), log)
bpy.ops.m3d.rig_mode(mode='OBJECT')
status = []
R.draw_status_line(Rec(status), RCtx())
check({r.values().get("mode") for r in status if r._kind == "operator" and r.values().get("mode")}
      >= {'OBJECT', 'EDIT', 'POSE', 'WEIGHT_PAINT'}, "Status Line has the four mode buttons")
check([r._args[1] for r in status if r._kind == "prop_enum" and r._args[1] == "display_type"].__len__() == 5, "Status Line: five bone display types")
check({r._args[1] for r in status if r._kind == "prop"} >= {"show_names", "show_axes", "show_in_front", "use_mirror_x"},
      "Status Line: names, axes, in front, X-Mirror")
check({r._args[2] for r in status if r._kind == "prop_enum" and r._args[1] == "pose_position"} == {'REST', 'POSE'}, "Status Line: Rest / Pose")

# --- Control shapes with colors
bpy.ops.m3d.rig_mode(mode='POSE')
for pb in rig.pose.bones:
    pb.select = False
rig.pose.bones["Joint.001"].select = True
rig.data.bones.active = rig.data.bones["Joint.001"]
s.control_color = (0.2, 0.6, 0.9)
s.control_scale = 1.5
check(bpy.ops.m3d.rig_control(shape='CIRCLE') == {'FINISHED'}, "Circle control")
pb = rig.pose.bones["Joint.001"]
check(pb.custom_shape is not None and pb.custom_shape.name == "WGT-Circle" and len(pb.custom_shape.data.edges) == 32
      and len(pb.custom_shape.data.vertices) == 32 and not pb.custom_shape.data.polygons, "circle widget: 32 edges, wire only")
check(tuple(round(c, 3) for c in pb.custom_shape_scale_xyz) == (1.5, 1.5, 1.5), "scale applied")
check(pb.color.palette == 'CUSTOM' and all(abs(a - b) < 0.01 for a, b in zip(pb.color.custom.normal, (0.2, 0.6, 0.9))), "color assigned")
check(pb.color.custom.select[0] > pb.color.custom.normal[0] and pb.color.custom.active[2] > pb.color.custom.select[2], "selected / active colors are lighter")
widgets = bpy.data.collections.get(R.WIDGETS)
check(widgets is not None and pb.custom_shape.name in widgets.objects and widgets.name in bpy.context.scene.collection.children, "Widgets collection holds the shape")
lc = next(c for c in bpy.context.view_layer.layer_collection.children if c.name == R.WIDGETS)
check(lc.hide_viewport and widgets.hide_render, "...and it is hidden")
expected = {'SQUARE': (4, 4), 'ARROW': (14, 14), 'CUBE': (8, 12), 'SPHERE': (96, 96)}
for shape, (nv, ne) in expected.items():
    bpy.ops.m3d.rig_control(shape=shape, use_color=False)
    wobj = pb.custom_shape
    check(wobj.name == "WGT-" + R.SHAPES[shape][0] and len(wobj.data.vertices) == nv and len(wobj.data.edges) == ne,
          "%s widget has %d vertices, %d edges (%d, %d)" % (shape, nv, ne, len(wobj.data.vertices), len(wobj.data.edges)))
bpy.ops.m3d.rig_control(shape='CIRCLE')
check(pb.custom_shape == bpy.data.objects["WGT-Circle"] and len([o for o in bpy.data.objects if o.name.startswith("WGT-Circle")]) == 1,
      "a widget is made once and shared")
check(bpy.ops.m3d.rig_control_color(preset='RED') == {'FINISHED'} and all(abs(a - b) < 0.01 for a, b in zip(pb.color.custom.normal, R.PRESET_RGB['RED'])), "red preset")
bpy.ops.m3d.rig_control_color(preset='DEFAULT')
check(pb.color.palette == 'DEFAULT', "default colors")
bpy.ops.m3d.rig_control(shape='NONE')
check(pb.custom_shape is None, "No Shape clears the shape")
other = rig.pose.bones["Joint.002"]
check(other.custom_shape is None, "unselected bones are left alone")
bpy.ops.m3d.rig_lock(channels='ALL', lock=True)
check(all(pb.lock_location) and all(pb.lock_rotation) and all(pb.lock_scale) and not any(other.lock_location), "Lock All locks the selected bones")
bpy.ops.m3d.rig_lock(channels='SCALE', lock=False)
bpy.ops.m3d.rig_lock(channels='ALL', lock=False)
check(not any(pb.lock_location) and not any(pb.lock_scale) and not pb.lock_rotation_w, "Unlock All")

# --- Pose tools
pb.rotation_mode = 'XYZ'
pb.rotation_euler = (0.4, 0.1, 0.2)
pb.location = (0.1, 0.2, 0.3)
pb.scale = (2, 2, 2)
other.rotation_quaternion = (0.9, 0.1, 0.0, 0.0)
bpy.ops.m3d.rig_reset_pose(selected_only=True)
check(tuple(pb.location) == (0, 0, 0) and tuple(pb.scale) == (1, 1, 1) and tuple(pb.rotation_euler) == (0, 0, 0)
      and tuple(other.rotation_quaternion) != (1, 0, 0, 0), "Reset Selected resets only the selected bones")
bpy.ops.m3d.rig_reset_pose(selected_only=False)
check(tuple(other.rotation_quaternion) == (1, 0, 0, 0), "Reset Pose resets every bone")

# --- IK with a pole: a bent two-bone limb
bpy.ops.m3d.rig_mode(mode='EDIT')
limb = [arm.edit_bones.new("Thigh"), arm.edit_bones.new("Shin")]
limb[0].head, limb[0].tail = (0.5, 0, 2.0), (0.5, -0.1, 1.0)
limb[1].head, limb[1].tail = (0.5, -0.1, 1.0), (0.5, 0.0, 0.1)
limb[1].parent, limb[1].use_connect = limb[0], True
bpy.ops.m3d.rig_mode(mode='POSE')
rig.data.bones.active = rig.data.bones["Shin"]
s.ik_chain, s.ik_pole = 2, 0.6
check(bpy.ops.m3d.rig_ik_pole() == {'FINISHED'}, "IK with Pole")
con = rig.pose.bones["Shin"].constraints[-1]
check(con.type == 'IK' and con.target == rig and con.subtarget == "IK_Shin" and con.pole_target == rig and con.pole_subtarget == "Pole_Shin"
      and con.chain_count == 2, "IK constraint with target and pole bones")
check("IK_Shin" in rig.data.bones and "Pole_Shin" in rig.data.bones and not rig.data.bones["IK_Shin"].use_deform
      and rig.data.bones["IK_Shin"].parent is None, "target and pole bones: not deforming, no parent")
tip = rig.data.bones["Shin"].tail_local
check((rig.data.bones["IK_Shin"].head_local - tip).length < 1e-5, "the target bone sits at the tip")
pole_head = rig.data.bones["Pole_Shin"].head_local
check(pole_head.y < -0.1, "the pole is out in front of the knee (-Y here): %s" % pole_head)
# Pull the target up: the knee bends toward the pole.
tpb = rig.pose.bones["IK_Shin"]
tpb.location = (0, 0, 0.5)   # bones point +Z in their own space... the matrix is applied below in armature space
tpb.location = tpb.bone.matrix_local.to_3x3().inverted() @ Vector((0, 0, 0.5))
bpy.context.view_layer.update()
ev = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
knee = ev.pose.bones["Shin"].head
line_point = Vector((0.5, 0, 2.0)) + (ev.pose.bones["Shin"].tail - Vector((0.5, 0, 2.0))) * 0.5
check(knee.y < line_point.y - 0.05, "the knee bends toward the pole when the target comes up (knee %s)" % knee)
pole_pb = rig.pose.bones["Pole_Shin"]
pole_pb.location = pole_pb.bone.matrix_local.to_3x3().inverted() @ Vector((0, 2.5, 0)) + pole_pb.location
bpy.context.view_layer.update()
ev = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
check(ev.pose.bones["Shin"].head.y > line_point.y - 0.05, "moving the pole behind turns the bend")
tpb.location = (0, 0, 0)
pole_pb.location = (0, 0, 0)
# Chain of one bone: IK without a pole.
rig.data.bones.active = rig.data.bones["Joint.002"]
s.ik_chain = 1
bpy.ops.m3d.rig_ik_pole()
con1 = rig.pose.bones["Joint.002"].constraints[-1]
check(con1.type == 'IK' and con1.chain_count == 1 and con1.pole_target is None, "chain length 1: no pole")
bpy.ops.m3d.rig_mode(mode='OBJECT')
check(not bpy.ops.m3d.rig_ik_pole.poll(), "IK with Pole needs Pose Mode")

# --- Driven Key
bpy.ops.m3d.rig_mode(mode='POSE')
drv_pb, driven_pb = rig.pose.bones["Joint"], rig.pose.bones["Joint.001"]
drv_pb.rotation_mode = 'QUATERNION'
s.dk_driver_object, s.dk_driver_bone, s.dk_driver_channel = rig, "Joint", 'ROT_X'
s.dk_kind, s.dk_driven_object, s.dk_driven_bone, s.dk_driven_channel = 'BONE', rig, "Joint.001", 'LOC_Y'
s.dk_interp = 'LINEAR'
driver, driven = R.driver_channel(s), R.driven_channel(s)
check(driver and driven and driver.path == 'pose.bones["Joint"].rotation_euler' and driver.index == 0
      and driven.path == 'pose.bones["Joint.001"].location' and driven.index == 1, "channels: %s / %s" % (driver, driven))
for x_angle, value in ((0.0, 0.0), (math.pi / 2, 1.0), (math.pi, 0.25)):
    drv_pb.rotation_euler[0] = x_angle
    s.dk_value = value
    check(bpy.ops.m3d.rig_driven_key(action='KEY') == {'FINISHED'}, "key pair %.2f -> %.2f" % (x_angle, value))
check(drv_pb.rotation_mode == 'XYZ', "a quaternion driver bone switches to Euler")
fc = R.driven_curve(driven)
keys = R.driven_keys(driven)
check(fc is not None and fc.driver.type == 'AVERAGE' and len(fc.driver.variables) == 1 and not fc.modifiers, "one driver, one variable, no modifiers")
var = fc.driver.variables[0]
check(var.targets[0].id == rig and var.targets[0].data_path == 'pose.bones["Joint"].rotation_euler[0]', "variable reads the driver channel: %s" % var.targets[0].data_path)
check([round(k[0], 4) for k in keys] == [0.0, round(math.pi / 2, 4), round(math.pi, 4)] and [round(k[1], 4) for k in keys] == [0.0, 1.0, 0.25], "the three pairs are the keys: %s" % keys)
for x_angle, value in ((0.0, 0.0), (math.pi / 2, 1.0), (math.pi, 0.25)):
    check(abs(fc.evaluate(x_angle) - value) < 1e-4, "curve at the key %.2f is %.2f (%.4f)" % (x_angle, value, fc.evaluate(x_angle)))
check(abs(fc.evaluate(math.pi / 4) - 0.5) < 1e-4 and abs(fc.evaluate(3 * math.pi / 4) - 0.625) < 1e-4, "linear in between: %s %s" % (fc.evaluate(math.pi / 4), fc.evaluate(3 * math.pi / 4)))
check(abs(fc.evaluate(-1.0)) < 1e-6 and abs(fc.evaluate(10.0) - 0.25) < 1e-6, "outside the keys the curve holds the end values")
# The scene follows: pose the driver bone, the driven bone moves.
drv_pb.rotation_euler[0] = math.pi / 4
bpy.context.view_layer.update()
check(abs(driven_pb.location[1] - 0.5) < 1e-3, "posing the driver moves the driven bone: %s" % driven_pb.location[1])
drv_pb.rotation_euler[0] = math.pi / 2
bpy.context.view_layer.update()
check(abs(driven_pb.location[1] - 1.0) < 1e-3, "...to the keyed value")
# Smooth keys: through the keys, no overshoot between them.
s.dk_interp = 'BEZIER'
s.dk_value = 1.0
drv_pb.rotation_euler[0] = math.pi / 2
bpy.ops.m3d.rig_driven_key(action='KEY')
fc = R.driven_curve(driven)
check(len(fc.keyframe_points) == 3 and all(kp.interpolation == 'BEZIER' for kp in fc.keyframe_points), "keying the same value again replaces the key; curve is smooth")
samples = [fc.evaluate(math.pi / 2 * i / 10) for i in range(11)]
check(abs(samples[0]) < 1e-4 and abs(samples[-1] - 1.0) < 1e-4 and all(b >= a - 1e-6 for a, b in zip(samples, samples[1:])) and max(samples) <= 1.0 + 1e-6,
      "smooth curve between keys rises 0 -> 1 without overshoot: %s" % [round(v, 3) for v in samples])
check(0.0 < fc.evaluate(math.pi / 4) < 1.0, "smooth curve interpolates")
bpy.ops.m3d.rig_driven_key(action='REMOVE', index=2)
check(len(R.driven_keys(driven)) == 2, "Remove Key")
s.dk_value = 7.0
bpy.ops.m3d.rig_driven_key(action='READ')
check(abs(s.dk_value - driven_pb.location[1]) < 1e-5, "Read Driven Value")
check(bpy.ops.m3d.rig_driven_key(action='CLEAR') == {'FINISHED'} and R.driven_curve(driven) is None, "Clear removes the driver")
# A custom property drives, a channel cannot drive itself.
rig.pose.bones["Joint.002"]["fk_ik"] = 0.0
s.dk_driver_bone, s.dk_driver_channel, s.dk_driver_prop = "Joint.002", 'PROP', "fk_ik"
s.dk_driven_bone, s.dk_driven_channel = "Joint.001", 'SCL_X'
s.dk_value = 3.0
rig.pose.bones["Joint.002"]["fk_ik"] = 1.0
check(R.driver_channel(s).path == 'pose.bones["Joint.002"]["fk_ik"]' and bpy.ops.m3d.rig_driven_key(action='KEY') == {'FINISHED'}, "custom property as the driver")
check(abs(R.driven_curve(R.driven_channel(s)).evaluate(1.0) - 3.0) < 1e-5, "custom property key maps 1.0 -> 3.0")
bpy.ops.m3d.rig_driven_key(action='CLEAR')
s.dk_driven_bone, s.dk_driven_channel = "Joint.002", 'PROP'
s.dk_driven_prop = "fk_ik"
check(bpy.ops.m3d.rig_driven_key(action='KEY') == {'CANCELLED'}, "a channel cannot drive itself")
# Shape key driven by a bone rotation.
bpy.ops.m3d.rig_mode(mode='OBJECT')
body.shape_key_add(name="Basis")
body.shape_key_add(name="Smile")
s.dk_driver_bone, s.dk_driver_channel = "Joint", 'ROT_X'
s.dk_kind, s.dk_driven_object, s.dk_driven_shape, s.dk_interp = 'SHAPE_KEY', body, "Smile", 'LINEAR'
shape_driven = R.driven_channel(s)
check(shape_driven is not None and shape_driven.path == 'key_blocks["Smile"].value', "shape key channel: %s" % (shape_driven,))
drv_pb.rotation_euler[0] = 0.0
s.dk_value = 0.0
bpy.ops.m3d.rig_driven_key(action='KEY')
drv_pb.rotation_euler[0] = math.pi / 2
s.dk_value = 1.0
bpy.ops.m3d.rig_driven_key(action='KEY')
bpy.context.view_layer.update()
drv_pb.rotation_euler[0] = math.pi / 4
bpy.context.view_layer.update()
check(abs(body.data.shape_keys.key_blocks["Smile"].value - 0.5) < 1e-3, "a bone rotation drives a shape key: %s" % body.data.shape_keys.key_blocks["Smile"].value)
check(len(R.drivers_of(body)) == 1 and R.drivers_of(body)[0][1] == body.data.shape_keys, "Drivers panel lists the shape key driver")
bpy.context.view_layer.objects.active = body
check(bpy.ops.m3d.rig_driver_remove(owner=body.data.shape_keys.name, path='key_blocks["Smile"].value', index=0) == {'FINISHED'}
      and not R.drivers_of(body), "driver removed from the list")
drv_pb.rotation_euler[0] = 0.0
# Use Active fills the pickers.
bpy.context.view_layer.objects.active = rig
rig.data.bones.active = rig.data.bones["Joint.002"]
bpy.ops.m3d.rig_driven_key(action='USE_DRIVER')
check(s.dk_driver_object == rig and s.dk_driver_bone == "Joint.002", "Use Active as Driver")

# --- Weights: limit, normalize, clean, mirror numbers
bpy.ops.m3d.rig_mode(mode='OBJECT')
bpy.context.view_layer.objects.active = body
body.select_set(True)
mid_i = min(body.data.vertices, key=lambda v: abs(v.co.z - 1.0) + abs(v.co.x) * 0.1).index
vg = {g.name: g for g in body.vertex_groups}
vg["Joint"].add([mid_i], 0.6, 'REPLACE')
vg["Joint.001"].add([mid_i], 0.3, 'REPLACE')
vg["Joint.002"].add([mid_i], 0.05, 'REPLACE')
bpy.ops.object.vertex_group_limit_total(group_select_mode='BONE_DEFORM', limit=2)
w = {body.vertex_groups[g.group].name: g.weight for g in body.data.vertices[mid_i].groups if g.weight > 0}
check(len(w) == 2 and "Joint.002" not in w, "Limit Total keeps the two strongest influences: %s" % w)
bpy.ops.object.vertex_group_normalize_all(group_select_mode='BONE_DEFORM', lock_active=False)
w = {body.vertex_groups[g.group].name: g.weight for g in body.data.vertices[mid_i].groups if g.weight > 0}
check(abs(sum(w.values()) - 1.0) < 1e-4 and abs(w["Joint"] - 0.6 / 0.9) < 1e-3, "Normalize All: the weights add up to 1 in the ratio 2:1: %s" % w)
vg["Joint.001"].add([mid_i], 0.004, 'REPLACE')
vg["Joint"].add([mid_i], 0.996, 'REPLACE')
bpy.ops.object.vertex_group_clean(group_select_mode='BONE_DEFORM', limit=0.01, keep_single=False)
w = {body.vertex_groups[g.group].name: g.weight for g in body.data.vertices[mid_i].groups if g.weight > 0}
check(list(w) == ["Joint"], "Clean removes weights below the threshold: %s" % w)
# Mirror: a flat grid with L / R groups.
grid_mesh = bpy.data.meshes.new("Grid")
bm_ = bmesh.new()
bmesh.ops.create_grid(bm_, x_segments=4, y_segments=4, size=1.0)
bm_.to_mesh(grid_mesh)
bm_.free()
gobj = bpy.data.objects.new("GridObj", grid_mesh)
bpy.context.collection.objects.link(gobj)
gl, gr = gobj.vertex_groups.new(name="Hand.L"), gobj.vertex_groups.new(name="Hand.R")
for v in grid_mesh.vertices:
    if v.co.x > 0.01:
        gl.add([v.index], min(1.0, v.co.x), 'REPLACE')
bpy.context.view_layer.objects.active = gobj
gobj.select_set(True)
def at(x, y):
    return next(v for v in grid_mesh.vertices if abs(v.co.x - x) < 1e-3 and abs(v.co.y - y) < 1e-3)


def weight_of(v, name):
    gi = gobj.vertex_groups[name].index
    return next((g.weight for g in v.groups if g.group == gi), 0.0)


check(bpy.ops.m3d.rig_mirror_weights(direction='POSITIVE_X') == {'FINISHED'} and gobj.mode == 'OBJECT', "Mirror Weights from Object Mode")
check(all(abs(weight_of(at(-x, y), "Hand.R") - weight_of(at(x, y), "Hand.L")) < 1e-3 for x in (0.5, 1.0) for y in (-1.0, -0.5, 0.0, 0.5, 1.0)),
      "Mirror Weights: the .R group on the -X side copies the .L group")
check(abs(weight_of(at(-1.0, 0.0), "Hand.R") - 1.0) < 1e-3 and abs(weight_of(at(-0.5, 0.0), "Hand.R") - 0.5) < 1e-3,
      "...with the same numbers: %s" % [round(weight_of(at(-x, 0.0), "Hand.R"), 3) for x in (0.5, 1.0)])
check(abs(weight_of(at(1.0, 0.0), "Hand.L") - 1.0) < 1e-3 and weight_of(at(1.0, 0.0), "Hand.R") == 0.0,
      "...and the side it copies from is unchanged")
check(not any(v.select for v in grid_mesh.vertices), "the selection is restored")
# And back: clear the left side, copy from the right.
for v in grid_mesh.vertices:
    if v.co.x > 0.01:
        gl.remove([v.index])
bpy.ops.m3d.rig_mirror_weights(direction='NEGATIVE_X')
check(abs(weight_of(at(1.0, 0.0), "Hand.L") - 1.0) < 1e-3 and abs(weight_of(at(0.5, 0.0), "Hand.L") - 0.5) < 1e-3, "-X to +X copies back")
for v in grid_mesh.vertices:
    if v.co.x > 0.01:
        gl.remove([v.index])
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.m3d.rig_mirror_weights(direction='NEGATIVE_X')
bpy.ops.object.mode_set(mode='OBJECT')
check(abs(weight_of(at(1.0, 0.0), "Hand.L") - 1.0) < 1e-3, "Mirror Weights from Edit Mode")
for v in grid_mesh.vertices:
    if v.co.x < -0.01:
        gr.remove([v.index])
bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
bpy.ops.m3d.rig_mirror_weights(direction='POSITIVE_X')
bpy.ops.object.mode_set(mode='OBJECT')
check(abs(weight_of(at(-1.0, 0.0), "Hand.R") - 1.0) < 1e-3 and abs(weight_of(at(1.0, 0.0), "Hand.L") - 1.0) < 1e-3 and not grid_mesh.use_paint_mask_vertex,
      "Mirror Weights from Weight Paint Mode (vertex select is put back)")

# --- Transfer weights: copy from the bound body to a copy without groups
twin = body.copy()
twin.data = body.data.copy()
twin.name = "Twin"
twin.vertex_groups.clear()
twin.location.x = 0.0
bpy.context.collection.objects.link(twin)
bpy.context.view_layer.objects.active = twin
s.transfer_source = body
check(bpy.ops.m3d.rig_transfer_weights() == {'FINISHED'}, "Transfer Weights")
check({g.name for g in twin.vertex_groups} == {g.name for g in body.vertex_groups}, "missing groups are created: %s" % [g.name for g in twin.vertex_groups])
probe = min(twin.data.vertices, key=lambda v: abs(v.co.z - 0.4) + v.co.x)
src_w = {body.vertex_groups[g.group].name: g.weight for g in body.data.vertices[probe.index].groups}
dst_w = {twin.vertex_groups[g.group].name: g.weight for g in probe.groups}
check(all(abs(src_w.get(k, 0.0) - dst_w.get(k, 0.0)) < 0.05 for k in {*src_w, *dst_w}) and dst_w, "weights are copied: %s vs %s" % (src_w, dst_w))
s.transfer_source = None
check(not bpy.ops.m3d.rig_transfer_weights.poll(), "Transfer needs a source")
bpy.data.objects.remove(twin)
bpy.data.objects.remove(gobj)

# --- Solo / lock influences
bpy.context.view_layer.objects.active = body
check(bpy.ops.m3d.rig_solo(index=1) == {'FINISHED'} and body.vertex_groups[1].lock_weight is False
      and body.vertex_groups[0].lock_weight and body.vertex_groups[2].lock_weight and body.vertex_groups.active_index == 1 and R.solo_state(body, 1), "Solo locks the others")
bpy.ops.m3d.rig_solo(index=1)
check(not any(g.lock_weight for g in body.vertex_groups), "Solo again unlocks all")

# --- Weight table: the active vertex
for v in body.data.vertices:
    v.select = False
check(R.active_vertex(body) is None, "no vertex selected: no table")
body.data.vertices[mid_i].select = True
vg["Joint.001"].add([mid_i], 0.4, 'REPLACE')
found = R.active_vertex(body)
check(found and found[0] == mid_i and {n for n, _ in found[1]} >= {"Joint", "Joint.001"}, "weight table of the selected vertex: %s" % (found,))
check(bpy.ops.m3d.rig_vertex_weight(group="Joint.001", weight=0.75) == {'FINISHED'}
      and abs(dict(R.active_vertex(body)[1])["Joint.001"] - 0.75) < 1e-5, "set a weight from the table")
check(bpy.ops.m3d.rig_vertex_weight(group="Joint.001", remove=True) == {'FINISHED'} and "Joint.001" not in dict(R.active_vertex(body)[1]),
      "remove a vertex from a group from the table")
bpy.ops.object.mode_set(mode='EDIT')
bm_ = bmesh.from_edit_mesh(body.data)
check(R.active_vertex(body) is not None, "the table works in Edit Mode too")
bpy.ops.m3d.rig_vertex_weight(group="Joint.002", weight=0.2)
bm_ = bmesh.from_edit_mesh(body.data)
layer = bm_.verts.layers.deform.active
bm_.verts.ensure_lookup_table()
check(abs(bm_.verts[mid_i][layer][body.vertex_groups["Joint.002"].index] - 0.2) < 1e-5, "Edit Mode table sets a weight")
bpy.ops.object.mode_set(mode='OBJECT')

# --- Test poses: pose assets, flipped copy
bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.m3d.rig_mode(mode='EDIT')
for name, x in (("Wing.L", 0.5), ("Wing.R", -0.5)):
    eb = arm.edit_bones.new(name)
    eb.head, eb.tail = (x, 0, 1.5), (x * 1.5, 0, 1.5)
bpy.ops.m3d.rig_mode(mode='POSE')
wl, wr = rig.pose.bones["Wing.L"], rig.pose.bones["Wing.R"]
wl.rotation_mode = wr.rotation_mode = 'XYZ'
for pb_ in rig.pose.bones:
    pb_.select = pb_.name in {"Wing.L"}
wl.rotation_euler = (0.1, 0.4, 0.5)
wl.location = (0.2, 0.3, 0.4)
s.pose_name = "Flap"
check(bpy.ops.m3d.rig_pose_save() == {'FINISHED'}, "Save Pose")
assets = R.pose_assets()
check([a.name for a in assets] == ["Flap"], "the saved pose is listed: %s" % [a.name for a in assets])
wl.rotation_euler = (0, 0, 0)
wl.location = (0, 0, 0)
check(bpy.ops.m3d.rig_pose_apply(name="Flap") == {'FINISHED'} and tuple(round(v, 4) for v in wl.rotation_euler) == (0.1, 0.4, 0.5)
      and tuple(round(v, 4) for v in wl.location) == (0.2, 0.3, 0.4), "Apply Pose restores the pose")
check(tuple(wr.rotation_euler) == (0, 0, 0), "...and leaves other bones alone")
bpy.ops.m3d.rig_pose_apply(name="Flap", flipped=True)
check(tuple(round(v, 4) for v in wr.rotation_euler) == (0.1, -0.4, -0.5) and tuple(round(v, 4) for v in wr.location) == (-0.2, 0.3, 0.4),
      "Apply Pose flipped puts it on the other side mirrored: %s %s" % (tuple(wr.rotation_euler), tuple(wr.location)))
wr.rotation_euler = (0, 0, 0)
wr.location = (0, 0, 0)
bpy.ops.m3d.rig_pose_apply(name="Flap", blend=0.5)
check(abs(wl.rotation_euler[1] - 0.4) < 1e-4, "blend 1 from the pose itself is unchanged")
wl.rotation_euler = (0, 0, 0)
bpy.ops.m3d.rig_pose_apply(name="Flap", blend=0.5)
check(abs(wl.rotation_euler[1] - 0.2) < 1e-4, "Apply Pose with blend 0.5 goes half way")
# Copy / paste flipped.
wl.rotation_euler = (0.3, 0.2, 0.1)
wr.rotation_euler = (0, 0, 0)
for pb_ in rig.pose.bones:
    pb_.select = pb_.name == "Wing.L"
bpy.ops.pose.copy()
for pb_ in rig.pose.bones:
    pb_.select = pb_.name == "Wing.R"
bpy.ops.pose.paste(flipped=True)
check(abs(wr.rotation_euler[0] - 0.3) < 1e-4 and abs(wr.rotation_euler[1] + 0.2) < 1e-4, "Paste Flipped mirrors the pose: %s" % (tuple(wr.rotation_euler),))
bpy.ops.m3d.rig_reset_pose()
bpy.ops.m3d.rig_mode(mode='OBJECT')

# --- Bone collections and selection sets (Blender's own operators, used by the Collections tab)
bpy.ops.m3d.rig_mode(mode='POSE')
check(bpy.ops.armature.collection_add() == {'FINISHED'} and len(rig.data.collections_all) == 1, "Bone collection added")
for pb_ in rig.pose.bones:
    pb_.select = pb_.name in {"Joint", "Joint.001"}
check(bpy.ops.armature.collection_assign() == {'FINISHED'} and len(rig.data.collections_all[0].bones) == 2, "...and assigned")
check(bpy.ops.pose.selection_set_add_and_assign() == {'FINISHED'} and len(rig.selection_sets) == 1, "Selection set added")
bpy.ops.m3d.rig_mode(mode='OBJECT')

# --- Drivers editor toggle works on a screen (the real windows are covered in gui_test.py)
check(R.drivers_open(None) is False and R.bottom_area(NS(areas=[NS(ui_type='TIMELINE', y=10), NS(ui_type='VIEW_3D', y=100)])).ui_type == 'TIMELINE',
      "bottom editor is the lowest Timeline / Drivers area")
check(R.drivers_open(NS(areas=[NS(ui_type='DRIVERS', y=0)])) and not R.drivers_open(NS(areas=[NS(ui_type='TIMELINE', y=0)])), "drivers_open")

# --- Rigify: off until asked, enabled on first use, failures handled
for mod in ("rigify",):
    try:
        addon_utils.disable(mod, default_set=True)
    except Exception:
        pass
check(not R.rigify_enabled(), "Rigify is off at first")
check(not any(e.get("idname") == "pose.rigify_generate" for e in sum((m[1] for m in m3d_ui.MENUS.values()), [])), "no menu depends on Rigify being on")
real_enable = addon_utils.enable


def broken_enable(*args, **kwargs):
    raise RuntimeError("no luck")


addon_utils.enable = broken_enable
check(bpy.ops.m3d.rig_rigify(action='ENABLE') == {'CANCELLED'} and "no luck" in s.rigify_note, "a Rigify that fails to load is reported, not raised: %r" % s.rigify_note)
addon_utils.enable = lambda *a, **k: None
check(bpy.ops.m3d.rig_rigify(action='ENABLE') == {'CANCELLED'}, "an add-on that does not load cancels")
addon_utils.enable = real_enable
check(bpy.ops.m3d.rig_rigify(action='ENABLE') == {'FINISHED'} and R.rigify_enabled() and s.rigify_note == "", "Enable Rigify")
check(op_ok("pose.rigify_generate", {}) and op_ok("object.armature_human_metarig_add", {}), "Rigify operators exist once enabled")
before = len(bpy.data.objects)
check(bpy.ops.m3d.rig_rigify(action='META') == {'FINISHED'} and len(bpy.data.objects) == before + 1 and bpy.context.active_object.type == 'ARMATURE',
      "Human Meta-Rig adds a meta-rig")
meta = bpy.context.active_object
check(bpy.ops.m3d.rig_rigify(action='GENERATE') in ({'FINISHED'}, {'CANCELLED'}), "Generate Rig runs (or reports)")
for ob_ in list(bpy.data.objects):
    if ob_ != rig and ob_ != body:
        bpy.data.objects.remove(ob_)
addon_utils.disable("rigify", default_set=True)
check(not R.rigify_enabled(), "Rigify can be turned off again")
# The Rigify panel draws in both states.
real_state = R.rigify_enabled
for state in (False, True):
    R.rigify_enabled = lambda state=state: state
    log = []
    R.PROPERTIES_PT_m3d_rg_rigify.draw(type("Inst", (), {"layout": Rec(log)})(), RCtx())
    check_calls_ext("rigify panel", log)
    labels = [r._kw.get("text") for r in log if r._kind == "operator"]
    check(labels == (["Human Meta-Rig", "Generate Rig"] if state else ["Enable Rigify"]), "Rigify panel buttons (enabled=%s): %s" % (state, labels))
R.rigify_enabled = real_state

# Constraint stack draws for the constraints we added (target, pole, influence).
bpy.ops.m3d.rig_mode(mode='POSE')
rig.data.bones.active = rig.data.bones["Shin"]
log = []
R.draw_constraint(Rec(log), rig.pose.bones["Shin"], rig.pose.bones["Shin"].constraints[0])
check_calls_ext("constraint row", log)
check({r._args[1] for r in log if r._kind == "prop"} >= {"mute", "name", "target", "pole_target", "chain_count", "pole_angle", "influence"}, "constraint row shows target, pole and influence")
bpy.ops.m3d.rig_mode(mode='OBJECT')

# ----------------------------------------------------------------------------------------------------
# Phase 5: Animation workspace (tabs, pages, gates, Tween, selection sets, presets, layers, playblast, Channel Box).
import m3d_anim as A
import math, shutil

anim_ws = bpy.data.workspaces["Animation"]
an_tabs = W.DOCK_TABS['ANIM']
check([t.label for t in an_tabs['RIGHT']] == ["Channel Box", "Pick", "Tween & Poses", "Motion", "Layers", "Playback"], "Animation dock tabs")
check(an_tabs['LEFT'] == () and W.dock_tabs('ANIM', 'LEFT') == an_tabs['RIGHT'], "Animation has no left tray")
check(an_tabs['RIGHT'][0].context == 'CHANNEL_BOX' and an_tabs['RIGHT'][0].page is None, "the first Animation tab is the Channel Box")
for tab in an_tabs['RIGHT'][1:]:
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("anim_"), "Animation page tab " + tab.id)
an_pages = {t.page for t in an_tabs['RIGHT'] if t.page}
check({c.page for c in A.classes if hasattr(c, "page")} == an_pages, "every Animation page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in A.classes if not issubclass(c, bpy.types.PropertyGroup)),
      "Animation classes registered")
check(m3d_ui.shelves_for('ANIM') == ['ANIM_ANIMATE', 'ANIM_POSES', 'CUSTOM'] and 'ANIM' in m3d_ui.STATUS_LINES, "Animation shelf tabs and Status Line")
check([it[3] for it in m3d_ui.SHELVES['ANIM_ANIMATE'][1] if it] == ["Set Key", "Translate", "Rotate", "Scale", "Breakdown", "Delete Key",
                                                                   "Euler Filter", "Stepped", "Spline"], "Animate shelf buttons")
check([it[3] if not callable(it) else "menu" for it in m3d_ui.SHELVES['ANIM_POSES'][1] if it] == ["Copy", "Paste", "Paste Flipped", "Reset", "Save Pose", "menu"],
      "Poses shelf buttons")
check(anim_ws.m3d_kind == 'ANIM' and anim_ws.object_mode == 'POSE', "Animation workspace kind and entry mode")
an_src = open(A.__file__, encoding="utf-8").read().lower()
for word in ("maya", "autodesk", "animbot", "tween machine", "studio library", "motionbuilder", "cascadeur", "mgear"):
    check(word not in an_src, "Animation code names " + word)

# Keys: the new ones land, and are free in the keymaps around them.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
for km in ("Object Mode", "Pose"):
    item = find(km, "m3d.tween", 'Q', alt=True, shift=False, ctrl=False)
    check(item and item[0].properties.interactive, "Alt+Q tweens in " + km)
for idname, key in (("pose.push", 'P'), ("pose.relax", 'R'), ("pose.breakdown", 'B')):
    check(find("Pose", idname, key, alt=True, shift=True, ctrl=False), "Alt+Shift+%s is %s in Pose Mode" % (key, idname))
for key, mods in (('Q', dict(alt=True)), ('P', dict(alt=True, shift=True)), ('R', dict(alt=True, shift=True)), ('B', dict(alt=True, shift=True))):
    want = {"shift": False, "ctrl": False, "alt": False, **mods}
    others = [(km.name, k.idname) for km in kc.keymaps for k in km.keymap_items
              if k.type == key and all(getattr(k, m) == v for m, v in want.items()) and not k.oskey
              and km.name in {"Window", "Screen", "Screen Editing", "Frames", "Property Editor", "3D View", "3D View Generic",
                              "Object Non-modal", "Object Mode", "Pose"}
              and not k.idname.startswith(("m3d.tween", "pose.push", "pose.relax", "pose.breakdown"))]
    check(not others, "Animation key %s %s is free around Pose / Object Mode: %s" % (key, mods, others))
check(find("Frames", "screen.keyframe_jump", "PERIOD", shift=False, alt=False) and find("Frames", "screen.frame_offset", "PERIOD", alt=True)
      and find("Frames", "screen.animation_play", "V", alt=True) and find("Object Mode", "m3d.key_marking_menu", "S", shift=True),
      "the old animation keys are still there")
check(find("Pose", "screen.frame_jump", "LEFT_ARROW", ctrl=True) and find("Object Mode", "screen.frame_jump", "RIGHT_ARROW", ctrl=True),
      "Ctrl+Left / Right jump to the start / end")

# A scene to animate: a cube and a two-bone rig with a custom slider, keyed at frames 1 and 11.
for ob_ in list(bpy.data.objects):
    if ob_.mode != 'OBJECT':
        bpy.context.view_layer.objects.active = ob_
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(ob_)
for mesh_ in list(bpy.data.meshes):
    bpy.data.meshes.remove(mesh_)
for act_ in list(bpy.data.actions):
    bpy.data.actions.remove(act_)
scn = bpy.context.scene
scn.camera = None


class ACtx(SCtx):
    """Context of the Animation dock: the real one with this workspace and an (empty) screen."""
    def __init__(self):
        super().__init__('RIGHT')
        self.workspace = anim_ws
        self.screen = NS(areas=[])


def an_panels(page):
    return [c for c in A.classes if getattr(c, "page", None) == page and hasattr(c, "poll")]


def an_shown(page):
    anim_ws.m3d_page_right = page
    ctx = ACtx()
    return [c.__name__ for c in an_panels(page) if c.poll(ctx)]


# Gates without anything to animate.
for page in A.GATES:
    names = an_shown("anim_" + page)
    check(names and names[0].endswith("_gate") and len(names) == 1, "anim_%s without an object shows its message only: %s" % (page, names))
check(an_shown("anim_pick") == ["PROPERTIES_PT_m3d_an_object_sets"] and an_shown("anim_playback")
      and not any(n.endswith("_gate") for n in an_shown("anim_playback")), "Pick and Playback need no object: %s" % an_shown("anim_pick"))
check(A.PROPERTIES_PT_m3d_an_camera.poll(ACtx()), "no scene camera: the Channel Box tab asks for one")
bpy.ops.object.camera_add()
scn.camera = bpy.context.active_object
check(not A.PROPERTIES_PT_m3d_an_camera.poll(ACtx()), "...and stops asking once there is one")
bpy.data.objects.remove(scn.camera)
scn.camera = None

bpy.ops.mesh.primitive_cube_add(size=1)
cube_ = bpy.context.active_object
cube_.name = "Box"
rig_a = R.new_armature(bpy.context, "Rig")
R._select_only(bpy.context, rig_a)
bpy.ops.object.mode_set(mode='EDIT')
for name_, z in (("Root", 0.0), ("Arm", 1.0)):
    eb_ = rig_a.data.edit_bones.new(name_)
    eb_.head, eb_.tail = (0, 0, z), (0, 0, z + 1.0)
rig_a.data.edit_bones["Arm"].parent = rig_a.data.edit_bones["Root"]
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.m3d.rig_mode(mode='POSE')
for pb_ in rig_a.pose.bones:
    pb_.rotation_mode = 'XYZ'
rig_a.pose.bones["Arm"]["IK_FK"] = 0.5
rig_a.data.bones.active = rig_a.data.bones["Arm"]
for pb_ in rig_a.pose.bones:
    pb_.select = pb_.name == "Arm"
arm_pb, root_pb = rig_a.pose.bones["Arm"], rig_a.pose.bones["Root"]
for frame_, value_ in ((1, 0.0), (11, 10.0)):
    arm_pb.location.x = root_pb.location.x = value_
    arm_pb.rotation_euler.y = value_ / 10
    for pb_ in (arm_pb, root_pb):
        pb_.keyframe_insert("location", index=0, frame=frame_)
    arm_pb.keyframe_insert("rotation_euler", index=1, frame=frame_)
scn.frame_set(6)


# --- Every page panel draws in Object Mode and in Pose Mode
def draw_anim_panels(label):
    drawn = 0
    for page in an_pages:
        anim_ws.m3d_page_right = page
        ctx = ACtx()
        for cls in an_panels(page):
            if not cls.poll(ctx):
                continue
            drawn += 1
            try:
                check_calls_ext("%s %s" % (label, cls.__name__), draw_stub(cls, ctx))
            except Exception as err:
                check(False, "%s %s draw: %r" % (label, cls.__name__, err))
    log = []
    A.draw_status_line(Rec(log), ACtx())
    check_calls_ext(label + " status line", log)
    for key in ('ANIM_ANIMATE', 'ANIM_POSES', 'CUSTOM'):
        log = []
        bpy.context.window_manager.m3d_shelf = key
        m3d_ui.draw_shelf(Rec(log), ACtx())
        check_calls_ext("shelf %s in %s" % (key, label), log)
    return drawn


bpy.ops.m3d.rig_mode(mode='OBJECT')
R._select_only(bpy.context, cube_)
cube_.keyframe_insert("location", index=0, frame=1)
cube_.location.x = 10
cube_.keyframe_insert("location", index=0, frame=11)
cube_.location.x = 0
scn.frame_set(6)
check(draw_anim_panels('OBJECT') >= 8, "Animation panels drew in Object Mode")
bpy.ops.m3d.rig_mode(mode='POSE')
check(draw_anim_panels('POSE') >= 9, "Animation panels drew in Pose Mode")
log = []
A.draw_status_line(Rec(log), ACtx())
check({r.values().get("mode") for r in log if r._kind == "operator" and r.values().get("mode")} >= {'OBJECT', 'POSE'}, "Status Line: Object / Pose")
check({r._args[1] for r in log if r._kind == "prop"} >= {"use_keyframe_insert_auto", "frame_start", "frame_end", "use_preview_range", "fps",
                                                      "playback_loop_mode"}, "Status Line: Auto Key, range, preview range, FPS, loop mode")
check(len([r for r in log if r._kind == "prop_enum" and r._args[1] == "keyframe_type"]) == 4, "Status Line: four key types")
check({r.values().get("kind") for r in log if r._kind == "operator" and r._args[0] == "m3d.anim_interp"} == set(A.INTERP), "Status Line: four new-key interpolations")
check({r.values().get("editor") for r in log if r._kind == "operator" and r._args[0] == "m3d.anim_editor"} == {'GRAPH', 'DOPESHEET'}, "Status Line: Graph / Dope Sheet")
check(any(r._kind == "operator" and r._args[0] == "m3d.playblast" for r in log) and any(r._kind == "popover" for r in log), "Status Line: Playblast, Auto Key options")


# --- Channel Box: the active bone in Pose Mode (and the object otherwise), custom properties as sliders
def channel_box_log():
    log = []
    inst = type("Inst", (), {"layout": Rec(log)})()
    m3d_mode.PROPERTIES_PT_m3d_channel_box.draw(inst, bpy.context)
    return log


bpy.context.view_layer.objects.active = rig_a
log = channel_box_log()
owners = {r._args[0].name for r in log if r._kind == "prop" and hasattr(r._args[0], "bone")}
check(owners == {"Arm"}, "Channel Box shows the active bone in Pose Mode: %s" % owners)
check(any(r._kind == "prop" and r._args[1] == '["IK_FK"]' and r._kw.get("slider") for r in log), "...its custom property as a slider")
check_calls("channel box pose", log)
rig_a.data.bones.active = rig_a.data.bones["Root"]
check({r._args[0].name for r in channel_box_log() if r._kind == "prop" and hasattr(r._args[0], "bone")} == {"Root"}, "...and follows the active bone")
rig_a.data.bones.active = rig_a.data.bones["Arm"]
arm_pb.rotation_mode = 'QUATERNION'
check(any(r._kind == "prop" and r._args[1] == "rotation_quaternion" for r in channel_box_log()), "...with the rotation mode's own channels")
arm_pb.rotation_mode = 'XYZ'
bpy.ops.m3d.rig_mode(mode='OBJECT')
R._select_only(bpy.context, cube_)
log = channel_box_log()
check({r._args[0] for r in log if r._kind == "prop" and r._args[1] == "location"} == {cube_}, "Channel Box shows the object in Object Mode")
check_calls("channel box object", log)

# Channel Box INPUTS: "<Kind> inputs" with the kind's rows above the modifiers; frozen shows the note and Delete History.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.m3d.add_primitive(kind='CYLINDER')
prim_ = bpy.context.active_object
prim_.modifiers.new("Bevel", 'BEVEL')
log = channel_box_log()
labels_ = [r._kw.get("text") for r in log if r._kind == "label"]
check("INPUTS" in labels_ and "Cylinder inputs" in labels_ and labels_.index("INPUTS") < labels_.index("Cylinder inputs"), "Channel Box: INPUTS > Cylinder inputs: %s" % labels_)
rows_ = [(r._args[1], r._kw.get("text")) for r in log if r._kind == "prop" and r._args[0] == prim_.m3d_input]
check([n for n, _t in rows_] == list(I.KINDS['CYLINDER'][1]) and rows_[3] == ("sub_height", "Subdivisions Height"), "Channel Box: the cylinder's inputs: %s" % rows_)
check(not any(t == "Mesh edited: inputs no longer apply" for t in labels_), "Channel Box: no frozen note on a live primitive")
check_calls("channel box inputs", log)
prim_.data.vertices[0].co.x += 0.1
prim_.data.update()
log = channel_box_log()
check("Mesh edited: inputs no longer apply" in [r._kw.get("text") for r in log if r._kind == "label"]
      and any(r._kind == "operator" and r._args[0] == "m3d.delete_history" for r in log), "Channel Box: frozen note and Delete History")
check_calls("channel box frozen", log)
bpy.data.objects.remove(prim_)
R._select_only(bpy.context, cube_)

# --- Tween math: keys at 1 (0) and 11 (10), 0.25 at frame 6 sets 2.5 and keys it
scn.frame_set(6)
items = A.collect_tween(bpy.context)
check(len(items) == 1 and (items[0].a, items[0].b) == (0.0, 10.0), "tween finds the neighbour keys: %s" % (items,))
check(bpy.ops.m3d.tween(factor=0.25) == {'FINISHED'}, "Tween runs")
check(abs(cube_.location.x - 2.5) < 1e-5, "tween 0.25 sets 2.5 (is %s)" % cube_.location.x)
fc_ = next(f for f in A.channel_fcurves(cube_) if f.array_index == 0)
key_ = [k for k in fc_.keyframe_points if k.co.x == 6]
check(key_ and abs(key_[0].co.y - 2.5) < 1e-5 and key_[0].type == 'BREAKDOWN', "...and inserts a breakdown key there")
check(len(fc_.keyframe_points) == 3, "...as a third key")
scn.frame_set(1)
check(bpy.ops.m3d.tween(factor=0.5) == {'CANCELLED'}, "no key before this frame: nothing to tween")
scn.frame_set(8)
cube_.location.x = 99
scn.m3d_anim.tween = 0.75   # The dock slider moves the selection live...
it_ = A.collect_tween(bpy.context)[0]
check(abs(cube_.location.x - (it_.a * 0.25 + it_.b * 0.75)) < 1e-5 and len(fc_.keyframe_points) == 3, "the dock slider previews without keying")
bpy.ops.m3d.anim_revert()
check(abs(cube_.location.x - fc_.evaluate(8)) < 1e-5, "Revert puts the keys' value back")
scn.m3d_anim.tween = 0.75
check(bpy.ops.m3d.tween(from_dock=True) == {'FINISHED'} and len(fc_.keyframe_points) == 4 and [k for k in fc_.keyframe_points if k.co.x == 8],
      "Key on the dock keys the slider's tween")
# Cancel: values go back (what the modal tween does on Esc; the window test drives the real thing)
scn.frame_set(3)
before = cube_.location.x
items = A.collect_tween(bpy.context)
originals = [A.get_channel(i.id, i.path, i.index) for i in items]
A.apply_tween(items, 0.9)
check(abs(cube_.location.x - before) > 1e-3, "the tween moved the object while dragging")
for i, v in zip(items, originals):
    A.set_channel(i.id, i.path, i.index, v)
check(abs(cube_.location.x - before) < 1e-6 and len(fc_.keyframe_points) == 4, "cancelling restores the value and keys nothing")

# Tween on bones: only the selected bone, its own channels
bpy.ops.m3d.rig_mode(mode='POSE')
for pb_ in rig_a.pose.bones:
    pb_.select = pb_.name == "Arm"
scn.frame_set(6)
root_x = root_pb.location.x
check(bpy.ops.m3d.tween(factor=0.25) == {'FINISHED'}, "Tween on a bone")
check(abs(arm_pb.location.x - 2.5) < 1e-5 and abs(arm_pb.rotation_euler.y - 0.25) < 1e-5,
      "...every keyed channel of the bone: %s %s" % (arm_pb.location.x, arm_pb.rotation_euler.y))
check(abs(root_pb.location.x - root_x) < 1e-6 and not any(k.co.x == 6 for f in A.channel_fcurves(rig_a)
      if f.data_path == 'pose.bones["Root"].location' for k in f.keyframe_points), "...the other bone is left alone")
check(abs(A.get_channel(rig_a, 'pose.bones["Arm"]["IK_FK"]', 0) - 0.5) < 1e-6, "custom property paths read")
A.set_channel(rig_a, 'pose.bones["Arm"]["IK_FK"]', 0, 0.75)
check(abs(arm_pb["IK_FK"] - 0.75) < 1e-6, "...and write")

# --- Euler filter and key range
cube_.rotation_euler.z = 0.0
cube_.keyframe_insert("rotation_euler", index=2, frame=1)
cube_.rotation_euler.z = 6.0
cube_.keyframe_insert("rotation_euler", index=2, frame=11)
bpy.ops.m3d.rig_mode(mode='OBJECT')
R._select_only(bpy.context, cube_)
check(bpy.ops.m3d.anim_euler_filter() == {'FINISHED'}, "Euler filter runs")
rz = next(f for f in A.channel_fcurves(cube_) if f.data_path == "rotation_euler" and f.array_index == 2)
check(abs(rz.keyframe_points[1].co.y - (6.0 - math.tau)) < 1e-5, "...a 6 radian jump becomes the short way round: %s" % rz.keyframe_points[1].co.y)
check(A.key_range(bpy.context) == (1, 11), "key range of the selection: %s" % (A.key_range(bpy.context),))
bpy.ops.m3d.anim_range(kind='KEYS')
check(scn.use_preview_range and (scn.frame_preview_start, scn.frame_preview_end) == (1, 11), "Preview range from the keys")
bpy.ops.m3d.anim_range(kind='SCENE')
check(not scn.use_preview_range, "Scene Range turns the preview range off")
check(A.playblast_frames(scn) == (scn.frame_start, scn.frame_end), "playblast frames follow the scene range")
scn.use_preview_range = True
check(A.playblast_frames(scn) == (scn.frame_preview_start, scn.frame_preview_end), "...or the preview range")
scn.use_preview_range = False

# --- Breakdown key keeps the key type setting
ts = scn.tool_settings
ts.keyframe_type = 'KEYFRAME'
scn.frame_set(4)
try:
    bpy.ops.m3d.anim_key_type(key_type='BREAKDOWN')   # (the key itself needs a window: gui_test.py)
except RuntimeError:
    pass
check(ts.keyframe_type == 'KEYFRAME', "Breakdown key leaves the key type setting alone")
fx_ = next(f for f in A.channel_fcurves(cube_) if f.data_path == "location" and f.array_index == 0)

# --- Object selection sets round trip
others = []
for n_ in range(2):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(n_ * 3 + 3, 0, 0))
    others.append(bpy.context.active_object)
a_s = scn.m3d_anim
for ob_ in bpy.context.view_layer.objects:
    ob_.select_set(ob_ in others)
check(bpy.ops.m3d.anim_set(action='ADD') == {'FINISHED'} and len(a_s.sets) == 1 and set(A.set_objects(a_s.sets[0])) == set(others), "Add a set from the selection")
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.m3d.anim_set(action='SELECT')
check(all(o.select_get() for o in others) and not cube_.select_get(), "Select selects the set")
bpy.ops.m3d.anim_set(action='DESELECT')
check(not any(o.select_get() for o in others), "Deselect")
cube_.select_set(True)
bpy.ops.m3d.anim_set(action='ASSIGN')
check(cube_ in A.set_objects(a_s.sets[0]) and len(a_s.sets[0].items) == 3, "Assign adds the selected objects once")
bpy.ops.m3d.anim_set(action='ASSIGN')
check(len(a_s.sets[0].items) == 3, "...no doubles")
bpy.ops.m3d.anim_set(action='UNASSIGN')
check(cube_ not in A.set_objects(a_s.sets[0]), "Unassign takes the selected objects out")
bpy.ops.m3d.anim_set(action='ADD')
check(len(a_s.sets) == 2 and a_s.set_index == 1, "a second set")
bpy.ops.m3d.anim_set(action='SELECT', index=0, extend=True)
check(cube_.select_get() and all(o.select_get() for o in others), "Select with extend keeps the selection")
bpy.data.objects.remove(others[1])
check(A.set_objects(a_s.sets[0]) == [others[0]], "a deleted object drops out of its set")
bpy.ops.m3d.anim_set(action='REMOVE', index=0)
check(len(a_s.sets) == 1 and bpy.ops.m3d.anim_set(action='SELECT', index=5) == {'CANCELLED'}, "Remove a set; a missing one cancels")
bpy.ops.m3d.anim_set(action='REMOVE')
bpy.data.objects.remove(others[0])
# Bone collection picker
bpy.ops.m3d.rig_mode(mode='POSE')
coll_ = rig_a.data.collections.new("Arms")
coll_.assign(rig_a.data.bones["Arm"])
for pb_ in rig_a.pose.bones:
    pb_.select = pb_.name == "Root"
check(bpy.ops.m3d.anim_pick_bones(collection="Arms") == {'FINISHED'} and arm_pb.select and not root_pb.select,
      "Bone collection picker selects its bones")
root_pb.select = True
bpy.ops.m3d.anim_pick_bones(collection="Arms", extend=True)
check(arm_pb.select and root_pb.select, "(extend keeps the others)")
bpy.ops.m3d.rig_mode(mode='OBJECT')
check(bpy.ops.m3d.anim_pick_bones.poll() is False, "...only in Pose Mode")

# --- Blocking / Polish and the new key buttons keep the user's preferences safe
edit_ = bpy.context.preferences.edit
mine = (edit_.keyframe_new_interpolation_type, edit_.keyframe_new_handle_type)
check(not A._prefs_before, "nothing remembered before the first change")
R._select_only(bpy.context, cube_)
bpy.ops.m3d.anim_preset(preset='BLOCKING')
check(edit_.keyframe_new_interpolation_type == 'CONSTANT' and A.new_key_kind(bpy.context) == 'STEPPED', "Blocking: new keys are stepped")
check(all(k.interpolation == 'CONSTANT' for f in A.channel_fcurves(cube_) for k in f.keyframe_points), "...and the selection's keys")
bpy.ops.m3d.anim_preset(preset='POLISH')
check((edit_.keyframe_new_interpolation_type, edit_.keyframe_new_handle_type) == ('BEZIER', 'AUTO_CLAMPED') and A.new_key_kind(bpy.context) == 'CLAMPED',
      "Polish: new keys are clamped splines")
check(all(k.interpolation == 'BEZIER' and k.handle_left_type == 'AUTO_CLAMPED' for f in A.channel_fcurves(cube_) for k in f.keyframe_points),
      "...and the selection's keys")
bpy.ops.m3d.anim_interp(kind='SPLINE')
check((edit_.keyframe_new_interpolation_type, edit_.keyframe_new_handle_type) == ('BEZIER', 'AUTO') and A.new_key_kind(bpy.context) == 'SPLINE', "Spline button")
bpy.ops.m3d.anim_interp(kind='LINEAR')
check(edit_.keyframe_new_interpolation_type == 'LINEAR' and A.new_key_kind(bpy.context) == 'LINEAR', "Linear button")
bpy.ops.m3d.anim_preset(preset='RESTORE')
check((edit_.keyframe_new_interpolation_type, edit_.keyframe_new_handle_type) == mine and not A._prefs_before, "Restore gives back the user's own defaults: %s" % (mine,))
check(bpy.ops.m3d.anim_preset(preset='RESTORE') == {'FINISHED'} and (edit_.keyframe_new_interpolation_type, edit_.keyframe_new_handle_type) == mine,
      "...and a second Restore changes nothing")
check(A.show_editor(None, 'GRAPH') is False and A.bottom_area(None) is None, "the editor switch copes with a screen without the editor")
check(A.bottom_area(NS(areas=[NS(type='DOPESHEET_EDITOR', spaces=NS(active=NS(mode='TIMELINE')), width=9, height=9),
                              NS(type='GRAPH_EDITOR', spaces=NS(active=None), width=2, height=2)])).type == 'GRAPH_EDITOR',
      "the bottom editor is the Graph Editor / Dope Sheet, never the Timeline")

# --- Motion paths on an object and on a bone
R._select_only(bpy.context, cube_)
check(bpy.ops.m3d.anim_paths(action='CALCULATE') == {'FINISHED'} and A.path_settings(bpy.context).has_motion_paths, "Object motion path calculated")
bpy.ops.m3d.anim_paths(action='UPDATE')
bpy.ops.m3d.anim_paths(action='CLEAR')
check(not A.path_settings(bpy.context).has_motion_paths, "...and cleared")
bpy.ops.m3d.rig_mode(mode='POSE')
for pb_ in rig_a.pose.bones:
    pb_.select = pb_.name == "Arm"
check(bpy.ops.m3d.anim_paths(action='CALCULATE') == {'FINISHED'} and A.path_settings(bpy.context).has_motion_paths, "Bone motion path calculated")
bpy.ops.m3d.anim_paths(action='CLEAR')
check(not A.path_settings(bpy.context).has_motion_paths, "...and cleared")
bpy.ops.m3d.rig_mode(mode='OBJECT')

# --- Layers (NLA): push down, additive layer, tweak, remove
R._select_only(bpy.context, cube_)
ad_ = cube_.animation_data
first_action = ad_.action
check(bpy.ops.m3d.anim_layer(action='PUSH_DOWN') == {'FINISHED'} and ad_.action is None and len(ad_.nla_tracks) == 1
      and ad_.nla_tracks[0].strips[0].action == first_action, "Push Down puts the action on an NLA track")
check(bpy.ops.m3d.anim_layer(action='PUSH_DOWN') == {'CANCELLED'}, "...nothing to push down twice")
scn.frame_set(11)
check(abs(cube_.location.x - 10) < 1e-4, "(the pushed layer still plays)")
check(bpy.ops.m3d.anim_layer(action='ADD_ADDITIVE') == {'FINISHED'} and ad_.action is not None and ad_.action_blend_type == 'ADD'
      and ad_.action.name.endswith("_Layer"), "Add Additive Layer starts an empty adding action")
scn.frame_set(5)
cube_.location.x = cube_.location.x + 2
cube_.keyframe_insert("location", index=0, frame=5)
check(len(ad_.nla_tracks) == 1 and len(A.channel_fcurves(cube_)) == 1, "...keys go on the new layer")
bpy.ops.m3d.anim_layer(action='PUSH_DOWN')
check(len(ad_.nla_tracks) == 2, "a second layer")
check(bpy.ops.m3d.anim_layer(action='TWEAK', index=0) == {'FINISHED'} and ad_.use_tweak_mode, "Edit Layer enters tweak mode")
bpy.ops.m3d.anim_layer(action='EXIT_TWEAK')
check(not ad_.use_tweak_mode, "Done Editing leaves it")
check(bpy.ops.m3d.anim_layer(action='REMOVE', index=1) == {'FINISHED'} and len(ad_.nla_tracks) == 1, "Remove Track")
check(bpy.ops.m3d.anim_layer(action='REMOVE', index=7) == {'CANCELLED'}, "a missing track cancels")
check(op_ok("nla.bake", {"frame_start": 1, "frame_end": 2, "visual_keying": True, "bake_types": {'OBJECT'}}), "Bake options exist")

# --- Playblast leaves the render settings alone
r_ = scn.render
r_.filepath = "//keep_me_"
r_.resolution_percentage = 77
r_.image_settings.file_format = 'OPEN_EXR'
r_.image_settings.color_mode = 'RGBA'
scn.frame_current = 7
snap_ = A.snapshot_render(scn)
tmp_ = tempfile.mkdtemp(prefix="m3d_pb_")
A.configure_playblast(scn, os.path.join(tmp_, "sub"), 25)
check(r_.resolution_percentage == 25 and r_.image_settings.file_format == 'PNG' and r_.image_settings.color_mode == 'RGB' and os.path.isdir(os.path.join(tmp_, "sub")),
      "Playblast settings: PNG, RGB, 25%, folder made")
scn.frame_start, scn.frame_end, scn.frame_current = 3, 4, 3
A.restore_render(scn, snap_)
check(r_.filepath == "//keep_me_" and r_.resolution_percentage == 77 and r_.image_settings.file_format == 'OPEN_EXR' and r_.image_settings.color_mode == 'RGBA'
      and scn.frame_current == 7 and (scn.frame_start, scn.frame_end) == (snap_["scene"]["frame_start"], snap_["scene"]["frame_end"]),
      "restore_render puts the output settings back")
shutil.rmtree(tmp_)
scn.m3d_anim.playblast_dir = ""
check(A.playblast_folder(scn).endswith("m3d_playblast"), "default playblast folder is a temporary one")
A.playblast_state["running"] = True
check(not bpy.ops.m3d.playblast.poll(), "no second Playblast while one runs")
A.playblast_state["running"] = False
check(A.playblast_area(NS(areas=[NS(type='VIEW_3D', width=10, height=10, spaces=NS(active=NS(region_3d=NS(view_perspective='PERSP')))),
                                 NS(type='VIEW_3D', width=5, height=5, spaces=NS(active=NS(region_3d=NS(view_perspective='CAMERA'))))])).width == 5,
      "Playblast prefers the camera view")

# --- Playback redraw limits
scr_ = NS(use_play_properties_editors=True, use_play_image_editors=True, use_play_node_editors=True, use_play_sequence_editors=True,
          use_play_clip_editors=True, use_play_spreadsheet_editors=True, use_play_3d_editors=False, use_play_animation_editors=False,
          use_play_top_left_3d_editor=False)
A.limit_playback_redraw(scr_)
check(not scr_.use_play_properties_editors and scr_.use_play_3d_editors and scr_.use_play_animation_editors and scr_.use_play_top_left_3d_editor,
      "While playing only the viewports and animation editors redraw")
for name_ in ("use_play_properties_editors", "use_play_3d_editors", "use_play_animation_editors", "use_play_top_left_3d_editor"):
    check(name_ in bpy.types.Screen.bl_rna.properties, "Screen." + name_)

# --- Pick tab with a skeleton: bone selection sets and collections show up
bpy.ops.m3d.rig_mode(mode='POSE')
bpy.ops.pose.selection_set_add_and_assign()
check({"PROPERTIES_PT_m3d_an_bone_sets", "PROPERTIES_PT_m3d_an_collections"} <= set(an_shown("anim_pick")),
      "Pick lists the skeleton's sets and collections: %s" % an_shown("anim_pick"))
check(draw_anim_panels('POSE with sets') >= 10, "Animation panels drew in Pose Mode with sets and collections")
bpy.ops.m3d.rig_mode(mode='OBJECT')

# ----------------------------------------------------------------------------------------------------
# Phase 6: Rendering workspace (tabs, pages, gates, quality presets, light table, HDRI, camera from view, IPR, keys, render).
import m3d_render as RN
import math

render_ws = bpy.data.workspaces["Rendering"]
rn_tabs = W.DOCK_TABS['RENDER']
check([t.label for t in rn_tabs['RIGHT']] == ["Camera", "Lighting", "Materials", "Render", "Output", "Passes & Layers", "Advanced"], "Rendering dock tabs")
check(rn_tabs['LEFT'] == () and W.dock_tabs('RENDER', 'LEFT') == rn_tabs['RIGHT'], "Rendering has no left tray")
for tab in rn_tabs['RIGHT']:
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("render_"), "Rendering page tab " + tab.id)
rn_pages = {t.page for t in rn_tabs['RIGHT']}
check({c.page for c in RN.classes if hasattr(c, "page")} == rn_pages, "every Rendering page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in RN.classes if not issubclass(c, bpy.types.PropertyGroup)),
      "Rendering classes registered")
check(m3d_ui.shelves_for('RENDER') == ['RENDER_LIGHTS', 'RENDER_RENDER', 'CUSTOM'] and 'RENDER' in m3d_ui.STATUS_LINES, "Rendering shelf tabs and Status Line")
check([it[3] for it in m3d_ui.SHELVES['RENDER_LIGHTS'][1] if it] == ["Point", "Spot", "Area", "Sun", "HDRI Sky", "Previous World"], "Lights shelf buttons")
check([it[3] for it in m3d_ui.SHELVES['RENDER_RENDER'][1] if it] == ["Render", "Animation", "Render View", "Camera from View", "Look Through",
                                                                  "Draft", "Medium", "Final"], "Render shelf buttons")
check(render_ws.m3d_kind == 'RENDER' and render_ws.object_mode == 'OBJECT', "Rendering workspace kind and entry mode")
rn_src = open(RN.__file__, encoding="utf-8").read()
for ic in set(re.findall(r"icon='([A-Z_0-9]+)'", rn_src)):
    check(ic in icons, "Rendering code uses a missing icon " + ic)
for word in ("maya", "autodesk", "arnold", "hypershade", "marmoset", "toolbag", "keyshot", "houdini", "solaris", "karma"):
    check(word not in rn_src.lower(), "Rendering code names " + word)

# Keys: Shift+F12 / Ctrl+Shift+F12 render, Alt+F12 shows the render; nothing else sits on them.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maelstrom3D"]
for mods, idname, props in ((dict(shift=True, ctrl=False, alt=False), "m3d.render", {"animation": False}),
                            (dict(shift=True, ctrl=True, alt=False), "m3d.render", {"animation": True}),
                            (dict(shift=False, ctrl=False, alt=True), "m3d.render_view", {})):
    item = find("Screen Editing", idname, 'F12', **mods)
    check(item and all(getattr(item[0].properties, k) == v for k, v in props.items()), "F12 %s runs %s" % (mods, idname))
    others = [(km.name, k.idname) for km in kc.keymaps for k in km.keymap_items
              if k.type == 'F12' and all(getattr(k, m) == v for m, v in mods.items()) and not k.oskey and not k.any
              and not k.idname.startswith("m3d.render")]
    check(not others, "F12 %s is free around the Rendering keys: %s" % (mods, others))
check(find("Mesh", "m3d.workspace", "F12", shift=False, ctrl=False, alt=False)[0].properties.kind == 'UV', "plain F12 is still the UV workspace")
check(find("Screen Editing", "render.render", "F12", ctrl=True, alt=True), "Ctrl+Alt+F12 is Blender's")

# A clean scene.
for ob_ in list(bpy.data.objects):
    if ob_.mode != 'OBJECT':
        bpy.context.view_layer.objects.active = ob_
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(ob_)
for coll_ in list(bpy.data.collections):
    bpy.data.collections.remove(coll_)
scn = bpy.context.scene
scn.camera = None
rn = scn.render


class RnCtx(SCtx):
    """Context of the Rendering dock: the real one with this workspace."""
    def __init__(self):
        super().__init__('RIGHT')
        self.workspace = render_ws


def rn_panels(page):
    return [c for c in RN.classes if getattr(c, "page", None) == page and hasattr(c, "poll")]


def rn_shown(page):
    render_ws.m3d_page_right = page
    ctx_ = RnCtx()
    return [c.__name__ for c in rn_panels(page) if c.poll(ctx_)]


def rn_cancelled(fn, **kw):
    """A cancelled operator call raises with its report; both count."""
    try:
        return fn(**kw) == {'CANCELLED'}
    except RuntimeError:
        return True


# --- Quality presets
check(RN.current_quality(scn) == 'CUSTOM' and scn.m3d_render.preset == 'CUSTOM', "a new scene has no preset")
want = {'DRAFT': (50, 32, 16, False, '4'), 'MEDIUM': (100, 128, 64, True, '2'), 'FINAL': (100, 512, 256, True, '1')}
saved_engine = rn.engine
for engine_ in ('BLENDER_EEVEE', 'CYCLES'):
    rn.engine = engine_
    for key_, (pct_, cy_samples_, ev_samples_, ev_rt_, ev_scale_) in want.items():
        bpy.ops.m3d.render_preset(preset=key_)
        check((rn.resolution_percentage, scn.cycles.samples, scn.eevee.taa_render_samples, scn.eevee.use_raytracing,
               scn.eevee.ray_tracing_options.resolution_scale) == (pct_, cy_samples_, ev_samples_, ev_rt_, ev_scale_),
              "%s preset values with %s" % (key_, engine_))
        check(scn.cycles.use_denoising and scn.cycles.use_adaptive_sampling, key_ + " denoises and samples adaptively")
        check(RN.current_quality(scn) == key_ and scn.m3d_render.preset == key_, "%s is the active preset (%s)" % (key_, engine_))
        for other_engine_ in ('BLENDER_EEVEE', 'CYCLES'):   # Both engines got the values: switching keeps the preset.
            rn.engine = other_engine_
            check(RN.current_quality(scn) == key_, "%s still active after switching to %s" % (key_, other_engine_))
        rn.engine = engine_
        if engine_ == 'CYCLES':
            scn.cycles.samples += 1
        else:
            scn.eevee.taa_render_samples += 1
        check(RN.current_quality(scn) == 'CUSTOM' and scn.m3d_render.preset == key_, "an edit makes %s Custom (%s)" % (key_, engine_))
        bpy.ops.m3d.render_preset(preset=key_)
        check(RN.current_quality(scn) == key_, "applying again clears Custom")
bpy.ops.m3d.render_preset(preset='MEDIUM')
rn.resolution_percentage = 75
check(RN.current_quality(scn) == 'CUSTOM', "the size is part of a preset")
bpy.ops.m3d.render_preset(preset='MEDIUM')
rn.engine = 'CYCLES'
scn.cycles.max_bounces = 3
check(RN.current_quality(scn) == 'CUSTOM', "the bounces are part of a Cycles preset")
bpy.ops.m3d.render_preset(preset='DRAFT')
rn.engine = 'BLENDER_EEVEE'
scn.eevee.use_raytracing = True
check(RN.current_quality(scn) == 'CUSTOM', "ray tracing is part of an EEVEE preset")
samples_ = [RN.PRESET_VALUES[k]['CYCLES']["cycles.samples"] for k in ('DRAFT', 'MEDIUM', 'FINAL')]
check(samples_ == sorted(samples_) and len(set(samples_)) == 3, "presets get better in order")
rn.engine = saved_engine

# --- HDRI world
world_before = scn.world
old_nodes = len(world_before.node_tree.nodes) if world_before.node_tree else 0
old_props = dict(world_before.items())
bundled = RN.bundled_hdris()
check(len(bundled) >= 4 and all(os.path.isfile(p) for _l, p in bundled), "studio HDRIs are listed: %s" % [l for l, _p in bundled])
check(RN.hdri_nodes(scn.world) is None and scn.m3d_render.hdri_strength == 1.0 and scn.m3d_render.hdri_rotation == 0.0,
      "no HDRI yet: defaults read back")
check(bpy.ops.m3d.hdri_clear.poll() is False, "Back to Previous World needs an HDRI world")
check(rn_cancelled(bpy.ops.m3d.hdri_setup, filepath="//missing_sky.exr") and scn.world == world_before, "a missing file changes nothing")
check(bpy.ops.m3d.hdri_setup() == {'FINISHED'}, "HDRI Sky with no file picks a studio HDRI")
hw = scn.world
nodes_ = RN.hdri_nodes(hw)
check(hw.name == "m3dHDRI" and nodes_ is not None, "a new world m3dHDRI is assigned")
check([nodes_[k].type for k in ("coord", "mapping", "env", "background", "output")] ==
      ['TEX_COORD', 'MAPPING', 'TEX_ENVIRONMENT', 'BACKGROUND', 'OUTPUT_WORLD'], "HDRI nodes: coordinates, mapping, environment, background, output")
links_ = {(l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name) for l in hw.node_tree.links}
check(links_ == {("M3D HDRI Coordinates", "Generated", "M3D HDRI Mapping", "Vector"), ("M3D HDRI Mapping", "Vector", "M3D HDRI Environment", "Vector"),
                 ("M3D HDRI Environment", "Color", "M3D HDRI Background", "Color"), ("M3D HDRI Background", "Background", "M3D HDRI Output", "Surface")},
      "HDRI nodes are wired: %s" % links_)
check(nodes_["env"].image is not None and os.path.samefile(bpy.path.abspath(nodes_["env"].image.filepath), RN.default_hdri()), "the environment uses the studio image")
check(scn.m3d_render.previous_world == world_before and world_before.name in bpy.data.worlds and world_before.users >= 1, "the old world is kept")
check((len(world_before.node_tree.nodes) if world_before.node_tree else 0) == old_nodes and dict(world_before.items()) == old_props, "...untouched")
scn.m3d_render.hdri_rotation, scn.m3d_render.hdri_strength = 1.0, 2.5
check(abs(nodes_["mapping"].inputs["Rotation"].default_value[2] - 1.0) < 1e-5 and abs(nodes_["background"].inputs["Strength"].default_value - 2.5) < 1e-5
      and abs(scn.m3d_render.hdri_rotation - 1.0) < 1e-5 and abs(scn.m3d_render.hdri_strength - 2.5) < 1e-5, "rotation and strength write the nodes")
other_hdri_ = next(p for _l, p in bundled if os.path.basename(p) != os.path.basename(RN.default_hdri()))
check(bpy.ops.m3d.hdri_setup(filepath=other_hdri_) == {'FINISHED'} and scn.world.name == "m3dHDRI" and len(bpy.data.worlds) == 2, "another image reuses the HDRI world")
check(os.path.basename(RN.hdri_nodes(scn.world)["env"].image.filepath) == os.path.basename(other_hdri_), "...with the new image")
check(abs(scn.m3d_render.hdri_rotation - 1.0) < 1e-5 and abs(scn.m3d_render.hdri_strength - 2.5) < 1e-5, "...and the same rotation and strength")
check(scn.m3d_render.previous_world == world_before, "the kept world is still the first one")
check(scn.m3d_render.hdri_path.endswith(os.path.basename(other_hdri_)), "the picked file is remembered")
check(bpy.ops.m3d.hdri_clear() == {'FINISHED'} and scn.world == world_before and RN.hdri_nodes(scn.world) is None
      and scn.m3d_render.previous_world is None, "Back to Previous World")
scn.world = None
bpy.ops.m3d.hdri_setup()
check(scn.m3d_render.previous_world is None and bpy.ops.m3d.hdri_clear() == {'FINISHED'} and scn.world is None, "a scene without a world goes back to none")
scn.world = world_before

# --- Lights: shelf operator, light table rows
for kind_, label_, _icon in RN.LIGHT_TYPES:
    bpy.ops.m3d.render_light_add(kind=kind_)
    ob_ = bpy.context.active_object
    check(ob_.type == 'LIGHT' and ob_.data.type == kind_ and ob_.location.z > 3.5, "%s light added above the cursor" % kind_)
check(bpy.context.active_object.rotation_euler.x > 0.5, "the sun is tilted")
lights_ = RN.scene_lights(scn)
check(len(lights_) == 4 and [o.name.lower() for o in lights_] == sorted(o.name.lower() for o in lights_), "four lights listed")
point_ = next(o for o in lights_ if o.data.type == 'POINT')
spot_ = next(o for o in lights_ if o.data.type == 'SPOT')
# a light in a hidden collection, one in an excluded collection, and two objects sharing one light
hid_coll = bpy.data.collections.new("HiddenLights")
exc_coll = bpy.data.collections.new("ExcludedLights")
scn.collection.children.link(hid_coll)
scn.collection.children.link(exc_coll)
hid_light = bpy.data.objects.new("HiddenLamp", bpy.data.lights.new("HiddenLamp", 'POINT'))
exc_light = bpy.data.objects.new("ExcludedLamp", bpy.data.lights.new("ExcludedLamp", 'AREA'))
hid_coll.objects.link(hid_light)
exc_coll.objects.link(exc_light)
twin_ = bpy.data.objects.new("TwinLamp", point_.data)
scn.collection.objects.link(twin_)
layer_ = bpy.context.view_layer
layer_.layer_collection.children["HiddenLights"].hide_viewport = True
layer_.layer_collection.children["ExcludedLights"].exclude = True
names_ = [o.name for o in RN.scene_lights(scn)]
check({"HiddenLamp", "ExcludedLamp", "TwinLamp"} <= set(names_) and len(names_) == 7, "the table lists hidden, excluded and shared lights: %s" % names_)
check(RN.light_state(layer_, hid_light) == 'HIDDEN' and RN.light_state(layer_, exc_light) == 'EXCLUDED' and RN.light_state(layer_, point_) == 'OK',
      "light states: %s %s %s" % (RN.light_state(layer_, hid_light), RN.light_state(layer_, exc_light), RN.light_state(layer_, point_)))
check(point_.data.users == 2 and twin_.data is point_.data, "the twin shares the light data")
log_ = []
rn_ctx = RnCtx()
render_ws.m3d_page_right = "render_lighting"
for cls_ in rn_panels("render_lighting"):
    if cls_.poll(rn_ctx):
        try:
            log_.extend(draw_stub(cls_, rn_ctx))
        except Exception as err:
            check(False, "%s draw: %r" % (cls_.__name__, err))
check_calls_ext("Lighting page", log_)
row_ops_ = [(r.values().get("name"), r.values().get("action")) for r in log_ if r._kind == "operator" and r._args[0] == "m3d.render_light"]
check({(n, a) for n, a in row_ops_ if a == 'VISIBLE'} == {(o.name, 'VISIBLE') for o in RN.scene_lights(scn)}, "every light has an eye button")
check({n for n, a in row_ops_ if a == 'SINGLE'} == {point_.name, twin_.name}, "only the lights sharing data say so: %s" % [n for n, a in row_ops_ if a == 'SINGLE'])
shared_text_ = [r._kw.get("text") for r in log_ if r._kind == "operator" and r.values().get("action") == 'SINGLE']
check(shared_text_ == ["x2", "x2"], "the shared rows read x2: %s" % shared_text_)
check({r._args[1] for r in log_ if r._kind == "prop"} >= {"hide_render", "name", "color", "energy", "use_shadow"}, "rows edit render visibility, name, color, power, shadow")
check(any(r._kind == "label" and "Greyed" in str(r._kw.get("text", "")) for r in log_), "the table explains greyed rows")
# the row buttons
check(bpy.ops.m3d.render_light(name=point_.name, action='VISIBLE') == {'FINISHED'} and point_.hide_get(), "the eye hides a light")
check(RN.light_state(layer_, point_) == 'HIDDEN', "...and the table sees it")
check(bpy.ops.m3d.render_light(name=point_.name, action='VISIBLE') == {'FINISHED'} and RN.light_state(layer_, point_) == 'OK', "...and shows it again")
point_.hide_viewport = True
check(RN.light_state(layer_, point_) == 'HIDDEN', "a light disabled in viewports reads hidden")
bpy.ops.m3d.render_light(name=point_.name, action='VISIBLE')
check(not point_.hide_viewport and RN.light_state(layer_, point_) == 'OK', "...the eye enables it")
check(rn_cancelled(bpy.ops.m3d.render_light, name=exc_light.name, action='VISIBLE') and rn_cancelled(bpy.ops.m3d.render_light, name=exc_light.name, action='SELECT'),
      "a light in an excluded collection cannot be shown or selected from the table")
check(rn_cancelled(bpy.ops.m3d.render_light, name=hid_light.name, action='SELECT'), "a hidden light is not selected")
check(bpy.ops.m3d.render_light(name=spot_.name, action='SELECT') == {'FINISHED'} and spot_.select_get() and bpy.context.active_object == spot_
      and not point_.select_get(), "Select makes the light the selection")
old_data_ = point_.data
check(bpy.ops.m3d.render_light(name=twin_.name, action='SINGLE') == {'FINISHED'} and twin_.data is not old_data_ and twin_.data.users == 1
      and point_.data.users == 1, "Make Single User gives the twin its own light")
check(point_.data.color[:] == twin_.data.color[:], "...with the same settings")
spot_.data.energy = 321.0
spot_.data.use_shadow = False
check(spot_.data.energy == 321.0 and not spot_.data.use_shadow, "light edits stick")
for ob_ in (hid_light, exc_light, twin_):
    bpy.data.objects.remove(ob_)
for coll_ in (hid_coll, exc_coll):
    bpy.data.collections.remove(coll_)

# --- Camera from view, IPR
space_ = RN.viewport(bpy.context)
check(space_ is not None and space_.region_3d is not None, "the test screen has a 3D view")
scn.camera = None
check(bpy.ops.m3d.render_camera_from_view(mode='NEW') == {'FINISHED'} and scn.camera is not None and scn.camera.type == 'CAMERA'
      and scn.camera == bpy.context.active_object and scn.camera.select_get(), "New Camera from View adds and selects a scene camera")
mat_ = space_.region_3d.view_matrix.inverted()
check(all(abs(a - b) < 1e-4 for ra, rb in zip(scn.camera.matrix_world, mat_) for a, b in zip(ra, rb)), "...at the view")
check(abs(scn.camera.data.lens - space_.lens / 2) < 1e-4, "...with the viewport's field of view (%s)" % scn.camera.data.lens)
first_cam_ = scn.camera
bpy.ops.m3d.render_camera_from_view(mode='NEW')
check(scn.camera != first_cam_ and len([o for o in scn.objects if o.type == 'CAMERA']) == 2, "another New Camera from View adds another")
scn.camera = first_cam_
check(bpy.ops.m3d.render_camera_from_view(mode='MATCH') == {'FINISHED'} and scn.camera == first_cam_, "Match Camera to View keeps the scene camera")
check(len([o for o in scn.objects if o.type == 'CAMERA']) == 2, "...and adds none")
space_.region_3d.view_perspective = 'CAMERA'
check(rn_cancelled(bpy.ops.m3d.render_camera_from_view, mode='MATCH'), "looking through the camera there is nothing to match")
bpy.ops.m3d.render_camera_from_view(mode='NEW')
check(len([o for o in scn.objects if o.type == 'CAMERA']) == 3, "a new camera from the camera view copies the camera")
space_.region_3d.view_perspective = 'PERSP'
for ob_ in [o for o in scn.objects if o.type == 'CAMERA']:
    bpy.data.objects.remove(ob_)
scn.camera = None
check(bpy.ops.m3d.render_camera_from_view(mode='MATCH') == {'FINISHED'} and scn.camera is not None, "Match without a scene camera adds one")

shading_ = space_.shading.type
space_.shading.type = 'MATERIAL'
bpy.ops.m3d.render_ipr()
check(space_.shading.type == 'RENDERED', "IPR turns the Rendered viewport on")
bpy.ops.m3d.render_ipr()
check(space_.shading.type == 'MATERIAL' and not RN._ipr_before, "...and back to the shading it had")
space_.shading.type = 'SOLID'
bpy.ops.m3d.render_ipr()
bpy.ops.m3d.render_ipr()
check(space_.shading.type == 'SOLID', "...whichever that was")
space_.shading.type = shading_

# --- Materials: principled inputs, normal strength, gate
bpy.ops.mesh.primitive_cube_add(size=1)
cube_rn = bpy.context.active_object
mat_rn = bpy.data.materials.new("RnMat")
mat_rn.use_nodes = True
cube_rn.data.materials.append(mat_rn)
bsdf_ = RN.principled(mat_rn)
check(bsdf_ is not None and bsdf_.type == 'BSDF_PRINCIPLED' and RN.normal_strength_node(bsdf_) is None, "the material's Principled shader is found")
nm_ = mat_rn.node_tree.nodes.new('ShaderNodeNormalMap')
mat_rn.node_tree.links.new(nm_.outputs["Normal"], bsdf_.inputs["Normal"])
check(RN.normal_strength_node(bsdf_) == nm_, "...and a Normal Map plugged into it")
bare_ = bpy.data.materials.new("NoShader")
bare_.node_tree.nodes.clear()
check(RN.principled(None) is None and RN.principled(bare_) is None, "no material or no Principled node: nothing to show")


# --- Every page draws
def rn_draw_all(label):
    drawn = 0
    for page in rn_pages:
        render_ws.m3d_page_right = page
        ctx_ = RnCtx()
        for cls_ in rn_panels(page):
            if not cls_.poll(ctx_):
                continue
            drawn += 1
            try:
                check_calls_ext("%s %s" % (label, cls_.__name__), draw_stub(cls_, ctx_))
                if hasattr(cls_, "draw_header"):
                    head_log_ = []
                    inst_ = type("Inst", (), {})()
                    inst_.layout = Rec(head_log_)
                    cls_.draw_header(inst_, ctx_)
                    check_calls_ext("%s %s header" % (label, cls_.__name__), head_log_)
            except Exception as err:
                check(False, "%s %s draw: %r" % (label, cls_.__name__, err))
    log_ = []
    RN.draw_status_line(Rec(log_), RnCtx())
    check_calls_ext(label + " status line", log_)
    for key_ in ('RENDER_LIGHTS', 'RENDER_RENDER', 'CUSTOM'):
        log_ = []
        bpy.context.window_manager.m3d_shelf = key_
        m3d_ui.draw_shelf(Rec(log_), RnCtx())
        check_calls_ext("shelf %s in %s" % (key_, label), log_)
    return drawn


check([c.__name__ for c in RN.PAGE_GATES] == ["PROPERTIES_PT_m3d_rn_materials_gate"], "Materials is the page with a gate")
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = None
check(rn_shown("render_materials") == ["PROPERTIES_PT_m3d_rn_materials_gate"], "Materials without an object shows its message only: %s" % rn_shown("render_materials"))
bpy.context.view_layer.objects.active = spot_
check(rn_shown("render_materials") == ["PROPERTIES_PT_m3d_rn_materials_gate"], "...and for a light")
bpy.context.view_layer.objects.active = cube_rn
cube_rn.select_set(True)
check(rn_shown("render_materials") == ["PROPERTIES_PT_m3d_rn_slots", "PROPERTIES_PT_m3d_rn_surface"], "Materials with a mesh: %s" % rn_shown("render_materials"))
for page_ in rn_pages - {"render_materials"}:
    check(not any(n.endswith("_gate") for n in rn_shown(page_)) and rn_shown(page_), "%s needs no object: %s" % (page_, rn_shown(page_)))
log_ = []
render_ws.m3d_page_right = "render_materials"
for cls_ in rn_panels("render_materials"):
    log_.extend(draw_stub(cls_, RnCtx()))
check(sum(1 for r in log_ if r._kind == "prop" and r._args[1] == "default_value") == 6,
      "Surface shows base color, metallic, roughness, emission color / strength, normal strength")
check(any(r._kind == "operator" and r._args[0] == "wm.context_set_id" and r.values().get("value") == "Shading" for r in log_), "Materials links to the Shading workspace")

for engine_ in ('BLENDER_EEVEE', 'CYCLES'):
    rn.engine = engine_
    for mode_ in ('cube', 'light', 'none'):
        bpy.context.view_layer.objects.active = {'cube': cube_rn, 'light': spot_, 'none': None}[mode_]
        n_ = rn_draw_all("%s %s" % (engine_, mode_))
        check(n_ >= 20, "Rendering panels drew with %s / %s (%d)" % (engine_, mode_, n_))
bpy.context.view_layer.objects.active = cube_rn
rn.engine = 'BLENDER_WORKBENCH'
check(rn_draw_all("workbench") >= 15, "Rendering panels draw with the Workbench engine")
rn.engine = 'BLENDER_EEVEE'
log_ = []
RN.draw_status_line(Rec(log_), RnCtx())
check({r.values().get("preset") for r in log_ if r._kind == "operator" and r._args[0] == "m3d.render_preset"} == {'DRAFT', 'MEDIUM', 'FINAL'}
      and [r._kw.get("text") for r in log_ if r._kind == "operator" and r._args[0] == "m3d.render"] == ["Render", "Render Animation"]
      and {r._args[0] for r in log_ if r._kind == "operator"} >= {"m3d.render_ipr", "m3d.render_view"}, "Status Line: presets, Render, Render Animation, IPR, Render View")
check({r._args[2] for r in log_ if r._kind == "prop_enum"} == {'CYCLES', 'BLENDER_EEVEE'} and any(r._kind == "prop" and r._args[1] == "camera" for r in log_),
      "Status Line: engine and camera picker")
bpy.ops.m3d.render_preset(preset='FINAL')
log_ = []
RN.draw_status_line(Rec(log_), RnCtx())
check(not any(r._kind == "label" and r._kw.get("text") == "Custom" for r in log_), "no Custom label while a preset is active")
scn.eevee.taa_render_samples += 5
log_ = []
RN.draw_status_line(Rec(log_), RnCtx())
check(any(r._kind == "label" and r._kw.get("text") == "Custom" for r in log_), "Custom label after an edit")
for ob_ in list(bpy.data.objects):
    if ob_ != cube_rn:
        bpy.data.objects.remove(ob_)

# --- Render View: the Render Result shows in the workspace's Image Editor
area_ = RN.render_view_area(render_ws.screens[0])
check(area_ is not None and area_.type == 'IMAGE_EDITOR', "the Rendering screen has a Render View")
fake_ = NS(workspace=render_ws, screen=render_ws.screens[0])
other_ws_ = NS(workspace=bpy.data.workspaces["Modeling"], screen=render_ws.screens[0])


# --- Render at 32 x 32, one sample: works for both engines and leaves every setting as it was
def rn_snapshot():
    return {"engine": rn.engine, "x": rn.resolution_x, "y": rn.resolution_y, "pct": rn.resolution_percentage, "path": rn.filepath,
            "fmt": rn.image_settings.file_format, "cy": scn.cycles.samples, "ev": scn.eevee.taa_render_samples, "frame": scn.frame_current,
            "camera": scn.camera, "world": scn.world, "preset": scn.m3d_render.preset, "quality": RN.current_quality(scn),
            "start": scn.frame_start, "end": scn.frame_end, "view": space_.shading.type, "lights": len(RN.scene_lights(scn)),
            "exposure": scn.view_settings.exposure, "bounces": scn.cycles.max_bounces, "denoise": scn.cycles.use_denoising}


bpy.ops.object.camera_add(location=(0, -4, 1), rotation=(math.radians(80), 0, 0))
scn.camera = bpy.context.active_object
rn.resolution_x = rn.resolution_y = 32
rn.resolution_percentage = 100
scn.cycles.samples = scn.eevee.taa_render_samples = 1
scn.cycles.device = 'CPU'
for engine_ in ('CYCLES', 'BLENDER_EEVEE'):
    rn.engine = engine_
    snap_ = rn_snapshot()
    check(bpy.ops.m3d.render() == {'FINISHED'}, "Render (%s, 32 x 32, 1 sample) works" % engine_)
    check(rn_snapshot() == snap_, "...and changes none of the settings (%s)" % engine_)
check(any(i.type == 'RENDER_RESULT' for i in bpy.data.images), "a Render Result exists after a render")
area_.spaces.active.image = None
check(RN.show_render_result(fake_) and area_.spaces.active.image is not None and area_.spaces.active.image.type == 'RENDER_RESULT',
      "Render View points the Rendering workspace's Image Editor at the Render Result")
area_.spaces.active.image = None
check(not RN.show_render_result(other_ws_) and area_.spaces.active.image is None, "...but only in the Rendering workspace")
rn.engine = saved_engine

# The Attribute Editor / All Settings tab with nothing active: the Object tab isn't there, the Scene settings show.
import m3d_mode as _mm


class _Space:
    """A Properties editor stand-in whose Object tab is missing (no active object)."""
    def __init__(self):
        self._ctx = 'CHANNEL_BOX'

    @property
    def context(self):
        return self._ctx

    @context.setter
    def context(self, value):
        if value == 'OBJECT':
            raise TypeError('enum "OBJECT" not found')
        self._ctx = value


_s = _Space()
check(_mm.set_dock_context(_s, 'OBJECT') == 'SCENE' and _s.context == 'SCENE', "All Settings with nothing active")
check(_mm.set_dock_context(_s, 'TOOL') == 'TOOL', "dock tab switch")

# Dock tab overflow: as many tabs as fit, the rest in the "more" menu, the active tab always drawn.
_tw = lambda label: len(label) * 10   # a button is 10 px per character
_t = [W.Tab(c, c * 5, 'TOOL', None, c * 2) for c in "abcd"]   # labels of 5 px chars, short labels of 2
check(W.Tab("x", "X", 'TOOL', None).short_label == "", "Tab short_label defaults to none")
check(W.fit_tabs(_t, 'a', 200, _tw, 20) == ([(t, t.label) for t in _t], []), "all tabs fit")
_shown, _more = W.fit_tabs(_t, 'a', 160, _tw, 20)   # 4 x 50 = 200 full, 4 x 20 = 80 short: short labels fit
check([l for _x, l in _shown] == ["aa", "bb", "cc", "dd"] and _more == [], "short labels when the full ones don't fit")
_t = [W.Tab(c, c * 5, 'TOOL', None) for c in "abcd"]       # no short labels: 4 x 50
_shown, _more = W.fit_tabs(_t, 'a', 130, _tw, 20)          # room for 2 next to the more button
check([x.id for x, _l in _shown] == ["a", "b"] and [x.id for x in _more] == ["c", "d"], "some tabs overflow")
_shown, _more = W.fit_tabs(_t, 'd', 130, _tw, 20)          # the active tab takes the last visible place
check([x.id for x, _l in _shown] == ["a", "d"] and [x.id for x in _more] == ["b", "c"], "active tab in the overflow is drawn")
_shown, _more = W.fit_tabs(_t, 'd', 70, _tw, 20)           # room for one
check([x.id for x, _l in _shown] == ["d"] and [x.id for x in _more] == ["a", "b", "c"], "very narrow: the active tab only")
_shown, _more = W.fit_tabs(_t, 'd', 0, _tw, 20)
check([x.id for x, _l in _shown] == ["d"], "no room at all: the active tab is still drawn")
_shown, _more = W.fit_tabs(_t, None, 0, _tw, 20)
check(_shown == [] and len(_more) == 4, "no active tab, no room: everything in the menu")
_shown, _more = W.fit_tabs(_t, 'b', 130, _tw, 20)
check([x.id for x, _l in _shown] == ["a", "b"], "active tab already drawn keeps the order")
check(all(t.short_label for k in W.KINDS for s in W.DOCK_TABS[k].values() for t in s if len(t.label) > 12),
      "long dock tab labels have a short label")
check(W.all_tab('MODEL').label == "Attribute Editor" and W.all_tab('SCULPT').short_label == "Settings", "All Settings tab")

# Workspace Settings (the popover next to the workspace picker): draws for every kind and for extra workspaces,
# its operators and properties exist, tab toggles / entry mode / hidden tabs work from there.
class WsCtx:
    def __init__(self, ws):
        self.workspace, self.window_manager = ws, bpy.context.window_manager
        self.window = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None


def ws_settings_log(ws):
    log = []
    W.M3D_PT_workspace_settings.draw(type("Inst", (), {"layout": Rec(log)})(), WsCtx(ws))
    check_calls("workspace settings " + ws.name, log)
    return log


def ws_ops(log):
    return [(r._args[0], r.values(), r._kw) for r in log if r._kind == "operator"]


log = []
m3d_ui.draw_workspace_picker(Rec(log), WsCtx(bpy.data.workspaces[0]))
check(any(r._kind == "popover" and r._args[0] == "M3D_PT_workspace_settings" for r in log), "Status Line has the Workspace Settings popover")
check(hasattr(W.M3D_OT_workspace_reset, "invoke"), "Reset Workspace asks for confirmation")
check(hasattr(bpy.types, "M3D_PT_workspace_settings"), "settings panel registered")
for kind_, (wname_, *_rest) in W.KINDS.items():
    ws_ = W.find_workspace(kind_)
    check(ws_ is not None, "workspace for " + kind_)
    ops_ = ws_ops(ws_settings_log(ws_))
    names_ = [o[0] for o in ops_]
    check("m3d.workspace_reset" in names_ and "wm.save_homefile" in names_, "%s settings: reset and save as default" % kind_)
    check(any(o[0] == "screen.userpref_show" and o[1].get("section") == 'KEYMAP' for o in ops_), "%s settings: keyboard shortcuts" % kind_)
    shown_ = [o[1]["tab"] for o in ops_ if o[0] == "m3d.dock_tab_toggle"]
    want_ = [t.id for t in W.DOCK_TABS[kind_]['RIGHT'] + W.DOCK_TABS[kind_]['LEFT']]
    check(shown_ == want_, "%s settings: a toggle per dock tab (%s)" % (kind_, shown_))
    log = []
    W.M3D_PT_workspace_settings.draw(type("Inst", (), {"layout": Rec(log)})(), WsCtx(ws_))
    props_ = {(r._args[0], r._args[1]) for r in log if r._kind == "prop"}
    check((ws_, "object_mode") in props_, "%s settings: entry mode" % kind_)
    edit_ = [o for o in ws_ops(log) if o[0] == "m3d.edit_mode"]
    check(len(edit_) == 1 and edit_[0][2].get("text") == "Click to Edit" and not edit_[0][2].get("depress"),
          "%s settings: Click to Edit toggle: %s" % (kind_, edit_))
    check("m3d.dock_layout_reset" in [o[0] for o in ws_ops(log)], "%s settings: Reset Dock Layout" % kind_)
    check((ws_, "m3d_show_shelf") in props_, "%s settings: Show Shelf" % kind_)
    # Entry mode sticks.
    old_ = ws_.object_mode
    ws_.object_mode = 'EDIT' if old_ != 'EDIT' else 'OBJECT'
    check(ws_.object_mode != old_, "%s entry mode changes" % kind_)
    ws_.object_mode = old_
shading_ = bpy.data.workspaces.get("Shading")
check(shading_ is not None and W.workspace_kind(shading_) is None, "Shading is an extra workspace")
ops_ = ws_ops(ws_settings_log(shading_))
check("m3d.workspace_reset" in [o[0] for o in ops_] and not any(o[0] == "m3d.dock_tab_toggle" for o in ops_), "extra workspace: reset, no dock tabs")

# Show Shelf: on in every workspace of the factory startup but Sculpt (the top bar then has two rows).
for ws_ in bpy.data.workspaces:
    want_ = W.workspace_kind(ws_) != 'SCULPT'
    check(ws_.m3d_show_shelf == want_, "%s: Show Shelf defaults to %s" % (ws_.name, want_))

# Brush tiles: every brush of the tray grids has a thumbnail (icon ids are 0 without a GPU, so look at the previews
# the lookup built), the library file gains no data, and the grid draws one tile per brush with the brush as tooltip.
data_before_ = (len(bpy.data.brushes), len(bpy.data.libraries))
for asset_, brushes_ in ((S.BRUSH_ASSET, S.BRUSHES), (T.BRUSH_ASSET, T.BRUSHES)):
    icons_ = S.brush_icons(asset_, [n for _l, n in brushes_])
    check(set(icons_) == {n for _l, n in brushes_}, "thumbnail for every brush of %s: %s" % (asset_, sorted(icons_)))
    check(all(S._previews[asset_ + n].image_size[0] > 0 for _l, n in brushes_), "thumbnails of %s have pixels" % asset_)
    log = []
    S.brush_tiles(Rec(log), SCtx('LEFT'), asset_, brushes_)
    check_calls("brush tiles", log)
    tiles_ = [r for r in log if r._kind == "operator"]
    check([t.identifier for t in tiles_] == [asset_ + n for _l, n in brushes_], "a tile per brush in order")
    check(all(t._args[0] == "m3d.brush_pick" and "icon_value" in t._kw for t in tiles_), "tiles show the thumbnail")
check(not S._missing and (len(bpy.data.brushes), len(bpy.data.libraries)) == data_before_, "thumbnail lookup leaves no data behind: %s" % S._missing)
check(S.brush_icons(S.BRUSH_ASSET, ["No Such Brush"]) == {} and S.BRUSH_ASSET + "No Such Brush" in S._missing,
      "a brush with no thumbnail is left out (its tile is a text button)")

# The Custom panel of the Sculpt tray: the Custom shelf where the shelf is hidden.
log = []
S.PROPERTIES_PT_m3d_sc_custom.draw_header_preset(type("Inst", (), {"layout": Rec(log)})(), SCtx('LEFT'))
S.PROPERTIES_PT_m3d_sc_custom.draw(type("Inst", (), {"layout": Rec(log)})(), SCtx('LEFT'))
check(any(r._kind == "label" for r in log), "empty Custom panel says how to add buttons")
m3d_user.shelf_items('SCULPT').append({"idname": "object.mode_set", "props": {"mode": 'OBJECT'}, "icon": "OBJECT_DATAMODE", "label": "Object Mode"})
log = []
S.PROPERTIES_PT_m3d_sc_custom.draw(type("Inst", (), {"layout": Rec(log)})(), SCtx('LEFT'))
check_calls("sculpt custom panel", log)
check(any(r._kind == "operator" and r._args[0] == "object.mode_set" for r in log), "Custom panel draws the Sculpt Custom shelf")
m3d_user.shelf_items('SCULPT').clear()
check(S.PROPERTIES_PT_m3d_sc_custom.page == "sculpt_brushes" and 'DEFAULT_CLOSED' in S.PROPERTIES_PT_m3d_sc_custom.bl_options,
      "Custom panel is on the brush page, collapsed")

# Hidden tabs round trip from the new place: the toggle shows in the next draw, and persists.
model_ws_ = W.find_workspace('MODEL')
with bpy.context.temp_override(workspace=model_ws_):
    bpy.ops.m3d.dock_tab_toggle(tab="tool")
m3d_user.reset_cache()
check(m3d_user.hidden_tabs('MODEL') == {"tool"}, "toggle from Workspace Settings hides the tab")
icons_ = {o[1]["tab"]: o[2].get("icon") for o in ws_ops(ws_settings_log(model_ws_)) if o[0] == "m3d.dock_tab_toggle"}
check(icons_["tool"] == 'CHECKBOX_DEHLT' and icons_["modeling_toolkit"] == 'CHECKBOX_HLT', "hidden tab drawn unticked: %s" % icons_)
with bpy.context.temp_override(workspace=model_ws_):
    bpy.ops.m3d.dock_tab_toggle(tab="tool")
m3d_user.reset_cache()
check(m3d_user.hidden_tabs('MODEL') == set(), "toggle from Workspace Settings shows the tab again")

# --- Edit the interface (m3d_edit.py): shelf drag data, dock layout store, hotkeys.
import m3d_edit as E
with open(path, "w") as fh:
    fh.write("{}")
m3d_user.reset_cache()
check(not E.editing(), "edit mode is off at start")
bpy.ops.m3d.edit_mode()
check(E.editing(), "Click to Edit turns it on")
log = []
W.M3D_PT_workspace_settings.draw(type("Inst", (), {"layout": Rec(log)})(), WsCtx(bpy.data.workspaces["Modeling"]))
edit_ops_ = [r for r in log if r._kind == "operator" and r._args[0] == "m3d.edit_mode"]
check(edit_ops_ and edit_ops_[0]._kw.get("text") == "Editing" and edit_ops_[0]._kw.get("depress"), "the toggle reads Editing while on")
bpy.ops.m3d.edit_mode()
check(not E.editing(), "the toggle turns it off again")

# Drop slots and hit tests on a recorded shelf row.
rec_ = {"rect": (0, 100, 800, 40), "unit": 20, "ws": "Modeling", "kind": 'MODEL', "key": 'CUSTOM',
        "cells": [(4, 40, ("C", 0)), (44, 40, ("C", 1)), (84, 40, ("C", 2)), (124, 4, None), (128, 40, ("C", 3))]}
slots_ = [E.drop_slot(rec_, x, 4) for x in (5, 30, 70, 110, 160, 700)]
check(slots_ == [0, 1, 2, 3, 4, 4], "drop slot from x: %s" % slots_)
check(E.drop_slot(rec_, 300, 0) == 0, "drop slot of an empty shelf")
check(E.shelf_hit(rec_, 50, 120) == ("C", 1) and E.shelf_hit(rec_, 126, 120) is None and E.shelf_hit(rec_, 150, 120) == ("C", 3)
      and E.shelf_hit(rec_, 50, 300) is None and E.shelf_hit(rec_, 900, 120) is None, "shelf hit test")
tabs_ = {"rect": (0, 140, 800, 26), "custom": (600, 800), "ws": "Modeling", "kind": 'MODEL', "width": 8}
check(E.on_custom_tab(tabs_, 700, 150) and not E.on_custom_tab(tabs_, 500, 150) and not E.on_custom_tab(tabs_, 700, 100), "custom tab hit test")
ctx_ = NS(workspace=NS(name="Modeling", m3d_show_shelf=True))
E._geom.update(shelf=rec_, tabs=tabs_)
m3d_user.shelf_items('MODEL').extend({"idname": "object.mode_set", "props": {"mode": 'OBJECT'}, "icon": "", "label": n} for n in "ABC")
check(E.target_at(110, 120, ctx_, ("C", 0)) == ("slot", 3) and E.target_at(700, 150, ctx_, ("C", 0)) == "tab"
      and E.target_at(300, 600, ctx_, ("C", 0)) == "out" and E.target_at(110, 120, ctx_, ("B", 'POLY', 0)) == "here",
      "drag target under the mouse")
ctx_.workspace.name = "Sculpt"
check(E.target_at(110, 120, ctx_, ("C", 0)) == "out", "a record of another workspace's shelf is ignored")
ctx_.workspace = NS(name="Modeling", m3d_show_shelf=False)
check(E.target_at(110, 120, ctx_, ("C", 0)) == "out", "a hidden shelf takes no drops")
E._geom.clear()

# Reorder / remove / copy data paths, round trip through the file.
def names_():
    m3d_user.reset_cache()
    return "".join(i["label"] for i in m3d_user.shelf_items('MODEL'))
m3d_user.save()
check(names_() == "ABC", "custom shelf saved before reordering: %s" % names_())
check(E.reorder_custom('MODEL', 0, 3) and names_() == "BCA", "drag A to the end: %s" % names_())
check(E.reorder_custom('MODEL', 2, 0) and names_() == "ABC", "drag A to the front")
check(not E.reorder_custom('MODEL', 1, 1) and not E.reorder_custom('MODEL', 1, 2) and names_() == "ABC", "dropping in place changes nothing")
check(E.reorder_custom('MODEL', 0, 2) and names_() == "BAC", "drag A between B and C")
check(not E.reorder_custom('MODEL', 7, 0) and not E.reorder_custom('MODEL', 0, 9), "out of range moves are ignored")
check(E.finish_drag('MODEL', ("C", 1), "out") == "remove" and names_() == "BC", "drag off the shelf removes")
check(E.finish_drag('MODEL', ("C", 0), ("slot", 2)) == "reorder" and names_() == "CB", "finish_drag reorders")
check(E.finish_drag('MODEL', ("C", 0), "tab") is None and names_() == "CB", "a Custom button on the Custom tab stays")
item_ = E.builtin_item('POLY', 1)
check(item_ and item_["idname"] == "m3d.add_primitive" and item_["props"] == {"kind": 'CUBE'} and item_["icon"] == "MESH_CUBE",
      "built-in button as a Custom item: %r" % item_)
check(E.builtin_item('POLY', 6) is None and E.builtin_item('SCULPT_REMESH', 1) is None and E.builtin_item('POLY', 99) is None
      and E.builtin_item('NOPE', 0) is None, "gaps, widgets and bad indices are not copied")
check(E.finish_drag('MODEL', ("B", 'POLY', 1), "tab") == "copy" and E.finish_drag('MODEL', ("B", 'POLY', 6), "tab") is None
      and E.finish_drag('MODEL', ("B", 'POLY', 1), "out") is None, "drag a built-in button onto the Custom tab copies it")
m3d_user.reset_cache()
copied_ = m3d_user.shelf_items('MODEL')[-1]
check(len(m3d_user.shelf_items('MODEL')) == 3 and copied_["idname"] == "m3d.add_primitive" and copied_["props"] == {"kind": 'CUBE'},
      "the copy is in the file: %r" % copied_)
check(m3d_user._item_ok(copied_), "the copied item draws")
m3d_user.shelf_items('MODEL').clear()
m3d_user.save()

# The shelf in edit mode draws fixed-width cells and records them (a fake layout and region).
real_ws_ = bpy.data.workspaces["Modeling"]
class ShelfCtx:
    workspace, region = real_ws_, NS(x=0, y=1251, width=2560, height=40, type='WINDOW')
    area, window_manager = NS(type='TOPBAR'), bpy.context.window_manager
    def __getattr__(self, name):
        return getattr(bpy.context, name)
E.set_editing(True)
bpy.context.window_manager.m3d_shelf = 'POLY'
log = []
m3d_ui.draw_shelf(Rec(log), ShelfCtx())
check_calls("edit-mode shelf", log)
cells_ = E._geom["shelf"]["cells"]
poly_ = m3d_ui.SHELVES['POLY'][1]
check([c[2] for c in cells_ if c[2]] == [("B", 'POLY', i) for i, it in enumerate(poly_) if it is not None], "a cell per shelf button")
check(all(w == 40 for _x, w, ref in cells_ if ref) and cells_[0][0] == E.SHELF_X0 * 20, "icon cells are two units wide: %s" % cells_[:2])
check(len([r for r in log if r._kind == "operator"]) == len([it for it in poly_ if it]), "every button is still drawn")
E.set_editing(False)
log = []
m3d_ui.draw_shelf(Rec(log), ShelfCtx())
check_calls("normal shelf", log)
check(not any(r._kind == "row" and "ui_units_x" in r.values() for r in log), "no edit cells outside edit mode")
m3d_user.shelf_items('MODEL').append({"idname": "object.mode_set", "props": {"mode": 'OBJECT'}, "icon": "OBJECT_DATAMODE", "label": "Obj"})
E.set_editing(True)
bpy.context.window_manager.m3d_shelf = 'CUSTOM'
log = []
m3d_ui.draw_shelf(Rec(log), ShelfCtx())
check_calls("edit-mode custom shelf", log)
check([c[2] for c in E._geom["shelf"]["cells"] if c[2]] == [("C", 0)], "custom cells: %s" % E._geom["shelf"]["cells"])
E._drag.update(src=("C", 0), target=("slot", 1))
log = []
m3d_ui.draw_shelf(Rec(log), ShelfCtx())
check(any(r._kind == "row" and r.values().get("alert") for r in log) and any(r._kind == "row" and r.values().get("active") is False for r in log),
      "the drop slot is marked and the dragged button greyed")
E._drag.update(src=None, target=None)
m3d_user.shelf_items('SCULPT').append({"idname": "object.mode_set", "props": {"mode": 'OBJECT'}, "icon": "OBJECT_DATAMODE", "label": "Obj"})
log = []
S.PROPERTIES_PT_m3d_sc_custom.draw(type("Inst", (), {"layout": Rec(log)})(), SCtx('LEFT'))
check(any(r._kind == "operator" and r._args[0] == "m3d.shelf_edit" for r in log), "the Sculpt tray's Custom panel has arrows while editing")
m3d_user.shelf_items('SCULPT').clear()
E.set_editing(False)
m3d_user.shelf_items('MODEL').clear()
bpy.context.window_manager.m3d_shelf = 'POLY'

# Dock layout store: user tabs, moved and hidden panels.
check(m3d_user.user_tabs('MODEL') == [] and m3d_user.panel_page('MODEL', "X", "home") == "home" and not m3d_user.panel_hidden('MODEL', "X"),
      "empty dock layout")
tab1_ = m3d_user.add_user_tab('MODEL', 'RIGHT', " Mine ")
tab2_ = m3d_user.add_user_tab('MODEL', 'RIGHT', "")
check((tab1_, tab2_) == ("user_1", "user_2") and [t["label"] for t in m3d_user.user_tabs('MODEL')] == ["Mine", "New Tab"], "user tabs: ids and names")
check([t.id for t in W.dock_tabs('MODEL', 'RIGHT')][-2:] == ["user_1", "user_2"], "user tabs are in the dock's tabs")
lt_ = m3d_user.add_user_tab('SCULPT', 'LEFT', "Mine L")
check(lt_ in [t.id for t in W.dock_tabs('SCULPT', 'LEFT')] and lt_ not in [t.id for t in W.dock_tabs('SCULPT', 'RIGHT')], "a user tab is on one side")
check(m3d_user.rename_user_tab('MODEL', "user_1", " Renamed ") and not m3d_user.rename_user_tab('MODEL', "user_1", "  ")
      and not m3d_user.rename_user_tab('MODEL', "nope", "x"), "rename a tab")
m3d_user.reset_cache()
check([t["label"] for t in m3d_user.user_tabs('MODEL')] == ["Renamed", "New Tab"], "user tabs round trip through the file")
panel_ = "PROPERTIES_PT_m3d_mtk_mesh"
check(m3d_user.move_panel('MODEL', panel_, "user_1", "modeling_toolkit") and m3d_user.panel_page('MODEL', panel_, "modeling_toolkit") == "user_1"
      and m3d_user.panel_page('SCULPT', panel_, "modeling_toolkit") == "modeling_toolkit", "moves are per kind")
m3d_user.reset_cache()
check(m3d_user.panel_page('MODEL', panel_, "modeling_toolkit") == "user_1", "moves round trip")
real_ws_.m3d_page_right = "modeling_toolkit"
mctx_ = lambda: NS(workspace=real_ws_, area=NS(x=1500, width=500), window=NS(width=2000))
check(not m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_()) and m3d_mode.PROPERTIES_PT_m3d_mtk_selection.poll(mctx_()),
      "a moved panel leaves its page")
real_ws_.m3d_page_right = "user_1"
check(W.active_page(mctx_()) == "user_1" and m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_())
      and not m3d_mode.PROPERTIES_PT_m3d_mtk_selection.poll(mctx_()), "...and shows on the user tab")
m3d_user.toggle_panel_hidden('MODEL', panel_)
check(m3d_user.panel_hidden('MODEL', panel_) and not m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_()), "a hidden panel is gone")
E._state["on"] = True
check(m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_()), "...but listed while editing, so it can be shown again")
def mesh_header_(log):
    """The Mesh panel's header drawing, on an instance of a class that looks like it."""
    inst = type("PROPERTIES_PT_m3d_mtk_mesh", (W._PagePanel,), {"layout": Rec(log), "page": "modeling_toolkit"})()
    inst.draw_header_preset(mctx_())
log = []
mesh_header_(log)
hdr_ = [(r._kind, r._args[:2], r._kw.get("icon")) for r in log]
check(("operator_menu_enum", ("m3d.panel_move", "tab"), 'ARROW_LEFTRIGHT') in hdr_ and ("operator", ("m3d.panel_hide",), 'HIDE_ON') in hdr_,
      "panel header controls while editing: %s" % hdr_)
E._state["on"] = False
log = []
mesh_header_(log)
check(not log, "no panel header controls outside edit mode")
m3d_user.toggle_panel_hidden('MODEL', panel_)
check(not m3d_user.panel_hidden('MODEL', panel_) and m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_()), "shown again")
# A sub-panel follows its parent.
check(E.panel_root(T.PROPERTIES_PT_m3d_tx_stabilize) is T.PROPERTIES_PT_m3d_tx_stroke and E.panel_root(m3d_mode.PROPERTIES_PT_m3d_mtk_mesh)
      is m3d_mode.PROPERTIES_PT_m3d_mtk_mesh, "panel_root")
# Deleting a tab returns its panels; ids aren't reused.
check(m3d_user.delete_user_tab('MODEL', "user_1") and m3d_user.panel_page('MODEL', panel_, "modeling_toolkit") == "modeling_toolkit"
      and [t["id"] for t in m3d_user.user_tabs('MODEL')] == ["user_2"], "deleting a tab returns its panels")
real_ws_.m3d_page_right = "user_1"
check(W.active_page(mctx_()) == "modeling_toolkit" and m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_()), "the dock falls back when its tab is gone")
check(m3d_user.add_user_tab('MODEL', 'RIGHT', "Again") == "user_3", "tab ids are never reused")
# The operators (m3d.panel_move / panel_hide / user_tab_* / dock_layout_reset).
with bpy.context.temp_override(workspace=real_ws_):
    bpy.ops.m3d.user_tab_add('EXEC_DEFAULT', name="Ops")
    check(m3d_user.user_tabs('MODEL')[-1]["label"] == "Ops" and real_ws_.m3d_page_right == "user_4", "user_tab_add makes a tab and shows it")
    bpy.ops.m3d.panel_move(panel=panel_, tab="user_4")
    check(m3d_user.panel_page('MODEL', panel_, "x") == "user_4", "panel_move")
    bpy.ops.m3d.panel_move(panel=panel_, tab="modeling_toolkit")
    check(m3d_user.panel_page('MODEL', panel_, "x") == "x" and panel_ not in m3d_user._dock('MODEL')["moves"],
          "moving a panel home drops the entry")
    bpy.ops.m3d.panel_hide(panel=panel_)
    check(m3d_user.panel_hidden('MODEL', panel_), "panel_hide")
    bpy.ops.m3d.user_tab_rename('EXEC_DEFAULT', tab="user_4", name="Renamed by op")
    check(m3d_user.user_tabs('MODEL')[-1]["label"] == "Renamed by op", "user_tab_rename")
    check(bpy.ops.m3d.panel_move(panel="NoSuchPanel", tab="modeling_toolkit") == {'CANCELLED'}, "unknown panel is ignored")
    bpy.ops.m3d.user_tab_delete(tab="user_4")
    check("user_4" not in [t["id"] for t in m3d_user.user_tabs('MODEL')], "user_tab_delete")
    m3d_user.toggle_tab('MODEL', "tool")
    bpy.ops.m3d.dock_layout_reset()
check(m3d_user.user_tabs('MODEL') == [] and not m3d_user.panel_hidden('MODEL', panel_) and m3d_user.hidden_tabs('MODEL') == set()
      and m3d_user.user_tabs('SCULPT') != [], "Reset Dock Layout clears this kind only")
m3d_user.reset_dock('SCULPT')
real_ws_.m3d_page_right = ""
# Damaged dock data never raises.
for text in ('{"dock": 5}', '{"dock": {"MODEL": 7}}',
             '{"dock": {"MODEL": {"tabs": [1, {"id": 3}, {"id": "a", "label": "x", "side": "UP"}], "moves": [], "hidden": 4}}}'):
    with open(path, "w") as fh:
        fh.write(text)
    m3d_user.reset_cache()
    try:
        W.dock_tabs('MODEL', 'RIGHT'); m3d_user.panel_page('MODEL', "x", "h"); m3d_user.panel_hidden('MODEL', "x")
        m3d_mode.PROPERTIES_PT_m3d_mtk_mesh.poll(mctx_())
        m3d_user.add_user_tab('MODEL', 'RIGHT', "t"); m3d_user.toggle_panel_hidden('MODEL', "x"); m3d_user.move_panel('MODEL', "x", "p", "h")
        ok = True
    except Exception as err:
        ok = False
        print("damaged dock data:", text, repr(err))
    check(ok, "damaged dock data: " + text)
with open(path, "w") as fh:
    fh.write("{}")
m3d_user.reset_cache()

# Hotkeys: the command of a button, the keymap, conflicts, the capture flow.
check(E.parse_command("bpy.ops.mesh.bevel(offset_type='PERCENT', segments=3)") == ("mesh.bevel", {"offset_type": 'PERCENT', "segments": 3})
      and E.parse_command("bpy.ops.mesh.select_mode(type='VERT', use_extend={'A'})") == ("mesh.select_mode", {"type": 'VERT', "use_extend": {'A'}})
      and E.parse_command("bpy.ops.wm.read_homefile(app_template=\"\")") == ("wm.read_homefile", {"app_template": ""})
      and E.parse_command("bpy.ops.object.mode_set()") == ("object.mode_set", {}), "parse_command")
check(all(E.parse_command(t) is None for t in ("", "os.system('x')", "bpy.ops.a.b(1)", "bpy.ops.a.b(x=__import__('os'))",
                                               "bpy.data.x.y()", "bpy.ops.a(x=1)", "nonsense(")), "parse_command ignores anything else")
cmd_ = "bpy.ops.m3d.call(idname='mesh.bevel', props=\"{'offset_type': 'PERCENT'}\", label='Bevel', editor='VIEW_3D')"
it_ = E.item_from_command(cmd_, 'TOPBAR')
check(E._op_label("m3d.add_primitive", {"kind": 'SPHERE'}) == "Polygon Primitive: Sphere" and E._op_label("m3d.call", {"idname": "mesh.bevel", "props": "{}", "label": ""}) == "Bevel",
      "button names in the prompt")
check(it_ and it_["idname"] == "m3d.call" and it_["props"]["idname"] == "mesh.bevel" and it_["label"] == "Bevel" and it_["keymap"] == "Window",
      "top bar button: Window keymap: %r" % it_)
check(E.item_from_command("bpy.ops.mesh.bevel()", 'VIEW_3D')["keymap"] == "3D View" and E.item_from_command("bpy.ops.mesh.nope()", 'VIEW_3D') is None
      and E.item_from_command("bpy.ops.mesh.bevel()", 'PROPERTIES')["keymap"] == "Window"
      and E.item_from_command("bpy.ops.mesh.bevel()", 'PROPERTIES')["label"] == "Bevel", "keymap by editor, unknown operators skipped")
sc_ = bpy.context.scene.name
it_ = E.item_from_path('bpy.data.scenes["%s"].tool_settings.use_snap' % sc_, 'TOPBAR')
check(it_ == {"idname": "wm.context_toggle", "props": {"data_path": "tool_settings.use_snap"}, "label": "Snap", "keymap": "Window"},
      "toggle button: %r" % it_)
scr_ = next(s for s in bpy.data.screens if any(a.type == 'VIEW_3D' for a in s.areas))
ai_ = next(i for i, a in enumerate(scr_.areas) if a.type == 'VIEW_3D')
it_ = E.item_from_path('bpy.data.screens["%s"].areas[%d].spaces[0].overlay.show_floor' % (scr_.name, ai_), 'TOPBAR')
check(it_ and it_["props"] == {"data_path": "space_data.overlay.show_floor"} and it_["keymap"] == "3D View", "space toggle: %r" % it_)
check(E.item_from_path('bpy.data.scenes["%s"].frame_current' % sc_, 'TOPBAR') is None and E.item_from_path("os.path", 'X') is None
      and E.item_from_path('bpy.data.scenes["%s"].no_such' % sc_, 'X') is None
      and E.item_from_path('bpy.data.objects["Cube"].hide_viewport', 'X') is None, "only boolean properties of the scene, tool settings and editors")
check(E.is_key('A') and E.is_key('F1') and E.is_key('RET') and E.is_key('NUMPAD_1') and E.is_key('ESC') and not E.is_key('LEFT_CTRL')
      and not E.is_key('LEFTMOUSE') and not E.is_key('MOUSEMOVE') and not E.is_key('TIMER') and not E.is_key('WHEELUPMOUSE')
      and not E.is_key('NDOF_BUTTON_1'), "which events are keys")
check(E.key_label({"type": 'J', "ctrl": True, "alt": True, "shift": False, "oskey": False}) == "Ctrl+Alt+J", "key label")
E._hover = {"item": {"label": "x"}, "pos": (100, 100)}
check(E.hover_at(102, 99) and E.hover_at(100, 110) is None, "a stale probe is ignored")
E._hover = None
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maelstrom3D", "keyconfig"))
def user_items_(idname, km="Window"):
    return [k for k in bpy.context.window_manager.keyconfigs.user.keymaps[km].keymap_items if k.idname == idname]
sphere_ = {"idname": "m3d.add_primitive", "props": {"kind": 'SPHERE'}, "label": "Sphere", "keymap": "Window"}
spec_j = {"type": 'J', "ctrl": True, "alt": True, "shift": True, "oskey": False}
check(E.conflicts(sphere_, spec_j) == [], "a free key has no conflicts")
kmi_ = E.assign_key(sphere_, spec_j)
check(kmi_ and kmi_.idname == "m3d.add_primitive" and kmi_.properties.kind == 'SPHERE' and kmi_.type == 'J' and kmi_.value == 'PRESS'
      and (kmi_.ctrl, kmi_.alt, kmi_.shift, kmi_.oskey) == (1, 1, 1, 0) and kmi_.is_user_defined, "assigned: %r" % kmi_)
check(len([k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'SPHERE' and k.type == 'J']) == 1, "the item is in the user keymap")
check(E.conflicts(sphere_, spec_j) == [], "the button's own key is not a conflict")
other_ = {**sphere_, "props": {"kind": 'CUBE'}}
check(E.conflicts(other_, spec_j) == ["Polygon Primitive"], "another button on that key conflicts: %s" % E.conflicts(other_, spec_j))
spec_k = {"type": 'K', "ctrl": True, "alt": False, "shift": False, "oskey": False}
E.assign_key(sphere_, spec_k)
sph_ = [k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'SPHERE']
check(len(sph_) == 1 and sph_[0].type == 'K' and (sph_[0].ctrl, sph_[0].alt, sph_[0].shift) == (1, 0, 0),
      "assigning again changes the button's key: %s" % [(k.type, k.ctrl) for k in sph_])
f1_ = {"type": 'F1', "ctrl": False, "alt": False, "shift": False, "oskey": False}
check("Switch Workspace" in E.conflicts({"idname": "m3d.add_primitive", "props": {"kind": 'CUBE'}, "label": "Cube", "keymap": "Window"}, f1_),
      "default keys conflict: F1 = workspace")
check(E.conflicts({"idname": "m3d.add_primitive", "props": {"kind": 'CUBE'}, "label": "Cube", "keymap": "NoSuchKeymap"}, f1_) == []
      and E.assign_key({"idname": "m3d.add_primitive", "props": {}, "label": "x", "keymap": "NoSuchKeymap"}, f1_) is None, "unknown keymap")
toggle_ = {"idname": "wm.context_toggle", "props": {"data_path": "tool_settings.use_snap"}, "label": "Snap", "keymap": "Window"}
tk_ = E.assign_key(toggle_, {"type": 'F9', "ctrl": True, "alt": False, "shift": False, "oskey": False})
check(tk_ and tk_.idname == "wm.context_toggle" and tk_.properties.data_path == "tool_settings.use_snap", "a property toggle becomes wm.context_toggle")
# The capture flow (Esc cancels, a free key assigns, a conflict asks first).
def ev_(type, **mods):
    return NS(type=type, value='PRESS', shift=mods.get("shift", False), ctrl=mods.get("ctrl", False), alt=mods.get("alt", False), oskey=False)
cube_ = {"idname": "m3d.add_primitive", "props": {"kind": 'CUBE'}, "label": "Cube", "keymap": "Window"}
cone_ = {**cube_, "props": {"kind": 'CONE'}, "label": "Cone"}
E.begin_capture(bpy.context, cube_)
check(E._capture and E._capture["state"] == 'KEY' and E._prompt["text"] == "Press a key for Cube... Esc cancels", "prompt: %r" % E._prompt["text"])
check(E.capture_event(bpy.context, NS(type='MOUSEMOVE', value='NOTHING')) == {'PASS_THROUGH'} and E._capture, "the mouse moves while waiting")
check(E.capture_event(bpy.context, NS(type='LEFT_CTRL', value='PRESS')) == {'PASS_THROUGH'} and E._capture, "modifier keys alone don't end it")
E.capture_event(bpy.context, ev_('ESC'))
check(E._capture is None and E._prompt["text"] == "" and not [k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'CUBE'], "Esc cancels")
E.begin_capture(bpy.context, cube_)
E.capture_event(bpy.context, ev_('J', ctrl=True, shift=True))
check(E._capture is None and [k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'CUBE' and k.type == 'J' and k.ctrl and k.shift],
      "a free key is assigned")
E.begin_capture(bpy.context, cone_)
E.capture_event(bpy.context, ev_('F1'))
check(E._capture and E._capture["state"] == 'CONFIRM' and "Switch Workspace" in E._prompt["text"] and "F1" in E._prompt["text"]
      and not [k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'CONE'], "a conflict asks first: %r" % E._prompt["text"])
E.capture_event(bpy.context, ev_('Q'))
check(E._capture and E._capture["state"] == 'CONFIRM', "other keys are ignored while asking")
E.capture_event(bpy.context, ev_('ESC'))
check(E._capture is None and not [k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'CONE'], "Esc at the conflict cancels")
E.begin_capture(bpy.context, cone_)
E.capture_event(bpy.context, ev_('F1'))
E.capture_event(bpy.context, ev_('RET'))
check(E._capture is None and [k for k in user_items_("m3d.add_primitive") if k.properties.kind == 'CONE' and k.type == 'F1'], "Enter assigns it anyway")
check([k.idname for k in user_items_("m3d.workspace") if k.type == 'F1'], "...and the default F1 item is still there")
E._load_post()
check(not E.editing() and E._capture is None, "loading a file ends edit mode")

# Save Layouts as Default writes the startup file (into the temp config folder here, never the real one).
startup_ = os.path.join(TEST_CONFIG, "config", "startup.blend")
check(not os.path.exists(startup_), "no startup file before saving")
bpy.ops.wm.save_homefile()
check(os.path.exists(startup_), "Save Layouts as Default wrote " + startup_)
os.remove(startup_)

print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)

