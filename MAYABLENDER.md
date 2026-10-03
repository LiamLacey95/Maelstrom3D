# MayaBlender

Fork of Blender 5.2.2 LTS (git branch `maya`) that looks and behaves like Autodesk Maya.
Run `dist\blender.exe`. Everything Maya-like is on by default; there is nothing to configure.

- Full list of changed shortcuts: [MAYABLENDER_SHORTCUTS.md](MAYABLENDER_SHORTCUTS.md) (generated from the keymap).
- Element-by-element comparison with Maya 2025 (interface, marking menus, every default hotkey): [MAYA_PARITY.md](MAYA_PARITY.md).
- Self-checks: `tools/maya/test_maya.py` (background) and `tools/maya/gui_test.py` (real window, simulated input).

## Change log

| Commit | Round | What changed |
|---|---|---|
| `5876761b` | 1. Look and controls | Maya keymap as default, Maya theme (C default theme), empty startup scene, Maya camera field of view, right-click marking menus, Channel Box, polygon shelf, smooth preview (1/2/3), Group (Ctrl+G), window title. |
| `38e1f7bc` | 2. Interface | Maya menu bar with menu sets, status line, Workspace selector, shelf tabs, viewport panel menus, Maya Classic layout (startup.blend), Maya workspace names, Maya editor names. |
| `30a49507` | 3. Dock (first try) | Channel Box / Attribute Editor / Modeling Toolkit as viewport sidebar tabs (replaced in round 4). |
| `919428c5` | 4. Right-hand dock | Properties editor became Maya's right-hand dock (new Channel Box / Layer Editor and Modeling Toolkit tabs, tabs on the right edge, opens on Channel Box). Maya selection modifiers, Ctrl+E/Ctrl+B, Maya Delete, Ctrl+RMB convert menu, Shift+RMB create menu, X/C/V snapping, , . keys, pickwalk, > <. |
| `9d4233db` | 5. Components, pivot, UVs | Right-click shows every tool for the selected component type, Shift+drag on the manipulator extrudes, D (hold) edits the pivot for objects and components, Space tap/hold = four view/hotbox, F2-F6 menu sets, Shift+D duplicate with transform, Ctrl+F9-F11 convert selection, Maya UV Editor workflow (UV Toolkit, UV marking menus, Cut/Sew/Unfold/Layout, checker map). |
| `eb2e734a` | 6. Maya parity pass | Researched Maya 2025's hotkey list, Status Line and marking menus. Fixed F2-F6 order, Maya Status Line (selection masks, symmetry, render settings, Hypershade, input box, sidebar buttons), panel toolbar, Quick Layout buttons, Channel Box locks, Layer Editor V/R, Maya Outliner, range-slider fps, Q/W/E/R/A/H/Shift+S + left click marking menus, context Shift+RMB, Ctrl+Shift+RMB transform menu, object RMB select/material items, Shift+drag duplicate (objects), Ctrl+Shift+drag slide, [ ] view undo, Alt+arrows nudge, pickwalk, Y, Ctrl+Y, Ctrl+T, Ctrl+X, Alt+B, Alt+1/2/4/5, B soft select radius, Ctrl+Shift+Q/X, Shift+{ }, F1, MEL command line + `maya.cmds`. |

## What changed vs. stock Blender

| Area | Change | Where |
|---|---|---|
| Keymap | Default keymap is **Maya** (Industry Compatible base + Maya overrides) | `scripts/presets/keyconfig/Maya.py`, `DNA_userdef_types.h` |
| Theme | Maya greys, `#5285a6` highlight, steel-blue to black viewport gradient, green lead / white selection, magenta verts, yellow/orange selected components, red playhead | `release/datafiles/userdef/userdef_default_theme.c` (from `tools/maya/maya_theme.py`) |
| Startup | Empty scene, Maya's default camera field of view (35 mm on a 36 mm film back), dock opens on Channel Box | `versioning_defaults.cc` |
| Layout | Maya Classic: Outliner left, Attribute Editor dock right, Time Slider and Command Line bottom. Workspaces: Maya Classic, Modeling - Standard, Sculpting, UV Editing, Rigging, Animation, Hypershade, Rendering, 3D Paint, Node Editor, Script Editor | `release/datafiles/startup.blend` (from `tools/maya/build_startup.py`) |
| Menu bar | Menu set dropdown (Modeling, Rigging, Animation, FX, Rendering), File/Edit/Create/Select/Modify/Display/Windows + menu-set menus + Help; status line; "Workspace:" dropdown | `scripts/startup/maya_ui.py`, `bl_ui/space_topbar.py` |
| Shelf | Shelf tabs (Curves/Surfaces, Poly Modeling, Sculpting, Rigging, Animation, Rendering, FX) in the viewport's second row | `maya_ui.py`, `bl_ui/space_view3d.py` |
| Viewport menus | View, Shading, Lighting, Show, Renderer, Panels (Blender's own menus under "...") | `maya_ui.py`, `bl_ui/space_view3d.py` |
| Right-hand dock | Tabs on the right edge: Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, then the Attribute Editor tabs (Object, Modifiers, Material, ...) | `space_buttons.cc`, `buttons_context.cc`, `DNA_space_enums.h`, `rna_space.cc`, `maya_mode.py` |
| Editor names | Attribute Editor, Hypershade, Script Editor, Command Line, Command History, Time Editor | `rna_space.cc`, `node_shader_tree.cc` |
| Marking menus | RMB, Shift+RMB, Ctrl+RMB in the viewport; RMB, Shift+RMB in the UV Editor; Space hotbox | `maya_mode.py`, `maya_uv.py` |
| UV editing | UV Toolkit, Cut/Sew/Unfold/Layout workflow, checker map | `scripts/startup/maya_uv.py` |
| Title | Window title says MayaBlender | `wm_window.cc` |

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

## UV editing (Maya workflow)

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

## Maya to Blender terms

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

The command line at the bottom of Maya Classic speaks MEL, like Maya's:
`polyCube -w 2 -n box; move -r 0 0 1; setAttr box.rotateZ 45; select -cl;`.
Windows > Command Line: Python switches to Python, where `cmds` is ready (`cmds.polyCube(w=2)`), and scripts can
`import maya.cmds as cmds`. Supported commands: polyCube/Sphere/Cylinder/Cone/Plane/Torus, polySmooth, spaceLocator,
group, parent, duplicate, delete, select, ls, move, rotate, scale, xform, setAttr, getAttr, rename, objExists, hide,
showHidden, makeIdentity, currentTime, playbackOptions, setKeyframe, file, undo, redo. Blender is Z-up, so a cube's
"height" runs along Z.

## Maya features to port next

See [MAYA_PARITY.md](MAYA_PARITY.md) for the full gap list. Top items: live creation history for primitives
(editable polyCube inputs), hotbox zones, the tangent marking menu and Graph Editor hotkeys, component pickwalk,
and (with a rebuild) a Maya splash and text labels on the dock tabs.

## Build

```
git -c submodule."lib/windows_x64".update=checkout submodule update --init --depth 1 lib/windows_x64
start "" /wait /belownormal /affinity F make.bat 2026 builddir <build-dir>
blender -b --factory-startup --python-exit-code 1 --python tools/maya/test_maya.py
blender --factory-startup --enable-event-simulate --python tools/maya/gui_test.py -- <result-file>
blender -b --factory-startup --python tools/maya/shortcuts_doc.py -- MAYABLENDER_SHORTCUTS.md
python tools/maya/demo/record.py <blender.exe> [scenario ...]    # README videos -> docs/media (keep off the PC)
tools\maya\regen_theme.sh <blender.exe>     # after editing tools/maya/maya_theme.py
set BLENDER_USER_RESOURCES=<empty dir> && blender --factory-startup --python tools/maya/build_startup.py -- release/datafiles/startup.blend
```
