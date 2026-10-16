# SPDX-FileCopyrightText: 2018-2023 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

from bpy.types import Header


class STATUSBAR_HT_header(Header):
    bl_space_type = 'STATUSBAR'

    def draw(self, context):
        layout = self.layout

        # Maelstrom3D: the keys of the active brush tool in Sculpt and Texture Paint, else the input status.
        from m3d_ui import draw_status_hints
        if not draw_status_hints(layout, context):
            # input status
            layout.template_input_status()

        layout.separator_spacer()

        # Messages
        layout.template_reports_banner()
        # Maelstrom3D: a command line result, or a note about a Python error.
        import m3d_help
        m3d_help.draw_status(layout)
        # Maelstrom3D: a background render's progress, textures a loaded file didn't find.
        import m3d_render
        m3d_render.draw_status(layout)

        # Progress Bar
        layout.template_running_jobs()

        layout.separator_spacer()

        row = layout.row()
        row.alignment = 'RIGHT'

        # Stats & Info
        layout.template_status_info()
        # Maelstrom3D: the version (Blender's own is off in the Maelstrom3D preferences).
        m3d_help.draw_version(layout, context)


classes = (
    STATUSBAR_HT_header,
)

if __name__ == "__main__":  # only for live edit.
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
