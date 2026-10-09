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
| Workspace Settings | **Settings** button next to the workspace picker in the Status Line (top right, same in every workspace): Reset Workspace (back to its factory layout, asks first), show / hide each dock tab of the workspace (also in the dock's own tab menu), Edit Custom Shelf, the workspace's entry mode, Keyboard Shortcuts (Preferences > Keymap), and **Save Layouts as Default** (saves every workspace's layout, and the open scene, as the startup file for new files; File > Defaults has Save Startup File and Load Factory Settings for all). Extra workspaces (Shading, Compositing...) show what applies | `m3d_workspace.py` (`M3D_PT_workspace_settings`), `m3d_ui.py` (`draw_workspace_picker`) |
| Viewport | Panel menus (View, Shading, Lighting, Show, Renderer, Panels) and panel toolbar only (Blender's menus under "..."), viewport HUD (camera name, axis triad) | `m3d_ui.py`, `m3d_hud.py`, `bl_ui/space_view3d.py` |
| Right-hand dock | Tabs on the right edge: Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, then the Attribute Editor tabs (Object, Modifiers, Material, ...) | `space_buttons.cc`, `buttons_context.cc`, `DNA_space_enums.h`, `rna_space.cc`, `m3d_mode.py` |
| Editor names | Attribute Editor, Shader Editor, Script Editor, Command Line, Command History, Time Editor | `rna_space.cc`, `node_shader_tree.cc` |
| Marking menus | RMB, Shift+RMB, Ctrl+RMB in the viewport; RMB, Shift+RMB in the UV Editor; Space hotbox | `m3d_mode.py`, `m3d_uv.py` |
| UV editing | UV workspace (F3): dock tabs, Status Line and shelf for Cut/Sew/Unfold/Optimize/Layout, texel density, Auto Unwrap, UDIMs, checker map; sidebar UV Toolkit in other workspaces | `scripts/startup/m3d_uv.py` |
| Texturing | Texture workspace (F4): brush tray, paint channels, Bake, Export, Display, Status Line and shelves; paint layer stack, painted images are saved or packed with the file | `scripts/startup/m3d_texture.py`, `scripts/startup/m3d_layers.py` |
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
| Brush tray (left) | Active brush and its picker, a grid of 15 brushes (Draw, Clay Strips, Clay, Smooth, Grab, Elastic Grab, Snake Hook, Inflate/Deflate, Pinch/Magnify, Crease Sharp, Flatten/Contrast, Scrape/Fill, Layer, Mask, Face Set Paint), Size, Strength, Add / Subtract, Mirror X/Y/Z. Closed panels: Brush Settings, Falloff, Stroke, Texture, Cursor, Advanced |
| Status Line | Object / Sculpt Mode, face count, Multires level, Dyntopo, Mirror X/Y/Z, Auto-Masking, Mask and Face Set overlays, matcap picker |
| Shelves | Sculpt (the brushes), Remesh (Voxel Remesh and size, QuadriFlow, Multires level up / down, Apply Base), Mask (Fill, Clear, Invert, Grow, Shrink, Sharpen, From Cavity, Hide Masked), Custom |
| Geometry tab | Multires (Subdivide, Simple, Linear, level sliders, Delete Higher, Unsubdivide, Apply Base), Voxel Remesh, QuadriFlow, Dyntopo. Options that cannot work together (Dyntopo and Multires) are greyed with the reason |
| Mask tab | Fill, Clear, Invert, filters (Smooth, Sharpen, Grow, Shrink, Contrast), From Cavity / Boundary, Box / Lasso / Line / Polyline Mask, Mask by Color, Hide Masked / Show |
| Face Sets tab | Initialize (Loose Parts, Materials, Normals, UV Seams, Creases, Sharp Edges, ...), Create from Mask / Visible / Selection, Grow, Shrink, Fair, Delete Geometry, Show All, Randomize Colors |
| Deform tab | Mesh filters (Smooth, Inflate, Relax, Surface Smooth, Sharpen, Enhance Details, Sphere, Random, Scale), Symmetrize, Set Pivot, trim tools |
| Paint tab | Color brushes, color picker, palette, Add Color Attribute, color filters |
| Display tab | Matcap / studio light, color, cavity, Mask and Face Set overlay opacity, wireframe, low resolution and delayed updates |
| Objects tab | The scene's meshes: show / hide, pick, solo, append a duplicate; add a sphere, cube or cylinder |

Tool buttons (mesh filters, trims, Grow / Shrink face set, color filters, Mask by Color) pick the tool: drag in the
viewport afterwards. Shift+1 ... Shift+7 pick Draw, Clay Strips, Smooth, Grab, Inflate/Deflate, Pinch/Magnify, Crease
Sharp. Expand stays on Shift+A (mask) and Shift+W (face sets) over the mesh. Space (hold) lists the brushes first.
"All Settings" at the end of each tab row is Blender's stock Properties tabs (symmetry locks, tiling, gravity, ...).

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
| Layers tab | The layer stack of the active material: a list (top layer first: eye, name, blend mode, opacity, channel letters), buttons to add a Paint Layer or Fill Layer, move, duplicate, delete, **Merge Down** and **Flatten**; below it the active layer's settings (name, blend, opacity, channels, fill values), its Mask, and closed panels Channels (the paint slots by channel) and All Paint Slots |
| Brush tab | Stroke and Stabilize, Falloff, Texture, Texture Mask, Stencil, Clone, Options (seam bleed, dither, cavity mask), Cursor, Color Palette |
| Shelf tab | All texture brushes (also the pressure and pixel art ones) and Blender's brush library popover (favorites live there); materials marked as assets, applied with a click, and a button to mark the active one |
| Bake tab | High Poly picker (or Use Selected as High Poly), maps Normal, AO, Curvature, Position, Thickness, size, margin, ray settings, **Bake**, and the list of baked images |
| Export tab | Presets glTF, Unreal, Unity; folder; size; **Export**; Save All Images |
| Display tab | Material Preview environment (HDRI, rotation, intensity), Channel View of each channel, UV checker map, wireframe |

A channel is a paint slot of the active material: the first click on **Base Color**, **Roughness**, **Metallic**,
**Normal**, **Height** or **Emission** adds an image of the "new slot" size (Non-Color for everything except Base Color
and Emission) and plugs it into the shader; later clicks only pick it. C and Shift+C step to the next / previous
channel, `[` and `]` change the brush size, Shift+X swaps the two colors (plain X is hold-to-snap in the viewport, so
it is not used for painting). Channel View shows the picked channel flat in the 3D view and goes back on the next click.

**Bake** needs Cycles: it switches to it, bakes every ticked map into an image named `<mesh>_<Map>` (kept with the file)
and switches back; the mesh's materials are not changed (a temporary material takes the bake and is removed). With a
high-poly mesh set, detail is baked from it onto the active mesh (selected to active); without one, the mesh bakes
itself. Curvature uses the shader's Pointiness (needs enough polygons), Thickness uses ambient occlusion from inside
the mesh (closed meshes only; white where the mesh is thicker than the Thickness Distance), Position is scaled to 0-1
within the object's bounds. The window waits while it bakes.

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
no memory. A Fill Layer is a value or color over the whole mesh; limit it with a **Mask**. A mask is a greyscale image
(white shows the layer, black hides it); **Paint Mask** sends strokes to the mask instead of the channel (on a Fill
Layer strokes always go to its mask; a Fill Layer without a mask can be turned into a Paint Layer with Convert, and
until then the brush is aimed at a tiny hidden scratch image so no layer is painted by mistake).
The brush always paints the active layer's image of the active channel (Status Line buttons, C / Shift+C). Blend modes
are Mix, Multiply, Add, Overlay, Screen, Soft Light, Subtract, Difference, Color, Darken and Lighten (the Normal channel
always mixes). Double-click a name to rename it. In the shader each channel has a frame with one Image Texture and Mix
node per layer; only nodes made by the stack are ever changed. **Merge Down** combines a layer into the one below with
its blend mode, opacity and mask baked in (exact when the lower layer is opaque or the upper one uses Mix; the merged
layer keeps the lower layer's blend mode); **Flatten** replaces the stack by one layer holding what it looks like.
Export, glTF included, uses the flattened visible stack of each channel and does not change the layers. The tab warns
when the layer images add up to more than twelve 4K images of memory.

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
