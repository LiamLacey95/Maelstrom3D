# SPDX-License-Identifier: GPL-2.0-or-later
"""
Apply the MayaBlender (Autodesk Maya look-alike) theme to the running Blender preferences.

Source of truth for 'release/datafiles/userdef/userdef_default_theme.c'. Regenerate with:

    tools/maya/regen_theme.sh <path-to-blender.exe>
"""

import bpy

MAYA_BLUE = (0.322, 0.522, 0.651)          # Maya selection highlight (#5285a6).
BLENDER_BLUE = (0.278, 0.447, 0.702)


def _is_grey(c):
    return max(c[:3]) - min(c[:3]) < 0.03


def _maya_grey(v, is_text):
    if is_text:
        return v * 0.87 if 0.6 < v < 0.99 else v  # Maya text is #c8c8c8-ish, not white.
    if 0.0 < v < 0.45:
        return min(0.06 + v * 1.1, 0.5)    # Maya UI is a lighter grey (#444 base, #2b fields).
    return v


def _remap(owner, depth=0):
    for prop in owner.bl_rna.properties:
        ident = prop.identifier
        if ident == "rna_type" or prop.is_readonly and prop.type != 'POINTER':
            continue
        value = getattr(owner, ident)
        if prop.type == 'POINTER':
            if value is not None and depth < 4:
                _remap(value, depth + 1)
            continue
        if prop.type != 'FLOAT' or prop.subtype not in {'COLOR', 'COLOR_GAMMA'}:
            continue
        c = list(value)
        if all(abs(a - b) < 0.01 for a, b in zip(c[:3], BLENDER_BLUE)):
            c[:3] = MAYA_BLUE
        elif _is_grey(c) and c[0] > 0.0:
            is_text = "text" in ident or "title" in ident
            c[:3] = [_maya_grey(x, is_text) for x in c[:3]]
        else:
            continue
        setattr(owner, ident, c)


def _set(owner, **kw):
    for k, v in kw.items():
        setattr(owner, k, v)


def apply(theme=None):
    t = theme or bpy.context.preferences.themes[0]

    # Global pass: lighten Blender's dark greys to Maya's mid greys, swap the accent blue.
    for ident in t.bl_rna.properties.keys():
        if ident in {"rna_type", "name", "theme_area", "common"}:
            continue
        sub = getattr(t, ident)
        if hasattr(sub, "bl_rna"):
            _remap(sub)

    ui = t.user_interface
    # Maya widgets: flatter, squarer, #5d5d5d buttons on #444 panels, #2b2b2b fields.
    for wname in ("wcol_regular", "wcol_tool", "wcol_radio", "wcol_option", "wcol_toggle",
                  "wcol_num", "wcol_numslider", "wcol_box", "wcol_pulldown", "wcol_menu"):
        w = getattr(ui, wname, None)
        if w is None:
            continue
        w.roundness = 0.15
        if wname in {"wcol_regular", "wcol_tool", "wcol_radio", "wcol_toggle", "wcol_num", "wcol_numslider"}:
            w.inner = (0.365, 0.365, 0.365, 1.0)
            w.outline = (0.235, 0.235, 0.235, 1.0)
    ui.wcol_text.inner = (0.169, 0.169, 0.169, 1.0)
    ui.wcol_text.roundness = 0.15
    ui.panel_roundness = 0.1

    v3d = t.view_3d
    # Maya default viewport: steel-blue to near-black gradient.
    _set(v3d.space.gradients,
         background_type='LINEAR',
         high_gradient=(0.533, 0.616, 0.702),
         gradient=(0.071, 0.071, 0.071))
    _set(v3d,
         grid=(0.45, 0.45, 0.45, 0.6),
         grid_major=(0.30, 0.30, 0.30, 1.0),
         wire=(0.0, 0.016, 0.375),               # Maya unselected wireframe: dark blue.
         wire_edit=(0.35, 0.62, 0.85),           # Component-mode wire: light blue.
         object_active=(0.263, 1.0, 0.639),      # Maya lead selection: green.
         object_selected=(1.0, 1.0, 1.0),        # Maya other selection: white.
         vertex=(0.75, 0.2, 0.75),               # Maya vertices: magenta.
         vertex_select=(1.0, 1.0, 0.0),          # Selected vertices: yellow.
         vertex_size=4,
         edge_select=(1.0, 0.55, 0.0),           # Selected edges: orange.
         edge_mode_select=(1.0, 0.55, 0.0),
         face_select=(1.0, 0.55, 0.0, 0.35),
         face_mode_select=(1.0, 0.55, 0.0, 0.35),
         editmesh_active=(1.0, 1.0, 1.0, 0.4),
         camera=(0.0, 0.016, 0.375),
         empty=(0.0, 0.016, 0.375),
         light=(0.0, 0.016, 0.375, 0.5))

    anim = t.common.anim
    anim.playhead = (0.85, 0.2, 0.2)              # Maya red time cursor.
    anim.keyframe = (0.8, 0.15, 0.15)             # Maya red key ticks.
    anim.keyframe_selected = (1.0, 1.0, 0.0)

    t.name = "Default"


if __name__ == "__main__":
    apply()
