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
import m3d_layers, m3d_marking, m3d_sculpt, m3d_texture, m3d_ui as _maya_ui, m3d_uv as _maya_uv
src = "".join(open(m.__file__).read() for m in (m3d_mode, m3d_layers, m3d_marking, m3d_sculpt, m3d_texture, _maya_ui, _maya_uv))
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
check([t.label for t in tex_tabs['RIGHT']] == ["Layers", "Brush", "Shelf", "Bake", "Export", "Display"], "Texture dock tabs")
check([t.label for t in tex_tabs['LEFT']] == ["Brushes"], "Texture left tray tab")
for tab in (*tex_tabs['RIGHT'], *tex_tabs['LEFT']):
    check(tab.context == 'MODELING_TOOLKIT' and tab.page == tab.id and tab.id.startswith("tex_"), "Texture page tab " + tab.id)
tex_pages = {t.page for side in tex_tabs.values() for t in side}
check({c.page for c in T.classes if hasattr(c, "page")} == tex_pages, "every Texture page has panels and the other way round")
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
check(bpy.ops.m3d.layer_mask_add(fill='BLACK') == {'FINISHED'} and fill.mask is not None and fill.paint_mask
      and fill.mask.colorspace_settings.name == 'Non-Color' and fill.mask.size[0] == 64, "Add Mask (black)")
check(read(fill.mask)[:, :3].max() == 0.0, "a black mask hides the layer")
check(slot_image(mat) == fill.mask, "Paint Mask: the brush paints the mask of the fill layer")
mix = expect_chain(mat, 'BASE_COLOR', "masked")[-1]
mask_nodes = [n for n in mat.node_tree.nodes if n.name.startswith(LY.part('BASE_COLOR', fill.uid, "mask"))]
check(any(n.type == 'TEX_IMAGE' and n.image == fill.mask for n in mask_nodes), "the mask is an image node in the chain")
check(bpy.ops.m3d.layer_mask_invert() == {'FINISHED'} and fill.mask_invert
      and any(n.name.endswith("maskinv") for n in mat.node_tree.nodes), "Invert Mask adds the invert node")
check(not bpy.ops.m3d.layer_mask_add.poll(), "one mask per layer")
check(bpy.ops.m3d.layer_paint_mask() == {'FINISHED'} and not fill.paint_mask and slot_image(mat) == fill.mask,
      "Paint Mask toggles off, but a fill layer's only paintable image is its mask")
check(bpy.ops.m3d.tex_channel(channel='METALLIC') == {'FINISHED'} and slot_image(mat) == fill.mask and T.active_channel(mat) == 'METALLIC',
      "channels can be picked while a masked fill layer is active")
# A paint layer: mask target vs channel target.
mat.m3d_layer_index = 1
paint_layer = mat.m3d_layers[1]
bpy.ops.m3d.tex_channel(channel='BASE_COLOR')
check(slot_image(mat) == LY.entry_of(paint_layer, 'BASE_COLOR').image, "target: active layer, active channel")
bpy.ops.m3d.layer_mask_add(fill='WHITE')
check(slot_image(mat) == paint_layer.mask and read(paint_layer.mask)[:, :3].min() == 1.0, "target: the layer's mask after Add Mask")
bpy.ops.m3d.tex_channel(channel='ROUGHNESS')
check(not paint_layer.paint_mask and slot_image(mat) == LY.entry_of(paint_layer, 'ROUGHNESS').image,
      "picking a channel goes back to painting the channel")
paint_layer.paint_mask = True
mat.m3d_layer_index = 0
check(slot_image(mat) == LY.entry_of(mat.m3d_layers[0], 'ROUGHNESS').image, "target: another layer, same channel")
mat.m3d_layer_index = 1
check(slot_image(mat) == paint_layer.mask, "target: Paint Mask is remembered per layer")
check(bpy.ops.m3d.layer_mask_remove() == {'FINISHED'} and paint_layer.mask is None and not paint_layer.paint_mask
      and not [n for n in mat.node_tree.nodes if ".%s.mask" % paint_layer.uid in n.name], "Remove Mask")
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
m.m3d_layers[1].mask = mask_img
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
m.m3d_layers[1].mask = small("fm", grid_rgba(lambda x, y: (mask_vals[x],) * 3, lambda y: 1.0), alpha=False)
LY.rebuild_all(m)
old_names = [im.name for im in imgs] + ["fm"]
px = [read(im).reshape(4, 4, 4) for im in imgs]
mk = read(m.m3d_layers[1].mask).reshape(4, 4, 4)
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
check(not any(n in bpy.data.images for n in old_names) and not m.m3d_layers[0].mask, "Flatten removes the old images")
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
            pmat.m3d_layers[1].mask = noise_image("ncm", False, alpha=False)
            pmat.m3d_layers[2].mask_invert = True
            pmat.m3d_layers[2].mask = noise_image("ncm2", False, alpha=False)
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
img_a, img_b, mask_b = LY.entry_of(layer_a, 'BASE_COLOR').image, LY.entry_of(layer_b, 'BASE_COLOR').image, layer_b.mask
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
check(len(sm.m3d_layers) == 2 and sm.m3d_layers[1].name == layer_b_name and sm.m3d_layers[1].mask is not None
      and sm.m3d_layers[1].mask.name == sv_names[1], "layers, names and mask are in the saved file")
check(abs(read(sm.m3d_layers[0].channels[0].image)[0, 0] - 0.7) < 2 / 255 and abs(read(sm.m3d_layers[1].mask)[0, 0] - 0.25) < 2 / 255,
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
    check((bpy.context.window_manager, "m3d_shelf_edit") in props_ and (ws_, "object_mode") in props_, "%s settings: Edit Shelf and entry mode" % kind_)
    # Entry mode sticks.
    old_ = ws_.object_mode
    ws_.object_mode = 'EDIT' if old_ != 'EDIT' else 'OBJECT'
    check(ws_.object_mode != old_, "%s entry mode changes" % kind_)
    ws_.object_mode = old_
shading_ = bpy.data.workspaces.get("Shading")
check(shading_ is not None and W.workspace_kind(shading_) is None, "Shading is an extra workspace")
ops_ = ws_ops(ws_settings_log(shading_))
check("m3d.workspace_reset" in [o[0] for o in ops_] and not any(o[0] == "m3d.dock_tab_toggle" for o in ops_), "extra workspace: reset, no dock tabs")

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

# Save Layouts as Default writes the startup file (into the temp config folder here, never the real one).
startup_ = os.path.join(TEST_CONFIG, "config", "startup.blend")
check(not os.path.exists(startup_), "no startup file before saving")
bpy.ops.wm.save_homefile()
check(os.path.exists(startup_), "Save Layouts as Default wrote " + startup_)
os.remove(startup_)

print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)

