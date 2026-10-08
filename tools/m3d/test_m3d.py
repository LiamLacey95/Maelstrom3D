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
import m3d_marking, m3d_ui as _maya_ui, m3d_uv as _maya_uv
src = "".join(open(m.__file__).read() for m in (m3d_mode, m3d_marking, _maya_ui, _maya_uv))
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
check(wm.m3d_menu_set == 'SCULPTING' and wm.m3d_shelf == 'CUSTOM', "menu set and shelf follow a workspace switch")
W.workspace_changed(wm, bpy.data.workspaces["Modeling"])
check(wm.m3d_menu_set == 'MODELING' and wm.m3d_shelf == 'POLY', "shelf tab is remembered per kind")

# Shelf tabs and status line per kind.
check(m3d_ui.shelves_for('SCULPT') == ['CUSTOM'] and 'POLY' in m3d_ui.shelves_for('MODEL')
      and m3d_ui.shelves_for('MODEL')[-1] == 'CUSTOM', "shelf tabs per kind")
check(set(m3d_ui.KIND_MODES) == set(W.KINDS) - {'MODEL'}, "placeholder status line modes for every other kind")

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
other = bpy.data.workspaces["Sculpt"]
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
m3d_user.reset_cache()
shutil.rmtree(TEST_CONFIG, ignore_errors=True)

print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
