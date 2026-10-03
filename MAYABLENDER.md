# MayaBlender

Fork of Blender 5.2.2 LTS (git branch `maya`) that looks and behaves like Autodesk Maya.
Run `dist\blender.exe`. Everything Maya-like is on by default; there is nothing to configure.

- Full list of changed shortcuts: [MAYABLENDER_SHORTCUTS.md](MAYABLENDER_SHORTCUTS.md) (generated from the keymap).
- Self-checks: `tools/maya/test_maya.py` (background) and `tools/maya/gui_test.py` (real window, simulated input).

## Change log

| Commit | Round | What changed |
|---|---|---|
| `5876761b` | 1. Look and controls | Maya keymap as default, Maya theme (C default theme), empty startup scene, 35 mm lens, right-click marking menus, Channel Box, polygon shelf, smooth preview (1/2/3), Group (Ctrl+G), window title. |
| `38e1f7bc` | 2. Interface | Maya menu bar with menu sets, status line, Workspace selector, shelf tabs, viewport panel menus, Maya Classic layout (startup.blend), Maya workspace names, Maya editor names. |
| `30a49507` | 3. Dock (first try) | Channel Box / Attribute Editor / Modeling Toolkit as viewport sidebar tabs (replaced in round 4). |
| `919428c5` | 4. Right-hand dock | Properties editor became Maya's right-hand dock (new Channel Box / Layer Editor and Modeling Toolkit tabs, tabs on the right edge, opens on Channel Box). Maya selection modifiers, Ctrl+E/Ctrl+B, Maya Delete, Ctrl+RMB convert menu, Shift+RMB create menu, X/C/V snapping, , . keys, pickwalk, > <. |
| (this round) | 5. Components, pivot, UVs | Right-click shows every tool for the selected component type, Shift+drag on the manipulator extrudes, D (hold) edits the pivot for objects and components, Space tap/hold = four view/hotbox, F2-F6 menu sets, Shift+D duplicate with transform, Ctrl+F9-F11 convert selection, Maya UV Editor workflow (UV Toolkit, UV marking menus, Cut/Sew/Unfold/Layout, checker map). |

## What changed vs. stock Blender

| Area | Change | Where |
|---|---|---|
| Keymap | Default keymap is **Maya** (Industry Compatible base + Maya overrides) | `scripts/presets/keyconfig/Maya.py`, `DNA_userdef_types.h` |
| Theme | Maya greys, `#5285a6` highlight, steel-blue to black viewport gradient, green lead / white selection, magenta verts, yellow/orange selected components, red playhead | `release/datafiles/userdef/userdef_default_theme.c` (from `tools/maya/maya_theme.py`) |
| Startup | Empty scene, 35 mm viewport lens, dock opens on Channel Box | `versioning_defaults.cc` |
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
| Shift+drag manipulator | Extrude the selected components along that axis |
| D (hold) / Insert | Edit pivot: objects move their origin; components move a custom pivot. Modify > Reset Pivot to go back |
| Space tap / hold | Four view / hotbox (every menu) |
| F2 / F3 / F4 / F5 / F6 | Menu set: Animation / Modeling / Rigging / FX / Rendering |
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
| Z, Shift+Z, G | Undo, redo, repeat last |
| Delete | Faces deleted; edges and vertices dissolved |
| Ctrl+E, Ctrl+B | Extrude, bevel |
| Ctrl+A | Channel Box / Attribute Editor |
| S, Shift+W/E/R | Set key, key translate/rotate/scale |
| , / . , Alt+, / Alt+. | Previous / next key, previous / next frame |
| Alt+V, Alt+Shift+V | Play / stop, go to start |
| = / - | Bigger / smaller manipulator |
| Ctrl+Space, Shift+M, Ctrl+Shift+M | Maximize panel, panel menu bar, shelf row |
| Ctrl+R | Create reference |

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

## Maya features to port next

Researched against [Autodesk's Maya hotkey list](https://download.autodesk.com/global/docs/maya2014/en_US/files/PC_Maya_Hotkeys.htm).
Ordered by how often a Maya user would notice them.

| Feature | Maya | Plan in MayaBlender | Needs rebuild |
|---|---|---|---|
| Tool marking menus | Q/W/E/R + LMB hold: selection mask, move/rotate/scale options | Pie menus with orientation, pivot, snapping per tool | No |
| Keyframe marking menu | Shift+S + LMB / MMB | Pie: set key, breakdown, tangents (interpolation) | No |
| View undo | [ / ] undo/redo view change | Store view matrices per viewport, step through them | No |
| Pickwalk left/right | Left/Right arrows walk siblings | Select next/previous sibling in hierarchy | No |
| Nudge | Alt+arrows move one pixel | Small translate in screen space | No |
| Last tool | Y repeats last non-QWER tool | Remember last tool id | No |
| Brush radius drag | B + drag (soft select / sculpt radius) | Modal radius drag for proportional size and brushes | No |
| Shift+H show selection | Show selected hidden objects | Reveal only selected in Outliner | No |
| Custom shelves | Ctrl+Shift+click menu item adds it to the shelf; shelf editor | User shelf stored in preferences | No |
| Hypershade browser | Material browser and node graph | Material grid panel + Shader Editor | No |
| Render Settings window | Window > Rendering Editors > Render Settings | Open the Render tab in a floating window | No |
| Set Project | scenes/, sourceimages/, images/ folders, relative paths | Create Maya project folders, set default paths | No |
| Command line MEL | `polyCube`, `move`, `select` | Translate common MEL commands to Python in the command line | No |
| Time slider / range slider | Maya range slider with playback start/end bar | Custom timeline header | No |
| Maya splash and icons | Maya-like splash | Replace splash image and app icon | Yes |
| Text dock tabs | Vertical text labels on the dock | Draw labels in the Properties tab bar | Yes |
| Y-up | Y-up world, centimetres | Scene unit scale is easy; true Y-up needs deep core changes | Yes (large) |

## Build

```
git -c submodule."lib/windows_x64".update=checkout submodule update --init --depth 1 lib/windows_x64
start "" /wait /belownormal /affinity F make.bat 2026 builddir <build-dir>
blender -b --factory-startup --python-exit-code 1 --python tools/maya/test_maya.py
blender --factory-startup --enable-event-simulate --python tools/maya/gui_test.py -- <result-file>
blender -b --factory-startup --python tools/maya/shortcuts_doc.py -- MAYABLENDER_SHORTCUTS.md
tools\maya\regen_theme.sh <blender.exe>     # after editing tools/maya/maya_theme.py
set BLENDER_USER_RESOURCES=<empty dir> && blender --factory-startup --python tools/maya/build_startup.py -- release/datafiles/startup.blend
```
