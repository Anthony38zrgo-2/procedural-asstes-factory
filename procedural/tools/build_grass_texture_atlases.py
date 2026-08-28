from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blade_polygon(rng: random.Random, base_x: float, base_y: float, height: float, width: float) -> list[tuple[float, float]]:
    lean = rng.uniform(-0.28, 0.28) * height
    points_left: list[tuple[float, float]] = []
    points_right: list[tuple[float, float]] = []
    for step in range(6):
        t = step / 5.0
        curve = lean * (t ** 1.35) + math.sin(t * math.pi) * rng.uniform(-0.035, 0.035) * height
        x = base_x + curve
        y = base_y - height * t
        half = width * (1.0 - t) ** 0.72 * 0.5
        points_left.append((x - half, y))
        points_right.append((x + half, y))
    return points_left + list(reversed(points_right))


def make_atlas(source: Image.Image, tint: list[float], seed: int) -> tuple[Image.Image, list[dict]]:
    scale = 3
    atlas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    regions: list[dict] = []
    src = np.asarray(source.convert("RGB"), dtype=np.float32)
    for cell in range(8):
        rng = random.Random(seed + cell * 997)
        col, row = cell % 4, cell // 4
        cell_w, cell_h = 128, 256
        mask_hi = Image.new("L", (cell_w * scale, cell_h * scale), 0)
        draw = ImageDraw.Draw(mask_hi)
        blades = 25 + cell * 2 + rng.randrange(0, 8)
        for blade in range(blades):
            base_x = rng.uniform(10, cell_w - 10) * scale
            base_y = rng.uniform(cell_h * 0.88, cell_h * 0.99) * scale
            height = rng.uniform(cell_h * 0.34, cell_h * (0.84 if blade % 5 else 0.95)) * scale
            width = rng.uniform(2.0, 5.2) * scale
            draw.polygon(blade_polygon(rng, base_x, base_y, height, width), fill=rng.randrange(205, 256))
        mask = mask_hi.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
        ox = rng.randrange(0, source.width - cell_w + 1)
        oy = rng.randrange(0, source.height - cell_h + 1)
        crop = src[oy : oy + cell_h, ox : ox + cell_w].copy()
        luminance = crop.mean(axis=2, keepdims=True)
        crop = crop * np.asarray(tint, dtype=np.float32)[None, None, :]
        crop = crop * 0.72 + luminance * 0.28
        variation = np.linspace(rng.uniform(0.72, 0.86), rng.uniform(1.00, 1.10), cell_h)[:, None, None]
        crop = np.clip(crop * variation, 0, 255).astype(np.uint8)
        rgba = Image.fromarray(crop, "RGB").convert("RGBA")
        rgba.putalpha(mask)
        x, y = col * cell_w, row * cell_h
        atlas.alpha_composite(rgba, (x, y))
        regions.append({
            "id": f"clump_{cell:02d}",
            "pixels": [x, y, x + cell_w, y + cell_h],
            "uv_bottom_left": [x / 512, 1.0 - (y + cell_h) / 512, (x + cell_w) / 512, 1.0 - y / 512],
        })
    return atlas, regions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    recipe_path = repo / "procedural/recipes/grass_v5_library.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    output = repo / "procedural/generated/vegetation_v5/textures/grass"
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (variant, spec) in enumerate(recipe["variants"].items()):
        source_path = repo / recipe["source_textures"][variant]
        source = Image.open(source_path)
        atlas, regions = make_atlas(source, spec["tint"], 85200 + index * 101)
        atlas_path = output / f"grass_{variant}_512.png"
        atlas.save(atlas_path, compress_level=9)
        manifest_path = output / f"grass_{variant}_512.json"
        manifest = {
            "schema_version": 1,
            "id": f"grass_{variant}_512",
            "variant": variant,
            "source": recipe["source_textures"][variant],
            "source_sha256": sha256(source_path),
            "atlas": atlas_path.relative_to(repo).as_posix(),
            "atlas_sha256": sha256(atlas_path),
            "alpha_cutoff": recipe["alpha_cutoff"],
            "regions": regions,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        records.append({"id": manifest["id"], "manifest": manifest_path.relative_to(repo).as_posix(), "sha256": manifest["atlas_sha256"]})
    library = {"schema_version": 1, "recipe": recipe_path.relative_to(repo).as_posix(), "recipe_sha256": sha256(recipe_path), "atlases": records}
    (output / "manifest.json").write_text(json.dumps(library, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"atlases": len(records), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
