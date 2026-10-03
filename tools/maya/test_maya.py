# Self-check for MayaBlender's Python layer. Run: blender -b --factory-startup --python-exit-code 1 --python tools/maya/test_maya.py
import bpy, sys
fails = []
def check(cond, msg):
    if not cond: fails.append(msg)

# Icons used in maya_mode exist.
import re, maya_mode
icons = set(bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items.keys())
import maya_marking, maya_ui as _maya_ui, maya_uv as _maya_uv
src = "".join(open(m.__file__).read() for m in (maya_mode, maya_marking, _maya_ui, _maya_uv))
for ic in set(re.findall(r"icon='([A-Z_0-9]+)'", src)):
    check(ic in icons, "missing icon " + ic)

# Every Maya menu / shelf entry points at a real operator, property, menu and icon.
import maya_ui

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

for mid, (label, entries) in maya_ui.MENUS.items():
    for e in entries:
        where = mid + ": " + e.get("label", "")
        kind = e["kind"]
        if kind == 'OP':
            check(op_ok(e["idname"], e["props"]), "bad op " + where + " " + e["idname"])
        elif kind == 'ENUM':
            check(op_ok(e["idname"], [e["prop"]]), "bad enum op " + where)
        elif kind == 'MENU' and e["idname"] not in C_MENUS:
            check(hasattr(bpy.types, e["idname"]), "bad submenu " + where + " " + e["idname"])
        elif kind == 'PROP':
            check(path_ok(e["path"]), "bad prop " + where + " " + e["path"])
        if e.get("icon", 'NONE') != 'NONE':
            check(e["icon"] in icons, "bad icon " + where + " " + e["icon"])
for _, menus in maya_ui.MENU_SETS.values():
    for mid in menus:
        check(hasattr(bpy.types, mid), "menu set refers to missing " + mid)
for tab, (label, items) in maya_ui.SHELVES.items():
    for it in filter(None, items):
        check(op_ok(it[0], it[2]), "bad shelf op %s %s" % (tab, it[0]))
        check(it[1] in icons, "bad shelf icon %s %s" % (tab, it[1]))

import maya_uv
for label, items in [*maya_mode.COMPONENT_TOOLS.values(), *maya_uv.UV_TOOLKIT_SECTIONS]:
    for item_label, idname, icon, props in items:
        check(op_ok(idname, props), "bad tool %s / %s %s" % (label, item_label, idname))
        check(icon in icons, "bad tool icon %s / %s %s" % (label, item_label, icon))
for group in (maya_mode.MTK_SELECT_TOOLS, maya_mode.MTK_MESH, maya_mode.MTK_COMPONENTS, maya_mode.MTK_TOOLS):
    for label, idname, icon, props in group:
        check(op_ok(idname, props), "bad toolkit op %s %s" % (label, idname))
        check(icon in icons, "bad toolkit icon %s %s" % (label, icon))

# Keymap loads and overrides land.
bpy.utils.keyconfig_set(bpy.utils.preset_find("Maya", "keyconfig"))
kc = bpy.context.window_manager.keyconfigs["Maya"]
def find(km, idname, type, **mods):
    return [k for k in kc.keymaps[km].keymap_items if k.idname == idname and k.type == type
            and all(getattr(k, m) == v for m, v in mods.items())]
check(find("Object Mode", "wm.call_menu_pie", "RIGHTMOUSE", shift=False), "rmb pie object")
check(find("Mesh", "wm.call_menu_pie", "RIGHTMOUSE", shift=True), "shift rmb pie mesh")
check(not [k for k in kc.keymaps["Frames"].keymap_items if k.type == 'SPACE'], "space still plays")
check(find("3D View", "wm.context_set_enum", "FOUR"), "4 wireframe")
check(find("Object Mode", "maya.smooth_preview", "THREE"), "3 smooth")
check(not find("Object Mode", "object.mode_set_with_submode", "ONE"), "1 still edit-mode")
check(find("Object Mode", "maya.group", "G", ctrl=True), "ctrl g group")
check(find("Mesh", "mesh.select_mode", "F10"), "F10 edge")
check(find("3D View", "maya.dock_tab", "A", ctrl=True), "ctrl a dock toggle")
check(find("Mesh", "maya.delete_components", "DEL"), "delete components")
check(find("Mesh", "view3d.edit_mesh_extrude_move_normal", "E", ctrl=True), "ctrl e extrude")
check(find("Frames", "screen.keyframe_jump", "PERIOD", shift=False, alt=False), ". next key")
check(find("3D View", "maya.snap_hold", "V"), "hold v snap")
check(find("3D View", "maya.space_hotbox", "SPACE", ctrl=False), "space hotbox")
check(find("Object Mode", "maya.pivot_hold", "D", shift=False, ctrl=False), "d pivot object")
check(find("Mesh", "maya.pivot_hold", "D", shift=False, ctrl=False), "d pivot mesh")
check(find("Object Mode", "maya.duplicate", "D", shift=True), "shift d duplicate with transform")
check(find("Generic Gizmo Maybe Drag", "maya.gizmo_shift_drag", "LEFTMOUSE", shift=True, ctrl=False),
      "shift drag extrude/duplicate")
check(find("Generic Gizmo Maybe Drag", "maya.gizmo_slide", "LEFTMOUSE", shift=True, ctrl=True), "ctrl shift drag slide")
f2 = find("Window", "wm.context_set_enum", "F2")
check(f2 and f2[0].properties.value == 'MODELING', "F2 = Modeling menu set (Maya 2025)")
for km in ("Object Mode", "Mesh"):
    for key, menu in (("Q", "MAYA_MT_select_mm"), ("W", "MAYA_MT_move_mm"), ("E", "MAYA_MT_rotate_mm"),
                      ("R", "MAYA_MT_scale_mm")):
        items = find(km, "maya.key_marking_menu", key, shift=False, ctrl=False)
        check(items and items[0].properties.menu == menu and hasattr(bpy.types, menu), f"{km} {key}+LMB marking menu")
check(find("Object Mode", "wm.call_menu_pie", "RIGHTMOUSE", shift=True), "shift rmb context menu")
check(find("3D View", "wm.call_menu_pie", "RIGHTMOUSE", ctrl=True, shift=True), "ctrl shift rmb transform menu")
check(find("3D View", "maya.view_history", "LEFT_BRACKET"), "[ view undo")
check(find("Window", "ed.redo", "Y", ctrl=True), "ctrl y redo")
check(find("Mesh", "mesh.knife_tool", "X", ctrl=True, shift=True), "ctrl shift x multi-cut")
check(find("UV Editor", "wm.call_menu_pie", "RIGHTMOUSE", shift=False), "uv marking menu")
check(find("Mesh", "mesh.select_mode", "F11", ctrl=True), "ctrl f11 convert to faces")
ctrl_click = [k for k in kc.keymaps["3D View"].keymap_items if k.idname == "view3d.select" and k.type == 'LEFTMOUSE'
              and k.ctrl and not k.shift and not k.alt]
check(ctrl_click and ctrl_click[0].properties.deselect, "ctrl click deselects")

# Operators.
bpy.ops.maya.reset_transformations()
bpy.ops.maya.add_primitive(kind='CUBE')
ob = bpy.context.active_object
bpy.ops.maya.smooth_preview(level='SMOOTH'); check("MayaSmoothPreview" in ob.modifiers, "smooth on")
bpy.ops.maya.smooth_preview(level='OFF'); check("MayaSmoothPreview" not in ob.modifiers, "smooth off")
for kind in ('CUBE','SPHERE','CYLINDER','CONE','PLANE','TORUS'):
    bpy.ops.maya.add_primitive(kind=kind)
bpy.ops.object.select_all(action='SELECT')
n = len(bpy.context.selected_objects)
bpy.ops.maya.group()
g = bpy.context.active_object
check(g.type == 'EMPTY' and len(g.children) == n, "group children %d" % len(g.children))
gname = g.name
bpy.ops.maya.ungroup()
check(gname not in bpy.data.objects and all(o.parent is None for o in bpy.data.objects), "ungroup")
bpy.ops.object.select_all(action='DESELECT')
a, b = [o for o in bpy.data.objects if o.type == 'MESH'][:2]
a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active = b
bpy.ops.maya.boolean(operation='DIFFERENCE')
check(any(m.type == 'BOOLEAN' and m.object == b for m in a.modifiers), "boolean A - B")
# Maya Delete / Fill Hole on a cube.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.maya.add_primitive(kind='CUBE')
cube = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
bpy.context.tool_settings.mesh_select_mode = (False, False, True)
bpy.ops.mesh.select_all(action='DESELECT')
import bmesh
bm = bmesh.from_edit_mesh(cube.data); bm.faces.ensure_lookup_table(); bm.faces[0].select = True
bmesh.update_edit_mesh(cube.data)
bpy.ops.maya.delete_components()
bpy.ops.object.mode_set(mode='OBJECT')
check(len(cube.data.polygons) == 5, "delete face")
bpy.ops.maya.fill_hole()
check(len(cube.data.polygons) == 6, "fill hole")
# Maya Shift+D repeats the last duplicate's offset.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.maya.add_primitive(kind='SPHERE')
first = bpy.context.active_object
bpy.ops.maya.duplicate()
second = bpy.context.active_object
second.location.x += 2.0
bpy.context.view_layer.update()
bpy.ops.maya.duplicate(with_transform=True)
check(abs(bpy.context.active_object.location.x - 4.0) < 1e-4, "shift d offset")

# UV workflow: cut, unfold, layout, checker on/off.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.maya.add_primitive(kind='CUBE')
cube = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.maya.uv_cut()
bpy.ops.maya.uv_unfold()
bpy.ops.object.mode_set(mode='OBJECT')
check(any(e.use_seam for e in cube.data.edges), "uv cut marks seams")
bpy.ops.maya.uv_checker()
check(cube.data.materials[0].name == "mayaUVChecker", "checker on")
bpy.ops.maya.uv_checker()
check(len(cube.data.materials) == 0, "checker off restores materials")
# maya.cmds and MEL in the command line.
import maya.cmds as cmds, _console_mel
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

print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
