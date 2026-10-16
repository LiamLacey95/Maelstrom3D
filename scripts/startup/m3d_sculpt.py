# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Sculpt workspace (F2) for Maelstrom3D: the brush tray (left), the dock pages (Geometry, Objects, Mask, Face Sets,
Deform, Paint, Display), the Sculpt Status Line, shelf items and the operators behind them.

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
    ColorPalettePanel, DisplayPanel, FalloffPanel, SmoothStrokePanel, StrokePanel,
    UnifiedPaintPanel, brush_settings, brush_settings_advanced, brush_texture_settings)

import m3d_pair
from m3d_mode import _button
from m3d_workspace import HEADERS, PAGE_SETS, _PagePanel, current_kind, draw_tab_row, side_of

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
    def description(cls, context, props):
        """The brush's name and its key (Sculpt's Shift+1-7)."""
        from m3d_ui import key_text
        key = key_text(context, "Sculpt" if props.identifier.startswith(BRUSH_ASSET) else "Image Paint", "brush.asset_activate",
                       {"relative_asset_identifier": props.identifier})
        name = props.identifier.rpartition("/")[2]
        return "%s (%s)" % (name, key) if key else name

    def execute(self, _context):
        return bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier=self.identifier)


def tile_grid(layout, context, units_x=0, min_px=46, columns=0, most=8):
    """Grid for square tiles (icon-only buttons this tall draw their thumbnail at the button size). The columns (at most
    `most`) and the tile height follow the width of the region (or of a popover, `units_x` wide) so the tiles stay square;
    `columns` asks for that many instead."""
    ui_scale = context.preferences.system.ui_scale or 1.0   # 0 without a window
    width = units_x * 20 * ui_scale if units_x else context.region.width if context.region else 300
    avail = width - 24 * ui_scale
    columns = columns or min(max(int(avail // (min_px * ui_scale)), 3), most)
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


def alpha_grid(layout, context, active, stencil=False):
    """The alpha library as small tiles: None (no alpha), then every alpha (the starter set, then the loaded ones); the one named
    `active` is pressed. A click gives the brush its alpha, or with `stencil` (Texture Paint) its stencil."""
    names = alpha_names()
    icons = alpha_icons(names)
    flow = tile_grid(layout, context, min_px=34, most=9)   # (None and the eight starter alphas in one row where it fits)
    # (None is an icon: a word is cut off on a small tile)
    o = flow.operator("m3d.alpha_pick", text="", icon='CANCEL', depress=not active)
    o.name, o.stencil = "", stencil
    for name in names:
        o = flow.operator("m3d.alpha_pick", text="" if name in icons else name, icon_value=icons.get(name, 0),
                          depress=active == name)
        o.name, o.stencil = name, stencil


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


def face_count(ob):
    """Faces being sculpted: the mesh's, or with Multires the level being sculpted (O(1): each base corner becomes
    4^(level - 1) faces). The viewport's statistics count the same."""
    mod = multires_of(ob)
    return m3d_pair.level_faces(ob, mod.sculpt_levels if mod is not None else 0)


def next_level_faces(ob):
    """Faces of the next Multires level Subdivide adds (O(1))."""
    mod = multires_of(ob)
    return m3d_pair.level_faces(ob, (mod.total_levels if mod is not None else 0) + 1)


def short_count(n):
    """240000 -> "240k", 1250000 -> "1.2M" (counts shown as an estimate)."""
    if n >= 1e6:
        return "%.1fM" % (n / 1e6) if n < 1e7 else "%dM" % round(n / 1e6)
    return "%dk" % round(n / 1e3) if n >= 1e4 else "%.1fk" % (n / 1e3) if n >= 1e3 else "%d" % n


# --- Voxel Remesh detail: the voxel size as the face count it gives (a voxel remesh covers the surface with the faces of
# the voxel grid: a face of the mesh adds its area seen along each axis, area * (|nx| + |ny| + |nz|), over the voxel size^2)

_areas = {}   # mesh pointer -> (key, surface area); see surface_area
DETAIL_FACES = (1e3, 5e6)   # Detail 0 and 100: the face counts at the ends of the slider (a log scale between them)


def surface_area(mesh, grid=False):
    """Surface area of the mesh (object space, what Voxel Remesh works in); `grid`: the area the voxel grid sees, each face's
    area seen along the three axes (1.5 times the area on a sphere, the same on an axis-aligned box). Kept per mesh while its
    vertex and face counts stay the same: strokes change it a little, an estimate doesn't mind, and reading the areas of a
    sculpt takes long (~75 ms for 330k faces), so it is not read again while it is sculpted."""
    import numpy as np
    key = (len(mesh.vertices), len(mesh.polygons))
    cached = _areas.get(mesh.as_pointer())
    if cached is None or cached[0] != key:
        n = len(mesh.polygons)
        areas, normals = np.empty(n, np.float32), np.empty(3 * n, np.float32)
        mesh.polygons.foreach_get("area", areas)
        mesh.polygons.foreach_get("normal", normals)
        seen = np.abs(normals.reshape(n, 3)).sum(axis=1)
        cached = _areas[mesh.as_pointer()] = (key, float(areas.sum(dtype=np.float64)),
                                              float((areas * seen).sum(dtype=np.float64)))
    return cached[2] if grid else cached[1]


def voxel_faces(mesh, size=None):
    """About how many faces Voxel Remesh gives at this voxel size (the mesh's own by default)."""
    size = size or mesh.remesh_voxel_size
    return surface_area(mesh, grid=True) / (size * size) if size > 0 else 0


def _detail_get(mesh):
    import math
    faces = voxel_faces(mesh)
    lo, hi = (math.log10(f) for f in DETAIL_FACES)
    return min(max((math.log10(faces) - lo) / (hi - lo) * 100.0, 0.0), 100.0) if faces > 0 else 0.0


def _detail_set(mesh, value):
    lo, hi = DETAIL_FACES
    faces = lo * (hi / lo) ** (value / 100.0)
    area = surface_area(mesh, grid=True)
    if area > 0:
        mesh.remesh_voxel_size = max((area / faces) ** 0.5, 0.0001)


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


# Brush tools of the viewport's toolbar that the docks already have (the brush tray's tiles and its brush line, the Paint
# tab's color brushes): the Sculpt workspace's toolbar leaves them out (picking a brush there still makes them active).
TRAY_TOOLS = frozenset({"builtin.brush", "builtin_brush.mask", "builtin_brush.draw_face_sets", "builtin_brush.paint"})


def toolbar_hidden(context):
    """The tools the toolbar leaves out here (bl_ui.space_toolsystem_common draws the toolbar)."""
    return TRAY_TOOLS if context.mode == 'SCULPT' and current_kind(context) == 'SCULPT' else frozenset()


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


def draw_lines(layout, context, text, icon='INFO', width=None):
    """`text` on as many lines as the width of the region (or `width` pixels: a dialog, which is not its region) needs (the first
    with `icon`), in the normal text colour."""
    from m3d_workspace import text_width
    scale = context.preferences.system.ui_scale or 1.0
    region = getattr(context, "region", None)
    room = (width or (region.width if region is not None else 400 * scale)) - 50 * scale
    lines, line = [], ""
    for word in text.split():
        if line and text_width(line + " " + word, scale) > room:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    col = layout.column(align=True)
    for i, line in enumerate([*lines, line]):
        col.label(text=line, icon=icon if i == 0 else 'BLANK1', translate=False)


def reason(layout, text):
    """A hint (why something is missing, what a click does): the info icon and the text in the normal text colour, on as many
    lines as it needs (nothing is cut off on a narrow panel)."""
    draw_lines(layout, bpy.context, text)


def empty_state(layout, context, text, action=None):
    """The card of a page or panel that can't work yet, the same everywhere: why (a hint line), then the one button that
    fixes it, `action` = (label, operator, icon, properties). Returns the card's column (for more ways to fix it)."""
    col = layout.column()
    if text:   # (none when a note above says why)
        reason(col, text)
    if action is not None:
        row = col.row()
        row.scale_y = 1.3
        _button(row, context, *action)
    return col


def draw_list(layout, list_type, owner, prop, active_owner, active_prop, add, remove, hint, list_id=""):
    """A list of our docks: no resize grip, as tall as its items (up to 6; one row when empty, with `hint` how to fill
    it), + / - beside it (- only with an item to remove). `add` / `remove`: operator ids. Returns the column of the
    buttons (for more of them)."""
    items = getattr(owner, prop)
    row = layout.row()
    row.template_list(list_type, list_id, owner, prop, active_owner, active_prop, rows=min(max(len(items), 1), 6),
                      show_handles=False)
    col = row.column(align=True)
    col.operator(add, icon='ADD', text="")
    if len(items):
        col.operator(remove, icon='REMOVE', text="")
    else:
        reason(layout, hint)
    return col


def draw_object_picks(layout, objects, extend=False, limit=6):
    """A button for each of `objects` (up to `limit`) that selects it (m3d.pick_object): the fix of a card that needs
    another selection."""
    col = layout.column(align=True)
    for ob in objects[:limit]:
        o = col.operator("m3d.pick_object", text=ob.name, icon=PICK_ICONS.get(ob.type, 'OBJECT_DATA'))
        o.name, o.extend = ob.name, extend


PICK_ICONS = {'MESH': 'OUTLINER_OB_MESH', 'CAMERA': 'OUTLINER_OB_CAMERA', 'LIGHT': 'OUTLINER_OB_LIGHT',
              'ARMATURE': 'OUTLINER_OB_ARMATURE', 'CURVE': 'OUTLINER_OB_CURVE', 'EMPTY': 'OUTLINER_OB_EMPTY'}


class M3D_OT_pick_object(Operator):
    """Select this object and make it the active one"""
    bl_idname = "m3d.pick_object"
    bl_label = "Select Object"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(options={'SKIP_SAVE'})
    extend: bpy.props.BoolProperty(options={'SKIP_SAVE'}, description="Add it to the selection (the active object stays)")

    def execute(self, context):
        ob = context.view_layer.objects.get(self.name)
        if ob is None:
            return {'CANCELLED'}
        if context.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')
        if not self.extend:
            for other in context.selected_objects:
                other.select_set(False)
            context.view_layer.objects.active = ob
        ob.hide_set(False)
        ob.select_set(True)
        return {'FINISHED'}


def fits(context, texts, share=1.0):
    """Do buttons showing `texts` fit side by side in `share` of the region's width (less a panel's margins)? Measured with
    the UI font like the dock tabs; True without a region (a test). Where they don't, a row drops to icons (tooltips)."""
    from m3d_workspace import text_width
    region = getattr(context, "region", None)
    if region is None or not getattr(region, "width", 0):
        return True
    scale = context.preferences.system.ui_scale or 1.0
    return sum(text_width(t, scale) for t in texts) <= (region.width - 40 * scale) * share


def grid(layout, context, items, columns=2, active=None):
    """Operator buttons: (label, idname, icon, props); `active(idname, props)` draws one pressed. A narrow dock gets
    fewer columns, so no label is cut off."""
    from m3d_workspace import TAB_PAD, text_width
    region = getattr(context, "region", None)
    if columns > 1 and items and region is not None and getattr(region, "width", 0):
        scale = context.preferences.system.ui_scale or 1.0
        # (a button: its label, the icon and a small margin; the panel takes about 32 px of the width)
        widest = max(text_width(label, scale) + ((24 if icon not in (None, 'NONE') else 8) - TAB_PAD) * scale
                     for label, _idname, icon, _props in items)
        while columns > 1 and widest * columns > region.width - 32 * scale:
            columns -= 1
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


def alpha_brush(context):
    """The brush of the mode, which the alphas and the stroke types go to: the active brush of Texture Paint Mode (the
    Texture workspace shares the alphas and the brush settings' drawing), else the sculpt brush."""
    if context.mode == 'PAINT_TEXTURE':
        paint = context.tool_settings.image_paint
        return paint.brush if paint else None
    return sculpt_brush(context)


# --- Brush settings: drawn by the same functions in Sculpt (the tray, on the left) and Texture (Properties, on the right), so
# they have the same order, labels and look in both: Size, Strength (Flow in Texture), Hardness; Lazy Mouse; Stroke Type;
# Alpha; Falloff. What only one mode has is passed in or drawn around them.

def draw_size_strength(layout, context, brush, header=False, only=None, strength="Strength"):
    """Size and Strength sliders of the brush (`only`: just one of them): the scene-wide ones when Unified Size /
    Strength is on. In a header (the Status Line) the pressure and Unified buttons are left out. `strength`: its label
    (Texture says Flow)."""
    texture = context.mode == 'PAINT_TEXTURE'
    caps = brush.sculpt_capabilities
    paint = context.tool_settings.image_paint if texture else context.tool_settings.sculpt
    ups = paint.unified_paint_settings   # (the header has no brush tool: pass it in)
    if only in {None, "size"}:
        owner = ups if ups.use_unified_size else brush
        size = "unprojected_size" if owner.use_locked_size == 'SCENE' else "size"
        pressure = (texture or caps.has_size_pressure) and not header
        UnifiedPaintPanel.prop_unified(layout, context, brush, size, unified_paint_settings_override=ups,
                                       unified_name="use_unified_size", text="Size", slider=True, header=header,
                                       pressure_name="use_pressure_size" if pressure else None)
    if only in {None, "strength"}:
        pressure = (texture or caps.has_strength_pressure) and not header
        UnifiedPaintPanel.prop_unified(layout, context, brush, "strength", unified_paint_settings_override=ups,
                                       unified_name="use_unified_strength", text=strength, slider=True, header=header,
                                       pressure_name="use_pressure_strength" if pressure else None)


def draw_hardness(layout, brush, always=False):
    """Hardness: how long the brush stays at full strength before it falls off (the Falloff curve shapes the rest).
    `always`: a texture brush, which always has it."""
    if always or brush.sculpt_capabilities.has_hardness:
        layout.prop(brush, "hardness", text="Hardness", slider=True)


def draw_brush_sliders(layout, context, brush, strength="Strength"):
    """Size, Strength (`strength`: its label) and Hardness: the first brush settings, in Sculpt and Texture."""
    draw_size_strength(layout, context, brush, strength=strength)
    draw_hardness(layout, brush, always=context.mode == 'PAINT_TEXTURE')


def draw_lazy_settings(layout, brush):
    """Lazy Mouse's settings (while it is on): how far the stroke lags behind the cursor, and how much it is smoothed."""
    col = layout.column()
    col.prop(brush, "smooth_stroke_radius", text="Distance", slider=True)
    col.prop(brush, "smooth_stroke_factor", text="Smoothing", slider=True)


def draw_falloff(layout, brush, shape=False):
    """Falloff: the preset of the brush's falloff curve (the curve itself when it is Custom); `shape`: Sphere / Projected
    too (Sculpt)."""
    layout.prop(brush, "curve_distance_falloff_preset", text="Falloff")
    if brush.curve_distance_falloff_preset == 'CUSTOM':
        layout.template_curve_mapping(brush, "curve_distance_falloff", brush=True, use_negative_slope=True, show_presets=True)
    if shape:
        layout.row().prop(brush, "falloff_shape", expand=True)


ALPHA_NONE = "No alpha: a round dab"


def draw_alpha(layout, context, brush, texture, slot=None, prop="", modes=()):
    """The brush's alpha: its thumbnail and name (or what the brush does without one), Load Alpha..., the ways it can be
    placed while it has one (`modes`: (value, text) of `slot`.`prop`; Texture's Camera / Tiled / Random / Stencil), then the
    library to pick from (its first tile: no alpha)."""
    icon = alpha_icons([texture.name]).get(texture.name, 0) if texture is not None else 0
    row = layout.row(align=True)
    if icon:
        row.template_icon(icon_value=icon, scale=3.0)
    col = row.column(align=True)
    col.label(text=texture.name if texture is not None else ALPHA_NONE, translate=False)
    col.operator("m3d.alpha_load", text="Load Alpha...", icon='FILE_FOLDER').stencil = False
    if texture is not None and modes:
        sub = col.row(align=True)
        for value, text in modes:
            sub.prop_enum(slot, prop, value, text=text)
    alpha_grid(layout, context, texture.name if texture is not None else "")


def draw_direction(layout, brush, labels=True):
    """Add / Subtract (Brush.direction) as two buttons."""
    if brush.sculpt_capabilities.has_direction:
        row = layout.row(align=True)
        row.prop_enum(brush, "direction", 'ADD', text="Add" if labels else "", icon='ADD')
        row.prop_enum(brush, "direction", 'SUBTRACT', text="Subtract" if labels else "", icon='REMOVE')


def draw_lazy(layout, brush, label=True):
    """Lazy Mouse (Stabilize Stroke): the toggle and, while it is on, the radius the stroke lags behind the cursor by."""
    if brush.brush_capabilities.has_smooth_stroke:
        row = layout.row(align=True)
        row.prop(brush, "use_smooth_stroke", text="Lazy Mouse" if label else "", icon='MOD_SMOOTH', toggle=True)
        if brush.use_smooth_stroke:
            row.prop(brush, "smooth_stroke_radius", text="Distance" if label else "", slider=True)


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
    """Add a detail level to sculpt on (the first one adds Multires to the mesh)"""
    bl_idname = "m3d.multires_subdivide"
    bl_label = "Multires Subdivide"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=(
        ('CATMULL_CLARK', "Subdivide (smooth)", "Add a level, rounding the shape"),
        ('SIMPLE', "Subdivide (keep shape)", "Add a level without rounding the shape"),
        ('LINEAR', "Subdivide (linear)", "Add a level, keeping corners and the shape exactly"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'CATMULL_CLARK': "Add a detail level, rounding the shape (the usual one)",
                'SIMPLE': "Add a detail level without rounding the shape",
                'LINEAR': "Add a detail level, keeping corners and the shape exactly"}[props.mode]

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def invoke(self, context, event):
        return m3d_pair.heavy_guard(self, context, event, next_level_faces(mesh_of(context)), "Subdivide")

    def execute(self, context):
        ob = mesh_of(context)
        if ob.use_dynamic_topology_sculpting:
            self.report({'WARNING'}, "Turn off Dynamic Detail to subdivide")
            return {'CANCELLED'}
        problem = m3d_pair.heavy_problem(next_level_faces(ob), "Subdivide")
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}
        try:
            if multires_of(ob) is None:
                bpy.ops.object.modifier_add(type='MULTIRES')
            bpy.ops.object.multires_subdivide(modifier=multires_of(ob).name, mode=self.mode)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


class M3D_OT_sculpt_level(Operator):
    """Ctrl+0 ... Ctrl+5 in Sculpt: show and sculpt this Multires level. Levels the mesh does not have are added (the
    first adds Multires); a level of millions of faces asks first"""
    bl_idname = "m3d.sculpt_level"
    bl_label = "Multires Level"
    bl_options = {'REGISTER', 'UNDO'}

    level: bpy.props.IntProperty(name="Level", min=0, max=6)

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def faces(self, ob):
        """Faces of the levels this adds (0: it adds none)."""
        mod = multires_of(ob)
        return m3d_pair.level_faces(ob, self.level) if self.level > (mod.total_levels if mod is not None else 0) else 0

    def invoke(self, context, event):
        return m3d_pair.heavy_guard(self, context, event, self.faces(mesh_of(context)), "Level %d" % self.level)

    def execute(self, context):
        ob = mesh_of(context)
        problem = m3d_pair.heavy_problem(self.faces(ob), "Level %d" % self.level)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}
        mod = multires_of(ob)
        if mod is None and self.level == 0:
            return {'CANCELLED'}
        if self.faces(ob) and ob.use_dynamic_topology_sculpting:
            self.report({'WARNING'}, "Turn off Dynamic Detail to subdivide")
            return {'CANCELLED'}
        try:
            if mod is None:
                mod = ob.modifiers.new("Multires", 'MULTIRES')
            with context.temp_override(active_object=ob, object=ob):
                for _ in range(self.level - mod.total_levels):
                    bpy.ops.object.multires_subdivide(modifier=mod.name, mode='CATMULL_CLARK')
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        mod.levels = mod.sculpt_levels = self.level
        return {'FINISHED'}


class M3D_OT_voxel_remesh(Operator):
    """Rebuild the mesh as an even mesh of faces the size of the voxel size (Detail: about how many faces that gives).
    UVs and Face Sets are lost; a remesh of millions of faces asks first"""
    bl_idname = "m3d.voxel_remesh"
    bl_label = "Voxel Remesh"
    bl_options = {'REGISTER', 'UNDO'}

    faces: bpy.props.IntProperty(name="Faces", min=0, options={'SKIP_SAVE'},
                                 description="Set the voxel size for about this many faces first (0: the size as it is)")

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is None and not ob.use_dynamic_topology_sculpting

    @classmethod
    def description(cls, _context, props):
        if props.faces:
            return "Voxel Remesh to about %s faces: an even mesh to sculpt on (UVs and Face Sets are lost)" % short_count(props.faces)
        return cls.__doc__

    def estimate(self, mesh):
        return self.faces or voxel_faces(mesh)

    def invoke(self, context, event):
        return m3d_pair.heavy_guard(self, context, event, self.estimate(mesh_of(context).data), "Voxel Remesh")

    def execute(self, context):
        mesh = mesh_of(context).data
        problem = m3d_pair.heavy_problem(self.estimate(mesh), "Voxel Remesh")
        if problem:
            self.report({'ERROR'}, problem + " (raise the voxel size)")
            return {'CANCELLED'}
        if self.faces:
            area = surface_area(mesh, grid=True)
            if area > 0:
                mesh.remesh_voxel_size = max((area / self.faces) ** 0.5, 0.0001)
        try:
            bpy.ops.object.voxel_remesh()
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        return {'FINISHED'}


def uniform_scale(ob):
    """The test Blender's sculpt mode warns with ("non-uniform scale, sculpting may be unpredictable")."""
    s = ob.scale
    return abs(s[0] - s[1]) < 1e-4 and abs(s[1] - s[2]) < 1e-4


class M3D_OT_sculpt_apply_scale(Operator):
    """Apply the object's scale to its mesh: brushes, symmetry and voxel remeshing are only even with a uniform
    scale"""
    bl_idname = "m3d.sculpt_apply_scale"
    bl_label = "Apply Scale"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and not uniform_scale(ob)

    def execute(self, context):
        ob = mesh_of(context)
        mode = ob.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')   # (Apply works in Object Mode only)
        try:
            with context.temp_override(active_object=ob, object=ob, selected_objects=[ob],
                                       selected_editable_objects=[ob]):
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        except RuntimeError as err:   # e.g. a mesh shared with another object
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        finally:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
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
    """Delete the higher levels, rebuild lower levels, or apply the sculpted shape to the base"""
    bl_idname = "m3d.multires_edit"
    bl_label = "Multires Edit"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=(
        ('DELETE_HIGHER', "Delete higher levels", "Delete the levels above the current one"),
        ('UNSUBDIVIDE', "Rebuild lower levels", "Rebuild a lower level from the lowest one"),
        ('APPLY_BASE', "Apply base shape", "Copy the sculpted shape to the base mesh and keep the detail"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'DELETE_HIGHER': "Delete the detail levels above the current one",
                'UNSUBDIVIDE': "Rebuild a lower detail level under the lowest one (for a mesh that came in already dense)",
                'APPLY_BASE': "Move the base mesh to the sculpted shape, keeping the detail on the levels"}[props.action]

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is not None

    def invoke(self, context, event):
        ob = mesh_of(context)
        message = delete_message(ob, multires_of(ob)) if self.action == 'DELETE_HIGHER' else None
        if message is None:
            return self.execute(context)
        return context.window_manager.invoke_confirm(self, event, title="Delete Higher Levels", message=message,
                                                     confirm_text="Delete", icon='ERROR')

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


def current_level(ob, mod):
    """The level Multires works on: the sculpt level in Sculpt Mode, else the display level (as Blender's own)."""
    return mod.sculpt_levels if ob.mode == 'SCULPT' else mod.levels


def level_text(ob, mod, level):
    return "level %d of %d (%s faces)" % (level, mod.total_levels, short_count(m3d_pair.level_faces(ob, level)))


def delete_message(ob, mod):
    """What Delete higher levels asks ("Delete levels 3-5 of Sphere? ..."), None when there are none above."""
    level = current_level(ob, mod)
    if level >= mod.total_levels:
        return None
    one = level + 1 == mod.total_levels
    lost = "level %d" % mod.total_levels if one else "levels %d-%d" % (level + 1, mod.total_levels)
    return "Delete %s of %s? The detail sculpted on %s is lost" % (lost, ob.name, "it" if one else "them")


def apply_message(ob, mod, highest=False):
    """What Apply Multires keeps and loses: "Keep level 2 of 5 (130k faces)? Levels 3-5 are lost"."""
    level = mod.total_levels if highest else mod.sculpt_levels
    if level >= mod.total_levels:
        return "Keep %s: all the detail stays" % level_text(ob, mod, level)
    one = level + 1 == mod.total_levels
    lost = "Level %d is" % mod.total_levels if one else "Levels %d-%d are" % (level + 1, mod.total_levels)
    return "Keep %s? %s lost" % (level_text(ob, mod, level), lost)


class M3D_OT_multires_apply(Operator):
    """Make the sculpted detail the mesh itself (Multires is removed): Voxel Remesh, Auto Retopology and Dynamic Detail
    work again"""
    bl_idname = "m3d.multires_apply"
    bl_label = "Apply Multires"
    bl_options = {'REGISTER', 'UNDO'}

    highest: bpy.props.BoolProperty(name="Use Highest Level", options={'SKIP_SAVE'},
                                    description="Keep the highest level (all the detail) instead of the level being sculpted")

    @classmethod
    def poll(cls, context):
        ob = mesh_of(context)
        return ob is not None and multires_of(ob) is not None

    def invoke(self, context, event):
        mod = multires_of(mesh_of(context))
        if mod.sculpt_levels >= mod.total_levels:
            return self.execute(context)   # (no detail is lost)
        return context.window_manager.invoke_props_dialog(self, title="Apply Multires", confirm_text="Apply", width=380)

    def draw(self, context):
        ob = mesh_of(context)
        mod = multires_of(ob)
        layout = self.layout
        draw_lines(layout, context, apply_message(ob, mod, self.highest), icon='INFO' if self.highest else 'ERROR',
                   width=380 * (context.preferences.system.ui_scale or 1.0))
        layout.prop(self, "highest", text="Use highest level (%s)" % level_text(ob, mod, mod.total_levels))

    def execute(self, context):
        ob = mesh_of(context)
        mode = ob.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')   # (Apply works in Object Mode only)
        mod = multires_of(ob)
        mod.levels = mod.render_levels = mod.total_levels if self.highest else mod.sculpt_levels   # (the level kept)
        try:
            with context.temp_override(active_object=ob, object=ob):
                bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        finally:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
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


def split_face_sets(mesh):
    """Cut the mesh apart along the borders of its face sets (each face set is then a loose part of its own). False when
    it has no face sets."""
    import bmesh
    if ".sculpt_face_set" not in mesh.attributes:
        return False
    bm = bmesh.new()
    bm.from_mesh(mesh)
    layer = bm.faces.layers.int.get(".sculpt_face_set")
    cut = [e for e in bm.edges if len({f[layer] for f in e.link_faces}) > 1]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(mesh)
    bm.free()
    return True


class M3D_OT_sculpt_object(Operator):
    """Objects tab: pick a mesh, show or hide it, solo it, append a duplicate, delete it, merge or split meshes"""
    bl_idname = "m3d.sculpt_object"
    bl_label = "Sculpt Object"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=(
        ('SELECT', "Sculpt", "Make this the active mesh"),
        ('VISIBLE', "Show / Hide", "Show or hide this mesh in the viewport"),
        ('SOLO', "Solo", "Hide every other mesh (again: show them)"),
        ('DUPLICATE', "Duplicate", "Append a copy of this mesh and sculpt it"),
        ('START', "Sculpt", "Make this the active mesh and sculpt it"),
        ('DELETE', "Delete", "Delete this mesh"),
        ('SHOW_ALL', "Show All", "Show every mesh"),
        ('MERGE', "Merge Visible", "Merge the shown meshes into this one"),
        ('SPLIT_LOOSE', "Split Loose Parts", "Make each loose part of this mesh a mesh of its own"),
        ('SPLIT_FACE_SETS', "Split Face Sets", "Make each face set of this mesh a mesh of its own"),
    ))

    @classmethod
    def description(cls, _context, props):
        return {'SELECT': "Make this the active mesh", 'VISIBLE': "Show or hide this mesh in the viewport",
                'SOLO': "Hide every other mesh; click again to show them",
                'DUPLICATE': "Append a copy of this mesh and sculpt it",
                'START': "Sculpt this mesh", 'DELETE': "Delete this mesh", 'SHOW_ALL': "Show every mesh of the scene",
                'MERGE': "Merge the shown meshes into the active one (one mesh to sculpt)",
                'SPLIT_LOOSE': "Make each loose part of the active mesh a mesh of its own",
                'SPLIT_FACE_SETS': "Make each face set of the active mesh a mesh of its own"}[props.action]

    def execute(self, context):
        meshes = [o for o in context.view_layer.objects if o.type == 'MESH']
        if self.action == 'SHOW_ALL':
            for o in meshes:
                o.hide_set(False)
            return {'FINISHED'}
        ob = bpy.data.objects.get(self.name)
        if ob is None or ob.type != 'MESH':
            return {'CANCELLED'}
        if self.action == 'DELETE':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            with context.temp_override(selected_objects=[ob], selected_editable_objects=[ob]):
                bpy.ops.object.delete()
            return {'FINISHED'}
        if self.action in {'MERGE', 'SPLIT_LOOSE', 'SPLIT_FACE_SETS'}:
            return self.reshape(context, ob, meshes)
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
        elif self.action == 'START' and context.mode != 'SCULPT':
            bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}

    def reshape(self, context, ob, meshes):
        """Merge Visible, Split Loose Parts, Split Face Sets (in Object Mode; the mode comes back)."""
        mode = context.mode
        _show_in_sculpt(context, ob)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            if self.action == 'MERGE':
                shown = [o for o in meshes if o.visible_get()]
                if len(shown) < 2:
                    self.report({'WARNING'}, "Show the meshes to merge first")
                    return {'CANCELLED'}
                for o in shown:
                    o.select_set(True)
                bpy.ops.object.join()
            else:
                if self.action == 'SPLIT_FACE_SETS' and not split_face_sets(ob.data):
                    self.report({'WARNING'}, "%s has no face sets (Face Sets tab: Make Face Sets)" % ob.name)
                    return {'CANCELLED'}
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.separate(type='LOOSE')
                bpy.ops.object.mode_set(mode='OBJECT')
                for o in context.selected_objects:   # (the new meshes come selected: only the active one stays)
                    o.select_set(o == ob)
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        finally:
            if mode == 'SCULPT' and context.mode != 'SCULPT':
                bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}


QUAD_SPHERE_CUTS = 31   # cuts of each edge of the cube the start sphere is made of: 32 x 32 quads a side, 6,144 in all


def quad_sphere(context, radius=1.0, cuts=QUAD_SPHERE_CUTS):
    """A sphere of even quads at the origin, active and selected: a cube divided `cuts` times along each edge with its
    points pushed out to the radius. No poles (a UV sphere pinches at the top and bottom) and enough faces to sculpt."""
    import bmesh
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cube(bm, size=2.0, calc_uvs=True)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    for v in bm.verts:
        v.co = v.co.normalized() * radius
    mesh = bpy.data.meshes.new("Sphere")
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()
    ob = bpy.data.objects.new("Sphere", mesh)
    context.collection.objects.link(ob)
    for other in context.selected_objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    return ob


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
        if props.kind == 'SPHERE':
            return "Add a sphere of even quads (6,144 faces) and start sculpting it"
        return "Add a %s and start sculpting it" % props.kind.lower()

    def execute(self, context):
        if self.kind == 'SPHERE':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            quad_sphere(context)
        else:
            bpy.ops.m3d.add_primitive(kind=self.kind)
        bpy.ops.object.mode_set(mode='SCULPT')
        return {'FINISHED'}


def off_centre(ob):
    """The mirror axes (of those that are on) about which the mesh is not centred: the middle of its bounding box is off
    its origin by more than 1% of its size, so a symmetric stroke lands beside the other side. O(1): the bounding box."""
    box = ob.bound_box
    lo = [min(c[i] for c in box) for i in range(3)]
    hi = [max(c[i] for c in box) for i in range(3)]
    size = max(h - l for h, l in zip(hi, lo))
    return [axis.upper() for i, axis in enumerate("xyz")
            if getattr(ob.data, "use_mirror_" + axis) and abs(lo[i] + hi[i]) / 2 > 0.01 * size]


class M3D_OT_sculpt_center_pivot(Operator):
    """Move the pivot to the middle of the mesh (the mesh stays where it is): symmetry mirrors about the pivot"""
    bl_idname = "m3d.sculpt_center_pivot"
    bl_label = "Center Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mesh_of(context) is not None

    def execute(self, context):
        ob = mesh_of(context)
        mode = ob.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            with context.temp_override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        except RuntimeError as err:
            self.report({'WARNING'}, str(err).replace("Error: ", "").strip())
            return {'CANCELLED'}
        finally:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
        return {'FINISHED'}


FEW_FACES = 5_000          # a mesh with fewer faces (no Multires, no Dynamic Detail) is too coarse to sculpt detail into
DETAIL_REMESH = 100_000    # Add Detail's Voxel Remesh: about this many faces
HEAVY_VIEW = 2_000_000     # with more faces than this the Status Line offers Fast Navigation (low resolution while navigating)


class M3D_MT_sculpt_add_detail(bpy.types.Menu):
    """The ways to give a coarse mesh enough faces to sculpt"""
    bl_label = "Add Detail"

    def draw(self, context):
        layout = self.layout
        ob = mesh_of(context)
        if ob is None:
            return
        layout.operator("m3d.voxel_remesh", text="Voxel Remesh (~%s faces)" % short_count(DETAIL_REMESH),
                        icon='MOD_REMESH').faces = DETAIL_REMESH
        faces = short_count(next_level_faces(ob))
        layout.operator("m3d.multires_subdivide", text="Subdivide (smooth) → %s faces" % faces).mode = 'CATMULL_CLARK'
        layout.operator("m3d.multires_subdivide", text="Subdivide (keep shape) → %s faces" % faces).mode = 'SIMPLE'


# --- Ctrl gestures: masking and visibility (Ctrl+LMB in the Sculpt keymap, with Alt and Shift)

CTRL_MODES = (
    ('MASK', "Mask", "Ctrl: drag on the mesh paints mask, click on it smooths the mask, click off the mesh inverts "
     "it, drag off the mesh clears it"),
    ('UNMASK', "Unmask", "Ctrl+Alt: drag on the mesh erases mask, click on it sharpens the mask, drag off the mesh "
     "unmasks a rectangle"),
    ('HIDE_OUTSIDE', "Hide Outside", "Ctrl+Shift: drag hides everything outside a rectangle, click off the mesh "
     "shows everything, click on the mesh shows only that face set"),
    ('HIDE_INSIDE', "Hide Inside", "Ctrl+Shift+Alt: drag hides everything inside a rectangle"),
)
TINY_BOX = 16   # px: a Ctrl+Alt / Ctrl+Shift drag off the mesh smaller than this (both sides) does nothing
BOX_OPS = {   # mode -> the rectangle operator and its options (a Ctrl drag off the mesh clears the mask instead)
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
        if self.mode == 'MASK':   # Off the mesh: Ctrl+drag clears the mask (a click there inverts it)
            self.run("paint.mask_flood_fill", mode='VALUE', value=0.0)
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
        return alpha_brush(context) is not None

    def execute(self, context):
        alpha_brush(context).stroke_method = self.stroke
        return {'FINISHED'}


def set_alpha(brush, texture, mask=False):
    """Use `texture` (or none) as the brush's alpha: it is mapped onto the brush, once. (A brush from the asset
    library is linked data, which can only point at linked data: the alphas are linked from the alpha library.)
    `mask`: a texture paint brush has no area mapping for its texture: the alpha is its Texture Mask, which follows the
    cursor."""
    if mask:
        brush.mask_texture = texture
        if texture is not None:
            slot = brush.mask_texture_slot
            slot.mask_map_mode = 'VIEW_PLANE'
            slot.offset = (0.0, 0.0, 0.0)
            slot.scale = (1.0, 1.0, 1.0)
            slot.angle = 0.0
        return
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
    path = os.path.join(alpha_dir(create=name in STARTER_ALPHAS), name + ".blend")
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


def give_alpha(brush, texture, context, stencil):
    """Give `texture` (or none) to the brush: as its alpha, or (`stencil`, Texture Paint Mode) as its stencil."""
    if stencil:
        import m3d_texture
        m3d_texture.set_stencil_texture(brush, texture)
    else:
        set_alpha(brush, texture, context.mode == 'PAINT_TEXTURE')


class M3D_OT_alpha_pick(Operator):
    """Use an alpha from the library as the brush texture (none: no alpha)"""
    bl_idname = "m3d.alpha_pick"
    bl_label = "Pick Alpha"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()   # an alpha_names() name, or empty for none
    stencil: bpy.props.BoolProperty(default=False, description="Use it as the stencil of the brush (Texture Paint Mode)")

    @classmethod
    def description(cls, _context, props):
        return (props.name or "No alpha") + (" as the stencil" if props.stencil and props.name else "")

    @classmethod
    def poll(cls, context):
        return alpha_brush(context) is not None

    def execute(self, context):
        tex = link_alpha(self.name) if self.name else None
        if self.name and tex is None:
            self.report({'WARNING'}, "Can't read the alpha %s from %s" % (self.name, alpha_dir()))
            return {'CANCELLED'}
        give_alpha(alpha_brush(context), tex, context, self.stencil)
        return {'FINISHED'}


class M3D_OT_alpha_load(Operator):
    """Add an image file to the alpha library and use it as the brush's alpha (a grey image: white is full strength)"""
    bl_idname = "m3d.alpha_load"
    bl_label = "Load Alpha"
    bl_options = {'INTERNAL'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    stencil: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'},
                                    description="Use it as the stencil of the brush (Texture Paint Mode)")
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return alpha_brush(context) is not None

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
        give_alpha(alpha_brush(context), link_alpha(name), context, self.stencil)
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


def draw_game_card(layout, context):
    """F2 on a game mesh without a high poly (m3d_pair.game_mesh) stays in Object Mode and asks: sculpt a high poly copy of
    it (the game mesh stays as it is, to bake onto), or this mesh itself."""
    col = empty_state(layout, context, "This is a game mesh: sculpt a high poly copy of it, or this mesh itself")
    row = col.row(align=True)
    row.scale_y = 1.3
    m3d_pair.draw_create(row, context)
    _button(row, context, "Sculpt this mesh", "object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'})


def _gate(page, need):
    """The panel a page shows instead of its own outside Sculpt Mode: how to get there. (Without a mesh the docks show
    the start card instead, see pages_shown.)"""
    def draw(self, context):
        if m3d_pair.game_mesh(context, mesh_of(context)):
            draw_game_card(self.layout, context)
            return
        empty_state(self.layout, context, "Enter Sculpt Mode to use these tools",
                    ("Sculpt Mode", "object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'}))
    return type("PROPERTIES_PT_m3d_sc_%s_gate" % page, (_PagePanel, Panel), {
        "bl_label": "Sculpt", "bl_options": {'HIDE_HEADER'}, "page": "sculpt_" + page,
        "page_poll": classmethod(lambda cls, context: mesh_of(context) is not None and not ready(context, need)),
        "draw": draw})


START_MESHES = (("Sphere", 'SPHERE', 'MESH_UVSPHERE'), ("Cube", 'CUBE', 'MESH_CUBE'), ("Plane", 'PLANE', 'MESH_PLANE'))


class PROPERTIES_PT_m3d_sc_start(_PagePanel, Panel):
    """The start card: all the dock shows while there is no mesh to sculpt (no tabs, the tray stays empty)"""
    page = "sculpt_start"
    bl_label = "Start Sculpting"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Start with a mesh to sculpt", icon='SCULPTMODE_HLT')
        row = col.row(align=True)
        row.scale_y = 1.5
        for label, kind, icon in START_MESHES:
            row.operator("m3d.sculpt_add_mesh", text=label, icon=icon).kind = kind
        sub = col.column(align=True)
        sub.operator("m3d.import_file", text="Import...", icon='IMPORT')
        sub.operator("m3d.workspace", text="Use a mesh from F1 Modeling", icon='EDITMODE_HLT').kind = 'MODEL'
        meshes = [o for o in context.view_layer.objects if o.type == 'MESH']
        if meshes:
            col.separator()
            col.label(text="Or sculpt a mesh of the scene:")
            sub = col.column(align=True)
            for ob in meshes:
                o = sub.operator("m3d.sculpt_object", text=ob.name, icon='MESH_DATA')
                o.name, o.action = ob.name, 'START'


def pages_shown(context, page):
    """The pages a Sculpt editor draws (m3d_workspace.PAGE_SETS): its own, or without a mesh to sculpt the start card in
    the dock and nothing in the tray."""
    if mesh_of(context) is None:
        return {"sculpt_start"} if side_of(context) == 'RIGHT' else set()
    return {page}


# --- Left tray: brushes

class PROPERTIES_PT_m3d_sc_grid(_Page, Panel):
    """The active brush on one line (a click opens every brush of the library, the arrow the brush's menu: save, revert...),
    then a tile per brush"""
    page = "sculpt_brushes"
    bl_label = "Brushes"

    def draw(self, context):
        layout = self.layout
        brush = sculpt_brush(context)
        if brush is not None:
            # (the stock selector, template_asset_shelf_popover, is a big preview tile outside headers)
            row = layout.row(align=True)
            name = ("* " if brush.has_unsaved_changes else "") + brush.name
            row.operator("wm.call_asset_shelf_popover", text=name, icon_value=brush.preview.icon_id if brush.preview else 0,
                         ).name = "VIEW3D_AST_brush_sculpt"
            row.menu("VIEW3D_MT_brush_context_menu", icon='DOWNARROW_HLT', text="")
        brush_tiles(layout, context, BRUSH_ASSET, BRUSHES)


class PROPERTIES_PT_m3d_sc_tuning(_Page, Panel):
    page = "sculpt_brushes"
    bl_label = "Size and Strength"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        brush = sculpt_brush(context)
        if brush is None:
            reason(layout, "Pick a brush above")
            return
        draw_brush_sliders(layout.column(), context, brush)
        row = layout.row()
        row.use_property_split = False   # (two buttons the width of the panel)
        draw_direction(row, brush, labels=fits(context, ("Add", "Subtract")))


class PROPERTIES_PT_m3d_sc_lazy(_BrushPage, Panel):
    """Lazy Mouse: the stroke lags behind the cursor by the radius (its settings show while it is on)"""
    page = "sculpt_brushes"
    bl_label = "Lazy Mouse"

    @classmethod
    def page_poll(cls, context):
        brush = sculpt_brush(context)
        return super().page_poll(context) and brush is not None and brush.brush_capabilities.has_smooth_stroke

    def draw_header(self, context):
        self.layout.prop(sculpt_brush(context), "use_smooth_stroke", text="")

    def draw(self, context):
        brush = sculpt_brush(context)
        if not brush.use_smooth_stroke:
            return
        layout = self.layout
        split_props(layout)
        draw_lazy_settings(layout, brush)


class PROPERTIES_PT_m3d_sc_strokes(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Stroke Type"

    def draw(self, context):
        stroke_tiles(self.layout, context, sculpt_brush(context))


class PROPERTIES_PT_m3d_sc_alpha(_BrushPage, Panel):
    page = "sculpt_brushes"
    bl_label = "Alpha"

    def draw(self, context):
        brush = sculpt_brush(context)
        draw_alpha(self.layout, context, brush, brush.texture)   # (how it is placed: More Brush Settings > Alpha Settings)


class PROPERTIES_PT_m3d_sc_more_brush(_PagePanel, Panel):
    """The rest of the brush settings and the Custom shelf, one section each (closed until needed)"""
    page = "sculpt_brushes"
    bl_label = "More Brush Settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, _context):
        pass


class _MoreBrush(_BrushPage):
    """A section of More Brush Settings."""
    page = "sculpt_brushes"
    bl_parent_id = "PROPERTIES_PT_m3d_sc_more_brush"
    bl_options = {'DEFAULT_CLOSED'}


class PROPERTIES_PT_m3d_sc_alpha_settings(_MoreBrush, Panel):
    bl_label = "Alpha Settings"

    def draw(self, context):
        brush = sculpt_brush(context)
        if brush.texture is None:
            reason(self.layout, "Pick an alpha above")
            return
        brush_texture_settings(self.layout.column(), brush, context.sculpt_object)


class PROPERTIES_PT_m3d_sc_more(_MoreBrush, Panel):
    bl_label = "Brush Options"

    def draw(self, context):
        split_props(self.layout)
        brush_settings(self.layout.column(), context, UnifiedPaintPanel.paint_settings(context).brush, popover=True)


class PROPERTIES_PT_m3d_sc_falloff(_MoreBrush, FalloffPanel, Panel):
    def draw(self, context):
        brush = sculpt_brush(context)
        split_props(self.layout)
        draw_falloff(self.layout.column(), brush, shape=brush.sculpt_brush_type != 'POSE')


class PROPERTIES_PT_m3d_sc_stroke(_MoreBrush, StrokePanel, Panel):
    bl_label = "Stroke Options"


class PROPERTIES_PT_m3d_sc_cursor(_MoreBrush, DisplayPanel, Panel):
    bl_label = "Cursor"


class PROPERTIES_PT_m3d_sc_advanced(_MoreBrush, Panel):
    bl_label = "Advanced"

    def draw(self, context):
        split_props(self.layout)
        settings = UnifiedPaintPanel.paint_settings(context)
        brush_settings_advanced(self.layout.column(), context, settings, settings.brush, self.is_popover)


class PROPERTIES_PT_m3d_sc_custom(_PagePanel, Panel):
    """The Custom shelf of this workspace: the top bar's shelf is hidden in Sculpt"""
    page = "sculpt_brushes"
    bl_label = "Custom Shelf"
    bl_parent_id = "PROPERTIES_PT_m3d_sc_more_brush"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        import m3d_edit
        from m3d_user import draw_custom_shelf
        draw_custom_shelf(self.layout, context, 'SCULPT', m3d_edit.editing(), tray=True)


# --- Geometry

class _Geometry(_Page):
    page = "sculpt_geometry"
    need = 'MESH'


def blocked(layout, context, ob, dyntopo=True):
    """A block that can't be used on this mesh draws one line instead: why, and the button that changes it. True when
    it is blocked: by Multires levels, or (`dyntopo`) by Dynamic Detail being on."""
    if multires_of(ob) is not None:
        row = layout.row(align=True)
        row.label(text="Not with Multires levels", icon='INFO')
        _button(row, context, "Apply Multires", "m3d.multires_apply", 'NONE', {})
        return True
    if dyntopo and ob.use_dynamic_topology_sculpting:
        dyntopo_off(layout, context)
        return True
    return False


def dyntopo_off(layout, context):
    row = layout.row(align=True)
    row.label(text="Not while Dynamic Detail is on", icon='INFO')
    _button(row, context, "Turn Off", "sculpt.dynamic_topology_toggle", 'NONE', {})


def draw_multires(layout, context):
    """Multires: Subdivide (smooth / keep shape), the level (with Lower / Higher), the display and sculpt levels, Delete
    higher levels / Rebuild lower levels / Apply base shape; Subdivide (linear), the render level and Apply Multires under
    Advanced (the Multires dock panel and the Remesh popover)."""
    ob = mesh_of(context)
    mod = multires_of(ob)
    if ob.use_dynamic_topology_sculpting:
        dyntopo_off(layout, context)
        return
    row = layout.row(align=True)
    faces = short_count(next_level_faces(ob))
    labels = [("%s → %s" % (label, faces), mode) for label, mode in (("Subdivide (smooth)", 'CATMULL_CLARK'),
                                                                     ("Subdivide (keep shape)", 'SIMPLE'))]
    wide = fits(context, [label for label, _mode in labels])
    for label, mode in labels:
        row.operator("m3d.multires_subdivide", text=label if wide else label.partition(" →")[0]).mode = mode
    if not wide:   # (a narrow dock: the face count on a line of its own)
        reason(layout, "The next level has %s faces" % faces)
    if mod is None:
        reason(layout, "Adds detail levels to sculpt on and step between")
    else:
        split_props(layout)
        row = layout.row(align=True)
        row.operator("m3d.multires_level", text="Lower", icon='TRIA_LEFT').delta = -1
        row.label(text="Level %d of %d" % (mod.sculpt_levels, mod.total_levels))
        row.operator("m3d.multires_level", text="Higher", icon='TRIA_RIGHT').delta = 1
        col = layout.column(align=True)
        col.prop(mod, "levels", text="Display level")
        col.prop(mod, "sculpt_levels", text="Sculpt level")
        flow = layout.grid_flow(columns=1, align=True)
        for action, label in (('DELETE_HIGHER', "Delete higher levels"), ('UNSUBDIVIDE', "Rebuild lower levels"),
                              ('APPLY_BASE', "Apply base shape")):
            flow.operator("m3d.multires_edit", text=label).action = action
    header, body = layout.panel("m3d_multires_advanced", default_closed=True)
    header.label(text="Advanced")
    if body:
        body.operator("m3d.multires_subdivide", text="Subdivide (linear)").mode = 'LINEAR'
        if mod is not None:
            split_props(body)
            body.prop(mod, "render_levels", text="Render level")
            body.operator("m3d.multires_apply")


def draw_voxel_detail(layout, mesh, text="Detail: "):
    """The Detail slider: the voxel size as the face count Voxel Remesh gives (a log scale, DETAIL_FACES)."""
    layout.prop(mesh, "m3d_voxel_detail", text="%s~%s faces" % (text, short_count(voxel_faces(mesh))), slider=True)


def draw_voxel(layout, context):
    """Voxel Remesh: the Detail slider and the button; the voxel size and the options under Advanced."""
    ob = mesh_of(context)
    if blocked(layout, context, ob):
        return
    mesh = ob.data
    draw_voxel_detail(layout, mesh)
    _button(layout, context, "Voxel Remesh", "m3d.voxel_remesh", 'MOD_REMESH', {})
    header, body = layout.panel("m3d_voxel_advanced", default_closed=True)
    header.label(text="Advanced")
    if body:
        split_props(body)
        row = body.row(align=True)
        row.prop(mesh, "remesh_voxel_size")
        _button(row, context, "", "sculpt.sample_detail_size", 'EYEDROPPER', {"mode": 'VOXEL'})
        body.prop(mesh, "remesh_voxel_adaptivity")
        body.prop(mesh, "use_remesh_fix_poles")
        sub = body.column(heading="Preserve", align=True)
        sub.prop(mesh, "use_remesh_preserve_volume", text="Volume")
        sub.prop(mesh, "use_remesh_preserve_attributes", text="Attributes")


def draw_quadriflow(layout, context):
    """Retopology: the low poly of this sculpt, made for you (Auto Low Poly, a paired copy: the sculpt stays) or drawn over
    it (Quad Draw, symmetric or not); under Advanced the mesh itself rebuilt as even quads (Rebuild as Quads: the target
    face count, ratio or edge length and its options)."""
    ob = mesh_of(context)
    lows, highs = m3d_pair.pair_of(context, ob)
    if lows and highs:
        reason(layout, "This mesh has a low poly: %s" % lows[0].name)
    else:
        col = layout.column(align=True)
        m3d_pair.draw_make_low(col, context)
        reason(layout, "Makes the low poly as a new mesh paired with this one, which stays as it is")
    header, body = layout.panel("m3d_quadriflow_advanced", default_closed=True)
    header.label(text="Advanced")
    if not body or blocked(body, context, ob):
        return
    split_props(body)
    col = body.column()
    props = context.window_manager.operator_properties_last("object.quadriflow_remesh")
    col.prop(props, "mode")
    col.prop(props, {'RATIO': "target_ratio", 'EDGE': "target_edge_length", 'FACES': "target_faces"}[props.mode])
    col.prop(props, "use_mesh_symmetry")
    col.prop(props, "use_preserve_sharp")
    col.prop(props, "use_preserve_boundary")
    col.prop(props, "smooth_normals")
    reason(col, "Rebuilds this mesh itself (UVs and Face Sets are lost)")
    _button(col, context, "Rebuild as Quads", "m3d.retopo_quads", 'MOD_REMESH', {})


def draw_dyntopo(layout, context):
    """Dynamic Detail (dynamic topology: strokes add and remove faces as they go): the switch and, while it is on, the
    detail size (how it is measured follows the Detailing method)."""
    ob = mesh_of(context)
    if blocked(layout, context, ob, dyntopo=False):
        return
    if context.mode != 'SCULPT':
        reason(layout, "Enter Sculpt Mode to use Dynamic Detail")
        return
    split_props(layout)
    sculpt = context.tool_settings.sculpt
    on = ob.use_dynamic_topology_sculpting
    _button(layout, context, "Turn Off Dynamic Detail" if on else "Turn On Dynamic Detail",
            "sculpt.dynamic_topology_toggle", 'CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT', {}, depress=on)
    if not on:
        reason(layout, "Strokes add and remove faces as they go")
        layout.label(text="Turning it on removes UVs and Face Sets", icon='ERROR')
        return
    col = layout.column()
    method = sculpt.detail_type_method
    if method in {'CONSTANT', 'MANUAL'}:
        row = col.row(align=True)
        row.prop(sculpt, "constant_detail_resolution")
        _button(row, context, "", "sculpt.sample_detail_size", 'EYEDROPPER', {"mode": 'DYNTOPO'})
    elif method == 'BRUSH':
        col.prop(sculpt, "detail_percent")
    else:
        col.prop(sculpt, "detail_size")
    col.prop(sculpt, "detail_refine_method", text="Refine Method")
    col.prop(sculpt, "detail_type_method", text="Detailing")
    if method in {'CONSTANT', 'MANUAL'}:
        _button(col, context, "Flood Fill Detail", "sculpt.detail_flood_fill", 'NONE', {})


class PROPERTIES_PT_m3d_sc_multires(_Geometry, Panel):
    bl_label = "Multires"

    def draw(self, context):
        draw_multires(self.layout, context)


class PROPERTIES_PT_m3d_sc_voxel(_Geometry, Panel):
    bl_label = "Voxel Remesh"

    def draw(self, context):
        draw_voxel(self.layout, context)


class PROPERTIES_PT_m3d_sc_quadriflow(_Geometry, Panel):
    bl_label = "Retopology"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        draw_quadriflow(self.layout, context)


class PROPERTIES_PT_m3d_sc_dyntopo(_Geometry, Panel):
    bl_label = "Dynamic Detail"
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
        col = layout.column(align=True)
        for i, text in enumerate(("Ctrl+drag: mask | Ctrl+Alt+drag: unmask", "Off the mesh: Ctrl+drag clears, Ctrl+click inverts",
                                  "Expand: Shift+A over the mesh (Shift+W: face sets)")):
            draw_lines(col, context, text, icon='INFO' if i == 0 else 'BLANK1')   # (one hint: the keys of the mask)
        space = viewport(context)
        if space is not None:
            # How the mask shows (the viewport's mask overlay): on / off, its color and opacity.
            overlay = space.overlay
            row = layout.row(align=True)
            row.prop(overlay, "show_sculpt_mask", text="Show Mask", toggle=True)
            if overlay.show_sculpt_mask:
                sub = row.row(align=True)
                sub.ui_units_x = 2
                sub.prop(overlay, "sculpt_mode_mask_color", text="")
                row.prop(overlay, "sculpt_mode_mask_opacity", text="Opacity", slider=True)


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
        reason(self.layout, "Ctrl+Shift+drag: hide outside | +Alt: inside | click: show")


# --- Face Sets

class _FaceSets(_Page):
    page = "sculpt_face_sets"


# Every way of making face sets (the Make Face Sets menu is the operator's own list; the tests run each)
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
    """Make face sets from a part of the mesh: loose parts, materials, UV seams... (one menu and the button)"""
    bl_label = "Make Face Sets"

    def draw(self, context):
        props = context.window_manager.operator_properties_last("sculpt.face_sets_init")
        row = self.layout.row(align=True)   # [Face Sets from Loose Parts v] [Make]
        sub = row.row(align=True)
        sub.scale_x = 2.0
        sub.prop(props, "mode", text="")
        _button(row, context, "Make", "sculpt.face_sets_init", 'NONE', {"mode": props.mode})


class PROPERTIES_PT_m3d_sc_fs_create(_FaceSets, Panel):
    bl_label = "Create"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_CREATE, columns=3)


class PROPERTIES_PT_m3d_sc_fs_edit(_FaceSets, Panel):
    bl_label = "Edit"

    def draw(self, context):
        tools_grid(self.layout, context, FACE_SET_EDIT)
        reason(self.layout, "Then click a face set in the viewport")


class PROPERTIES_PT_m3d_sc_fs_visibility(_FaceSets, Panel):
    bl_label = "Visibility"

    def draw(self, context):
        grid(self.layout, context, FACE_SET_VISIBILITY)
        reason(self.layout, "Hide / show one set: H over it")


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
        reason(layout, "Pick a filter, then drag in the viewport")


class PROPERTIES_PT_m3d_sc_symmetrize(_Deform, Panel):
    bl_label = "Symmetrize"

    def draw(self, context):
        layout = self.layout
        split_props(layout)
        layout.prop(context.tool_settings.sculpt, "symmetrize_direction", text="Direction")
        layout.operator("sculpt.symmetrize", icon='MOD_MIRROR')
        header, body = layout.panel("m3d_symmetrize_advanced", default_closed=True)
        header.label(text="Advanced")
        if body:
            body.prop(context.window_manager.operator_properties_last("sculpt.symmetrize"), "merge_tolerance")


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
        reason(layout, "These paint vertex colors; paint textures in F4 Texture")
        grid(layout, context, [(label, "brush.asset_activate", 'NONE', brush_props(name))
                               for label, name in PAINT_BRUSHES], columns=3,
             active=lambda idname, props: is_active(context, idname, props))
        if mesh.color_attributes.active_color is None:
            layout.label(text="This mesh has no vertex colors yet", icon='ERROR')
            layout.operator_context = 'EXEC_DEFAULT'   # No options dialog: the defaults are what you want.
            _button(layout, context, "Add Vertex Colors", "geometry.color_attribute_add", 'ADD',
                    {"name": "Color", "domain": 'POINT', "data_type": 'BYTE_COLOR', "color": (0.8, 0.8, 0.8, 1.0)})
        settings = UnifiedPaintPanel.paint_settings(context)
        brush = settings.brush if settings else None
        if brush is None or not brush.sculpt_capabilities.has_color:
            reason(layout, "Pick a color brush above")
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
        reason(self.layout, "Pick a filter, then drag in the viewport")


# --- Display

def draw_shading(layout, context, units_x=0):
    """Viewport look for sculpting: matcap / studio light (a grid of thumbnails), color, cavity (the Display tab and
    the matcap popover, which is `units_x` wide)."""
    space = viewport(context)
    if space is None:
        reason(layout, "No 3D Viewport in this workspace")
        return
    shading = space.shading
    names = [i.name for i in shading.bl_rna.properties["type"].enum_items]
    layout.row().prop(shading, "type", expand=True, icon_only=not fits(context, names))   # (icons and tooltips when narrow)
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
        # (the mask's look is on the Mask tab)
        for flag, opacity, label in (("show_sculpt_face_sets", "sculpt_mode_face_sets_opacity", "Face Sets"),
                                     ("show_wireframes", "wireframe_opacity", "Wireframe")):
            row = layout.row(align=True)
            row.use_property_split = False   # (the whole width: the toggle and its opacity both fit on a narrow dock)
            row.prop(overlay, flag, text=label, toggle=True)
            if getattr(overlay, flag):
                row.prop(overlay, opacity, text="Opacity")


class PROPERTIES_PT_m3d_sc_performance(_Display, Panel):
    bl_label = "Performance"

    @classmethod
    def page_poll(cls, context):
        return context.tool_settings.sculpt is not None

    def draw(self, context):
        layout = self.layout
        sculpt = context.tool_settings.sculpt
        col = layout.column(align=True)   # (no split: the long names fit on a narrow dock)
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
        active = mesh_of(context)
        if not meshes:
            reason(layout, "No meshes in the scene")
        elif active:
            m3d_pair.draw_sculpt_status(layout, context, active)
        col = layout.column(align=True)
        for ob in meshes:
            hidden = ob.hide_get()
            others = [o for o in meshes if o is not ob]
            solo = bool(others) and all(o.hide_get() for o in others) and not hidden
            row = col.row(align=True)
            o = row.operator("m3d.sculpt_object", text="", icon='HIDE_ON' if hidden else 'HIDE_OFF')
            o.name, o.action = ob.name, 'VISIBLE'
            sub = row.row(align=True)
            sub.active = not hidden
            role = ob.m3d_pair.role
            badge = "" if role == 'NONE' else "  · " + m3d_pair.ROLE_LABEL[role]
            if ob is active:   # (the active mesh's name is a field: click it to rename)
                sub.prop(ob, "name", text="")
                sub.label(text="%s faces%s" % (short_count(face_count(ob)), badge))
            else:
                o = sub.operator("m3d.sculpt_object", text="%s  (%s faces)%s" % (ob.name, format(face_count(ob), ","), badge))
                o.name, o.action = ob.name, 'SELECT'
            o = row.operator("m3d.sculpt_object", text="", icon='SOLO_ON' if solo else 'SOLO_OFF', depress=solo)
            o.name, o.action = ob.name, 'SOLO'
            o = row.operator("m3d.sculpt_object", text="", icon='DUPLICATE')
            o.name, o.action = ob.name, 'DUPLICATE'
            o = row.operator("m3d.sculpt_object", text="", icon='X')
            o.name, o.action = ob.name, 'DELETE'
        if not meshes:
            return
        flow = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        if any(o.hide_get() for o in meshes):
            flow.operator("m3d.sculpt_object", text="Show All", icon='HIDE_OFF').action = 'SHOW_ALL'
        if active is not None:
            for label, action, icon in (("Merge Visible", 'MERGE', 'AUTOMERGE_ON'), ("Split Loose Parts", 'SPLIT_LOOSE', 'MOD_EXPLODE'),
                                        ("Split Face Sets", 'SPLIT_FACE_SETS', 'FACE_MAPS')):
                o = flow.operator("m3d.sculpt_object", text=label, icon=icon)
                o.name, o.action = active.name, action


GATES = {"sculpt_brushes": 'SCULPT', "sculpt_geometry": 'MESH', "sculpt_mask": 'SCULPT', "sculpt_face_sets": 'SCULPT',
         "sculpt_deform": 'SCULPT', "sculpt_paint": 'SCULPT'}
# Registered first so a page's message comes before its panels (they are never shown together).
PAGE_GATES = tuple(_gate(page[len("sculpt_"):], need) for page, need in GATES.items())
PAGE_SETS['SCULPT'] = pages_shown


def draw_dock_header(layout, context):
    """Header of the tray and the dock: their tabs, none while there is no mesh to sculpt (the start card is all there is)."""
    if mesh_of(context) is not None:
        draw_tab_row(layout, context)


HEADERS[('SCULPT', 'LEFT')] = HEADERS[('SCULPT', 'RIGHT')] = draw_dock_header

# The tools whose settings a page shows while one of them is the active tool (Sculpt's viewport has no tool settings row;
# All Settings > Tool has them too).
PAGE_TOOLS = {
    "sculpt_mask": {"builtin.box_mask", "builtin.lasso_mask", "builtin.line_mask", "builtin.polyline_mask",
                    "builtin.mask_by_color", "builtin.box_hide", "builtin.lasso_hide", "builtin.line_hide",
                    "builtin.polyline_hide"},
    "sculpt_face_sets": {"builtin.face_set_edit", "builtin.box_face_set", "builtin.lasso_face_set",
                         "builtin.line_face_set", "builtin.polyline_face_set"},
    "sculpt_deform": {"builtin.mesh_filter", "builtin.cloth_filter", "builtin.box_trim", "builtin.lasso_trim",
                      "builtin.line_trim", "builtin.polyline_trim", "builtin.line_project"},
    "sculpt_paint": {"builtin.color_filter"},
}


def _tool_panel(page, tools):
    """Tool Settings of a page: the settings of the active tool when it is one of `tools`."""
    def draw(self, context):
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        layout = self.layout
        split_props(layout)
        ToolSelectPanelHelper.draw_active_tool_header(context, layout.column(), show_tool_icon_always=True,
                                                      tool_key=('VIEW_3D', 'SCULPT'))
    return type("PROPERTIES_PT_m3d_sc_%s_tool" % page[len("sculpt_"):], (_PagePanel, Panel), {
        "bl_label": "Tool Settings", "page": page, "draw": draw,
        "page_poll": classmethod(lambda cls, context: ready(context, 'SCULPT')
                                 and getattr(active_tool(context), "idname", None) in tools)})


TOOL_PANELS = tuple(_tool_panel(page, tools) for page, tools in PAGE_TOOLS.items())


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
    """Brush options: size, strength, hardness, add / subtract, Lazy Mouse, stroke type, falloff"""
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
        draw_brush_sliders(layout.column(), context, brush)
        draw_direction(layout, brush)
        if brush.brush_capabilities.has_smooth_stroke:
            layout.separator()
            layout.prop(brush, "use_smooth_stroke", text="Lazy Mouse")
            if brush.use_smooth_stroke:
                draw_lazy_settings(layout, brush)
        layout.separator()
        stroke_tiles(layout, context, brush, M3D_PT_sculpt_brush.bl_ui_units_x)
        layout.separator()
        draw_falloff(layout.column(align=True), brush, shape=brush.sculpt_brush_type != 'POSE')


class M3D_PT_sculpt_remesh(Panel):
    """Remesh and topology: Voxel Remesh, Retopology, Multires levels and Dynamic Detail"""
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
                                         ("quadriflow", "Retopology", draw_quadriflow, True),
                                         ("multires", "Multires", draw_multires, True),
                                         ("dyntopo", "Dynamic Detail", draw_dyntopo, True)):
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
    Remesh popover (and on a wide window Voxel Remesh's Detail), face count and Multires level, Dynamic Detail, symmetry,
    Auto-Masking, Mask / Face Set overlays, matcap."""
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
        layout.separator()
        draw_brush_controls(layout, context, brush, tier)
    layout.separator()
    layout.popover("M3D_PT_sculpt_remesh", text="Remesh" if tier else "", icon='MOD_REMESH')
    if tier == 2 and mod is None and not dyntopo:
        # Voxel Remesh in place (the popover has the options, Auto Retopology, Multires and Dynamic Detail).
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.ui_units_x = 7
        draw_voxel_detail(sub, mesh, text="")
        _button(row, context, "Remesh", "m3d.voxel_remesh", 'NONE', {})
    # The mesh data is not updated while Dynamic Detail changes it, so no count then (the viewport's statistics have it).
    layout.separator()
    faces = face_count(ob)
    if dyntopo:
        layout.label(text="Dynamic Detail")
    elif mod is None and faces < FEW_FACES:
        row = layout.row(align=True)
        row.alert = True
        row.ui_units_x = 10 if tier else 6   # (a header sizes a menu button for its text poorly)
        row.menu("M3D_MT_sculpt_add_detail", text="Too few faces: Add Detail" if tier else "Add Detail", icon='ERROR')
    else:
        layout.label(text="%s faces" % format(faces, ","))
        if sculpting and faces > HEAVY_VIEW and not context.tool_settings.sculpt.show_low_resolution:
            layout.prop(context.tool_settings.sculpt, "show_low_resolution", text="Fast Navigation" if tier else "",
                        icon='MOD_DECIM', toggle=True)
    m3d_pair.draw_sculpt_status(layout, context, ob, tier > 0)
    if not uniform_scale(ob):
        row = layout.row(align=True)
        row.alert = True
        row.operator("m3d.sculpt_apply_scale", icon='ERROR')
    if mod is not None:
        row = layout.row(align=True)
        row.operator("m3d.multires_level", text="", icon='TRIA_LEFT').delta = -1
        row.label(text="Lv %d/%d" % (mod.sculpt_levels, mod.total_levels))
        row.operator("m3d.multires_level", text="", icon='TRIA_RIGHT').delta = 1
    if sculpting and mod is None:
        _call(layout.row(align=True), "sculpt.dynamic_topology_toggle", 'CHECKBOX_HLT' if dyntopo else 'CHECKBOX_DEHLT',
              "Dynamic Detail: strokes add and remove faces as they go", depress=dyntopo)
    layout.separator()
    row = layout.row(align=True)
    for axis in "xyz":
        row.prop(mesh, "use_mirror_" + axis, text=axis.upper(), toggle=True)
    if off_centre(ob):
        row = layout.row(align=True)
        row.alert = True
        row.operator("m3d.sculpt_center_pivot", text="Off-centre: Center Pivot" if tier else "Center Pivot", icon='ERROR')
    if sculpting:
        layout.popover("M3D_PT_sculpt_automasking", text="Auto-Masking" if tier else "", icon='NONE' if tier else 'MOD_MASK')
    space = viewport(context)
    if space is not None:
        layout.separator()
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
        sub.scale_x = 3.75
        draw_voxel_detail(sub, ob.data, text="")


SHELF_BRUSHES = [
    ("object.mode_set", 'SCULPTMODE_HLT', {"mode": 'SCULPT'}),
    None,
    *(brush_item(label, name) for label, name in BRUSHES),
]
SHELF_REMESH = [
    ("m3d.voxel_remesh", 'MOD_REMESH', {}),
    _voxel_size,
    None,
    ("m3d.hp_auto_low", 'MOD_DECIM', {}),
    ("m3d.retopo_quads", 'MESH_GRID', {}),
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
    M3D_OT_pick_object,
    M3D_OT_sculpt_tool,
    M3D_OT_multires_subdivide,
    M3D_OT_sculpt_level,
    M3D_OT_voxel_remesh,
    M3D_OT_sculpt_center_pivot,
    M3D_MT_sculpt_add_detail,
    M3D_OT_sculpt_apply_scale,
    M3D_OT_multires_level,
    M3D_OT_multires_edit,
    M3D_OT_multires_apply,
    M3D_OT_sculpt_object,
    M3D_OT_sculpt_add_mesh,
    M3D_OT_sculpt_ctrl,
    M3D_OT_brush_pick,
    M3D_OT_stroke_pick,
    M3D_OT_alpha_pick,
    M3D_OT_alpha_load,
    M3D_OT_light_pick,
    *PAGE_GATES,
    PROPERTIES_PT_m3d_sc_start,
    PROPERTIES_PT_m3d_sc_grid,
    PROPERTIES_PT_m3d_sc_tuning,
    PROPERTIES_PT_m3d_sc_lazy,
    PROPERTIES_PT_m3d_sc_strokes,
    PROPERTIES_PT_m3d_sc_alpha,
    PROPERTIES_PT_m3d_sc_more_brush,
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
    *TOOL_PANELS,
    M3D_PT_sculpt_automasking,
    M3D_PT_sculpt_shading,
    M3D_PT_sculpt_brush,
    M3D_PT_sculpt_remesh,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Mesh.m3d_voxel_detail = bpy.props.FloatProperty(
        name="Detail", subtype='PERCENTAGE', min=0.0, max=100.0, precision=0, get=_detail_get, set=_detail_set,
        options=set(),
        description="How fine Voxel Remesh makes the mesh: the voxel size as the number of faces it gives (an estimate "
                    "from the surface area; the size itself is under Advanced)")


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    del bpy.types.Mesh.m3d_voxel_detail
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
