#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Generate Maelstrom3D's own artwork (replacing Blender's logo, which is a Blender Foundation trademark):
the Windows app / file icons and the splash image. Uses Blender's bundled Inter font (SIL OFL).

    python tools/m3d/make_brand.py
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONT = os.path.join(ROOT, "release", "datafiles", "fonts", "Inter.woff2")
TEAL = (63, 167, 214)
DARK_TOP, DARK_BOTTOM = (46, 52, 60), (20, 23, 28)


def font(size, weight="Bold"):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_name(weight)
    return f


def gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def icon(size=256):
    """Dark rounded square, white "M3D", teal bar."""
    scale = 4  # Supersample for clean edges.
    s = size * scale
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.2, fill=255)
    img = gradient((s, s), DARK_TOP, DARK_BOTTOM).convert("RGBA")
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)
    text_font = font(int(s * 0.38))
    box = draw.textbbox((0, 0), "M3D", font=text_font)
    x = (s - (box[2] - box[0])) / 2 - box[0]
    y = s * 0.44 - (box[3] - box[1]) / 2 - box[1]
    draw.text((x, y), "M3D", font=text_font, fill=(255, 255, 255, 255))
    bar = s * 0.08
    draw.rounded_rectangle([s * 0.22, s * 0.74, s * 0.78, s * 0.74 + bar], radius=bar / 2, fill=(*TEAL, 255))
    return img.resize((size, size), Image.LANCZOS)


def splash():
    img = gradient((1000, 500), DARK_TOP, DARK_BOTTOM)
    draw = ImageDraw.Draw(img)
    logo = icon(140).convert("RGBA")
    img.paste(logo, (70, 150), logo)
    draw.text((240, 158), "Maelstrom3D", font=font(72), fill=(255, 255, 255))
    draw.text((244, 250), "3D creation suite based on Blender", font=font(26, "Regular"), fill=(170, 176, 184))
    draw.rectangle([244, 300, 520, 304], fill=TEAL)
    return img


def main():
    icons = os.path.join(ROOT, "release", "windows", "icons")
    sizes = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]
    art = icon(256)
    art.save(os.path.join(icons, "winblender.ico"), sizes=sizes)
    art.save(os.path.join(icons, "winblenderfile.ico"), sizes=sizes)
    splash().save(os.path.join(ROOT, "release", "datafiles", "splash.png"))
    art.save(os.path.join(ROOT, "docs", "media", "maelstrom3d-icon.png"))
    print("wrote icons, splash and docs/media/maelstrom3d-icon.png")


if __name__ == "__main__":
    main()
