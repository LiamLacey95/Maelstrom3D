# Maelstrom3D

Blender 5.2.2 LTS based 3D suite (git branch `maelstrom3d`) with a classic studio workflow: menu sets, Status
Line, shelves, Channel Box dock, marking menus, toolkits and a MEL command line.
Run `Maelstrom3D.exe` (or `blender.exe`). Everything is on by default; there is nothing to configure.

*Autodesk and Maya are registered trademarks of Autodesk, Inc. Maelstrom3D is not affiliated with Autodesk; Maya is
named here only to describe compatibility.*

- Full list of changed shortcuts: [SHORTCUTS.md](SHORTCUTS.md) (generated from the keymap).
- Element-by-element comparison with Maya 2025 (interface, marking menus, every default hotkey): [PARITY.md](PARITY.md).
- Self-checks: `tools/m3d/test_m3d.py` (background) and `tools/m3d/gui_test.py` (real window, simulated input).

## Change log

| Commit | Round | What changed |
|---|---|---|
| `36fb3c7f` | 1. Look and controls | Maya keymap as default, Maya theme (C default theme), empty startup scene, Maya camera field of view, right-click marking menus, Channel Box, polygon shelf, smooth preview (1/2/3), Group (Ctrl+G), window title. |
| `32ff0290` | 2. Interface | Maya menu bar with menu sets, status line, Workspace selector, shelf tabs, viewport panel menus, Classic layout (startup.blend), Maya workspace names, Maya editor names. |
| `bb68ffe4` | 3. Dock (first try) | Channel Box / Attribute Editor / Modeling Toolkit as viewport sidebar tabs (replaced in round 4). |
| `d7f8f7ed` | 4. Right-hand dock | Properties editor became Maya's right-hand dock (new Channel Box / Layer Editor and Modeling Toolkit tabs, tabs on the right edge, opens on Channel Box). Maya selection modifiers, Ctrl+E/Ctrl+B, Maya Delete, Ctrl+RMB convert menu, Shift+RMB create menu, X/C/V snapping, , . keys, pickwalk, > <. |
| `57eb61be` | 5. Components, pivot, UVs | Right-click shows every tool for the selected component type, Shift+drag on the manipulator extrudes, D (hold) edits the pivot for objects and components, Space tap/hold = four view/hotbox, F2-F6 menu sets, Shift+D duplicate with transform, Ctrl+F9-F11 convert selection, Maya UV Editor workflow (UV Toolkit, UV marking menus, Cut/Sew/Unfold/Layout, checker map). |
| `4f411d07` | 6. Maya parity pass | Researched Maya 2025's hotkey list, Status Line and marking menus. Fixed F2-F6 order, Maya Status Line (selection masks, symmetry, render settings, Hypershade, input box, sidebar buttons), panel toolbar, Quick Layout buttons, Channel Box locks, Layer Editor V/R, Maya Outliner, range-slider fps, Q/W/E/R/A/H/Shift+S + left click marking menus, context Shift+RMB, Ctrl+Shift+RMB transform menu, object RMB select/material items, Shift+drag duplicate (objects), Ctrl+Shift+drag slide, [ ] view undo, Alt+arrows nudge, pickwalk, Y, Ctrl+Y, Ctrl+T, Ctrl+X, Alt+B, Alt+1/2/4/5, B soft select radius, Ctrl+Shift+Q/X, Shift+{ }, F1, MEL command line + `maya.cmds`. |
| `61bf9b70`, `ed424595` | 7. Release | Tangent marking menu, Shift+H, Ctrl+Shift+H last hidden; Maya camera field of view (70 mm viewport lens); Target Weld fix; README videos (tools/m3d/demo); GitHub fork setup. |
| `30d2df4f` | 8a. Interface (Python) | Viewport header reduced to panel menus + panel toolbar (mode menu moved to the Status Line); camera-name and axis HUD; Attribute Editor node tabs; flat Outliner, default camera `persp`, empty-looking new scene; first-run preferences: solid toolbox/dock strips, no splash, no navigation buttons, Segoe UI. |
| `7f40fdef`, `d636fa48` | 8b. Interface (C) | Top bar is four stacked rows: menu bar, Status Line, shelf tabs, large shelf buttons (new top-bar regions in `screen_edit.cc` / `space_topbar.cc`); dock text tabs; near-square widgets; timeline controls below the slider; viewport tool header only in Sculpting / 3D Paint. |
| `7f40fdef` | 9. Rename to Maelstrom3D | Renamed from MayaBlender to avoid trademark issues: window title, keymap (`Maelstrom3D`), operators `m3d.*`, modules `m3d_*.py`, `m3d.cmds` (with a `maya.cmds` compatibility alias), workspaces Classic / Shading, Shader Editor, original app icon and splash (`tools/m3d/make_brand.py`), `Maelstrom3D.exe` launcher, repo and docs. |
| `73a8b5ea`, `5436c2a2`, `e1883f8c` | 9b. Fixes | Shift+drag on the X / Y arrow (or a plane handle) extruded or duplicated along Z: the axis now comes from the gizmo's world matrix. GUI test drags the X arrow and checks the axis. Options box (In-View Editor): Modeling Toolkit and right-click component tools apply on the click (Bevel 25%, Inset 0.1, Extrude 0 the first time) and open Blender's Adjust Last Operation panel expanded beside the click, or beside the selection when clicked in the dock (`m3d.tool`, `interface_region_hud.cc`). Shortcuts, Shift+drag and menu commands no longer show the panel at all; Connect gained Divisions / Smoothness. UV checker material renamed `m3dUVChecker`. |
| `329cf6e4` | 10. Installer, portable | Own settings folders, apart from Blender's: `%APPDATA%\Maelstrom3D.2` and `%LOCALAPPDATA%\Maelstrom3D\Cache` (`GHOST_SystemPathsWin32.cc`, `appdir.cc`). Windows installer from `tools/m3d/installer/maelstrom3d.iss` (Inno Setup: per-user, Start menu, optional desktop shortcut, uninstaller) and a portable zip whose `portable` folder holds the settings. |

## What changed vs. stock Blender

| Area | Change | Where |
|---|---|---|
| Keymap | Default keymap is **Maya** (Industry Compatible base + Maya overrides) | `scripts/presets/keyconfig/Maelstrom3D.py`, `DNA_userdef_types.h` |
| Theme | Maya greys, `#5285a6` highlight, steel-blue to black viewport gradient, green lead / white selection, magenta verts, yellow/orange selected components, red playhead | `release/datafiles/userdef/userdef_default_theme.c` (from `tools/m3d/theme.py`) |
| Startup | Empty scene (camera `persp` and light hidden), Maya's default camera field of view (35 mm on a 36 mm film back), dock opens on Channel Box, no splash, solid toolbox/dock strips, Segoe UI font | `versioning_defaults.cc`, `m3d_mode.py` (factory startup / preferences handlers) |
| Layout | Classic: Outliner left, Attribute Editor dock right, Time Slider and Command Line bottom. Workspaces: Classic, Modeling - Standard, Sculpting, UV Editing, Rigging, Animation, Hypershade, Rendering, 3D Paint, Node Editor, Script Editor | `release/datafiles/startup.blend` (from `tools/m3d/build_startup.py`) |
| Top rows | Four stacked rows like Maya: menu bar (menu set dropdown + File/Edit/Create/Select/Modify/Display/Windows + menu-set menus + Help), Status Line (with "Workspace:"), shelf tabs, shelf buttons | `screen_edit.cc`, `space_topbar.cc` (extra top-bar rows), `m3d_ui.py`, `bl_ui/space_topbar.py` |
| Shelf | Shelf tabs (Curves/Surfaces, Poly Modeling, Sculpting, Rigging, Animation, Rendering, FX) and large buttons in the top rows | `m3d_ui.py` |
| Viewport | Panel menus (View, Shading, Lighting, Show, Renderer, Panels) and panel toolbar only (Blender's menus under "..."), Maya HUD (camera name, axis triad) | `m3d_ui.py`, `m3d_hud.py`, `bl_ui/space_view3d.py` |
| Right-hand dock | Tabs on the right edge: Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, then the Attribute Editor tabs (Object, Modifiers, Material, ...) | `space_buttons.cc`, `buttons_context.cc`, `DNA_space_enums.h`, `rna_space.cc`, `m3d_mode.py` |
| Editor names | Attribute Editor, Hypershade, Script Editor, Command Line, Command History, Time Editor | `rna_space.cc`, `node_shader_tree.cc` |
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

Attribute Editor = Properties editor · Hypershade = Shader Editor / Hypershade workspace · Construction history =
modifiers ("INPUTS" in the Channel Box) · Freeze Transformations = Apply Transforms · Group node = Empty ·
Display layers = Collections (Layer Editor) · Blender is Z-up (Maya is Y-up); units are metres.

## Known differences

- Dock tabs are icons with tooltips, not vertical text labels.
- Target Weld merges at the last-selected vertex instead of dragging one vertex onto another.
- Shift+drag on the manipulator extrudes along the grabbed arrow or plane; dragging the centre extrudes along normals.
- Blender's Item / Tool / View tabs still exist in the viewport sidebar (closed at startup; Ctrl+] or Display > UI Elements > Sidebar opens it).
- The splash screen is still Blender-branded.

## Command line (MEL and Python)

The command line at the bottom of Classic speaks MEL, like Maya's:
`polyCube -w 2 -n box; move -r 0 0 1; setAttr box.rotateZ 45; select -cl;`.
Windows > Command Line: Python switches to Python, where `cmds` is ready (`cmds.polyCube(w=2)`), and scripts can
`import m3d.cmds as cmds`. Supported commands: polyCube/Sphere/Cylinder/Cone/Plane/Torus, polySmooth, spaceLocator,
group, parent, duplicate, delete, select, ls, move, rotate, scale, xform, setAttr, getAttr, rename, objExists, hide,
showHidden, makeIdentity, currentTime, playbackOptions, setKeyframe, file, undo, redo. Blender is Z-up, so a cube's
"height" runs along Z.

## Maya features to port next

See [PARITY.md](PARITY.md) for the full gap list. Top items: live creation history for primitives
(editable polyCube inputs), hotbox zones, the tangent marking menu and Graph Editor hotkeys, component pickwalk,
and (with a rebuild) a Maya splash and text labels on the dock tabs.

## Build

```
git -c submodule."lib/windows_x64".update=checkout submodule update --init --depth 1 lib/windows_x64
start "" /wait /belownormal /affinity F make.bat 2026 builddir <build-dir>
blender -b --factory-startup --python-exit-code 1 --python tools/m3d/test_m3d.py
blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result-file>
blender -b --factory-startup --python tools/m3d/shortcuts_doc.py -- SHORTCUTS.md
python tools/m3d/demo/record.py <blender.exe> [scenario ...]    # README videos -> docs/media (keep off the PC)
tools\m3d\regen_theme.sh <blender.exe>     # after editing tools/m3d/theme.py
set BLENDER_USER_RESOURCES=<empty dir> && blender --factory-startup --python tools/m3d/build_startup.py -- release/datafiles/startup.blend
```
