"""Turn one colour picture per material into a full material: colour, bumps and shine.

    python tools/make_pbr.py            (needs numpy and Pillow)

For every entry in textures/materials.json that has textures/<material>/source.png
(a picture of the surface seen straight on, e.g. generated with fal.ai), this writes
next to it:

    basecolor.png   the picture made to tile without a visible seam, 1024 px
    normal.png      surface bumps worked out from the picture's light and dark
                    (dark cracks and pores sink in, bright lumps stand out)
    orm.png         R = ambient occlusion (crevices darker), G = roughness (wet areas
                    shiny, dry areas dull), B = metallic (the material's 'metallic' value)

unreal/hh_setup.py imports these three into /Game/HollowHull/Textures and plugs them
into the material instance of the same name; blender/hh_kit.py uses them for previews.
Materials without a source.png stay plain colour, exactly as before.
"""

import json
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX = os.path.join(ROOT, "textures")
SIZE = 1024


def load_rgb(path, crop=1.0):
    img = Image.open(path).convert("RGB")
    if crop < 1.0:
        w, h = img.size
        cw, ch = int(w * crop), int(h * crop)
        img = img.crop(((w - cw) // 2, (h - ch) // 2, (w + cw) // 2, (h + ch) // 2))
    if img.size != (SIZE, SIZE):
        img = img.resize((SIZE, SIZE), Image.LANCZOS)
    return np.asarray(img).astype(np.float32) / 255.0


def save(path, arr):
    Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path)


def make_seamless(rgb, blend=0.18):
    """Cross-fade each edge with the opposite one so the picture tiles without a seam.
    Seamless generations pass through almost unchanged."""
    n = rgb.shape[0]
    w = int(n * blend)
    ramp = np.linspace(0, 1, w, dtype=np.float32)
    out = rgb.copy()
    rolled = np.roll(rgb, n // 2, axis=0)
    out[:w] = rgb[:w] * ramp[:, None, None] + rolled[:w] * (1 - ramp[:, None, None])
    out[-w:] = rgb[-w:] * ramp[::-1, None, None] + rolled[-w:] * (1 - ramp[::-1, None, None])
    rolled = np.roll(out, n // 2, axis=1)
    out2 = out.copy()
    out2[:, :w] = out[:, :w] * ramp[None, :, None] + rolled[:, :w] * (1 - ramp[None, :, None])
    out2[:, -w:] = out[:, -w:] * ramp[None, ::-1, None] + rolled[:, -w:] * (1 - ramp[None, ::-1, None])
    return out2


def blur(x, radius):
    """Wrap-around box blur (three passes ~ gaussian), so maps stay tileable."""
    for _ in range(3):
        for axis in (0, 1):
            acc = np.zeros_like(x)
            for k in range(-radius, radius + 1):
                acc += np.roll(x, k, axis=axis)
            x = acc / (2 * radius + 1)
    return x


def height_from(rgb):
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    # keep the shapes (lumps, pores), drop the big light/dark patches of the picture
    detail = lum - blur(lum, 24)
    return (detail - detail.min()) / max(detail.max() - detail.min(), 1e-6), lum


def normal_from(height, strength):
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    nz = np.ones_like(height)
    length = np.sqrt(dx * dx + dy * dy + nz * nz)
    # Unreal's convention (DirectX): green points down the picture
    return np.stack([-dx / length * 0.5 + 0.5, dy / length * 0.5 + 0.5, nz / length * 0.5 + 0.5], axis=-1)


def build(name, spec):
    folder = os.path.join(TEX, name)
    src = os.path.join(folder, "source.png")
    if not os.path.exists(src):
        return False
    rgb = load_rgb(src, spec.get("crop", 1.0))
    if not spec.get("atlas") and spec.get("seamless", True):  # a model's colour map is wrapped, not tiled
        rgb = make_seamless(rgb)
    height, lum = height_from(rgb)
    small = blur(height, 2)
    normal = normal_from(small, spec.get("bump", 6.0))
    ao = np.clip(1.0 - spec.get("ao", 0.6) * (blur(height, 8) - height).clip(0, None) * 4.0, 0, 1)
    lo, hi = spec.get("roughness", [0.2, 0.6])
    # brighter, raised parts read wetter (shinier) on flesh; cracks stay dull
    rough = hi - (hi - lo) * (0.6 * small + 0.4 * lum)
    orm = np.stack([ao, np.clip(rough, 0, 1), np.full_like(ao, spec.get("metallic", 0.0))], axis=-1)
    save(os.path.join(folder, "basecolor.png"), rgb)
    save(os.path.join(folder, "normal.png"), normal)
    save(os.path.join(folder, "orm.png"), orm)
    print(f"{name}: basecolor, normal, orm ({SIZE}px)")
    return True


def main():
    with open(os.path.join(TEX, "materials.json"), encoding="utf-8") as f:
        specs = json.load(f)["materials"]
    done = [n for n, s in specs.items() if build(n, s)]
    print(f"{len(done)} of {len(specs)} materials have textures")


if __name__ == "__main__":
    main()
