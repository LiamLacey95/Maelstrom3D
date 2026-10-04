#!/usr/bin/env sh
# Regenerate release/datafiles/userdef/userdef_default_theme.c from tools/m3d/theme.py.
# Usage: tools/m3d/regen_theme.sh <blender executable of the same major version>
set -e
BLENDER="$1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
BLENDER_USER_RESOURCES="$TMP" "$BLENDER" -b --factory-startup --python-exit-code 1 \
  --python "$ROOT/tools/m3d/theme.py" \
  --python-expr "import bpy; bpy.ops.wm.save_userpref()"
"$BLENDER" -b --factory-startup --python-exit-code 1 --python "$ROOT/tools/utils/blender_theme_as_c.py" -- "$(find "$TMP" -name userpref.blend | head -1)"
rm -rf "$TMP"
