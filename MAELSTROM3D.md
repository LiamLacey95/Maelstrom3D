# Maelstrom3D

Blender 5.2.2 LTS based 3D suite (git branch `maelstrom3d`) with a classic studio workflow: menu sets, Status
Line, shelves, Channel Box dock, marking menus, toolkits and a MEL command line.
Run `Maelstrom3D.exe` (or `blender.exe`). Everything is on by default; there is nothing to configure.

*Autodesk and Maya are registered trademarks of Autodesk, Inc. Maelstrom3D is not affiliated with Autodesk; Maya is
named here only to describe compatibility.*

- Full list of changed shortcuts: [SHORTCUTS.md](SHORTCUTS.md) (generated from the keymap).
- Self-checks: `tools/m3d/test_m3d.py` (background) and `tools/m3d/gui_test.py` (real window, simulated input).

## What changed vs. stock Blender

| Area | Change | Where |
|---|---|---|
| Keymap | Default keymap is **Maelstrom3D** (Blender's Industry Compatible keymap plus classic studio-style overrides) | `scripts/presets/keyconfig/Maelstrom3D.py`, `DNA_userdef_types.h` |
| Theme | Mid greys, `#5285a6` highlight, steel-blue to black viewport gradient, green lead / white selection, magenta verts, yellow/orange selected components, red playhead | `release/datafiles/userdef/userdef_default_theme.c` (from `tools/m3d/theme.py`) |
| Startup | Empty scene (camera `persp` and light hidden), a 35 mm-equivalent default camera field of view, dock opens on Channel Box, no splash, solid toolbox/dock strips, Segoe UI font | `versioning_defaults.cc`, `m3d_mode.py` (factory startup / preferences handlers) |
| Layout | Classic: Outliner left, Attribute Editor dock right, Time Slider and Command Line bottom. Workspaces: Classic, Modeling - Standard, Sculpting, UV Editing, Rigging, Animation, Hypershade, Rendering, 3D Paint, Node Editor, Script Editor | `release/datafiles/startup.blend` (from `tools/m3d/build_startup.py`) |
| Top rows | Four stacked rows: menu bar (menu set dropdown + File/Edit/Create/Select/Modify/Display/Windows + menu-set menus + Help), Status Line (with "Workspace:"), shelf tabs, shelf buttons | `screen_edit.cc`, `space_topbar.cc` (extra top-bar rows), `m3d_ui.py`, `bl_ui/space_topbar.py` |
| Shelf | Shelf tabs (Curves/Surfaces, Poly Modeling, Sculpting, Rigging, Animation, Rendering, FX) and large buttons in the top rows | `m3d_ui.py` |
| Viewport | Panel menus (View, Shading, Lighting, Show, Renderer, Panels) and panel toolbar only (Blender's menus under "..."), viewport HUD (camera name, axis triad) | `m3d_ui.py`, `m3d_hud.py`, `bl_ui/space_view3d.py` |
| Right-hand dock | Tabs on the right edge: Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, then the Attribute Editor tabs (Object, Modifiers, Material, ...) | `space_buttons.cc`, `buttons_context.cc`, `DNA_space_enums.h`, `rna_space.cc`, `m3d_mode.py` |
| Editor names | Attribute Editor, Shader Editor, Script Editor, Command Line, Command History, Time Editor | `rna_space.cc`, `node_shader_tree.cc` |
| Marking menus | RMB, Shift+RMB, Ctrl+RMB in the viewport; RMB, Shift+RMB in the UV Editor; Space hotbox | `m3d_mode.py`, `m3d_uv.py` |
| UV editing | UV Toolkit, Cut/Sew/Unfold/Layout workflow, checker map | `scripts/startup/m3d_uv.py` |
| Title | Window title says Maelstrom3D | `wm_window.cc` |

## Everyday controls

| Key | Action |
|---|---|
| Alt+LMB / MMB / RMB | Tumble / Track / Dolly |
| F / A (Shift: all views) | Frame selected / Frame all |
| Q W E R T | Select / Move / Rotate / Scale / Universal manipulator |
| Click, Shift, Ctrl, Ctrl+Shift | Select, toggle, deselect, add (click and drag) |
| RMB (hold) | Marking menu (see below) |
| Shift+RMB | Object mode: create primitives. Component mode: polygon tools |
| Ctrl+RMB | Convert selection (vertices, edges, faces, loop, ring, border, shell) |
| Shift+drag manipulator | Components: extrude along that axis. Objects: duplicate |
| Ctrl+Shift+drag manipulator | Slide components along their edges |
| Q / W / E / R / A / H (hold) + left click | Select / Move / Rotate / Scale / History / Menu set marking menus |
| Shift+S (hold) + left click | Keyframe marking menu |
| Ctrl+Shift+RMB | Transform options: symmetry, soft select, preserve UVs, tweak |
| B (tap / hold + drag) | Toggle soft select / set its radius |
| [ / ] | Undo / redo view change |
| Alt+arrows, arrows | Nudge one pixel, pickwalk (up/down hierarchy, left/right siblings) |
| Y, Ctrl+T | Last tool, universal manipulator |
| Ctrl+Shift+Q / X | Quad Draw / Multi-Cut |
| Alt+B, Alt+1/2/4/5 | Cycle background, toggle curves / meshes / image planes / wireframe |
| Shift+{ / Shift+}, F1 | Previous / next workspace, help |
| D (hold) / Insert | Edit pivot: objects move their origin; components move a custom pivot. Modify > Reset Pivot to go back |
| Space tap / hold | Four view / hotbox (every menu) |
| F2 / F3 / F4 / F5 / F6 | Menu set: Modeling / Rigging / Animation / FX / Rendering (Maya 2025) |
| F8, F9, F10, F11, F12 | Object/component toggle, Vertex, Edge, Face, UV Editing |
| Ctrl+F9 / F10 / F11 | Convert selection to vertices / edges / faces |
| 1 / 2 / 3, Page Up / Down | Smooth preview off / cage / smooth, more / fewer divisions |
| 4 / 5 / 6 / 7 | Wireframe / Shaded / Textured / Lighting |
| Ctrl+D, Shift+D, Ctrl+Shift+D | Duplicate in place, duplicate with transform, duplicate as instance |
| Ctrl+G, P, Shift+P | Group, parent, unparent |
| Ctrl+H, Alt+H, Ctrl+Shift+H | Hide selected, hide unselected, show hidden |
| Ctrl+1, Shift+L | Isolate select |
| X / C / V / J (hold) | Snap to grid / curve / point / increments |
| > / < | Grow / shrink selection |
| Up / Down | Pickwalk to parent / child |
| Z / Ctrl+Z, Shift+Z / Ctrl+Y, G | Undo, redo, repeat last |
| Delete | Faces deleted; edges and vertices dissolved |
| Ctrl+E, Ctrl+B | Extrude, bevel |
| Ctrl+A | Channel Box / Attribute Editor |
| S, Shift+W/E/R | Set key, key translate/rotate/scale |
| , / . , Alt+, / Alt+. | Previous / next key, previous / next frame |
| Alt+V, Alt+Shift+V | Play / stop, go to start |
| = / - | Bigger / smaller manipulator |
| Ctrl+Space, Shift+M, Ctrl+Shift+M | Maximize panel, panel menu bar, shelf row |
| Ctrl+R, Ctrl+X | Create reference, cut |

## Right-click marking menu

- **Object mode:** Vertex, Edge, Face, Multi, Object Mode, Group, Select All, More (Blender's object menu).
- **Component mode:** the same mode switches, plus a list underneath with every tool for what is selected:
  - Vertex: Extrude, Chamfer, Connect, Merge, Merge to Center, Target Weld, Average, Slide, Detach, Create Polygon, Delete.
  - Edge: Extrude, Bevel, Bridge, Connect, Insert Edge Loop, Offset Edge Loop, Slide, Collapse, Merge to Center, Fill Hole, Spin, Crease, Soften/Harden, Cut UVs, Detach, Delete.
  - Face: Extrude, Extrude Offset, Bevel, Bridge, Poke, Wedge, Add Divisions, Triangulate, Quadrangulate, Merge to Center, Duplicate, Extract, Detach, Flip, Planar UV, Delete.

## UV editing 

F12 in component mode (or UV > UV Editing Workspace) opens the UV Editing workspace. The UV Toolkit sits on the right of
the UV Editor, like Maya's:

| Section | Tools |
|---|---|
| Selection | Sync with viewport, UV / Edge / Face mode, Shell, Grow, Shrink, Invert, Overlapping |
| Pin | Pin, Unpin |
| Transform | Flip U/V, Rotate 90, Align U/V, Straighten, Snap Together |
| Create | Automatic, Planar, Cylindrical, Spherical, Camera-Based, Cube |
| Cut and Sew | Cut, Sew, Split, Merge, Auto Seams |
| Unfold | Unfold, Optimize, Layout, Orient Shells, Match Texel Scale |
| Display | Checker map (toggle), Distortion, Shaded UVs |

Typical flow, as in Maya: select edges, **Cut** (Shift+RMB in the UV Editor), select the shells, **Unfold**, then **Layout**.
In the UV Editor: RMB switches UV / Edge / Face / Shell, Shift+RMB has Cut, Sew, Unfold, Layout, Straighten, Orient,
Optimize, Automatic. F9-F11 change mode, Z undoes, Alt+MMB/RMB pan and zoom.

Difference from Maya: Blender stores cuts as seams, and shells split when you Unfold. Maya splits them as soon as you cut.

## Terms used

Attribute Editor = Properties editor · Shader Editor = shader node editor (Shading workspace) · Construction history =
modifiers ("INPUTS" in the Channel Box) · Freeze Transformations = Apply Transforms · Group node = Empty ·
Display layers = Collections (Layer Editor) · Blender is Z-up (Maya is Y-up); units are metres.

## Known differences

- Dock tabs are icons with tooltips, not vertical text labels.
- Target Weld merges at the last-selected vertex instead of dragging one vertex onto another.
- Shift+drag on the manipulator extrudes along the grabbed arrow or plane; dragging the centre extrudes along normals.
- Blender's Item / Tool / View tabs still exist in the viewport sidebar (closed at startup; Ctrl+] or Display > UI Elements > Sidebar opens it).

## Command line (MEL and Python)

The command line at the bottom of Classic speaks MEL, like Maya's:
`polyCube -w 2 -n box; move -r 0 0 1; setAttr box.rotateZ 45; select -cl;`.
Windows > Command Line: Python switches to Python, where `cmds` is ready (`cmds.polyCube(w=2)`), and scripts can
`import m3d.cmds as cmds`. Supported commands: polyCube/Sphere/Cylinder/Cone/Plane/Torus, polySmooth, spaceLocator,
group, parent, duplicate, delete, select, ls, move, rotate, scale, xform, setAttr, getAttr, rename, objExists, hide,
showHidden, makeIdentity, currentTime, playbackOptions, setKeyframe, file, undo, redo. Blender is Z-up, so a cube's
"height" runs along Z.

## Build

```
git -c submodule."lib/windows_x64".update=checkout submodule update --init --depth 1 lib/windows_x64
make.bat 2026 builddir <build-dir>
blender -b --factory-startup --python-exit-code 1 --python tools/m3d/test_m3d.py
blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result-file>
blender -b --factory-startup --python tools/m3d/shortcuts_doc.py -- SHORTCUTS.md
python tools/m3d/demo/record.py <blender.exe> [scenario ...]    # README videos -> docs/media (keep off the PC)
tools\m3d\regen_theme.sh <blender.exe>     # after editing tools/m3d/theme.py
set BLENDER_USER_RESOURCES=<empty dir> && blender --factory-startup --python tools/m3d/build_startup.py -- release/datafiles/startup.blend
```
