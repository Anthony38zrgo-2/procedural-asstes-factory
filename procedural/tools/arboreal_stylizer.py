from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image, ImageFilter

STYLE_ID = "arboreal_stipple_v1"
STYLE_VERSION = 1


def _rgb(value: str) -> np.ndarray:
    text = value.lstrip("#")
    return np.asarray([int(text[index : index + 2], 16) for index in (0, 2, 4)], dtype=np.uint8)


def _seed(asset_id: str, biome: str) -> int:
    digest = hashlib.sha256(f"{STYLE_ID}:{asset_id}:{biome}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


def stylize_arboreal_card(
    image: Image.Image, palette: dict, kind: str, asset_id: str
) -> tuple[Image.Image, dict]:
    """Add deterministic leaf mottling and sparse canopy gaps to trees and bushes."""
    if kind not in {"tree", "bush"}:
        return image, {"id": "none", "version": 0, "applied": False}
    category = palette["categories"][kind]
    foliage_roles = [role for role in ("foliage", "leaf") if role in category]
    woody_roles = [role for role in ("root", "trunk", "branch", "detail") if role in category]
    foliage_palette = np.asarray(
        [_rgb(color) for role in foliage_roles for color in category[role]], dtype=np.float32
    )
    woody_palette = np.asarray(
        [_rgb(color) for role in woody_roles for color in category[role]], dtype=np.float32
    )

    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    rgb = rgba[..., :3].astype(np.float32)
    visible = rgba[..., 3] > 0
    foliage_distance = (
        ((rgb[..., None, :] - foliage_palette[None, None, :, :]) ** 2).sum(axis=-1).min(axis=-1)
    )
    if woody_palette.size:
        woody_distance = (
            ((rgb[..., None, :] - woody_palette[None, None, :, :]) ** 2).sum(axis=-1).min(axis=-1)
        )
        foliage_mask = visible & (foliage_distance < woody_distance)
        woody_mask = visible & ~foliage_mask
    else:
        foliage_mask = visible
        woody_mask = np.zeros_like(visible)

    rng = np.random.default_rng(_seed(asset_id, palette["biome"]))
    height, width = foliage_mask.shape
    fine = rng.random((height, width), dtype=np.float32)
    coarse_source = Image.fromarray(
        np.rint(rng.random((height, width)) * 255).astype(np.uint8), "L"
    )
    coarse = np.asarray(
        coarse_source.filter(ImageFilter.GaussianBlur(radius=14.0)), dtype=np.float32
    ) / 255.0
    coarse = np.clip((coarse - 0.5) * 7.0 + 0.5, 0.0, 1.0)
    rows = np.arange(height, dtype=np.float32)[:, None] / max(height - 1, 1)
    light_field = 0.62 * coarse + 0.25 * fine + 0.13 * (1.0 - rows)

    role_colors = np.asarray([_rgb(color) for color in category["foliage"]], dtype=np.uint8)
    indices = np.zeros((height, width), dtype=np.int16)
    for index, threshold in enumerate((0.40, 0.49, 0.58, 0.67, 0.78), start=1):
        indices[light_field >= threshold] = index
    indices = np.clip(indices, 0, len(role_colors) - 1)
    textured = role_colors[indices]
    rgba[..., :3][foliage_mask] = textured[foliage_mask]

    if woody_mask.any():
        wood_role = "trunk" if "trunk" in category else "branch"
        wood_colors = np.asarray([_rgb(color) for color in category[wood_role]], dtype=np.uint8)
        # Wood uses an intermediate finish: a stable base with broad shading and restrained
        # fine variation, less stippled than foliage but not completely flat.
        columns = np.arange(width, dtype=np.float32)[None, :] / max(width - 1, 1)
        bark_field = 0.55 * coarse + 0.30 * fine + 0.15 * columns
        bark_indices = np.full((height, width), min(2, len(wood_colors) - 1), dtype=np.int16)
        bark_indices[bark_field < 0.30] = min(1, len(wood_colors) - 1)
        bark_indices[bark_field < 0.14] = 0
        bark_indices[bark_field > 0.58] = min(3, len(wood_colors) - 1)
        bark_indices[bark_field > 0.73] = min(4, len(wood_colors) - 1)
        bark_indices[bark_field > 0.88] = min(5, len(wood_colors) - 1)
        bark_texture = wood_colors[bark_indices]
        rgba[..., :3][woody_mask] = bark_texture[woody_mask]

    mask_image = Image.fromarray((foliage_mask * 255).astype(np.uint8), "L")
    interior = np.asarray(mask_image.filter(ImageFilter.MinFilter(5)), dtype=np.uint8) > 0
    eroded = np.asarray(mask_image.filter(ImageFilter.MinFilter(9)), dtype=np.uint8) > 0
    edge = foliage_mask & ~eroded
    holes = foliage_mask & interior & (fine > 0.945) & (coarse > 0.40)
    edge_gaps = edge & (fine > 0.76)
    holes |= edge_gaps
    rgba[..., 3][holes] = 0
    rgba[..., :3][holes] = 0

    dilated = np.asarray(mask_image.filter(ImageFilter.MaxFilter(7)), dtype=np.uint8) > 0
    fringe = dilated & ~visible & (fine > 0.88) & (coarse > 0.34)
    rgba[..., :3][fringe] = textured[fringe]
    rgba[..., 3][fringe] = 255

    return Image.fromarray(rgba, "RGBA"), {
        "id": STYLE_ID,
        "version": STYLE_VERSION,
        "applied": True,
        "seed": _seed(asset_id, palette["biome"]),
        "foliage_pixels": int(foliage_mask.sum()),
        "pigmented_wood_pixels": int(woody_mask.sum()),
        "wood_finish": "moderate_bark_pigmentation",
        "transparent_leaf_gaps": int(holes.sum()),
        "silhouette_fringe_pixels": int(fringe.sum()),
        "detail_scale_px": [1, 3],
        "canopy_noise_radius_px": 14,
    }
