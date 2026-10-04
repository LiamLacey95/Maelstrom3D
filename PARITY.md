# Parity report

*Autodesk and Maya are registered trademarks of Autodesk, Inc. Maelstrom3D is not affiliated with Autodesk; Maya is named here only to describe compatibility.*

How closely Maelstrom3D follows the Autodesk Maya workflow, element by element. Sources:

- Autodesk, [All Maya Hotkeys (Maya 2025)](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-KeyboardShortcuts/files/GUID-30CACC9D-8FBE-4B85-8A8F-C5ADF32DDD4E.htm)
- Autodesk, [Status line (Maya 2026)](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Basics/files/GUID-86E5CEDA-4100-40AE-8F95-346206CF8456.htm)
- Autodesk, [Marking Menus](https://help.autodesk.com/cloudhelp/2022/ENU/Maya-Basics/files/GUID-8BA1A3AA-4C44-4779-8B22-0AAE3627E8EB.htm)
- Autodesk, [Quick layout buttons](https://help.autodesk.com/cloudhelp/2016/ENU/Maya/files/GUID-693FBB4C-4010-4D55-8215-67FBE19114E7.htm)

Status: **Done** works like Maya · **Close** same job, Blender mechanics differ · **Missing** not ported (reason given).

## Interface

| Maya element | Status | In Maelstrom3D |
|---|---|---|
| Menu bar with menu sets (Modeling, Rigging, Animation, FX, Rendering) | Done | Top bar; menu set dropdown on the left |
| Menu bar, Status Line, shelf tabs, shelf as stacked rows | Done | Four rows across the top, like Maya |
| Status Line: menu set, New/Open/Save | Done | Second row of the top bar |
| Status Line: selection mode (object / component) | Done | |
| Status Line: selection masks | Done | Mesh, curve, light, camera, locator, joint selectable toggles |
| Status Line: selection lock, highlight selection | Missing | No Blender equivalent for lock |
| Status Line: snapping (grid, curve, point, view plane / live) | Done | Grid, edge, vertex, face + snapping on/off |
| Status Line: symmetry | Done | Active mesh X symmetry |
| Status Line: construction history on/off, inputs/outputs | Close | Blender history = modifiers; A + left click has Delete History |
| Status Line: render view, render, IPR, render settings | Done | IPR = rendered viewport; settings open the Render tab of the dock |
| Status Line: Hypershade button | Done | Opens the Hypershade (Shader Editor) window |
| Status Line: input box | Close | Rename only (no absolute/relative transform entry) |
| Status Line: sidebar buttons (Modeling Toolkit, Attribute Editor, Tool Settings, Channel Box) | Done | HumanIK missing (no HumanIK in Blender) |
| Shelf with tabs | Done | Full-width tab row and a row of large buttons: Curves/Surfaces, Poly Modeling, Sculpting, Rigging, Animation, Rendering, FX |
| Tool Box (select, lasso, paint, move, rotate, scale) | Close | Solid strip like Maya's; still lists extra Blender tools |
| Quick Layout buttons + Outliner button | Done | Under the toolbox: four view / single, maximize, Outliner |
| Viewport panel menus (View, Shading, Lighting, Show, Renderer, Panels) | Done | Blender's mode / transform / gizmo buttons removed from the panel bar |
| Viewport HUD: camera name, view axis | Done | `persp` / `top` / `front` / `side` bottom centre, axis triad bottom left |
| Panel toolbar icons | Done | Camera, grid, wireframe/shaded/textured/lit, wireframe on shaded, shadows, AO, X-ray, isolate |
| Channel Box (Translate/Rotate/Scale/Visibility, SHAPES, INPUTS) | Done | Lock toggle per channel; right-click a channel to key it |
| Channel Box: INPUTS editable (polyCube1 width, subdivisions) | Missing | Blender primitives have no live creation history |
| Layer Editor (V, P, T/R, create from selection) | Close | V and R (collections); no P (playback) |
| Attribute Editor | Done | Node tabs (transform, shape, inputs, material) across its header |
| Dock tabs | Close | Text tabs in the dock header (Channel Box / Layer Editor, Modeling Toolkit, Tool Settings, Attribute Editor) plus icon tabs on the right edge; Maya's are vertical text |
| Modeling Toolkit (selection, soft select, symmetry, mesh, components, tools) | Done | Dock tab |
| Tool Settings | Done | Dock tab |
| Outliner (DAG objects only) | Done | Flat object list; default camera is `persp`; new scene shows nothing |
| Time Slider with playback controls, current frame | Done | Controls below the slider, like Maya |
| Range Slider (playback range, fps, auto key) | Close | Start/end, preview range, fps menu, auto key; no separate animation-range bar |
| Command Line (MEL / Python) | Done | MEL by default (`polyCube -w 2;`), Python with `cmds`; Windows menu switches |
| Help Line | Done | Status bar |
| Hotbox (Space) | Close | Every menu in one popup; no N/E/S/W zone marking menus |
| Workspaces (Classic, Modeling, Sculpting, UV Editing, Rigging, Animation, Rendering...) | Done | |
| UV Editor + UV Toolkit | Done | See MAELSTROM3D.md |
| Hypershade | Close | Shader Editor (node graph) without the material browser |
| Script Editor | Close | Text editor + Command History |
| Y-up world, centimetres | Missing | Blender is Z-up; changing it needs deep core changes |
| Splash screen | Done | None at startup, like Maya |
| Square, flat widgets | Done | Near-square corners, Segoe UI font on Windows |
| Maya-style icon set | Missing | Autodesk's icons can't be copied; needs original artwork |
| App icon | Missing | Still Blender's |

## Marking menus

| Maya marking menu | Status |
|---|---|
| Right click on object: components, select, select all/hierarchy/similar, assign new/existing material | Done |
| Right click in component mode: component modes | Done (plus the full tool list for the selection, as requested) |
| Shift+right click, nothing selected: create polygon primitives | Done |
| Shift+right click, object: polygon tools (Combine, Separate, Smooth, Booleans, Mirror, Triangulate, Reduce...) | Done |
| Shift+right click, vertex / edge / face: component tools | Done |
| Ctrl+right click: convert selection | Done |
| Ctrl+Shift+right click: transform options (symmetry, soft select, preserve UVs, tweak) | Done |
| Q / W / E / R + left click: select / move / rotate / scale tool options | Done |
| A + left click: history operations | Done |
| H + left click: menu sets | Done |
| Shift+S + left click: keyframe | Done |
| Shift+S + middle click: tangents | Done |
| UV Editor right click / Shift+right click | Done |
| Hypershade / Node Editor / Script Editor marking menus | Missing |

## Hotkeys (Maya 2025 default set)

| Maya hotkey | Status | Note |
|---|---|---|
| Q W E R, T, Ctrl+T, Y | Done | T shows the transform tool |
| Hold J, Shift+J | Done / Missing | Relative snapping not ported |
| = / - manipulator size | Done | |
| D (hold), Insert | Done | |
| Return complete tool | Done | Blender native |
| Tab in-view editor | Missing | Blender uses the Adjust Last Operation panel |
| Ctrl+MMB drag move along normals | Done | Rotate / scale variants missing |
| Ctrl+Z, Ctrl+Y, Z, Shift+Z, G, Shift+G | Done | Shift+G does not use the mouse position |
| F8, F9, F10, F11 | Done | |
| F12 | Close | Switches to UV Editing (Blender edits UVs in the UV Editor) |
| Alt+F9 vertex face, Ctrl+I intermediate object | Missing | No Blender equivalent |
| P, Shift+P, Ctrl+G | Done | |
| Ctrl+D, Shift+D, Ctrl+Shift+D, Shift+drag manipulator | Done | Shift+drag: duplicate (objects) / extrude (components) |
| Ctrl+Shift+drag manipulator (slide) | Done | |
| Ctrl+X, Ctrl+C, Ctrl+V | Done | |
| Space tap / hold, Ctrl+Space | Done | |
| Alt+M hotbox style | Missing | |
| Ctrl+H, Alt+H, Ctrl+Shift+H, Ctrl+1, Shift+L | Done | Ctrl+Shift+H shows the last hidden objects |
| Shift+H show selection | Done | Select hidden objects in the Outliner, then Shift+H |
| 1 2 3, 4 5 6 7, Page Up / Down | Done | 0 (NURBS quality) not applicable |
| Alt+1 / 2 / 4 / 5 | Done | |
| Ctrl+N, O, S, Shift+S, Q, R | Done | |
| S, Shift+W / E / R, Ctrl+Shift+W / E / R, Alt+I | Done | |
| Alt+V, Alt+Shift+V, Alt+. / Alt+, , . / , | Done | |
| Ctrl+Alt+. / , (Graph Editor key selection), K virtual slider, Alt+J | Missing | |
| Time bookmarks (Alt+T, \|, : ...) | Missing | Blender markers could stand in |
| Alt+LMB / MMB / RMB tumble / track / dolly | Done | |
| \ 2D pan / zoom | Missing | |
| X, C, V hold snapping | Done | |
| < / > grow / shrink | Done | |
| Up / Down / Left / Right pickwalk | Done | Objects; component pickwalk missing |
| Alt+arrows nudge | Done | |
| Ctrl+A, A, Shift+A, F, Shift+F | Done | |
| [ / ] view undo | Done | |
| Shift+{ / Shift+} previous / next layout | Done | Cycles workspaces |
| Alt+B background | Done | Gradient, black, dark grey, light grey |
| F1 help, F2 F3 F4 F5 F6 menu sets | Done | F2 Modeling, F3 Rigging, F4 Animation, F5 FX, F6 Rendering |
| Ctrl+M main menu bar, Shift+M, Ctrl+Shift+M | Missing / Done / Done | |
| Ctrl+Shift+Q Quad Draw, Ctrl+Shift+X Multi-Cut | Done | |
| B (soft select radius / brush radius), Shift+B | Close | B tap toggles and B + drag sets soft select radius; brush radius in sculpt keeps Blender's F |
| Painting hotkeys (Alt+F, Alt+A, Alt+C, Alt+R, U, M, N, /, O) | Missing | Artisan / Paint Effects have no direct Blender match |
| ` / ~ / Ctrl+` subdiv proxy | Missing | 1 / 2 / 3 smooth preview covers the common case |
| L lock curve length | Missing | |

## Next steps (by value)

1. Live creation history for primitives (editable polyCube width/subdivisions in the Channel Box), e.g. Geometry Nodes primitives.
2. Hotbox zones (N/E/S/W marking menus around the hotbox).
3. Graph Editor hotkeys, time bookmarks via markers.
4. Component pickwalk.
5. Original Maya-style icon set and app icon; vertical text dock tabs (C rebuild).
