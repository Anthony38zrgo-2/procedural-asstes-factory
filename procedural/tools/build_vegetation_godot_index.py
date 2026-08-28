from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rounded(values: list[float]) -> list[float]:
    return [round(float(value), 5) for value in values]


def godot_vector(blender_xyz: list[float]) -> list[float]:
    """Blender Z-up to glTF/Godot Y-up, preserving the exported handedness."""
    x, y, z = (float(value) for value in blender_xyz)
    return rounded([x, z, -y])


def godot_aabb(record: dict) -> tuple[list[float], list[float], list[float]]:
    bmin = record["bounds_min"]
    bmax = record["bounds_max"]
    minimum = godot_vector([bmin[0], bmax[1], bmin[2]])
    maximum = godot_vector([bmax[0], bmin[1], bmax[2]])
    size = rounded([maximum[index] - minimum[index] for index in range(3)])
    return minimum, maximum, size


def visibility_ranges(category: str, lod_index: int, max_dimension: float, levels: int) -> dict:
    if levels == 1:
        end = max(24.0 if category == "grass" else 80.0, max_dimension * (22.0 if category == "grass" else 16.0))
        return {"begin_m": 0.0, "end_m": round(end, 2), "fade_margin_m": round(min(4.0, end * 0.10), 2)}
    transition = max(22.0, max_dimension * 8.0)
    if lod_index == 0:
        return {"begin_m": 0.0, "end_m": round(transition * 1.08, 2), "fade_margin_m": round(max(2.0, transition * 0.12), 2)}
    return {"begin_m": round(transition * 0.92, 2), "end_m": round(max(90.0, max_dimension * 24.0), 2), "fade_margin_m": round(max(3.0, transition * 0.16), 2)}


def normalized_record(repo: Path, record: dict, source_manifest: str, available_lods: list[str]) -> dict:
    category = record.get("kind", "conifer")
    variant = record.get("variant", "green")
    source_lod = record.get("lod")
    lod_name = source_lod or "lod0"
    lod_index = int(lod_name.removeprefix("lod"))
    glb_path = record["glb"]
    minimum, maximum, size = godot_aabb(record)
    dimensions_godot = godot_vector(record["dimensions"])
    dimensions_godot = rounded([abs(value) for value in dimensions_godot])
    ground_correction = round(max(0.0, -minimum[1]), 5)
    max_dimension = max(size)
    materials = record.get("materials", {})
    alpha_mode = record.get("alpha_mode", materials.get("alpha_mode", "MASK"))
    return {
        "name": Path(glb_path).stem,
        "asset_id": record["id"],
        "category": category,
        "family": record.get("family", "conifer" if category == "conifer" else None),
        "color": variant,
        "lod": {
            "name": lod_name,
            "level": lod_index,
            "available": available_lods,
            "visibility": visibility_ranges(category, lod_index, max_dimension, len(available_lods)),
        },
        "files": {
            "glb": glb_path,
            "godot_resource": "res://" + glb_path,
            "sha256": record["glb_sha256"],
            "audit_png": record.get("audit"),
        },
        "geometry": {
            "units": "meters",
            "triangles": record["triangles"],
            "vertices": record["vertices"],
            "draw_meshes": record.get("draw_meshes", 1 if category == "grass" else 2),
            "dimensions_m": {"godot_xyz": dimensions_godot, "source_blender_xyz": rounded(record["dimensions"])},
            "aabb_godot": {"position": minimum, "size": size, "min": minimum, "max": maximum},
            "bounding_radius_m": round(math.sqrt(sum((value * 0.5) ** 2 for value in size)), 5),
        },
        "placement": {
            "pivot": "base_center",
            "ground_axis": "+Y",
            "ground_plane_y_m": 0.0,
            "recommended_transform": {
                "position": [0.0, ground_correction, 0.0],
                "rotation_degrees": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
            "ground_correction_y_m": ground_correction,
            "placement_radius_m": round(max(size[0], size[2]) * 0.5, 5),
        },
        "rendering": {
            "alpha_mode": alpha_mode,
            "alpha_cutoff": materials.get("alpha_cutoff", 0.46 if category == "grass" else None),
            "double_sided_foliage": True,
            "casts_shadow": True,
            "recommended_import_scale": 1.0,
        },
        "provenance": {
            "source_manifest": source_manifest,
            "seed": record.get("seed"),
            "atlas": record.get("atlas", materials.get("foliage")),
            "wood": record.get("wood", materials.get("wood")),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve() if args.output else repo / "procedural/generated/vegetation_catalog_godot.json"
    manifest_paths = [
        "procedural/generated/vegetation_v5/manifest.json",
        "procedural/generated/vegetation_v5/grass_manifest.json",
        "procedural/generated/conifers_v5/manifest.json",
    ]
    loaded: list[tuple[str, dict]] = []
    all_records: list[tuple[str, dict]] = []
    for relative in manifest_paths:
        path = repo / relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        loaded.append((relative, manifest))
        all_records.extend((relative, record) for record in manifest["records"])

    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for _, record in all_records:
        groups[(record["id"], record.get("variant", "green"))].add(record.get("lod") or "lod0")

    assets = [
        normalized_record(repo, record, source, sorted(groups[(record["id"], record.get("variant", "green"))]))
        for source, record in all_records
    ]
    assets.sort(key=lambda item: (item["category"], item["asset_id"], item["color"], item["lod"]["level"]))
    category_counts = Counter(item["category"] for item in assets)
    index = {
        "schema_version": 1,
        "format": "procedural_vegetation_godot_catalog",
        "engine_target": {"name": "Godot", "minimum_version": "4.2", "renderer": "Forward+ or Compatibility"},
        "coordinate_system": {
            "units": "meters",
            "handedness": "right-handed",
            "up_axis": "+Y",
            "forward_axis": "-Z",
            "source_to_godot": "(x, y, z) -> (x, z, -y)",
            "glb_import_scale": 1.0,
        },
        "import_defaults": {
            "root_type": "Node3D",
            "materials_extract": False,
            "generate_lods": False,
            "create_shadow_meshes": True,
            "light_baking": "Static for placed vegetation; Dynamic for wind-enabled grass",
            "texture_filter": "Linear with mipmaps",
        },
        "summary": {
            "asset_files": len(assets),
            "unique_asset_ids": len({item["asset_id"] for item in assets}),
            "categories": dict(sorted(category_counts.items())),
            "colors": sorted({item["color"] for item in assets}),
        },
        "source_manifests": [
            {"path": relative, "sha256": sha256(repo / relative), "records": len(manifest["records"])}
            for relative, manifest in loaded
        ],
        "assets": assets,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **index["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
