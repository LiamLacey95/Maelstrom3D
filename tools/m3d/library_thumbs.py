# SPDX-License-Identifier: GPL-2.0-or-later
"""
Make the thumbnails of the Library's starter items (the tiles of the Assets panel) that come with the program.

    blender -b --factory-startup --python tools/m3d/library_thumbs.py -- [output folder]

The default folder is release/datafiles/m3d_library_thumbs (CMake installs it next to m3d_factory_layout.blend; m3d_library.py
looks there before it makes a thumbnail itself). Each file is <item>_<digest>.png, 128 px, named the way m3d_library.thumb_path names
the ones it makes: the digest is of the item and m3d_library.RIG_VERSION, so after an item or the preview look changes the old file is not
found any more and the program makes that thumbnail itself until this script is run again. Run it again after changing
m3d_library_data.py or the preview rig, and commit the folder (its PNGs are not in Git LFS: .gitattributes).

The thumbnails are the Cycles renders the Library makes on a timer (see m3d_library.py), all in one go. Takes about a minute.
"""

import glob
import os
import shutil
import sys
import tempfile

import bpy

import m3d_library as LB

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1
                      else os.path.join(HERE, "..", "..", "release", "datafiles", "m3d_library_thumbs"))

cache = tempfile.mkdtemp(prefix="m3d_thumbs_")
LB.library_dir = lambda create=False: cache   # (the thumbnails are made into an empty cache, not the user's)
LB._gen["shipped"] = False                    # (and none of the thumbnails that came with the program counts as made)
LB._user["entries"] = []                      # (the starters only: not the items of whoever runs this)

made = LB.generate_pending()
files = sorted(glob.glob(os.path.join(cache, "thumbs", "*.png")))
print("m3d_library_thumbs: made %d, %d starter items, failed %s" % (made, len(LB.STARTERS), sorted(LB._gen["failed"])))
if len(files) != len(LB.STARTERS):
    sys.exit("m3d_library_thumbs: %d thumbnails for %d items: not writing %s" % (len(files), len(LB.STARTERS), OUT))

os.makedirs(OUT, exist_ok=True)
for old in glob.glob(os.path.join(OUT, "*.png")):
    os.remove(old)
for path in files:
    shutil.copy(path, OUT)
total = sum(os.path.getsize(os.path.join(OUT, os.path.basename(f))) for f in files)
print("m3d_library_thumbs: %d files, %.0f KB in %s" % (len(files), total / 1024, OUT))
shutil.rmtree(cache, ignore_errors=True)
