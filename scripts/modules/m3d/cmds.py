# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
A subset of Maya's `maya.cmds` for Maelstrom3D, so Maya habits and simple Maya scripts work:

    import m3d.cmds as cmds
    cube, node = cmds.polyCube(w=2, h=1, d=1, n="box")
    cmds.move(0, 0, 2, cube, relative=True)
    cmds.setAttr(cube + ".rotateZ", 45)

Flags accept Maya's long and short names. Note: Blender is Z-up, so "height" runs along Z (a plane's along Y).
Primitives keep their creation settings: `setAttr("box.subdivisionsWidth", 4)` rebuilds the mesh until it is edited.
"""

import fnmatch
import math

import bpy

__all__ = (
    "polyCube", "polySphere", "polyCylinder", "polyCone", "polyPlane", "polyTorus", "polySmooth",
    "spaceLocator", "group", "parent", "duplicate", "delete", "select", "ls", "move", "rotate", "scale",
    "xform", "setAttr", "getAttr", "rename", "objExists", "nodeType", "hide", "showHidden", "makeIdentity",
    "currentTime", "playbackOptions", "setKeyframe", "file", "undo", "redo", "refresh",
)


# -----------------------------------------------------------------------------
# Helpers

def _flag(kw, long, short, default=None):
    for key in (long, short):
        if key in kw:
            return kw[key]
    return default


def _get(name):
    ob = bpy.data.objects.get(name)
    if ob is None:
        raise ValueError("No object matches name: " + name)
    return ob


def _targets(args):
    """Objects named in args (strings or lists), else the selection, like Maya."""
    names = []
    for a in args:
        names.extend(a if isinstance(a, (list, tuple)) else [a])
    return [_get(n) for n in names] if names else list(bpy.context.selected_objects)


def _unique(prefix):
    i = 1
    while bpy.data.objects.get(f"{prefix}{i}") is not None:
        i += 1
    return f"{prefix}{i}"


def _object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


# Flag names per input (Maya's long and short names, plus the attribute-style ones), per primitive.
_AXIS = ("subdivisionsAxis", "subdivisionsX", "sa", "sx")
_HEIGHT_DIVS = ("subdivisionsHeight", "subdivisionsY", "sh", "sy")
_CAPS = ("subdivisionsCaps", "subdivisionsZ", "sc", "sz")
_RADIUS, _HEIGHT = ("radius", "r"), ("height", "h")
_FLAGS = {
    'CUBE': {"width": ("width", "w"), "height": _HEIGHT, "depth": ("depth", "d"),
             "sub_width": ("subdivisionsWidth", "subdivisionsX", "sx"), "sub_height": _HEIGHT_DIVS,
             "sub_depth": ("subdivisionsDepth", "subdivisionsZ", "sz")},
    'SPHERE': {"radius": _RADIUS, "sub_axis": _AXIS, "sub_height": _HEIGHT_DIVS},
    'CYLINDER': {"radius": _RADIUS, "height": _HEIGHT, "sub_axis": _AXIS, "sub_height": _HEIGHT_DIVS, "sub_caps": _CAPS},
    'CONE': {"radius": _RADIUS, "height": _HEIGHT, "sub_axis": _AXIS, "sub_height": _HEIGHT_DIVS, "sub_caps": _CAPS},
    'PLANE': {"width": ("width", "w"), "height": _HEIGHT, "sub_width": ("subdivisionsWidth", "subdivisionsX", "sx"),
              "sub_height": _HEIGHT_DIVS},
    'TORUS': {"radius": _RADIUS, "section_radius": ("sectionRadius", "sr"), "sub_axis": _AXIS,
              "sub_height": _HEIGHT_DIVS},
}


def _primitive(prefix, node, kind, kw, **defaults):
    """A polygon primitive with live inputs (see m3d_inputs); `defaults` are the command's own starting values."""
    import m3d_inputs
    _object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.m3d.add_primitive(kind=kind)
    ob = bpy.context.active_object
    values = dict(defaults)
    for prop, names in _FLAGS[kind].items():
        for name in names:
            if name in kw:
                values[prop] = kw[name]
    m3d_inputs.set_inputs(ob, **values)
    bpy.context.view_layer.update()   # So dimensions read right away.
    ob.name = _flag(kw, "name", "n") or _unique(prefix)
    ob.data.name = ob.name + "Shape"
    return [ob.name, _unique(node)]


# -----------------------------------------------------------------------------
# Creation: the inputs stay on the object, so setAttr box.subdivisionsWidth 4 rebuilds it.

def polyCube(**kw):
    return _primitive("pCube", "polyCube", 'CUBE', kw)


def polySphere(**kw):
    return _primitive("pSphere", "polySphere", 'SPHERE', kw)


def polyCylinder(**kw):
    return _primitive("pCylinder", "polyCylinder", 'CYLINDER', kw)


def polyCone(**kw):
    return _primitive("pCone", "polyCone", 'CONE', kw)


def polyPlane(**kw):
    return _primitive("pPlane", "polyPlane", 'PLANE', kw, sub_width=10, sub_height=10)


def polyTorus(**kw):
    return _primitive("pTorus", "polyTorus", 'TORUS', kw, sub_axis=20, sub_height=20)


def spaceLocator(**kw):
    _object_mode()
    ob = bpy.data.objects.new(_flag(kw, "name", "n") or _unique("locator"), None)
    ob.empty_display_type = 'PLAIN_AXES'
    bpy.context.collection.objects.link(ob)
    return [ob.name]


def polySmooth(*args, **kw):
    for ob in _targets(args):
        mod = ob.modifiers.new(_unique("polySmoothFace"), 'SUBSURF')
        mod.levels = mod.render_levels = _flag(kw, "divisions", "dv", 1)
    return [m.name for ob in _targets(args) for m in ob.modifiers[-1:]]


# -----------------------------------------------------------------------------
# Hierarchy, duplicate, delete

def group(*args, **kw):
    obs = [] if _flag(kw, "empty", "em", False) else _targets(args)
    grp = bpy.data.objects.new(_flag(kw, "name", "n") or _unique("group"), None)
    bpy.context.collection.objects.link(grp)
    bpy.context.view_layer.update()
    for ob in obs:
        world = ob.matrix_world.copy()
        ob.parent = grp
        ob.matrix_world = world
    return grp.name


def parent(*args, **kw):
    obs = _targets(args)
    if _flag(kw, "world", "w", False):
        new_parent, children = None, obs
    else:
        new_parent, children = obs[-1], obs[:-1]
    for ob in children:
        world = ob.matrix_world.copy()
        ob.parent = new_parent
        ob.matrix_world = world
    return [ob.name for ob in children]


def duplicate(*args, **kw):
    names = []
    for ob in _targets(args):
        copy = ob.copy()
        if ob.data is not None:
            copy.data = ob.data.copy()
        for coll in ob.users_collection:
            coll.objects.link(copy)
        copy.name = _flag(kw, "name", "n") or ob.name.rstrip("0123456789") + "1"
        names.append(copy.name)
    select(names)
    return names


def delete(*args, **kw):
    obs = _targets(args)
    if _flag(kw, "constructionHistory", "ch", False):
        import m3d_inputs
        for ob in obs:
            with bpy.context.temp_override(active_object=ob, selected_objects=[ob],
                                           selected_editable_objects=[ob]):
                bpy.ops.object.convert(target='MESH')
            m3d_inputs.clear(ob)
        return
    for ob in obs:
        bpy.data.objects.remove(ob)


# -----------------------------------------------------------------------------
# Selection and queries

def select(*args, **kw):
    if _flag(kw, "clear", "cl", False):
        for ob in bpy.context.selected_objects:
            ob.select_set(False)
        return
    names = []
    for a in args:
        names.extend(a if isinstance(a, (list, tuple)) else [a])
    obs = [ob for pattern in names for ob in bpy.context.scene.objects if fnmatch.fnmatchcase(ob.name, pattern)]
    add = _flag(kw, "add", "af", False)
    if _flag(kw, "deselect", "d", False):
        for ob in obs:
            ob.select_set(False)
        return
    if _flag(kw, "toggle", "tgl", False):
        for ob in obs:
            ob.select_set(not ob.select_get())
        return
    if not add:
        for ob in bpy.context.selected_objects:
            ob.select_set(False)
    for ob in obs:
        ob.select_set(True)
    if obs:
        bpy.context.view_layer.objects.active = obs[-1]


def ls(*patterns, **kw):
    obs = bpy.context.selected_objects if _flag(kw, "selection", "sl", False) else bpy.context.scene.objects
    if patterns:
        obs = [ob for ob in obs if any(fnmatch.fnmatchcase(ob.name, p) for p in patterns)]
    kind = _flag(kw, "type", "typ")
    if kind:
        wanted = {"mesh": 'MESH', "camera": 'CAMERA', "light": 'LIGHT', "joint": 'ARMATURE',
                  "locator": 'EMPTY', "transform": None, "nurbsCurve": 'CURVE'}.get(kind, kind.upper())
        obs = [ob for ob in obs if wanted is None or ob.type == wanted]
    return [ob.name for ob in obs]


def objExists(name):
    return bpy.data.objects.get(name) is not None


def nodeType(name):
    return "transform"


# -----------------------------------------------------------------------------
# Transforms and attributes

def _transform(attr, args, kw, convert=lambda v: v):
    values = [a for a in args if isinstance(a, (int, float))]
    names = [a for a in args if not isinstance(a, (int, float))]
    relative = _flag(kw, "relative", "r", False)
    for ob in _targets(names):
        current = getattr(ob, attr)
        new = [convert(v) for v in values]
        if relative:
            new = [c + n if attr != "scale" else c * n for c, n in zip(current, new)]
        setattr(ob, attr, new)


def move(*args, **kw):
    _transform("location", args, kw)


def rotate(*args, **kw):
    _transform("rotation_euler", args, kw, math.radians)


def scale(*args, **kw):
    _transform("scale", args, kw)


_ATTRS = {
    "translate": ("location", None), "t": ("location", None),
    "rotate": ("rotation_euler", None), "r": ("rotation_euler", None),
    "scale": ("scale", None), "s": ("scale", None),
}
for _i, _axis in enumerate("XYZ"):
    for _long, _short, _prop in (("translate", "t", "location"), ("rotate", "r", "rotation_euler"),
                                 ("scale", "s", "scale")):
        _ATTRS[_long + _axis] = _ATTRS[_short + _axis.lower()] = (_prop, _i)


def _split(plug):
    name, _, attr = plug.partition(".")
    return _get(name), attr


def _input(ob, attr):
    """The primitive input behind "<object>.<attr>" (Maya attribute names), or None for another attribute."""
    import m3d_inputs
    prop = m3d_inputs.ATTRS.get(attr)
    if prop is None:
        return None
    if prop not in m3d_inputs.KINDS.get(ob.m3d_input.kind, ("", ()))[1]:
        raise ValueError("%s has no attribute %s (no history, or not a primitive that has it)" % (ob.name, attr))
    return prop


def setAttr(plug, *values, **_kw):
    ob, attr = _split(plug)
    prop = _input(ob, attr)
    if prop:
        import m3d_inputs
        m3d_inputs.set_inputs(ob, **{prop: values[0]})
        bpy.context.view_layer.update()
        return
    if attr in {"visibility", "v"}:
        ob.hide_viewport = not values[0]
        return
    prop, index = _ATTRS[attr]
    convert = math.radians if prop == "rotation_euler" else float
    if index is None:
        setattr(ob, prop, [convert(v) for v in values])
    else:
        getattr(ob, prop)[index] = convert(values[0])


def getAttr(plug, **_kw):
    ob, attr = _split(plug)
    prop = _input(ob, attr)
    if prop:
        return getattr(ob.m3d_input, prop)
    if attr in {"visibility", "v"}:
        return not ob.hide_viewport
    prop, index = _ATTRS[attr]
    convert = math.degrees if prop == "rotation_euler" else float
    value = getattr(ob, prop)
    return convert(value[index]) if index is not None else [tuple(convert(v) for v in value)]


def xform(*args, **kw):
    ob = _targets([a for a in args if isinstance(a, str)])[0]
    if _flag(kw, "query", "q", False):
        if _flag(kw, "translation", "t", False):
            return list(ob.matrix_world.translation if _flag(kw, "worldSpace", "ws", False) else ob.location)
        if _flag(kw, "rotation", "ro", False):
            return [math.degrees(v) for v in ob.rotation_euler]
        if _flag(kw, "scale", "s", False):
            return list(ob.scale)
        return None
    for long, short, setter in (("translation", "t", move), ("rotation", "ro", rotate), ("scale", "s", scale)):
        value = _flag(kw, long, short)
        if value is not None:
            setter(*value, ob.name, relative=_flag(kw, "relative", "r", False))


def rename(*args):
    if len(args) == 1:
        old, new = bpy.context.active_object.name, args[0]
    else:
        old, new = args
    ob = _get(old)
    ob.name = new
    return ob.name


def hide(*args, **_kw):
    for ob in _targets(args):
        ob.hide_set(True)


def showHidden(*args, **kw):
    obs = list(bpy.context.scene.objects) if _flag(kw, "all", "a", False) else _targets(args)
    for ob in obs:
        ob.hide_set(False)


def makeIdentity(*args, **kw):
    obs = _targets(args)
    apply = _flag(kw, "apply", "a", False)
    t, r, s = (_flag(kw, "translate", "t", True), _flag(kw, "rotate", "r", True), _flag(kw, "scale", "s", True))
    for ob in obs:
        if apply:
            with bpy.context.temp_override(active_object=ob, selected_editable_objects=[ob], object=ob):
                bpy.ops.object.transform_apply(location=t, rotation=r, scale=s)
        else:
            if t:
                ob.location = (0, 0, 0)
            if r:
                ob.rotation_euler = (0, 0, 0)
            if s:
                ob.scale = (1, 1, 1)


# -----------------------------------------------------------------------------
# Animation

def currentTime(*args, **kw):
    scene = bpy.context.scene
    if _flag(kw, "query", "q", False) or not args:
        return scene.frame_current
    scene.frame_set(int(args[0]))
    return scene.frame_current


def playbackOptions(**kw):
    scene = bpy.context.scene
    if _flag(kw, "query", "q", False):
        if _flag(kw, "minTime", "min", False) or _flag(kw, "animationStartTime", "ast", False):
            return scene.frame_start
        return scene.frame_end
    start = _flag(kw, "minTime", "min", _flag(kw, "animationStartTime", "ast"))
    end = _flag(kw, "maxTime", "max", _flag(kw, "animationEndTime", "aet"))
    if start is not None:
        scene.frame_start = int(start)
    if end is not None:
        scene.frame_end = int(end)


def setKeyframe(*args, **kw):
    frame = _flag(kw, "time", "t", bpy.context.scene.frame_current)
    attrs = _flag(kw, "attribute", "at")
    attrs = [attrs] if isinstance(attrs, str) else attrs
    count = 0
    for ob in _targets(args):
        props = {_ATTRS[a][0] for a in attrs} if attrs else {"location", "rotation_euler", "scale"}
        for prop in props:
            ob.keyframe_insert(prop, frame=frame)
            count += 1
    return count


# -----------------------------------------------------------------------------
# Files and misc

def file(path=None, **kw):
    if _flag(kw, "new", "new", False):
        bpy.ops.wm.read_homefile(app_template="")
    elif _flag(kw, "open", "o", False):
        bpy.ops.wm.open_mainfile(filepath=path)
    elif _flag(kw, "save", "s", False):
        bpy.ops.wm.save_mainfile()
    elif _flag(kw, "rename", "rn", False):
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=False)
    return bpy.data.filepath


def undo():
    bpy.ops.ed.undo()


def redo():
    bpy.ops.ed.redo()


def refresh(**_kw):
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()
