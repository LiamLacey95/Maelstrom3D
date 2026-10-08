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
import m3d_marking, m3d_sculpt, m3d_texture, m3d_ui as _maya_ui, m3d_uv as _maya_uv
src = "".join(open(m.__file__).read() for m in (m3d_mode, m3d_marking, m3d_sculpt, m3d_texture, _maya_ui, _maya_uv))
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
check(set(m3d_ui.KIND_MODES) == set(W.KINDS) - set(m3d_ui.STATUS_LINES), "placeholder status line modes for the other kinds")
check(set(m3d_ui.STATUS_LINES) == {'MODEL', 'SCULPT', 'UV', 'TEXTURE'}, "status lines")

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
        self.region = NS(type='WINDOW')

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
    return [c.__name__ for c in page_panels(page) if c.poll(ctx)]


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
            check(name in owner.bl_rna.properties, "%s: %r has no property %s" % (where, owner, name))
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
check(m3d_ui.shelves_for('UV') == ['UV', 'CUSTOM'] and 'UV' in m3d_ui.STATUS_LINES and 'UV' not in m3d_ui.KIND_MODES,
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
check([t.label for t in tex_tabs['RIGHT']] == ["Layers", "Brush", "Shelf", "Bake", "Export", "Display"], "Texture dock tabs")
check([t.label for t in tex_tabs['LEFT']] == ["Brushes"], "Texture left tray tab")
for tab in (*tex_tabs['RIGHT'], *tex_tabs['LEFT']):
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("tex_"), "Texture page tab " + tab.id)
tex_pages = {t.page for side in tex_tabs.values() for t in side}
check({c.page for c in T.classes if hasattr(c, "page")} == tex_pages, "every Texture page has panels and the other way round")
check(all(isinstance(getattr(bpy.types, c.__name__, None), type) for c in T.classes
          if not issubclass(c, bpy.types.PropertyGroup)), "Texture classes registered")
check(m3d_ui.shelves_for('TEXTURE') == ['TEXTURE_BRUSHES', 'TEXTURE_CHANNELS', 'TEXTURE_OUTPUT', 'CUSTOM']
      and 'TEXTURE' in m3d_ui.STATUS_LINES and 'TEXTURE' not in m3d_ui.KIND_MODES, "Texture shelf tabs and Status Line")
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
    return [c for c in T.classes if getattr(c, "page", None) == page and hasattr(c, "poll")]


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
check(not any(n.endswith("_gate") for n in tex_shown("tex_shelf") + tex_shown("tex_display")), "Shelf and Display need no mesh")
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
    for cls in (*T.PAGE_GATES, T.PROPERTIES_PT_m3d_tx_shelf_brushes, T.PROPERTIES_PT_m3d_tx_shelf_materials,
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

print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)

