# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Maya viewport heads-up display: the camera name at the bottom centre ("persp", "top", "front", "side")
and the view axis triad at the bottom left. Blender's own view-name text is turned off at startup.
"""

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

AXES = ((Vector((1, 0, 0)), (0.86, 0.22, 0.22), "x"), (Vector((0, 1, 0)), (0.33, 0.78, 0.25), "y"),
        (Vector((0, 0, 1)), (0.25, 0.45, 0.95), "z"))
ORTHO_NAMES = (((0, 0, 1), "top"), ((0, 0, -1), "bottom"), ((0, -1, 0), "front"), ((0, 1, 0), "back"),
               ((1, 0, 0), "side"), ((-1, 0, 0), "left"))


def camera_name(context, rv3d):
    """Panel camera: persp, top / front / side for orthographic views, or the camera looked through."""
    if rv3d.view_perspective == 'CAMERA':
        return context.scene.camera.name if context.scene.camera else "camera"
    if rv3d.view_perspective == 'PERSP':
        return "persp"
    toward_viewer = rv3d.view_rotation @ Vector((0, 0, 1))
    for axis, name in ORTHO_NAMES:
        if toward_viewer.dot(Vector(axis)) > 0.999:
            return name
    return "ortho"


def draw_hud():
    context = bpy.context
    region, rv3d = context.region, context.region_data
    if rv3d is None or not context.space_data.overlay.show_overlays:
        return
    scale = context.preferences.system.ui_scale
    font = 0

    # Camera name, bottom centre.
    blf.size(font, 13 * scale)
    name = camera_name(context, rv3d)
    width, _height = blf.dimensions(font, name)
    blf.color(font, 0.85, 0.85, 0.85, 1.0)
    blf.position(font, (region.width - width) / 2, 12 * scale, 0)
    blf.draw(font, name)

    # A camera view with no camera (the Animation workspace's camera pane).
    if rv3d.view_perspective == 'CAMERA' and context.scene.camera is None:
        blf.size(font, 15 * scale)
        text = "No camera: add one (Create > Camera)"
        width, _height = blf.dimensions(font, text)
        blf.color(font, 0.95, 0.75, 0.3, 1.0)
        blf.position(font, (region.width - width) / 2, region.height / 2, 0)
        blf.draw(font, text)
        blf.size(font, 13 * scale)

    # View axis triad, bottom left.
    origin = Vector((34 * scale, 34 * scale))
    length = 22 * scale
    rotation = rv3d.view_rotation.inverted()
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", 2.0 * scale)
    gpu.state.blend_set('ALPHA')
    blf.size(font, 11 * scale)
    for axis, color, label in AXES:
        tip = rotation @ axis
        end = origin + Vector((tip.x, tip.y)) * length
        shader.uniform_float("color", (*color, 1.0))
        batch_for_shader(shader, 'LINES', {"pos": [(*origin, 0), (*end, 0)]}).draw(shader)
        blf.color(font, *color, 1.0)
        blf.position(font, end.x + 3 * scale * (1 if tip.x >= 0 else -2), end.y + 2 * scale, 0)
        blf.draw(font, label)
    gpu.state.blend_set('NONE')


_handle = None


def register():
    global _handle
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw_hud, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
