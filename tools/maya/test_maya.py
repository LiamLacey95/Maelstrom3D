# Self-check for MayaBlender's Python layer. Run: blender -b --factory-startup --python-exit-code 1 --python tools/maya/test_maya.py
import bpy, sys
fails = []
def check(cond, msg):
    if not cond: fails.append(msg)

# Icons used in maya_mode exist.
import re, maya_mode
icons = set(bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items.keys())
src = open(maya_mode.__file__).read()
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
check(find("3D View", "screen.region_quadview", "SPACE"), "space quadview")
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
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
