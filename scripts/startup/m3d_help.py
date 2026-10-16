# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Files, help and trust for Maelstrom3D: the version label, the log file and the status bar note, the Help menu's commands
(Report a Bug, logs, About, Check for Updates), the card after a session that ended unexpectedly, File > Defaults (reset,
settings export / import), settings carried to a new version folder, and the command line strip (Windows > Command Line).
Nothing is ever sent anywhere: Report a Bug only opens a pre-filled page in the browser, and Check for Updates (only with
online access allowed) only reads the list of releases.
"""

import os
import sys
import time
from functools import cache

import bpy
from bpy.types import Operator

import m3d_user

REPO = "https://github.com/LiamLacey95/Maelstrom3D"
DOCS = REPO + "/blob/maelstrom3d/"
BLENDER_VERSION = "%d.%d.%d" % bpy.app.version[:3]


# -----------------------------------------------------------------------------
# Version

@cache
def version_tag():
    """The alpha tag in datafiles/m3d_version.txt ("m3d.5"; the build installs it), "dev" without one."""
    path = os.path.join(bpy.utils.system_resource('DATAFILES'), "m3d_version.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"


def version_label():
    return "Maelstrom3D alpha %s (Blender %s)" % (version_tag(), BLENDER_VERSION)


# -----------------------------------------------------------------------------
# Status bar note: a command line result, or a Python error in one of our panels

_note = {"text": "", "icon": 'NONE', "until": 0.0}


def show_note(text, icon='INFO', seconds=8.0):
    """Show `text` in the status bar for a few seconds."""
    _note.update(text=text, icon=icon, until=time.monotonic() + seconds)
    import threading
    if threading.current_thread() is threading.main_thread():
        bpy.app.timers.register(_redraw_status, first_interval=0.0)
        bpy.app.timers.register(_redraw_status, first_interval=seconds + 0.1)


def note_text():
    return _note["text"] if time.monotonic() < _note["until"] else ""


def _redraw_status():
    """Redraw the status bar (not in screen.areas): it redraws when a view layer's name changes (space_statusbar.cc)."""
    bpy.msgbus.publish_rna(key=(bpy.types.ViewLayer, "name"))
    return None


def draw_status(layout):
    """The note (while it lasts), then the version at the right end (STATUSBAR_HT_header)."""
    text = note_text()
    if text:
        layout.label(text=text, icon=_note["icon"], translate=False)


def draw_version(layout, context):
    """A newer alpha's link, the version; on a narrow window the version gives way to a note while that shows."""
    from m3d_ui import status_narrow
    newer = newer_release()
    if newer is not None:
        layout.operator("wm.url_open", text="New alpha %s" % newer[0], icon='URL', emboss=False).url = newer[1]
    if not (note_text() and status_narrow(context, 1700)):
        layout.label(text=version_label(), translate=False)


# -----------------------------------------------------------------------------
# Log file: what goes to stderr (Python errors) is copied to m3d_log.txt in the user config folder

LOG_NAME, OLD_LOG_NAME, LOG_MAX = "m3d_log.txt", "m3d_log.old.txt", 1_000_000


def config_dir():
    return bpy.utils.user_resource('CONFIG')


def log_path():
    cfg = config_dir()
    return os.path.join(cfg, LOG_NAME) if cfg else ""


class LogTee:
    """sys.stderr that also appends to the log file (`path`, none: no file), rolled to m3d_log.old.txt past LOG_MAX, and
    shows a status bar note when a traceback passes through one of our files. The file is opened per write (they are rare),
    so it is never held open."""

    def __init__(self, stream, path):
        self.stream, self.path, self.started, self.line = stream, path, False, ""

    def write(self, text):
        n = self.stream.write(text) if self.stream is not None else len(text)
        try:
            self._log(text)
            self._watch(text)
        except Exception:
            pass   # (logging must never break the output)
        return n

    def _log(self, text):
        if not self.path:
            return
        if os.path.exists(self.path) and os.path.getsize(self.path) > LOG_MAX:
            os.replace(self.path, os.path.join(os.path.dirname(self.path), OLD_LOG_NAME))
        with open(self.path, "a", encoding="utf-8", errors="replace") as fh:
            if not self.started:
                self.started = True
                fh.write("\n=== %s, %s ===\n" % (version_label(), time.strftime("%Y-%m-%d %H:%M:%S")))
            fh.write(text)

    def _watch(self, text):
        """A traceback line in one of our modules ('File "...m3d_texture.py", line 9, in draw'): the note names it."""
        import re
        self.line += text
        *lines, self.line = self.line.split("\n")
        for line in lines:
            found = re.search(r'File "[^"]*[\\/](m3d_\w+)\.py", line \d+, in ([\w<>]+)', line)
            if found:
                show_note("Something went wrong in %s.py (%s): Help > Report a Bug" % found.groups(), 'ERROR', 15.0)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def log_tail(lines=40):
    """The last lines of the log file, as text ("" without one)."""
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return ""


# -----------------------------------------------------------------------------
# Report a Bug: a new GitHub issue pre-filled with the version, OS, GPU and the log's last lines

ISSUES = REPO + "/issues/new"
MAX_URL = 7500   # (GitHub refuses much longer links)


def system_info():
    """(OS, GPU) as text."""
    import platform
    os_name = "%s %s (%s)" % (platform.system(), platform.release(), platform.version())
    try:
        import gpu
        gpu_name = "%s %s (%s)" % (gpu.platform.vendor_get(), gpu.platform.renderer_get(), gpu.platform.backend_type_get())
    except Exception:
        gpu_name = "unknown"
    return os_name, gpu_name


def bug_report_url(version, os_name, gpu_name, log):
    """The new-issue link of the bug form (.github/ISSUE_TEMPLATE/bug.yml), its fields filled in. The log loses its first
    lines until the link is short enough."""
    from urllib.parse import urlencode
    lines = log.splitlines()
    while True:
        query = {"template": "bug.yml", "version": version, "os": os_name, "gpu": gpu_name, "log": "\n".join(lines)}
        url = ISSUES + "?" + urlencode(query)
        if len(url) <= MAX_URL or not lines:
            return url
        lines.pop(0)


class M3D_OT_report_bug(Operator):
    """Open a new bug report on GitHub in your browser, filled in with the version, your system and the log's last lines
    (nothing is sent until you submit it there)"""
    bl_idname = "m3d.report_bug"
    bl_label = "Report a Bug"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Report a Bug", confirm_text="Open in Browser",
            message="Opens a bug report on GitHub with the version, your OS and graphics card and the last lines of the log "
                    "filled in. You can read and edit it there; nothing is sent until you submit it.")

    def execute(self, _context):
        bpy.ops.wm.url_open(url=bug_report_url(version_label(), *system_info(), log_tail()))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Logs: the crash log Blender writes into the temp folder, our log file's folder

def temp_base():
    """The temp folder (Preferences > File Paths, else the system's): auto saves, quit.blend and crash logs go there.
    bpy.app.tempdir is this session's folder inside it."""
    return os.path.dirname(os.path.normpath(bpy.app.tempdir))


def crash_log():
    """The newest crash log ("<file>.crash.txt") in the temp folder, or None."""
    base = temp_base()
    try:
        found = [os.path.join(base, n) for n in os.listdir(base) if n.endswith(".crash.txt")]
    except OSError:
        return None
    return max(found, key=os.path.getmtime) if found else None


class M3D_OT_open_log(Operator):
    bl_idname = "m3d.open_log"
    bl_label = "Open Log"

    what: bpy.props.EnumProperty(items=(('CRASH', "Crash Log", ""), ('FOLDER', "Log Folder", "")))

    @classmethod
    def description(cls, _context, props):
        if props.what == 'CRASH':
            return "Open the crash log of the last crash (a text file in the temp folder)"
        return "Open the folder of the log file (m3d_log.txt: the errors of recent sessions) and your settings"

    def execute(self, _context):
        if self.what == 'CRASH':
            path = crash_log()
            if path is None:
                self.report({'INFO'}, "No crash log in %s: no crash since the temp folder was emptied" % temp_base())
                return {'CANCELLED'}
        else:
            path = config_dir()
            os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


class M3D_OT_about(Operator):
    """Version, license and links"""
    bl_idname = "m3d.about"
    bl_label = "About Maelstrom3D"

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=420)

    def draw(self, _context):
        col = self.layout.column()
        col.label(text=version_label(), icon='INFO', translate=False)
        col.label(text="A 3D creation suite based on Blender, with a classic studio workflow.")
        col.label(text="Early alpha: keep backups of your work.")
        col.label(text="Free software under the GNU GPL (version 2 or later).")
        col.separator()
        row = col.row()
        row.operator("wm.url_open", text="Website", icon='URL').url = REPO
        row.operator("wm.url_open", text="Guide", icon='HELP').url = DOCS + "MAELSTROM3D.md"
        row.operator("m3d.report_bug", text="Report a Bug", icon='ERROR')

    def execute(self, _context):
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Check for Updates: the newest release on GitHub (every release is an alpha pre-release), read only while Preferences >
# System > Allow Online Access is on: by itself at most once a week, from Help > Check for Updates any time. The status bar
# links a newer alpha. Nothing but the release list is fetched, in a thread with a short timeout (the UI never waits).

RELEASES_API = "https://api.github.com/repos/LiamLacey95/Maelstrom3D/releases"
RELEASES = REPO + "/releases"
WEEK = 7 * 24 * 3600
_check = {"thread": None, "result": None, "manual": False}


def online():
    """Preferences > System > Allow Online Access (or --online-mode); the tests replace this."""
    return bpy.app.online_access


def fetch(url):
    """The body of a GET of `url` (the tests replace this: they never go online)."""
    import urllib.request
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Maelstrom3D"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read(2_000_000)


def tag_number(tag):
    """"m3d.12" or the release tag "v5.2.2-m3d.12-alpha" -> 12; None for "dev", "m3d.13 (dev)" or any other tag."""
    import re
    found = re.fullmatch(r"(?:v[\d.]+-)?m3d\.(\d+)(?:-[a-z]+)?", tag or "")
    return int(found.group(1)) if found else None


def latest_release():
    """(tag, page) of the newest release (the highest m3d.N; drafts left out). ValueError for an answer without one."""
    import json
    found = [(tag_number(r.get("tag_name")), r.get("tag_name"), r.get("html_url"))
             for r in json.loads(fetch(RELEASES_API)) if isinstance(r, dict) and not r.get("draft")]
    found = [f for f in found if f[0] is not None]
    if not found:
        raise ValueError("no Maelstrom3D release found")
    _n, tag, page = max(found)
    return tag, page if isinstance(page, str) and page.startswith(REPO + "/") else RELEASES   # (only our pages are linked)


def newer_release():
    """(tag, page) of the last checked release when it is newer than this version, else None (a dev build: None)."""
    found = m3d_user.data().get("update")
    ours = tag_number(version_tag())
    if not isinstance(found, dict) or ours is None or (tag_number(found.get("tag")) or 0) <= ours:
        return None
    return found["tag"], found.get("page") or RELEASES


def _check_thread():
    try:
        _check["result"] = latest_release()
    except Exception as err:   # (offline, a timeout, a changed answer: said when asked, else ignored)
        _check["result"] = err


def start_update_check(manual=False):
    """Ask GitHub for the newest release in a thread; False (nothing sent) without online access or while one runs."""
    if not online() or (_check["thread"] is not None and _check["thread"].is_alive()):
        return False
    import threading
    _check.update(result=None, manual=manual, thread=threading.Thread(target=_check_thread, daemon=True))
    _check["thread"].start()
    if bpy.app.timers.is_registered(_check_wait):
        bpy.app.timers.unregister(_check_wait)
    bpy.app.timers.register(_check_wait, first_interval=0.5)
    return True


def _check_wait():
    if _check["thread"].is_alive():
        return 0.5
    finish_update_check()
    return None


def finish_update_check():
    """The thread is done: keep its answer (m3d_user.json) and, when asked from the menu, say what it found."""
    result, manual = _check["result"], _check["manual"]
    if isinstance(result, Exception):
        if manual:
            show_note("Could not check for updates: %s" % result, 'ERROR', 10.0)
        return
    tag, page = result
    m3d_user.data()["update"] = {"checked": time.time(), "tag": tag, "page": page}
    m3d_user.save()
    if newer_release():
        show_note("Maelstrom3D alpha %s is out: the link is at the right end of the status bar" % tag, 'INFO', 15.0)
    elif manual:
        show_note("You have the newest alpha (%s)" % version_tag(), 'INFO', 8.0)
    else:
        _redraw_status()


def auto_update_check():
    """At startup: check when the last check is a week old (only with online access)."""
    found = m3d_user.data().get("update")
    checked = found.get("checked", 0) if isinstance(found, dict) else 0
    if not isinstance(checked, (int, float)) or time.time() - checked >= WEEK:
        start_update_check()


class M3D_OT_check_updates(Operator):
    """Look for a newer alpha on GitHub (needs Preferences > System > Allow Online Access; only the list of releases is
    read). With online access on, Maelstrom3D also looks once a week by itself"""
    bl_idname = "m3d.check_updates"
    bl_label = "Check for Updates"

    def execute(self, context):
        if not online():
            self.report({'WARNING'}, "Checking for updates needs Preferences > System > Allow Online Access")
            bpy.ops.screen.userpref_show(section='SYSTEM')
            return {'CANCELLED'}
        if start_update_check(manual=True):
            self.report({'INFO'}, "Checking for updates...")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# The last session ended unexpectedly: its auto save is newer than the last normal quit

def crash_autosave():
    """The newest auto save in the temp folder newer than quit.blend (a normal quit deletes the session's auto save, so
    one left over is what a crash leaves), not this session's and not offered before; None otherwise."""
    base, pid = temp_base(), os.getpid()
    try:
        found = [os.path.join(base, n) for n in os.listdir(base)
                 if n.endswith("_autosave.blend") and n != "%d_autosave.blend" % pid and not n.endswith("_%d_autosave.blend" % pid)]
    except OSError:
        return None
    if not found:
        return None
    path = max(found, key=os.path.getmtime)
    quit_ = os.path.join(base, "quit.blend")
    if os.path.exists(quit_) and os.path.getmtime(quit_) >= os.path.getmtime(path):
        return None
    if m3d_user.data().get("recover_offered") == [path, os.path.getmtime(path)]:
        return None
    return path


class M3D_OT_recover_card(Operator):
    """The last session ended unexpectedly: open its auto save"""
    bl_idname = "m3d.recover_card"
    bl_label = "Recover Auto Save"
    bl_options = {'INTERNAL'}

    filepath: bpy.props.StringProperty()

    def invoke(self, context, event):
        when = time.strftime("%H:%M on %d %b", time.localtime(os.path.getmtime(self.filepath)))
        return context.window_manager.invoke_confirm(
            self, event, title="Last session ended unexpectedly", confirm_text="Recover Auto Save", icon='WARNING',
            message="An auto save from %s (%s) is newer than your last quit. Open it? Later: File > Recover > Auto Save."
                    % (when, os.path.basename(self.filepath)))

    def execute(self, _context):
        return bpy.ops.wm.recover_auto_save(filepath=self.filepath)


def offer_recovery():
    """At startup: the card when a crash left an auto save (asked once per auto save)."""
    path = crash_autosave()
    if path is None:
        return
    m3d_user.data()["recover_offered"] = [path, os.path.getmtime(path)]
    m3d_user.save()
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.m3d.recover_card('INVOKE_DEFAULT', filepath=path)


# -----------------------------------------------------------------------------
# A new version folder (the next Blender base version): the previous one's settings come along once

def carry_settings():
    """First start in a new version folder: copy the previous version's settings (preferences, m3d_user.json, startup
    file: the whole config folder) like Blender's splash offers. True when copied."""
    if not bpy.ops.preferences.copy_prev.poll():
        return False
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.preferences.copy_prev()
    m3d_user.reset_cache()
    show_note("Settings carried over from the previous version", 'INFO', 15.0)
    return True


def _startup():
    # A headless or --factory-startup session never touches the user's settings or offers their auto saves.
    if not (bpy.app.background or bpy.app.factory_startup) and bpy.context.window_manager.windows:
        try:
            carry_settings()
            offer_recovery()
            auto_update_check()
        except Exception:
            import traceback
            traceback.print_exc()
    return None


# -----------------------------------------------------------------------------
# File > Defaults: layouts, resets, settings export / import

class M3D_OT_save_layouts_default(Operator):
    """Save the layouts of every workspace as what new files start with"""
    bl_idname = "m3d.save_layouts_default"
    bl_label = "Save Layouts as Default"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Save Layouts as Default", confirm_text="Save",
            message="New files will start with these layouts, and with what this scene holds now. "
                    "File > Defaults > Load Factory Layouts brings the factory ones back.")

    def execute(self, _context):
        bpy.ops.wm.save_homefile()
        self.report({'INFO'}, "New files start with these layouts")
        return {'FINISHED'}


# m3d_user.json keys that Reset Shelves & Docks clears (Reset Everything clears all but the preferences version).
SHELF_KEYS = ("shelf", "dock", "hidden_tabs")


def backup_user_file():
    """Copy m3d_user.json to m3d_user.json.bak (before a reset). False without one."""
    import shutil
    path = m3d_user._path()
    if not (path and os.path.exists(path)):
        return False
    shutil.copy2(path, path + ".bak")
    return True


def reset_user_settings(everything):
    """Shelves and docks back to the factory ones (`everything`: also the render presets and the other choices kept in
    m3d_user.json, and the layouts for new files: startup.blend becomes startup.blend.bak). Backups are kept."""
    backup_user_file()
    root = m3d_user.data()
    for key in list(root):
        if key in SHELF_KEYS or (everything and key != "prefs_version"):
            del root[key]
    m3d_user.save()
    if everything:
        startup = os.path.join(config_dir(), "startup.blend")
        if os.path.exists(startup):
            os.replace(startup, startup + ".bak")


RESET_MESSAGES = {
    'PREFS': ("Reset Preferences", "Preferences go back to Maelstrom3D's factory ones (and are saved)."),
    'SHELVES': ("Reset Shelves & Docks", "Your Custom shelf buttons, dock tabs and moved or hidden panels go back to the "
                "factory ones. A copy is kept (m3d_user.json.bak in the settings folder)."),
    'ALL': ("Reset Everything", "Preferences, shelves, docks, your render presets and the layouts of new files go back to "
            "the factory ones, and a new scene opens. Copies are kept (.bak files in the settings folder)."),
}


class M3D_OT_reset_settings(Operator):
    bl_idname = "m3d.reset_settings"
    bl_label = "Reset Settings"

    what: bpy.props.EnumProperty(items=[(k, title, "") for k, (title, _msg) in RESET_MESSAGES.items()])

    @classmethod
    def description(cls, _context, props):
        return RESET_MESSAGES[props.what][1]

    def invoke(self, context, event):
        title, message = RESET_MESSAGES[self.what]
        return context.window_manager.invoke_confirm(self, event, title=title, message=message, confirm_text="Reset",
                                                     icon='WARNING')

    def execute(self, context):
        if self.what in {'SHELVES', 'ALL'}:
            reset_user_settings(self.what == 'ALL')
        if self.what in {'PREFS', 'ALL'}:
            bpy.ops.wm.read_factory_userpref()
            bpy.ops.wm.save_userpref()
        if self.what == 'ALL':
            bpy.ops.wm.read_homefile('INVOKE_DEFAULT', use_factory_startup=True, app_template="")   # (asks about unsaved work)
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
        self.report({'INFO'}, RESET_MESSAGES[self.what][0] + ": done")
        return {'FINISHED'}


# Files of the config folder that are not settings.
_NOT_SETTINGS = (LOG_NAME, OLD_LOG_NAME)
SETTINGS_FILES = ("userpref.blend", "startup.blend", "m3d_user.json")   # (a settings zip has at least one)
MAX_IMPORT = 200 * 1024 * 1024


def export_settings(zip_path, cfg):
    """Zip the config folder `cfg` (preferences, startup file, m3d_user.json, recent files...; not the logs or backups).
    Returns the names written."""
    import zipfile
    names = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, _dirs, files in os.walk(cfg):
            for name in files:
                if name in _NOT_SETTINGS or name.endswith((".bak", ".tmp", ".zip")):
                    continue
                path = os.path.join(folder, name)
                arc = os.path.relpath(path, cfg).replace("\\", "/")
                zf.write(path, arc)
                names.append(arc)
    return names


def import_settings(zip_path, cfg):
    """Unpack a settings zip into the config folder `cfg`, after zipping what is there to m3d_settings_backup.zip.
    Raises ValueError for a zip that isn't settings or has paths outside the folder."""
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        members = [i for i in zf.infolist() if not i.is_dir()]
        for info in members:
            parts = info.filename.replace("\\", "/").split("/")
            if info.filename.startswith(("/", "\\")) or ":" in info.filename or ".." in parts or "" in parts:
                raise ValueError("unsafe path in the zip: " + info.filename)
        if not any(i.filename in SETTINGS_FILES for i in members):
            raise ValueError("not a Maelstrom3D settings file (no userpref.blend, startup.blend or m3d_user.json)")
        if sum(i.file_size for i in members) > MAX_IMPORT:
            raise ValueError("too big for a settings file")
        os.makedirs(cfg, exist_ok=True)
        export_settings(os.path.join(cfg, "m3d_settings_backup.zip"), cfg)
        for info in members:
            path = os.path.join(cfg, *info.filename.replace("\\", "/").split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with zf.open(info) as src, open(path, "wb") as dst:
                dst.write(src.read())
    return [i.filename for i in members]


class M3D_OT_settings_export(Operator):
    """Save your settings (preferences, layouts for new files, shelves, docks, render presets) in a zip file, to take
    them to another computer or between the installed and the portable Maelstrom3D"""
    bl_idname = "m3d.settings_export"
    bl_label = "Export Settings"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.zip", options={'HIDDEN'})

    def invoke(self, context, _event):
        self.filepath = "Maelstrom3D_settings.zip"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, _context):
        path = bpy.path.ensure_ext(self.filepath, ".zip")
        try:
            bpy.ops.wm.save_userpref()
        except RuntimeError:
            pass   # (a --factory-startup session: the saved preferences go as they are)
        m3d_user.save()
        try:
            names = export_settings(path, config_dir())
        except OSError as err:
            self.report({'ERROR'}, "Could not write %s: %s" % (path, err))
            return {'CANCELLED'}
        self.report({'INFO'}, "Saved %d settings files to %s" % (len(names), path))
        return {'FINISHED'}


class M3D_OT_settings_import(Operator):
    """Use the settings of a zip made by Export Settings (yours now are kept in m3d_settings_backup.zip)"""
    bl_idname = "m3d.settings_import"
    bl_label = "Import Settings"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.zip", options={'HIDDEN'})

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, _context):
        import zipfile
        try:
            import_settings(self.filepath, config_dir())
        except (OSError, ValueError, zipfile.BadZipFile) as err:
            self.report({'ERROR'}, "Settings not imported: %s" % err)
            return {'CANCELLED'}
        m3d_user.reset_cache()
        bpy.ops.wm.read_userpref()   # (the preferences apply now; the startup file to new files)
        bpy.ops.wm.read_history()
        self.report({'INFO'}, "Settings imported (yours before are in m3d_settings_backup.zip)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Windows > Command Line: a one-line command line under the 3D view of any workspace

LINE_HEIGHT = 26   # pixels at UI scale 1: one line of the command line


def open_command_line(context):
    """Split a one-line command line (MEL) off the bottom of the workspace's biggest 3D view; the new area or None."""
    screen = context.screen
    views = [a for a in screen.areas if a.type == 'VIEW_3D'] or list(screen.areas)
    view = max(views, key=lambda a: a.width * a.height)
    before = {a.as_pointer() for a in screen.areas}
    scale = context.preferences.system.ui_scale or 1.0
    region = next(r for r in view.regions if r.type == 'WINDOW')
    with context.temp_override(area=view, region=region):
        bpy.ops.screen.area_split(direction='HORIZONTAL', factor=min(0.5, LINE_HEIGHT * scale / max(view.height, 1)))
    new = next((a for a in screen.areas if a.as_pointer() not in before), None)
    if new is None:
        return None
    line = min((view, new), key=lambda a: a.y)   # (the lower of the two)
    line.type = 'CONSOLE'
    line.spaces.active.language = 'mel'
    key = line.as_pointer()
    bpy.app.timers.register(lambda: _tidy_command_line(key), first_interval=0.2)   # (hiding the header right away crashes)
    return line


def _tidy_command_line(key):
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() == key and area.type == 'CONSOLE':
                area.spaces.active.show_region_header = False
                if not len(area.spaces.active.scrollback):   # (the prompt; Command Line: Python has put its banner already)
                    with bpy.context.temp_override(window=win, area=area, region=area.regions[-1]):
                        bpy.ops.console.banner()
    return None


class M3D_OT_command_line(Operator):
    """Show or hide a one-line command line (MEL) under the 3D view of this workspace"""
    bl_idname = "m3d.command_line"
    bl_label = "Command Line"

    def execute(self, context):
        console = next((a for a in context.screen.areas if a.type == 'CONSOLE'), None)
        if console is not None:
            with context.temp_override(area=console, region=console.regions[-1]):
                bpy.ops.screen.area_close()
            return {'FINISHED'}
        if open_command_line(context) is None:
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    M3D_OT_report_bug,
    M3D_OT_open_log,
    M3D_OT_about,
    M3D_OT_check_updates,
    M3D_OT_recover_card,
    M3D_OT_save_layouts_default,
    M3D_OT_reset_settings,
    M3D_OT_settings_export,
    M3D_OT_settings_import,
    M3D_OT_command_line,
)

_stderr = None


def register():
    global _stderr
    for cls in classes:
        bpy.utils.register_class(cls)
    # The log file is the user's: a headless or --factory-startup session (the tests) only watches for errors.
    _stderr = sys.stderr
    sys.stderr = LogTee(sys.stderr, None if bpy.app.background or bpy.app.factory_startup else log_path())
    bpy.app.timers.register(_startup, first_interval=0.5, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_startup):
        bpy.app.timers.unregister(_startup)
    if isinstance(sys.stderr, LogTee):
        sys.stderr = _stderr
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
