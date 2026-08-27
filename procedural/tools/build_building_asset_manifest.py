"""Validate scenic building GLBs and publish their review/asset manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw


OUTPUT_DIR = Path("game/resources/environment/assets/buildings")
REVIEW_DIR = OUTPUT_DIR / "review"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_visual(path: Path) -> trimesh.Trimesh:
    scene = trimesh.load(path, force="scene")
    parts = []
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph.get(node)
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        material = getattr(mesh.visual, "material", None)
        main = np.asarray(getattr(material, "main_color", (170, 165, 155, 255)), dtype=np.uint8)
        mesh.visual = trimesh.visual.ColorVisuals(
            mesh=mesh, vertex_colors=np.tile(main, (len(mesh.vertices), 1)),
        )
        parts.append(mesh)
    if not parts:
        raise ValueError(f"Building GLB contains no geometry: {path}")
    return trimesh.util.concatenate(parts)


def validate(mesh: trimesh.Trimesh, source: dict, contract: dict) -> dict:
    if not np.isfinite(mesh.vertices).all():
        raise ValueError(f"{source['id']}: non-finite vertices")
    if np.any(mesh.area_faces <= 1e-9):
        raise ValueError(f"{source['id']}: degenerate triangles")
    if not mesh.is_winding_consistent:
        raise ValueError(f"{source['id']}: inconsistent winding")
    if len(mesh.faces) > int(source["triangle_budget"]):
        raise ValueError(f"{source['id']}: triangle budget exceeded")
    tolerance = float(contract["geometry"]["ground_tolerance_m"])
    if abs(float(mesh.bounds[0][1])) > tolerance:
        raise ValueError(f"{source['id']}: pivot is not grounded on Y=0")
    return {
        "vertices": int(len(mesh.vertices)),
        "triangles": int(len(mesh.faces)),
        "bounds_min": [round(float(value), 6) for value in mesh.bounds[0]],
        "bounds_max": [round(float(value), 6) for value in mesh.bounds[1]],
        "extents": [round(float(value), 6) for value in mesh.extents],
        "winding_consistent": bool(mesh.is_winding_consistent),
        "watertight": bool(mesh.is_watertight),
    }


def _rotate(values: np.ndarray, yaw: float, pitch: float) -> np.ndarray:
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    values = values @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]).T
    return values @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]]).T


def render_preview(mesh: trimesh.Trimesh, path: Path) -> None:
    image = Image.new("RGBA", (900, 900), (28, 30, 32, 255))
    draw = ImageDraw.Draw(image)
    views = ((0.0, 0.0, "front"), (math.pi / 4, 0.0, "45 deg"),
             (math.pi / 2, 0.0, "side"), (math.pi / 4, -0.25, "iso"))
    light = np.asarray((-0.3, 0.8, 0.5)); light /= np.linalg.norm(light)
    colors = mesh.visual.vertex_colors[:, :3]
    for index, (yaw, pitch, label) in enumerate(views):
        tx, ty = (index % 2) * 450, (index // 2) * 450
        rotated = _rotate(mesh.vertices, yaw, pitch)
        points, depths = rotated[:, :2], rotated[:, 2]
        minimum, maximum = points.min(axis=0), points.max(axis=0)
        scale = 350.0 / max(float(np.max(maximum - minimum)), 1e-6)
        center = (minimum + maximum) * 0.5
        normals = _rotate(mesh.face_normals, yaw, pitch)
        faces = []
        for face_index, face in enumerate(mesh.faces):
            polygon = [(tx + 225 + (points[i][0] - center[0]) * scale,
                        ty + 220 - (points[i][1] - center[1]) * scale) for i in face]
            factor = 0.72 + 0.34 * max(0.0, float(normals[face_index] @ light))
            color = np.clip(np.mean(colors[face], axis=0) * factor, 0, 255).astype(np.uint8)
            faces.append((float(np.mean(depths[face])), polygon, tuple(int(v) for v in color)))
        draw.ellipse((tx + 75, ty + 380, tx + 375, ty + 414), fill=(8, 9, 10, 125))
        for _, polygon, color in sorted(faces, key=lambda item: item[0]):
            draw.polygon(polygon, fill=(*color, 255))
        draw.text((tx + 12, ty + 12), label, fill=(240, 240, 240, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    source_path = args.sources.resolve()
    sources = json.loads(source_path.read_text(encoding="utf-8"))
    contract_path = repo / sources["construction_manifest"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if sources.get("schema_version") != 1 or contract.get("schema_version") != 1:
        raise ValueError("Unsupported building manifest schema")
    output = repo / OUTPUT_DIR
    review = repo / REVIEW_DIR
    assets = []
    for source in sources["assets"]:
        glb = repo / source["glb"]
        mesh = load_visual(glb)
        geometry = validate(mesh, source, contract)
        preview = review / f"{source['id']}.png"
        render_preview(mesh, preview)
        assets.append({
            **source,
            "glb_sha256": sha256_file(glb),
            "preview": (REVIEW_DIR / preview.name).as_posix(),
            "preview_sha256": sha256_file(preview),
            "geometry": geometry,
            "collision": False,
        })
    catalog = Image.new("RGBA", (900, 450), (20, 22, 24, 255))
    catalog_draw = ImageDraw.Draw(catalog)
    for index, asset in enumerate(assets):
        source_image = Image.open(repo / asset["preview"]).convert("RGBA")
        source_image.thumbnail((430, 410), Image.Resampling.LANCZOS)
        x = index * 450
        catalog.alpha_composite(source_image, (x + (450 - source_image.width) // 2, 30))
        catalog_draw.text((x + 10, 8), asset["id"], fill=(240, 240, 240, 255))
    catalog_path = review / "building_library_catalog.png"
    catalog.save(catalog_path)
    manifest = {
        "schema_version": 1,
        "generator": "formula90_building_manifest_v1",
        "sources_sha256": sha256_file(source_path),
        "construction_manifest": sources["construction_manifest"],
        "construction_manifest_sha256": sha256_file(contract_path),
        "human_gate_catalog": (REVIEW_DIR / catalog_path.name).as_posix(),
        "human_gate_catalog_sha256": sha256_file(catalog_path),
        "assets": assets,
    }
    manifest_path = output / "building_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assets": len(assets), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
