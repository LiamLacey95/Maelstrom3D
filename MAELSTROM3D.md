# Maelstrom3D

Blender 5.2.2 LTS based 3D suite (git branch `maelstrom3d`) with a classic studio workflow: menu sets, Status
Line, shelves, Channel Box dock, marking menus, toolkits and a MEL command line.
Run `Maelstrom3D.exe` (or `blender.exe`). Everything is on by default; there is nothing to configure.

*Autodesk and Maya are registered trademarks of Autodesk, Inc. Maelstrom3D is not affiliated with Autodesk; Maya is
named here only to describe compatibility.*

- The keys by task and every changed shortcut: [SHORTCUTS.md](SHORTCUTS.md) (generated from the keymap; in the app: Help >
  Keyboard Shortcuts). Coming from Blender? See [If you know Blender](#if-you-know-blender).
- Self-checks: `tools/m3d/test_m3d.py` (background) and `tools/m3d/gui_test.py` (real window, simulated input).

## What changed vs. stock Blender

| Area | Change | Where |
|---|---|---|
| Keymap | Default keymap is **Maelstrom3D** (Blender's Industry Compatible keymap plus classic studio-style overrides) | `scripts/presets/keyconfig/Maelstrom3D.py`, `DNA_userdef_types.h` |
| Theme | Mid greys, `#5285a6` highlight, steel-blue to black viewport gradient, green lead / white selection, magenta verts, yellow/orange selected components, red playhead. Theme presets (Quick Setup, Preferences > Themes): **Maelstrom3D** (the default), **Maelstrom3D High Contrast** (brighter text, stronger widget outlines, thicker object outlines and edges, brighter selection), **Blender Light (Original)** (Blender's own light theme). **UI Size** (the interface scale) is in the Quick Setup and in Display > UI Elements | `release/datafiles/userdef/userdef_default_theme.c` (from `tools/m3d/theme.py`), `scripts/presets/interface_theme/` |
| Startup | Empty scene (camera `persp` and light hidden; the viewport says where to start: "Create > Polygon Primitives or the shelf · F1-F7 tasks · hold Space for every menu"), a 35 mm-equivalent default camera field of view, dock opens on Channel Box, solid toolbox/dock strips, Segoe UI font. **Splash** (at startup until you untick **Show this at startup**; again from Help > Getting Started): New Scene, Open Scene, Recover Last Session, Recent Files, the keys to get started (F1-F7 task workspaces, Alt+LMB / MMB / RMB tumble / track / dolly, Space hold hotbox, RMB hold marking menu, Tab search), the guide, Keyboard Shortcuts, What's New, Report a Bug. The first run shows **Quick Setup** instead: UI Size, Theme, Import Settings From the previous version, Continue | `versioning_defaults.cc`, `m3d_mode.py` (factory startup / preferences handlers), `m3d_welcome.py`, `m3d_hud.py`, `bl_operators/wm.py` |
| Layout | Modeling: Outliner left, Attribute Editor dock right, Time Slider and Command Line bottom. Workspaces (F1-F7 are the first seven): Modeling, Sculpt, UV, Texture, Rigging, Animation, Rendering, Shading, Compositing, Node Editor, Script Editor | `release/datafiles/startup.blend` (from `tools/m3d/build_startup.py`) |
| Top rows | Four stacked rows: menu bar (the **Menus** dropdown: the menu set, + File/Edit/Create/Select/Modify/Display/Windows + menu-set menus + Help), Status Line (with "Workspace:"), shelf tabs, shelf buttons. The Status Line is the same in every workspace: New / Open / Save first, then groups of buttons with a small gap between them, the workspace picker at the right end. On a narrow window (1366 px) long rows give way to icons with tooltips or a menu (Rigging's bone display, Animation's modes, Auto Key, interpolation, Graph / Dope Sheet and Playblast) and the picker drops its "Workspace:" label, so nothing is cut off | `screen_edit.cc`, `space_topbar.cc` (extra top-bar rows), `m3d_ui.py`, `bl_ui/space_topbar.py` |
| Shelf | Shelf tabs (Curves/Surfaces, Poly Modeling, Sculpting, Rigging, Animation, Rendering, FX, UV, Custom) and large buttons in the top rows; every workspace has a Custom tab (right-click any button, Add to Shelf). One look on every shelf: tall buttons as wide as their content, left-aligned, groups apart; the long Modeling shelves are icons (the tooltip names the command), the task shelves (UV, Rigging, Animation, Rendering) icon and a short label | `m3d_ui.py`, `m3d_user.py` |
| Workspace Settings | The **gear** button next to the workspace picker in the Status Line (top right, same in every workspace; its tooltip says Workspace settings): Reset Workspace (back to its factory layout, asks first), show / hide each dock tab of the workspace (also in the dock's own tab menu), **Show Shelf** (the shelf tabs and shelf rows of the top bar, per workspace: on everywhere except Sculpt and Texture; when off the top bar is two rows and the viewport grows), **Click to Edit** (see Customising the interface), Reset Dock Layout, the workspace's entry mode, **Bake on GPU** (Texture workspace: see Bake) with the device it found, Keyboard Shortcuts (Preferences > Keymap), **Save Layouts as Default** (asks first; saves every workspace's layout, and the open scene, as the startup file for new files; also in File > Defaults) **F2-F6 Change Menus Only** (off by default: F2-F6 then change the menu set alone, F2 Modeling, F3 Rigging, F4 Animation, F5 FX, F6 Rendering, like the classic menu-set keys; F1, F7 and the picker still switch workspaces) and **Delete Workspace** (asks first; a deleted task workspace comes back from its factory layout with its F-key, "Restored Sculpt"). The workspace picker is a menu: the task workspaces show their F-key beside the name, then the others, then New Workspace; it has no delete button. The first time each F-key switches workspace the status bar says what it did. Windows > Workspaces is the same menu. Extra workspaces (Shading, Compositing...) show what applies | `m3d_workspace.py` (`M3D_PT_workspace_settings`), `m3d_ui.py` (`draw_workspace_picker`) |
| Viewport | Panel menus (View, Shading, Lighting, Show, Renderer, Panels) and panel toolbar first in every mode, Blender's own menus of the mode in the one **Blender Menus** button (☰) after them (none in Sculpt and Texture, whose menus are in the menu bar); other modes (Pose, Weight Paint, Edit of a curve or armature) add their mode dropdown and transform settings after the toolbar; viewport HUD (camera name, axis triad). A narrow view's header gives way in steps so nothing overlaps: the menus become one menu button, then the toolbar keeps only the shading buttons, then goes (all of it is in the menus) | `m3d_ui.py`, `m3d_hud.py`, `bl_ui/space_view3d.py` |
| Right-hand dock | Tabs on the right edge: Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, then the Attribute Editor tabs (Object, Modifiers, Material, ...). **Primitive inputs:** a polygon primitive (shelf, Create menu, marking menus, `polyCube` ...) lists its size and subdivisions under INPUTS in the Channel Box ("Cube inputs": width / height / depth and the divisions along each, radius and axis / height / cap divisions, torus section radius ...); changing one rebuilds the mesh at once (one undo step). Editing the mesh (components, applied modifiers, sculpting, Freeze Transformations with a scale) **freezes** the inputs: they turn grey with the note "Mesh edited: inputs no longer apply". **Delete History** (button there, or Edit > Delete All History, which also applies modifiers) clears them. Duplicates keep their own inputs. A rebuild resets UVs, face materials to the first slot (slots are kept) and keeps Shade Smooth. **Layer Editor** (under the Channel Box): a row per layer (collection) with V (visible) and R (not selectable), the name, its object count and a menu (also on right-click): **Add Selected Objects**, **Remove Selected Objects**, **Select Objects**, **Rename Layer**, **Delete Layer** (its objects and layers stay, one level up); layers inside layers are indented under them | `space_buttons.cc`, `buttons_context.cc`, `DNA_space_enums.h`, `rna_space.cc`, `m3d_mode.py`, `m3d_inputs.py` |
| Editor names | Attribute Editor, Shader Editor, Script Editor, Command Line, Command History, Time Editor | `rna_space.cc`, `node_shader_tree.cc` |
| Marking menus | RMB, Shift+RMB, Ctrl+RMB in the viewport; RMB, Shift+RMB in the UV Editor; Space hotbox | `m3d_mode.py`, `m3d_uv.py` |
| Status bar (bottom) | The keys of the workspace and mode, read from the keymap (so they follow your own keys): in Object and Edit Mode LMB Select, Shift Toggle, Ctrl Deselect, Alt+LMB / MMB / RMB Tumble / Track / Dolly, RMB Marking Menu, Space Hotbox, Tab Search; UV: the UV Editor's selection, UV Menu and UV Tools; Rigging Edit Mode: Extrude, Names, Menu; Weight Paint: Paint, Subtract, Smooth, Size, Weight, Sample; Pose Mode: Set Key, Tween, Play; Rendering: Render, Render View; Sculpt and Texture: the keys of the brush (see there). While a tool or gesture runs, the bar shows that tool's keys instead. In the middle: the command line's last result or error, and a short note when one of Maelstrom3D's panels hits an error ("Something went wrong in m3d_texture.py: Help > Report a Bug"). At the right end: **New alpha m3d.N** (a link to its release notes) when Check for Updates found a newer alpha, the version, "Maelstrom3D alpha m3d.5 (Blender 5.2.2)" | `m3d_ui.py` (`draw_status_hints`), `m3d_help.py`, `bl_ui/space_statusbar.py` |
| File menu | New / Open / Recent, Save, Increment and Save, **Save Copy for Sharing...** (see Sharing files), **Revert** (a saved file: back to its saved state), **Recover** > Last Session / Auto Save..., **Set Project... / New Project... / Recent Projects**, **Import...** (one picker for every format), Import from Scene File (.blend)..., **Create Reference...**, Import Other Formats, **Export to Engine...** / Repeat Last Export, Export Other Formats (see Pipeline below), **Defaults** > Save Layouts as Default, Load Factory Layouts, Reset Preferences, Reset Shelves & Docks, Reset Everything (each asks first; resets keep a copy: m3d_user.json.bak, startup.blend.bak), Export Settings... / Import Settings... (a zip of the settings folder: preferences, layouts for new files, shelves, docks, render presets; to move them between the installed and the portable Maelstrom3D or to another computer; importing keeps the settings it replaces in m3d_settings_backup.zip). After a session that ended unexpectedly (an auto save newer than the last quit) the next start asks once: **Recover Auto Save**. A damaged m3d_user.json is kept as m3d_user.json.bak before it is replaced. The first start of a new version folder (the next Blender base version) takes over the previous version's settings | `m3d_ui.py` (`M3D_MT_file`, `M3D_MT_file_defaults`), `m3d_help.py`, `m3d_user.py` |
| Help menu | **Maelstrom3D Guide** (this page), **Getting Started** (the splash), **Keyboard Shortcuts** (the keys by task, read from your keymap, and If You Know Blender; **Full List** opens SHORTCUTS.md), Hotkey Editor, **What's New in This Alpha** (the release notes), **Check for Updates** (asks GitHub for the newest alpha; only with Preferences > System > Allow Online Access on, which also lets Maelstrom3D look once a week by itself; only the list of releases is read, nothing is sent), **Report a Bug...** (opens a new GitHub issue in the browser with the version, OS, graphics card and the last lines of the log filled in; nothing is sent until you submit it), **Open Crash Log** (the newest crash log in the temp folder), **Open Log Folder** (the settings folder with m3d_log.txt: the Python errors of recent sessions, about 1 MB, the older part in m3d_log.old.txt), **About Maelstrom3D** (version, license, links), Blender Manual (reference) | `m3d_ui.py` (`M3D_MT_help`), `m3d_help.py`, `.github/ISSUE_TEMPLATE/bug.yml` |
| Errors | A command that can't run where it is clicked says why in plain words ("Bevel can't run here: it works on vertices, edges or faces..."). Bevel, Add Divisions, Merge, Flip, Conform, Average Vertices, Poke, Symmetrize and Quadrangulate clicked with a mesh in Object Mode switch to component mode with the whole mesh selected and run on all of it | `m3d_mode.py` (`run_tool`) |
| Docks | A dock shows its own tabs in its header; Blender's column of stock tabs beside it shows only with **All Settings** (the Attribute Editor in Modeling), in every task workspace. The Tool tab shows the active tool's settings (Blender's Workspace panel is in the 3D view's sidebar, Tool tab). A page or panel that cannot work yet shows one card in every workspace: a hint line saying why and the button that fixes it (Pose Mode, New Camera from View, Assign New Material, the scene's objects to pick...); controls that cannot work are hidden rather than greyed, lists are as tall as their items (an empty one says how to fill it), and on a narrow dock button grids take fewer columns so no label is cut off | `m3d_workspace.py` (`sync_nav_bar`), `bl_ui/properties_workspace.py` |
| UV editing | UV workspace (F3): dock tabs, Status Line and shelf for Cut/Sew/Unfold/Optimize/Layout, texel density, Auto Unwrap, UDIMs, checker map; sidebar UV Toolkit in other workspaces | `scripts/startup/m3d_uv.py` |
| Texturing | Texture workspace (F4): tool strip, Assets, Texture Set List, Layers, Properties and dock strip laid out like a dedicated painting tool, painting keys, context toolbar, display modes of the 3D and 2D views, texture sets with their channels, size and mesh maps, Bake Mesh Maps, Export Textures and New Texture Project dialogs; paint layer stack, painted images are saved or packed with the file; assets: plain and smart materials, smart masks, brushes, alphas, environments and your own items | `scripts/startup/m3d_texture.py`, `scripts/startup/m3d_layers.py`, `scripts/startup/m3d_masks.py`, `scripts/startup/m3d_library.py` (data: `m3d_library_data.py`; preview pictures: `tools/m3d/library_thumbs.py`), `scripts/startup/m3d_bakegroups.py` (bake groups), `scripts/startup/m3d_bakeq.py` (the bake queue, the guard and the device), `scripts/startup/m3d_bakeview.py` (the view of Bake Mesh Maps), `scripts/startup/m3d_texset.py` (texture set settings, Export Textures dialog, New Texture Project) |
| Rigging | Rigging workspace (F5): Outliner with the bone hierarchy and bone collections on the left, a large viewport, a dock of Channel Box, Skeleton, Controls & Constraints, Skin, Drive, Test and Collections tabs that follows the mode, a Time Slider (the Drivers editor opens over it); Joint tool (name lists, numbered names), Orient Joint, Mirror and Rename Chain, control shapes, constraints that keep their offset, IK with pole, Pole Vector, Rotate Order, bind with fallback, weight tools that keep weights adding up to 1, Driven Key, Check Rig, range-of-motion test, naming check, Rigify on demand; Ctrl+E, Shift+N | `scripts/startup/m3d_rig.py` |
| Animation | Animation workspace (F6): a large viewport and a camera view, one bottom editor that switches between the Graph Editor and the Dope Sheet, a short Timeline, a dock of Channel Box, Pick, Tween & Poses, Motion, Layers and Playback tabs; Status Line with Auto Key, key type, new key interpolation, Key: Selected / Character, keying set, range, frame rate, loop mode, Blocking / Polish, Playblast; one Set Key rule (unlocked channels and custom properties), Tween (Alt+Q), Push / Relax / Breakdown, Mirror Pose / Animation, world position, object selection sets, rig controls, motion paths, ghost curves, NLA layers with weights, Playblast movie | `scripts/startup/m3d_anim.py` |
| Rendering | Rendering workspace (F7): a 3D view and a Render View, a dock of Camera, Lighting, Materials, Render, Output, Passes & Layers and Advanced tabs; Status Line with engine, camera, Draft / Medium / Final presets, Render, IPR; light table, HDRI sky, camera from view; Shift+F12 | `scripts/startup/m3d_render.py` |
| Pipeline | Projects (scenes, sourceimages, images, playblasts, export, cache), File > Import... for FBX / OBJ / glTF / USD / Alembic / .blend with studio units, Create Reference and the Reference Editor, Export to Engine (low polys, textures and animation for Unreal, Unity or glTF in one pass) | `scripts/startup/m3d_io.py` |
| Title | Window title says Maelstrom3D | `wm_window.cc` |
| Files from Blender | A file saved by stock Blender (none of its workspaces are Maelstrom3D's) opens with the seven task workspaces added beside its own and Modeling shown, "Opened with Maelstrom3D layouts (file layouts kept)": its Modeling, Sculpting, UV Editing, Animation and Rendering stay as "Modeling (Blender)" and so on, and F1-F7 work at once | `m3d_workspace.py` (`add_factory_workspaces`) |

## Everyday controls

| Key | Action |
|---|---|
| Alt+LMB / MMB / RMB | Tumble / Track / Dolly (RMB: drag right zooms in, left zooms out) |
| F / A (Shift: all views) | Frame selected / Frame all |
| Q W E R T | Select / Move / Rotate / Scale / Universal manipulator |
| Click, Shift, Ctrl, Ctrl+Shift | Select, toggle, deselect, add (click and drag) |
| Double-click, Shift / Ctrl + double-click (edges) | Edge loop; the edges between the edge selected before and this one along their ring or loop, selected / deselected (neighbours: the whole ring or loop) |
| RMB (hold) | Marking menu (see below) |
| Shift+RMB | Object mode: create primitives. Component mode: polygon tools |
| Ctrl+RMB | Convert selection (vertices, edges, faces, loop, ring, border, shell) |
| Shift+drag manipulator | Components: extrude, then move / scale / rotate along the grabbed handle. Objects: duplicate, then the same |
| Ctrl+Shift+drag manipulator | Slide components along their edges |
| Q / W / E / R / A / H (hold) + left click | Select / Move / Rotate / Scale / History / Menu set marking menus |
| Shift+S (hold) + left / middle click | Keyframe marking menu / tangents (Object and Pose Mode) |
| Ctrl+Shift+RMB | Transform options: symmetry, soft select, preserve UVs, tweak |
| B (tap / hold + drag) | Toggle soft select / set its radius |
| [ / ] | Undo / redo view change |
| Alt+arrows, arrows | Nudge one pixel, pickwalk (up/down hierarchy, left/right siblings) |
| Y, Ctrl+T | Last tool, universal manipulator |
| Ctrl+Shift+Q / X | Quad Draw / Multi-Cut |
| Shift+click, Shift+drag / Ctrl+click / drag (Quad Draw) | Add a point, edge or quad (drag from a point to extend it) / delete a point / move a point |
| Alt+B, Alt+1/2/4/5 | Cycle background, toggle curves / meshes / image planes / wireframe |
| Shift+{ / Shift+} | Previous / next workspace |
| D (hold) / Insert | Edit pivot: objects move their origin; components move a custom pivot. Modify > Reset Pivot to go back |
| Space tap / hold | Four view / hotbox (every menu) |
| Tab | Search every menu (all menu sets, not only the menu bar's; also Edit > Search Every Menu) |
| F1 / F2 / F3 / F4 / F5 / F6 / F7 | Workspace (and its menu set): Modeling / Sculpt / UV / Texture / Rigging / Animation / Rendering. The Menus dropdown also offers FX; Workspace Settings > F2-F6 Change Menus Only makes F2-F6 change the menu set alone |
| F8, F9, F10, F11, F12 | Object/component toggle, Vertex, Edge, Face, UV workspace |
| Shift+F12 / Ctrl+Shift+F12 / Alt+F12 | Render the frame / the animation / show the last render |
| Ctrl+F9 / F10 / F11 | Convert selection to vertices / edges / faces |
| 1 / 2 / 3, Page Up / Down | Smooth preview off / cage / smooth, more / fewer divisions |
| 4 / 5 / 6 / 7 | Wireframe / Shaded / Textured / Lighting |
| Ctrl+D, Shift+D, Ctrl+Shift+D | Duplicate in place, duplicate with transform, duplicate as instance (Ctrl+D in Sculpt: the mesh being sculpted, which you then sculpt) |
| Ctrl+G, P, Shift+P | Group, parent, unparent |
| Ctrl+H, Alt+H, Ctrl+Shift+H | Hide selected, hide unselected, show hidden |
| Ctrl+1, Shift+L | Isolate select |
| X / C / V / J (hold) | Snap to grid / curve / point / increments |
| > / < | Grow / shrink selection |
| Up / Down | Pickwalk to parent / child |
| Z / Ctrl+Z, Shift+Z / Ctrl+Y, G | Undo, redo (in every editor: the Graph Editor and Dope Sheet's Zoom Region is on their View menu), repeat last |
| Delete | Faces deleted; edges and vertices dissolved |
| Ctrl+E, Ctrl+B | Extrude, bevel |
| Ctrl+A | Channel Box / Attribute Editor |
| S, Shift+W/E/R (or Ctrl+Shift+W/E/R) | Set key, key translate/rotate/scale (the unlocked channels; S also the custom properties). S over a Channel Box row keys that channel |
| , / . , Alt+, / Alt+. | Previous / next key, previous / next frame |
| Alt+V, Alt+Shift+V | Play / stop, go to start |
| = / - | Bigger / smaller manipulator |
| Ctrl+Space, Shift+M, Ctrl+Shift+M | Maximize panel, panel menu bar, shelf row |
| Ctrl+R, Ctrl+X | Create reference, cut |

### If you know Blender

| In Blender | Here |
|---|---|
| Tab: Edit Mode | F8: object / component (F9-F11: vertex, edge, face); Tab searches every menu |
| G / R / S: move / rotate / scale | W / E / R (tools with a manipulator); S sets a key |
| Space: play | Alt+V plays; Space: tap for four views, hold for the hotbox |
| Shift+A: add | The Create menu, the shelf or Shift+RMB |
| RMB: context menu | RMB (hold): marking menu |
| MMB: orbit | Alt+LMB tumble, Alt+MMB track, Alt+RMB dolly |
| F2: rename | The name field in the Status Line; F2 is Sculpt |
| F3: search | Tab; F3 is the UV workspace |
| Shift+D: duplicate | Ctrl+D in place, Shift+D with the last transform |
| H / Alt+H: hide / show | Ctrl+H / Ctrl+Shift+H |
| I: insert keyframe | S: set key |
| N: sidebar | Ctrl+A: Channel Box / Attribute Editor (the dock) |
| F12: render | Shift+F12 (F12 in component mode: the UV workspace) |

Undo works across workspace switches: a switch that changes the mode is one undo step named after the mode (Sculpt Mode,
Toggle Edit Mode...), so Ctrl+Z after F2 and a stroke takes back the stroke, then the switch's mode change.

## Right-click marking menu

- **Object mode:** Vertex, Edge, Face, Multi, Object Mode, Group, Assign New / Existing Material, Select All, More (Blender's object menu).
- **Component mode:** the same mode switches, plus a list underneath with every tool for what is selected:
  - Vertex: Extrude, Chamfer, Connect, Merge, Merge to Center, Target Weld, Average, Slide, Detach, Create Polygon, Delete.
  - Edge: Extrude, Bevel, Bridge, Connect, Insert Edge Loop, Offset Edge Loop, Slide, Collapse, Merge to Center, Fill Hole, Spin, Crease, Soften/Harden, Cut UVs, Detach, Delete.
  - Face: Extrude, Extrude Offset, Bevel, Bridge, Poke, Wedge, Add Divisions, Triangulate, Quadrangulate, Merge to Center, Duplicate, Extract, Detach, Flip, Planar UV, Delete; Assign New / Existing Material.

**Assign New / Existing Material** (marking menu, Lighting/Shading menu, Rendering shelf). In Edit Mode it goes on the selected
faces only: the slot that has the material is used, else one is added, and the other faces keep theirs (a mesh without any
material gets an empty first slot, so the rest keeps its look). In Object Mode it replaces the material of each selected object's
active slot; an object with several materials asks first: **Active Slot** or **All Materials**. The list of existing materials
leaves out Maelstrom3D's own (UV checker, bake views).

## UV editing (F3)

F3, or F12 in component mode (or UV > UV Workspace), opens the UV workspace in Edit Mode: the UV Editor large on the left,
the 3D view (Solid, seams shown) on the right, and the dock with the UV tools. Names are Blender's own.

| Part | Contents |
|---|---|
| Status Line | Object / Edit Mode, UV Sync, select mode (Vertex / Edge / Face) and Shell select, Live Unwrap, Distortion (and its type), Checker, texture size |
| Shelf | Cut, Sew, Unfold, Optimize, Layout (large buttons), Auto Unwrap, Custom |
| Unwrap tab | Cut and Sew (Cut, Sew, Split, Merge, Seams from Shells), Unfold (Angle Based or Conformal, Fill Holes), Optimize (iterations), Layout (margin in pixels of the texture size, rotation: none / 90 degrees / axis aligned / any), Pin (Pin, Unpin, Invert Pins, Select Pinned) |
| Arrange tab | Select (Shell, Grow, Shrink, Invert, Overlapping, Pinned), Transform (Flip U/V, Rotate 90, Align U/V, Straighten, Snap Together), Shells (Orient Shells, Match Scale) |
| Check tab | Checker map, Distortion (angle or area), Shaded UVs, Texel Density: texture size, target, **Read**, **Set**, **Match** |
| Create tab | Auto Unwrap (seam angle, margin in pixels), projections: Automatic, Planar, Cylindrical, Spherical, Camera-Based, Cube |
| UDIM tab | The UV Editor's image (New / New UDIM Image), tile list with Add, Remove, Fill, tile grid, Pack to Active / Closest Tile, Select Tile |

Typical flow: **Cut** the edges you want as seams, **Unfold**, **Optimize** if shells stretch (it is slow on dense
meshes, so it has its own button), **Layout**, then check Distortion and the Checker map and match the Texel Density.
**Auto Unwrap** does cut (at edges sharper than the seam angle), unfold and layout in one go; a smooth shape with no
sharp edge is projected instead. Buttons in the dock and shelf run in the UV Editor, so they work on the UV selection.
UV Sync (Alt+S) makes the UV Editor follow the 3D view's selection; with it off, only what is selected in the UV Editor
is used. Texel density is pixels per unit at the texture size in the Status Line (**Same as Set** by default: the size of the active mesh's
texture set, shown as "1024 px (Set)"; 2048 while it has none), and the Layout and Auto Unwrap margin is in pixels of that size: Read measures the selected shells
(nothing selected: the whole mesh), Set scales every selected shell about its centre to the target, Match scales
them to the shell of the active face.

Keys in the UV Editor: Alt+P Layout, Ctrl+Shift+U Unfold, Alt+C Checker, Shift+T Set texel density, Alt+S UV Sync.
RMB switches UV / Edge / Face / Shell, Shift+RMB has Cut, Sew, Unfold, Layout, Straighten, Orient, Optimize, Automatic.
F9-F11 change mode, Z undoes, Alt+MMB/RMB pan and zoom. The checker map is taken off before a file is saved (and put
back afterwards), so scene files never keep it.

A UV Editor opened in another workspace (Windows > UV Editor) keeps the old sidebar UV Toolkit with the same tools.
Difference from Maya: Blender stores cuts as seams, and shells split when you Unfold. Maya splits them as soon as you cut.

## Sculpt (F2)

F2 opens the Sculpt workspace and enters Sculpt Mode on the active mesh. With no mesh to sculpt the dock shows one start
card (Sphere, Cube, Plane, Import..., **Use a mesh from F1 Modeling**, and the meshes of the scene to pick), the tray stays
empty and the tabs show once there is a mesh. The **Sphere** is made of even quads (a divided cube pushed out to a sphere:
6,144 faces, no poles where a UV sphere pinches). A game mesh without a high poly (a low poly, or a painted mesh without a
role) opens in Object Mode, and the tray asks: **This is a game mesh**: **Create High Poly** (sculpt a copy, bake onto the
game mesh) or **Sculpt this mesh**. A workspace switch that takes a moment (the first Texture or Rendering of the session,
or a mode on a mesh of more than 500,000 faces) shows the wait cursor and "Opening Sculpt..." in the status bar. The viewport has no tool settings row: the Status Line, the tray and the tabs
have its controls, and the toolbar beside the viewport has only the tools the tray does not (masking, hiding, face set,
trim, filter, transform and annotate tools; the brushes are the tray's tiles).

| Part | Contents |
|---|---|
| Brush tray (left) | Open panels, essentials first: **Brushes**: the active brush on one line (click it for every brush of the library, the arrow for its menu: save, revert, duplicate...) and a grid of 15 small brush tiles showing each brush's thumbnail (the tooltip is the name and, for the seven that have one, the key Shift+1-7; the active brush is highlighted: Draw, Clay Strips, Clay, Smooth, Grab, Elastic Grab, Snake Hook, Inflate/Deflate, Pinch/Magnify, Crease Sharp, Flatten/Contrast, Scrape/Fill, Layer, Mask, Face Set Paint); **Size and Strength** (Size, Strength, Hardness, then **Add** | **Subtract**: icons with tooltips on a narrow tray); **Lazy Mouse** (toggle; **Distance** and **Smoothing** while it is on: Blender's Stabilize Stroke); **Stroke Type** (a tile with a little picture for each of Dots, Drag Dot, Space, Airbrush, Anchored, Line, Curve); **Alpha** (the alpha's picture and name, or "No alpha: a round dab", **Load Alpha...**, then a tile for None, the eight starter alphas and every alpha you loaded). These are drawn by the same code as Texture's Properties - Paint (Brush, Alpha, Advanced), so both have the same order, labels and tiles. **More Brush Settings** (closed) holds the rest, one closed section each: Alpha Settings (mapping, size, angle), Brush Options, Falloff, Stroke Options, Cursor, Advanced, Custom Shelf (the Custom shelf; arrows to move / remove buttons while editing the interface) |
| Status Line | Object / Sculpt Mode; the brush controls (see below); the **Remesh** popover; face count (under 5,000 faces without Multires or Dynamic Detail it is a red **Too few faces: Add Detail** menu: Voxel Remesh to about 100k faces, or Subdivide with the face count it gives; over 2 million faces in Sculpt Mode a **Fast Navigation** button turns on Low Resolution While Navigating), **Create High Poly** / **Make Low Poly** / **Show Low Poly** (see High poly and low poly), Multires level with Lower / Higher arrows, Dynamic Detail, Mirror X/Y/Z (the only place for symmetry; a red **Off-centre: Center Pivot** when the mesh is not centred on its pivot along a mirror axis, so strokes would land beside the other side: it moves the pivot to the middle of the mesh), Auto-Masking, Mask and Face Set overlays, the **Matcap** popover; the gear at the right end is Workspace Settings |
| Top bar | Only the menu bar and the Status Line: the shelf rows (Sculpt / Remesh / Mask / Custom tabs and the brush buttons) are off in this workspace because the tray and tabs have all of it, and the viewport gets the space. Turn **Show Shelf** on in Workspace Settings to bring them back |
| Status bar (bottom) | The keys of the active brush, read from the keymap (so they follow your own keys): LMB Sculpt, Shift Smooth, Ctrl Mask, Ctrl+Alt Unmask, Ctrl+Shift Hide, S Size, U Strength, N Add / Subtract, D / Shift+D Level Up / Down (Multires), ` Sculpt Mesh Under Pointer, Shift+1-7 Brushes. While a tool or gesture runs, the bar shows that tool's keys instead |
| Geometry tab | Multires: **Subdivide (smooth)** and **Subdivide (keep shape)** with the face count of the level they add ("Subdivide (smooth) → 98k"), the level with Lower / Higher, **Display level** and **Sculpt level**, **Delete higher levels** (asks first, naming the levels it deletes), **Rebuild lower levels** (for a mesh that came in dense), **Apply base shape**; Subdivide (linear), the render level and Apply Multires under Advanced. Voxel Remesh: the **Detail** slider shows the face count the remesh gives ("~240k faces", estimated from the surface area and the voxel size) and the button; the voxel size, its eyedropper and the options are under Advanced. **Retopology**: the low poly of this sculpt as a new mesh paired with it (the sculpt stays): **Auto Low Poly**, **Draw Low Poly (Quad Draw)** and **Draw Low Poly, Symmetric (X)** (see Retopology); under Advanced, **Rebuild as Quads** rebuilds this mesh itself as even quads (target face count, ratio or edge length, symmetry, sharp edges, boundary, normals; a mesh over 300,000 faces is reduced first). **Dynamic Detail** (strokes add and remove faces as they go; its detail settings show while it is on). A block that cannot work on this mesh is one line saying why with the button that changes it: **Apply Multires** while the mesh has Multires levels, **Turn Off** while Dynamic Detail is on |
| Mask tab | A big **Invert Mask** button, Clear, Fill, the Ctrl gestures (Ctrl+drag mask, Ctrl+Alt+drag unmask; off the mesh Ctrl+drag clears and Ctrl+click inverts), **Show Mask** with the mask's **color** (black, the default, darkens the surface; any other color tints it) and **Opacity**; filters (Smooth, Sharpen, Grow, Shrink, Contrast), From Cavity / Boundary, Box / Lasso / Line / Polyline Mask, Mask by Color, Hide Masked / Show (with the Ctrl+Shift gestures listed) |
| Face Sets tab | **Make Face Sets** from [Loose Parts, Materials, Normals, UV Seams, Edge Creases, Sharp Edges, ...] with **Make**, Create from Mask / Visible / Selection, Grow, Shrink, Fair, Delete Geometry, Show All, Randomize Colors |
| Deform tab | Mesh filters (Smooth, Inflate, Relax, Surface Smooth, Sharpen, Enhance Details, Sphere, Random, Scale), Symmetrize (the merge distance under Advanced), Set Pivot, trim tools |
| Paint tab | Color brushes (they paint vertex colors; textures are painted in F4 Texture), color picker, palette, **Add Vertex Colors** when the mesh has none, color filters |
| Display tab | Matcap / studio light as a grid of thumbnails, color, cavity, Face Set and wireframe overlays (their opacity while they are on), **Turntable** (Create / Remove, Playblast, Render Animation: see Rendering), low resolution and delayed updates |
| Objects tab | Second in the tab row, so it stays in sight on a narrow dock. The scene's meshes with their face counts and a Low Poly / High Poly badge: show / hide, pick, solo, append a duplicate, delete; the active mesh's name is a field (click to rename it); **Show All** (when a mesh is hidden), **Merge Visible** (the shown meshes become the active one), **Split Loose Parts** and **Split Face Sets** (each part a mesh of its own); add a sphere, cube or cylinder |

On the Mask, Face Sets, Deform and Paint tabs, **Tool Settings** shows the settings of the active tool when it is one of
that tab's tools (a mask or hide shape, a trim, a filter, Face Set Edit...). The face count is the same everywhere: with
Multires it is the level being sculpted, and the viewport's statistics count the vertices of that level too.

**Status Line brush controls** (the top shelf of Sculpt): **Size**, **Strength** (the scene-wide sliders while Unified
Size / Strength is on), **Hardness** (how far from the centre the brush stays at full strength; the Falloff curve shapes
the rest), **Add / Subtract** (Brush.direction), **Lazy Mouse**
(toggle, and its Distance while it is on), and for a color brush the two colors and swap. The **Brush** popover has all of
them plus Lazy Mouse Distance and Smoothing, the stroke type tiles and the Falloff curve and shape. The **Remesh** popover has
Voxel Remesh (Detail, button, size and options under Advanced), Retopology (as on the Geometry tab), Multires (as on the
Geometry tab) and Dynamic Detail (switch, detail size and method). On a window wider than about 2200 px the Hardness slider, the Lazy Mouse toggle with its Distance, and Voxel
Remesh's Detail with a **Remesh** button sit in the Status Line itself (not while the mesh has Multires or Dynamic Detail is
on); on a narrower one (down to about 1500 px) only the sliders and the Add / Subtract buttons do and the popovers have the
rest. The **Matcap** popover is the thumbnail grid of the matcaps (Studio and Flat are the other lights), plus color and
cavity. There are no RGB / material-only toggles: in Blender a color brush paints color attributes and a normal brush
deforms, so the color brushes' two colors are what the Status Line shows.

**Ctrl is masking** (the Alt+mouse navigation is untouched; Ctrl no longer inverts a stroke). The gesture is decided
by what is under the cursor when you press and by whether you click or drag (more than the drag threshold):

| Input | On the mesh | Off the mesh (empty space) |
|---|---|---|
| Ctrl+drag | Paint mask (the Mask brush for this stroke, at the brush's size; your active brush stays) | Clear the mask |
| Ctrl+Alt+drag | Erase mask | Unmask a rectangle |
| Ctrl+click | Smooth (blur) the mask once | **Invert the mask** |
| Ctrl+Alt+click | Sharpen the mask | Nothing |
| Ctrl+Shift+drag | Hide everything outside a rectangle (show only inside) | Same |
| Ctrl+Shift+Alt+drag | Hide everything inside a rectangle | Same |
| Ctrl+Shift+click | Show only the face set under the cursor (hide the others) | Show all |
| Shift+drag, plain drag | Smooth, the brush stroke (as before) | |

To subtract, switch the brush to Subtract: the buttons in the tray and the Status Line, or **N** in the viewport (a
sticky toggle). Esc or right-click cancels a gesture. The other Ctrl keys are as before: Ctrl+I invert mask, Ctrl+Shift+A
fill mask, Ctrl+H hide masked, Ctrl+A mask pie, Ctrl+W face sets pie, Ctrl+0-5 Multires level (a level the mesh does not
have yet is added), Ctrl+D duplicate (as everywhere), Ctrl+R Voxel Remesh, D / Shift+D one Multires level up / down,
Ctrl+RMB stencil; H / Shift+H / Alt+H hide the face set, isolate / show it, show all. Alphas: Blender's essentials
brushes are linked asset data, which can only use linked textures, so every alpha lives in the **alpha library** (one
.blend with its thumbnail per alpha, in the user data folder `datafiles/m3d_alphas`); the starter set is made the first
time you pick one and Load Alpha... adds an image file (grey: white is full strength, mapped once onto the brush, clipped
at its edge). Blender 5.2 ships no image alphas of its own.

Tool buttons (mesh filters, trims, Grow / Shrink face set, color filters, Mask by Color) pick the tool: drag in the
viewport afterwards. Shift+1 ... Shift+7 pick Draw, Clay Strips, Smooth, Grab, Inflate/Deflate, Pinch/Magnify, Crease
Sharp. Expand stays on Shift+A (mask) and Shift+W (face sets) over the mesh.

**Heavy operations ask first.** Everything that can make millions of faces estimates the result before it runs (from the
face count, without reading the mesh): Ctrl+0-5 and Subdivide, Smooth Preview (key 3), Voxel Remesh (also with a tiny
voxel size typed under Advanced), Create High Poly and Rebuild as Quads. Over 5 million faces it asks ("... makes about
19M faces. That can take minutes and slow the viewport down"), over 50 million it refuses and says why. **Apply Multires**
on a lower level than the top asks too: "Keep level 2 of 5 (130k faces)? Levels 3-5 are lost", with **Use highest level**
(and its face count) to keep all the detail instead. Space (hold) lists the brushes first.
"All Settings" at the end of each tab row is Blender's stock Properties tabs (symmetry locks, radial symmetry, tiling,
gravity, the active tool's settings, ...); the column of stock tabs beside a dock shows only then. Files
saved with the earlier Sculpt layout keep their Outliner and tool settings row until Reset Workspace.

## High poly and low poly

A game model has two meshes: the **low poly**, the light mesh you unwrap, paint and export, and the **high poly**, a
detailed copy you sculpt and bake the detail from. Maelstrom3D keeps the two as a pair, and keeps a mesh of millions of
faces from slowing the other workspaces down.

- **Create High Poly** copies the selected mesh into `<name>_high` (a full copy; the original keeps its name) and pairs the two. The copy is the mesh as it shows, but
  without what only a game mesh needs (Triangulate, Weighted Normal and Subdivision modifiers are left out; a Mirror is applied, so both halves can be sculpted). A copy
  with a non-uniform scale gets it applied, since Sculpt Mode wants a uniform one; the original keeps its own. The options (the box that opens on the click, or Adjust
  Last Operation) are **Detail**: **Multires** (the default: **Levels**, 2 at first, each with 4 times the faces of the last, and **Keep Hard Edges**, on at first: edges
  marked sharp or folded more than 30° are creased, so the levels keep a box a box instead of rounding it), **Voxel Remesh** (voxel size) or None, and the face count of
  the new high poly. Under 100,000 faces it says the high poly is light for fine detail. It is on the Sculpt Status Line (on a game mesh), on the Objects tab of Sculpt,
  in the right-click menu in Object Mode and the **Mesh** menu of Modeling under **High / Low Poly**, in the **Bake** menu of Texture, and on the **Poly Modeling** shelf
  (with Auto-Pair by Name). If the mesh already has a high poly, you get that one selected instead of another.
- **Make Low Poly** is what the Sculpt Status Line offers instead on a sculpt that has no low poly yet (a mesh without a role of more than 50,000 faces or with Multires,
  or a high poly alone): Auto Low Poly or Draw Low Poly (see Retopology).
- **Roles and groups.** Every mesh has a role (None, Low, High) and a group name; meshes with the same group belong together. **Mark as High Poly**,
  **Mark as Low Poly**, **Clear Role** and **Pair Selected** (the active mesh is the low poly, the other selected meshes are its high poly) are in the same submenu. The group is the name
  without its suffix: `Sword_low` and `Sword_high` are group `Sword`. The suffixes `_low` / `_high`, `_lp` / `_hp`, `_lo` / `_hi` and `_lowpoly` / `_highpoly` are known, in any case, with or
  without Blender's `.001`. Words after the suffix make a part of the group: `Panel_high_bolts` belongs with `Panel_low`. The **Channel Box** shows the role and group of the active mesh
  ("Low Poly · Sword"; a mesh without a role shows no row) with a menu to change the role.
- **Auto-Pair by Name** (the same submenu, the Bake menu and the Bake tab) gives a role and a group to every mesh of the scene that has none and is named with one of the suffixes, and tells you what it
  paired and which meshes found no partner. `sword_HP` joins `Sword_LP` (case does not matter), a mesh joins a group that exists, and a mesh that already has a role is left alone. **Rename to Suffixes**
  (a menu of `_low / _high`, `_lp / _hp` and `_lo / _hi`, same places) renames the meshes of every group to one style, so that files exported to other tools find their pairs by name: floaters keep their
  words (`Panel_high_bolts` becomes `Panel_hp_bolts`), a name that is taken gets `_2`, and the baked maps of a renamed low poly keep up. **Make Pair** turns the old High Poly picker of the Bake tab into a pair (see Bake).
- **Sculpt shows the high poly.** F2 with the low poly or the high poly selected hides the low poly, shows the high poly (every part of the group) and starts Sculpt Mode on it (with several
  parts, the one you sculpted last). Leaving Sculpt (F1, F3 ... or the workspace picker) leaves Sculpt Mode, hides the high poly again and shows, selects and activates the low poly. The hiding
  happens in the same step as the switch, so the huge mesh is never drawn in the next workspace: switching away from Sculpt takes a few tens of milliseconds
  instead of a fifth of a second or more. **Show Low Poly** on the Sculpt Status Line draws the low poly as a wire, which cannot be selected, while you sculpt.
- **Only what Maelstrom3D hid is shown again.** A mesh you hid yourself stays hidden, a mesh without a role is never touched, and a high poly without a low poly (sculpting first, retopology later)
  is never hidden. Marking or pairing does not hide anything by itself: the high poly is hidden at the next switch of workspace.
- **Renders show each pair once.** A parked high poly is left out of renders as well (its render toggle is off while it is parked), so F12 does not render
  the high poly inside its low poly. **Render: Low Poly | High Poly** (Render tab of F7, shown when the scene has pairs) picks which one renders; the other is
  left out. A mesh whose render toggle you turned off yourself stays off, and a mesh that leaves its pair renders again. Bakes are not affected.
- **Multires outside Sculpt.** Leaving Sculpt lowers the display level of a Multires sculpt to the highest level under 500,000 faces, so F1 and F7 stay
  fast; entering Sculpt puts it back (the sculpt level and the render level are not touched).
- **Edit High Poly** (the submenu, on a low poly whose high poly is hidden) asks first ("Sword_high has 2,996,586 faces. Showing it takes a moment"), then shows, selects and activates the high poly. It stays shown
  until the next switch of workspace hides it again, or until **Park High Poly** (same submenu) does.
- **Face limit.** Entering Edit Mode (UV, F3) or Texture Paint Mode (Texture, F4) on a mesh of millions of faces takes seconds, and is rarely what you want. A mesh with more faces than the **Face Limit** (500,000; in
  Workspace Settings of the UV and Texture workspaces, 0 turns it off) opens in Object Mode there, and the dock and the Status Line say so ("High poly (2.1M faces): select the low poly to unwrap or paint").
  A high poly with a low poly opens the low poly instead. The Edit Mode and Texture Paint Mode buttons still enter the mode when you do want it.
- A file saved with a hidden high poly keeps it hidden, and opens the same way in any Blender: it is just a hidden object, with a role and a group stored on it.

### Retopology

Retopology builds the low poly from a high poly you already have, either by drawing it over the high poly or by letting Maelstrom3D make it. All of it is in the **High / Low Poly** submenu (right-click in Object Mode, Mesh menu of Modeling); Auto Low Poly and Draw Low Poly are also in Sculpt: **Make Low Poly** on the Status Line, the Retopology section of the Geometry tab and the Remesh popover, and the **Remesh** menu (with Rebuild as Quads, in place).

- **Make Live** turns the high poly of the selected mesh (or the mesh itself, when it has no role) into a **live surface**: new points snap onto it. A high poly Maelstrom3D hid asks first
  ("Sword_high has 2,996,586 faces. Showing it takes a moment"), then shows. It cannot be selected while it is live, so clicks go to the mesh you draw, and it stays shown when you switch workspace
  (a live surface is never hidden). Snapping turns on as Face Project (each point lands on the surface under the pointer), not onto the mesh you are drawing, and the retopology overlay turns on so the new
  mesh is drawn in front. The Modeling Status Line shows **Live: Sword_high** with a button that ends it. **Make Not Live** (the submenu or that button) gives back what you had: selection, how the surface
  was drawn, the snapping and the overlay; a high poly with a low poly is hidden again. Deleting the live surface does the same. A file saved while live opens live, with your own snapping still remembered.
- **New Low Poly (Quad Draw)** starts the drawing: it makes the surface live if it is not, adds an empty mesh `<group>_low` paired with it (a mesh without a role becomes the high poly of a group named after it), enters
  Edit Mode and picks the **Quad Draw** tool. **Shift+click** on the surface adds the first point. **Shift+drag** from a point adds the next point and an edge to it; from the middle point of two edges it adds a
  quad. A plain **drag** on a point moves it, **Ctrl+click** on a point deletes it. Points always land on the surface, also when you move them. The Modeling Toolkit says "Make Live first" under its tools until a surface is live.
  (Poly Build's own Ctrl+click is changed to Shift+click: with Ctrl held, a move snaps the other way round, which would leave the new point off the surface.)
  **New Low Poly, Symmetric (X)** (Draw Low Poly, Symmetric in Sculpt) does the same with a Mirror modifier on the new mesh: draw one half, the other follows (points on the
  middle stay there). **Conform to Surface** (the submenu, and under the Modeling Toolkit's tools while a surface is live) moves every point of the low poly onto the live
  surface (or its shown high poly) along its normal, for a low poly that was moved or edited off it.
- **Auto Low Poly** makes the low poly for you from a copy of the high poly: `<group>_low`, paired with it, with the high poly untouched. **Method**: **Auto Retopology** (quads) or **Decimate** (triangles), **Faces**
  (2,000 by default; the result is about that many), **Symmetry (X)** (on at first when the high poly's Mirror X is on: the low poly is the same on both sides), and for Auto Retopology **Preserve Sharp** and **Preserve Boundary**. A high poly over 300,000 faces is voxel remeshed to about that first (decimated instead with Preserve
  Boundary, since a voxel remesh closes open borders), since Auto Retopology on millions of faces takes very long. A Multires high poly is copied as it shows in the viewport. Auto Retopology needs a closed mesh without loose edges or flipped faces; when it cannot remesh, nothing is
  added and the message suggests Voxel Remesh on the high poly first, or Decimate. The new low poly has no UVs: unwrap it in the UV workspace (F3).

## Texture (F4)

F4 opens the Texture workspace and enters Texture Paint Mode on the active mesh. It is laid out like a dedicated painting
tool, with the tools on the left, the assets next to them, the 3D view and the 2D paint view side by side, and the texture
sets, layers and properties on the right. Names are Blender's own. Until there is a texture project the Texture Set List shows
a **start card**: what the selection is missing (a mesh, a material, a project), the three steps **1 New Texture Project ->
2 Bake Mesh Maps -> 3 Paint** and the **New Texture Project** button (**Add Cube** without a mesh); the dock and Properties
are empty meanwhile and Assets is greyed (Bake Mesh Maps works without a project: the list comes back for its Bake checkboxes). (A material with images of its own is painted as it is: its images become the Base
layer on the first layer operation.) A mesh needs UVs and a material before it can be painted: the panels say what is missing and have a
button to fix it (Auto Unwrap, Add Material, Texture Paint Mode). The
workspace shows only what texturing needs: the menu bar of the Texturing set has no Create, Select or Modify, and the two
view headers are short (see Headers below); everything else of Blender is in the other workspaces and in the More menu of the 3D view.

```
 menu bar        File Edit Paint Layers Bake Export Display Windows Help
 toolbar         tool controls (Size, Flow, Spacing, Lazy Mouse, Symmetry)   |  view layout, Bake Mesh Maps, Export Textures
 +---+----------+-----------------------+----------------------+------------------+---+
 | T | ASSETS   | 3D VIEW  [Material v] | 2D VIEW  [Material v]| TEXTURE SETS     | D |
 | O | icons    |                       |                      +------------------+ O |
 | O | search   |                       |                      | LAYERS | TEXTURE | C |
 | L | tiles    |                       |                      |        SET SETT. | K |
 | S |          |                       |                      +------------------+   |
 |   |          |                       |                      | PROPERTIES - ... |   |
 +---+----------+-----------------------+----------------------+------------------+---+
```

| Part | Contents |
|---|---|
| Tool strip (far left) | One icon button for each tool: **Paint** (1), **Eraser** (2), **Projection** (3), **Polygon Fill** (4), **Smudge** (5), **Clone** (6) and the **Picker** (P). The tooltip names the tool and its key; the active tool is highlighted. Blender's own tool column is hidden in both views, so this is the only one |
| Assets | A full height column: a row of category icons (see Assets below), a search field and a grid of tiles |
| 3D view and 2D view | The 3D view (Material Preview, lit by a studio environment that shows blurred behind the model; no floor grid or axis lines, **Grid** in its More menu brings the grid back) and the 2D paint view (the Image Editor in Paint mode). Their headers hold only what texturing needs (see Headers below): a short **View** menu and, at the top right, the **display mode** dropdown: Material, each channel on its own, the baked mesh maps, the mask of the active layer. The 3D header also has the **viewport type**, the view layout, Display Settings and More |
| Texture Set List (right, top) | One row for each material of the active mesh, then the materials with layers of the other meshes (a texture set is a material and its layers). A row has an **eye** that shows or hides the set, its **name** (a double-click renames it), the mesh it is on when that is not the active one, and the size of its images; a click on a row makes it the active material (the Layers follow). In Bake Mesh Maps each row also has a **Bake** checkbox. The right-click menu of a row has **Rename**, **Show / Hide** and **Isolate**; the button in the header isolates the active set (Alt+Q). The list is as tall as its rows. While no material has layers it is the start card (see above) |
| Layers \| Texture Set Settings (right, middle) | Two tabs. **Layers** is the layer stack (see Layers below). **Texture Set Settings** has **General** (name, **Size**, **Normal Map Format**), **Channels** (a row for each channel of the set with its format and an x, **Add Channel**), **Mesh Maps** (a slot for each baked map, and a big **Bake Mesh Maps** button) and All Paint Slots (behind **More Brush Settings**; see Texture set settings below). **Bake Mesh Maps** replaces the tabs by the Bake page (see Bake below); **Back to Painting** (in its header) brings the Layers back, and a new project always ends on the Layers |
| Properties (right, bottom) | Follows the thumbnail you clicked in the layer list, and its title says what it shows: **Properties - Paint** (a paint layer's content: previews, then the sections of the tool: Brush, Alpha, Stencil, Material ..., and **Layer Settings**, closed), **Properties - Fill** (a fill's content: its UV transform, its Material and Layer Settings), **Properties - Mask** (a mask thumbnail: the layer's mask and the selected effect; the Paint sections follow when the mask has a Paint effect, which strokes then paint) and **Properties - Folder**. The settings that are rarely needed (Advanced, Cursor) are behind **More Brush Settings** at the bottom. See Properties below |
| Dock strip (far right) | Icons that open a popover: **Display Settings** (the viewport type, AO in viewport, the environment: a thumbnail for each studio HDRI, rotation, exposure, background and blur, Channel View, UV checker), **Shader Settings** (the Principled shader of the active material and its displacement), **History** (the undo steps, a click goes back to that step), **Export Textures** (opens the Export Textures dialog; Ctrl+Shift+E), and **Log** (the Info window with the reports) |
| Toolbar (top bar) | Left: the controls of the active tool, **Size** and **Flow** (the brush strength) with their pen pressure buttons, **Spacing**, **Lazy Mouse** (its distance shows while it is on), **Symmetry** X Y Z (the channels a stroke paints are in Properties > Material). Polygon Fill shows its fill mode instead of the brush controls; Projection adds the stencil's opacity, **Reset** and **Fit**; when a fill layer is selected the toolbar shows its UV transform (**Tiling**, **Rotation**, **Offset**, **Reset**) instead of the brush. Right: the view layout (3D \| 2D, 3D only, 2D only: one view takes the space of both while the panels stay; 3D \| 2D puts the edge back where it was, also after saving; Ctrl+Space over a view does the same), perspective / orthographic, **Bake Mesh Maps**, **Export Textures**, the workspace picker. There are no shelf rows in this workspace (Show Shelf in Workspace Settings brings them back) |
| Status bar (bottom) | The keys of the active tool, read from the keymap (so they follow your own keys): LMB with the tool's name (Paint, Eraser, Projection...), Ctrl+RMB Size / Hardness, Ctrl+LMB Flow / Angle, Shift+RMB Turn Environment, P Picker, X Swap Colors, 1-6 Tools. While a tool or gesture runs, the bar shows that tool's keys instead |

**Tools.** Blender has one brush tool for texture painting, and the brush decides what a stroke does, so each tool of the strip picks a brush and a few settings in one click:

| Tool | What it sets |
|---|---|
| Paint (1) | The Draw tool with the Paint brush you used last (Paint Hard at first) |
| Eraser (2) | A Draw brush that erases alpha: Erase Hard, or the Erase brush you used last |
| Projection (3) | Paint Hard with its texture mapped as a **Stencil** (screen space; the stencil keys move and scale it). Without a brush texture the Clouds alpha is used until you pick another |
| Polygon Fill (4) | The Fill brush with Face Selection masking: one click fills what is under the cursor, a **Polygon**, a **UV Island** (every polygon connected in the UV map) or the **Mesh** (the Fill mode is in the toolbar) |
| Smudge (5) | The Smear brush |
| Clone (6) | The Clone brush |
| Picker (P) | Picks the color under the cursor and goes on with the same tool: hold P over the model; the button on the strip starts the picker, then click on the model |

Leaving Projection puts the brush texture mapping back, and leaving Polygon Fill puts Face Selection masking back.
The other brushes (Blur, Mask, Airbrush, Paint Soft and the rest) are in Assets > Brushes: picking one makes the strip show
the tool it belongs to.

**Properties.** What the editor at the bottom right shows follows the selection, and every control is a property of Blender's
brush or of the layer. For a Paint Layer (or without a layer) it is **Properties - Paint**, with the sections of the tool:

| Tool | Sections |
|---|---|
| Paint | Previews, Brush, Alpha, Stencil, Material, Advanced, Cursor |
| Eraser | The same; its Material has only the channel buttons, it erases every channel that is on |
| Projection | Previews, **Projection** (the stencil, first), Brush, Material, Advanced, Cursor |
| Polygon Fill | Previews, **Polygon Fill** (Polygon, UV Island or Mesh) and Material |
| Smudge | Previews, Brush, Advanced, Cursor |
| Clone | Previews, Brush, **Clone** (the source to paint from), Advanced, Cursor |

The **previews** are the brush's picture and name, and a named swatch for each channel of the brush material that is on (the
color, the grey of Height, Roughness and Metallic, the Emission color). **Brush** starts closed, because the
toolbar has what you use all the time: Size (with the Unified Settings button and pen pressure), Flow (the brush
strength, with pen pressure), Hardness (in the order of Sculpt's Size, Strength, Hardness), **Accumulate**, Spacing, **Size Space**
(View or Scene units), then, when the brush has an alpha, **Angle** and **Follow Path** (the alpha turns with the stroke),
**Position Jitter** and **Angle Jitter**, **Lazy Mouse** with its **Distance** and **Smoothing**, the **Stroke Type** tiles (as in
Sculpt), and the projection options **Occlude**, **Backface Culling** and **Normal Falloff** with its angle. Blender has no separate Stroke Opacity: Flow
is the strength of a dab, and with Accumulate off a stroke never goes past it (what a stroke opacity does), while with it on
the dabs add up. Size and Flow jitter, and placing the alpha along the surface (tangent, UV), do not exist in Blender's texture
painting either, so they are not offered: an alpha is always laid over the screen.

**Alpha** is the brush's alpha (its Texture Mask) drawn as in Sculpt's tray: its picture and name, **Load Alpha...**, the
**Alignment** (Camera: the alpha stays upright on the screen, Tiled, Random or Stencil), then a grid of the alpha library (the
same alphas as the Assets category; the first tile, None, clears it). **Stencil** (closed at first) is the S key as a button, with **Reset** and **Fit** for its place and size, the opacity it is
drawn with, the same library grid (a click makes that alpha the stencil) and **Load Stencil...**; S shows it, RMB moves it,
Shift+RMB scales it and Ctrl+RMB turns it. A stencil is one picture on the screen, so it has no tiling. **Material** is the row
of channel buttons and the value of each channel that is on (see Painting several channels at once). **Advanced** (closed) has the
airbrush rate, the **Falloff** (as in Sculpt's More Brush Settings), input samples, seam bleed, dither and the cavity mask, and what the Blur and Mask
brushes have of their own. **Cursor** (closed) is Blender's brush cursor display. Both are hidden until you press **More
Brush Settings** at the bottom of Properties - Paint (**Fewer Brush Settings** hides them again); the same button shows All Paint Slots in
Texture Set Settings. **Layer Settings** (closed, at the bottom) has the rest of the layer's own settings: the name, the blend mode
and opacity of every channel, the eye, Image Alpha, the channels the layer has and its image sizes, and Save to Library. While a mask is
painted (**Properties - Mask**) the
Material is replaced by the two **Grayscale** colors: white shows the layer, black hides it, X swaps them.

For a Fill Layer it is **Properties - Fill**. **Fill** has the UV transform of the layer's textures, **Tiling**, **Rotation**
and **Offset**, with **Reset** (tiling and rotation turn around the middle of the UV map); the projection is the UV map. **Material**
is a row of buttons for the channels the fill has (**Base Color**, **Height**, **Roughness**, **Metallic**, **Emission**, **Normal**; **Color**, **Rough**... when the editor is narrow), and below it, for each one that is on, its
value and a texture slot: an image picked there (Open loads a file) replaces the value, follows the UV map through the layer's UV
transform and does not use the image's alpha. A file picked for a channel takes that channel's color space (sRGB for Base Color and
Emission, Non-Color for the rest); a Normal channel with a texture is a normal map. Its **Layer Settings** has the name, the blend
mode and opacity of every channel and the eye. For a **Folder** it is **Properties - Folder**:
name, the blend mode and opacity of each channel, **Freeze** and **Merge Folder** (its mask thumbnail shows the folder's mask). **Properties - Mask** has the **Mask** section
(Use Mask, Show Mask, Invert Mask, the mask's commands and its effects: see Masks) and the **Effect** section: the selected effect's name, its type (Paint, Fill,
Generator, Levels or Filter) and its settings; for a Paint effect a line says whether strokes paint it, in the words of the Layers panel.

The **2D view** frames the whole image (the same as F over it) when the workspace opens, the first time it shows an image
(Blender shows a new image 1:1, a small square in a big empty area), when the image has another size, and when the view
layout changes. An image you framed before comes back with the view you gave it, so the next channel with C does not undo
your zoom after the first time.

**Keys in Texture Paint Mode** (3D view and 2D view):

| Key | Does |
|---|---|
| 1 2 3 4 5 6 | Paint, Eraser, Projection, Polygon Fill, Smudge, Clone |
| P | Pick color (hold P, move over the model, let go) |
| M | Show the material |
| C / Shift+C | Show the next / previous channel on its own (what a stroke paints does not change: that is the Material section); after the last the material is shown again |
| B / Shift+B | Show the next / previous baked mesh map |
| D | Lazy Mouse |
| L | Symmetry (X) |
| S | Stencil on / off for the brush texture. Blender's stencil keys stay: RMB moves it, Shift+RMB scales it, Ctrl+RMB turns it |
| X | Swap the two colors (for a mask: black and white) |
| [ ] | Smaller / bigger brush |
| Ctrl+RMB drag | Sideways: brush size. Up and down: hardness |
| Ctrl+LMB drag | Sideways: flow. Up and down: angle of the alpha or texture |
| Shift+RMB drag | Turn the Material Preview environment |
| Alt+Q | Isolate the active texture set (again: show everything) |
| Ctrl+Shift+B | Bake Mesh Maps |
| Ctrl+Shift+E | Export Textures |
| F | Frame the model (3D view) or the image (2D view) |
| Ctrl+Space | The view under the pointer alone (3D only or 2D only, the panels stay); again: both views |

Keys pressed over the 3D view or the 2D view act on that view. F1 to F7 still switch workspaces, Space is the hotbox and
Alt+mouse navigates. Where one of these keys is also used in the 3D view (4 5 6 show wireframe, solid, textured; X C B hold
to snap; [ ] view history; Shift+RMB places the 3D cursor), the painting key wins while you are in Texture Paint Mode.
While **Face Selection masking** is on (Polygon Fill turns it on) L picks the polygons linked to the one under the cursor,
as Blender does.

**Display modes.** The dropdown at the top right of the 3D view and the 2D view lists **Material**, the **Channels** (Base
Color, Roughness, Metallic, Normal, Height, Emission: the ones the material has), the **Mesh maps** (Normal, Ambient
Occlusion, Curvature, Position, Thickness, ID, World Normal, Displacement: the ones that are baked) and **Mask**. In the 3D
view a channel is shown flat without lighting, and the maps and the mask are shown by the material instead of its shader (the
shader comes back with Material). In the 2D view the image of the channel, the map or the mask is shown. The dropdown is as
wide as what it shows and says it whole: a channel names the layer that is painted (**Base Color (Rust)**), the mask names its
layer, a map shows its name; Material is always in the list. Blender's image selector is not in the headers: the dropdown picks what
is shown, and the code picks the image that is painted.

**Material in the 2D view** is a picture of the whole material in UV space (the Material View): the layers' Base Color, with the
baked AO when AO in Viewport is on, lit by one light from the top left over the combined normal (a flat surface is as bright as
its color) and with the Emission added. It is made from the layers by a timer a moment after a stroke or any change (never while
the view draws) at 512 px at most, it is shown in View mode (strokes on it would be lost: show a channel to paint in the 2D view),
and it is never saved with the file. The 2D view paints the image it shows (it stays in Paint mode for the channels, so the painting
keys work there), so a baked map shown in it changes if you paint on it: Undo takes it back.

**Viewport types and environment.** The **viewport type** dropdown (in the 3D header and at the right of the toolbar; the five
buttons are also in Display Settings) has: **Material** (the default: Material Preview, lit by the environment), **Rendered**
(EEVEE with the lights and the world of the scene: it switches the scene to EEVEE, since Cycles in the viewport is slow), **Unlit**
(the Base Color alone, flat, without light: the material shows an Emission of the layers' Base Color, through the scene's view
transform, and every texture set follows), **Solid** (the fast Workbench view with the painted channel, lit by studio lights) and
**Wireframe** (Material with the wireframe overlay). The type is read back from the view, so the dropdown always says what it
is, and picking one takes the view back from a channel, a map or a mask. A new 3D view in the Texture workspace starts as a studio:
Material Preview with Blender's **studio** HDRI (soft boxes, neutral grey: it is the one that shows the colors the least tinted),
shown blurred behind the model (background 1.0, blur 0.5, strength 1.0), without the floor grid and the axis lines; this is set once, the first time a Texture workspace
opens, and after that the view is yours. **Display Settings** (dock strip, or the globe in the 3D header) has a thumbnail for each
studio HDRI (a click lights the Material view with it), **Rotation** (Shift+RMB drag in the view turns it too), **Exposure**,
**Background** and **Blur**, **Studio Defaults** to go back, and **AO in Viewport**.

**Headers.** The 3D view's header in the Texture workspace has the editor type, a compact **View** menu (frame, perspective,
the three axis views, the camera, and More for Blender's whole View menu), then at the right the display mode dropdown, the viewport
type, the view layout, Display Settings and a **More** menu (overlays, grid, gizmos, X-Ray, Blender's own menus). Left out of it,
and reachable in the other workspaces: the Shading, Lighting, Show, Renderer and Panels menus and their toolbar, the selection
modes, the overlay, gizmo and shading buttons, the texture slot and mask popovers. The 2D view's header has the editor type, a
compact View menu (fit, zoom) and the display mode dropdown: no image selector, pin, New / Open, Image or UV menus, overlays or
paint mode switch. Only the Texture workspace of the new layout is changed: files saved with the old layout, and the other
workspaces, keep Blender's headers.

**Assets.** The category icons are, left to right: **Materials**, **Smart Materials**, **Smart Masks**, **Brushes**,
**Alphas**, **Environments** and **Mine**.

| Category | What a click does |
|---|---|
| Materials | Adds **one Fill layer** on top of the layer stack, named after the material, with its Base Color, Roughness and Metallic: base metals (Iron, Steel, Aluminium, Raw Copper, Brass, Gold, Chrome), plastics (Plastic, White Plastic, Black Plastic), Rubber, Wood, Dark Wood, Ceramic, Matte Black |
| Smart Materials | Adds a **folder** of Fill layers whose masks use the Edges, Cavity, Top-down and Noise generators, so it fits the mesh (it reads the baked mesh maps; they are baked the first time when the mesh has none) |
| Smart Masks | Gives the **active layer** (or folder) the preset's mask effects. **Replace** swaps them for the layer's mask, **Add on Top** puts them above it, combined with it |
| Brushes | Picks the texture paint brush (all of them, also the pressure and pixel art ones), with the brush library popover on top |
| Alphas | The Sculpt alphas: the same starter set and **Load Alpha...**, in the same user folder. In Texture Paint Mode the alpha is the active brush's **Texture Mask** (it follows the cursor), None clears it. The Alpha and Stencil sections of Properties - Paint pick from the same library |
| Environments | The environments (HDRIs) of Blender's studio lights: a click lights the Material Preview with it, **Scene World** turns the scene's own world back on. Shift+RMB drag turns it |
| Mine | Your own items, and **Save Layer** / **Save Mask** |

A channel is a paint slot of the active material: the first click on **Base Color**, **Roughness**, **Metallic**,
**Normal**, **Height** or **Emission** in Texture Set Settings adds an image of the size of the texture set (Non-Color for
everything except Base Color and Emission) and plugs it into the shader; later clicks only pick it. C and Shift+C show the
next / previous channel on its own, `[` and `]` change the brush size, X swaps the two colors. A channel button in Texture Set Settings (or **Paint Roughness** and the others in the Layers menu) picks that channel to paint, alone.
The old Channel View (in Display Settings) shows the picked channel flat in the 3D view and goes back on the next click.

**Painting several channels at once.** A stroke on a Paint Layer paints every channel that is on in the **Material**
section of Properties - Paint, with its own value, in one go: the same pixels, the same opacity, falloff, symmetry and seam
bleed, and **one undo step** takes the whole stroke back in all of them. The section is a row of buttons, **Base Color
Height Roughness Metallic Emission** (Color, Rough, Metal, Emit when the editor is narrow; a channel the texture set does not have
has no button), and below it a value for each one that is on: **Base Color** is the brush color (the picker and the X
swap are the same), **Height** and **Roughness** and **Metallic** are sliders from 0 to 1 (Height 0.5 is flat, more is
higher), **Emission** is a color. Base Color is on at first, so a new project paints as before; turn on **Roughness**, say, and
the next stroke paints a Roughness value next to the color. The previews at the top of Properties - Paint show a named swatch
for each channel that is on. The channel that is turned on is added to the layer if it is missing: its image
is made at the size of the layer's other images (a stroke paints only images of one size, and says so for one that is
not). Normal is painted alone: pick it with **Paint Normal**, and with every button off the channel shown with C is the one
painted. What each tool does with them:

| Tool | Channels |
|---|---|
| Paint, Projection | Every channel that is on. A brush texture only masks (through its alpha) the channels that have a value; Base Color gets its colors |
| Eraser | Erases every channel that is on, so the layer shows through in all of them |
| Polygon Fill | Fills every channel that is on |
| Smudge, Clone, Blur | The first channel that is on only (they move the color that is there: the other channels need a smear of their own, which is not done yet) |

With Base Color off the first channel that is on is the one the brush is aimed at, and it gets its own value, not the brush
color. A selected mask, a Fill Layer, a folder and a frozen folder have nothing to paint besides the mask: the section says so and
the toolbar buttons are hidden. In the 2D view the image shown there is painted and every other channel that is on goes along with it, so a
stroke in the 2D view changes the same channels as one in the 3D view. Not done yet: UDIM tiles (a stroke on a mesh with
UDIM paints its own image only).

**Texture set settings.** **General** has the **Name** of the set (its material), its **Size** and the **Normal Map Format**. The size is one square size for the whole set: picking another
scales every image of it (the layers' images, the masks' paint images, the images of frozen folders), and a layer, mask or folder made later starts at that size. A smaller size asks first ("Scale Down"):
the detail the painted images lose is gone for good, Undo does not bring it back. The set's size is the one size of the project: the Bake page's Size, the texture size of the UV tools and the export's
**Based on the Set** follow it unless you pick another. It is square only, because masks,
Merge Down, Flatten and Export work on square images. The normal map format (**OpenGL (Unity, Blender)** or **DirectX (Unreal)**) is a setting of the project: the Normal bake writes its green channel up or down by it, and the export
templates that follow the project (Document Channels) flip the Normal channel for DirectX; the painted Normal channel itself is always kept the way Blender reads it (OpenGL).
**Channels** lists the channels of the set, each with its format and an x. The x removes a channel: its layers keep their images, but nothing is built, painted, shown or exported for it until **Add Channel**
brings it back as it was (painting a removed channel from the Layers menu or the shelf adds it back too); the last channel cannot be removed. A channel that is not a color (Roughness, Metallic, Normal, Height)
can be stored as **8 bit** or **16 bit float**: its images are copied into the other kind with the same pixels and names, and the layers made later follow. Base Color and Emission stay 8 bit sRGB, because a
float image keeps linear light, which the layer math of the colors does not read. **Mesh Maps** has a slot for Normal, World Normal, ID, Ambient Occlusion, Curvature, Position and Thickness (Displacement
joins them once baked): a thumbnail, the name of the image (`<set>_<map>`), a folder button that takes an image file for the slot, and an x that clears it. A map from a file is used like a baked one (the display modes, the
mask effects); the next bake into the slot replaces it. Not done: non-square sizes, other ways to combine the normals (the layers' normal always goes on top of the baked one as a whiteout combine), channels beyond the six.

**New Texture Project.** **File > New Texture Project...** (in the Texturing menu set) and the button of the start card in the Texture Set List (while no material has layers; it also says
when the mesh has no material: the project makes one) open a dialog for the selected meshes (a high poly, and a mesh over the face limit of the Texture workspace, is left out: the dialog says which and why; with nothing left it does nothing): the **Document Resolution** (1024 by default, then the last one used), the **Normal Map Format**, the **Channels** (Base Color, Roughness, Metallic, Normal and Height; the same with
Emission; or the minimal Base Color, Roughness and Metallic), **Auto Unwrap Missing UVs** and **Bake Mesh Maps Next** (off at first). OK gives every material of the meshes a Base layer, which is its texture set, with an image of
that size for each channel of the template (a channel that is not in the template is removed from the set, and can be added later), makes a material for a mesh that has none, unwraps a mesh without UVs and keeps the resolution
and the format as the project's. The bake size of the meshes and the texture size of the UV tools are set to **Same as Set**. The first set is the one painted and the dock shows the **Layers** (with Bake Mesh Maps Next the Bake page opens instead, to pick the high poly and bake; Back to Painting brings the Layers). A material that has layers already is left alone.

**Bake.** **Bake Mesh Maps** (in Texture Set Settings, in the toolbar, the Bake menu or Ctrl+Shift+B) is a mode of the Texture workspace: the dock shows the Bake page (its
header says **Bake Mesh Maps** and has **Back to Painting**), the Assets column shows **Baked Maps** and Properties shows **Bake Settings**: the brushes, the library and the
layer settings are no use while baking. Back to Painting puts all three back as they were, and the 2D view too. The Bake page, top to bottom:

| Part | What it is |
|---|---|
| Size and Bake | On top, so it is always in sight: the **Size** of the maps (**Same as Set** by default, shown as "1024 = Set": the size of the texture set; 1024 for a mesh without one) and one big **Bake** button that says what it bakes: **Bake 2 maps**, or **Bake 2 maps for 3 texture sets** (**Rebake 2 maps** when the maps of the active set are older than its mesh) (the ticked maps of the active set, for every texture set that has its Bake checkbox ticked in the Texture Set List; a mesh with several sets is baked once, a bake group as a group). Its tooltip says where it bakes ("GPU: NVIDIA GeForce RTX 4070 SUPER (OPTIX)" or "CPU: ..." with the reason). While a bake runs the page shows its progress instead (see Baking while you work) |
| High Poly | One line: the picker of the high poly (for a mesh without a group; the eyedropper takes the other selected mesh) or, for a mesh of a bake group, the group with its number of low and high polys. **Auto-Pair** is on the same line: it pairs meshes called Sword_low and Sword_high into bake groups. Under it, when it applies, "Maps older than the mesh" (see Out-of-date maps) and "Crate_low has Smooth Preview on: the bake uses the plain mesh" (Smooth Preview, key 3, is turned off on the low polys for a bake and for an export, and back on after; a high poly keeps it), then the result of the cage check (see The view of Bake Mesh Maps), with a button that checks again, then the **Cage Distance** (how far in front of the low poly the rays start; a group has its own) and **Auto-fit Cage** |
| Maps | A checkbox for each map with what it is for beside it (Normal: surface bumps, Ambient Occlusion: dark in crevices, Curvature: edges and cavities, Position: height and sides, Thickness: thin parts, ID: parts by colour, World Normal: which way it faces; the tooltip says more), and a line that says which maps the smart materials and masks of the library use (made from the items, also your own). When a mask of the layers reads a map that the bake leaves out, a line says so ("Rust uses Curvature") with **Tick**; it is a warning when the map is missing ("Rust needs Curvature") |

**Bake Settings** (Properties): **Visualization** (what the 3D view shows while this page is open: **Show High Poly**, **High Poly Opacity**, **Show Cage**, **Problem Color**, **Outlines and Stripes**) and **Advanced**: **Dilation**, **Antialiasing** (the samples of each pixel of the Normal, World Normal and Curvature maps), **Bake on GPU** with the device it found, **Max Ray Distance** and a custom **Cage** mesh (a group has these in its Group Settings), **All Maps**, **No Maps**, Invert and **Apply to Checked Texture Sets** (it gives the other ticked sets the maps, size, dilation and antialiasing of this one). Under them, closed at first: **Map Settings** (the settings of the map the dropdown picks: Normal: the format and the antialiasing; AO: the distance of the world's ambient occlusion and its **Quality**; Curvature: the contrast and the antialiasing; Thickness: the distance and its **Quality**; Position, World Normal and ID: what they are), **Bake Groups**, **Group Settings** (for a mesh of a group) and **Multires** (a mesh with levels and no high poly). The old layout shows all of it in its Bake tab.

**Baked Maps** (the Assets column): a thumbnail of each baked map of the active texture set with its name and size; a click shows it in the 2D view (the 3D view's display dropdown shows a map on the model). While a bake runs the 2D view shows the last map it finished (Blender's own bake would show the image it is writing) and Baked Maps the maps that are done; after the bake the 2D view keeps the last one. When you leave Bake Mesh Maps the 2D view shows what it showed before (the workspace keeps it, also in a saved file).

The tooltip of every control says what it does. When the bake is done the dock stays on the Bake page (a bake started from the Layers, with the Bake button of the shelf, goes back to them), the 3D view shows the material and every texture set that was baked uses its maps (next paragraph). A set that cannot be baked (a mesh without UVs) is reported and skipped. A mask effect that has no map (a map that was removed) is also said in the Layers panel ("Masks need Position") with a **Bake Mesh Maps** button.
The bake needs Cycles: it switches to it, bakes every ticked map into an image (kept with the file) and switches back; the mesh's materials
are not changed (a temporary material takes the bake and is removed). Curvature uses the shader's Pointiness (needs enough polygons), Thickness uses
ambient occlusion from inside the mesh (closed meshes only; white where the mesh is thicker than the Thickness Distance), Position is scaled to 0-1
within the bounds of the baked meshes. Each map gets the samples it needs: Normal, World Normal and Curvature are exact, their samples only smooth the edges (**Antialiasing**, 4 at first),
Ambient Occlusion and Thickness shoot rays and have a **Quality** of their own (32 and 8; each sample of Thickness shoots 16 rays), and Position and ID always use one sample (Cycles adds a position pass up over its samples, and the ID colours are flat).
Mask effects use these maps too (see Masks).

**Baking while you work.** A bake does not freeze the window. The maps are baked one after the other, group after group, each as one of Blender's own bake jobs (the status bar shows the bar of the
map that is baking, and after each map "Baked 2 of 10"; the maps are kept with the project when you save). The Bake page, the Status Line and the headers of the 3D and 2D views say what is baking ("Baking AO (Sword): 3 of 10"); the page also has the bar of the maps that are done, the time, and
**Cancel**, and the 3D view has a banner. **Esc** stops the map that is baking at once and ends the bake; **Cancel** ends it after the map that is baking. A cancelled bake (or one that fails) puts everything back as it was:
selection, active mesh, hidden meshes, materials, render engine, device and mode; a group that was not finished is not baked. When the last map is done the results are applied as always (the maps, the Normal and
AO of the viewport, the Material view), and the bake is one step of Undo.

While it bakes you can move the view (Alt + mouse to orbit, pan and zoom, the middle mouse button, the wheel, F, Home and the number pad), use the View menu, the layout buttons and the Display Settings (the environment and the overlays) in the headers and the layout buttons in the Status Line, and scroll the
panels. Every other click and key is stopped, with the note "Baking... (Esc to cancel)": the bake reads the scene from its own thread while it runs, so nothing can be edited, saved, undone, deleted or switched (a mode, a workspace)
until it is done. The high polys are drawn as boxes meanwhile (a mesh of millions of faces would slow the window down), a 3D view in the Rendered type shows Material (Cycles is the engine during a bake), and the view of the Bake page (below) is
put away. Mask effects bake the maps they need at once, as before. Without a window (background mode, scripts) the operators bake at once and wait.

**Where it bakes.** **Bake on GPU** (Bake Settings > Advanced, and Workspace Settings in the Texture workspace; on by default) bakes on the graphics card when there is one that bakes right, which is much faster for
Ambient Occlusion and Thickness: it takes the best Cycles backend this build has (OptiX, then CUDA, HIP, oneAPI, Metal). When Cycles' preferences have no compute device type, the first bake sets the best backend that has a GPU
and turns its GPUs on and the processor off; a type that you chose there stays as it is, and the bake never changes it. Nothing is saved by the bake: Blender keeps the preferences if its own
Save on Quit is on. A GPU is first tried with a tiny test bake of a flat colour (a card without kernels in this build, or with a failing driver, makes Cycles write grey and say nothing), and a card that fails is not used, with the
preferences put back: the processor bakes, and the Bake page says why ("CPU: The GPU did not pass a test bake (CUDA)"). The device of the scene is put back after each bake. A build of Maelstrom3D needs the Cycles
CUDA binaries (and the OptiX SDK for OptiX) to bake on a GPU.

**The view of Bake Mesh Maps.** While the dock shows the Bake page the 3D view shows what the bake will see. The **high polys** of the groups that are baked (the ticked texture sets, else the group of the active mesh) are shown as a see-through blue mesh: a temporary
material in their object slots (the meshes and their materials are not touched; a high poly that is hidden is shown meanwhile). The **cage** is each low poly pushed out by the group's Cage Distance, drawn as an orange wire. Where the bake would go wrong it is **red**: from every point of
the low poly (each corner, and the middle of each face, which lies deeper than its corners on a curved low poly; past 20,000 faces the biggest ones) a ray goes in along the normal from the extruded surface, as far as the Max Ray Distance, as the bake sends it. A point is a problem when the ray finds no high poly
(a miss: the high poly is missing there, or too far away) or when the point is inside a high poly (it sticks out past the cage, so the bake would take its inner wall instead of its surface). The page (in High Poly) and the corner of the 3D view say what was found and what fixes it, a line for each kind of problem
("Cage too tight in 3 places: raise Cage Distance"; "Rays find no high poly here: raise Max Ray Distance", or "...: the high poly does not cover it" where it has a hole or a gap; places are patches of faces that touch), and a button next to it checks again. The check runs a moment after the last change (the Cage Distance, the Max Ray Distance, a custom cage, a mesh that moved or was edited), in small slices
of a timer, so the window stays usable; a high poly bigger than 8 million faces is not checked. **Auto-fit Cage** (next to the Cage Distance) measures, from every point of the low polys (corners and face middles, at most 50,000 of each mesh), how far the high polys stick out along the normal, and sets the Cage Distance 10% past the farthest (in the units of the mesh, as the bake extrudes; a ray that leaves through a hole of an open high poly is not counted); a Max Ray Distance that is set and too short for that cage is raised. It does that for every group and mesh the Bake button bakes (not for one that bakes from a cage mesh), as one step of Undo, and the check runs again. **Visualization** (Bake Settings) has **Show High Poly**, **High Poly Opacity**, **Show Cage**, **Problem Color** and **Outlines and Stripes** (on at first: a thick black and white outline around the problem areas and diagonal stripes on the see-through high poly, so neither needs telling colours apart; the stripes show in the Material view). Everything goes back when you leave the Bake page
(the high polys are hidden again), before a file is saved (a file never has the blue material), and after an Undo or when a file is loaded.

**Baked maps in the viewport.** A bake changes what you see: the texture sets of the baked meshes use the **Normal** and **AO** maps in their shader (Texture Set Settings > Mesh Maps and a map picked from a file do the same, and so does a file that has baked maps when it is opened). The baked **Normal** is the base normal of the material: an Image Texture (Non-Color) into a Normal Map node, under the layers. When the layers paint a Normal channel, the layers' normal goes on top of the baked one as detail, a whiteout combine in tangent space made of Vector Math nodes in front of the Normal Map node (decode both to -1..1, add the slopes x and y, multiply the z's, make the vector one long, encode): a flat layer normal leaves the baked normal as it is and a flat baked normal leaves the painted one. A normal bake made as DirectX is read with its green channel turned over first (the bake remembers its format, so changing the project's format later does not change a map that is made). A set without the Normal channel uses no baked normal. The **AO** map darkens the Base Color in the viewport only: a Multiply node between the Base Color layers and the Principled shader (Display Settings > **AO in Viewport**, on by default), and the Unlit viewport type, the exported Base Color and a render (F12, an animation: the multiply is taken out of the shader when a render starts and put back when it ends) never have it. Export writes the same combined normal the nodes show (in OpenGL, or DirectX when the template follows a DirectX project), computed in numpy and compared with a Cycles bake of the nodes; Merge Down and Flatten work on the layers alone, since the baked map is not a layer. Height from a Multires displacement is not combined: the Normal bake already holds that detail, so it would count twice.

A mesh without a role bakes as before: the images are named `<mesh>_<Map>`, with the **High Poly** mesh when one is picked (selected to active), else
from the mesh itself. **Make Pair** (below the picker) turns the picked mesh into the high poly of a new group and the mesh into its low poly.

**Out-of-date maps.** Maps are older than the mesh when a mesh they were baked from or onto was moved or edited after the bake (the same rules as a Stale bake group, below), or another High Poly was picked. This is tracked for bake groups and for meshes baked with the High Poly picker (or from themselves) alike, and kept in the file. It shows as a warning icon on the row of the texture set in the Texture Set List, a "Maps older than the mesh" line with **Rebake** in the Layers panel, on the Export page and in the Export Textures dialog, and on the Bake page, whose Bake button then says **Rebake**. Rebake bakes those texture sets again with the maps ticked on the Bake page.

**Bake groups.** A group (see High poly and low poly) is one or more low polys, which get the maps, and one or more high polys, which the detail is
baked from; several high polys in one group (a panel and its bolts) are baked together. The **Bake Groups** section of Advanced (Bake Settings) lists the
groups of the scene with their number of low and high polys and their state: **Baked**, **Stale** (a mesh of the group was moved or edited, joined or left
the group, or a setting of the group changed, after the bake; the file keeps this) or **Not baked**. Clicking a row selects the group's low poly. Below the
list: **Pair Selected**, **Make Pair** (once a High Poly is picked), the **Rename to Suffixes** menu and **Explode**. **Auto-Pair by Name** is next to the High Poly picker, and
the one **Bake** button bakes the groups of the ticked texture sets; the Bake menu has **Bake Maps** (the group of the active mesh) and **Bake All Groups**. Bake All Groups
shows its progress, writes the time of each group to the Info log, skips a group that fails (a missing UV map, a cage that does not fit) and says which,
and is one step of Undo. The Bake button of the shelf bakes the group of the active mesh. Going into a mode, painting a texture, adding or applying a material, the UV checker map, the export and a rename do not make a group stale. Leaving Sculpt Mode or Edit Mode does (Blender only tells then that a mesh may have changed, not whether it did), and so does any other change of a mesh's material slots, which Blender reports like an edit.

Every group is baked on its own, whatever else is in the scene: only its high polys are the source, and all the other meshes (the other groups, the low
polys, loose meshes) are not rendered meanwhile, so a neighbour that touches the group, or sits in the same place, cannot shadow its ambient occlusion or reach its normal
map. The low poly that is being baked never shadows its high poly. High polys that are hidden (Maelstrom3D hides them outside Sculpt) are shown for the bake
only, and hidden again; selection, the active mesh, the mode, the render engine and every visibility and render flag are put back, also when the bake fails.

The **Group Settings** section (below the list, for the group of the active mesh) has the group's own values, made from the low poly's own Bake page values:
**Max Ray Distance** (its **Cage Distance** is in High Poly), a **Cage** (a mesh with the same faces as the low poly, for a group with one low poly; the rays start from it instead of
from the extruded low poly), and **AO Shadows**: **This Group** (the default) or **Whole Model**, which lets the high polys of every group shadow this group's ambient
occlusion, for contact shadows between the groups. The maps, the size, the dilation, the antialiasing, the Thickness Distance and the AO Distance are shared by the
group's texture set.

**Explode.** The **Explode** button of the Bake Groups section moves the groups apart along one axis (**Axis**: X, Y or Z), so that you can look at them one by one or export them to
another baker. The low polys, high polys and custom cage of a group move together, so a bake while they are apart gives the same maps as before; Whole Model ambient occlusion is the one
exception, since it sees the groups where they are. The groups are taken in the order they have along the axis, and a group is moved past the one before it only when their bounds overlap or are closer than
the **Gap** (a share of the average size of a group): a group that has room stays where it is. The button says **Collapse** while they are apart and puts every mesh back exactly where it was; the
small refresh button beside it lines the groups up again, for a group that was added meanwhile. Changing the axis or the gap while the groups are apart lines them up again at once. Each mesh keeps where it was and what
was added to it, so this survives saving and opening the file, and Undo works. A mesh that you moved yourself in the meantime goes back by what was added. Exploding or collapsing does not make a baked group stale.
A copy of a moved mesh (Create High Poly, Auto Low Poly, New Low Poly) goes back with the mesh it was made from; a mesh that you add to an exploded group by hand is left where it is: use the refresh button.

**Cage preview.** **Show Cage** in the Group Settings section draws the low poly of the active group pushed out along its normals by the group's Cage Distance (or the custom Cage, as it is) as an orange wire in the 3D view, so you can check that it
covers the high poly (show the high poly with Edit High Poly). It follows the Cage Distance and the low poly while you work. It is only drawn: the wire is made of temporary objects that share the low poly's mesh, are never rendered or selected, and
are taken away when you press the button again, pick a mesh of another group, start a bake, and when a file is saved or opened, so they are never in a saved file or in a bake. The distance is the Cage Distance in the world, also when the low poly is
scaled (a scale you change afterwards is not followed: press the button twice).

**Texture sets.** Low polys that share a material are one texture set, for example a blade, a guard and a hilt with one UV layout: they bake into the same images, named after
the material (`Sword_Normal`, `Sword_AO`), and each adds its own UV islands. Bake All starts the images over; **Bake Group** on one of the groups adds its islands and keeps the
others (Position is scaled to the bounds of the whole set, so it is baked again for the whole set). The first low poly by name decides the maps, the size, the margin and the
samples of the set. A low poly whose material nobody else shares, and every mesh without a role, keeps maps named after the mesh (`Cube_Normal`); maps named after a mesh in
files from earlier versions are still found and used until the set is baked.

**Multires.** A mesh with a Multires modifier that has levels, and no high poly (a low poly of a group without high polys, or a mesh without a role and without a picked High Poly), gets a **Multires** section under
Advanced in Bake Settings: **Normal** and **Displacement** buttons, **Low Level** (the Multires level the detail is baked onto: 0 is the base mesh) and **Bake Multires**. It uses Blender's own Multires baker: what the levels above the Low Level
add to it becomes a tangent space normal map and / or a displacement map (a float map; grey is no distance), without any high poly, in the size and dilation of the Bake page. The images are named like the other maps (`<mesh>_Normal`,
`<mesh>_Displacement`; after the material for a low poly of a texture set), so everything that reads a baked map finds them. The Multires modifier has to be the last modifier, and the mesh needs UVs. The render settings of the scene,
the level of the modifier, the selection and the mode are put back, also when the bake fails. A Low Level of 3 on a modifier with 3 levels has nothing above it, so it bakes the last level only.

**ID map.** The **ID** map of the Maps list gives each material of the group's high polys a flat colour, or each high poly mesh when they have only one material (or none) between them, baked onto the low poly: one sample, so the edges
between the colours are hard, and the margin only extends them. The colours follow the names of the materials (or the meshes) in order, so a new bake gives the same ones; a slot without a material is black, like the background. The map is
named like the others (`<mesh>_ID`) and keeps which colour is which (shown in the Color ID mask effect, see Masks).

**Bake meshes.** The **Bake meshes** option of Export Textures (off by default) also writes the low polys and the high polys of the bake groups as two FBX files in the export folder, for tools that match meshes by name: `<name>_low.fbx` with the
low polys and `<name>_high.fbx` with the high polys, of the groups of the active mesh's texture set (all the low polys that share its material; the name is the material's when there are several, else the group's). The meshes are named in the
`_low` / `_high` style inside the files (`Sword_low`, `Sword_high`, `Sword_high_bolts`), whatever style they have in the scene, and have their own names again afterwards. High polys that Maelstrom3D hid are shown for the export only and hidden
again before anything is drawn. A mesh without a bake group is refused; a group without a high poly only writes the low file.

**Export Textures** (the dock strip, the toolbar, the Export menu or Ctrl+Shift+E) opens a dialog. On the left are the **Texture Sets** to export (a checkbox for each) and the **Output Maps** of the template, each with a
checkbox that skips it and the file name it will have. On the right: the **Template** (the engine the files are for), the **Output Directory** (it may start with `//`, next to the saved file), the **File Type** (PNG, TGA, TIFF
or EXR) with its **Bit Depth** (PNG and TIFF 8 or 16 bit, EXR 16 or 32 bit float, TGA 8 bit), the **Size** (the size of each set, or 64 to 8192 px: the layers are resampled) and the **Padding**, and the Bake meshes option. **Export**
writes the files, and a summary lists them (**Export to Engine...** beside the count writes the meshes and the animation with them, see Pipeline). A file is named after the texture set: its material when several meshes share it (`T_Crate_BC.png` for Crate_low and Crate_low_lid), else the mesh without its _low / _high suffix (`T_Crate_BC.png` for Crate_low), with the material too when the mesh has more than one (`T_Hero_Body_BC.png`). **File Name** (below the Output Directory) is the pattern, kept for each template: `$set` (that name), `$mesh` (the mesh without its suffix), `$material`, and any prefix or suffix around them (`Props_$set`). The padding around the UV islands takes the islands of every mesh of the set, so each mesh keeps its own colours. A channel without a paint image uses the shader's value, and
the colors are written in linear light in EXR files. The Normal is the combined one (the layers' normal on top of the baked normal map, as the 3D view shows it); the baked AO is
never in the exported Base Color.

| Template | Files |
|---|---|
| glTF PBR Metal Roughness | One `.glb` for each texture set, named after it, with every mesh of the set (their modifiers applied, Smooth Preview left out), materials and textures; sets that share a mesh (a mesh with two materials) go into one file, named after the mesh |
| Unreal Engine Packed (ORM) | `T_Name_BC`, `_N` (DirectX: green channel flipped), `_ORM` (red occlusion from the baked AO map, green roughness, blue metallic), `_E` |
| Unity URP | `Name_Albedo`, `_Normal`, `_MetallicSmoothness` (metallic in red, smoothness in alpha), `_Occlusion`, `_Emission` |
| Unity HDRP | `Name_BaseMap`, `_Normal`, `_MaskMap` (red metallic, green occlusion, blue detail mask, alpha smoothness), `_Emission` |
| Blender Principled | `Name_BaseColor`, `_Roughness`, `_Metallic`, `_Normal` (OpenGL), `_Emission`, `_Height` |
| Document Channels + Normal + AO | One file for each channel of the set, `_Normal` in the format of the project, and `_AO` from the baked map |
| Mesh Maps | The baked mesh maps of the set as they are: `Name_Normal`, `_WorldNormal`, `_ID`, `_AO`, `_Curvature`, `_Position`, `_Thickness` |

A map is written only when its channel is in the set (or its mesh map is baked): the packed maps are always written, with the shader's values for what the set lacks. **Padding** is **Dilation Infinite** (the default: the color at the edge
of each UV island spreads over the whole empty part of the map, so filtering and mip-maps show no seams), **Dilation** (it spreads that many pixels, the rest of the map is left as the layers have it) or **No Padding**. The islands are the
faces of the set's material in the active UV map; the baked mesh maps are written as they are (a bake has its own dilation). The **Export Active Set** entry of the Export menu writes the active set with the settings of the dialog,
without asking.

**Layers.** Blender has no paint layers, so the stack is kept on the material and built into its shader. The first
**Paint Layer** or **Fill Layer** on a material that already has paint slots turns those images into the bottom layer
"Base" (nothing painted is lost; the new image nodes keep the old ones' interpolation, extension, Mapping link and
the Normal Map / Bump settings, and the Base layer ignores image alpha so the look does not change). A Paint Layer is transparent and holds one image per channel; the image of a channel
is only made (at the "new slot" size) when that layer and channel are first picked for painting, so unused channels cost
no memory. A Fill Layer is a value or color over the whole mesh, or a texture (Properties - Fill); limit it with a **Mask** (next paragraphs).
**What a stroke paints** is the thumbnail selected in the list: the content thumbnail (or the name) paints the layer's channels,
the mask thumbnail (or an effect row) paints the mask's Paint effect. The content of a Fill Layer or a folder is not painted: click
its mask thumbnail to paint the mask, or turn the fill into a Paint Layer with Convert (the Layers panel offers it for a fill
without a mask); until then the brush is aimed at a tiny hidden scratch image so no layer is painted by mistake. The line under the
list says what is painted ("Painting Paint Layer: Base Color", "Painting Fill Layer mask") or what to click; **Switch Layer / Mask**
in the Layers menu does the same as the thumbnails.
The brush paints the active layer's images of the channels that are on in the brush material (next paragraph). Every layer
has its own **blend mode and opacity for each channel** (next paragraph). Double-click a name to rename it. In the shader each
channel has a frame with one Image Texture and Mix node per layer; only nodes made by the stack are ever changed. **Merge Down**
combines a layer into the one below with its blend mode, opacity and mask baked in (exact when the lower layer is opaque or the
upper one uses Normal; the merged layer keeps the lower layer's blend mode in each channel); **Flatten** replaces the stack by one
layer holding what it looks like.
Export, glTF included, uses the flattened visible stack of each channel (the Normal on top of the baked normal map) and does not change the layers. The Layers dock warns
(Layer images use N MB, in red) when the layer images add up to more than twelve 4K images of memory; below that it says nothing.

**The Layers panel.** The header has, from the left, **Show** [channel] (the channel the rows show) and these icon buttons (the
tooltip of each says what it is and its key): **Add Effect** (a menu:
Add Fill, Add Paint, Add Generator and Add Filter (menus of the generators and the filters), Add Levels, Add Color Selection (a
Color ID effect): they are the effects of the selected layer's mask, see Masks), **Add Mask** (a
menu: White Mask, Black Mask and Image Mask, which reads an image file, then the same Add items as Add Effect),
**Add Paint Layer**, **Add Fill Layer**, **Add Smart Material** (a grid of the smart materials of the Library: a click adds one as a
folder), **Add Folder** and **Delete**. The **...** menu has Merge Down, Flatten, Group, Move In and Move Out, Freeze (Unfreeze),
Merge Folder, Convert to Paint Layer and Cut, Copy and Paste. The list shows the top layer first and grows with the stack (it has no filter options or resize grip). A row is one line: the eye, the folder
triangle (folders), the **content thumbnail**, the **mask thumbnail** when the layer has a mask, the name (a double-click renames
it; it takes the free width, so it is not cut short), and at the right the blend mode and the opacity where they say something:
on the active layer always, as a button ("100%", "Mult 50%") that opens the blend modes and an opacity slider, on the other rows only
when they are not Normal at 100%, as a short text (Mult 50%, Ovrl, 75%: Norm, Pthr, Repl, Mult, Add ...). The columns have the
same width in every row, so the names line up. The thumbnail is a small picture of the layer's image,
a flat swatch for a fill, a folder icon for a folder, and the layer's kind in grey when it has nothing in the channel. The mask
thumbnail is the picture of the mask's Paint effect, or the icon of its top effect when it has none (a generator). The row
at its right shows **the channel picked in the dropdown**: the thumbnail, the blend mode and the opacity of Base Color, Roughness,
Metallic, Normal, Height or Emission (it changes nothing else: the other channels keep their own). A click on the content thumbnail
(or on the name) selects the layer with its content: strokes paint the layer and Properties shows its settings; a click on the mask
thumbnail selects the layer with its mask: strokes paint the mask and Properties shows it (Properties - Mask). The selected thumbnail of
the active layer is framed. **Alt+click** on the mask thumbnail also shows the mask alone in the 3D view (Show Mask, again to go back)
and **Shift+click** switches the mask off and on (Use Mask: the layer shows as if it had none; the mask is kept). The active layer lists
the effects of its mask under it, each in a thin row with an eye, its icon and name, and its blend mode and opacity by the same rule as
the layer rows (a filter has no blend mode): a click on the name selects the effect and the mask (Properties - Mask); **Delete Effect**
is in its right-click menu. The arrows beside the list move the active layer (a list cannot be dragged); the button under them duplicates it.

The blend modes are Normal (a mix), **Passthrough** (the layer does not touch this channel: it has no nodes in it and nothing
is exported for it), **Replace** (the layer's pixels replace what is below, also where its image is transparent; opacity and
mask still fade it), Multiply, Divide, Darken, Lighten, Add (Linear Dodge), Subtract, Difference, Overlay, Screen, Color Burn,
Color Dodge, Soft Light, Linear Light, Hue, Saturation, Color and Value. New layers mix every channel except Height, which
is **Linear Light**: Height is stored with 0.5 as flat, and Linear Light leaves 0.5 alone, raises what is above it and digs
what is below (what Add does to a signed height in other painting tools), so painted or filled bumps add up. The Base layer
made from existing paint slots, or by Flatten, mixes Height, so the look does not change. The Normal channel mixes its layers; the baked normal map is not a layer: the layers' normal goes on top of it as detail (see Baked maps in the viewport). Every mode is exact in the numbers Merge Down,
Flatten, Freeze and Export use, and was compared with a Cycles bake of the shader nodes. Color Burn and Color Dodge need one more
Mix node in the channel (their node formulas are not linear in the strength). **Layer Settings** (in Properties - Paint and Fill) and Properties - Folder have the
blend mode and opacity of every channel. Layers from older files open with their one blend mode and opacity in every channel
(the Normal channel keeps mixing), so they look the same.

**The right-click menu and the keys.** A right-click on a row opens a menu for the layer under the pointer (it is selected
first): **Cut**, **Copy**, **Paste**, **Duplicate**, **Delete**, **Group**, **Add Effect**, **Add Mask**, **Create Smart Material**
(on a folder: the same as Save to Library), **Create Smart Mask** (on a layer with a mask), **Merge Down**, **Flatten** and **Freeze**
(Unfreeze). Copy and Cut take the active layer (a folder with its layers); Paste puts a copy above the active layer, with its own
images, also in another material (after Cut it moves the layer instead). A right-click on the **mask thumbnail**, on an effect row
of its mask, or on the effects in the Mask panel opens the **mask menu** instead, for that layer: **Add Fill**, **Add Paint**
(white or black), **Add Generator** and **Add Filter** (menus), **Add Levels**, **Add Color Selection**, **Delete Effect** (on an effect), then **Invert Mask**,
**Toggle Mask**, **Clear Mask** (to white or to black), **Copy Mask**, **Paste Mask** (replaces the mask of the layer with a copy,
also from another material), **Create Smart Mask** and **Remove Mask**. From an effect row a new effect goes above that effect.
The Mask panel has the same menu behind its **...** button. In the Layers tab the keys are Ctrl+C, Ctrl+X, Ctrl+V
(also Ctrl+Shift+V), Ctrl+D, Ctrl+G and Delete. Blender uses the buttons first: with the pointer on a number field or a name,
Ctrl+D adds a driver and Ctrl+V pastes text into it, so point at a thumbnail or at empty space when you use the keys (Ctrl+V
needs empty space; Ctrl+Shift+V works over a thumbnail).

**Masks.** A mask decides where a layer shows: white shows the layer, black hides it, grey shows it partly. A layer's
mask is a list of **effects** that combine from the bottom up (the list shows the top effect first, like the layer
list). The result starts out white, so a layer without effects shows everywhere; each effect then changes the result
below it. In the Mask panel: **White (Show All)** / **Black (Hide All)** start a mask with a Paint effect (an image you
paint: black hides, white shows). A mask has **Use Mask** (off: the layer shows as if it had none; the mask is kept), **Show Mask**,
**Invert Mask** and the mask menu (the button at its right: the commands of the right-click menu, **Remove Mask** among them). Its
effects are under **Mask Effects (N)**, closed at first (the layer list shows them too): **Add Mask Effect** adds one above the
selected effect; the arrows move it, the buttons beside the list duplicate and delete it. A new mask or effect selects the mask. **Image Mask** (Add Mask in the Layers panel) makes a Paint effect from an image file,
by its brightness. Every effect has an eye, a name, an opacity (how strongly it applies;
at 0 it does nothing) and, for the sources, a blend mode (Normal, Multiply, Add, Subtract, Max, Min: Multiply keeps
only what both agree on, Add and Max grow the white). A new effect on top of others multiplies (a black Paint adds),
so it starts out gentle; the first one simply sets the mask.

| Effect | What it makes |
|---|---|
| Paint | An image you paint with the brush (the mask thumbnail selected). Starts white (paint black to hide) or black (paint white to show) |
| Fill | One value, 0 (black) to 1 (white), over the whole mesh |
| Edges | White on convex edges, for edge wear: Amount, Softness, Invert. Needs the Curvature map, so it works best on meshes with enough polygons |
| Cavity | White in crevices, for dirt: Amount, Contrast, Invert (from the ambient occlusion map) |
| Top-down | White on surfaces facing a direction (default up, +Z in the world), for dust and snow: Direction, Offset (higher also covers steeper surfaces), Softness, Height Falloff (less toward the bottom of the mesh) |
| Thickness | White where the mesh is thin: Amount, Contrast, Invert (closed meshes only) |
| Color ID | White where the baked ID map has the picked colour, so one material (or one mesh) of the high poly: Color, Tolerance (a colour within half of it counts fully, one further than it not at all). The Mask panel lists the colours of the map to pick from |
| Noise | Procedural noise: Scale, Detail, Contrast, Seed, and Space: UV (breaks where UV islands meet) or Object (follows the 3D position, no breaks) |
| Levels | Filter: Black In / White In stretch the range, Gamma bends the midtones, Black Out / White Out limit the result |
| Blur | Filter: softens everything below it (Amount is the width) |
| Invert | Filter: swaps black and white (opacity sets how much) |
| Sharpen | Filter: steeper steps between black and white |

Filters work on everything below them, so their place in the list matters; sources and generators are combined with
the result below by their blend mode. **Show Mask** shows the active layer's mask in the 3D view (white where the layer
shows); switching it off puts the material back exactly as it was. **Invert Mask** adds an Invert effect on top (or
takes it off again); **Remove Mask** (mask menu) removes the whole mask. **Rebake Mesh Maps**, shown when an effect of the mask reads baked
maps, makes the maps again after the mesh or the Bake page's settings changed.

The generators read maps baked from the mesh (Curvature, AO, Position, Thickness, ID, plus the world normal). A smart material or mask applied
from the Library to a mesh with no high poly asks first: when a mesh named like its high poly is in the scene ("Crate_high found") it offers **Pair and Bake**
(the two become a bake group and the maps come from the high poly) or **Bake from the Mesh Itself**; else it says the maps come from the mesh itself. The first time
an effect needs one, it is baked with Cycles at the Bake page's resolution, like the Bake page does (named
`<mesh>_<Map>`, with the high-poly mesh when one is set; for a low poly of a group: from its group, together with the other low polys of its texture set, named after the material) and kept with the file; every layer and effect then reuses it,
and only a new resolution, Rebake Mesh Maps or the Bake page bake it again. Nothing in the mesh's materials changes while
baking. A mesh without UVs shows the usual "Auto Unwrap" message first.

In the shader each layer's mask is one more chain in a frame of its own ("Mask: layer name"), made of one node group
per effect type (Edges, Cavity, Top-down, Thickness, Noise, Levels, Invert, Sharpen: made once and shared) and one Mix
node per effect; it multiplies the layer's strength in every channel the layer has. Editing a value only sets node
values, adding, removing or moving an effect makes that layer's mask chain again. Merge Down, Flatten and Export
compute the same masks in numpy (including the noise, which is Cycles' own Perlin noise ported, and the maps), so what
you export is what the shader shows. Blur cannot be done per pixel in the shader, so it keeps a small image (a blurred
copy of everything below it, kept as `<material>_<layer>_Blur`); it is made again when anything below the Blur changes,
a moment after a brush stroke ends, and before Merge Down, Flatten and Export. Files from before mask stacks open with
each mask as a Paint effect (and Invert Mask as an Invert effect), looking the same.

**Folders.** A folder groups layers so a long stack stays manageable and cheap. The layers inside are combined with
each other first, as if they were laid on an empty sheet, and the result is then blended onto the stack below with the
folder's own blend mode, opacity, eye and mask, like one more layer. So a folder at 50% fades everything inside together
(not layer by layer), and a mask on a folder hides or shows the group as a whole. **Add Folder** (in the header)
adds an empty folder above the active layer, **Group** (the ... menu, Ctrl+G) puts the active layer (or folder) into a new
one. The triangle in front of a folder's name closes or opens it in the list (closing a folder that holds the active
layer selects the folder). The arrows move the active layer one place of the list at a time: past a neighbour, into an
open folder next to it, and out of a folder when it is at its first or last place (a closed folder is passed as one
block); **Move In** (the ... menu) lists the folders and moves the layer to the top of the one you pick, **Move Out** puts it just
above its folder. Folders can hold folders, to any depth. Duplicate copies a folder with all its layers and their
images, Delete removes the folder, its layers and their images (images used elsewhere stay), **Merge Down** merges a
layer or folder into the layer below it in the same folder (not into a folder: merge that first), and **Merge Folder**
turns a folder into one Paint Layer holding what its layers made together, with the folder's name, blend mode, opacity,
eye and mask (the look does not change). The folder's mask thumbnail shows its mask in Properties - Mask, like a layer's; a folder itself cannot be
painted, pick a layer inside it (or its mask).

**Freezing.** A folder of many layers costs one Image Texture, Mix and several helper nodes per layer and channel while
you work: in a material with two channels, a live folder of eight layers is about 100 shader nodes. **Freeze** (the
snowflake on the folder's row, or in the Layer panel) bakes the folder into one image per channel it changes (the image's
alpha is what the layers cover) at the size of the largest image inside, or the new slot size when no layer has an image;
the folder then needs 3 nodes per channel (a 12-layer material of two channels went from 134 to 34 shader nodes with a
folder of eight frozen). It uses the same pixel math as Merge Down and Export, not a render, and takes a few seconds at
2048 px (about 5 s for eight layers in Base Color and Roughness). The layers stay in the folder, shown greyed in the list,
but are not in the shader and cannot be edited, moved, masked or painted until you **Unfreeze**: strokes then go to the
hidden scratch image, so no image changes. The folder's own blend mode, opacity, eye and mask stay live while it is
frozen. Unfreeze deletes the frozen images and puts back exactly the nodes it had; to refresh after an edit, unfreeze,
edit and freeze again. Frozen images are 8 bit like all layer images, so a frozen folder differs from the live one by
that rounding (about 1% at most, usually far less). Merge Down, Flatten and Export use the frozen images, so they give
what the shader shows. The frozen images are saved or packed with the file like the other layer images.

In the shader a folder's layers are chained in the channel's frame like any layer, but over nothing instead of the
channel's value: besides the color the chain carries the coverage (how much of the pixel the layers cover), so the
layers on top of a half-covered pixel blend only where something is below them, which is what the numpy math of Merge
Down and Export does too (the comparison with a Cycles bake of the chain agrees to float rounding for data channels and
to about 1% for sRGB images with alpha, which Cycles keeps with the color multiplied by the alpha in 8 bits). A layer in
a folder after the first needs about four more nodes than a layer on its own, which freezing takes away. Materials from
before folders open unchanged.

**Library.** The Assets panel (see above) holds ready-made things to apply and the things you saved. A material is a Fill layer
or a folder of them, and a mask preset is a mask stack, so applying one only makes layers and effects; each click is one undo
step and one rebuild of the nodes (the maps the generators read are baked once; Rebake Mesh Maps keeps them current). A mesh
without a material gets one. Everything in it can be toggled, faded, masked, frozen or deleted like any layer.

The starter **plain materials** are one Fill layer each (see the Materials row above) with plausible PBR values (metals have
metallic 1 and a tinted color, the rest 0). The starter **smart materials** are Painted Metal (worn through at the edges,
dirt in the crevices), Rusty Iron, Brushed Steel, Copper (patina in the cavities), Dirty Plastic, Concrete (noise), Dusty and
Snow Cover (top-down, to add over any material) and Mud (cavity and noise). The starter **smart masks** are Edge Wear, Dirt in
Cavities, Top-down Dust, Noise Breakup, Thickness Glow, Speckle, Grunge, Light Dust, Snow Cap and Large Patches. They are
built from fills and the mask generators only, no image files, and are read-only.

**Saving your own.** **Save to Library** in the Layer panel saves the active layer, or the active folder with everything
in it (nested folders, fills, paint layers with their pixels, blend modes, opacities, masks), as a material; in the Mask
panel it saves the layer's mask stack as a mask preset. You are asked for a name. Under Mine, each item has a rename and
a delete button (Your Items); the starter items have neither. An item is a folder in the user data folder
`datafiles/m3d_library/user/<name>/` (inside the portable folder in a portable install): `item.json` describes the
layers (kind, name, visible, the blend mode and opacity of each channel that is not Normal and 100%, per channel the fill color or value
or the PNG of a paint layer, the textures of a fill layer and its UV transform, the mask effects with all their settings, and whether the
mask is on; an item from before every channel had its own has one blend mode and opacity, which are read into every channel) and any paint and texture images are saved beside it as PNG, so applying an item makes the layers
again with the same pixels and values (a saved folder applied back gives the same composite exactly). Applying one
checks nothing is half done: a damaged item is refused and leaves the stack as it was.

**Previews.** The tile pictures are small Cycles renders of a sphere with grooves (so edges and cavities exist) lit by
Blender's courtyard HDRI, 128 px, with the item applied; a mask preset is shown as the mask on the sphere. They are made
the first time the Assets panel is drawn, one small step at a time on a timer (the preview scene, then each baked map,
then one item per step: the longest step is about a second), and a tile shows a shaded disc in the material's color until its picture is
ready. The pictures of the starter items come with the program (`datafiles/m3d_library_thumbs`: 128 px PNGs, about 700 KB in all, made in half a minute by
`tools/m3d/library_thumbs.py`), so the first Texture workspace does not make them; one that is not there (an item or the preview look changed since) is made as
above and cached in `datafiles/m3d_library/thumbs`. Yours are `thumb.png` in the item's folder. The temporary preview scene is removed when it is done (and when you save the file in between); **Refresh
Previews** (Mine, Your Items) makes them all again.

Painted images never get lost: before a file is saved, images with changes are written to their files, or packed into
the .blend when they have none. **File > Save All Images** (Texturing menu set) does the same on demand. Large images use a lot of memory: new slots
take the size of their texture set (1024 px by default).

## Rigging (F5)

F5 opens the Rigging workspace in Object Mode. Left: the Outliner (a skeleton shows its bones as a tree under it) over a
small page with the bone collections and the active bone. Middle: a large viewport (bones show through the mesh in Pose
Mode; each new skeleton is drawn in front). Right: the dock. Bottom: the Time Slider, as in the other workspaces; the
**Drivers** button in the Status Line (or in the Drive tab) opens the Drivers editor under the viewport (with its sidebar,
where a driver is edited) and closes it again.

| Part | Contents |
|---|---|
| Status Line | **Object / Edit / Pose / Weight Paint** mode buttons, X-Mirror (of the bones in Edit Mode, of the pose in Pose Mode, of the mesh in Weight Paint Mode), bone display (Octahedral, Stick, B-Bone, Envelope, Wire), Names, Axes, In Front, Rest / Pose position, Drivers |
| Shelves | Skeleton (Joint, Extrude, Mirror, Orient, Names L/R, Parent, Disconnect), Controls (circle, square, arrow, cube and sphere shapes, a color and Apply, IK + Pole), Skin (Bind, Paint Weights, Normalize, Mirror Weights), Custom |
| Channel Box tab | The same Channel Box as everywhere (Ctrl+A): the active object's channels, or in Pose Mode the active bone's, with its **Rotate Order** |
| Skeleton tab | Joint tool and its options; Edit Bones (Extrude, Extrude Forked, Click Extrude, Subdivide, Duplicate, Delete, Fill Between Joints, Switch Direction, Align); Mirror (+X to -X, -X to +X, Select Mirror); Orient (Orient Joint and the roll presets); Names (Name Sides by X / Y / Z, Flip Names, **Rename Chain**, Prefix, Find / Replace, the naming check); Hierarchy (Parent connected / with offset, Disconnect, Clear Parent, Select Parent / Child); Generate Rig (Rigify) |
| Controls & Constraints tab | Add Constraint buttons (Copy Location / Rotation / Scale / Transforms, Child Of, Damped Track, Stretch To, Armature, the Limit constraints, Action, Spline IK, IK) with **Keep Offset**, Remove Constraints; IK (chain length, pole distance, **IK with Pole**, IK to Bone, **Pole Vector**, Clear IK); the active bone's constraint stack; Control Shape and Color; Locks with **Rotate Order** and "New Bones in XYZ Euler" |
| Skin tab | Bind (Automatic, Envelope or Empty Groups, with a fall back to envelope weights), Unbind (for a bound mesh); Weight Paint (mode button, brush weight, size and strength, **Auto Normalize**, Multi-Paint, Lock-Relative, Vertex / Face Select, bone selection and mirror options); Influences (every vertex group with a lock and a solo button, **Select Weighted Vertices**); Weights once the mesh has vertex groups (Flood and Weights from Bones in Weight Paint Mode, Smooth, Normalize All, Limit Total, Clean, Mirror Weights); Transfer Weights; Weight Table of the selected vertex (Normalize) |
| Drive tab | Shape Keys (Add Basis Shape, then the list, value, Add, From Mix, Reset Values, Mirror Shape); **Driven Key**; the drivers of the active object with a button for the Drivers editor |
| Test tab | Reset Pose, Reset Selected, Clear Location / Rotation / Scale, Copy / Paste / Paste Flipped; Rest / Pose position and Apply Pose as Rest Pose; **Range of Motion** (Make Test, Remove); Pose Library (Save Pose, the saved poses with Apply and Flipped, the viewport's pose shelf); **Check Rig** (also in Object Mode) |
| Collections tab | Bone Collections (the tree with show / hide, assign, select; Show All / Unsolo All while a collection is hidden / soloed), Selection Sets (Pose Mode), Bone Colors, Bone Display |

The dock opens the tab that fits the mode when you enter it: Edit Mode the Skeleton tab, Pose Mode Controls & Constraints,
Weight Paint Mode Skin. A tab you pick yourself in a mode is what that mode opens on from then on (the Channel Box too), and a
dock on All Settings or the Channel Box is left alone. Every tab says what it needs (a skeleton, a mode, a mesh) with a button
that fixes it.

**Modes.** Edit and Pose act on the skeleton, so the buttons make it the active object (the mesh you were working on
stays selectable afterwards). **Weight Paint** acts on the mesh: the button makes the mesh active, keeps its skeleton selected
and puts the skeleton in Pose Mode, so a bone can be picked with Ctrl+click while you paint (tick "Paint Only the Selected
Bones" to restrict the brush to it). The influence list in the Skin tab picks a group without a bone click, and Object
Mode leaves both.

**Joint tool.** Click in the viewport to place joints; every click after the first adds a bone from the last joint, so three
clicks make a two-bone chain. Joints go on the view plane through the previous joint (the 3D cursor for the first one), or
on the surface of a mesh with Place: Surface (Inset pushes them into the mesh). A click close to an existing joint uses it:
on the tip of a bone the chain continues that bone, on the start of a bone it branches from the bone's parent. Enter or a
right click finishes, Backspace takes the last joint back, Esc takes the whole run back. With X-Mirror on, a chain placed
on one side is named .L (or .R) and gets a mirrored copy. The first use creates the skeleton. **Name** names the bones: a
list (`Shoulder, Elbow, Wrist`) names them in order, a name ending in a number counts up (`Arm_01.L`, `Arm_02.L` ...), any
other name is numbered by Blender (`Bone`, `Bone.001`). New bones rotate in XYZ Euler, not in quaternions (the "New Bones in
XYZ Euler" option in Controls > Locks; bones of opened files, keyed bones and Rigify rigs are left as they are).

**Names.** **Rename Chain** (Skeleton > Names) gives the selected bones the names of the Names field from the root of the
chain to its tip, with .L or .R when the chain is on one side; **Prefix, Find / Replace...** opens the batch rename for
bones. **Mirror** (+X to -X, the shelf, Skeleton > Mirror Joints, Shift+N) first names bones without a side by where they
are (`Arm` on +X becomes `Arm.L`), so the copies get the matching names, and says so.

**Orient Joint.** A bone's Y axis always runs from its start to its tip; Orient Joint chooses the roll. Pick which side axis
(Z or X) should point along a world direction (+Z by default), and every selected bone (all bones if none) rolls so that axis is
as close to the direction as the bone allows. A bone that runs along the direction itself uses -Y instead (+Z for a bone along
Y). With X-Mirror on, Blender gives the opposite bone the mirrored roll.

**Control shapes.** The shape buttons make a wire mesh (WGT-Circle, WGT-Square, WGT-Arrow, WGT-Cube, WGT-Sphere) once, keep it
in a hidden Widgets collection, and use it as the custom shape of the selected bones, at the chosen scale and in the picked
color (selected and active bones are drawn lighter). No Shape removes it.

**IK with Pole.** With the end bone of a limb active in Pose Mode, **IK with Pole** adds an IK constraint over the chosen
number of bones, a target bone at the tip (IK_name) and a pole target bone out from the middle joint (Pole_name), and searches
the pole angle so the limb bends toward the pole. Move the target to pose the limb and the pole to turn the bend.
**Pole Vector** (Constrain menu or the IK panel) makes another bone, or an object, the pole of an IK you already have:
select the pole, then the bone with the IK.

**Constraints.** The **Constrain** menu (Rigging menu set), the Add Constraint buttons and the Rigging shelf constrain the
active bone in Pose Mode (select the target bone first) and the active object otherwise (select the target object first).
With **Keep Offset** (on; Controls tab and the Constrain menu) Parent (Child Of), Point (Copy Location), Orient (Copy
Rotation), Scale and Copy Transforms keep the bone or object where it is and add the target's moves from there; off, it
jumps onto the target. Between two bones in the rest pose the bone's own channels stay at rest. IK Handle, IK with Pole
Target and Pole Vector are in the menu in Pose Mode; **Remove Constraints** clears the selected bones (Pose Mode) or objects.

**Rotate Order.** The Channel Box and Controls > Locks have a **Rotate Order** row (XYZ ... ZYX, Quaternion, Axis Angle) for
the selected bones or objects. It keeps the pose and turns the rotation keys into keys of the new order on the same frames
(between keys the curves may take a slightly different path). The Euler filter says when channels are in quaternions (it
cannot filter those).

**Bind.** Select the mesh (and the skeleton if the scene has more than one) and press Bind. Automatic weights that leave
vertices without any weight, usually a mesh with holes or overlapping parts, are replaced by envelope weights and the tab
says so; close the holes and merge doubles for better weights. Empty Groups makes a group per bone with no weights for
hand painting. Mirror Weights copies the weights of one side of a symmetric mesh to the other (the .L groups fill the .R groups).
Smooth works on selected vertices (Edit Mode, or Vertex Select in Weight Paint Mode). Bind runs Check Rig and says what it
found.

**Weights add up to 1.** Paint Weights on a bound mesh turns **Auto Normalize** on (the Weight Paint panel has it with
Multi-Paint and Lock-Relative): painting one bone takes the weight from the others. The Weight Table's **Set** and remove do
the same with Normalize on: the vertex's other unlocked bone weights are scaled so they add up to 1 (locked ones keep theirs).
**Select Weighted Vertices** (Influences) selects the vertices of the active influence (the bone picked with Ctrl+click while
painting) above the threshold, in Weight Paint Mode with Vertex Select or in Edit Mode.

**Check Rig** (Test tab; Bind runs it too) looks for what goes wrong at bind or export, each with a fix: rotation or scale not
applied on the skeleton or its meshes (Apply Rotation and Scale; they stay where they are), a skeleton out of its rest pose
(Reset Pose), bones in quaternions (Make Them XYZ Euler, keys kept), controls that deform (Deform Off), vertices without bone
weights (Select Them, in Edit Mode), vertices with more influences than Max Influences (Limit), weights that do not add up to
1 (Normalize) and naming problems (Select Them). Run it before exporting a rig.

**Range of Motion** (Test tab): **Make Test** turns the selected bones (every deforming bone when none) by the Angle each way
around X, then Y, then Z (10 frames a pose), on an NLA layer of its own ("ROM Test"); play it to watch the skin deform.
**Remove** takes the layer and its action away and puts those bones back. The skeleton's own animation is left alone (an
active action on the same bones plays over the test).

**Driven Key.** Pick the driver channel (an object or bone transform, or a custom property) and the driven channel (a
transform, a custom property, or a shape key). Pose the driver, type the Driven Value the other channel should have there and
press **Key**; repeat for each pair. It makes an ordinary driver whose curve is keyed with those pairs (Smooth, Linear
or Stepped), so the Drivers editor shows and edits it; the driven channel holds the end values outside the keys. A
bone in Quaternion mode switches to XYZ Euler when it is used as a rotation channel.

**Naming check.** The Names panel lists bones with a side name but no partner (`Arm.L` without `Arm.R`), a name on the wrong
side, a bone that mirrors a sided bone by position but has no side, and numbered duplicates (`Bone.001`, `Bone.001.L` next
to `Bone.L`), with a button that selects them.

**Rigify** ships with Blender and stays off until the Generate Rig panel is opened and **Enable Rigify** is pressed; then it
offers a human meta-rig and Generate Rig. If it cannot be turned on the panel says why.

Keys: Ctrl+E extrudes a bone in Edit Mode, P / Shift+P parent / unparent bones, Shift+N opens the naming marking menu (Name
Sides, Flip Names, Mirror, Select Mirror, Select Problem Names) in Edit and Pose Mode.

## Animation (F6)

F6 opens the Animation workspace (in Pose Mode when a skeleton is active; with a bound mesh active or selected its skeleton
becomes the active object and enters Pose Mode). Left: a camera view (the scene camera; the view says
so when there is none and the Channel Box tab offers New Camera from View). Middle: the large viewport. Bottom: one editor that is the
Dope Sheet or the Graph Editor (the **Graph / Dope Sheet** buttons in the Status Line, Ctrl+Space maximizes it; it shows the keys of
the selected objects and bones) with the Time Slider under it: one row of playback controls, the Time Slider's (the editor's own
row and its sidebar are off; View > Sidebar or N opens the sidebar). Right: the dock. While the animation plays only the viewports and the animation editors redraw, so the dock does not
slow playback (it catches up when you stop).

| Part | Contents |
|---|---|
| Status Line | Object / Pose, **Auto Key** (+ its options: replace or add keys, only the active keying set, layered recording), key type (Keyframe, Breakdown, Extreme, Moving Hold), **New keys** (Stepped, Spline, Linear, Clamped), Blocking / Polish (+ whose keys: Selection, Whole Character, Scene), **Key: Selected / Character**, keying set, playback range (start / end, preview range button), frame rate dropdown, loop mode, Graph / Dope Sheet, Playblast |
| Shelves | Animate (Set Key, Translate / Rotate / Scale keys, Breakdown, Delete Key, Euler Filter, Stepped, Spline), Poses (Copy, Paste, Paste Flipped, Mirror Pose, Reset, Save Pose, Apply Pose menu), Custom |
| Channel Box tab | The active object's channels, or in Pose Mode the **active bone's** channels (translate, the rotation of its mode, scale), with its custom properties as sliders (IK / FK switches); animated channels are coloured as usual (yellow = key on this frame, green = animated) |
| Pick tab | **Controls** (Pose Mode): Select All Controls, Set Key keys Selected / Character, and for a generated (Rigify) rig its **Rig Controls** (IK / FK switches, snapping: the panel its script adds to the viewport sidebar); bone selection sets of the skeleton (list and one button per set), **object selection sets** (made from the selection; a click selects, Shift-click adds), bone collection picker (visibility toggle and a button that selects the collection's bones) |
| Tween & Poses tab | Tween slider with 0 / 25 / 50 / 75 / 100 buttons, Key and Revert; Push, Relax, Breakdown, To Neighbor, To Rest (Pose Mode); Copy / Paste / Flipped, **Mirror**, **Mirror All**, **Mirror Anim**; World Position Copy / Paste (this frame or over the playback range); Save Pose, the saved poses with Apply and Flipped |
| Motion tab | Motion paths (show, range, frame step, Calculate, then Update / Clear, Frame Numbers / Key Numbers, show in the viewport) of the selected bones or objects; Ghost Curves for the Graph Editor |
| Layers tab | Layers are NLA tracks: Push Down, Add Additive Layer, the tracks (mute, name, solo, Edit, remove; under each its **Weight** and frames), the top action's blend and influence, Bake |
| Playback tab | Range (start, end, preview range, **Frame Rate**, Range from Keys, Scene from Keys), Blocking / Polish (+ Convert: Selection, Whole Character, Scene) and the new key defaults, loop, pre-roll, sync, Playblast (Movie / Images, range, folder, size, Meshes Only, Burn-in, play when done) |

**Tween.** With keys before and after the current frame, Tween sets the selected bones (Pose Mode) or objects to a value
between the previous and the next key of each keyed channel and keys it as a breakdown. Alt+Q starts it in the viewport:
move the mouse left and right (400 px is the whole way from the previous to the next key, 0.5 is the start; Ctrl snaps to
tenths, Shift is slower), click or Enter keys it, Esc or right click puts everything back. In the dock the slider moves the
selection live and **Key** keeps it (**Revert** drops it); the number buttons key straight away. Alt+Shift+P, R and B run
Push, Relax and Breakdown (Blender's own, Pose Mode).

**Set Key.** S, the shelf's Set Key, the Key menu and the keyframe marking menu (Shift+S + left click) follow one rule: they
key the unlocked translate, rotate (in the bone's or object's rotation mode) and scale channels and the numeric custom
properties (IK / FK switches) of the selected bones in Pose Mode, or of the selected objects; locked channels are skipped.
Translate / Rotate / Scale (Shift+W / E / R) key only those. **Key: Character** (Status Line, Pick tab) makes S in Pose Mode key
every control of the character: the bones you can see (not hidden, not in a hidden bone collection). Keying a mesh that is
bound to a skeleton warns: its object transform moves the whole mesh away from the bones that pose it.

**Tangents.** Stepped, Spline, Linear, Clamped and Flat (the Animate shelf, Shift+S + middle click) change the keys selected
in the Graph Editor or Dope Sheet among the selected bones' (or objects') channels, else every key of those channels; the other
bones are left alone. Clamped never overshoots between keys.

**Blocking and Polish.** Blocking makes new keys stepped, converts keys to stepped and shows the Dope Sheet. Polish makes new
keys clamped splines, converts keys and shows the Graph Editor. Whose keys they convert is the dropdown beside them: the
**Whole Character** (every bone of the skeleton in Pose Mode; the selected objects and their skeletons in Object Mode; the
default), the **Selection** or the **Scene**. The **New keys** buttons only change the default. That default is a Preferences
setting, so it applies to every file and stays until you change it (and a key set between two others copies the key before it,
which is why Blocking / Polish convert keys too). **Restore My Defaults** (Playback tab) puts back what the preferences had
before the first change.

**Frame rate.** The frame rate dropdown (Status Line, Playback tab) offers 23.976, 24, 25, 29.97, 30, 48, 50, 60 and 120 fps
(23.976 and 29.97 are 24 and 30 / 1.001). When the file has keys it asks: **Keep Timing** moves the keys (and the layers, the
scene end, the preview range and the markers, around the scene start) so the animation plays at the same speed; **Keep
Frames** leaves them on their frames, so it plays faster or slower.

**Mirror.** **Mirror** gives the selected bones' pose, mirrored left to right, to the bones of the other side (named .L / .R,
Left / Right ...); with both sides selected they swap, a middle bone mirrors itself. **Mirror All** flips the whole pose. With
Auto Key on, the changed bones are keyed. **Mirror Anim** puts the selected bones' keys, mirrored, on the other side's channels
half a cycle later (half the action's length, wrapping round), for walk and run cycles. **World Position** Copy remembers where
the active bone or object is in the world, Paste puts the selected ones there (keeping their scale); Copy Range / Paste Range do
it for every frame of the playback range and key it.

**Layers.** The Layers tab uses the NLA: Push Down puts the current action on its own track; Add Additive Layer pushes it down
and starts an empty action on top that adds to the layers below, so a pass of polish keys goes on its own layer. Edit enters
tweak mode on a layer, Done Editing leaves it, and the layer grows to keys set past its ends. Each layer has a **Weight**
(0 to 1; S over it keys it, so a layer can fade in and out). Bake flattens the selection over the playback range into one action.

**Playblast.** Renders the viewport (the camera view when the workspace has one) for review, into a **Movie** (H.264 .mp4 with
the scene's sound, the default) or **Images** (a PNG per frame), and opens it in the player. The Playback tab sets the range
(the playback range, i.e. the preview range when it is on, or the scene range), the folder (default the project's playblasts folder, without a project a temporary one; the folder
button beside the frame range opens it), the size as a percentage, **Meshes Only** (no bones, controls, grid or other overlays;
on by default) and **Burn-in** (the frame, camera, file name and date on the pictures). Each playblast is a new version named
after the file (`shot_v001.mp4`, `shot_v002.mp4` ...), never replacing an earlier one. Esc cancels images (a movie is written in
one go). Your render output settings (path, format, size, frame range, burn-in) are put back afterwards.

Keys: S sets a key, Shift+W / E / R key translate / rotate / scale, Alt+V plays, `,` and `.` jump between keys, Alt+, and Alt+.
step a frame, Shift+S is the keyframe marking menu (+ middle click: tangents; Object and Pose Mode), Z / Shift+Z undo / redo
with the pointer over any editor, Ctrl+Left / Right jump to the start / end, **Alt+Q Tween**,
**Alt+Shift+P / R / B Push / Relax / Breakdown** (Pose Mode).

## Rendering (F7)

F7 opens the Rendering workspace. Left: a 3D view in Material Preview (the Status Line's **IPR** button turns it into the
Rendered viewport and back; Rendered re-renders as you work, which is heavy on a slow PC, so it starts off). Middle: the
**Render View** (an Image Editor showing the Render Result: renders land here, not in a new window; until the first render it says
how to render, Shift+F12). Right: the dock.

| Part | Contents |
|---|---|
| Status Line | Engine (Cycles / EEVEE), scene camera picker, quality preset (**Draft / Medium / Final**, the name of your own preset, or Custom once you edit a value), **Render**, **Render Animation**, **IPR**, **Render View** / **Shader Graph** (what the middle area shows; Modeling's Status Line has the same Render View, Render and IPR buttons) |
| Shelves | Lights (Point, Spot, Area, Sun, HDRI Sky, Previous World), Render (Render, Animation, Render View, Background, Camera from View, Turntable, Look Through, Draft / Medium / Final), Custom |
| Render menu | Render Current Frame, Render Sequence, IPR, Render View, Shader Graph, **Render Sequence in Background**, **Export Render Job...**, **Create Turntable** (or with the sky turning), **Remove Turntable**, Camera from View, presets, engine |
| Camera tab | Scene camera, **New Camera from View**, Match Camera to View, Look Through Camera; focal length (or ortho scale), clip range; depth of field (focus object or distance, f-stop, blades); resolution X / Y / %; safe areas and composition guides; render border (Set / Clear) |
| Lighting tab | Add Light buttons, the **Light Editor** (one row per light: viewport eye, render toggle, name, color, power, shadow, shared-data button, select), **HDRI Sky** (Blender's studio HDRIs, or your own file; rotation, strength), exposure and gamma |
| Materials tab | The active object's material slots (Assign New Material for an object without one; with a camera, a light or nothing selected, the objects that can have one) and the Principled inputs (base color, metallic, roughness, emission color / strength, normal strength when a Normal Map or Bump node feeds it); **Edit Graph** (the shader graph in the Render View's place); **Scene Materials** (below) |
| Render tab | Engine and quality presets with **Your Presets** (the menu beside them), then the engine's settings: Cycles device (with "GPU found: ... **Use GPU**" while it renders on the CPU), samples, noise threshold, time limit, denoising; EEVEE samples, ray tracing, shadows. With high poly / low poly pairs in the scene, **High / Low Poly**: **Low Poly** or **High Poly**, which mesh of each pair renders (see High poly and low poly) |
| Output tab | Path (`//render/` in a new file: a render folder next to the saved file), **Type**: **Image Sequence** (format, color mode and depth), **Multilayer EXR** (every pass and render layer in one file per frame; depth, compression) or **Video** (container, codec, quality), Overwrite Existing Frames, **Keep Each Render**, **Save Each Still**, frame range, FPS, Render / Render Animation, **Render in Background** (and Export Render Job beside it), **Open Render Folder**, color management (view transform, look, exposure, gamma) |
| Passes & Layers tab | **Render Layers** (picker, Render This Layer, **New Render Layer from Selection**), passes (data, light, Cryptomatte, shadow catcher), AOVs, light groups, **Collections in This Render Layer** (**In Layer**, **holdout** and **indirect only** per collection), light linking and shadow linking for the active object, shadow catcher and holdout flags |
| Advanced tab | Light paths (Cycles bounces and clamping; EEVEE fast GI), film (transparent background, filter, motion blur), performance, simplify |

**Quality presets.** Each preset sets both engines at once and the size, so switching engine keeps the preset. Draft: Cycles 32
samples, 4 bounces; EEVEE 16 samples, no ray tracing; half size. Medium: Cycles 128 samples, 8 bounces; EEVEE 64 samples, ray
tracing at half resolution. Final: Cycles 512 samples, 12 bounces; EEVEE 256 samples, full ray tracing, 2 shadow rays. All
use denoising and adaptive sampling in Cycles. A new file starts at Medium. The Status Line and the Render tab show **Custom** as
soon as you change one of those values (or the size); the preset buttons put them back. A preset also makes Cycles render on the
GPU when there is one that passes a short test bake (the same test as Bake Mesh Maps). **Your Presets** (the menu beside the
presets, and the Render menu): **Save as Preset...** keeps the current samples, bounces, ray tracing and size of both engines
under a name of yours (for every file, in `m3d_user.json`), a click applies one, **Delete Preset** removes one.

**Render and Render Animation.** The first render from a camera you cannot see (the hidden *persp* camera of a new scene) while
the view does not look through it asks: **Match Camera to View** (moves the camera to the view, then renders) or **Render
Anyway**, with **Don't ask again**; it asks once per camera in a session. Render Animation in a file that was never saved (with a
`//` path) opens Save As first: the frames go into a folder next to the file. A path that is only a folder (`//render/`) gets the
scene's name, so the frames are `Scene_0001.png` ... When frames of the range are there already it asks: **New Version Folder**
(the next free `v002`, `v003`... folder) or **Overwrite**. When it is done the status bar and a popup say how many frames went where,
with **Open Folder** (the Output tab has **Open Render Folder** too).

**Passes.** Passes other than Combined (and Cryptomatte, AOVs, light groups) are saved only in a Multilayer EXR: the Passes and
Output tabs say so while the output is another type, with **Switch Output to Multilayer EXR**.

**Render layers.** A render layer is Blender's view layer. **New Render Layer from Selection** makes one with the selected objects
and the scene's lights: they go into a new collection of their own (they stay in theirs too) and every other collection is left
out of the new layer, which the window then shows (objects in no collection are in every layer: it says so). **In Layer** in
Collections in This Render Layer puts a collection in or out of the layer shown.

**Light Editor.** Every light of the scene is a row, including lights in hidden or excluded collections (greyed). The eye shows
or hides the light in the viewport, the camera icon in the render. A light whose settings are shared with other lights shows
**xN**: editing one changes them all, and clicking it gives that light its own copy. The arrow selects the light (not possible
for a light in an excluded collection).

**HDRI Sky.** Picking an HDRI (or **HDRI Sky** on the shelf) assigns a new world called *m3dHDRI* (Texture Coordinate, Mapping,
Environment Texture, Background). The world the scene had is kept and **Back to Previous World** puts it back. Rotation and
strength edit the Mapping and Background nodes. F7's 3D view shows the sky in Material Preview too (Back to Previous World
returns it to the studio light) and in Rendered shading. F7's Material Preview is lit by the scene's lights as well; the Lighting
menu of a 3D view switches: **Use Default Lighting** (studio light only), **Use Flat Lighting**, **Use All Lights** (Material
Preview with the scene's lights).

**Camera from View.** Adds a camera at the current viewport view (with the viewport's field of view) and makes it the scene
camera; **Match Camera to View** moves the scene camera to the view instead.

**Render snapshots.** With **Keep Each Render** on (the default; Render View header and Output tab) every still goes into a slot
of its own in the Render View, named with the time, the preset and the engine ("14:32 Medium EEVEE"), so the renders before stay
for the session. **Left / Right** or **J / Shift+J** over the Render View flip through them (the slot dropdown in its header too),
**A/B** flips to the render shown before and back. After 16 slots the oldest render makes room. **Save Render...** in the header
saves the render shown. **Save Each Still** (Output tab, off by default) saves every still as `render/stills/<scene>_v001.png`,
`v002`... next to the saved file. Renders are not kept in the file.

**Shader Graph.** **Shader Graph** on the Status Line (or **Edit Graph** in the Materials tab, Render > Shader Graph) shows the
active object's material as a node graph in the Render View's place; **Render View** (or a render) brings the render back. The
area keeps what it shows, so each Rendering workspace remembers it. Shader Editor windows (Windows menu, the Modeling Status Line)
open once: clicking again brings that window to the front instead of opening another.

**Scene Materials** (Materials tab; Lighting/Shading > Scene Materials). Every material of the file as a grid of previews
(Maelstrom3D's own, such as the UV checker, are left out). Click one to pick it: **Assign to Selection** (the selected faces in
Edit Mode, else the selected objects, as Assign Existing Material), **Select Objects Using**, **Duplicate**, **Rename**. **New**
and **Duplicate** make materials that are kept when the file is saved even before an object uses them. **Delete Unused** deletes
the materials no object uses (it asks first).

**Render in the background.** **Render Sequence in Background** (Render menu, shelf, Output tab) saves a copy of the scene (unsaved
changes included) and renders its animation in another Maelstrom3D at low priority while you go on working. It asks the same
questions as Render Animation (save first, New Version Folder / Overwrite). The status bar shows the progress with **Cancel** and
the folder button; when it is done it says how many frames went where. **Export Render Job...** saves a copy of the scene and a
script beside it (`.bat` on Windows, `.sh` elsewhere) that renders the animation with this Maelstrom3D: run it later, or overnight.

**Turntable.** **Create Turntable** (Render menu and shelf, Sculpt's Display tab) puts a pivot at the centre of the selection (or
of everything visible) with a new camera on it that frames the model, and turns it once around over the frame range at an even
speed (the loop has no repeated frame). It becomes the scene camera. **Sky Around** keeps the camera still and turns the HDRI sky
instead (one is added when there is none). Then **Playblast** (keeps the viewport's look, a matcap in Sculpt) or **Render
Animation**. **Remove Turntable** deletes its camera and pivot and puts the scene camera and the sky back.

Keys: **Shift+F12** renders the frame, **Ctrl+Shift+F12** the animation, **Alt+F12** shows the last render (F12 itself is the
UV workspace in Modeling). Esc cancels a render.

## Pipeline: projects, import, references, export

**Projects.** **File > New Project...** picks (or makes) a folder and puts `scenes`, `sourceimages`, `images`, `playblasts`, `export`
and `cache` in it; **Set Project...** uses a folder as it is; **Recent Projects** switches back (No Project goes without one). The
project is kept in `m3d_user.json` with the recent ones, so it is there the next time. With a project, Open Scene, Save Scene (a
scene not saved yet), Import and Create Reference start in `scenes`; a new scene renders into `images` and exports its textures
into `export`; playblasts go into `playblasts` and Export to Engine into `export`. The tooltips of Open and Save in the Status
Line name the project; Ctrl+O, Ctrl+S and Ctrl+Shift+S do the same.

**Import.** **File > Import...** is one file picker for FBX, OBJ, glTF / GLB, USD (usd, usda, usdc, usdz), Alembic and scene files
(.blend: their objects come in a collection named after the file); the importer follows the extension. OBJ and Alembic files carry
no units: **Studio (centimetres, Y up)** in the picker's side bar reads them as centimetres (a 100-unit cube comes in 1 m, not
100 m), **Metres** as they are; the choice is remembered. FBX, glTF and USD say their units and axes themselves. **Import from
Scene File (.blend)...** is Blender's Append (pick what to bring in), **Import Other Formats** the importers with all their
options. The Sculpt start card's Import... is the same picker.

**References.** **Create Reference...** (Ctrl+R) brings the collections of another scene file in, linked to it: an edit of that
file shows up here on reload. Its skeletons are editable at once, so a referenced character can be posed and keyed right away; the
rest follows the file. **Windows > Reference Editor** lists the referenced files: the path (red with "Missing" when the file is not
there), **Reload**, **Replace** (another file; the same names are matched up), **Unload / Load** (out of the scene for now and back),
**Remove**, **Make Editable** (every object of the reference; a collection linked with Blender's Link becomes one too), **Import
Objects** (they become the scene's own and no longer follow the file) and **Make Relative / Make Absolute**. Reload and Replace say
when keyed bones are gone in the new file ("keys of bones that are gone: Arm").

**Export to Engine.** **File > Export to Engine...** (also in the Texturing Export menu, the Export Textures dialog, F6's Key menu
and the Animation Playback tab) writes what a game engine needs in one pass. Pick the **Engine**: **Unreal Engine** (FBX in
centimetres, the skeleton named Armature so Unreal adds no extra root bone, textures with the Unreal template), **Unity** (FBX with
the scale and, without a skeleton, the axes applied, so the object comes in at scale 1 without a rotation; Unity URP or HDRP
textures) or **glTF** (a .glb with the meshes, materials and textures). **Meshes**, **Textures** and **Animation** turn each
part on or off.

- **Meshes:** the low polys and the plain meshes that are visible (parked low polys too), or the selected ones (**Selected Only**);
  a high poly or a cage is never written. A file for each mesh, or for each skeleton with the meshes it deforms (**One File**: all
  in one). A mesh is named after its group without the role suffix (Crate_low: Crate), after the **Prefix** (SM_, SK_), and so is
  its file. Modifiers are applied with Smooth Preview off, smoothing groups written, **Triangulate** on by default, **Move to
  Origin** puts each file's skeleton (else first mesh) at the world origin; exploded groups are written where they belong.
- **Textures:** the texture sets of those meshes, with the file type, size and padding of Export Textures and the engine's
  template (a Unity project on HDRP keeps HDRP), into the same folder.
- **Animation** (Unreal, Unity): the skeletons of the meshes. **Clips**: **What Plays** (every layer, over the playback range, the
  scene range or the keys) or **Each Action** (the skeleton's action and its layers' actions, each over its keys), in one file with a
  take for each clip or **A File per Clip** (`Hero_Walk.fbx`). Each clip is baked to a key on every frame as it plays (constraints
  and layers included), deforming bones only, no leaf bones, in the engine's units. **Root Motion** moves the hips' motion over the
  ground to the root bone above them (it needs one); **In Place** takes it out. The dialog runs Check Rig first and lists its
  problems, with the root bone's.

The folder is the project's `export` (else an `export` folder next to the saved scene, or one you pick). The settings are kept
with the scene; **Repeat Last Export** (File and Export menus, the Repeat button) writes everything again in one click.

## Sharing files

**Textures not found.** When a file opens and some of its textures are not where it says, the status bar shows "**N textures
not found**" with **Find Missing Files...** (pick a folder: they are looked for in it and below), **Show List** (each texture and
the path it was looked for at) and **X** to close the note. Blender's studio HDRIs (HDRI Sky) are found again by name when the
file comes from another computer or another install.

**HDRI paths.** An HDRI of your own is stored relative to the saved file (`//textures/sky.exr`), so the folder can move as a
whole; the studio HDRIs keep the path of the install (found again by name, see above).

**Save Copy for Sharing...** (File menu) saves a copy to send to someone, and leaves the scene you work on as it is: **Pack Into
the File** puts the textures into the `.blend` (one file to send), **Keep Beside It** stores their paths relative to the copy
(send the folder). A note then says what was packed, which textures were not found or have unsaved edits, and what stock Blender
doesn't show: the file opens in Blender 5.2 or newer, but its docks show Maelstrom3D's own tabs (Channel Box, toolkits) that
stock Blender draws empty, so open it there with **Load UI** off (File > Open, the gear menu); the scene, materials, lights and
render settings are plain Blender, Maelstrom3D's own settings (render presets, texture sets, layers) are kept but not used.

## Customising the interface

**Small screens.** On a window narrower than the layouts were made for (1366 x 768, say), the Sculpt tray and dock, the Rigging bone collections
page and the Texture workspace's Assets column and right column (Texture Sets, the dock, Properties) keep the width their panels need, and the
Texture Set List the height of its start card; the views give up the room. This happens when the window gets a new size or shows
another workspace, so a column you drag narrower afterwards stays so. Rows that still do not fit show icons (their tooltips say the
name and key), hints go on more lines, the Assets grid takes fewer columns so the names show, and the dock tabs that do not fit
are in the » menu.

**Settings > Click to Edit** (it then reads **Editing**; click again to leave) turns on the interface edit mode for every workspace. It is off whenever the app starts and is not saved in files. While it is on:

- **Shelf buttons.** Press a button and drag it. Drop a Custom shelf button between two others to reorder, off the shelf (anywhere else) to remove it, or drag a button of any other shelf onto the **Custom (drop here)** tab (right end of the tab row) to copy it into this workspace's Custom shelf. Esc cancels a drag; a click without moving does nothing. In the Sculpt tray's Custom panel (Sculpt hides its shelf rows) each button has move / remove arrows instead. Right-click > Add to Shelf works as before.
- **Shortcuts.** Hold **Ctrl+Alt**, hover a button and click it, then press the key (with any modifiers) that should run it. A prompt shows while it waits (Esc cancels); if the key is already used in the same keymap you are told what by and Enter assigns it anyway. Operator buttons and on / off toggles get the shortcut (the top bar, shelves and docks use the Window keymap, buttons in an editor's own area that editor's keymap). It is saved in your keymap, so it shows (and can be changed or removed) in Preferences > Keymap. Entries of open menus and popovers are not reached this way: use Blender's right-click > Assign Shortcut there.
- **Dock panels.** Every panel of the docks (Modeling Toolkit, Sculpt / UV / Texture / Rigging / Animation / Rendering tabs) gets a **move to tab** menu and an **eye** in its header. Hidden panels stay in the list, dimmed by the closed eye, while editing. The dock's tab row has **+** to make your own tab (name it, then move panels into it) and, on one of your tabs, rename and delete (its panels go back to their own tabs). Your tabs show in the tab row, the overflow menu and Workspace Settings. Dragging panels to reorder them within a tab works as in Blender.
- **Settings > Reset Dock Layout** puts the dock of the workspace back to the defaults (your tabs, moved and hidden panels, hidden tabs). Everything is stored per workspace kind in `m3d_user.json` in the user config folder; a damaged file reads as empty. Code: `m3d_edit.py`, `m3d_user.py`, `m3d_workspace.py`.

## Terms used

Attribute Editor = Properties editor · Shader Editor = shader node editor (Shading workspace) · Construction history =
modifiers ("INPUTS" in the Channel Box) · Freeze Transformations = Apply Transforms · Group node = Empty ·
Display layers = Collections (Layer Editor) · Blender is Z-up (Maya is Y-up); units are metres.

## Known differences

- Dock tabs are icons with tooltips, not vertical text labels.
- Target Weld merges at the last-selected vertex instead of dragging one vertex onto another.
- Shift+drag on the Move manipulator extrudes along the grabbed arrow or plane (the centre extrudes along normals); on the Scale manipulator it extrudes and scales along the handle (the centre scales uniformly); on a Rotate ring it extrudes and rotates about that axis. The view ring and the trackball extrude along normals.
- Blender's Item / Tool / View tabs still exist in the viewport sidebar (closed at startup; Ctrl+] or Display > UI Elements > Sidebar opens it).

## Command line (MEL and Python)

The command line at the bottom of Modeling speaks MEL, like Maya's:
`polyCube -w 2 -n box; move -r 0 0 1; setAttr box.rotateZ 45; select -cl;`.
**Windows > Command Line** shows or hides a one-line command line under the 3D view of any workspace (Rigging, Animation...).
The command line is one line high, so it shows only the prompt (a taller one, or a Command Line editor, has an example line
over it; the tooltip of Windows > Command Line: MEL has the example too); results (`Result: pCube1`) and errors also show
in the status bar. `help` lists the commands; a command that isn't there says "'X' isn't supported yet. Type help for the
list." `file -new` and `file -o <path>` refuse while the scene has unsaved changes (`file -s` saves; `-f` discards them).
Windows > Command Line: Python switches to Python, where `cmds` is ready (`cmds.polyCube(w=2)`), and scripts can
`import m3d.cmds as cmds`. Supported commands: polyCube/Sphere/Cylinder/Cone/Plane/Torus, polySmooth, spaceLocator,
group, parent, duplicate, delete, select, ls, move, rotate, scale, xform, setAttr, getAttr, rename, objExists, hide,
showHidden, makeIdentity, currentTime, playbackOptions, setKeyframe, file, undo, redo. Blender is Z-up, so a cube's
"height" runs along Z (a plane's along Y).

Primitive inputs are flags and attributes: `polyCube -w 2 -h 1 -d 3 -sx 4 -sy 2 -sz 1` (subdivisions width / height /
depth), `polySphere -r 2 -sa 24 -sh 12`, `polyCylinder -r 1 -h 3 -sa 16 -sh 4 -sc 2` (axis / height / caps; caps 0 =
open, 1 = one n-gon), `polyCone` (same), `polyPlane -w 4 -h 2 -sx 8 -sy 4`, `polyTorus -r 2 -sr 0.5 -sa 32 -sh 16`
(`-sx` / `-sy` / `-sz` work too). Afterwards `setAttr box.subdivisionsWidth 6;` and `getAttr box.width;` read and
rebuild them (attributes: width, height, depth, radius, sectionRadius, subdivisionsWidth / Height / Depth / Axis / Caps)
until the mesh is edited; `delete -ch` clears them. Subdivisions go from 1 to 200.

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
