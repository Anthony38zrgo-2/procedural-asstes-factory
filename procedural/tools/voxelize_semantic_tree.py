from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
from defusedxml import ElementTree as SafeET
from PIL import Image, ImageDraw

ROLE_ID = {"root": 1, "trunk": 2, "branch": 3, "detail": 3, "foliage": 4, "leaf": 4}
PATH_Q = re.compile(r"M\s+([-.\d]+)\s+([-.\d]+)\s+Q\s+([-.\d]+)\s+([-.\d]+)\s+([-.\d]+)\s+([-.\d]+)")
PATH_L = re.compile(r"M\s+([-.\d]+)\s+([-.\d]+)\s+L\s+([-.\d]+)\s+([-.\d]+)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hex(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def _depth_field(x: float, y: float, center: float) -> float:
    return center + 2.2 * math.sin(x * 0.041) + 1.5 * math.cos(y * 0.033)


def _element_offset(asset_id: str, index: int, spread: float) -> float:
    digest = hashlib.sha256(f"{asset_id}:{index}".encode()).digest()
    unit = int.from_bytes(digest[:4], "little") / 0xFFFFFFFF
    return (unit - 0.5) * 2.0 * spread


def _stamp_ellipsoid(grid: np.ndarray, cx: float, cy: float, cz: float, rx: float, ry: float, rz: float, value: int) -> None:
    x0, x1 = max(0, int(cx - rx - 1)), min(grid.shape[0], int(cx + rx + 2))
    y0, y1 = max(0, int(cy - ry - 1)), min(grid.shape[1], int(cy + ry + 2))
    z0, z1 = max(0, int(cz - rz - 1)), min(grid.shape[2], int(cz + rz + 2))
    for x in range(x0, x1):
        for y in range(y0, y1):
            for z in range(z0, z1):
                distance = ((x - cx) / max(rx, 0.5)) ** 2 + ((y - cy) / max(ry, 0.5)) ** 2 + ((z - cz) / max(rz, 0.5)) ** 2
                if distance <= 1.0 and (grid[x, y, z] == 0 or value < 4):
                    grid[x, y, z] = value


def voxelize(
    svg_path: Path,
    size: tuple[int, int, int] = (96, 96, 48),
    *,
    include_foliage: bool = True,
) -> tuple[np.ndarray, dict]:
    root = SafeET.fromstring(svg_path.read_bytes())
    asset_id = root.get("data-asset-id", svg_path.stem)
    grid = np.zeros(size, dtype=np.uint8)
    scale_x = (size[0] - 1) / 512.0
    scale_y = (size[1] - 1) / 512.0
    center_z = (size[2] - 1) * 0.5
    counts: dict[str, int] = {}

    for index, element in enumerate(root.iter()):
        role = element.get("data-role")
        if role not in ROLE_ID:
            continue
        tag = _local(element.tag)
        value = ROLE_ID[role]
        counts[role] = counts.get(role, 0) + 1
        if tag == "path":
            data = element.get("d", "")
            qmatch = PATH_Q.fullmatch(data)
            lmatch = PATH_L.fullmatch(data)
            if qmatch:
                x0, y0, qx, qy, x1, y1 = map(float, qmatch.groups())
                estimated = math.dist((x0, y0), (qx, qy)) + math.dist((qx, qy), (x1, y1))
                steps = max(3, int(estimated * scale_x * 2.0))
                points = []
                for step in range(steps + 1):
                    t = step / steps
                    inv = 1.0 - t
                    points.append((inv * inv * x0 + 2 * inv * t * qx + t * t * x1, inv * inv * y0 + 2 * inv * t * qy + t * t * y1))
            elif lmatch:
                x0, y0, x1, y1 = map(float, lmatch.groups())
                steps = max(3, int(math.dist((x0, y0), (x1, y1)) * scale_x * 2.0))
                points = [(x0 + (x1 - x0) * step / steps, y0 + (y1 - y0) * step / steps) for step in range(steps + 1)]
            else:
                continue
            stroke = float(element.get("stroke-width", "2"))
            radius = max(0.62, stroke * scale_x * 0.5)
            for px, py in points:
                vx, vy = px * scale_x, (512.0 - py) * scale_y
                vz = _depth_field(vx, vy, center_z)
                _stamp_ellipsoid(grid, vx, vy, vz, radius, radius, max(0.7, radius * 0.82), value)
        elif include_foliage and tag == "ellipse" and role in {"leaf", "foliage"}:
            px, py = float(element.get("cx", "0")), float(element.get("cy", "0"))
            rx, ry = float(element.get("rx", "2")), float(element.get("ry", "2"))
            vx, vy = px * scale_x, (512.0 - py) * scale_y
            vz = _depth_field(vx, vy, center_z) + _element_offset(asset_id, index, size[2] * 0.18)
            _stamp_ellipsoid(grid, vx, vy, vz, max(0.8, rx * scale_x), max(0.7, ry * scale_y), max(1.0, (rx + ry) * scale_x * 0.75), value)

    occupied = int(np.count_nonzero(grid))
    return grid, {"asset_id": asset_id, "grid_size": list(size), "occupied_voxels": occupied, "fill_ratio": occupied / grid.size, "semantic_elements": counts, "depth": "continuous_field_plus_seeded_leaf_spread", "foliage_voxelized": include_foliage}


def extract_leaf_sprites(svg_path: Path, size: tuple[int, int, int]) -> list[dict]:
    root = SafeET.fromstring(svg_path.read_bytes())
    asset_id = root.get("data-asset-id", svg_path.stem)
    scale_x = (size[0] - 1) / 512.0
    scale_y = (size[1] - 1) / 512.0
    center_z = (size[2] - 1) * 0.5
    sprites = []
    for index, element in enumerate(root.iter()):
        if _local(element.tag) != "ellipse" or element.get("data-role") not in {"leaf", "foliage"}:
            continue
        px, py = float(element.get("cx", "0")), float(element.get("cy", "0"))
        rx, ry = float(element.get("rx", "2")), float(element.get("ry", "2"))
        vx, vy = px * scale_x, (512.0 - py) * scale_y
        sprites.append({
            "x": vx,
            "y": vy,
            "z": _depth_field(vx, vy, center_z) + _element_offset(asset_id, index, size[2] * 0.18),
            "rx": max(0.75, rx * scale_x),
            "ry": max(0.55, ry * scale_y),
            "tone": element.get("data-tone", "base"),
        })
    return sprites


def render_isometric(grid: np.ndarray, palette: dict, output: Path, scale: int = 4) -> None:
    category = palette["categories"]["tree"]
    colors = {1: _hex(category["root"][2]), 2: _hex(category["trunk"][2]), 3: _hex(category["branch"][2]), 4: _hex(category["foliage"][2])}
    canvas = Image.new("RGBA", (800, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    origin_x, origin_y = 400, 650
    voxels = np.argwhere(grid > 0)
    surface = []
    for x, y, z in voxels:
        if any(nx < 0 or ny < 0 or nz < 0 or nx >= grid.shape[0] or ny >= grid.shape[1] or nz >= grid.shape[2] or grid[nx, ny, nz] == 0 for nx, ny, nz in ((x-1,y,z),(x+1,y,z),(x,y-1,z),(x,y+1,z),(x,y,z-1),(x,y,z+1))):
            surface.append((int(x), int(y), int(z), int(grid[x, y, z])))
    surface.sort(key=lambda item: (item[0] + item[2], item[1]))
    for x, y, z, material in surface:
        sx = origin_x + (x - z) * scale
        sy = origin_y + (x + z) * scale * 0.48 - y * scale
        top = [(sx, sy-scale), (sx+scale, sy-scale//2), (sx, sy), (sx-scale, sy-scale//2)]
        left = [(sx-scale, sy-scale//2), (sx, sy), (sx, sy+scale), (sx-scale, sy+scale//2)]
        right = [(sx, sy), (sx+scale, sy-scale//2), (sx+scale, sy+scale//2), (sx, sy+scale)]
        base = colors[material]
        light = tuple(min(255, int(channel * 1.17)) for channel in base)
        dark = tuple(int(channel * 0.68) for channel in base)
        mid = tuple(int(channel * 0.86) for channel in base)
        draw.polygon(left, fill=dark + (255,))
        draw.polygon(right, fill=mid + (255,))
        draw.polygon(top, fill=light + (255,))
    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=False)


def render_hybrid_isometric(
    wood_grid: np.ndarray, leaves: list[dict], palette: dict, output: Path, scale: int = 4
) -> None:
    category = palette["categories"]["tree"]
    leaf_colors = category["leaf"]
    tone_index = {"deep-shadow": 0, "shadow": 1, "base": 2, "light": 3, "highlight": 4, "accent": 5}
    canvas = Image.new("RGBA", (800, 760), (0, 0, 0, 0))
    origin_x, origin_y = 400, 650

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return origin_x + (x - z) * scale, origin_y + (x + z) * scale * 0.48 - y * scale

    def draw_leaf(sprite: dict) -> None:
        sx, sy = project(sprite["x"], sprite["y"], sprite["z"])
        rx = max(2.0, sprite["rx"] * scale)
        ry = max(1.2, sprite["ry"] * scale)
        color = _hex(leaf_colors[tone_index.get(sprite["tone"], 2)])
        ImageDraw.Draw(canvas).ellipse((sx-rx, sy-ry, sx+rx, sy+ry), fill=color + (235,))

    center_z = (wood_grid.shape[2] - 1) * 0.5
    for sprite in sorted((item for item in leaves if item["z"] >= center_z), key=lambda item: item["z"], reverse=True):
        draw_leaf(sprite)

    wood_palette = {key: value for key, value in palette.items()}
    wood_layer_path = output.with_suffix(".wood.tmp.png")
    render_isometric(wood_grid, wood_palette, wood_layer_path, scale)
    wood_layer = Image.open(wood_layer_path).convert("RGBA")
    # render_isometric crops; center its audit layer over the same canvas.
    canvas.alpha_composite(wood_layer, ((canvas.width - wood_layer.width) // 2, canvas.height - wood_layer.height))
    wood_layer_path.unlink()

    for sprite in sorted((item for item in leaves if item["z"] < center_z), key=lambda item: item["z"], reverse=True):
        draw_leaf(sprite)
    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Voxelize a semantic tree and render an isometric audit PNG")
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--palette", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    palette = json.loads(args.palette.read_text(encoding="utf-8"))
    grid, report = voxelize(args.svg, include_foliage=False)
    leaves = extract_leaf_sprites(args.svg, tuple(report["grid_size"]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output_dir / f"{report['asset_id']}.npz", voxels=grid)
    render_hybrid_isometric(grid, leaves, palette, args.output_dir / f"{report['asset_id']}_hybrid_isometric.png")
    report["render_mode"] = "voxel_wood_with_2d_leaf_sprites"
    report["leaf_sprites_2d"] = len(leaves)
    (args.output_dir / f"{report['asset_id']}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
