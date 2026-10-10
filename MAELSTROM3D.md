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
| Layout | Modeling: Outliner left, Attribute Editor dock right, Time Slider and Command Line bottom. Workspaces (F1-F7 are the first seven): Modeling, Sculpt, UV, Texture, Rigging, Animation, Rendering, Shading, Compositing, Node Editor, Script Editor | `release/datafiles/startup.blend` (from `tools/m3d/build_startup.py`) |
| Top rows | Four stacked rows: menu bar (menu set dropdown + File/Edit/Create/Select/Modify/Display/Windows + menu-set menus + Help), Status Line (with "Workspace:"), shelf tabs, shelf buttons | `screen_edit.cc`, `space_topbar.cc` (extra top-bar rows), `m3d_ui.py`, `bl_ui/space_topbar.py` |
| Shelf | Shelf tabs (Curves/Surfaces, Poly Modeling, Sculpting, Rigging, Animation, Rendering, FX, UV, Custom) and large buttons in the top rows; every workspace has a Custom tab (right-click any button, Add to Shelf) | `m3d_ui.py`, `m3d_user.py` |
| Workspace Settings | **Settings** button next to the workspace picker in the Status Line (top right, same in every workspace): Reset Workspace (back to its factory layout, asks first), show / hide each dock tab of the workspace (also in the dock's own tab menu), **Show Shelf** (the shelf tabs and shelf rows of the top bar, per workspace: on everywhere except Sculpt; when off the top bar is two rows and the viewport grows), **Click to Edit** (see Customising the interface), Reset Dock Layout, the workspace's entry mode, Keyboard Shortcuts (Preferences > Keymap), and **Save Layouts as Default** (saves every workspace's layout, and the open scene, as the startup file for new files; File > Defaults has Save Startup File and Load Factory Settings for all). Extra workspaces (Shading, Compositing...) show what applies | `m3d_workspace.py` (`M3D_PT_workspace_settings`), `m3d_ui.py` (`draw_workspace_picker`) |
| Viewport | Panel menus (View, Shading, Lighting, Show, Renderer, Panels) and panel toolbar only (Blender's menus under "..."), viewport HUD (camera name, axis triad) | `m3d_ui.py`, `m3d_hud.py`, `bl_ui/space_view3d.py` |
| Right-hand dock | Tabs on the right edge: Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, then the Attribute Editor tabs (Object, Modifiers, Material, ...). **Primitive inputs:** a polygon primitive (shelf, Create menu, marking menus, `polyCube` ...) lists its size and subdivisions under INPUTS in the Channel Box ("Cube inputs": width / height / depth and the divisions along each, radius and axis / height / cap divisions, torus section radius ...); changing one rebuilds the mesh at once (one undo step). Editing the mesh (components, applied modifiers, sculpting, Freeze Transformations with a scale) **freezes** the inputs: they turn grey with the note "Mesh edited: inputs no longer apply". **Delete History** (button there, or Edit > Delete All History, which also applies modifiers) clears them. Duplicates keep their own inputs. A rebuild resets UVs, face materials to the first slot (slots are kept) and keeps Shade Smooth | `space_buttons.cc`, `buttons_context.cc`, `DNA_space_enums.h`, `rna_space.cc`, `m3d_mode.py`, `m3d_inputs.py` |
| Editor names | Attribute Editor, Shader Editor, Script Editor, Command Line, Command History, Time Editor | `rna_space.cc`, `node_shader_tree.cc` |
| Marking menus | RMB, Shift+RMB, Ctrl+RMB in the viewport; RMB, Shift+RMB in the UV Editor; Space hotbox | `m3d_mode.py`, `m3d_uv.py` |
| UV editing | UV workspace (F3): dock tabs, Status Line and shelf for Cut/Sew/Unfold/Optimize/Layout, texel density, Auto Unwrap, UDIMs, checker map; sidebar UV Toolkit in other workspaces | `scripts/startup/m3d_uv.py` |
| Texturing | Texture workspace (F4): brush tray, paint channels, Bake, Export, Display, Status Line and shelves; paint layer stack, painted images are saved or packed with the file; a Library of materials (layer setups), mask presets, brushes, alphas and your own items | `scripts/startup/m3d_texture.py`, `scripts/startup/m3d_layers.py`, `scripts/startup/m3d_masks.py`, `scripts/startup/m3d_library.py` (data: `m3d_library_data.py`), `scripts/startup/m3d_bakegroups.py` (bake groups) |
| Rigging | Rigging workspace (F5): Outliner with the bone hierarchy and bone collections on the left, a large viewport, a dock of Skeleton, Controls & Constraints, Skin, Drive, Test and Collections tabs that follows the mode, Timeline that switches to the Drivers editor; Joint tool, Orient Joint, control shapes, IK with pole, bind with fallback, weight tools, Driven Key, naming check, Rigify on demand; Ctrl+E, Shift+N | `scripts/startup/m3d_rig.py` |
| Animation | Animation workspace (F6): a large viewport and a camera view, one bottom editor that switches between the Graph Editor and the Dope Sheet, a short Timeline, a dock of Channel Box, Pick, Tween & Poses, Motion, Layers and Playback tabs; Status Line with Auto Key, key type, new key interpolation, keying set, range, FPS, loop mode, Blocking / Polish, Playblast; Tween (Alt+Q), Push / Relax / Breakdown, object selection sets, motion paths, ghost curves, NLA layers, Playblast | `scripts/startup/m3d_anim.py` |
| Rendering | Rendering workspace (F7): a 3D view and a Render View, a dock of Camera, Lighting, Materials, Render, Output, Passes & Layers and Advanced tabs; Status Line with engine, camera, Draft / Medium / Final presets, Render, IPR; light table, HDRI sky, camera from view; Shift+F12 | `scripts/startup/m3d_render.py` |
| Title | Window title says Maelstrom3D | `wm_window.cc` |

## Everyday controls

| Key | Action |
|---|---|
| Alt+LMB / MMB / RMB | Tumble / Track / Dolly (RMB: drag right zooms in, left zooms out) |
| F / A (Shift: all views) | Frame selected / Frame all |
| Q W E R T | Select / Move / Rotate / Scale / Universal manipulator |
| Click, Shift, Ctrl, Ctrl+Shift | Select, toggle, deselect, add (click and drag) |
| RMB (hold) | Marking menu (see below) |
| Shift+RMB | Object mode: create primitives. Component mode: polygon tools |
| Ctrl+RMB | Convert selection (vertices, edges, faces, loop, ring, border, shell) |
| Shift+drag manipulator | Components: extrude, then move / scale / rotate along the grabbed handle. Objects: duplicate, then the same |
| Ctrl+Shift+drag manipulator | Slide components along their edges |
| Q / W / E / R / A / H (hold) + left click | Select / Move / Rotate / Scale / History / Menu set marking menus |
| Shift+S (hold) + left click | Keyframe marking menu |
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
| F1 / F2 / F3 / F4 / F5 / F6 / F7 | Workspace (and its menu set): Modeling / Sculpt / UV / Texture / Rigging / Animation / Rendering. The menu set dropdown also offers FX |
| F8, F9, F10, F11, F12 | Object/component toggle, Vertex, Edge, Face, UV workspace |
| Shift+F12 / Ctrl+Shift+F12 / Alt+F12 | Render the frame / the animation / show the last render |
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

## UV editing (F3)

F3, or F12 in component mode (or UV > UV Workspace), opens the UV workspace in Edit Mode: the UV Editor large on the left,
the 3D view (Solid, seams shown) on the right, and the dock with the UV tools. Names are Blender's own.

| Part | Contents |
|---|---|
| Status Line | Object / Edit Mode, UV Sync, select mode (Vertex / Edge / Face) and Shell select, Live Unwrap, Distortion (and its type), Checker, texture size |
| Shelf | Cut, Sew, Unfold, Optimize, Layout (large buttons), Auto Unwrap, Custom |
| Unwrap tab | Cut and Sew (Cut, Sew, Split, Merge, Auto Seams from shells), Unfold (Angle Based or Conformal, Fill Holes), Optimize (iterations), Layout (margin, rotation: none / 90 degrees / axis aligned / any), Pin (Pin, Unpin, Invert Pins, Select Pinned) |
| Arrange tab | Select (Shell, Grow, Shrink, Invert, Overlapping, Pinned), Transform (Flip U/V, Rotate 90, Align U/V, Straighten, Snap Together), Shells (Orient Shells, Match Scale) |
| Check tab | Checker map, Distortion (angle or area), Shaded UVs, Texel Density: texture size, target, **Read**, **Set**, **Match** |
| Create tab | Auto Unwrap (seam angle, margin), projections: Automatic, Planar, Cylindrical, Spherical, Camera-Based, Cube |
| UDIM tab | The UV Editor's image (New / New UDIM Image), tile list with Add, Remove, Fill, tile grid, Pack to Active / Closest Tile, Select Tile |

Typical flow: **Cut** the edges you want as seams, **Unfold**, **Optimize** if shells stretch (it is slow on dense
meshes, so it has its own button), **Layout**, then check Distortion and the Checker map and match the Texel Density.
**Auto Unwrap** does cut (at edges sharper than the seam angle), unfold and layout in one go; a smooth shape with no
sharp edge is projected instead. Buttons in the dock and shelf run in the UV Editor, so they work on the UV selection.
UV Sync (Alt+S) makes the UV Editor follow the 3D view's selection; with it off, only what is selected in the UV Editor
is used. Texel density is pixels per unit at the texture size in the Status Line: Read measures the selected shells
(nothing selected: the whole mesh), Set scales every selected shell about its centre to the target, Match scales
them to the shell of the active face.

Keys in the UV Editor: Alt+P Layout, Ctrl+Shift+U Unfold, Alt+C Checker, Shift+T Set texel density, Alt+S UV Sync.
RMB switches UV / Edge / Face / Shell, Shift+RMB has Cut, Sew, Unfold, Layout, Straighten, Orient, Optimize, Automatic.
F9-F11 change mode, Z undoes, Alt+MMB/RMB pan and zoom. The checker map is taken off before a file is saved (and put
back afterwards), so scene files never keep it.

A UV Editor opened in another workspace (Windows > UV Editor) keeps the old sidebar UV Toolkit with the same tools.
Difference from Maya: Blender stores cuts as seams, and shells split when you Unfold. Maya splits them as soon as you cut.

## Sculpt (F2)

F2 opens the Sculpt workspace and enters Sculpt Mode on the active mesh (with no mesh, the tabs offer to add a sphere).
Names are Blender's own.

| Part | Contents |
|---|---|
| Brush tray (left) | Open panels, essentials first: the active brush and its picker; a grid of 15 small brush tiles showing each brush's thumbnail (the name is the tooltip, the active brush is highlighted: Draw, Clay Strips, Clay, Smooth, Grab, Elastic Grab, Snake Hook, Inflate/Deflate, Pinch/Magnify, Crease Sharp, Flatten/Contrast, Scrape/Fill, Layer, Mask, Face Set Paint); **Size and Strength** (Size, Strength, Hardness, Add / Subtract, Mirror X/Y/Z); **Lazy Mouse** (toggle, Radius, Factor: Blender's Stabilize Stroke); **Stroke Type** (a tile with a little picture for each of Dots, Drag Dot, Space, Airbrush, Anchored, Line, Curve); **Alpha** (None, eight starter alphas, every alpha you loaded, and **Load Alpha...**). Closed panels: Alpha Settings (mapping, size, angle), Brush Settings, Falloff, Stroke Options, Cursor, Advanced, Custom (the Custom shelf; arrows to move / remove buttons while editing the interface) |
| Status Line | Object / Sculpt Mode; the brush controls (see below); the **Remesh** popover; face count, Multires level with Lower / Higher arrows, Dyntopo, Mirror X/Y/Z, Auto-Masking, Mask and Face Set overlays, the **Matcap** popover |
| Top bar | Only the menu bar and the Status Line: the shelf rows (Sculpt / Remesh / Mask / Custom tabs and the brush buttons) are off in this workspace because the tray and tabs have all of it, and the viewport gets the space. Turn **Show Shelf** on in Workspace Settings to bring them back |
| Geometry tab | Multires (Subdivide, Simple, Linear, level sliders, Delete Higher, Unsubdivide, Apply Base), Voxel Remesh, QuadriFlow, Dyntopo. Options that cannot work together (Dyntopo and Multires) are greyed with the reason |
| Mask tab | A big **Invert Mask** button, Clear, Fill, a line listing the Ctrl gestures, filters (Smooth, Sharpen, Grow, Shrink, Contrast), From Cavity / Boundary, Box / Lasso / Line / Polyline Mask, Mask by Color, Hide Masked / Show (with the Ctrl+Shift gestures listed) |
| Face Sets tab | Initialize (Loose Parts, Materials, Normals, UV Seams, Creases, Sharp Edges, ...), Create from Mask / Visible / Selection, Grow, Shrink, Fair, Delete Geometry, Show All, Randomize Colors |
| Deform tab | Mesh filters (Smooth, Inflate, Relax, Surface Smooth, Sharpen, Enhance Details, Sphere, Random, Scale), Symmetrize, Set Pivot, trim tools |
| Paint tab | Color brushes, color picker, palette, Add Color Attribute, color filters |
| Display tab | Matcap / studio light as a grid of thumbnails, color, cavity, Mask and Face Set overlay opacity, wireframe, low resolution and delayed updates |
| Objects tab | The scene's meshes: show / hide, pick, solo, append a duplicate; add a sphere, cube or cylinder |

**Status Line brush controls** (the top shelf of Sculpt): **Size**, **Strength** (the scene-wide sliders while Unified
Size / Strength is on), **Hardness** (how far from the centre the brush stays at full strength; the Falloff curve shapes
the rest), **Add / Subtract** (Brush.direction), **Lazy Mouse**
(toggle and Radius), and for a color brush the two colors and swap. The **Brush** popover has all of them plus the
Falloff curve and shape, Lazy Mouse Radius and Factor and the stroke type tiles. The **Remesh** popover has Voxel Remesh
(size, eyedropper, options, button), QuadriFlow (target face count, ratio or edge length, symmetry, sharp edges,
boundary, normals), Multires (Subdivide, Lower / Higher, the level sliders, Delete Higher, Unsubdivide, Apply Base) and
Dyntopo (toggle, detail size and method). On a window wider than about 2200 px the Hardness slider, the Lazy Mouse
toggle with its Radius, and the Voxel size with a **Remesh** button sit in the Status Line itself; on a narrower one
(down to about 1500 px) only the sliders and the Add / Subtract buttons do and the popovers have the rest. The **Matcap**
popover is the thumbnail grid of the matcaps (Studio and Flat are the other lights), plus color and cavity. There are no
RGB / material-only toggles: in Blender a color brush paints color attributes and a normal brush deforms, so the color
brushes' two colors are what the Status Line shows.

**Ctrl is masking** (Maya's Alt+mouse navigation is untouched; Ctrl no longer inverts a stroke). The gesture is decided
by what is under the cursor when you press and by whether you click or drag (more than the drag threshold):

| Input | On the mesh | Off the mesh (empty space) |
|---|---|---|
| Ctrl+drag | Paint mask (the Mask brush for this stroke, at the brush's size; your active brush stays) | Mask a rectangle (what you see; a tiny rectangle clears the mask) |
| Ctrl+Alt+drag | Erase mask | Unmask a rectangle |
| Ctrl+click | Smooth (blur) the mask once | **Invert the mask** |
| Ctrl+Alt+click | Sharpen the mask | Nothing |
| Ctrl+Shift+drag | Hide everything outside a rectangle (show only inside) | Same |
| Ctrl+Shift+Alt+drag | Hide everything inside a rectangle | Same |
| Ctrl+Shift+click | Show only the face set under the cursor (hide the others) | Show all |
| Shift+drag, plain drag | Smooth, the brush stroke (as before) | |

To subtract, switch the brush to Subtract: the buttons in the tray and the Status Line, or **N** in the viewport (a
sticky toggle). Esc or right-click cancels a gesture. The other Ctrl keys are as before: Ctrl+I invert mask, Ctrl+Shift+A
fill mask, Ctrl+H hide masked, Ctrl+A mask pie, Ctrl+W face sets pie, Ctrl+0-5 subdivision level, Ctrl+D voxel remesh,
Ctrl+RMB stencil; H / Shift+H / Alt+H hide the face set, isolate / show it, show all. Alphas: Blender's essentials
brushes are linked asset data, which can only use linked textures, so every alpha lives in the **alpha library** (one
.blend with its thumbnail per alpha, in the user data folder `datafiles/m3d_alphas`); the starter set is made the first
time you pick one and Load Alpha... adds an image file (grey: white is full strength, mapped once onto the brush, clipped
at its edge). Blender 5.2 ships no image alphas of its own.

Tool buttons (mesh filters, trims, Grow / Shrink face set, color filters, Mask by Color) pick the tool: drag in the
viewport afterwards. Shift+1 ... Shift+7 pick Draw, Clay Strips, Smooth, Grab, Inflate/Deflate, Pinch/Magnify, Crease
Sharp. Expand stays on Shift+A (mask) and Shift+W (face sets) over the mesh. Space (hold) lists the brushes first.
"All Settings" at the end of each tab row is Blender's stock Properties tabs (symmetry locks, tiling, gravity, ...).

## High poly and low poly

A game model has two meshes: the **low poly**, the light mesh you unwrap, paint and export, and the **high poly**, a
detailed copy you sculpt and bake the detail from. Maelstrom3D keeps the two as a pair, and keeps a mesh of millions of
faces from slowing the other workspaces down.

- **Create High Poly** copies the selected mesh into `<name>_high` (a full copy; the original keeps its name) and pairs the two. A copy with a non-uniform
  scale gets it applied, since Sculpt Mode wants a uniform one; the original keeps its own. The options (the box that opens on the click, or Adjust Last
  Operation) are **Detail**: None, **Multires** (levels, 2 by default) or **Voxel Remesh** (voxel size). It is on the Sculpt Status Line (on a mesh without a
  high poly), on the Objects tab of Sculpt, and in the right-click menu in Object Mode under **High / Low Poly**. If the mesh already has a high poly, you get that one selected instead of another.
- **Roles and groups.** Every mesh has a role (None, Low, High) and a group name; meshes with the same group belong together. **Mark as High Poly**,
  **Mark as Low Poly**, **Clear Role** and **Pair Selected** (the active mesh is the low poly, the other selected meshes are its high poly) are in the same submenu. The group is the name
  without its suffix: `Sword_low` and `Sword_high` are group `Sword`. The suffixes `_low` / `_high`, `_lp` / `_hp`, `_lo` / `_hi` and `_lowpoly` / `_highpoly` are known, in any case, with or
  without Blender's `.001`. Words after the suffix make a part of the group: `Panel_high_bolts` belongs with `Panel_low`. The **Channel Box** shows the role and group of the active mesh
  ("Bake: Low · Sword") with a menu to change the role.
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
- **Edit High Poly** (the submenu, on a low poly whose high poly is hidden) asks first ("Sword_high has 2,996,586 faces. Showing it takes a moment"), then shows, selects and activates the high poly. It stays shown
  until the next switch of workspace hides it again, or until **Park High Poly** (same submenu) does.
- **Face limit.** Entering Edit Mode (UV, F3) or Texture Paint Mode (Texture, F4) on a mesh of millions of faces takes seconds, and is rarely what you want. A mesh with more faces than the **Face Limit** (500,000; in
  Workspace Settings of the UV and Texture workspaces, 0 turns it off) opens in Object Mode there, and the dock and the Status Line say so ("High poly (2.1M faces): select the low poly to unwrap or paint").
  A high poly with a low poly opens the low poly instead. The Edit Mode and Texture Paint Mode buttons still enter the mode when you do want it.
- A file saved with a hidden high poly keeps it hidden, and opens the same way in any Blender: it is just a hidden object, with a role and a group stored on it.

### Retopology

Retopology builds the low poly from a high poly you already have, either by drawing it over the high poly or by letting Maelstrom3D make it. All of it is in the **High / Low Poly** submenu (right-click in Object Mode).

- **Make Live** turns the high poly of the selected mesh (or the mesh itself, when it has no role) into a **live surface**: new points snap onto it. A high poly Maelstrom3D hid asks first
  ("Sword_high has 2,996,586 faces. Showing it takes a moment"), then shows. It cannot be selected while it is live, so clicks go to the mesh you draw, and it stays shown when you switch workspace
  (a live surface is never hidden). Snapping turns on as Face Project (each point lands on the surface under the pointer), not onto the mesh you are drawing, and the retopology overlay turns on so the new
  mesh is drawn in front. The Modeling Status Line shows **Live: Sword_high** with a button that ends it. **Make Not Live** (the submenu or that button) gives back what you had: selection, how the surface
  was drawn, the snapping and the overlay; a high poly with a low poly is hidden again. Deleting the live surface does the same. A file saved while live opens live, with your own snapping still remembered.
- **New Low Poly (Quad Draw)** starts the drawing: it makes the surface live if it is not, adds an empty mesh `<group>_low` paired with it (a mesh without a role becomes the high poly of a group named after it), enters
  Edit Mode and picks the **Quad Draw** tool. **Shift+click** on the surface adds the first point. **Shift+drag** from a point adds the next point and an edge to it; from the middle point of two edges it adds a
  quad. A plain **drag** on a point moves it, **Ctrl+click** on a point deletes it. Points always land on the surface, also when you move them. The Modeling Toolkit says "Make Live first" under its tools until a surface is live.
  (Poly Build's own Ctrl+click is changed to Shift+click: with Ctrl held, a move snaps the other way round, which would leave the new point off the surface.)
- **Auto Low Poly** makes the low poly for you from a copy of the high poly: `<group>_low`, paired with it, with the high poly untouched. **Method**: **QuadriFlow** (quads) or **Decimate** (triangles), **Faces**
  (2,000 by default; the result is about that many), and for QuadriFlow **Preserve Sharp** and **Preserve Boundary**. A high poly over 300,000 faces is voxel remeshed to about that first (decimated instead with Preserve
  Boundary, since a voxel remesh closes open borders), since QuadriFlow on millions of faces takes very long. A Multires high poly is copied as it shows in the viewport. QuadriFlow needs a closed mesh without loose edges or flipped faces; when it cannot remesh, nothing is
  added and the message suggests Voxel Remesh on the high poly first, or Decimate. The new low poly has no UVs: unwrap it in the UV workspace (F3).

## Texture (F4)

F4 opens the Texture workspace and enters Texture Paint Mode on the active mesh: the 3D view (Material Preview) and the
2D paint view side by side, the brush tray on the left, the dock on the right. Names are Blender's own. A mesh needs
UVs and a material before it can be painted: the tabs say what is missing and have a button to fix it (Auto Unwrap,
Add Material, Texture Paint Mode).

| Part | Contents |
|---|---|
| Brush tray (left) | Brush picker, a grid of 10 brushes (Paint Soft, Paint Hard, Airbrush, Blur, Smear, Clone, Fill, Erase Soft, Erase Hard, Mask), Size, Strength, color picker with the second color and swap, Blend Mode, Stencil and Projection (stencil image, Occlude, Backface Culling, Normal Falloff). Closed panels: Brush Settings, Advanced |
| Status Line | Object / Texture Paint Mode, the paint channels (Base Color, Roughness, Metallic, Normal, Height, Emission), Mirror X/Y/Z, viewport display (Material Preview, Solid, Rendered) and Channel View, size of new slots, Save All |
| Shelves | Paint (the brushes, swap colors), Channels (add or pick a channel, Auto Unwrap, Add Material), Bake / Export, Custom |
| Layers tab | The layer stack of the active material: a list (top layer first: eye, name, blend mode, opacity, channel letters; folders have a triangle and a snowflake), buttons to add a Paint Layer, Fill Layer or **New Folder**, move, duplicate, delete, **Merge Down** and **Flatten**, **Group** / **Move In** / **Move Out** for folders; below it the active layer's settings (name, blend, opacity, channels, fill values, or for a folder Freeze / Unfreeze and Merge Folder), its **Mask** (the stack of mask effects, see below), and closed panels Channels (the paint slots by channel) and All Paint Slots |
| Brush tab | Stroke and Stabilize, Falloff, Texture, Texture Mask, Stencil, Clone, Options (seam bleed, dither, cavity mask), Cursor, Color Palette |
| Library tab | Materials, Masks, Brushes, Alphas and Mine as a tile grid with a search field; **Save to Library** is in the Layer and Mask panels (see Library below). Materials of the file that are marked as assets are listed in a closed panel when there are some |
| Bake tab | **Bake Groups** (the groups of the scene, Auto-Pair by Name, Pair Selected, Rename to Suffixes, **Bake Group**, **Bake All**), the settings of the selected group, maps Normal, AO, Curvature, Position, Thickness, size, margin, the list of baked images; a mesh without a role has the High Poly picker (or Use Selected as High Poly) and a **Bake** button instead |
| Export tab | Presets glTF, Unreal, Unity; folder; size; **Export**; Save All Images |
| Display tab | Material Preview environment (HDRI, rotation, intensity), Channel View of each channel, UV checker map, wireframe |

A channel is a paint slot of the active material: the first click on **Base Color**, **Roughness**, **Metallic**,
**Normal**, **Height** or **Emission** adds an image of the "new slot" size (Non-Color for everything except Base Color
and Emission) and plugs it into the shader; later clicks only pick it. C and Shift+C step to the next / previous
channel, `[` and `]` change the brush size, Shift+X swaps the two colors (plain X is hold-to-snap in the viewport, so
it is not used for painting). Channel View shows the picked channel flat in the 3D view and goes back on the next click.

**Bake** needs Cycles: it switches to it, bakes every ticked map into an image (kept with the file) and switches back; the mesh's materials
are not changed (a temporary material takes the bake and is removed). Curvature uses the shader's Pointiness (needs enough polygons), Thickness uses
ambient occlusion from inside the mesh (closed meshes only; white where the mesh is thicker than the Thickness Distance), Position is scaled to 0-1
within the bounds of the baked meshes (and is always baked with one sample: Cycles adds a position pass up over its samples). The window waits while
it bakes. Mask effects use these maps too (see Masks).

A mesh without a role bakes as before: the images are named `<mesh>_<Map>`, with the **High Poly** mesh when one is picked (selected to active), else
from the mesh itself. **Make Pair** (below the picker) turns the picked mesh into the high poly of a new group and the mesh into its low poly.

**Bake groups.** A group (see High poly and low poly) is one or more low polys, which get the maps, and one or more high polys, which the detail is
baked from; several high polys in one group (a panel and its bolts) are baked together. The **Bake Groups** panel at the top of the Bake tab lists the
groups of the scene with their number of low and high polys and their state: **Baked**, **Stale** (a mesh of the group was moved or edited, joined or left
the group, or a setting of the group changed, after the bake; the file keeps this) or **Not baked**. Clicking a row selects the group's low poly. Below the
list: **Auto-Pair by Name**, **Pair Selected**, the **Rename to Suffixes** menu, **Bake Group** (the group of the active mesh) and **Bake All**. Bake All
shows its progress, writes the time of each group to the Info log, skips a group that fails (a missing UV map, a cage that does not fit) and says which,
and is one step of Undo. The Bake button of the shelf and the menu bakes the group of the active mesh. Going into a mode, painting a texture, adding or applying a material, the UV checker map, the export and a rename do not make a group stale. Leaving Sculpt Mode or Edit Mode does (Blender only tells then that a mesh may have changed, not whether it did), and so does any other change of a mesh's material slots, which Blender reports like an edit.

Every group is baked on its own, whatever else is in the scene: only its high polys are the source, and all the other meshes (the other groups, the low
polys, loose meshes) are not rendered meanwhile, so a neighbour that touches the group, or sits in the same place, cannot shadow its ambient occlusion or reach its normal
map. The low poly that is being baked never shadows its high poly. High polys that are hidden (Maelstrom3D hides them outside Sculpt) are shown for the bake
only, and hidden again; selection, the active mesh, the mode, the render engine and every visibility and render flag are put back, also when the bake fails.

The **Group Settings** panel (below the list, for the group of the active mesh) has the group's own values, made from the low poly's old Bake tab values:
**Extrusion** and **Max Ray Distance**, a **Cage** (a mesh with the same faces as the low poly, for a group with one low poly; the rays start from it instead of
from the extruded low poly), and **AO Shadows**: **This Group** (the default) or **Whole Model**, which lets the high polys of every group shadow this group's ambient
occlusion, for contact shadows between the groups. The Maps panel (maps, size, margin) and the Settings panel (samples, Thickness Distance, AO Distance) are shared by the
group's texture set.

**Texture sets.** Low polys that share a material are one texture set, for example a blade, a guard and a hilt with one UV layout: they bake into the same images, named after
the material (`Sword_Normal`, `Sword_AO`), and each adds its own UV islands. Bake All starts the images over; **Bake Group** on one of the groups adds its islands and keeps the
others (Position is scaled to the bounds of the whole set, so it is baked again for the whole set). The first low poly by name decides the maps, the size, the margin and the
samples of the set. A low poly whose material nobody else shares, and every mesh without a role, keeps maps named after the mesh (`Cube_Normal`); maps named after a mesh in
files from earlier versions are still found and used until the set is baked.

**Export** writes the active mesh's channels: **glTF** one `.glb` with the mesh, material and textures; **Unreal**
`T_Name_BC`, `_N` (green channel flipped for DirectX), `_ORM` (red occlusion from the baked AO map, green roughness, blue
metallic) and `_E`; **Unity** `Name_Albedo`, `_Normal`, `_MetallicSmoothness` (metallic in red, smoothness in alpha),
`_Occlusion`, `_Emission`. A channel without a paint image uses the shader's value. The folder may start with `//`
(next to the saved file).

**Layers.** Blender has no paint layers, so the stack is kept on the material and built into its shader. The first
**Paint Layer** or **Fill Layer** on a material that already has paint slots turns those images into the bottom layer
"Base" (nothing painted is lost; the new image nodes keep the old ones' interpolation, extension, Mapping link and
the Normal Map / Bump settings, and the Base layer ignores image alpha so the look does not change). A Paint Layer is transparent and holds one image per channel; the image of a channel
is only made (at the "new slot" size) when that layer and channel are first picked for painting, so unused channels cost
no memory. A Fill Layer is a value or color over the whole mesh; limit it with a **Mask** (next paragraphs).
**Paint Mask** sends strokes to the mask's Paint effect instead of the channel (on a Fill Layer strokes always go to
it; a Fill Layer without a Paint effect can be turned into a Paint Layer with Convert, and until then the brush is
aimed at a tiny hidden scratch image so no layer is painted by mistake).
The brush always paints the active layer's image of the active channel (Status Line buttons, C / Shift+C). Blend modes
are Mix, Multiply, Add, Overlay, Screen, Soft Light, Subtract, Difference, Color, Darken and Lighten (the Normal channel
always mixes). Double-click a name to rename it. In the shader each channel has a frame with one Image Texture and Mix
node per layer; only nodes made by the stack are ever changed. **Merge Down** combines a layer into the one below with
its blend mode, opacity and mask baked in (exact when the lower layer is opaque or the upper one uses Mix; the merged
layer keeps the lower layer's blend mode); **Flatten** replaces the stack by one layer holding what it looks like.
Export, glTF included, uses the flattened visible stack of each channel and does not change the layers. The tab warns
when the layer images add up to more than twelve 4K images of memory.

**Masks.** A mask decides where a layer shows: white shows the layer, black hides it, grey shows it partly. A layer's
mask is a list of **effects** that combine from the bottom up (the list shows the top effect first, like the layer
list). The result starts out white, so a layer without effects shows everywhere; each effect then changes the result
below it. In the Mask panel: **White (Show All)** / **Black (Hide All)** start a mask with a Paint effect (an image you
paint: black hides, white shows); **Add Mask Effect** adds one above the selected effect; the arrows move it, the
buttons beside the list duplicate and delete it. Every effect has an eye, a name, an opacity (how strongly it applies;
at 0 it does nothing) and, for the sources, a blend mode (Normal, Multiply, Add, Subtract, Max, Min: Multiply keeps
only what both agree on, Add and Max grow the white). A new effect on top of others multiplies (a black Paint adds),
so it starts out gentle; the first one simply sets the mask.

| Effect | What it makes |
|---|---|
| Paint | An image you paint with the brush (Paint Mask on). Starts white (paint black to hide) or black (paint white to show) |
| Fill | One value, 0 (black) to 1 (white), over the whole mesh |
| Edges | White on convex edges, for edge wear: Amount, Softness, Invert. Needs the Curvature map, so it works best on meshes with enough polygons |
| Cavity | White in crevices, for dirt: Amount, Contrast, Invert (from the ambient occlusion map) |
| Top-down | White on surfaces facing a direction (default up, +Z in the world), for dust and snow: Direction, Offset (higher also covers steeper surfaces), Softness, Height Falloff (less toward the bottom of the mesh) |
| Thickness | White where the mesh is thin: Amount, Contrast, Invert (closed meshes only) |
| Noise | Procedural noise: Scale, Detail, Contrast, Seed, and Space: UV (breaks where UV islands meet) or Object (follows the 3D position, no breaks) |
| Levels | Filter: Black In / White In stretch the range, Gamma bends the midtones, Black Out / White Out limit the result |
| Blur | Filter: softens everything below it (Amount is the width) |
| Invert | Filter: swaps black and white (opacity sets how much) |
| Sharpen | Filter: steeper steps between black and white |

Filters work on everything below them, so their place in the list matters; sources and generators are combined with
the result below by their blend mode. **Show Mask** shows the active layer's mask in the 3D view (white where the layer
shows); switching it off puts the material back exactly as it was. **Invert Mask** adds an Invert effect on top (or
takes it off again), **X** next to it removes the whole mask. **Rebake Maps** makes the maps again after the mesh or the
Bake tab's settings changed.

The generators read maps baked from the mesh (Curvature, AO, Position, Thickness, plus the world normal). The first time
an effect needs one, it is baked with Cycles at the Bake tab's resolution, like the Bake tab does (named
`<mesh>_<Map>`, with the high-poly mesh when one is set; for a low poly of a group: from its group, together with the other low polys of its texture set, named after the material) and kept with the file; every layer and effect then reuses it,
and only a new resolution, Rebake Maps or the Bake tab bake it again. Nothing in the mesh's materials changes while
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
(not layer by layer), and a mask on a folder hides or shows the group as a whole. **New Folder** (next to Paint Layer
and Fill Layer) adds an empty folder above the active layer, **Group** puts the active layer (or folder) into a new
one. The triangle in front of a folder's name closes or opens it in the list (closing a folder that holds the active
layer selects the folder). The arrows move the active layer one place of the list at a time: past a neighbour, into an
open folder next to it, and out of a folder when it is at its first or last place (a closed folder is passed as one
block); **Move In** lists the folders and moves the layer to the top of the one you pick, **Move Out** puts it just
above its folder. Folders can hold folders, to any depth. Duplicate copies a folder with all its layers and their
images, Delete removes the folder, its layers and their images (images used elsewhere stay), **Merge Down** merges a
layer or folder into the layer below it in the same folder (not into a folder: merge that first), and **Merge Folder**
turns a folder into one Paint Layer holding what its layers made together, with the folder's name, blend mode, opacity,
eye and mask (the look does not change). The folder's Mask panel is the layer Mask panel; a folder itself cannot be
painted, pick a layer inside it.

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

**Library.** The Library tab holds ready-made things to apply and the things you saved. Five categories, a search field,
and square tiles with the name under each (the full name and a description are the tooltip):

| Category | What a click does |
|---|---|
| Materials | Adds the material as a **new folder on top of the layer stack**, named after it, and makes it the active layer: it is a folder of Fill Layers (Base Color, Roughness, Metallic values) whose masks use the Edges, Cavity, Top-down and Noise generators, so it can be toggled, faded, masked, frozen or deleted as one. A mesh without a material gets one. One click is one undo step and one rebuild of the nodes; the maps the generators read are baked once (Rebake Maps keeps them current) |
| Masks | Gives the **active layer** (or folder) the preset's mask effects. **Replace** swaps them for the layer's mask, **Add on Top** puts them above it, combined with it (multiplied) |
| Brushes | Picks the texture paint brush (all of them, also the pressure and pixel art ones), with the brush library popover on top (favorites live there) |
| Alphas | The Sculpt alphas: the same starter set and **Load Alpha...**, in the same user folder, so an alpha loaded in Sculpt is here too. In Texture Paint Mode the alpha is the active brush's **Texture Mask** (it follows the cursor; angle and mapping in the Brush tab), None clears it |
| Mine | Your own items, and **Save Layer** / **Save Mask** |

The starter **materials** are Painted Metal (worn through at the edges, dirt in the crevices), Rusty Iron, Brushed Steel,
Chrome, Gold, Copper (patina in the cavities), Rubber, Plastic (glossy), Dirty Plastic, Concrete (noise), Dusty and Snow
Cover (top-down, to add over any material), Mud (cavity and noise), Aluminium, Matte Black and Ceramic, with plausible PBR
values (metals have metallic 1 and a tinted color, the rest 0). The starter **mask presets** are Edge Wear, Dirt in
Cavities, Top-down Dust, Noise Breakup, Thickness Glow, Speckle, Grunge, Light Dust, Snow Cap and Large Patches. They are
built from fills and the mask generators only, no image files, and are read-only.

**Saving your own.** **Save to Library** in the Layer panel saves the active layer, or the active folder with everything
in it (nested folders, fills, paint layers with their pixels, blend modes, opacities, masks), as a material; in the Mask
panel it saves the layer's mask stack as a mask preset. You are asked for a name. Under Mine, each item has a rename and
a delete button (Your Items); the starter items have neither. An item is a folder in the user data folder
`datafiles/m3d_library/user/<name>/` (inside the portable folder in a portable install): `item.json` describes the
layers (kind, name, visible, opacity, blend, per channel the fill color or value or the PNG of a paint layer, the mask
effects with all their settings) and any paint images are saved beside it as PNG, so applying an item makes the layers
again with the same pixels and values (a saved folder applied back gives the same composite exactly). Applying one
checks nothing is half done: a damaged item is refused and leaves the stack as it was.

**Previews.** The tile pictures are small Cycles renders of a sphere with grooves (so edges and cavities exist) lit by
Blender's courtyard HDRI, 128 px, with the item applied; a mask preset is shown as the mask on the sphere. They are made
the first time the Library tab is drawn, one small step at a time on a timer (the preview scene, then each baked map,
then one item per step: the longest step is about a second, 26 starter items take about 15 s in all), and a tile shows a
shaded disc in the material's color until its picture is ready. Starter previews are cached in
`datafiles/m3d_library/thumbs` (made again when an item or the preview look changes), yours are `thumb.png` in the item's
folder. The temporary preview scene is removed when it is done (and when you save the file in between); **Refresh
Previews** (Mine, Your Items) makes them all again.

Painted images never get lost: before a file is saved, images with changes are written to their files, or packed into
the .blend when they have none. Save All Images does the same on demand. Large images use a lot of memory: new slots
default to 2048 px.

## Rigging (F5)

F5 opens the Rigging workspace in Object Mode. Left: the Outliner (a skeleton shows its bones as a tree under it) over a
small page with the bone collections and the active bone. Middle: a large viewport (bones show through the mesh in Pose
Mode; each new skeleton is drawn in front). Right: the dock. Bottom: a short Timeline; the **Drivers** button in the
Status Line (or in the Drive tab) turns the same area into the Drivers editor and back.

| Part | Contents |
|---|---|
| Status Line | **Object / Edit / Pose / Weight Paint** mode buttons, X-Mirror (of the bones in Edit Mode, of the pose in Pose Mode, of the mesh in Weight Paint Mode), bone display (Octahedral, Stick, B-Bone, Envelope, Wire), Names, Axes, In Front, Rest / Pose position, Drivers |
| Shelves | Skeleton (Joint, Extrude, Mirror, Orient, Names L/R, Parent, Disconnect), Controls (circle, square, arrow, cube and sphere shapes, a color and Apply, IK + Pole), Skin (Bind, Paint Weights, Normalize, Mirror Weights), Custom |
| Skeleton tab | Joint tool and its options; Edit Bones (Extrude, Extrude Forked, Click Extrude, Subdivide, Duplicate, Delete, Fill Between Joints, Switch Direction, Align); Mirror (+X to -X, -X to +X, Select Mirror); Orient (Orient Joint and the roll presets); Names (Name Sides by X / Y / Z, Flip Names, the naming check); Hierarchy (Parent connected / with offset, Disconnect, Clear Parent, Select Parent / Child); Generate Rig (Rigify) |
| Controls & Constraints tab | Add Constraint buttons (Copy Location / Rotation / Scale / Transforms, Child Of, Damped Track, Stretch To, Armature, the Limit constraints, Action, Spline IK, IK); IK (chain length, pole distance, **IK with Pole**, IK to Bone, Clear IK); the active bone's constraint stack; Control Shape and Color; Locks |
| Skin tab | Bind (Automatic, Envelope or Empty Groups, with a fall back to envelope weights), Unbind; Weight Paint (mode button, brush weight, size and strength, Vertex / Face Select, bone selection and mirror options); Influences (every vertex group with a lock and a solo button); Weights (Flood, Weights from Bones, Smooth, Normalize All, Limit Total, Clean, Mirror Weights); Transfer Weights; Weight Table of the selected vertex |
| Drive tab | Shape Keys (list, value, Add, From Mix, Reset Values, Mirror Shape); **Driven Key**; the drivers of the active object with a button for the Drivers editor |
| Test tab | Reset Pose, Reset Selected, Clear Location / Rotation / Scale, Copy / Paste / Paste Flipped; Rest / Pose position and Apply Pose as Rest Pose; Pose Library (Save Pose, the saved poses with Apply and Flipped, the viewport's pose shelf) |
| Collections tab | Bone Collections (the tree with show / hide, assign, select), Selection Sets, Bone Colors, Bone Display |

The dock opens the tab that fits the mode when you enter it: Edit Mode the Skeleton tab, Pose Mode Controls & Constraints,
Weight Paint Mode Skin. A tab you pick yourself in a mode is what that mode opens on from then on, and a dock on All Settings
is left alone. Every tab says what it needs (a skeleton, a mode, a mesh) with a button that fixes it.

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
on one side is named .L (or .R) and gets a mirrored copy. The first use creates the skeleton.

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

**Bind.** Select the mesh (and the skeleton if the scene has more than one) and press Bind. Automatic weights that leave
vertices without any weight, usually a mesh with holes or overlapping parts, are replaced by envelope weights and the tab
says so; close the holes and merge doubles for better weights. Empty Groups makes a group per bone with no weights for
hand painting. Mirror Weights copies the weights of one side of a symmetric mesh to the other (the .L groups fill the .R groups).
Smooth works on selected vertices (Edit Mode, or Vertex Select in Weight Paint Mode).

**Driven Key.** Pick the driver channel (an object or bone transform, or a custom property) and the driven channel (a
transform, a custom property, or a shape key). Pose the driver, type the Driven Value the other channel should have there and
press **Key**; repeat for each pair. It makes an ordinary driver whose curve is keyed with those pairs (Smooth, Linear
or Stepped), so the Drivers editor shows and edits it; the driven channel holds the end values outside the keys. A
bone in Quaternion mode switches to XYZ Euler when it is used as a rotation channel.

**Naming check.** The Names panel lists bones with a side name but no partner (`Arm.L` without `Arm.R`), a name on the wrong
side, a bone that mirrors a sided bone by position but has no side, and numbered duplicates (`Bone.001`), with a button
that selects them.

**Rigify** ships with Blender and stays off until the Generate Rig panel is opened and **Enable Rigify** is pressed; then it
offers a human meta-rig and Generate Rig. If it cannot be turned on the panel says why.

Keys: Ctrl+E extrudes a bone in Edit Mode, P / Shift+P parent / unparent bones, Shift+N opens the naming marking menu (Name
Sides, Flip Names, Mirror, Select Mirror, Select Problem Names) in Edit and Pose Mode.

## Animation (F6)

F6 opens the Animation workspace (in Pose Mode when a skeleton is active). Left: a camera view (the scene camera; the view says
so when there is none and the Channel Box tab offers Add Camera). Middle: the large viewport. Bottom: one editor that is the
Dope Sheet or the Graph Editor (the **Graph / Dope Sheet** buttons in the Status Line, Ctrl+Space maximizes it) with the Timeline
under it. Right: the dock. While the animation plays only the viewports and the animation editors redraw, so the dock does not
slow playback (it catches up when you stop).

| Part | Contents |
|---|---|
| Status Line | Object / Pose, **Auto Key** (+ its options: replace or add keys, only the active keying set, layered recording), key type (Keyframe, Breakdown, Extreme, Moving Hold), **New keys** (Stepped, Spline, Linear, Clamped), Blocking / Polish, keying set, playback range (start / end, preview range button), FPS, loop mode, Graph / Dope Sheet, Playblast |
| Shelves | Animate (Set Key, Translate / Rotate / Scale keys, Breakdown, Delete Key, Euler Filter, Stepped, Spline), Poses (Copy, Paste, Paste Flipped, Reset, Save Pose, Apply Pose menu), Custom |
| Channel Box tab | The active object's channels, or in Pose Mode the **active bone's** channels (translate, the rotation of its mode, scale), with its custom properties as sliders (IK / FK switches); animated channels are coloured as usual (yellow = key on this frame, green = animated) |
| Pick tab | Bone selection sets of the skeleton (list and one button per set), **object selection sets** (made from the selection; a click selects, Shift-click adds), bone collection picker (visibility toggle and a button that selects the collection's bones) |
| Tween & Poses tab | Tween slider with 0 / 25 / 50 / 75 / 100 buttons, Key and Revert; Push, Relax, Breakdown, To Neighbor, To Rest (Pose Mode); Copy / Paste / Flipped, Save Pose, the saved poses with Apply and Flipped |
| Motion tab | Motion paths (show, range, frame step, Calculate / Update / Clear, numbers, show in the viewport) of the selected bones or objects; Ghost Curves for the Graph Editor |
| Layers tab | Layers are NLA tracks: Push Down, Add Additive Layer, the tracks (mute, name, solo, Edit, remove), the top action's blend and influence, Bake |
| Playback tab | Range (start, end, preview range, FPS, Range from Keys, Scene from Keys), Blocking / Polish and the new key defaults, loop, pre-roll, sync, Playblast (folder, size, play when done) |

**Tween.** With keys before and after the current frame, Tween sets the selected bones (Pose Mode) or objects to a value
between the previous and the next key of each keyed channel and keys it as a breakdown. Alt+Q starts it in the viewport:
move the mouse left and right (400 px is the whole way from the previous to the next key, 0.5 is the start; Ctrl snaps to
tenths, Shift is slower), click or Enter keys it, Esc or right click puts everything back. In the dock the slider moves the
selection live and **Key** keeps it (**Revert** drops it); the number buttons key straight away. Alt+Shift+P, R and B run
Push, Relax and Breakdown (Blender's own, Pose Mode).

**Blocking and Polish.** Blocking makes new keys stepped, converts the selection's keys to stepped and shows the Dope Sheet.
Polish makes new keys clamped splines, converts the selection's keys and shows the Graph Editor. The **New keys** buttons only
change the default. That default is a Preferences setting, so it applies to every file and stays until you change it (and a
key set between two others copies the key before it, which is why Blocking / Polish convert the selection too). **Restore My
Defaults** (Playback tab) puts back what the preferences had before the first change.

**Layers.** The Layers tab uses the NLA: Push Down puts the current action on its own track; Add Additive Layer pushes it down
and starts an empty action on top that adds to the layers below, so a pass of polish keys goes on its own layer. Edit enters
tweak mode on a layer, Done Editing leaves it. Bake flattens the selection over the playback range into one action.

**Playblast.** Renders the viewport (the camera view when the workspace has one) over the playback range into PNG frames
(the Playback tab sets the folder, default a temporary one, and the size as a percentage) and opens them in the player. Esc
cancels. Your render output settings (path, format, size, frame range) are put back afterwards.

Keys: S sets a key, Shift+W / E / R key translate / rotate / scale, Alt+V plays, `,` and `.` jump between keys, Alt+, and Alt+.
step a frame, Shift+S is the keyframe marking menu, Ctrl+Left / Right jump to the start / end, **Alt+Q Tween**,
**Alt+Shift+P / R / B Push / Relax / Breakdown** (Pose Mode).

## Rendering (F7)

F7 opens the Rendering workspace. Left: a 3D view in Material Preview (the Status Line's **IPR** button turns it into the
Rendered viewport and back; Rendered re-renders as you work, which is heavy on a slow PC, so it starts off). Middle: the
**Render View** (an Image Editor showing the Render Result: renders land here, not in a new window). Right: the dock.

| Part | Contents |
|---|---|
| Status Line | Engine (Cycles / EEVEE), scene camera picker, quality preset (**Draft / Medium / Final**, or Custom once you edit a value), **Render**, **Render Animation**, **IPR**, **Render View** |
| Shelves | Lights (Point, Spot, Area, Sun, HDRI Sky, Previous World), Render (Render, Animation, Render View, Camera from View, Look Through, Draft / Medium / Final), Custom |
| Camera tab | Scene camera, **New Camera from View**, Match Camera to View, Look Through Camera; focal length (or ortho scale), clip range; depth of field (focus object or distance, f-stop, blades); resolution X / Y / %; safe areas and composition guides; render border (Set / Clear) |
| Lighting tab | Add Light buttons, the **Light Editor** (one row per light: viewport eye, render toggle, name, color, power, shadow, shared-data button, select), **HDRI Sky** (Blender's studio HDRIs, or your own file; rotation, strength), exposure and gamma |
| Materials tab | The active object's material slots and the Principled inputs (base color, metallic, roughness, emission color / strength, normal strength when a Normal Map or Bump node feeds it); a button to the Shading workspace |
| Render tab | Engine and quality presets, then the engine's settings: Cycles device, samples, noise threshold, time limit, denoising; EEVEE samples, ray tracing, shadows |
| Output tab | Path, format, color mode and depth, frame range, FPS, Render / Render Animation, color management (view transform, look, exposure, gamma) |
| Passes & Layers tab | View layers, passes (data, light, Cryptomatte, shadow catcher), AOVs, light groups, **holdout** and **indirect only** per collection, light linking and shadow linking for the active object, shadow catcher and holdout flags |
| Advanced tab | Light paths (Cycles bounces and clamping; EEVEE fast GI), film (transparent background, filter, motion blur), performance, simplify |

**Quality presets.** Each preset sets both engines at once and the size, so switching engine keeps the preset. Draft: Cycles 32
samples, 4 bounces; EEVEE 16 samples, no ray tracing; half size. Medium: Cycles 128 samples, 8 bounces; EEVEE 64 samples, ray
tracing at half resolution. Final: Cycles 512 samples, 12 bounces; EEVEE 256 samples, full ray tracing, 2 shadow rays. All
use denoising and adaptive sampling in Cycles. The Status Line and the Render tab show **Custom** as soon as you change one of
those values (or the size); the preset buttons put them back.

**Light Editor.** Every light of the scene is a row, including lights in hidden or excluded collections (greyed). The eye shows
or hides the light in the viewport, the camera icon in the render. A light whose settings are shared with other lights shows
**xN**: editing one changes them all, and clicking it gives that light its own copy. The arrow selects the light (not possible
for a light in an excluded collection).

**HDRI Sky.** Picking an HDRI (or **HDRI Sky** on the shelf) assigns a new world called *m3dHDRI* (Texture Coordinate, Mapping,
Environment Texture, Background). The world the scene had is kept and **Back to Previous World** puts it back. Rotation and
strength edit the Mapping and Background nodes. The viewport shows the sky in Rendered shading.

**Camera from View.** Adds a camera at the current viewport view (with the viewport's field of view) and makes it the scene
camera; **Match Camera to View** moves the scene camera to the view instead.

Keys: **Shift+F12** renders the frame, **Ctrl+Shift+F12** the animation, **Alt+F12** shows the last render (F12 itself is the
UV workspace in Modeling). Esc cancels a render.

## Customising the interface

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
