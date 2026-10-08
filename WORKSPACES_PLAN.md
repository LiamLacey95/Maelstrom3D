# Maelstrom3D task workspaces: plan

Seven task-focused workspaces on F1-F7, each showing only what that task needs, with everything else one tab
away. Based on research into ZBrush, Blender, Mudbox, 3DCoat and Nomad (sculpting), Substance 3D Painter, Mari,
3DCoat, ArmorPaint and Ucupaint (texturing), Maya, Blender, Houdini KineFX/APEX, Rigify, mGear, AccuRig and
Cascadeur (rigging), Maya, Blender, MotionBuilder, Cascadeur and animBot-style tools (animation), Maya, RizomUV
and Blender (UVs), and Maya/Arnold, Marmoset Toolbag, KeyShot and Blender (rendering). Every Blender identifier
named below was checked against our 5.2.2 build.

| Key | Workspace | Mode on entry | Inspired by |
|---|---|---|---|
| F1 | Modeling | Object | Today's Classic layout (unchanged) |
| F2 | Sculpt | Sculpt | ZBrush trays and top shelf, Nomad's simplicity |
| F3 | UV | Edit (UV editor + 3D view) | Maya UV Toolkit, RizomUV's Cut / Sew / Unfold / Optimize / Layout |
| F4 | Texture | Texture Paint | Substance 3D Painter's layer stack, shelf and bake/export |
| F5 | Rigging | Object / Edit / Pose / Weight Paint as needed | Maya skeleton + skin tools, Blender bone collections, auto-rig tools |
| F6 | Animation | Pose / Object | Maya Time Slider + Graph Editor, tween and picker tools |
| F7 | Rendering | Object | Maya Render Settings + light editor, Marmoset / KeyShot look-dev |

Rules for every workspace:
- **Essentials visible, the rest one click away.** Each workspace has: the 4-row top bar (menu bar, Status Line,
  shelf tabs, shelf) with task-specific contents; a right-hand dock with task tabs (essential tab first); in Sculpt
  and Texture a left tray. Stock Blender panels stay reachable through an "All Settings" tab or the Attribute
  Editor, never deleted.
- **Blender names, no trademarks.** Labels use Blender's names (Voxel Remesh, Face Sets, Multires, Bake, Layers,
  Pose Library). Never: DynaMesh, ZRemesher, SubTool, Polygroups, ZAdd, LightBox, Polypaint, Substance, Smart
  Material, Mari, animBot, Tween Machine, Studio Library, AccuRig, Mixamo, mGear, KineFX, APEX, Cascadeur,
  Hypershade.
- **Maya-style keys keep working** (QWERT, Alt+mouse navigation, F frame, Space hotbox, Z undo, marking menus).
  Task keys only go where they don't clash; clashes found in research are listed per workspace.
- **Python + startup file only.** No C changes are planned. Layouts live in `release/datafiles/startup.blend`,
  built by `tools/m3d/build_startup.py` (embedded in the binary, so a layout change needs a quick incremental
  rebuild, not the 45 minute one). Behaviour lives in `scripts/startup/m3d_*.py`.
- **Each phase ships with tests** (`tools/m3d/test_m3d.py` background checks, `tools/m3d/gui_test.py` real-window
  checks), screenshots of the workspace, a change-log row in `MAELSTROM3D.md` and updated `SHORTCUTS.md` /
  `PARITY.md`.

---

## Phase 0: shared framework

### 0.1 Workspace switching (F1-F7)
- Workspaces carry a kind: `WorkSpace.m3d_kind` (bpy.props string: `MODEL`, `SCULPT`, `UV`, `TEXTURE`, `RIG`,
  `ANIM`, `RENDER`), set by `build_startup.py`. Files without it fall back to a name table (`Classic`/`Modeling`
  -> MODEL, `Sculpting`/`Sculpt` -> SCULPT, `UV Editing`/`UV` -> UV, `3D Paint`/`Texture` -> TEXTURE, ...).
- Workspace names and order: **Modeling, Sculpt, UV, Texture, Rigging, Animation, Rendering**, then the extras
  (Shading, Compositing, Node Editor, Script Editor). Blender's spare "Modeling - Standard" is dropped. Old names
  are mapped in `WORKSPACE_NAMES` so older files still get the right kind.
- `m3d.workspace(kind)` switches the window's workspace and sets the matching menu set. Window keymap: F1-F7 ->
  `m3d.workspace`. Old F1 (Help menu, still in the menu bar) and F2-F6 (menu sets) are replaced; the menu-set
  dropdown keeps working and also offers FX. `WorkSpace.object_mode` gives each workspace its entry mode.
- Menu sets per workspace: Modeling -> Modeling; Sculpt -> new **Sculpting** set (Sculpt, Mask, Face Sets,
  Remesh menus, reusing Blender's `VIEW3D_MT_sculpt`, `VIEW3D_MT_mask`, `VIEW3D_MT_face_sets`); UV -> new **UV**
  set (UV Edit, UV Select, UV Create menus); Texture -> new **Texturing** set (Paint, Layers, Bake, Export);
  Rigging, Animation, Rendering -> the existing sets.
- Every place that names a workspace today (`m3d_mode.py` startup layout and tool-header list, F12 -> "UV
  Editing", `gui_test.py`, demo scenarios, docs) moves to kinds instead of names.

### 0.2 Per-workspace top bar
- `draw_status_line`, the shelf-tab row and `draw_shelf` dispatch on the active workspace kind. Modeling keeps
  today's rows. Each phase below defines its Status Line and shelves.
- Shelves get a `kinds` field so each workspace shows its own shelf tabs plus a **Custom** tab (0.4).

### 0.3 Per-workspace dock tabs (and a left tray)
- `DOCK_TABS` becomes a table per kind. A tab is either a native Properties context (`TOOL`, `MATERIAL`, `BONE`,
  `RENDER`, ...) or a **page**. Pages reuse the existing `MODELING_TOOLKIT` context (no C change): the active page
  is stored per workspace and per side (`WorkSpace.m3d_page_right`, `m3d_page_left`), and page panels poll
  `page == their page id` via a `_PagePanel` mixin. The Modeling Toolkit becomes the page `modeling_toolkit`.
- The left tray (Sculpt, Texture) is a second Properties editor on the left, same tab mechanism, side `LEFT`
  (decided by the area's position).
- Every dock ends with **All Settings** (the stock Properties tabs) so nothing is lost.

### 0.4 Personalization (all workspaces)
- **Custom shelf:** right-click any button -> "Add to Shelf" (appended to Blender's button context menu, reads
  the button's operator and properties). Per workspace, stored in `m3d_user.json` in the user config folder
  (`%APPDATA%\Maelstrom3D\5.2\config`, or the `portable` folder). An "Edit Shelf" toggle shows remove / move
  buttons.
- **Dock tabs:** a small menu at the end of each dock's tab row to show/hide tabs and pick the default tab;
  stored in the same JSON.
- **Layouts:** resizing/splitting areas and File > Defaults > Save Startup File keep the user's layout; "Reset
  Workspace" (in the tab menu) re-appends the factory version of the current workspace.
- **Favourites:** brush and material favourites use Blender's asset catalogs and the asset "Favorite" flag; the
  trays show a favourites grid first.
- **Hotkeys:** right-click any button -> Assign Shortcut (Blender's), and Preferences > Keymap.

**Phase 0 tests:** F1-F7 switch to the right workspace, mode and menu set; old names map to kinds; page panels
show only on their page; Add to Shelf round-trips through the JSON; trademark word scan over `scripts/startup`
and UI strings.

---

## Phase 1: Sculpt (F2)

Research: smoothing, build-up/carve (Clay Strips, Draw), Move/Grab, constant size/strength changes, symmetry,
masking, hide/isolate, Face Sets, blockout remesh then subdivide, detail, colour last. Workflow: blockout (low
res, Voxel Remesh, Move, Clay, Smooth) -> retopo (QuadriFlow) -> Multires subdivide -> detail -> colour.

**Layout**
- **Left tray (brush tray), always on:** active brush name and thumbnail (opens Blender's brush asset popover),
  a grid of ~14 favourite brushes (Draw, Clay Strips, Clay, Smooth, Grab, Elastic Grab, Snake Hook, Inflate/
  Deflate, Pinch/Magnify, Crease Sharp, Flatten/Contrast, Scrape/Fill, Layer, Mask, Face Set Paint), then Size,
  Strength, Add/Subtract, Mirror X/Y/Z. Collapsed: Falloff, Stroke, Texture, Display, Advanced (stock
  `VIEW3D_PT_tools_brush_*` panels re-drawn inside our page).
- **Status Line:** Sculpt Mode / Object Mode, mesh poly count, Multires level ("Lv 2/4"), Dyntopo toggle,
  symmetry X/Y/Z, Automasking popover, Mask / Face Set overlay toggles, matcap picker.
- **Shelves:** Sculpt (brush favourites), Remesh (Voxel Remesh + size, QuadriFlow, Multires +/-, Apply Base),
  Mask (Fill, Clear, Invert, Grow, Shrink, Sharpen, From Cavity, Hide Masked), Custom.
- **Right dock tabs:**
  1. **Geometry:** Multires (Subdivide / Simple / Linear, level sliders, Delete Higher, Unsubdivide, Apply Base),
     Voxel Remesh (size, adaptivity, preserve options), QuadriFlow, Dyntopo (detail type, size, refine).
     Controls that don't apply are greyed with a one-line reason (Dyntopo vs Multires).
  2. **Mask:** flood fill/clear/invert, mask filter (smooth, sharpen, grow, shrink, contrast), from cavity /
     boundary / colour, Expand, hide masked.
  3. **Face Sets:** init from loose parts / materials / normals / UV seams / creases / sharp edges, create from
     mask/visible, grow/shrink, extract, fair, randomize colours, visibility.
  4. **Deform:** mesh filters (smooth, inflate, relax, surface smooth, sharpen, enhance details, sphere, random),
     symmetrize, set pivot, trim gestures.
  5. **Paint:** colour paint brush, colour picker and swatches, colour filter.
  6. **Display:** matcap / studio light, cavity, overlay opacities, wireframe, low-res display and delayed
     updates (performance).
  7. **Objects:** the scene's meshes as a list (show/hide, select, solo, append duplicate) = the "tool stack".
  8. **All Settings.**
- **Hidden but reachable:** gravity, tiling/lock axes, radial symmetry, stencil, cloth brushes, experimental
  options.

**Keys** (the Sculpt keymap already has S size, U strength, D / Shift+D subdivide, Ctrl+D remesh, H isolate face
set, Ctrl+I invert mask, B brush shelf): add brush hotkeys via `brush.asset_activate` on free keys (proposal:
Shift+1..Shift+7 for Draw, Clay Strips, Smooth, Grab, Inflate, Pinch, Crease). Space hotbox gets a brush section
in Sculpt. RMB stays Blender's sculpt context panel.

**Pitfalls handled:** non-mesh active object (tabs show "Select a mesh to sculpt" + button); unified vs brush size
(sliders write `tool_settings.sculpt.unified_paint_settings` when unified); Dyntopo destroys UVs/face sets (warn);
symmetry uses the mesh's `use_mirror_x/y/z`.

**Tests:** F2 enters sculpt mode; brush grid activates the right brush; Geometry buttons run (multires add level,
voxel remesh); mask tab ops run; screenshot review.

---

## Phase 2: UV (F3)

Research: seams / Cut and Sew, Unfold, select shell, check distortion + checker, Layout/pack, straighten/orient,
pin + Optimize, texel density, stitch, projections, UDIMs. Workflow: seams -> unfold -> straighten/orient ->
pack -> check distortion and texel density -> UDIMs.

**Layout:** UV editor large on the left, 3D view on the right (solid, seams visible). The UV Toolkit (existing
`m3d_uv.py`) moves into the dock as pages.
- **Status Line:** UV Sync, select mode (vertex/edge/face/shell), Live Unwrap, Distortion, Checker, texture size.
- **Shelf:** Cut, Sew, Unfold, Optimize, Layout (the five big buttons), Auto Unwrap, Custom.
- **Dock tabs:** 1 **Unwrap** (Cut, Sew, Unfold with method, Optimize, Layout with margin/rotation options, Pin /
  Unpin); 2 **Arrange** (shell select, overlapping, flip, rotate 90, align, straighten, orient, snap together, match
  scale); 3 **Check** (checker, distortion type, **texel density read/set/match**); 4 **Create** (projections);
  5 **UDIM** (tiles, pack to tile); 6 All Settings.
- **New tools:** `m3d.uv_texel_density` (bmesh: density = sqrt(uv area / world area) x texture px; set scales
  shells about their centres, ~40 lines), `m3d.uv_auto` (cut by angle -> unfold -> layout). Checker material is
  restored before saving (save handler).
- **Keys** (UV editor only, all free): Alt+P Layout, Ctrl+Shift+U Unfold, Alt+C Checker, Shift+T texel density,
  Alt+S sync toggle.

---

## Phase 3: Texture (F4)

Research: Blender 5.2 has **no native paint layer stack** (planned for a later Blender). Ucupaint's design is the
model to follow. Workflow: UVs -> bake mesh maps -> base materials -> masks/generators -> hand paint -> export.

Split in two:

**3a. Workspace, painting, bake, export**
- **Layout:** 3D view (Material Preview) centre-left, 2D paint view centre-right (collapsible), left tray, dock.
- **Left tray:** brush grid (Paint Soft/Hard, Airbrush, Blur, Smear, Clone, Fill, Erase, Mask), size, strength,
  colour + secondary colour, blend mode, stencil/projection toggle.
- **Status Line:** active channel (Base Color / Roughness / Metallic / Normal / Height / Emission), symmetry,
  viewport display (Material, single channel, lighting), resolution, Save All.
- **Dock tabs:** 1 **Layers** (3b; until then the paint slots), 2 **Brush** (stroke, falloff, texture,
  stencil), 3 **Shelf** (asset grid: brushes, base materials, favourites), 4 **Bake** (high-poly picker, maps:
  Normal, AO, Curvature via Pointiness/emission, Position, Thickness; resolution, margin, one Bake button;
  settings stored on the object), 5 **Export** (presets: glTF, Unreal ORM, Unity; folder, size, Save All), 6
  **Display** (environment, channel view, checker), 7 All Settings.
- **Safety:** images saved/packed on file save (no lost work), Non-Color set on data channels, "needs UVs" and
  "needs material" messages with fix buttons.
- **Keys:** `[` `]` brush size and Shift+X colour swap in texture paint only (Maelstrom uses X/C/V for snapping),
  C / Shift+C cycle channel.

**3b. Layer stack (largest single piece, ~800-1200 lines)**
- Per channel, a node chain: each layer = Image Texture (or fill value / tiling material) -> Mix (blend mode,
  opacity) over the layer below; optional mask image into the Mix factor. Layers stored in a PropertyGroup on
  the material; operators add / delete / duplicate / reorder / rename / hide / set blend / add mask / fill layer.
  Painting targets the active layer through `material.paint_active_slot`. Live result in Material Preview; flatten
  only on export (bake or numpy pass for ORM packing).
- Layers default to 2K and are created lazily (memory).
- Saved "material presets" (node groups marked as assets) cover the smart-material idea under a neutral name.

---

## Phase 4: Rigging (F5)

Research: place/extrude joints, orient (roll), naming and mirroring, hierarchy, IK, constraints, control shapes
and colours, bind skin, weight painting, weight cleanup, mirror/transfer weights, test poses, drivers / driven
keys, bone collections, auto-rig. Order: skeleton -> orient -> name/mirror -> controls -> constraints/IK -> skin
-> weights -> drivers/correctives -> test poses -> animator UI.

**Layout:** large viewport (X-ray bones), optional small front/side view; Outliner left (armature hierarchy) with
bone collections below; bottom area Timeline, switchable to the Drivers editor.
- **Status Line:** Object / Edit / Pose / Weight Paint mode buttons, X-Mirror, bone display (Octahedral, Stick,
  B-Bone, names, axes, in front), Rest / Pose position.
- **Shelves:** Skeleton (Joint, Extrude, Mirror, Orient, Names L/R), Controls (circle/box/arrow shapes + colour),
  Skin (Bind, Paint Weights, Normalize, Mirror Weights), Custom.
- **Dock tabs (mode-aware, opens on the right section):** 1 **Skeleton** (add bone, extrude, symmetrize, roll
  presets, auto-side/flip names, parent/disconnect, subdivide, align); 2 **Controls & Constraints** (constraint
  add buttons, the active bone's constraint stack, IK with pole, custom shape + colour, locks); 3 **Skin** (bind
  auto / envelope / empty, weight paint toggle, influence list with lock/solo, flood, smooth, normalize, limit
  total, clean, mirror, transfer); 4 **Drive** (shape keys + mirror, **Driven Key** helper, drivers); 5 **Test**
  (reset pose, copy/paste flipped, pose library, rest/pose toggle); 6 **Collections** (bone collections,
  selection sets); 7 All Settings. Channel Box stays available.
- **New tools:** joint tool (click to place a chain, snapping, X-mirror), Orient Joint (primary/secondary axis),
  control-shape library (creates widget meshes and assigns custom shape + colour), Driven Key (driver + keyed
  mapping curve), weight table for the active vertex (Component Editor substitute), naming validator.
- **Rigify** (bundled, off by default): one "Generate Rig" section that enables it on first use.
- **Keys:** Ctrl+E extrude bone, P / Shift+P parent / unparent bones, names in a marking menu (Ctrl+N is New Scene).

---

## Phase 5: Animation (F6)

Research: pose and key, scrub/play/step, blocking (stepped) -> spline -> polish, breakdowns/tweening, picking
controls (selection sets / picker), Graph Editor, Dope Sheet retiming, copy/paste/mirror poses, pose library,
motion paths, ghosting, auto-key and tangent toggles, NLA layering, world-space copy/paste, playblast.

**Layout:** large viewport + a camera view pane; one bottom editor tabbed between Graph Editor and Dope Sheet
(Ctrl+Space maximizes); Time Slider + range below. Playback redraw limited to viewports (Properties editors don't
redraw every frame).
- **Status Line:** Auto Key, key type (Keyframe / Breakdown / Extreme), default tangent (Stepped / Spline /
  Linear / Clamped), keying set, playback range, FPS, loop mode, Playblast.
- **Shelves:** Animate (Set Key, Key Translate/Rotate/Scale, Breakdown, Euler Filter, Stepped / Spline), Poses,
  Custom.
- **Dock tabs:** 1 **Channel Box** (keyed channel colours, custom properties like IK/FK as sliders); 2 **Pick**
  (selection sets + bone-collection picker buttons); 3 **Tween & Poses** (tween slider, Push, Relax, Breakdown,
  pose library grid, copy/paste flipped); 4 **Motion** (motion paths calculate/update/clear + range, ghost
  curves); 5 **Layers** (NLA-based layers: push down, add additive layer, tweak, bake); 6 **Playback**
  (range, FPS, loop mode, preroll, sync); 7 All Settings.
- **New tools:** `m3d.tween` modal slider (interpolates selected channels between previous and next key), object
  selection sets (Blender's are pose-only), Blocking / Polish presets (default interpolation + editor),
  playblast (`render.opengl` animation to a folder and open it).
- **Keys:** tween / push / relax on free keys (Blender's Shift+E / Ctrl+E / Alt+E clash with Maya keys); keep
  `,` `.` key jumps, Alt+V play, Ctrl+Left/Right jump by delta.

---

## Phase 6: Rendering (F7)

Research: camera framing, render still, IPR, lighting (lights + HDRI + exposure), materials, engine/samples/
denoise, colour management, output, passes/AOVs, view layers, light linking/shadow catcher, animation render.

**Layout:** 3D view in Rendered shading centre, Render View (Image Editor) beside it, dock right.
- **Status Line:** engine (Cycles / EEVEE), camera picker, quality preset (Draft / Medium / Final), Render,
  Render Animation, IPR, Render View.
- **Shelves:** Lights (Point, Spot, Area, Sun, HDRI sky), Render, Custom.
- **Dock tabs:** 1 **Camera** (camera select, focal length, DOF, resolution + %, safe frames, border); 2
  **Lighting** (light editor table: on/off, name, colour, power, shadows; HDRI picker with rotation/strength;
  exposure); 3 **Materials** (slots + main Principled inputs); 4 **Render** (engine, samples, denoise, quality
  presets); 5 **Output** (path, format, frame range, colour management); 6 **Passes & Layers** (passes, AOVs,
  light groups, view layers, holdout / indirect only, light linking); 7 **Advanced** (light paths, film,
  performance, simplify); 8 All Settings.
- **New tools:** light editor table, `m3d.hdri_setup` (environment texture + mapping + background, rotation),
  quality presets.
- **Keys:** Shift+F12 render, Ctrl+Shift+F12 render animation, Alt+F12 view render (F12 is taken).

---

## Order of work and review

| Phase | Content | Size |
|---|---|---|
| 0 | Framework: F1-F7, kinds, per-kind top rows and dock tabs, pages, custom shelf, tab menu | M |
| 1 | Sculpt | M |
| 2 | UV | S-M |
| 3a | Texture: workspace, painting, bake, export | M |
| 3b | Texture: layer stack | L |
| 4 | Rigging | L |
| 5 | Animation | M-L |
| 6 | Rendering | M |
| 7 | Docs, README videos for the new workspaces, release | S |

One phase at a time. A Sonnet agent implements each phase from this plan. I review the diff, run both test suites
and look at screenshots, send fixes back, and only then commit and start the next phase.
