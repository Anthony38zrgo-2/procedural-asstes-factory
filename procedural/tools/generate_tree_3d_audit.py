from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from defusedxml import ElementTree as SafeET
from PIL import Image, ImageDraw

from voxelize_semantic_tree import PATH_L, PATH_Q, _hex, _local


def _hash_unit(text: str) -> float:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "little") / 0xFFFFFFFF


def _depth(x: float, y: float) -> float:
    return 18.0 * math.sin(x * 0.014) + 12.0 * math.cos(y * 0.011)


def _project(point: tuple[float, float, float], scale: float, origin: tuple[float, float]) -> tuple[float, float, float]:
    x, y, z = point
    sx = origin[0] + (0.86 * x - 0.50 * z) * scale
    sy = origin[1] - y * scale + (0.26 * x + 0.45 * z) * scale
    camera_depth = 0.50 * x + 0.86 * z
    return sx, sy, camera_depth


def _parse_branches(svg_path: Path) -> tuple[list[dict], list[tuple[float, float, float]]]:
    root = SafeET.fromstring(svg_path.read_bytes())
    segments: list[dict] = []
    tips: list[tuple[float, float, float]] = []
    for index, element in enumerate(root.iter()):
        role = element.get("data-role")
        if _local(element.tag) != "path" or role not in {"root", "trunk", "branch"}:
            continue
        data = element.get("d", "")
        qmatch, lmatch = PATH_Q.fullmatch(data), PATH_L.fullmatch(data)
        width = float(element.get("stroke-width", "2"))
        if qmatch:
            x0, y0, qx, qy, x1, y1 = map(float, qmatch.groups())
            points = []
            for step in range(9):
                t, inv = step / 8, 1 - step / 8
                x = inv * inv * x0 + 2 * inv * t * qx + t * t * x1
                sy = inv * inv * y0 + 2 * inv * t * qy + t * t * y1
                points.append((x - 256, 512 - sy, _depth(x, sy)))
        elif lmatch:
            x0, y0, x1, y1 = map(float, lmatch.groups())
            points = [(x0 - 256, 512 - y0, _depth(x0, y0)), (x1 - 256, 512 - y1, _depth(x1, y1))]
        else:
            continue
        for start, end in zip(points, points[1:]):
            segments.append({"start": start, "end": end, "width": width, "role": role, "index": index})
        if role == "branch" and width <= 1.15:
            tips.append(points[-1])
    return segments, tips


def _cluster_centers(tips: list[tuple[float, float, float]], count: int) -> list[tuple[float, float, float]]:
    candidates = sorted(tips, key=lambda p: (p[1], p[0], p[2]))
    centers = [max(candidates, key=lambda p: p[1])]
    while len(centers) < min(count, len(candidates)):
        chosen = max(candidates, key=lambda point: min(math.dist(point, center) for center in centers))
        centers.append(chosen)
    return centers


def _leaf_cards(
    centers: list[tuple[float, float, float]],
    seed: int,
    cards_min: int,
    cards_max: int,
    minimum_distance: float,
) -> list[dict]:
    rng = random.Random(seed)
    cards = []
    for cluster_index, center in enumerate(centers):
        accepted: list[tuple[float, float, float]] = []
        target = rng.randint(cards_min, cards_max)
        attempts = 0
        while len(accepted) < target and attempts < 240:
            attempts += 1
            offset = (rng.uniform(-18, 18), rng.uniform(-12, 12), rng.uniform(-14, 14))
            normalized = (offset[0] / 18) ** 2 + (offset[1] / 12) ** 2 + (offset[2] / 14) ** 2
            if normalized > 1 or any(math.dist(offset, other) < minimum_distance for other in accepted):
                continue
            accepted.append(offset)
        for leaf_index, offset in enumerate(accepted):
            position = tuple(center[i] + offset[i] for i in range(3))
            radial_angle = math.atan2(position[2], position[0] or 0.001)
            mode = rng.random()
            if mode < 0.50:  # outward-facing plane
                tangent = (-math.sin(radial_angle), 0.0, math.cos(radial_angle))
            elif mode < 0.80:  # rotate around supporting cluster
                angle = radial_angle + rng.uniform(-1.0, 1.0)
                tangent = (-math.sin(angle), 0.0, math.cos(angle))
            else:  # camera-biased card for stable readability
                tangent = (0.86, 0.0, -0.50)
            cards.append({
                "center": position,
                "tangent": tangent,
                "width": rng.uniform(5.0, 9.0),
                "height": rng.uniform(3.0, 6.0),
                "tone": rng.choices([1, 2, 3, 4], [2, 6, 3, 1])[0],
                "key": f"{cluster_index}:{leaf_index}",
            })
    return cards


def generate(
    svg_path: Path,
    palette_path: Path,
    output: Path,
    report_path: Path,
    *,
    branch_radius_scale: float = 1.3,
    cluster_count: int = 48,
    cards_min: int = 13,
    cards_max: int = 18,
    poisson_min_distance: float = 4.0,
) -> dict:
    palette = json.loads(palette_path.read_text(encoding="utf-8"))["categories"]["tree"]
    wood = [_hex(color) for color in palette["branch"]]
    leaves = [_hex(color) for color in palette["leaf"]]
    segments, tips = _parse_branches(svg_path)
    centers = _cluster_centers(tips, cluster_count)
    cards = _leaf_cards(centers, 7391, cards_min, cards_max, poisson_min_distance)

    supersample = 2
    canvas = Image.new("RGBA", (900 * supersample, 900 * supersample), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    scale = 1.28 * supersample
    origin = (450 * supersample, 790 * supersample)
    primitives = []
    for segment in segments:
        start = _project(segment["start"], scale, origin)
        end = _project(segment["end"], scale, origin)
        pigment = _hash_unit(f"wood:{segment['index']}")
        color_index = 1 if pigment < 0.16 else 3 if pigment > 0.78 else 2
        primitives.append((0.5 * (start[2] + end[2]), "wood", segment, start, end, wood[color_index]))
    for card in cards:
        projected = _project(card["center"], scale, origin)
        primitives.append((projected[2], "leaf", card, projected, None, leaves[card["tone"]]))
    primitives.sort(key=lambda item: item[0], reverse=True)

    for _, kind, data, projected, end, color in primitives:
        if kind == "wood":
            width = max(1, round(data["width"] * scale * 0.72 * branch_radius_scale))
            draw.line((projected[0], projected[1], end[0], end[1]), fill=color + (255,), width=width)
            highlight = tuple(min(255, int(channel * 1.13)) for channel in color)
            draw.line((projected[0]-width*0.12, projected[1], end[0]-width*0.12, end[1]), fill=highlight + (150,), width=max(1, width // 5))
        else:
            center = data["center"]
            tangent = data["tangent"]
            half_w, half_h = data["width"] * 0.5, data["height"] * 0.5
            corners = []
            for horizontal, vertical in ((-1,-1),(1,-1),(1,1),(-1,1)):
                point = (center[0] + tangent[0] * half_w * horizontal, center[1] + half_h * vertical, center[2] + tangent[2] * half_w * horizontal)
                px, py, _ = _project(point, scale, origin)
                corners.append((px, py))
            draw.polygon(corners, fill=color + (236,))
            if _hash_unit(f"leaf:{data['key']}") > 0.72:
                vein = tuple(max(0, int(channel * 0.72)) for channel in color)
                draw.line((corners[0], corners[2]), fill=vein + (130,), width=1 * supersample)

    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)
    canvas = canvas.resize((canvas.width // supersample, canvas.height // supersample), Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=False)
    report = {"source": svg_path.as_posix(), "branch_segments": len(segments), "terminal_tips": len(tips), "foliage_clusters": len(centers), "leaf_cards_2d": len(cards), "branch_radius_scale": branch_radius_scale, "cards_per_cluster": [cards_min, cards_max], "poisson_min_distance": poisson_min_distance, "wood_geometry": "depth-sorted_bezier_tubes_audit", "leaf_distribution": "poisson_rejection_in_oriented_ellipsoids", "pigmentation": "biome_palette_wood_moderate_leaf_full"}
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a 3D tree audit with clustered 2D foliage cards")
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--palette", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--branch-radius-scale", type=float, default=1.3)
    parser.add_argument("--cluster-count", type=int, default=48)
    parser.add_argument("--cards-min", type=int, default=13)
    parser.add_argument("--cards-max", type=int, default=18)
    parser.add_argument("--poisson-min-distance", type=float, default=4.0)
    args = parser.parse_args()
    print(json.dumps(generate(
        args.svg, args.palette, args.output, args.report,
        branch_radius_scale=args.branch_radius_scale,
        cluster_count=args.cluster_count,
        cards_min=args.cards_min,
        cards_max=args.cards_max,
        poisson_min_distance=args.poisson_min_distance,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
