#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Record the Maelstrom3D README videos (Windows): runs each scenario in tools/m3d/demo/scenarios.py,
captures the Blender window with ffmpeg, writes docs/media/<name>.mp4 and docs/media/<name>.gif.

    python tools/m3d/demo/record.py <blender.exe> [scenario ...]

Don't use the PC while it records: the Blender window must stay in front.
"""

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCENARIOS = os.path.join(os.path.dirname(__file__), "scenarios.py")
OUT = os.path.join(ROOT, "docs", "media")
ALL = ("interface", "modeling", "marking_menus", "dock", "uv", "mel")

user32 = ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Physical pixels, same as ffmpeg's gdigrab.


def find_window(pid):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def bring_to_front(hwnd):
    user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    user32.keybd_event(0x12, 0, 0, 0)  # Alt tap: lets a background process take the foreground.
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)


def client_rect(hwnd):
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right - rect.right % 2, rect.bottom - rect.bottom % 2


def wait_for(path, timeout):
    end = time.time() + timeout
    while not os.path.exists(path):
        if time.time() > end:
            raise TimeoutError(path)
        time.sleep(0.05)


def record(blender, name):
    status = tempfile.mkdtemp(prefix="mb_demo_")
    raw = os.path.join(status, name + ".mkv")
    proc = subprocess.Popen([blender, "--factory-startup", "--enable-event-simulate",
                             "--python", SCENARIOS, "--", name, status])
    try:
        hwnd = None
        while hwnd is None:
            time.sleep(0.2)
            hwnd = find_window(proc.pid)
        bring_to_front(hwnd)
        wait_for(os.path.join(status, "ready"), 60)
        bring_to_front(hwnd)
        x, y, w, h = client_rect(hwnd)
        ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "gdigrab", "-framerate", "30", "-draw_mouse", "0",
             "-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}", "-i", "desktop",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", raw],
            stdin=subprocess.PIPE)
        wait_for(os.path.join(status, "done"), 180)
        ffmpeg.communicate(b"q")
        proc.wait(30)
    finally:
        if proc.poll() is None:
            proc.kill()

    os.makedirs(OUT, exist_ok=True)
    mp4, gif = os.path.join(OUT, name + ".mp4"), os.path.join(OUT, name + ".gif")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-vf", "scale=1600:-2",
                    "-c:v", "libx264", "-crf", "24", "-preset", "slow", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", mp4], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-filter_complex",
                    "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=4", gif], check=True)
    shutil.rmtree(status, ignore_errors=True)
    print(f"{name}: {os.path.getsize(mp4) // 1024} KB mp4, {os.path.getsize(gif) // 1024} KB gif")


def main():
    blender, names = sys.argv[1], sys.argv[2:] or ALL
    for name in names:
        record(blender, name)


if __name__ == "__main__":
    main()
