# SPDX-FileCopyrightText: 2026 Maelstrom3D
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Starter items of the Library (Texture workspace, F4) for Maelstrom3D: plain data, no images. Materials are folders of
fill layers (values for Base Color, Roughness and Metallic) whose masks use the generators (Edges, Cavity, Top-down,
Noise) and filters of the mask stack; mask presets are mask stacks. The format is the one m3d_library.py reads and
writes for the items you save (a JSON description of the layers, their channel values and their mask effects), so these
dicts are the same as the files in the user library folder.

Layers are listed bottom to top. A mask effect has a `kind` (m3d_masks.KINDS), optionally a `name`, `blend`, `opacity`
and the settings of its kind (m3d_masks.PARAM_UI). An effect without a `blend` takes the first-effect rule: it sets the
mask when it is the first one and multiplies with what is below otherwise. Colors are written as sRGB hex codes and
stored in linear light, the way a Fill Layer keeps them.
"""

FORMAT = 1


def rgb(code):
    """'#c8c8c8' -> [r, g, b, 1.0] in linear light."""
    def linear(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return [round(linear(int(code[i:i + 2], 16) / 255), 6) for i in (1, 3, 5)] + [1.0]


def fx(kind, name=None, **settings):
    """A mask effect."""
    return {"kind": kind, **({"name": name} if name else {}), **settings}


def fill(name, color=None, rough=None, metal=None, opacity=1.0, mask=()):
    """A Fill Layer holding the channels that are given (a color is a hex code, roughness and metallic are 0-1)."""
    channels = {}
    if color is not None:
        channels["BASE_COLOR"] = rgb(color)
    if rough is not None:
        channels["ROUGHNESS"] = rough
    if metal is not None:
        channels["METALLIC"] = metal
    return {"name": name, "kind": 'FILL', "channels": channels, **({"opacity": opacity} if opacity != 1.0 else {}),
            **({"mask": list(mask)} if mask else {})}


def material(name, description, *layers):
    """A material item: a folder (named after the item when applied) holding `layers`."""
    return {"format": FORMAT, "type": 'MATERIAL', "name": name, "description": description,
            "layer": {"name": name, "kind": 'FOLDER', "layers": list(layers)}}


def mask(name, description, *effects):
    return {"format": FORMAT, "type": 'MASK', "name": name, "description": description, "mask": list(effects)}


# Plausible PBR values: metals are metallic 1 with a tinted base color, everything else is 0; the base colors are the
# sRGB codes you see in the color picker.
MATERIALS = (
    material(
        "Painted Metal", "Painted metal worn through to the bare metal at the edges, with dirt in the crevices",
        fill("Bare Metal", "#b8b9bc", rough=0.38, metal=1.0),
        fill("Paint", "#b3261e", rough=0.42, metal=0.0, mask=[
            fx("EDGES", amount=0.55, softness=0.2),
            fx("NOISE", "Breakup", scale=9.0, detail=5.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65),
            fx("INVERT")]),
        fill("Dirt", "#1d1813", rough=0.9, metal=0.0, opacity=0.8, mask=[fx("CAVITY", amount=0.7, contrast=0.4)])),
    material(
        "Rusty Iron", "Dark iron with orange rust spreading from the crevices",
        fill("Iron", "#4a4745", rough=0.6, metal=1.0),
        fill("Rust", "#8a3f1c", rough=0.85, metal=0.0, mask=[
            fx("NOISE", scale=5.0, detail=6.0, noise_contrast=3.5),
            fx("CAVITY", amount=0.7, blend='ADD', opacity=0.7),
            fx("LEVELS", black_in=0.45, white_in=0.8)]),
        fill("Rust Flakes", "#b4602a", rough=0.95, metal=0.0, opacity=0.8, mask=[
            fx("NOISE", scale=32.0, detail=3.0, noise_contrast=8.0),
            fx("LEVELS", black_in=0.55, white_in=0.8)])),
    material(
        "Brushed Steel", "Steel with fine variation in the roughness",
        fill("Steel", "#a9abae", rough=0.3, metal=1.0),
        fill("Fine Variation", rough=0.55, opacity=0.6, mask=[fx("NOISE", scale=70.0, detail=2.0, noise_contrast=4.0)])),
    material("Chrome", "Polished chrome", fill("Surface", "#e3e3e3", rough=0.02, metal=1.0)),
    material("Gold", "Polished gold", fill("Surface", "#ffc457", rough=0.2, metal=1.0)),
    material(
        "Copper", "Copper with green patina in the cavities",
        fill("Metal", "#f0a284", rough=0.28, metal=1.0),
        fill("Patina", "#3d9c86", rough=0.65, metal=0.0, mask=[
            fx("CAVITY", amount=0.7, contrast=0.4),
            fx("NOISE", "Breakup", scale=8.0, detail=5.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65)])),
    material("Rubber", "Matte black rubber", fill("Surface", "#1c1c1c", rough=0.85, metal=0.0)),
    material("Plastic", "Glossy plastic", fill("Surface", "#d1281f", rough=0.12, metal=0.0)),
    material(
        "Dirty Plastic", "Plastic with grime in the crevices and scuffed edges",
        fill("Base", "#cfcabb", rough=0.4, metal=0.0),
        fill("Grime", "#2b2218", rough=0.8, metal=0.0, mask=[
            fx("CAVITY", amount=0.7, contrast=0.4),
            fx("NOISE", "Breakup", scale=12.0, detail=4.0, noise_contrast=2.5, blend='MULTIPLY', opacity=0.65)]),
        fill("Scuffs", "#efece2", rough=0.65, metal=0.0, mask=[
            fx("EDGES", amount=0.5, softness=0.2),
            fx("NOISE", "Breakup", scale=14.0, detail=4.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65)])),
    material(
        "Concrete", "Rough concrete with stains and pits (noise only)",
        fill("Base", "#8a8884", rough=0.92, metal=0.0),
        fill("Stains", "#5d5b57", rough=0.95, metal=0.0, mask=[fx("NOISE", scale=4.0, detail=6.0, noise_contrast=2.5)]),
        fill("Pits", "#3c3b39", rough=1.0, metal=0.0, mask=[
            fx("NOISE", scale=40.0, detail=3.0, noise_contrast=8.0),
            fx("LEVELS", black_in=0.6, white_in=0.85)])),
    material(
        "Dusty", "A layer of dust on the surfaces that face up (add it on top of any material)",
        fill("Dust", "#b7a98e", rough=0.95, metal=0.0, opacity=0.85, mask=[
            fx("TOPDOWN", softness=0.45, height_falloff=0.2),
            fx("NOISE", "Breakup", scale=14.0, detail=4.0, noise_contrast=2.5, blend='MULTIPLY', opacity=0.65)])),
    material(
        "Snow Cover", "Snow on the surfaces that face up (add it on top of any material)",
        fill("Snow", "#f2f6fb", rough=0.6, metal=0.0, mask=[
            fx("TOPDOWN", offset=-0.05, softness=0.3, height_falloff=0.15),
            fx("NOISE", "Breakup", scale=7.0, detail=5.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65),
            fx("SHARPEN", amount=0.3)])),
    material(
        "Mud", "Wet mud caked into the crevices",
        fill("Caked Mud", "#3a2615", rough=0.88, metal=0.0, mask=[
            fx("CAVITY", amount=0.75, contrast=0.4),
            fx("NOISE", scale=6.0, detail=6.0, noise_contrast=3.0, blend='ADD', opacity=0.6)]),
        fill("Wet Sheen", "#2a1a0e", rough=0.18, metal=0.0, opacity=0.7, mask=[
            fx("NOISE", scale=9.0, detail=4.0, noise_contrast=4.0),
            fx("LEVELS", black_in=0.45, white_in=0.7)])),
    material("Aluminium", "Brushed aluminium", fill("Surface", "#d4d6d9", rough=0.4, metal=1.0)),
    material("Matte Black", "Matte black metal", fill("Surface", "#141414", rough=0.65, metal=0.0)),
    material("Ceramic", "Glazed white ceramic", fill("Glaze", "#f1efe8", rough=0.08, metal=0.0)),
)

MASKS = (
    mask("Edge Wear", "Wear on the convex edges, broken up by noise",
         fx("EDGES", amount=0.5, softness=0.15),
         fx("NOISE", "Breakup", scale=9.0, detail=5.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65)),
    mask("Dirt in Cavities", "Dirt in the crevices, patchy",
         fx("CAVITY", amount=0.7, contrast=0.45),
         fx("NOISE", "Breakup", scale=12.0, detail=4.0, noise_contrast=2.0, blend='MULTIPLY', opacity=0.65)),
    mask("Top-down Dust", "Dust on the surfaces that face up",
         fx("TOPDOWN", softness=0.5, height_falloff=0.3),
         fx("NOISE", "Breakup", scale=14.0, detail=4.0, noise_contrast=2.5, blend='MULTIPLY', opacity=0.65)),
    mask("Noise Breakup", "Large soft noise, to vary a layer or break up another mask",
         fx("NOISE", scale=6.0, detail=5.0, noise_contrast=4.0)),
    mask("Thickness Glow", "The thin parts of a closed mesh (for emission or subsurface looks)",
         fx("THICKNESS", amount=0.5, contrast=0.5),
         fx("LEVELS", black_in=0.1, white_in=0.9)),
    mask("Speckle", "Fine specks",
         fx("NOISE", scale=55.0, detail=2.0, noise_contrast=10.0),
         fx("LEVELS", black_in=0.5, white_in=0.7)),
    mask("Grunge", "Edge wear and crevice dirt together, broken up by noise",
         fx("EDGES", amount=0.45, softness=0.2),
         fx("CAVITY", amount=0.7, contrast=0.4, blend='LIGHTEN'),
         fx("NOISE", "Breakup", scale=10.0, detail=5.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65)),
    mask("Light Dust", "A thin, even dusting on the surfaces that face up",
         fx("TOPDOWN", offset=0.2, softness=0.7, height_falloff=0.2, opacity=0.6)),
    mask("Snow Cap", "A cap of snow on the top of the mesh",
         fx("TOPDOWN", offset=-0.1, softness=0.25, height_falloff=0.15),
         fx("NOISE", "Breakup", scale=7.0, detail=5.0, noise_contrast=3.0, blend='MULTIPLY', opacity=0.65)),
    mask("Large Patches", "Big patches with soft edges",
         fx("NOISE", scale=3.0, detail=3.0, noise_contrast=3.0),
         fx("LEVELS", black_in=0.35, white_in=0.65)),
)


def register():
    pass   # (data only: Blender asks every startup script for a register function)


def unregister():
    pass
