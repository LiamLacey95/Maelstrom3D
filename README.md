# MayaBlender

**Blender 5.2, reworked to look and work like Autodesk Maya.** For Maya users who want Blender without relearning
every hotkey, menu and panel. This is a fork of [Blender](https://www.blender.org) (branch `maya`, based on the
`v5.2.2` release). Everything Maya-like is on by default.

**Download (Windows x64):** see [Releases](../../releases). Unzip and run `blender.exe`.

| | |
|---|---|
| ![Interface](docs/media/interface.gif) | ![Modeling](docs/media/modeling.gif) |
| **Maya interface:** Maya Classic layout, menu sets (F2-F6), shelf tabs, Space for four view. [MP4](docs/media/interface.mp4) | **Modeling like Maya:** Shift+drag the manipulator to extrude, right-click for every tool on the selected faces, 1/2/3 smooth preview. [MP4](docs/media/modeling.mp4) |
| ![Marking menus](docs/media/marking_menus.gif) | ![Dock](docs/media/dock.gif) |
| **Marking menus:** W + left click, Shift / Ctrl+Shift right-click, Space hotbox. [MP4](docs/media/marking_menus.mp4) | **Right-hand dock:** Channel Box / Layer Editor, Attribute Editor (Ctrl+A), Modeling Toolkit. [MP4](docs/media/dock.mp4) |
| ![UV editing](docs/media/uv.gif) | ![MEL](docs/media/mel.gif) |
| **UV editing:** F12, UV Toolkit, Automatic / Layout, checker map. [MP4](docs/media/uv.mp4) | **MEL command line:** `polyCube -w 3 -n floor;`, plus `maya.cmds` in Python. [MP4](docs/media/mel.mp4) |

## What you get

- **Maya interface:** menu bar with menu sets (Modeling, Rigging, Animation, FX, Rendering), Maya Status Line,
  shelf tabs, viewport panel menus and toolbar, Quick Layout buttons, Outliner on the left, Time Slider with fps,
  MEL/Python command line, Maya Classic / Modeling / Sculpting / UV Editing / Rigging / Animation / Rendering workspaces.
- **Right-hand dock:** Channel Box / Layer Editor, Modeling Toolkit, Tool Settings and the Attribute Editor as tabs.
- **Maya hotkeys:** QWERT, Alt+mouse tumble/track/dolly, F/A framing, F8-F12, 1-7, D pivot, Ctrl+D/Shift+D, Ctrl+G,
  P, X/C/V snapping, Z undo, G repeat, [ ] view undo, pickwalk, Ctrl+A, Space hotbox and more.
- **Marking menus:** right-click, Shift/Ctrl/Ctrl+Shift right-click, Q/W/E/R/A/H + left click, Shift+S keys and tangents.
- **Maya look:** Maya greys and highlight colour, gradient viewport, Maya selection and component colours,
  Maya's camera field of view, empty startup scene.
- **UV workflow:** UV Toolkit, Cut / Sew / Unfold / Layout, checker map, UV marking menus.
- **Scripting:** a `maya.cmds` subset (`polyCube`, `move`, `setAttr`, `select`, `ls`, ...) and MEL in the command line.

Guides:
- [MAYABLENDER.md](MAYABLENDER.md): full guide and change log.
- [MAYABLENDER_SHORTCUTS.md](MAYABLENDER_SHORTCUTS.md): every changed shortcut, before and after.
- [MAYA_PARITY.md](MAYA_PARITY.md): element-by-element comparison with Maya 2025.

## Build from source (Windows)

Needs Visual Studio 2022 or 2026 with C++, CMake and Git LFS (Blender's
[build guide](https://developer.blender.org/docs/handbook/building_blender/windows/)).

```
git clone -b maya https://github.com/LiamLacey95/MayaBlender.git
cd MayaBlender
git -c submodule."lib/windows_x64".update=checkout submodule update --init --depth 1 lib/windows_x64
make.bat 2026
```

Large files come from Blender's own LFS server (see `.lfsconfig`). Self-checks:
`blender -b --factory-startup --python-exit-code 1 --python tools/maya/test_maya.py`.

## Credits, license, trademarks

MayaBlender is a modified version of Blender by the Blender Foundation and contributors, released under the
GNU GPL v2 or later like Blender itself (see [COPYING](COPYING) and [doc/license](doc/license)). The full source
for every release is this repository.

MayaBlender is an independent project. It is not affiliated with, endorsed by or sponsored by Autodesk, Inc. or the
Blender Foundation. Autodesk and Maya are registered trademarks of Autodesk, Inc. Blender is a registered trademark
of the Blender Foundation. Names are used only to describe compatibility.

Blender's original read-me: [README.blender.md](README.blender.md).
