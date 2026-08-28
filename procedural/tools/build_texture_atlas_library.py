from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont


GENERATOR = "deterministic_recovered_texture_atlas_v1"
GENERATOR_VERSION = 1
ALPHA_VISIBLE = 16


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def rel(path: Path, repo: Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


def validate_recipe(recipe: dict) -> None:
    required = {"schema_version", "id", "family", "size", "padding", "layout_seed", "color_seed", "sprites"}
    missing = required - recipe.keys()
    if missing:
        raise ValueError(f"recipe missing fields: {sorted(missing)}")
    if recipe["schema_version"] != 1 or recipe["family"] not in {"broadleaf", "bush", "conifer"}:
        raise ValueError(f"invalid recipe identity: {recipe.get('id')}")
    if int(recipe["size"]) not in {256, 512} or int(recipe["padding"]) < 4:
        raise ValueError(f"invalid size or padding: {recipe['id']}")
    if len(recipe["sprites"]) < 4 or len(recipe["sprites"]) > 6:
        raise ValueError(f"recipe must use 4-6 sprites: {recipe['id']}")


def alpha_metrics(image: Image.Image) -> dict:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    visible = alpha > ALPHA_VISIBLE
    strong = alpha >= 128
    if np.any(visible):
        yy, xx = np.where(visible)
        bbox = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
        rgb = rgba[:, :, :3][visible].astype(np.float32)
        luminance = rgb @ np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
        mean_luma, std_luma = float(luminance.mean()), float(luminance.std())
    else:
        bbox, mean_luma, std_luma = [0, 0, 0, 0], 0.0, 0.0
    transparent = alpha == 0
    contaminated = bool(np.any(rgba[:, :, :3][transparent] > 8)) if np.any(transparent) else False
    return {
        "alpha_min": int(alpha.min()),
        "alpha_max": int(alpha.max()),
        "alpha_unique": int(len(np.unique(alpha))),
        "coverage_16": round(float(visible.mean()), 6),
        "coverage_128": round(float(strong.mean()), 6),
        "visible_bbox": bbox,
        "visible_luminance_mean": round(mean_luma, 4),
        "visible_luminance_std": round(std_luma, 4),
        "transparent_rgb_present": contaminated,
    }


def average_hash(image: Image.Image) -> str:
    gray = np.asarray(image.convert("RGBA").resize((8, 8), Image.Resampling.LANCZOS).convert("L"), dtype=np.uint8)
    bits = (gray >= gray.mean()).flatten()
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    return f"{value:016x}"


def classify_default(index: int, metrics: dict) -> tuple[str, str]:
    if metrics["alpha_max"] == 0:
        return "empty", "excluded"
    if metrics["coverage_16"] < 0.005:
        return "nearly_empty", "excluded"
    return "unknown", "unverified"


def build_catalog(repo: Path, output: Path, curation: dict) -> tuple[dict, dict[str, dict]]:
    manifest_path = repo / "assets-texturas/textures/objects_core/manifest.csv"
    texture_root = manifest_path.parent / "png"
    overrides = {entry["id"]: entry for entry in curation["sources"]}
    sources = []
    seen_ids: set[str] = set()
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            index = int(row["index"])
            source_id = f"objects_core_{index:03d}"
            if source_id in seen_ids:
                raise ValueError(f"duplicate source id: {source_id}")
            seen_ids.add(source_id)
            path = texture_root / f"{index:03d}.png"
            if not path.exists():
                raise FileNotFoundError(path)
            image = Image.open(path).convert("RGBA")
            metrics = alpha_metrics(image)
            classification, confidence = classify_default(index, metrics)
            override = overrides.get(source_id, {})
            record = {
                "id": source_id,
                "index": index,
                "path": rel(path, repo),
                "sha256": sha256_file(path),
                "width": image.width,
                "height": image.height,
                "candidate_source_name": row.get("candidate_source_name") or None,
                "candidate_name_is_heuristic": True,
                "decode": row.get("decode"),
                "format": row.get("format"),
                "classification": override.get("classification", classification),
                "semantic_name": override.get("semantic_name"),
                "confidence": override.get("confidence", confidence),
                "approved": bool(override.get("approved", False)),
                "tags": sorted(override.get("tags", [])),
                "metrics": metrics,
                "average_hash": average_hash(image),
            }
            sources.append(record)
    exact_groups: dict[str, list[str]] = {}
    perceptual_groups: dict[str, list[str]] = {}
    for source in sources:
        exact_groups.setdefault(source["sha256"], []).append(source["id"])
        perceptual_groups.setdefault(source["average_hash"], []).append(source["id"])
    duplicates = {
        "exact": sorted((ids for ids in exact_groups.values() if len(ids) > 1), key=lambda ids: ids[0]),
        "perceptual_candidates": sorted((ids for ids in perceptual_groups.values() if len(ids) > 1), key=lambda ids: ids[0]),
    }
    catalog = {
        "schema_version": 1,
        "generator": GENERATOR,
        "source_manifest": rel(manifest_path, repo),
        "source_count": len(sources),
        "approved_count": sum(bool(source["approved"]) for source in sources),
        "duplicates": duplicates,
        "sources": sources,
    }
    write_json(output / "catalog/source_catalog.json", catalog)
    write_json(output / "catalog/allowlist.json", {
        "schema_version": 1,
        "generator": GENERATOR,
        "sources": [source for source in sources if source["approved"]],
    })
    return catalog, {source["id"]: source for source in sources}


def checkerboard(size: tuple[int, int], cell: int = 12) -> Image.Image:
    image = Image.new("RGBA", size, (220, 220, 220, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(x + cell - 1, size[0]), min(y + cell - 1, size[1])), fill=(160, 160, 160, 255))
    return image


def contain(image: Image.Image, bounds: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(bounds, Image.Resampling.LANCZOS)
    return copy


def contact_sheet(repo: Path, records: list[dict], output_path: Path, *, approved_only: bool, title: str) -> None:
    selected = [record for record in records if record["approved"]] if approved_only else records
    columns, tile_w, tile_h, header = 5, 260, 230, 42
    rows = math.ceil(len(selected) / columns)
    sheet = Image.new("RGBA", (columns * tile_w, header + rows * tile_h), (24, 26, 28, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 12), title, fill=(242, 242, 238, 255), font=ImageFont.load_default())
    for index, record in enumerate(selected):
        col, row = index % columns, index // columns
        x, y = col * tile_w, header + row * tile_h
        panel = checkerboard((tile_w - 12, 168), 12)
        source = Image.open(repo / record["path"]).convert("RGBA")
        preview = contain(source, (tile_w - 24, 158))
        panel.alpha_composite(preview, ((panel.width - preview.width) // 2, (panel.height - preview.height) // 2))
        sheet.alpha_composite(panel, (x + 6, y + 4))
        color = (190, 238, 178, 255) if record["approved"] else (218, 218, 212, 255)
        draw.text((x + 8, y + 176), f"{record['id']}  {record['width']}x{record['height']}", fill=color)
        label = record.get("semantic_name") or record["classification"]
        draw.text((x + 8, y + 192), str(label)[:38], fill=(220, 220, 215, 255))
        draw.text((x + 8, y + 208), f"alpha={record['metrics']['coverage_128']:.3f}  {record['confidence']}", fill=(170, 174, 178, 255))
    save_png(sheet, output_path)


def dilate_rgb_under_alpha(image: Image.Image, iterations: int = 8) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    original_alpha = rgba[:, :, 3].copy()
    rgb = rgba[:, :, :3].copy()
    known = original_alpha > 0
    height, width = known.shape
    for _ in range(iterations):
        if bool(np.all(known)):
            break
        accumulator = np.zeros((height, width, 3), dtype=np.uint32)
        counts = np.zeros((height, width), dtype=np.uint16)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            shifted_known = np.roll(known, (dy, dx), axis=(0, 1))
            shifted_rgb = np.roll(rgb, (dy, dx), axis=(0, 1))
            if dy < 0:
                shifted_known[dy:, :] = False
            elif dy > 0:
                shifted_known[:dy, :] = False
            if dx < 0:
                shifted_known[:, dx:] = False
            elif dx > 0:
                shifted_known[:, :dx] = False
            targets = (~known) & shifted_known
            accumulator[targets] += shifted_rgb[targets]
            counts[targets] += 1
        fill = (~known) & (counts > 0)
        if not np.any(fill):
            break
        rgb[fill] = (accumulator[fill] / counts[fill, None]).astype(np.uint8)
        known[fill] = True
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = original_alpha
    return Image.fromarray(rgba, mode="RGBA")


def trim_visible(image: Image.Image, margin: int = 4) -> tuple[Image.Image, list[int]]:
    alpha = np.asarray(image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    yy, xx = np.where(alpha > ALPHA_VISIBLE)
    if not len(xx):
        raise ValueError("sprite has no visible alpha")
    x0, y0 = max(0, int(xx.min()) - margin), max(0, int(yy.min()) - margin)
    x1, y1 = min(image.width, int(xx.max()) + 1 + margin), min(image.height, int(yy.max()) + 1 + margin)
    return image.crop((x0, y0, x1, y1)), [x0, y0, x1, y1]


def build_sprites(repo: Path, output: Path, curation: dict, sources: dict[str, dict]) -> tuple[dict, dict[str, dict]]:
    normalized_root = output / "normalized"
    sprite_root = output / "sprites"
    approved_ids = {source["id"] for source in sources.values() if source["approved"]}
    for source_id in sorted(approved_ids):
        source = sources[source_id]
        cleaned = dilate_rgb_under_alpha(Image.open(repo / source["path"]).convert("RGBA"))
        save_png(cleaned, normalized_root / f"{source_id}.png")
    records = []
    for definition in sorted(curation["sprites"], key=lambda item: item["id"]):
        if definition["source"] not in approved_ids:
            raise ValueError(f"sprite uses non-approved source: {definition['id']}")
        source_path = normalized_root / f"{definition['source']}.png"
        source_image = Image.open(source_path).convert("RGBA")
        rect = tuple(int(value) for value in definition["rect"])
        if rect[0] < 0 or rect[1] < 0 or rect[2] > source_image.width or rect[3] > source_image.height:
            raise ValueError(f"sprite rect outside source: {definition['id']}")
        cropped, trim = trim_visible(source_image.crop(rect))
        cropped = dilate_rgb_under_alpha(cropped)
        path = sprite_root / f"{definition['id']}.png"
        save_png(cropped, path)
        record = {
            **definition,
            "path": rel(path, repo),
            "sha256": sha256_file(path),
            "width": cropped.width,
            "height": cropped.height,
            "trim_within_rect": trim,
            "metrics": alpha_metrics(cropped),
        }
        records.append(record)
    manifest = {"schema_version": 1, "generator": GENERATOR, "sprites": records}
    write_json(output / "sprites/manifest.json", manifest)
    return manifest, {record["id"]: record for record in records}


def vary_sprite(image: Image.Image, recipe: dict, sprite_id: str) -> tuple[Image.Image, dict]:
    digest = hashlib.sha256(f"{recipe['color_seed']}:{sprite_id}".encode("utf-8")).digest()
    unit_a, unit_b = int.from_bytes(digest[:4], "little") / 0xFFFFFFFF, int.from_bytes(digest[4:8], "little") / 0xFFFFFFFF
    brightness = recipe.get("brightness_range", [1.0, 1.0])
    saturation = recipe.get("saturation_range", [1.0, 1.0])
    brightness_factor = brightness[0] + (brightness[1] - brightness[0]) * unit_a
    saturation_factor = saturation[0] + (saturation[1] - saturation[0]) * unit_b
    alpha = image.getchannel("A")
    rgb = ImageEnhance.Color(image.convert("RGB")).enhance(saturation_factor)
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness_factor)
    rgba = rgb.convert("RGBA")
    rgba.putalpha(alpha)
    return rgba, {"brightness": round(brightness_factor, 6), "saturation": round(saturation_factor, 6)}


def preserve_alpha_coverage(image: Image.Image, target_coverage: float, cutoff: int) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    alpha = rgba[:, :, 3].astype(np.float32)
    low, high = 0.25, 4.0
    for _ in range(18):
        middle = (low + high) * 0.5
        coverage = float(np.mean(np.clip(alpha * middle, 0, 255) >= cutoff))
        if coverage < target_coverage:
            low = middle
        else:
            high = middle
    rgba[:, :, 3] = np.clip(alpha * ((low + high) * 0.5), 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def seam_score(image: Image.Image) -> dict:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    return {
        "x_edge_mae": round(float(np.abs(rgb[:, 0] - rgb[:, -1]).mean()), 6),
        "y_edge_mae": round(float(np.abs(rgb[0] - rgb[-1]).mean()), 6),
    }


def make_edges_seamless(image: Image.Image, border: int) -> Image.Image:
    """Feather opposite borders toward their shared average.

    Paired edge pixels become byte-identical while the blend decays toward the
    untouched interior. This is intentionally deterministic and conservative:
    it does not synthesize details or alter the middle of the recovered bark.
    """
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32).copy()
    height, width = rgba.shape[:2]
    border = max(2, min(int(border), width // 3, height // 3))
    original = rgba.copy()
    for distance in range(border):
        amount = distance / max(border - 1, 1)
        left, right = original[:, distance].copy(), original[:, width - 1 - distance].copy()
        average = (left + right) * 0.5
        rgba[:, distance] = average * (1.0 - amount) + left * amount
        rgba[:, width - 1 - distance] = average * (1.0 - amount) + right * amount
    original = rgba.copy()
    for distance in range(border):
        amount = distance / max(border - 1, 1)
        top, bottom = original[distance].copy(), original[height - 1 - distance].copy()
        average = (top + bottom) * 0.5
        rgba[distance] = average * (1.0 - amount) + top * amount
        rgba[height - 1 - distance] = average * (1.0 - amount) + bottom * amount
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), mode="RGBA")


def build_seamless_bark(repo: Path, output: Path, sources: dict[str, dict], source_id: str, material_id: str, label: str) -> dict:
    source = sources[source_id]
    if not source["approved"] or source["classification"] != "bark":
        raise ValueError(f"bark source must be approved: {source_id}")
    source_image = Image.open(repo / source["path"]).convert("RGBA")
    seamless = make_edges_seamless(source_image, border=max(16, source_image.width // 10))
    path = output / "wood" / f"{material_id}.png"
    save_png(seamless, path)
    before, after = seam_score(source_image), seam_score(seamless)
    if after["x_edge_mae"] != 0.0 or after["y_edge_mae"] != 0.0:
        raise ValueError(f"bark seam contract failed: {after}")
    audit = Image.new("RGBA", (1400, 850), (24, 26, 28, 255))
    draw = ImageDraw.Draw(audit)
    draw.text((18, 14), f"{label} seamless audit — {source_id}", fill=(242, 242, 236, 255))
    source_preview = source_image.resize((360, 360), Image.Resampling.NEAREST)
    seamless_preview = seamless.resize((360, 360), Image.Resampling.NEAREST)
    audit.alpha_composite(source_preview, (20, 62))
    audit.alpha_composite(seamless_preview, (400, 62))
    draw.text((20, 434), f"SOURCE seam x={before['x_edge_mae']:.2f} y={before['y_edge_mae']:.2f}", fill=(226, 190, 160, 255))
    draw.text((400, 434), f"SEAMLESS seam x={after['x_edge_mae']:.2f} y={after['y_edge_mae']:.2f}", fill=(178, 232, 170, 255))
    tile = Image.new("RGBA", (600, 600), (0, 0, 0, 255))
    tile_unit = seamless.resize((200, 200), Image.Resampling.NEAREST)
    for y in range(3):
        for x in range(3):
            tile.alpha_composite(tile_unit, (x * 200, y * 200))
    audit.alpha_composite(tile, (780, 62))
    draw.text((780, 676), "3x3 repeat — inspect both seam directions", fill=(220, 220, 214, 255))
    draw.text((20, 500), f"source: {source['id']} / {source['sha256'][:20]}", fill=(178, 182, 185, 255))
    draw.text((20, 528), "method: paired-edge average with 10% inward feather", fill=(178, 182, 185, 255))
    audit_path = output / "review" / f"{material_id}_audit.png"
    save_png(audit, audit_path)
    manifest = {
        "schema_version": 1,
        "generator": GENERATOR,
        "id": material_id,
        "source": source["id"],
        "source_path": source["path"],
        "source_sha256": source["sha256"],
        "path": rel(path, repo),
        "sha256": sha256_file(path),
        "repeat": True,
        "before": before,
        "after": after,
        "audit": rel(audit_path, repo),
    }
    write_json(output / "wood" / f"{material_id}.json", manifest)
    return manifest


def build_conifer_bark(repo: Path, output: Path, sources: dict[str, dict]) -> dict:
    return build_seamless_bark(repo, output, sources, "objects_core_035", "conifer_bark_035_seamless", "Conifer bark")


def build_mips(atlas: Image.Image, root: Path, atlas_id: str, cutoff: int) -> list[dict]:
    level, current = 0, atlas
    target = float(np.mean(np.asarray(atlas)[:, :, 3] >= cutoff))
    records = []
    while current.width >= 64:
        path = root / atlas_id / f"mip_{level}_{current.width}.png"
        save_png(current, path)
        records.append({"level": level, "size": current.width, "path": path, "sha256": sha256_file(path), "coverage": round(float(np.mean(np.asarray(current)[:, :, 3] >= cutoff)), 6)})
        if current.width == 64:
            break
        next_size = current.width // 2
        resized = current.resize((next_size, next_size), Image.Resampling.LANCZOS)
        current = preserve_alpha_coverage(resized, target, cutoff)
        level += 1
    return records


def build_atlas(repo: Path, output: Path, recipe_path: Path, sprites: dict[str, dict]) -> dict:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    validate_recipe(recipe)
    size, padding = int(recipe["size"]), int(recipe["padding"])
    order = list(recipe["sprites"])
    random.Random(int(recipe["layout_seed"])).shuffle(order)
    missing = [sprite_id for sprite_id in order if sprite_id not in sprites]
    if missing:
        raise ValueError(f"unknown sprites in {recipe['id']}: {missing}")
    columns, rows = 2, 3
    cell_w, cell_h = size // columns, size // rows
    atlas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    regions = []
    for index, sprite_id in enumerate(order):
        record = sprites[sprite_id]
        image = Image.open(repo / record["path"]).convert("RGBA")
        image, variation = vary_sprite(image, recipe, sprite_id)
        max_w, max_h = cell_w - 2 * padding, cell_h - 2 * padding
        scale = min(max_w / image.width, max_h / image.height)
        width, height = max(1, round(image.width * scale)), max(1, round(image.height * scale))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        image = dilate_rgb_under_alpha(image, padding)
        col, row = index % columns, index // columns
        x = col * cell_w + (cell_w - width) // 2
        y = row * cell_h + (cell_h - height) // 2
        atlas.alpha_composite(image, (x, y))
        regions.append({
            "sprite": sprite_id,
            "source": record["source"],
            "pixels_top_left": [x, y, width, height],
            "uv_bottom_left": [round(x / size, 8), round(1.0 - (y + height) / size, 8), round((x + width) / size, 8), round(1.0 - y / size, 8)],
            "anchor": record["anchor"],
            "axis": record["axis"],
            "variation": variation,
        })
    atlas_path = output / "atlases" / f"{recipe['id']}.png"
    save_png(atlas, atlas_path)
    downsampled = preserve_alpha_coverage(atlas.resize((256, 256), Image.Resampling.LANCZOS), float(np.mean(np.asarray(atlas)[:, :, 3] >= round(float(recipe["alpha_cutoff"]) * 255))), round(float(recipe["alpha_cutoff"]) * 255))
    atlas_256_path = output / "atlases" / f"{recipe['id']}_256.png"
    save_png(downsampled, atlas_256_path)
    cutoff = round(float(recipe["alpha_cutoff"]) * 255)
    mip_records = build_mips(atlas, output / "mips", recipe["id"], cutoff)
    source_hashes = {sprite_id: sprites[sprite_id]["sha256"] for sprite_id in sorted(set(recipe["sprites"]))}
    manifest = {
        "schema_version": 1,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "id": recipe["id"],
        "family": recipe["family"],
        "recipe": rel(recipe_path, repo),
        "recipe_sha256": sha256_file(recipe_path),
        "layout_seed": recipe["layout_seed"],
        "color_seed": recipe["color_seed"],
        "alpha_mode": "MASK",
        "alpha_cutoff": recipe["alpha_cutoff"],
        "double_sided": True,
        "atlas": rel(atlas_path, repo),
        "atlas_sha256": sha256_file(atlas_path),
        "atlas_256": rel(atlas_256_path, repo),
        "atlas_256_sha256": sha256_file(atlas_256_path),
        "source_sprite_hashes": source_hashes,
        "regions": regions,
        "mips": [{**item, "path": rel(item["path"], repo)} for item in mip_records],
    }
    manifest_path = output / "atlases" / f"{recipe['id']}.json"
    write_json(manifest_path, manifest)
    manifest["manifest"] = rel(manifest_path, repo)
    manifest["manifest_sha256"] = sha256_file(manifest_path)
    return manifest


def sprite_sheet(repo: Path, sprite_manifest: dict, output_path: Path) -> None:
    sprites = sprite_manifest["sprites"]
    columns, tile_w, tile_h = 4, 300, 250
    rows = math.ceil(len(sprites) / columns)
    sheet = Image.new("RGBA", (columns * tile_w, rows * tile_h), (25, 27, 29, 255))
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(sprites):
        col, row = index % columns, index // columns
        x, y = col * tile_w, row * tile_h
        panel = checkerboard((tile_w - 12, 205), 12)
        image = contain(Image.open(repo / record["path"]).convert("RGBA"), (tile_w - 28, 190))
        panel.alpha_composite(image, ((panel.width - image.width) // 2, (panel.height - image.height) // 2))
        sheet.alpha_composite(panel, (x + 6, y + 4))
        draw.text((x + 8, y + 214), record["id"], fill=(232, 232, 225, 255))
        draw.text((x + 8, y + 230), f"source={record['source']}  {record['width']}x{record['height']}", fill=(168, 174, 178, 255))
    save_png(sheet, output_path)


def atlas_review(repo: Path, manifest: dict, output_path: Path) -> None:
    width, height = 1400, 820
    sheet = Image.new("RGBA", (width, height), (24, 26, 28, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 14), f"{manifest['id']} | alpha MASK {manifest['alpha_cutoff']} | {manifest['atlas_sha256'][:16]}", fill=(242, 242, 236, 255))
    atlas = Image.open(repo / manifest["atlas"]).convert("RGBA")
    panel = checkerboard((540, 540), 16)
    preview = atlas.resize((512, 512), Image.Resampling.NEAREST)
    panel.alpha_composite(preview, (14, 14))
    sheet.alpha_composite(panel, (18, 52))
    for region in manifest["regions"]:
        x, y, w, h = region["pixels_top_left"]
        scale = 512 / atlas.width
        draw.rectangle((32 + x * scale, 66 + y * scale, 32 + (x + w) * scale, 66 + (y + h) * scale), outline=(255, 210, 64, 255), width=2)
        draw.text((34 + x * scale, 68 + y * scale), region["sprite"], fill=(255, 238, 148, 255))
    mip_x = 590
    for item in manifest["mips"]:
        image = Image.open(repo / item["path"]).convert("RGBA")
        target = min(220, max(90, item["size"]))
        panel = checkerboard((target, target), max(4, target // 16))
        panel.alpha_composite(image.resize((target, target), Image.Resampling.NEAREST), (0, 0))
        sheet.alpha_composite(panel, (mip_x, 75))
        draw.text((mip_x, 75 + target + 8), f"mip {item['level']} / {item['size']} px", fill=(224, 224, 217, 255))
        draw.text((mip_x, 75 + target + 24), f"coverage {item['coverage']:.3f}", fill=(170, 176, 181, 255))
        mip_x += target + 24
    y = 650
    draw.text((20, y), "PROVENANCE", fill=(196, 232, 184, 255))
    for index, region in enumerate(manifest["regions"]):
        col, row = index % 3, index // 3
        draw.text((20 + col * 450, y + 28 + row * 30), f"{region['sprite']} <- {region['source']} | b={region['variation']['brightness']:.3f} s={region['variation']['saturation']:.3f}", fill=(205, 207, 204, 255))
    save_png(sheet, output_path)


def build_all(repo: Path, output: Path) -> dict:
    curation_path = repo / "procedural/texture_pipeline/config/source_curations.json"
    curation = json.loads(curation_path.read_text(encoding="utf-8"))
    catalog, sources = build_catalog(repo, output, curation)
    contact_sheet(repo, catalog["sources"], output / "review/source_catalog_all.png", approved_only=False, title="Recovered object textures — complete technical catalog")
    contact_sheet(repo, catalog["sources"], output / "review/source_allowlist.png", approved_only=True, title="Vegetation source allowlist — visually verified recovered indices")
    sprite_manifest, sprites = build_sprites(repo, output, curation, sources)
    sprite_sheet(repo, sprite_manifest, output / "review/extracted_sprites.png")
    conifer_bark = build_conifer_bark(repo, output, sources)
    broadleaf_bark = build_seamless_bark(repo, output, sources, "objects_core_036", "broadleaf_bark_036_seamless", "Broadleaf bark")
    shrub_bark = build_seamless_bark(repo, output, sources, "objects_core_025", "shrub_bark_025_seamless", "Shrub bark")
    manifests = []
    recipe_root = repo / "procedural/texture_pipeline/recipes"
    for recipe_path in sorted(recipe_root.glob("*.json")):
        manifest = build_atlas(repo, output, recipe_path, sprites)
        atlas_review(repo, manifest, output / "review" / f"{manifest['id']}_atlas_audit.png")
        manifests.append(manifest)
    library = {
        "schema_version": 1,
        "generator": GENERATOR,
        "curation": rel(curation_path, repo),
        "curation_sha256": sha256_file(curation_path),
        "source_count": catalog["source_count"],
        "approved_source_count": catalog["approved_count"],
        "sprite_count": len(sprites),
        "atlas_count": len(manifests),
        "wood_materials": [conifer_bark, broadleaf_bark, shrub_bark],
        "atlases": manifests,
    }
    write_json(output / "library_manifest.json", library)
    return library


def verify(repo: Path, output: Path) -> dict:
    expected = json.loads((output / "library_manifest.json").read_text(encoding="utf-8"))
    failures = []
    for material in expected.get("wood_materials", []):
        actual = sha256_file(repo / material["path"]) if (repo / material["path"]).exists() else None
        if actual != material["sha256"]:
            failures.append({"path": material["path"], "expected": material["sha256"], "actual": actual})
    for atlas in expected["atlases"]:
        checks = ((atlas["atlas"], atlas["atlas_sha256"]), (atlas["atlas_256"], atlas["atlas_256_sha256"]), (atlas["manifest"], atlas["manifest_sha256"]))
        for path_text, expected_hash in checks:
            path = repo / path_text
            actual = sha256_file(path) if path.exists() else None
            if actual != expected_hash:
                failures.append({"path": path_text, "expected": expected_hash, "actual": actual})
        for mip in atlas["mips"]:
            actual = sha256_file(repo / mip["path"])
            if actual != mip["sha256"]:
                failures.append({"path": mip["path"], "expected": mip["sha256"], "actual": actual})
    return {"ok": not failures, "checked_atlases": len(expected["atlases"]), "failures": failures}


def reproducibility_check(repo: Path, output: Path) -> dict:
    temp_root = repo / "procedural/generated/.texture_pipeline_repro"
    resolved = temp_root.resolve()
    allowed = (repo / "procedural/generated").resolve()
    if allowed not in resolved.parents:
        raise RuntimeError(f"unsafe reproducibility path: {resolved}")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    build_all(repo, temp_root)
    reference = json.loads((output / "library_manifest.json").read_text(encoding="utf-8"))
    candidate = json.loads((temp_root / "library_manifest.json").read_text(encoding="utf-8"))
    failures = []
    for reference_wood, candidate_wood in zip(reference.get("wood_materials", []), candidate.get("wood_materials", []), strict=True):
        if reference_wood["sha256"] != candidate_wood["sha256"]:
            failures.append({"material": reference_wood["id"], "field": "sha256", "reference": reference_wood["sha256"], "candidate": candidate_wood["sha256"]})
    for ref_atlas, new_atlas in zip(reference["atlases"], candidate["atlases"], strict=True):
        for key in ("atlas_sha256", "atlas_256_sha256"):
            if ref_atlas[key] != new_atlas[key]:
                failures.append({"atlas": ref_atlas["id"], "field": key, "reference": ref_atlas[key], "candidate": new_atlas[key]})
        ref_regions = [{key: value for key, value in region.items() if key != "path"} for region in ref_atlas["regions"]]
        new_regions = [{key: value for key, value in region.items() if key != "path"} for region in new_atlas["regions"]]
        if canonical_bytes(ref_regions) != canonical_bytes(new_regions):
            failures.append({"atlas": ref_atlas["id"], "field": "regions"})
    shutil.rmtree(temp_root)
    return {"ok": not failures, "checked_atlases": len(reference["atlases"]), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic foliage atlases from recovered textures")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("procedural/generated/texture_pipeline"))
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--reproducibility-check", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    generated_root = (repo / "procedural/generated").resolve()
    if generated_root not in output.resolve().parents:
        raise SystemExit(f"output must remain below {generated_root}")
    if args.verify:
        report = verify(repo, output)
    elif args.reproducibility_check:
        report = reproducibility_check(repo, output)
    else:
        if args.clean and output.exists():
            shutil.rmtree(output)
        report = build_all(repo, output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
