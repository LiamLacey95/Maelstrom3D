# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Sculpt workspace (F2) for Maelstrom3D: the brush tray (left), the dock pages (Geometry, Mask, Face Sets, Deform,
Paint, Display, Objects), the Sculpt Status Line, shelf items and the operators behind them.

The layout is built by tools/m3d/build_startup.py (phase1_sculpt), the tabs are DOCK_TABS['SCULPT'] in
m3d_workspace.py, the menus and shelves in m3d_ui.py. Controls that stock Blender already draws (brush settings,
falloff, stroke, palette) are the stock panel classes, re-used on the dock pages.
"""

from ast import literal_eval

import bpy
import bpy.utils.previews
from bpy.types import Operator, Panel
from mathutils import Vector
from bl_ui.properties_paint_common import (
    BrushSelectPanel, ColorPalettePanel, DisplayPanel, FalloffPanel, SmoothStrokePanel, StrokePanel,
    UnifiedPaintPanel, brush_settings, brush_settings_advanced, brush_texture_settings)

from m3d_mode import _button
from m3d_workspace import _PagePanel

# -----------------------------------------------------------------------------
# Brushes

BRUSH_ASSET = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"
# (label, asset name): the tray grid, the Sculpt shelf and the hotbox
BRUSHES = (
    ("Draw", "Draw"), ("Clay Strips", "Clay Strips"), ("Clay", "Clay"), ("Smooth", "Smooth"),
    ("Grab", "Grab"), ("Elastic Grab", "Elastic Grab"), ("Snake Hook", "Snake Hook"),
    ("Inflate/Deflate", "Inflate/Deflate"), ("Pinch/Magnify", "Pinch/Magnify"), ("Crease Sharp", "Crease Sharp"),
    ("Flatten/Contrast", "Flatten/Contrast"), ("Scrape/Fill", "Scrape/Fill"), ("Layer", "Layer"),
    ("Mask", "Mask"), ("Face Set Paint", "Face Set Paint"),
)
PAINT_BRUSHES = tuple((name, name) for name in ("Paint Soft", "Paint Hard", "Airbrush", "Paint Blend", "Blur", "Smear"))
# Shift+1 ... Shift+7 (the keymap file repeats the names; test_m3d.py checks them)
BRUSH_KEYS = ("Draw", "Clay Strips", "Smooth", "Grab", "Inflate/Deflate", "Pinch/Magnify", "Crease Sharp")


def brush_props(name):
    return {"asset_library_type": 'ESSENTIALS', "relative_asset_identifier": BRUSH_ASSET + name}


def brush_item(label, name):
    """Brush button for a shelf (the optional fourth entry is the button text)."""
    return ("brush.asset_activate", 'NONE', brush_props(name), label)


def active_brush_id(context):
    ts = context.tool_settings
    paint = ts.image_paint if context.mode == 'PAINT_TEXTURE' else ts.sculpt
    ref = paint.brush_asset_reference if paint else None
    return ref.relative_asset_identifier if ref else ""


def is_active(context, idname, props):
    """True for the button of the brush that is active (shelf and tray draw it pressed)."""
    return idname == "brush.asset_activate" and props.get("relative_asset_identifier") == active_brush_id(context)


def draw_brush_column(layout):
    """Hotbox section: pick a brush (the hotbox runs in the viewport, so the operator is called directly)."""
    layout.label(text="Brushes")
    for label, name in BRUSHES:
        o = layout.operator("brush.asset_activate", text=label)
        for key, value in brush_props(name).items():
            setattr(o, key, value)


# -----------------------------------------------------------------------------
# Tiles: small buttons showing a thumbnail (brushes, stroke types, alphas, matcaps)

_previews = None   # preview collection: "<asset><name>" -> brush thumbnail copied from the essentials .blend,
#                    "stroke:<kind>" / "alpha:<name>" -> thumbnails drawn by the functions below
_missing = set()   # brushes whose thumbnail can't be loaded (their tile is a text button)


def _collection():
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()
    return _previews


def brush_icons(asset, names):
    """{name: icon id} of the thumbnails of the brushes `names` in the library file named by `asset`
    (BRUSH_ASSET). A file is read once for the brushes not loaded yet: the thumbnails are copied into a
    preview collection and the brushes unlinked again, so the .blend file gains no data. A brush without a
    thumbnail is left out."""
    todo = [n for n in names if asset + n not in (_previews or ()) and asset + n not in _missing]
    if todo:
        import array
        import os
        _collection()
        path = os.path.join(bpy.utils.system_resource('DATAFILES'), "assets", asset.partition(".blend/")[0] + ".blend")
        data = bpy.data
        had_brushes, had_libs = {b.as_pointer() for b in data.brushes}, {lib.as_pointer() for lib in data.libraries}
        loaded = []
        try:
            with data.libraries.load(path, link=True, assets_only=True) as (src, dst):
                dst.brushes = [n for n in todo if n in src.brushes]
            loaded = list(dst.brushes)
        except OSError:
            pass
        for brush in loaded:
            w, h = brush.preview.image_size if brush.preview else (0, 0)
            if w and h:
                pixels = array.array('f', bytes(16 * w * h))
                brush.preview.image_pixels_float.foreach_get(pixels)
                thumb = _previews.new(asset + brush.name)
                thumb.image_size = (w, h)
                thumb.image_pixels_float.foreach_set(pixels)
        data.batch_remove([b for b in loaded if b.as_pointer() not in had_brushes])
        for lib in [lib for lib in data.libraries if lib.as_pointer() not in had_libs]:
            data.libraries.remove(lib)
        _missing.update(asset + n for n in todo if asset + n not in _previews)
    return {n: _previews[asset + n].icon_id for n in names if _previews and asset + n in _previews}


class M3D_OT_brush_pick(Operator):
    """Pick a brush from a tile (the tooltip is the brush's name)"""
    bl_idname = "m3d.brush_pick"
    bl_label = "Pick Brush"
    bl_options = {'INTERNAL'}

    identifier: bpy.props.StringProperty()   # relative asset identifier, "brushes/<file>.blend/Brush/<name>"

    @classmethod
    def description(cls, _context, props):
        return props.identifier.rpartition("/")[2]

    def execute(self, _context):
        return bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier=self.identifier)


def tile_grid(layout, context, units_x=0, min_px=46):
    """Grid for square tiles (icon-only buttons this tall draw their thumbnail at the button size). The columns and
    the tile height follow the width of the region (or of a popover, `units_x` wide) so the tiles stay square."""
    ui_scale = context.preferences.system.ui_scale or 1.0   # 0 without a window
    width = units_x * 20 * ui_scale if units_x else context.region.width if context.region else 300
    avail = width - 24 * ui_scale
    columns = min(max(int(avail // (min_px * ui_scale)), 3), 8)
    flow = layout.grid_flow(row_major=True, columns=columns, even_columns=True, even_rows=True, align=True)
    flow.scale_y = avail / columns / (20 * ui_scale)
    return flow


def brush_tiles(layout, context, asset, brushes):
    """Grid of small brush tiles: each is the brush's thumbnail, the name is the tooltip and the active brush is
    pressed. `brushes` are (label, name) pairs of the library file `asset`."""
    icons = brush_icons(asset, [name for _label, name in brushes])
    flow = tile_grid(layout, context)
    active = active_brush_id(context)
    for label, name in brushes:
        icon = icons.get(name, 0)
        o = flow.operator("m3d.brush_pick", text="" if icon else label, icon_value=icon, depress=asset + name == active)
        o.identifier = asset + name


# Stroke types (Brush.stroke_method): (identifier, label, what it does)
STROKES = (
    ('DOTS', "Dots", "One dab for every mouse movement"),
    ('DRAG_DOT', "Drag Dot", "One dab that follows the cursor while you drag"),
    ('SPACE', "Space", "Dabs placed along the stroke at a fixed spacing"),
    ('AIRBRUSH', "Airbrush", "Keeps adding while the button is held, even without moving"),
    ('ANCHORED', "Anchored", "Drag out the size of one dab from where you pressed"),
    ('LINE', "Line", "Drag a straight line of dabs"),
    ('CURVE', "Curve", "Draw along a curve you edit with control points"),
)


def stroke_pixels(kind, n=64):
    """A little picture of a stroke type, n x n RGBA floats (light shapes on a dark tile)."""
    import numpy as np
    y, x = np.mgrid[0:n, 0:n] + 0.5
    s = n / 64.0

    def disc(cx, cy, r):
        return np.clip(r * s - np.hypot(x - cx * s, y - cy * s) + 0.5, 0, 1)

    def seg(a, b, w):
        (ax, ay), (bx, by) = (np.array(a) * s), (np.array(b) * s)
        t = np.clip(((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2), 0, 1)
        return np.clip(w * s - np.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay))) + 0.5, 0, 1)

    def ring(cx, cy, r, w):
        return np.clip(w * s - np.abs(np.hypot(x - cx * s, y - cy * s) - r * s) + 0.5, 0, 1)

    shapes = {
        'DOTS': lambda: [disc(cx, 36 - 4 * (i % 2), 4.5) for i, cx in enumerate((9, 20, 32, 44, 55))],
        'DRAG_DOT': lambda: [seg((8, 32), (38, 32), 1.6), disc(46, 32, 10)],
        'SPACE': lambda: [seg((9, 42), (55, 22), 6.5)],
        'AIRBRUSH': lambda: [np.exp(-((x - 32 * s) ** 2 + (y - 32 * s) ** 2) / (2 * (11 * s) ** 2))],
        'ANCHORED': lambda: [ring(32, 32, 21, 2), disc(32, 32, 4.5), seg((32, 32), (53, 32), 2)],
        'LINE': lambda: [seg((9, 52), (55, 12), 3), disc(9, 52, 6), disc(55, 12, 6)],
        'CURVE': lambda: [seg((9, 46), (23, 20), 1.4), seg((55, 18), (41, 44), 1.4), disc(9, 46, 5), disc(55, 18, 5),
                          *(disc(*((1 - t) ** 3 * np.array((9, 46)) + 3 * (1 - t) ** 2 * t * np.array((23, 20))
                                   + 3 * (1 - t) * t ** 2 * np.array((41, 44)) + t ** 3 * np.array((55, 18))), 2.6)
                            for t in np.linspace(0, 1, 40))],
    }
    cover = np.max(shapes[kind](), axis=0)[..., None]
    px = np.ones((n, n, 4), np.float32)
    px[..., :3] = 0.17 + (0.93 - 0.17) * cover
    return px


STARTER_ALPHAS = ("Clouds", "Fine Noise", "Cells", "Ridges", "Dots", "Stripes", "Bricks", "Star")
ALPHA_SIZE = 256   # pixels of a starter alpha's image


def alpha_pixels(name, n):
    """Starter alpha `name` (clouds, noise and patterns that tile, and one stamp) as n x n RGBA floats."""
    import numpy as np
    rng = np.random.default_rng(sum(map(ord, name)))
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n

    def smooth(t):
        return t * t * (3 - 2 * t)

    def noise(cells):
        grid = rng.random((cells, cells))
        gx, gy = x * cells, y * cells
        x0, y0 = gx.astype(int) % cells, gy.astype(int) % cells
        x1, y1 = (x0 + 1) % cells, (y0 + 1) % cells
        fx, fy = smooth(gx % 1), smooth(gy % 1)
        return (grid[y0, x0] * (1 - fx) + grid[y0, x1] * fx) * (1 - fy) + (grid[y1, x0] * (1 - fx) + grid[y1, x1] * fx) * fy

    def clouds():
        return sum(noise(c) * w for c, w in ((4, 1.0), (8, 0.5), (16, 0.25), (32, 0.125)))

    if name == "Clouds":
        v = clouds()
    elif name == "Fine Noise":
        v = noise(32) + 0.7 * noise(64) + 0.5 * noise(128)
    elif name == "Cells":
        pts = rng.random((20, 2))
        d = np.min([np.hypot((x - px + 0.5) % 1 - 0.5, (y - py + 0.5) % 1 - 0.5) for px, py in pts], axis=0)
        v = smooth(1 - d / d.max())
    elif name == "Ridges":
        v = (1 - np.abs(2 * clouds() / 1.875 - 1)) ** 3
    elif name == "Dots":
        v = smooth(np.clip((0.4 - np.hypot(x * 8 % 1 - 0.5, y * 8 % 1 - 0.5)) / 0.25, 0, 1))
    elif name == "Stripes":
        v = 0.5 + 0.5 * np.sin(2 * np.pi * (6 * x + 0.5 * np.sin(4 * np.pi * y)))
    elif name == "Bricks":
        mortar_y = np.clip((y * 6 % 1 - 0.05) / 0.06, 0, 1)
        mortar_x = np.clip(((x * 3 + np.floor(y * 6) % 2 * 0.5) % 1 - 0.03) / 0.05, 0, 1)
        v = mortar_x * mortar_y
    else:   # Star
        v = np.clip((0.3 + 0.13 * np.cos(5 * np.arctan2(y - 0.5, x - 0.5)) - np.hypot(x - 0.5, y - 0.5)) / 0.05, 0, 1)
    v = (v - v.min()) / ((v.max() - v.min()) or 1.0)
    px = np.ones((n, n, 4), np.float32)
    px[..., :3] = v[..., None]
    return px


def _thumbs(prefix, names, make):
    """{name: icon id} of thumbnails drawn by `make(name)` (64 x 64 RGBA floats), made on first use."""
    import numpy as np
    coll = _collection()
    for name in names:
        if prefix + name not in coll:
            thumb = coll.new(prefix + name)
            thumb.image_size = (64, 64)
            thumb.image_pixels_float.foreach_set(np.ascontiguousarray(make(name), np.float32).ravel())
    return {name: coll[prefix + name].icon_id for name in names}


def stroke_icons():
    return _thumbs("stroke:", [k for k, _l, _d in STROKES], lambda kind: stroke_pixels(kind))


def alpha_dir(create=False):
    """The alpha library: one <name>.blend (a Texture with its image) and <name>.png (its thumbnail) per alpha."""
    return bpy.utils.user_resource('DATAFILES', path="m3d_alphas", create=create)


def alpha_names():
    """Alphas to pick from: the starter set (made when first used), then the ones loaded from image files."""
    import os
    folder = alpha_dir()
    found = sorted(f[:-6] for f in os.listdir(folder) if f.endswith(".blend")) if folder and os.path.isdir(folder) else []
    return [*STARTER_ALPHAS, *(n for n in found if n not in STARTER_ALPHAS)]


def alpha_icons(names):
    """{name: icon id} of the alphas' thumbnails: drawn for the starter set, the saved .png for the others."""
    import os
    coll = _collection()
    icons = _thumbs("alpha:", [n for n in names if n in STARTER_ALPHAS], lambda name: alpha_pixels(name, 64))
    for name in names:
        if name not in icons:
            png = os.path.join(alpha_dir(), name + ".png")
            if "alpha:" + name not in coll and os.path.isfile(png):
                coll.load("alpha:" + name, png, 'IMAGE')
            if "alpha:" + name in coll:
                icons[name] = coll["alpha:" + name].icon_id
    return icons


def stroke_tiles(layout, context, brush, units_x=0):
    """Stroke type picker: a tile per Brush.stroke_method with a little picture of it."""
    icons = stroke_icons()
    flow = tile_grid(layout, context, units_x, min_px=38)
    for kind, label, _desc in STROKES:
        o = flow.operator("m3d.stroke_pick", text="", icon_value=icons[kind], depress=brush.stroke_method == kind)
        o.stroke = kind
    layout.label(text=next(label for kind, label, _d in STROKES if kind == brush.stroke_method))


def alpha_tiles(layout, context, brush, units_x=0):
    """Alpha picker: None, then a tile per alpha (the one the brush uses is pressed)."""
    names = alpha_names()
    icons = alpha_icons(names)
    flow = tile_grid(layout, context, units_x, min_px=38)
    flow.operator("m3d.alpha_pick", text="None", depress=brush.texture is None).name = ""
    active = brush.texture.name if brush.texture else ""
    for name in names:
        o = flow.operator("m3d.alpha_pick", text="" if name in icons else name, icon_value=icons.get(name, 0),
                          depress=active == name)
        o.name = name


def studio_lights(context, kind):
    """The studio lights of one type: 'MATCAP' (matcaps) or 'STUDIO' (the built-in and user lights)."""
    return [sl for sl in context.preferences.studio_lights if sl.type == kind]


def light_tiles(layout, context, shading, units_x=0):
    """Matcap / studio light picker: a tile per light of the shading's light type (Flat has none)."""
    flow = tile_grid(layout, context, units_x, min_px=40)
    for sl in studio_lights(context, shading.light):
        icon = layout.enum_item_icon(shading, "studio_light", sl.name)
        o = flow.operator("m3d.light_pick", text="", icon_value=icon, depress=shading.studio_light == sl.name)
        o.name, o.kind = sl.name, shading.light
    name = shading.studio_light.rpartition(".")[0] or shading.studio_light
    layout.label(text=name.replace("_", " ").title())


# -----------------------------------------------------------------------------
# Helpers

def mesh_of(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'MESH' else None


def multires_of(ob):
    return next((m for m in ob.modifiers if m.type == 'MULTIRES'), None)


def ready(context, need):
    """Can a page with this need be used: None always, 'MESH' with an active mesh, 'SCULPT' also in Sculpt Mode."""
    if need is None:
        return True
    return mesh_of(context) is not None and (need == 'MESH' or context.mode == 'SCULPT')


def viewport(context):
    """The main 3D Viewport's space (docks and the top bar have none of their own)."""
    screen = context.screen
    areas = [a for a in screen.areas if a.type == 'VIEW_3D'] if screen else []
    return max(areas, key=lambda a: a.width * a.height).spaces.active if areas else None


def brush_mode(context):
    return UnifiedPaintPanel.get_brush_mode(context)


def active_tool(context):
    tools = context.workspace.tools if context.workspace else None
    return tools.from_space_view3d_mode('SCULPT') if tools else None


def tool_is_active(context, tool, op, props):
    cur = active_tool(context)
    if cur is None or cur.idname != tool:
        return False
    if not op:
        return True
    cur_props = cur.operator_properties(op)
    return all(getattr(cur_props, k, None) == v for k, v in props.items())


def reason(layout, text):
    layout.label(text=text, icon='INFO')


def grid(layout, context, items, columns=2, active=None):
    """Operator buttons: (label, idname, icon, props); `active(idname, props)` draws one pressed."""
    flow = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=True)
    for label, idname, icon, props in items:
        _button(flow, context, label, idname, icon, props,
                depress=bool(active and active(idname, props)))


def tools_grid(layout, context, items, columns=2):
    """Tool buttons: (label, tool id, operator, props). A click sets the tool; the work happens in the viewport."""
    flow = layout.grid_flow(row_major=True, columns=columns, even_columns=True, align=True)
    for label, tool, op, props in items:
        o = flow.operator("m3d.sculpt_tool", text=label, depress=tool_is_active(context, tool, op, props))
        o.tool, o.op, o.props, o.label = tool, op, repr(props), label


def split_props(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False


def ui_scale_factor(context):
    """Pixels per UI pixel at scale 1 (Resolution Scale and the display's DPI; both are 0 without a window)."""
    system = context.preferences.system
    return (system.ui_scale or 1.0) * (system.dpi or 72) / 72


def sculpt_brush(context):
    sculpt = context.tool_settings.sculpt
    return sculpt.brush if sculpt else None


def draw_size_strength(layout, context, brush, header=False, only=None):
    """Size and Strength sliders of the brush (`only`: just one of them): the scene-wide ones when Unified Size /
    Strength is on. In a header (the Status Line) the pressure and Unified buttons are left out."""
    caps = brush.sculpt_capabilities
    ups = context.tool_settings.sculpt.unified_paint_settings   # (the header has no brush tool: pass it in)
    if only in {None, "size"}:
        owner = ups if ups.use_unified_size else brush
        size = "unprojected_size" if owner.use_locked_size == 'SCENE' else "size"
        UnifiedPaintPanel.prop_unified(layout, context, brush, size, unified_paint_settings_override=ups,
                                       unified_name="use_unified_size", text="Size", slider=True, header=header,
                                       pressure_name="use_pressure_size" if caps.has_size_pressure and not header else None)
    if only in {None, "strength"}:
        UnifiedPaintPanel.prop_unified(layout, context, brush, "strength", unified_paint_settings_override=ups,
                                       unified_name="use_unified_strength", text="Strength", slider=True, header=header,
                                       pressure_name="use_pressure_strength" if caps.has_strength_pressure and not header
                                       else None)


def draw_hardness(layout, brush):
    """Hardness: how long the brush stays at full strength before it falls off (the Falloff curve shapes the rest)."""
    if brush.sculpt_capabilities.has_hardness:
        layout.prop(brush, "hardness", text="Hardness", slider=True)


def draw_direction(layout, brush, labels=True):
    """Add / Subtract (Brush.direction) as two buttons."""
    if brush.sculpt_capabilities.has_direction:
        row = layout.row(align=True)
        row.prop_enum(brush, "direction", 'ADD', text="Add" if labels else "", icon='ADD')
        row.prop_enum(brush, "direction", 'SUBTRACT', text="Subtract" if labels else "", icon='REMOVE')


def draw_lazy(layout, brush, label=True):
    """Lazy Mouse (Stabilize Stroke): the toggle and the radius the stroke lags behind the cursor by."""
    if brush.brush_capabilities.has_smooth_stroke:
        row = layout.row(align=True)
        row.prop(brush, "use_smooth_stroke", text="Lazy Mouse" if label else "", icon='MOD_SMOOTH', toggle=True)
        sub = row.row(align=True)
        sub.active = brush.use_smooth_stroke
        sub.prop(brush, "smooth_stroke_radius", text="Radius" if label else "", slider=True)


# -----------------------------------------------------------------------------
# Operators

class M3D_OT_sculpt_tool(Operator):
    """Pick a sculpt tool and its options; then use it in the 3D Viewport"""
    bl_idname = "m3d.sculpt_tool"
    bl_label = "Sculpt Tool"
    bl_options = {'INTERNAL'}

    tool: bpy.props.StringProperty()
    op: bpy.props.StringProperty(description="Operator whose options are set (empty: none)")
    props: bpy.props.StringProperty(default="{}")
    label: bpy.props.StringProperty()

    @classmethod
    def description(cls, _context, props):
        return (props.label or props.tool) + ": pick the tool, then use it in the viewport"

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name=self.tool, space_type='VIEW_3D')
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        tool = active_tool(context)
        if self.op and tool is not None and tool.idname == self.tool:
            options = tool.operator_properties(self.op)
            for key, value in literal_eval(self.props).items():
                setattr(options, key, value)
        self.report({'INFO'}, "%s: use it in the viewport" % (self.label or self.tool))
        return {'FINISHED'}


class M3D_OT_multires_subdivide(Operator):
    """Add a Multires level (the Multires modifier is added first when the mesh has none)"""
    bl_idname = "m3d.multires_subdivide"
    bl_label = "Multires Subdivide"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=(
        ('CATMULL_CLARK', "Subdivide", "Smooth subdivision (Catmull-Clark)"),
        ('SIMPLE', "Simple", "Subdivide without smoothing the shape"),
        ('LINEAR', "Linear", "Subdivide the faces linearly, keeping corners sharp"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'CATMULL_CLARK': "Add a Multires level, smoothing the shape", 'SIMPLE': "Add a Multires level without "
                "smoothing the shape", 'LINEAR': "Add a Multires level, keeping corners sharp"}[props.mode]

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        if ob.use_dynamic_topology_sculpting:
            self.report({'WARNING'}, "Turn off Dyntopo to use Multires")
            return {'CANCELLED'}
        try:
            if multires_of(ob) is None:
                bpy.ops.object.modifier_add(type='MULTIRES')
            bpy.ops.object.multires_subdivide(modifier=multires_of(ob).name, mode=self.mode)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_multires_level(Operator):
    """Go one Multires level up or down (viewport and sculpt level)"""
    bl_idname = "m3d.multires_level"
    bl_label = "Multires Level"
    bl_options = {'REGISTER', 'UNDO'}

    delta: bpy.props.IntProperty(default=1)

    @classmethod
    def description(cls, _context, props):
        return "Show and sculpt the %s Multires level" % ("next" if props.delta > 0 else "previous")

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is not None

    def execute(self, context):
        mod = multires_of(mesh_of(context))
        level = max(0, min(mod.total_levels, mod.sculpt_levels + self.delta))
        mod.levels = mod.sculpt_levels = level
        return {'FINISHED'}


class M3D_OT_multires_edit(Operator):
    """Delete the higher Multires levels, Unsubdivide, or Apply Base"""
    bl_idname = "m3d.multires_edit"
    bl_label = "Multires Edit"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=(
        ('DELETE_HIGHER', "Delete Higher", "Delete the levels above the current one"),
        ('UNSUBDIVIDE', "Unsubdivide", "Rebuild a lower level from the highest one"),
        ('APPLY_BASE', "Apply Base", "Copy the sculpted shape to the base mesh and keep the detail"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'DELETE_HIGHER': "Delete the Multires levels above the current one",
                'UNSUBDIVIDE': "Rebuild a lower Multires level from the highest one",
                'APPLY_BASE': "Apply the sculpted shape to the base mesh and keep the detail"}[props.action]

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is not None

    def execute(self, context):
        name = multires_of(mesh_of(context)).name
        run = {'DELETE_HIGHER': bpy.ops.object.multires_higher_levels_delete,
               'UNSUBDIVIDE': bpy.ops.object.multires_unsubdivide,
               'APPLY_BASE': bpy.ops.object.multires_base_apply}[self.action]
        try:
            run(modifier=name)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


def _show_in_sculpt(context, ob):
    """Make `ob` the only selected, active object (and back in Sculpt Mode if that is where we were)."""
    was_sculpt = context.mode == 'SCULPT'
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in context.selected_objects:
        other.select_set(False)
    ob.hide_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if was_sculpt and ob.type == 'MESH':
        bpy.ops.object.mode_set(mode='SCULPT')


class M3D_OT_sculpt_object(Operator):
    """Objects tab: pick a mesh, show or hide it, solo it, or append a duplicate"""
    bl_idname = "m3d.sculpt_object"
    bl_label = "Sculpt Object"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=(
        ('SELECT', "Sculpt", "Make this the active mesh"),
        ('VISIBLE', "Show / Hide", "Show or hide this mesh in the viewport"),
        ('SOLO', "Solo", "Hide every other mesh (again: show them)"),
        ('DUPLICATE', "Duplicate", "Append a copy of this mesh and sculpt it"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'SELECT': "Make this the active mesh", 'VISIBLE': "Show or hide this mesh in the viewport",
                'SOLO': "Hide every other mesh; click again to show them",
                'DUPLICATE': "Append a copy of this mesh and sculpt it"}[props.action]

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or ob.type != 'MESH':
            return {'CANCELLED'}
        meshes = [o for o in context.view_layer.objects if o.type == 'MESH']
        if self.action == 'VISIBLE':
            if ob is context.active_object and not ob.hide_get() and context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')   # leave Sculpt Mode before the mesh goes away
            ob.hide_set(not ob.hide_get())
            return {'FINISHED'}
        _show_in_sculpt(context, ob)
        if self.action == 'SOLO':
            others = [o for o in meshes if o is not ob]
            hide = not all(o.hide_get() for o in others)
            for o in others:
                o.hide_set(hide)
        elif self.action == 'DUPLICATE':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.duplicate()
            bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}


class M3D_OT_sculpt_add_mesh(Operator):
    """Add a mesh at the origin and start sculpting it"""
    bl_idname = "m3d.sculpt_add_mesh"
    bl_label = "Add Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=(
        ('SPHERE', "Sphere", ""), ('CUBE', "Cube", ""), ('CYLINDER', "Cylinder", ""), ('PLANE', "Plane", ""),
    ))

    @classmethod
    def description(cls, _context, props):
        return "Add a %s and start sculpting it" % props.kind.lower()

    def execute(self, _context):
        bpy.ops.m3d.add_primitive(kind=self.kind)
        bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}


# --- Ctrl gestures: masking and visibility (Ctrl+LMB in the Sculpt keymap, with Alt and Shift)

CTRL_MODES = (
    ('MASK', "Mask", "Ctrl: drag on the mesh paints mask, click on it smooths the mask, click off the mesh inverts "
     "it, drag off the mesh masks a rectangle (a tiny one clears the mask)"),
    ('UNMASK', "Unmask", "Ctrl+Alt: drag on the mesh erases mask, click on it sharpens the mask, drag off the mesh "
     "unmasks a rectangle"),
    ('HIDE_OUTSIDE', "Hide Outside", "Ctrl+Shift: drag hides everything outside a rectangle, click off the mesh "
     "shows everything, click on the mesh shows only that face set"),
    ('HIDE_INSIDE', "Hide Inside", "Ctrl+Shift+Alt: drag hides everything inside a rectangle"),
)
TINY_BOX = 16   # px: a Ctrl+drag off the mesh smaller than this (both sides) clears the mask instead of masking
BOX_OPS = {   # mode -> the rectangle operator and its options
    'MASK': ("paint.mask_box_gesture", {"mode": 'VALUE', "value": 1.0, "use_front_faces_only": True}),
    'UNMASK': ("paint.mask_box_gesture", {"mode": 'VALUE', "value": 0.0, "use_front_faces_only": True}),
    'HIDE_OUTSIDE': ("paint.hide_show", {"action": 'HIDE', "area": 'OUTSIDE'}),
    'HIDE_INSIDE': ("paint.hide_show", {"action": 'HIDE', "area": 'Inside'}),   # (sic: Blender's identifier)
}


def surface_under(context, co):
    """True when the sculpted mesh is under the region point `co`: not another object, and not a hidden face (the
    ray goes on through those, to the part of the mesh behind). The evaluated mesh is what ray_cast sees, so with
    Dyntopo on (the mesh is only written back after the stroke) it can be a little behind.
    ponytail: hidden faces are looked up by index on meshes without modifiers only."""
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
    ob = context.active_object
    origin = region_2d_to_origin_3d(context.region, context.region_data, co)
    vec = region_2d_to_vector_3d(context.region, context.region_data, co)
    depsgraph = context.evaluated_depsgraph_get()
    hide = None if ob.modifiers else ob.data.attributes.get(".hide_poly")
    step = 1e-4 * max(1.0, ob.dimensions.length)
    for _ in range(16):
        hit, location, _normal, index, hit_ob, _matrix = context.scene.ray_cast(depsgraph, origin, vec)
        if not hit or hit_ob.original != ob:
            return False
        if hide is None or index >= len(hide.data) or not hide.data[index].value:
            return True
        origin = location + vec * step
    return False


class M3D_OT_sculpt_ctrl(Operator):
    """Ctrl gestures of Sculpt Mode: masking and visibility, decided by what is under the cursor and by whether you
    click or drag"""
    bl_idname = "m3d.sculpt_ctrl"
    bl_label = "Mask / Hide Gesture"
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(items=CTRL_MODES, default='MASK')

    @classmethod
    def description(cls, _context, props):
        return next(desc for ident, _label, desc in CTRL_MODES if ident == props.mode)

    @classmethod
    def poll(cls, context):
        return (context.mode == 'SCULPT' and context.area is not None and context.area.type == 'VIEW_3D'
                and context.region_data is not None)

    def invoke(self, context, event):
        scale = ui_scale_factor(context)
        inputs = context.preferences.inputs
        self.threshold = (inputs.drag_threshold_tablet if event.is_tablet else inputs.drag_threshold_mouse) * scale
        self.tiny = TINY_BOX * scale
        self.start = self.end = Vector((event.mouse_region_x, event.mouse_region_y))
        self.on_mesh = surface_under(context, self.start)
        self.tainted = False   # a key was pressed or released since the button went down
        self.box = False
        self.handle = None
        self.region_ptr = context.region.as_pointer()   # (the region itself can go away while we wait)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.end = Vector((event.mouse_region_x, event.mouse_region_y))
            if self.box:
                context.area.tag_redraw()
            elif (self.end - self.start).length > self.threshold:
                return self.drag(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.end = Vector((event.mouse_region_x, event.mouse_region_y))
            return self.release(context)
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            return self.finish(context, {'CANCELLED'})
        if event.value in {'PRESS', 'RELEASE'}:
            self.tainted = True
        return {'RUNNING_MODAL', 'PASS_THROUGH'}

    def finish(self, context, result):
        if self.handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
            self.handle = None
            context.window.cursor_modal_restore()
            context.area.tag_redraw()
        return result

    def cancel(self, context):   # (the window went away while waiting)
        if self.handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
            self.handle = None

    def drag(self, context):
        if self.mode in {'MASK', 'UNMASK'} and self.on_mesh:
            # A Mask brush stroke from here. The stroke ends on the release of whatever was pressed last (the
            # window's last button or key event), so a key event in between would leave it running.
            if self.tainted:
                return self.finish(context, {'CANCELLED'})
            self.run("sculpt.brush_stroke", 'INVOKE_DEFAULT', mode='INVERT' if self.mode == 'UNMASK' else 'NORMAL',
                     brush_toggle='MASK')
            return self.finish(context, {'FINISHED'})
        self.box = True
        self.handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_box, (), 'WINDOW', 'POST_PIXEL')
        context.window.cursor_modal_set('CROSSHAIR')
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def release(self, context):
        if self.box:
            (x0, y0), (x1, y1) = self.start, self.end
            if max(abs(x1 - x0), abs(y1 - y0)) >= self.tiny:
                op, options = BOX_OPS[self.mode]
                self.run(op, 'EXEC_DEFAULT', xmin=int(min(x0, x1)), xmax=int(max(x0, x1)),
                         ymin=int(min(y0, y1)), ymax=int(max(y0, y1)), **options)
            elif self.mode == 'MASK':
                self.run("paint.mask_flood_fill", mode='VALUE', value=0.0)
        elif self.mode == 'MASK':
            if self.on_mesh:
                self.run("sculpt.mask_filter", filter_type='SMOOTH')
            else:
                self.run("paint.mask_flood_fill", mode='INVERT')
        elif self.mode == 'UNMASK' and self.on_mesh:
            self.run("sculpt.mask_filter", filter_type='SHARPEN')
        elif self.mode == 'HIDE_OUTSIDE':
            self.run("paint.hide_show_all", action='SHOW')
            if self.on_mesh:   # (with nothing hidden, Toggle hides every face set but the one under the cursor)
                self.run("sculpt.face_set_change_visibility", 'INVOKE_DEFAULT', mode='TOGGLE')
        return self.finish(context, {'FINISHED'})

    def run(self, idname, *context, **props):
        mod, name = idname.split(".")
        try:
            getattr(getattr(bpy.ops, mod), name)(*context, **props)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())

    def draw_box(self):
        region = bpy.context.region
        if region is None or region.as_pointer() != self.region_ptr:
            return
        import gpu
        from gpu_extras.batch import batch_for_shader
        hide = self.mode.startswith('HIDE')
        scale = ui_scale_factor(bpy.context)
        (x0, y0), (x1, y1) = self.start, self.end
        gpu.state.blend_set('ALPHA')
        fill = gpu.shader.from_builtin('UNIFORM_COLOR')
        fill.uniform_float("color", (1.0, 0.55, 0.15, 0.12) if hide else (0.9, 0.9, 0.9, 0.12))
        batch_for_shader(fill, 'TRI_FAN', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]}).draw(fill)
        line = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        line.uniform_float("viewportSize", (region.width, region.height))
        line.uniform_float("lineWidth", 1.5 * scale)
        line.uniform_float("color", (1.0, 0.65, 0.25, 1.0) if hide else (1.0, 1.0, 1.0, 1.0))
        batch_for_shader(line, 'LINE_STRIP', {"pos": [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0), (x0, y0, 0)]}).draw(line)
        gpu.state.blend_set('NONE')


# --- Pickers behind the tiles

class M3D_OT_stroke_pick(Operator):
    """Pick the stroke type of the brush"""
    bl_idname = "m3d.stroke_pick"
    bl_label = "Pick Stroke Type"
    bl_options = {'INTERNAL'}

    stroke: bpy.props.StringProperty()   # a Brush.stroke_method

    @classmethod
    def description(cls, _context, props):
        return next((f"{label}: {desc}" for kind, label, desc in STROKES if kind == props.stroke), "Stroke type")

    @classmethod
    def poll(cls, context):
        return sculpt_brush(context) is not None

    def execute(self, context):
        sculpt_brush(context).stroke_method = self.stroke
        return {'FINISHED'}


def set_alpha(brush, texture):
    """Use `texture` (or none) as the brush's alpha: it is mapped onto the brush, once. (A brush from the asset
    library is linked data, which can only point at linked data: the alphas are linked from the alpha library.)"""
    brush.texture = texture
    if texture is not None:
        slot = brush.texture_slot
        slot.map_mode = 'AREA_PLANE'
        slot.offset = (0.0, 0.0, 0.0)
        slot.scale = (1.0, 1.0, 1.0)
        slot.angle = 0.0


def store_alpha(name, image, thumb):
    """Write a Texture named `name` showing `image` (packed into it, clipped at the edge) to the alpha library with
    its 64 x 64 thumbnail (`thumb`: RGBA floats), and take both out of this file again. Returns False when the
    folder can't be written."""
    import os
    folder = alpha_dir(create=True)
    if not folder:
        return False
    tex = bpy.data.textures.new(name, 'IMAGE')
    tex.image = image
    tex.extension = 'CLIP'
    picture = bpy.data.images.new(name + " thumbnail", 64, 64)
    picture.pixels.foreach_set(thumb.ravel())
    try:
        bpy.data.libraries.write(os.path.join(folder, name + ".blend"), {tex}, fake_user=True)
        picture.filepath_raw = os.path.join(folder, name + ".png")
        picture.file_format = 'PNG'
        picture.save()
    except (OSError, RuntimeError):
        return False
    finally:
        bpy.data.textures.remove(tex)
        bpy.data.images.remove(picture)
        bpy.data.images.remove(image)
    return True


def link_alpha(name):
    """The alpha `name` linked from the library (made first if it is one of the starter set)."""
    import os
    path = os.path.join(alpha_dir(), name + ".blend")
    if not os.path.isfile(path) and name in STARTER_ALPHAS:
        image = bpy.data.images.new(name, ALPHA_SIZE, ALPHA_SIZE)
        image.colorspace_settings.name = 'Non-Color'   # (before the pixels: it resets them)
        image.pixels.foreach_set(alpha_pixels(name, ALPHA_SIZE).ravel())
        image.pack()
        store_alpha(name, image, alpha_pixels(name, 64))
    if not os.path.isfile(path):
        return None
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.textures = [name] if name in src.textures else []
    return dst.textures[0] if dst.textures else None


class M3D_OT_alpha_pick(Operator):
    """Use an alpha from the library as the brush texture (none: no alpha)"""
    bl_idname = "m3d.alpha_pick"
    bl_label = "Pick Alpha"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()   # an alpha_names() name, or empty for none

    @classmethod
    def description(cls, _context, props):
        return props.name or "No alpha"

    @classmethod
    def poll(cls, context):
        return sculpt_brush(context) is not None

    def execute(self, context):
        tex = link_alpha(self.name) if self.name else None
        if self.name and tex is None:
            self.report({'WARNING'}, "Can't read the alpha %s from %s" % (self.name, alpha_dir()))
            return {'CANCELLED'}
        set_alpha(sculpt_brush(context), tex)
        return {'FINISHED'}


class M3D_OT_alpha_load(Operator):
    """Add an image file to the alpha library and use it as the brush's alpha (a grey image: white is full strength)"""
    bl_idname = "m3d.alpha_load"
    bl_label = "Load Alpha"
    bl_options = {'INTERNAL'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return sculpt_brush(context) is not None

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import numpy as np
        import os
        name = os.path.splitext(os.path.basename(self.filepath))[0][:48]
        try:
            image = bpy.data.images.load(self.filepath)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        image.colorspace_settings.name = 'Non-Color'
        image.pack()
        small = image.copy()
        small.scale(64, 64)
        thumb = np.empty(64 * 64 * 4, np.float32)
        small.pixels.foreach_get(thumb)
        bpy.data.images.remove(small)
        if not store_alpha(name, image, thumb):
            self.report({'WARNING'}, "Can't write to the alpha library %s" % alpha_dir())
            return {'CANCELLED'}
        set_alpha(sculpt_brush(context), link_alpha(name))
        return {'FINISHED'}


class M3D_OT_light_pick(Operator):
    """Use this matcap (or studio light) in the 3D Viewport"""
    bl_idname = "m3d.light_pick"
    bl_label = "Pick Matcap"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()   # a StudioLight name
    kind: bpy.props.EnumProperty(items=(('MATCAP', "MatCap", ""), ('STUDIO', "Studio", "")), default='MATCAP')

    @classmethod
    def description(cls, _context, props):
        return (props.name.rpartition(".")[0] or props.name).replace("_", " ").title()

    def execute(self, context):
        space = viewport(context)
        if space is None:
            return {'CANCELLED'}
        space.shading.light = self.kind   # the studio_light list follows the light type
        space.shading.studio_light = self.name
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Dock pages: panels of the MODELING_TOOLKIT context, shown by page id (see m3d_workspace.DOCK_TABS)

class _Page(_PagePanel):
    """Panel that needs `need` (see `ready`)."""
    need = 'SCULPT'

    @classmethod
    def page_poll(cls, context):
        return ready(context, cls.need)


class _BrushPage(_PagePanel):
    """Panel for the active brush; the stock mixin classes (falloff, stroke ...) add their own poll."""
    @classmethod
    def page_poll(cls, context):
        stock = super(_PagePanel, cls)
        return ready(context, 'SCULPT') and brush_mode(context) is not None and (
            not hasattr(stock, "poll") or stock.poll(context))


def _gate(page, need):
    """The panel a page shows instead of its own when there is nothing to work on: what to do next."""
    def draw(self, context):
        col = self.layout.column(align=True)
        if mesh_of(context) is None:
            col.label(text="Select a mesh to sculpt")
            col.operator("m3d.sculpt_add_mesh", text="Add Sphere", icon='MESH_UVSPHERE').kind = 'SPHERE'
        else:
            col.label(text="Enter Sculpt Mode to use these tools")
            _button(col, context, "Sculpt Mode", "object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'})
    return type("PROPERTIES_PT_m3d_sc_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Sculpt", "bl_options": {'HIDE_HEADER'}, "page": "sculpt_" + page,
        "page_poll": classmethod(lambda cls, context: not ready(context, need)), "draw": draw})


# --- Left tray: brushes

class PROPERTIES_PT_m3d_sc_brush(_BrushPage, BrushSelectPanel, Panel):
    page = "sculpt_brushes"


class PROPERTIES_PT_m3d_sc_grid(_Page, Panel):
    page = "sculpt_brushes"
    bl_label = "Brushes"

    def draw(self, context):
        brush_tiles(self.layout, context, BRUSH_ASSET, BRUSHES)


class PROPERTIES_PT_m3d_sc_custom(_PagePanel, Panel):
    """The Custom shelf of this workspace: the top bar's shelf is hidden in Sculpt"""
    page = "sculpt_brushes"
    bl_label = "Custom"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        import m3d_edit
        from m3d_user import draw_custom_shelf
        draw_custom_shelf(self.layout, context, 'SCULPT', m3d_edit.editing(), tray=True)


class PROPERTIES_PT_m3d_sc_tuning(_Page, Panel):
    page = "sculpt_brushes"
    bl_label = "Size and Strength"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        mesh = mesh_of(context).data
        brush = sculpt_brush(context)
        if brush is not None:
            col = layout.column()
            draw_size_strength(col, context, brush)
            draw_hardness(col, brush)
            draw_direction(layout, brush)
        else:
            layout.label(text="Pick a brush above")
        row = layout.row(align=True, heading="Mirror")
        for axis in "xyz":
            row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)


class PROPERTIES_PT_m3d_sc_lazy(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Lazy Mouse"

    @classmethod
    def page_poll(cls, context):
        brush = sculpt_brush(context)
        return super().page_poll(context) and brush is not None and brush.brush_capabilities.has_smooth_stroke

    def draw_header(self, context):
        self.layout.prop(sculpt_brush(context), "use_smooth_stroke", text="")

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        brush = sculpt_brush(context)
        col = layout.column()
        col.active = brush.use_smooth_stroke
        col.prop(brush, "smooth_stroke_radius", text="Radius", slider=True)
        col.prop(brush, "smooth_stroke_factor", text="Factor", slider=True)


class PROPERTIES_PT_m3d_sc_strokes(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Stroke Type"

    def draw(self, context):
        stroke_tiles(self.layout, context, sculpt_brush(context))


class PROPERTIES_PT_m3d_sc_alpha(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Alpha"

    def draw(self, context):
        layout = self.layout
        brush = sculpt_brush(context)
        alpha_tiles(layout, context, brush)
        layout.operator("m3d.alpha_load", text="Load Alpha...", icon='FILE_FOLDER')


class PROPERTIES_PT_m3d_sc_alpha_settings(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Alpha Settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        brush = sculpt_brush(context)
        if brush.texture is None:
            self.layout.label(text="Pick an alpha above", icon='INFO')
            return
        brush_texture_settings(self.layout.column(), brush, context.sculpt_object)


class PROPERTIES_PT_m3d_sc_more(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Brush Settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        split_props(self.layout)
        brush_settings(self.layout.column(), context, UnifiedPaintPanel.paint_settings(context).brush, popover=True)


class PROPERTIES_PT_m3d_sc_falloff(_BrushPage, FalloffPanel, Panel):
    page = "sculpt_brushes"


class PROPERTIES_PT_m3d_sc_stroke(_BrushPage, StrokePanel, Panel):
    page = "sculpt_brushes"
    bl_label = "Stroke Options"


class PROPERTIES_PT_m3d_sc_cursor(_BrushPage, DisplayPanel, Panel):
    page = "sculpt_brushes"
    bl_label = "Cursor"


class PROPERTIES_PT_m3d_sc_advanced(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Advanced"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        split_props(self.layout)
        settings = UnifiedPaintPanel.paint_settings(context)
        brush_settings_advanced(self.layout.column(), context, settings, settings.brush, self.is_popover)


# --- Geometry

class _Geometry(_Page):
    page = "sculpt_geometry"
    need = 'MESH'


def draw_multires(layout, context):
    """Multires: Subdivide, the level (with Lower / Higher), the three level sliders, Delete Higher / Unsubdivide /
    Apply Base (the Multires dock panel and the Remesh popover)."""
    ob = mesh_of(context)
    mod = multires_of(ob)
    dyntopo = ob.use_dynamic_topology_sculpting
    if dyntopo:
        reason(layout, "Turn off Dyntopo to use Multires")
    col = layout.column()
    col.enabled = not dyntopo
    row = col.row(align=True)
    for label, mode in (("Subdivide", 'CATMULL_CLARK'), ("Simple", 'SIMPLE'), ("Linear", 'LINEAR')):
        row.operator("m3d.multires_subdivide", text=label).mode = mode
    if mod is None:
        col.label(text="The first Subdivide adds a Multires modifier")
        return
    split_props(col)
    row = col.row(align=True)
    row.operator("m3d.multires_level", text="Lower", icon='TRIA_LEFT').delta = -1
    row.label(text="Level %d of %d" % (mod.sculpt_levels, mod.total_levels))
    row.operator("m3d.multires_level", text="Higher", icon='TRIA_RIGHT').delta = 1
    sub = col.column(align=True)
    sub.prop(mod, "levels", text="Viewport")
    sub.prop(mod, "sculpt_levels", text="Sculpt")
    sub.prop(mod, "render_levels", text="Render")
    col.separator()
    flow = col.grid_flow(columns=1, align=True)
    for action, label in (('DELETE_HIGHER', "Delete Higher"), ('UNSUBDIVIDE', "Unsubdivide"),
                          ('APPLY_BASE', "Apply Base")):
        flow.operator("m3d.multires_edit", text=label).action = action


def draw_voxel(layout, context):
    """Voxel Remesh: the voxel size, its options and the button."""
    split_props(layout)
    ob = mesh_of(context)
    mesh = ob.data
    if multires_of(ob) is not None:
        reason(layout, "Voxel Remesh does not work with Multires")
    elif ob.use_dynamic_topology_sculpting:
        reason(layout, "Turn off Dyntopo to use Voxel Remesh")
    col = layout.column()
    col.enabled = multires_of(ob) is None and not ob.use_dynamic_topology_sculpting
    row = col.row(align=True)
    row.prop(mesh, "remesh_voxel_size")
    _button(row, context, "", "sculpt.sample_detail_size", 'EYEDROPPER', {"mode": 'VOXEL'})
    col.prop(mesh, "remesh_voxel_adaptivity")
    col.prop(mesh, "use_remesh_fix_poles")
    sub = col.column(heading="Preserve", align=True)
    sub.prop(mesh, "use_remesh_preserve_volume", text="Volume")
    sub.prop(mesh, "use_remesh_preserve_attributes", text="Attributes")
    _button(col, context, "Voxel Remesh", "object.voxel_remesh", 'MOD_REMESH', {})


def draw_quadriflow(layout, context):
    """QuadriFlow: the target (face count, ratio or edge length), its options and the button."""
    split_props(layout)
    ob = mesh_of(context)
    if multires_of(ob) is not None:
        reason(layout, "QuadriFlow does not work with Multires")
    elif ob.use_dynamic_topology_sculpting:
        reason(layout, "Turn off Dyntopo to use QuadriFlow")
    col = layout.column()
    col.enabled = multires_of(ob) is None and not ob.use_dynamic_topology_sculpting
    props = context.window_manager.operator_properties_last("object.quadriflow_remesh")
    col.prop(props, "mode")
    col.prop(props, {'RATIO': "target_ratio", 'EDGE': "target_edge_length", 'FACES': "target_faces"}[props.mode])
    col.prop(props, "use_mesh_symmetry")
    col.prop(props, "use_preserve_sharp")
    col.prop(props, "use_preserve_boundary")
    col.prop(props, "smooth_normals")
    col.label(text="Replaces the mesh (UVs and Face Sets are lost)", icon='INFO')
    col.operator_context = 'EXEC_DEFAULT'
    _button(col, context, "QuadriFlow Remesh", "object.quadriflow_remesh", 'MOD_REMESH', {})


def draw_dyntopo(layout, context):
    """Dyntopo: the toggle and the detail size (how it is measured follows the Detailing method)."""
    split_props(layout)
    ob = mesh_of(context)
    sculpt = context.tool_settings.sculpt
    if multires_of(ob) is not None:
        reason(layout, "Dyntopo does not work with Multires")
    elif context.mode != 'SCULPT':
        reason(layout, "Enter Sculpt Mode to use Dyntopo")
    on = ob.use_dynamic_topology_sculpting
    col = layout.column()
    col.enabled = multires_of(ob) is None and context.mode == 'SCULPT'
    _button(col, context, "Disable Dyntopo" if on else "Enable Dyntopo", "sculpt.dynamic_topology_toggle",
            'CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT', {}, depress=on)
    if not on:
        col.label(text="Turning it on removes UVs and Face Sets", icon='ERROR')
    sub = col.column()
    sub.active = on
    method = sculpt.detail_type_method
    if method in {'CONSTANT', 'MANUAL'}:
        row = sub.row(align=True)
        row.prop(sculpt, "constant_detail_resolution")
        _button(row, context, "", "sculpt.sample_detail_size", 'EYEDROPPER', {"mode": 'DYNTOPO'})
    elif method == 'BRUSH':
        sub.prop(sculpt, "detail_percent")
    else:
        sub.prop(sculpt, "detail_size")
    sub.prop(sculpt, "detail_refine_method", text="Refine Method")
    sub.prop(sculpt, "detail_type_method", text="Detailing")
    if method in {'CONSTANT', 'MANUAL'}:
        _button(sub, context, "Flood Fill Detail", "sculpt.detail_flood_fill", 'NONE', {})


class PROPERTIES_PT_m3d_sc_multires(_Geometry, Panel):
    bl_label = "Multires"

    def draw(self, context):
        draw_multires(self.layout, context)


class PROPERTIES_PT_m3d_sc_voxel(_Geometry, Panel):
    bl_label = "Voxel Remesh"

    def draw(self, context):
        draw_voxel(self.layout, context)


class PROPERTIES_PT_m3d_sc_quadriflow(_Geometry, Panel):
    bl_label = "QuadriFlow"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        draw_quadriflow(self.layout, context)


class PROPERTIES_PT_m3d_sc_dyntopo(_Geometry, Panel):
    bl_label = "Dyntopo"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        draw_dyntopo(self.layout, context)


# --- Mask

class _Mask(_Page):
    page = "sculpt_mask"


MASK_FILL = (
    ("Invert", "paint.mask_flood_fill", 'ARROW_LEFTRIGHT', {"mode": 'INVERT'}),
    ("Clear", "paint.mask_flood_fill", 'X', {"mode": 'VALUE', "value": 0.0}),
    ("Fill", "paint.mask_flood_fill", 'MOD_MASK', {"mode": 'VALUE', "value": 1.0}),
)
MASK_FILTERS = (
    ("Smooth", "sculpt.mask_filter", 'NONE', {"filter_type": 'SMOOTH'}),
    ("Sharpen", "sculpt.mask_filter", 'NONE', {"filter_type": 'SHARPEN'}),
    ("Grow", "sculpt.mask_filter", 'NONE', {"filter_type": 'GROW'}),
    ("Shrink", "sculpt.mask_filter", 'NONE', {"filter_type": 'SHRINK'}),
    ("Contrast +", "sculpt.mask_filter", 'NONE', {"filter_type": 'CONTRAST_INCREASE'}),
    ("Contrast -", "sculpt.mask_filter", 'NONE', {"filter_type": 'CONTRAST_DECREASE'}),
)
MASK_CREATE = (
    ("From Cavity", "sculpt.mask_from_cavity", 'NONE', {}),
    ("From Boundary", "sculpt.mask_from_boundary", 'NONE', {}),
)
MASK_TOOLS = (
    ("Box Mask", "builtin.box_mask", "", {}), ("Lasso Mask", "builtin.lasso_mask", "", {}),
    ("Line Mask", "builtin.line_mask", "", {}), ("Polyline Mask", "builtin.polyline_mask", "", {}),
    ("Mask by Color", "builtin.mask_by_color", "", {}),
)
HIDE_MASKED = (
    ("Hide Masked", "paint.hide_show_masked", 'HIDE_ON', {"action": 'HIDE'}),
    ("Show Masked", "paint.hide_show_masked", 'HIDE_OFF', {"action": 'SHOW'}),
    ("Show All", "paint.hide_show_all", 'RESTRICT_VIEW_OFF', {"action": 'SHOW'}),
)


class PROPERTIES_PT_m3d_sc_mask(_Mask, Panel):
    bl_label = "Mask"

    def draw(self, context):
        layout = self.layout
        label, idname, icon, props = MASK_FILL[0]
        big = layout.row()
        big.scale_y = 1.8
        _button(big, context, label + " Mask", idname, icon, props)
        grid(layout, context, MASK_FILL[1:], columns=2)
        layout.label(text="Ctrl+drag: mask | +Alt: unmask | click off the mesh: invert")
        layout.label(text="Expand: Shift+A over the mesh (Shift+W: face sets)")


class PROPERTIES_PT_m3d_sc_mask_filter(_Mask, Panel):
    bl_label = "Filter"

    def draw(self, context):
        grid(self.layout, context, MASK_FILTERS)


class PROPERTIES_PT_m3d_sc_mask_create(_Mask, Panel):
    bl_label = "Create Mask"

    def draw(self, context):
        grid(self.layout, context, MASK_CREATE)
        tools_grid(self.layout, context, MASK_TOOLS)


class PROPERTIES_PT_m3d_sc_mask_hide(_Mask, Panel):
    bl_label = "Hide"

    def draw(self, context):
        grid(self.layout, context, HIDE_MASKED, columns=3)
        self.layout.label(text="Ctrl+Shift+drag: hide outside | +Alt: inside | click: show")


# --- Face Sets

class _FaceSets(_Page):
    page = "sculpt_face_sets"


FACE_SET_INIT = tuple((label, "sculpt.face_sets_init", 'NONE', {"mode": mode}) for label, mode in (
    ("Loose Parts", 'LOOSE_PARTS'), ("Materials", 'MATERIALS'), ("Normals", 'NORMALS'), ("UV Seams", 'UV_SEAMS'),
    ("Creases", 'CREASES'), ("Sharp Edges", 'SHARP_EDGES'), ("Bevel Weights", 'BEVEL_WEIGHT'),
    ("Face Set Boundaries", 'FACE_SET_BOUNDARIES')))
FACE_SET_CREATE = tuple((label, "sculpt.face_sets_create", 'NONE', {"mode": mode}) for label, mode in (
    ("From Mask", 'MASKED'), ("From Visible", 'VISIBLE'), ("From Selection", 'SELECTION')))
FACE_SET_EDIT = tuple((label, "builtin.face_set_edit", "sculpt.face_set_edit", {"mode": mode}) for label, mode in (
    ("Grow", 'GROW'), ("Shrink", 'SHRINK'), ("Fair Positions", 'FAIR_POSITIONS'), ("Fair Tangency", 'FAIR_TANGENCY'),
    ("Delete Geometry", 'DELETE_GEOMETRY')))
FACE_SET_VISIBILITY = (
    ("Show All", "paint.hide_show_all", 'RESTRICT_VIEW_OFF', {"action": 'SHOW'}),
    ("Randomize Colors", "sculpt.face_sets_randomize_colors", 'COLOR', {}),
)


class PROPERTIES_PT_m3d_sc_fs_init(_FaceSets, Panel):
    bl_label = "Initialize"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_INIT)


class PROPERTIES_PT_m3d_sc_fs_create(_FaceSets, Panel):
    bl_label = "Create"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_CREATE, columns=3)


class PROPERTIES_PT_m3d_sc_fs_edit(_FaceSets, Panel):
    bl_label = "Edit"

    def draw(self, context):
        tools_grid(self.layout, context, FACE_SET_EDIT)
        self.layout.label(text="Then click a face set in the viewport")


class PROPERTIES_PT_m3d_sc_fs_visibility(_FaceSets, Panel):
    bl_label = "Visibility"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_VISIBILITY)
        self.layout.label(text="Hide / show one set: H over it")


# --- Deform

class _Deform(_Page):
    page = "sculpt_deform"


MESH_FILTERS = tuple((label, "builtin.mesh_filter", "sculpt.mesh_filter", {"type": kind}) for label, kind in (
    ("Smooth", 'SMOOTH'), ("Inflate", 'INFLATE'), ("Relax", 'RELAX'), ("Surface Smooth", 'SURFACE_SMOOTH'),
    ("Sharpen", 'SHARPEN'), ("Enhance Details", 'ENHANCE_DETAILS'), ("Sphere", 'SPHERE'), ("Random", 'RANDOM'),
    ("Scale", 'SCALE')))
PIVOT_BUTTONS = tuple((label, "sculpt.set_pivot_position", 'PIVOT_CURSOR', {"mode": mode}) for label, mode in (
    ("Origin", 'ORIGIN'), ("Unmasked", 'UNMASKED'), ("Mask Border", 'BORDER')))
TRIM_TOOLS = (
    ("Box Trim", "builtin.box_trim", "", {}), ("Lasso Trim", "builtin.lasso_trim", "", {}),
    ("Line Trim", "builtin.line_trim", "", {}), ("Polyline Trim", "builtin.polyline_trim", "", {}),
    ("Line Project", "builtin.line_project", "", {}),
)


class PROPERTIES_PT_m3d_sc_filters(_Deform, Panel):
    bl_label = "Mesh Filters"

    def draw(self, context):
        layout = self.layout
        tools_grid(layout, context, MESH_FILTERS)
        if tool_is_active(context, "builtin.mesh_filter", "", {}):
            split_props(layout)
            props = active_tool(context).operator_properties("sculpt.mesh_filter")
            col = layout.column()
            col.prop(props, "strength")
            col.prop(props, "deform_axis")
        layout.label(text="Pick a filter, then drag in the viewport")


class PROPERTIES_PT_m3d_sc_symmetrize(_Deform, Panel):
    bl_label = "Symmetrize"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        layout.prop(context.tool_settings.sculpt, "symmetrize_direction", text="Direction")
        layout.prop(context.window_manager.operator_properties_last("sculpt.symmetrize"), "merge_tolerance")
        layout.operator("sculpt.symmetrize", icon='MOD_MIRROR')


class PROPERTIES_PT_m3d_sc_pivot(_Deform, Panel):
    bl_label = "Set Pivot"

    def draw(self, context):
        grid(self.layout, context, PIVOT_BUTTONS, columns=3)


class PROPERTIES_PT_m3d_sc_trim(_Deform, Panel):
    bl_label = "Trim"

    def draw(self, context):
        tools_grid(self.layout, context, TRIM_TOOLS)


# --- Paint

class _Paint(_Page):
    page = "sculpt_paint"


COLOR_FILTERS = tuple((label, "builtin.color_filter", "sculpt.color_filter", {"type": kind}) for label, kind in (
    ("Fill", 'FILL'), ("Hue", 'HUE'), ("Saturation", 'SATURATION'), ("Value", 'VALUE'), ("Brightness", 'BRIGHTNESS'),
    ("Contrast", 'CONTRAST'), ("Smooth", 'SMOOTH'), ("Red", 'RED'), ("Green", 'GREEN'), ("Blue", 'BLUE')))


class PROPERTIES_PT_m3d_sc_paint(_Paint, Panel):
    bl_label = "Color Brushes"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        mesh = mesh_of(context).data
        grid(layout, context, [(label, "brush.asset_activate", 'NONE', brush_props(name))
                               for label, name in PAINT_BRUSHES], columns=3,
             active=lambda idname, props: is_active(context, idname, props))
        if mesh.color_attributes.active_color is None:
            layout.label(text="This mesh has no color attribute", icon='ERROR')
            layout.operator_context = 'EXEC_DEFAULT'   # No options dialog: the defaults are what you want.
            _button(layout, context, "Add Color Attribute", "geometry.color_attribute_add", 'ADD',
                    {"name": "Color", "domain": 'POINT', "data_type": 'BYTE_COLOR', "color": (0.8, 0.8, 0.8, 1.0)})
        settings = UnifiedPaintPanel.paint_settings(context)
        brush = settings.brush if settings else None
        if brush is None or not brush.sculpt_capabilities.has_color:
            layout.label(text="Pick a color brush above")
        else:
            UnifiedPaintPanel.prop_unified_color_picker(layout, context, brush, "color")
            row = layout.row(align=True)
            UnifiedPaintPanel.prop_unified_color(row, context, brush, "color", text="")
            UnifiedPaintPanel.prop_unified_color(row, context, brush, "secondary_color", text="")
            row.operator("paint.brush_colors_flip", icon='FILE_REFRESH', text="")
            layout.prop(brush, "blend", text="Blend Mode")
        space = viewport(context)
        if space is not None:
            layout.prop(space.shading, "color_type", text="Viewport Color")


class PROPERTIES_PT_m3d_sc_palette(_BrushPage, ColorPalettePanel, Panel):
    page = "sculpt_paint"


class PROPERTIES_PT_m3d_sc_color_filter(_Paint, Panel):
    bl_label = "Color Filter"

    def draw(self, context):
        tools_grid(self.layout, context, COLOR_FILTERS)
        self.layout.label(text="Pick a filter, then drag in the viewport")


# --- Display

def draw_shading(layout, context, units_x=0):
    """Viewport look for sculpting: matcap / studio light (a grid of thumbnails), color, cavity (the Display tab and
    the matcap popover, which is `units_x` wide)."""
    space = viewport(context)
    if space is None:
        layout.label(text="No 3D Viewport in this workspace")
        return
    shading = space.shading
    layout.row().prop(shading, "type", expand=True)
    if shading.type != 'SOLID':
        reason(layout, "Lighting and cavity are for Solid shading")
        return
    split_props(layout)
    layout.row().prop(shading, "light", expand=True)
    if shading.light in {'STUDIO', 'MATCAP'}:
        light_tiles(layout, context, shading, units_x)
    layout.prop(shading, "color_type", text="Color")
    layout.prop(shading, "show_cavity")
    if shading.show_cavity:
        col = layout.column()
        col.prop(shading, "cavity_type", text="Type")
        col.prop(shading, "cavity_ridge_factor", text="Ridge")
        col.prop(shading, "cavity_valley_factor", text="Valley")


class _Display(_Page):
    page = "sculpt_display"
    need = None


class PROPERTIES_PT_m3d_sc_shading(_Display, Panel):
    bl_label = "Shading"

    def draw(self, context):
        draw_shading(self.layout, context)


class PROPERTIES_PT_m3d_sc_overlays(_Display, Panel):
    bl_label = "Overlays"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        space = viewport(context)
        if space is None:
            return
        overlay = space.overlay
        for flag, opacity, label in (("show_sculpt_mask", "sculpt_mode_mask_opacity", "Mask"),
                                     ("show_sculpt_face_sets", "sculpt_mode_face_sets_opacity", "Face Sets")):
            row = layout.row(align=True)
            row.prop(overlay, flag, text=label, toggle=True)
            sub = row.row(align=True)
            sub.active = getattr(overlay, flag)
            sub.prop(overlay, opacity, text="Opacity")
        row = layout.row(align=True)
        row.prop(overlay, "show_wireframes", text="Wireframe", toggle=True)
        sub = row.row(align=True)
        sub.active = overlay.show_wireframes
        sub.prop(overlay, "wireframe_opacity", text="Opacity")


class PROPERTIES_PT_m3d_sc_performance(_Display, Panel):
    bl_label = "Performance"

    @classmethod
    def page_poll(cls, context):
        return context.tool_settings.sculpt is not None

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        sculpt = context.tool_settings.sculpt
        col = layout.column(heading="Display", align=True)
        col.prop(sculpt, "show_low_resolution", text="Low Resolution While Navigating")
        col.prop(sculpt, "use_sculpt_delay_updates", text="Delay Updates While Stroking")
        col.prop(sculpt, "use_deform_only", text="Deform Only (no topology update)")


# --- Objects: the scene's meshes

class PROPERTIES_PT_m3d_sc_objects(_Page, Panel):
    page = "sculpt_objects"
    bl_label = "Meshes"
    need = None

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        for label, kind in (("Sphere", 'SPHERE'), ("Cube", 'CUBE'), ("Cylinder", 'CYLINDER')):
            row.operator("m3d.sculpt_add_mesh", text=label, icon='ADD').kind = kind
        meshes = [o for o in context.view_layer.objects if o.type == 'MESH']
        if not meshes:
            layout.label(text="No meshes in the scene")
        col = layout.column(align=True)
        for ob in meshes:
            hidden = ob.hide_get()
            others = [o for o in meshes if o is not ob]
            solo = bool(others) and all(o.hide_get() for o in others) and not hidden
            row = col.row(align=True)
            o = row.operator("m3d.sculpt_object", text="", icon='HIDE_ON' if hidden else 'HIDE_OFF')
            o.name, o.action = ob.name, 'VISIBLE'
            sub = row.row(align=True)
            o = sub.operator("m3d.sculpt_object", text="%s  (%s faces)" % (ob.name, format(len(ob.data.polygons), ",")),
                             depress=ob is context.active_object)
            o.name, o.action = ob.name, 'SELECT'
            sub.active = not hidden
            o = row.operator("m3d.sculpt_object", text="", icon='SOLO_ON' if solo else 'SOLO_OFF', depress=solo)
            o.name, o.action = ob.name, 'SOLO'
            o = row.operator("m3d.sculpt_object", text="", icon='DUPLICATE')
            o.name, o.action = ob.name, 'DUPLICATE'


GATES = {"sculpt_brushes": 'SCULPT', "sculpt_geometry": 'MESH', "sculpt_mask": 'SCULPT', "sculpt_face_sets": 'SCULPT',
         "sculpt_deform": 'SCULPT', "sculpt_paint": 'SCULPT'}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page[len("sculpt_"):], need) for page, need in GATES.items())


# -----------------------------------------------------------------------------
# Status Line and popovers

class M3D_PT_sculpt_automasking(Panel):
    """Auto-Masking: limit strokes to the part of the mesh under the cursor"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Auto-Masking"
    bl_ui_units_x = 13

    @classmethod
    def poll(cls, context):
        sculpt = context.tool_settings.sculpt
        return sculpt is not None and sculpt.brush is not None

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        am = context.tool_settings.sculpt.brush.mesh_automasking_settings
        col = layout.column(align=True)
        col.prop(am, "use_automasking_topology", text="Topology")
        col.prop(am, "use_automasking_face_sets", text="Face Sets")
        col.prop(am, "use_automasking_boundary_edges", text="Mesh Boundary")
        col.prop(am, "use_automasking_boundary_face_sets", text="Face Sets Boundary")
        if am.use_automasking_boundary_edges or am.use_automasking_boundary_face_sets:
            col.prop(am, "boundary_edges_propagation_steps", text="Steps")
        col = layout.column(align=True)
        col.prop(am, "use_automasking_cavity", text="Cavity")
        col.prop(am, "use_automasking_cavity_inverted", text="Cavity (inverted)")
        if am.use_automasking_cavity or am.use_automasking_cavity_inverted:
            col.prop(am, "cavity_factor", text="Factor")
            col.prop(am, "cavity_blur_steps", text="Blur")
        col = layout.column(align=True)
        col.prop(am, "use_automasking_view_normal", text="View Normal")
        if am.use_automasking_view_normal:
            col.prop(am, "use_automasking_view_occlusion", text="Occlusion")
            if not am.use_automasking_view_occlusion:
                col.prop(am, "view_normal_limit", text="Limit")
                col.prop(am, "view_normal_falloff", text="Falloff")
        col.prop(am, "use_automasking_start_normal", text="Area Normal")
        if am.use_automasking_start_normal:
            col.prop(am, "start_normal_limit", text="Limit")
            col.prop(am, "start_normal_falloff", text="Falloff")


class M3D_PT_sculpt_shading(Panel):
    """Matcap, studio light and cavity of the viewport"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Matcap"
    bl_ui_units_x = 16

    def draw(self, context):
        draw_shading(self.layout, context, M3D_PT_sculpt_shading.bl_ui_units_x)


class M3D_PT_sculpt_brush(Panel):
    """Brush options: size, strength, hardness, add / subtract, falloff, Lazy Mouse, stroke type"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Brush"
    bl_ui_units_x = 16

    @classmethod
    def poll(cls, context):
        return sculpt_brush(context) is not None

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        brush = sculpt_brush(context)
        col = layout.column()
        draw_size_strength(col, context, brush)
        draw_hardness(col, brush)
        draw_direction(layout, brush)
        col = layout.column(align=True)
        col.prop(brush, "curve_distance_falloff_preset", text="Falloff")
        if brush.curve_distance_falloff_preset == 'CUSTOM':
            col.template_curve_mapping(brush, "curve_distance_falloff", brush=True, use_negative_slope=True,
                                       show_presets=True)
        col.row().prop(brush, "falloff_shape", expand=True)
        if brush.brush_capabilities.has_smooth_stroke:
            layout.separator()
            layout.prop(brush, "use_smooth_stroke", text="Lazy Mouse")
            col = layout.column(align=True)
            col.active = brush.use_smooth_stroke
            col.prop(brush, "smooth_stroke_radius", text="Radius", slider=True)
            col.prop(brush, "smooth_stroke_factor", text="Factor", slider=True)
        layout.separator()
        stroke_tiles(layout, context, brush, M3D_PT_sculpt_brush.bl_ui_units_x)


class M3D_PT_sculpt_remesh(Panel):
    """Remesh and topology: Voxel Remesh, QuadriFlow, Multires levels and Dyntopo detail"""
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Remesh"
    bl_ui_units_x = 17

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def draw(self, context):
        layout = self.layout
        for key, label, draw, closed in (("voxel", "Voxel Remesh", draw_voxel, False),
                                         ("quadriflow", "QuadriFlow", draw_quadriflow, True),
                                         ("multires", "Multires", draw_multires, True),
                                         ("dyntopo", "Dyntopo", draw_dyntopo, True)):
            header, body = layout.panel("m3d_sculpt_remesh_" + key, default_closed=closed)
            header.label(text=label)
            if body:
                draw(body, context)


def header_tier(context):
    """How much of the Status Line's brush controls fit: 2 on a wide window (all of them in place), 1 for the
    sliders and toggles, 0 for narrow ones (the Brush popover has the rest). Measured in pixels at UI scale 1."""
    region = context.region
    width = region.width / ui_scale_factor(context) if region else 2000
    return 2 if width >= 2200 else 1 if width >= 1500 else 0


def draw_brush_controls(layout, context, brush, tier):
    """The Status Line's brush controls (a top shelf): Size, Strength, Hardness, Add / Subtract, Lazy Mouse, the colors
    of a color brush; the Brush popover has the rest."""
    caps = brush.sculpt_capabilities
    row = layout.row(align=True)
    for units, draw in ((7 if tier else 5.5, lambda sub: draw_size_strength(sub, context, brush, header=True, only="size")),
                        (7.5 if tier else 6, lambda sub: draw_size_strength(sub, context, brush, header=True, only="strength")),
                        (7 if tier == 2 and caps.has_hardness else 0, lambda sub: draw_hardness(sub, brush))):
        if units:
            sub = row.row(align=True)
            sub.ui_units_x = units
            draw(sub)
    draw_direction(layout.row(align=True), brush, labels=tier == 2)
    if brush.brush_capabilities.has_smooth_stroke:
        if tier == 2:
            draw_lazy(layout.row(align=True), brush)
        else:
            layout.prop(brush, "use_smooth_stroke", text="", icon='MOD_SMOOTH', toggle=True)
    if caps.has_color:
        row = layout.row(align=True)
        ups = context.tool_settings.sculpt.unified_paint_settings   # (prop_unified_color needs a brush tool here)
        for prop in ("color", "secondary_color"):
            sub = row.row(align=True)
            sub.ui_units_x = 2
            sub.prop(ups if ups.use_unified_color else brush, prop, text="")
        row.operator("paint.brush_colors_flip", icon='ARROW_LEFTRIGHT', text="")
    layout.popover("M3D_PT_sculpt_brush", text="Brush" if tier else "", icon='BRUSH_DATA')


def draw_status_line(layout, context):
    """Sculpt Status Line: file, modes, the brush controls (Size, Strength, Hardness, Add / Subtract, Lazy Mouse), the
    Remesh popover, face count and Multires level, Dyntopo, symmetry, Auto-Masking, Mask / Face Set overlays, matcap."""
    from m3d_ui import _call, draw_file_buttons, draw_workspace_picker
    tier = header_tier(context)
    draw_file_buttons(layout)
    row = layout.row(align=True)
    _call(row, "object.mode_set", 'OBJECT_DATAMODE', "Object Mode", depress=context.mode == 'OBJECT', mode='OBJECT')
    _call(row, "object.mode_set", 'SCULPTMODE_HLT', "Sculpt Mode", depress=context.mode == 'SCULPT', mode='SCULPT')
    ob = mesh_of(context)
    if ob is None:
        draw_workspace_picker(layout, context)
        return
    mesh, mod = ob.data, multires_of(ob)
    dyntopo = ob.use_dynamic_topology_sculpting
    sculpting = context.mode == 'SCULPT'
    brush = sculpt_brush(context) if sculpting else None
    if brush is not None:
        draw_brush_controls(layout, context, brush, tier)
    layout.popover("M3D_PT_sculpt_remesh", text="Remesh" if tier else "", icon='MOD_REMESH')
    if tier == 2:
        # Voxel Remesh in place (the popover has the options, QuadriFlow, Multires and Dyntopo).
        row = layout.row(align=True)
        row.enabled = mod is None and not dyntopo
        sub = row.row(align=True)
        sub.ui_units_x = 6
        sub.prop(mesh, "remesh_voxel_size", text="Voxel")
        _button(row, context, "Remesh", "object.voxel_remesh", 'NONE', {})
    # The mesh data is not updated while Dyntopo changes it, so no count then.
    layout.label(text="Dyntopo" if dyntopo else "%s faces" % format(len(mesh.polygons), ","))
    if mod is not None:
        row = layout.row(align=True)
        row.operator("m3d.multires_level", text="", icon='TRIA_LEFT').delta = -1
        row.label(text="Lv %d/%d" % (mod.sculpt_levels, mod.total_levels))
        row.operator("m3d.multires_level", text="", icon='TRIA_RIGHT').delta = 1
    if sculpting:
        row = layout.row(align=True)
        row.enabled = mod is None
        _call(row, "sculpt.dynamic_topology_toggle", 'CHECKBOX_HLT' if dyntopo else 'CHECKBOX_DEHLT',
              "Dyntopo (needs no Multires modifier)" if mod is None else "Dyntopo is off while the mesh has Multires",
              depress=dyntopo)
    row = layout.row(align=True)
    for axis in "xyz":
        row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)
    if sculpting:
        layout.popover("M3D_PT_sculpt_automasking", text="Auto-Masking" if tier else "", icon='NONE' if tier else 'MOD_MASK')
    space = viewport(context)
    if space is not None:
        row = layout.row(align=True)
        row.prop(space.overlay, "show_sculpt_mask", text="", icon='MOD_MASK')
        row.prop(space.overlay, "show_sculpt_face_sets", text="", icon='FACE_MAPS')
        layout.popover("M3D_PT_sculpt_shading", text="Matcap" if tier == 2 else "", icon='MATSPHERE')
    draw_workspace_picker(layout, context)


# -----------------------------------------------------------------------------
# Shelves (items as in m3d_ui.SHELVES: (idname, icon, props[, text]), or a function drawing into the row)

def _voxel_size(row, context):
    ob = mesh_of(context)
    if ob is not None:
        sub = row.row()
        sub.scale_x = 2.0
        sub.prop(ob.data, "remesh_voxel_size", text="")


SHELF_BRUSHES = [
    ("object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'}),
    None,
    *(brush_item(label, name) for label, name in BRUSHES),
]
SHELF_REMESH = [
    ("object.voxel_remesh", 'MOD_REMESH', {}),
    _voxel_size,
    None,
    ("object.quadriflow_remesh", 'MESH_GRID', {}),
    None,
    ("m3d.multires_subdivide", 'ADD', {"mode": 'CATMULL_CLARK'}),
    ("m3d.multires_level", 'TRIA_RIGHT', {"delta": 1}),
    ("m3d.multires_level", 'TRIA_LEFT', {"delta": -1}),
    ("m3d.multires_edit", 'FREEZE', {"action": 'APPLY_BASE'}),
]
SHELF_MASK = [
    ("paint.mask_flood_fill", 'MOD_MASK', {"mode": 'VALUE', "value": 1.0}),
    ("paint.mask_flood_fill", 'X', {"mode": 'VALUE', "value": 0.0}),
    ("paint.mask_flood_fill", 'ARROW_LEFTRIGHT', {"mode": 'INVERT'}),
    None,
    ("sculpt.mask_filter", 'ADD', {"filter_type": 'GROW'}),
    ("sculpt.mask_filter", 'REMOVE', {"filter_type": 'SHRINK'}),
    ("sculpt.mask_filter", 'SHARPCURVE', {"filter_type": 'SHARPEN'}),
    None,
    ("sculpt.mask_from_cavity", 'MOD_WIREFRAME', {}),
    ("paint.hide_show_masked", 'HIDE_ON', {"action": 'HIDE'}),
]


classes = (
    M3D_OT_sculpt_tool,
    M3D_OT_multires_subdivide,
    M3D_OT_multires_level,
    M3D_OT_multires_edit,
    M3D_OT_sculpt_object,
    M3D_OT_sculpt_add_mesh,
    M3D_OT_sculpt_ctrl,
    M3D_OT_brush_pick,
    M3D_OT_stroke_pick,
    M3D_OT_alpha_pick,
    M3D_OT_alpha_load,
    M3D_OT_light_pick,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_sc_brush,
    PROPERTIES_PT_m3d_sc_grid,
    PROPERTIES_PT_m3d_sc_tuning,
    PROPERTIES_PT_m3d_sc_lazy,
    PROPERTIES_PT_m3d_sc_strokes,
    PROPERTIES_PT_m3d_sc_alpha,
    PROPERTIES_PT_m3d_sc_alpha_settings,
    PROPERTIES_PT_m3d_sc_more,
    PROPERTIES_PT_m3d_sc_falloff,
    PROPERTIES_PT_m3d_sc_stroke,
    PROPERTIES_PT_m3d_sc_cursor,
    PROPERTIES_PT_m3d_sc_advanced,
    PROPERTIES_PT_m3d_sc_custom,
    PROPERTIES_PT_m3d_sc_multires,
    PROPERTIES_PT_m3d_sc_voxel,
    PROPERTIES_PT_m3d_sc_quadriflow,
    PROPERTIES_PT_m3d_sc_dyntopo,
    PROPERTIES_PT_m3d_sc_mask,
    PROPERTIES_PT_m3d_sc_mask_filter,
    PROPERTIES_PT_m3d_sc_mask_create,
    PROPERTIES_PT_m3d_sc_mask_hide,
    PROPERTIES_PT_m3d_sc_fs_init,
    PROPERTIES_PT_m3d_sc_fs_create,
    PROPERTIES_PT_m3d_sc_fs_edit,
    PROPERTIES_PT_m3d_sc_fs_visibility,
    PROPERTIES_PT_m3d_sc_filters,
    PROPERTIES_PT_m3d_sc_symmetrize,
    PROPERTIES_PT_m3d_sc_pivot,
    PROPERTIES_PT_m3d_sc_trim,
    PROPERTIES_PT_m3d_sc_paint,
    PROPERTIES_PT_m3d_sc_palette,
    PROPERTIES_PT_m3d_sc_color_filter,
    PROPERTIES_PT_m3d_sc_shading,
    PROPERTIES_PT_m3d_sc_overlays,
    PROPERTIES_PT_m3d_sc_performance,
    PROPERTIES_PT_m3d_sc_objects,
    M3D_PT_sculpt_automasking,
    M3D_PT_sculpt_shading,
    M3D_PT_sculpt_brush,
    M3D_PT_sculpt_remesh,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
