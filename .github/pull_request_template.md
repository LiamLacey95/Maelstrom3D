Thanks for contributing to Maelstrom3D!

**What this changes and why** (link the issue if there is one):

**How it was tested:**
- [ ] `blender -b --factory-startup --python-exit-code 1 --python tools/m3d/test_m3d.py` ends with `FAILS: none`
- [ ] `blender --factory-startup --enable-event-simulate --python tools/m3d/gui_test.py -- <result file>` writes `FAILS: 'none'` (for UI changes)
- [ ] `MAELSTROM3D.md` is updated where labels or behaviour it documents changed

Maelstrom3D is a fork of Blender (branch `maelstrom3d`); changes to Blender itself belong upstream at projects.blender.org.
