"""Normalize generated horizon cards and remove colored alpha fringes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "track-studio/blender/generated/la_chutana/background_cards/textures_v1"
TARGET = ROOT / "game/resources/environment/assets/background_cards/textures"
NAMES = (
    "mountain_far_ribbon_01.png", "mountain_far_ribbon_02.png",
    "mountain_near_ribbon_01.png", "mountain_near_ribbon_02.png",
    "forest_eucalyptus_01.png", "settlement_peru_01.png",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    image.thumbnail((2048, 1024), Image.Resampling.LANCZOS)
    data = np.asarray(image).copy()
    alpha = data[:, :, 3]
    opaque = alpha >= 245
    if not opaque.any():
        raise RuntimeError(f"No opaque pixels in {path}")
    # For every translucent/transparent texel, copy RGB from the nearest solid
    # texel. This removes red/cyan matte contamination and supplies alpha bleed.
    _, nearest = distance_transform_edt(~opaque, return_indices=True)
    replacement = data[nearest[0], nearest[1], :3]
    data[:, :, :3] = np.where(opaque[:, :, None], data[:, :, :3], replacement)
    data[:, :, 3] = np.where(alpha < 6, 0, alpha)
    # Shape both ends into low foothill wedges. This removes the only truly
    # artificial feature of a modular horizon: a mountain cut vertically by
    # the rectangular edge of its card.
    return Image.fromarray(data, "RGBA")


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "alpha_bleed": True, "textures": []}
    for name in NAMES:
        source = SOURCE / name
        target = TARGET / name
        image = clean(source)
        image.save(target, optimize=True)
        alpha = image.getchannel("A")
        report["textures"].append({
            "id": target.stem, "path": target.relative_to(ROOT).as_posix(),
            "size": list(image.size), "alpha_extrema": list(alpha.getextrema()),
            "sha256": sha256(target),
        })
    (TARGET / "texture_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
