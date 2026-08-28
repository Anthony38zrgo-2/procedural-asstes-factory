"""Prepare deterministic seamless surface textures and their audit manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


FACTORY = Path(__file__).resolve().parents[2]
SOURCE = FACTORY / "assets-texturas/textures"
OUTPUT = FACTORY / "track-studio/blender/generated/la_chutana/textures"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seamless_tile(image: Image.Image, size: int) -> Image.Image:
    """Feather only the outer 6.25%, preserving the source's natural variation."""
    tile = image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    band = max(8, size // 16)
    for distance in range(band):
        amount = distance / float(band - 1)
        left = tile.crop((distance, 0, distance + 1, size))
        right_x = size - 1 - distance
        right = tile.crop((right_x, 0, right_x + 1, size))
        shared = Image.blend(left, right, 0.5)
        tile.paste(Image.blend(shared, left, amount), (distance, 0))
        tile.paste(Image.blend(shared, right, amount), (right_x, 0))
    for distance in range(band):
        amount = distance / float(band - 1)
        top = tile.crop((0, distance, size, distance + 1))
        bottom_y = size - 1 - distance
        bottom = tile.crop((0, bottom_y, size, bottom_y + 1))
        shared = Image.blend(top, bottom, 0.5)
        tile.paste(Image.blend(shared, top, amount), (0, distance))
        tile.paste(Image.blend(shared, bottom, amount), (0, bottom_y))
    return tile


def seam_metrics(image: Image.Image) -> dict:
    rgb = image.convert("RGB")
    left = rgb.crop((0, 0, 1, rgb.height))
    right = rgb.crop((rgb.width - 1, 0, rgb.width, rgb.height))
    top = rgb.crop((0, 0, rgb.width, 1))
    bottom = rgb.crop((0, rgb.height - 1, rgb.width, rgb.height))
    horizontal = sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3.0
    vertical = sum(ImageStat.Stat(ImageChops.difference(top, bottom)).mean) / 3.0
    return {"left_right_mean_abs_error": horizontal, "top_bottom_mean_abs_error": vertical}


def write_texture(name: str, image: Image.Image, source: Path, records: dict, require_seamless: bool = True):
    target = OUTPUT / name
    image.save(target, optimize=True)
    metrics = seam_metrics(image)
    if require_seamless and (metrics["left_right_mean_abs_error"] != 0.0 or metrics["top_bottom_mean_abs_error"] != 0.0):
        raise RuntimeError(f"Texture is not seamless: {target}: {metrics}")
    records[name] = {
        "source": source.relative_to(FACTORY).as_posix(),
        "source_sha256": sha256(source),
        "sha256": sha256(target),
        "size": list(image.size),
        "seam_metrics": metrics,
        "seamless_required": require_seamless,
    }


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    asphalt_source = OUTPUT / "asphalt_102_imagegen_source.png"
    terrain_source = SOURCE / "terrain/png/059.png"
    curb_source = SOURCE / "objects_styles/png/103.png"
    start_finish_source = SOURCE / "objects_styles/png/062.png"
    if not asphalt_source.is_file():
        raise FileNotFoundError(asphalt_source)
    records = {}
    write_texture("asphalt_102_seamless.png", seamless_tile(Image.open(asphalt_source), 1024), asphalt_source, records)
    write_texture("terrain_059_seamless.png", seamless_tile(Image.open(terrain_source), 1024), terrain_source, records)
    curb = Image.open(curb_source).convert("RGB")
    midpoint = curb.height // 2
    write_texture("curb_103_navy_seamless.png", seamless_tile(curb.crop((0, 0, curb.width, midpoint)), 512), curb_source, records)
    write_texture("curb_103_white_seamless.png", seamless_tile(curb.crop((0, midpoint, curb.width, curb.height)), 512), curb_source, records)
    # Start/finish is a bounded marking rather than a repeating terrain
    # surface, so preserve the authored checkerboard without seam processing.
    write_texture("start_finish_062.png", Image.open(start_finish_source).convert("RGB"), start_finish_source, records,
                  require_seamless=False)
    active = {
        "schema_version": 1,
        "active_biome": "south_america_west_low",
        "forge": {"style": "ps1_rally_clean", "surface_authority": "textures_059_102_103"},
        "shared": {
            "asphalt": "asphalt_102_seamless.png",
            "guardrail": "curb_103_navy_seamless.png",
            "start_finish": "start_finish_062.png",
        },
        "terrain": "terrain_059_seamless.png",
        "shoulder": "terrain_059_seamless.png",
        "bark": "terrain_059_seamless.png",
        "curbs": {"navy": "curb_103_navy_seamless.png", "white": "curb_103_white_seamless.png"},
        "assets": {},
    }
    (OUTPUT / "active_manifest.json").write_text(json.dumps(active, indent=2) + "\n", encoding="utf-8")
    report = {"result": "pass", "textures": records}
    (OUTPUT / "seamless_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
