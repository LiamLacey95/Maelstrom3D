# SPDX-License-Identifier: GPL-2.0-or-later
"""
A mouse cursor for the demo videos: a click-through, always-on-top layered window with an arrow (and a ring while a
button is held), moved with the simulated mouse. Simulated input doesn't move the real cursor, and a window of our own
shows over everything the screen capture sees: menus, popups and the top bar rows included (Blender can't draw there).
"""

import ctypes
import ctypes.wintypes as wt

import numpy as np

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
PAD = 40            # Ring radius; the arrow's tip is at (PAD, PAD) of the bitmap.
SIZE = PAD * 2 + 48
SCALE = 1.9         # Arrow size relative to a 17 x 26 px pointer.

HANDLE = ctypes.c_void_p
user32.CreateWindowExW.restype = HANDLE
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, HANDLE, HANDLE, HANDLE, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [HANDLE, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.GetDC.restype = HANDLE
user32.GetDC.argtypes = [HANDLE]
user32.ShowWindow.argtypes = [HANDLE, ctypes.c_int]
user32.DestroyWindow.argtypes = [HANDLE]
user32.UpdateLayeredWindow.argtypes = [HANDLE, HANDLE, ctypes.c_void_p, ctypes.c_void_p, HANDLE, ctypes.c_void_p,
                                       wt.DWORD, ctypes.c_void_p, wt.DWORD]
gdi32.CreateCompatibleDC.restype = HANDLE
gdi32.CreateCompatibleDC.argtypes = [HANDLE]
gdi32.CreateDIBSection.restype = HANDLE
gdi32.CreateDIBSection.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, HANDLE, wt.DWORD]
gdi32.SelectObject.restype = HANDLE
gdi32.SelectObject.argtypes = [HANDLE, HANDLE]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", HANDLE), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", HANDLE), ("hIcon", HANDLE), ("hCursor", HANDLE),
                ("hbrBackground", HANDLE), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


def _inside(poly, px, py):
    """Even-odd point-in-polygon test for arrays of points."""
    inside = np.zeros(px.shape, bool)
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cond = ((y0 > py) != (y1 > py)) & (px < (x1 - x0) * (py - y0) / (y1 - y0 + 1e-12) + x0)
        inside ^= cond
    return inside


def _image(pressed):
    """BGRA premultiplied bitmap (top-down) of the pointer."""
    ss = 3
    ys, xs = np.mgrid[0:SIZE * ss, 0:SIZE * ss]
    px, py = (xs + 0.5) / ss - PAD, (ys + 0.5) / ss - PAD
    s = SCALE
    arrow = [(0, 0), (0, 22 * s), (6 * s, 16 * s), (11 * s, 26 * s), (15 * s, 24 * s), (10 * s, 14 * s), (17 * s, 14 * s)]
    fill = _inside(arrow, px, py)
    # Outline: pixels within 1.3 px of the arrow's edge.
    edge = np.zeros(px.shape, bool)
    for i in range(len(arrow)):
        x0, y0 = arrow[i]
        x1, y1 = arrow[(i + 1) % len(arrow)]
        dx, dy = x1 - x0, y1 - y0
        t = np.clip(((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy), 0, 1)
        edge |= np.hypot(px - (x0 + t * dx), py - (y0 + t * dy)) < 1.4
    rgba = np.zeros(px.shape + (4,), np.float32)
    if pressed:
        r = np.hypot(px, py)
        ring = (r > 24) & (r < 28)
        rgba[ring] = (1.0, 0.85, 0.1, 0.9)
    rgba[fill] = (1, 1, 1, 1)
    rgba[edge] = (0, 0, 0, 1)
    rgba = rgba.reshape(SIZE, ss, SIZE, ss, 4).mean(axis=(1, 3))
    # Averaging straight colors of transparent pixels would darken edges: weight by alpha, then premultiply.
    out = np.zeros((SIZE, SIZE, 4), np.uint8)
    a = rgba[..., 3:]
    out[..., :3] = np.clip(rgba[..., [2, 1, 0]] * 255, 0, 255).astype(np.uint8)  # BGR; mean already ~premultiplied
    out[..., 3:] = np.clip(a * 255, 0, 255).astype(np.uint8)
    return out


class OsCursor:
    def __init__(self):
        name = "m3dDemoCursor"
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, HANDLE)
        wc.lpszClassName = name
        user32.RegisterClassW(ctypes.byref(wc))
        # WS_EX_LAYERED | TOPMOST | TRANSPARENT | TOOLWINDOW | NOACTIVATE
        self.hwnd = user32.CreateWindowExW(0x80000 | 0x8 | 0x20 | 0x80 | 0x08000000, name, "", 0x80000000,
                                           0, 0, SIZE, SIZE, None, None, None, None)
        self.screen_dc = user32.GetDC(None)
        self.dc = gdi32.CreateCompatibleDC(self.screen_dc)
        self.bitmaps = {}
        for pressed in (False, True):
            info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), SIZE, -SIZE, 1, 32, 0)
            bits = ctypes.c_void_p()
            bmp = gdi32.CreateDIBSection(self.dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
            pixels = _image(pressed)
            ctypes.memmove(bits, pixels.tobytes(), pixels.nbytes)
            self.bitmaps[pressed] = bmp
        self.last = None
        user32.ShowWindow(self.hwnd, 8)  # SW_SHOWNA

    def update(self, x, y, pressed):
        """Put the arrow's tip at screen point (x, y)."""
        if self.last == (int(x), int(y), pressed):
            return
        self.last = (int(x), int(y), pressed)
        gdi32.SelectObject(self.dc, self.bitmaps[pressed])
        dst = wt.POINT(int(x) - PAD, int(y) - PAD)
        size = wt.SIZE(SIZE, SIZE)
        src = wt.POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(dst), ctypes.byref(size), self.dc,
                                   ctypes.byref(src), 0, ctypes.byref(blend), 2)  # ULW_ALPHA

    def close(self):
        user32.DestroyWindow(self.hwnd)
