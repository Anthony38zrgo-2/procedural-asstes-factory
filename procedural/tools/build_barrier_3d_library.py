"""Deterministic and validated low-poly barrier GLB generator.

Contract: metres, glTF Y-up, module length on local X, track-facing side on
local +Z, and pivot at ground centre. Visual and collision GLBs are separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from trimesh.visual.material import PBRMaterial


SCHEMA_VERSION = 3
GENERATOR_ID = "gen_barriers_v2"
ASSET_DIR = Path("game/resources/environment/assets/barriers")
REVIEW_DIR = ASSET_DIR / "review"
KNOWN_FAMILIES = {"tire_wall", "concrete", "guardrail"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _hex(value: str) -> tuple[int, int, int]:
    """Convert an exact ``#RRGGBB`` colour to RGB bytes."""
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"Invalid colour {value!r}; expected #RRGGBB")
    try:
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    except ValueError as exc:
        raise ValueError(f"Invalid colour {value!r}; expected #RRGGBB") from exc


def _tone(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(channel * factor))) for channel in color)


def _paint(mesh: trimesh.Trimesh, color: tuple[int, int, int],
           material_kind: str = "generic") -> trimesh.Trimesh:
    """Bake subtle object-space lighting and material variation into vertex colours.

    This is deliberately local and low contrast: Godot remains responsible for
    cast shadows, while the baked values keep volume readable under flat light.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
    light = np.asarray((-0.35, 0.82, 0.46), dtype=np.float64)
    light /= np.linalg.norm(light)
    diffuse = np.clip(normals @ light, 0.0, 1.0)
    bounds = mesh.bounds
    height_span = max(float(bounds[1][1] - bounds[0][1]), 1e-9)
    relative_height = np.clip((vertices[:, 1] - bounds[0][1]) / height_span, 0.0, 1.0)
    grain = np.sin(vertices[:, 0] * 17.13 + vertices[:, 1] * 31.71 + vertices[:, 2] * 11.37)
    factor = 0.72 + diffuse * 0.27 + relative_height * 0.08 + grain * 0.018

    if material_kind == "tire":
        center = bounds.mean(axis=0)
        angle = np.arctan2(vertices[:, 2] - center[2], vertices[:, 0] - center[0])
        tread = 0.94 + 0.06 * (0.5 + 0.5 * np.sin(angle * 12.0))
        underside = 0.90 + relative_height * 0.10
        factor *= tread * underside
    elif material_kind == "concrete":
        factor *= 0.96 + grain * 0.025
    elif material_kind == "metal":
        factor *= 0.94 + diffuse * 0.10
    elif material_kind == "plastic":
        factor *= 0.96 + relative_height * 0.05

    factor = np.clip(factor, 0.68, 1.12)
    rgb = np.clip(np.asarray(color, dtype=np.float64)[None, :] * factor[:, None], 0, 255)
    alpha = np.full((len(vertices), 1), 255.0)
    mesh.visual.vertex_colors = np.concatenate((rgb, alpha), axis=1).round().astype(np.uint8)
    return mesh


def _translated(mesh: trimesh.Trimesh, xyz) -> trimesh.Trimesh:
    mesh.apply_translation(np.asarray(xyz, dtype=np.float64))
    return mesh


def _box(extents, center, color, material_kind="generic") -> trimesh.Trimesh:
    return _paint(_translated(trimesh.creation.box(extents=extents), center), color, material_kind)


def _combine(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    if not parts:
        raise ValueError("Barrier generator produced no geometry")
    return trimesh.util.concatenate(parts)


def _tire_wall_mesh(recipe: dict, palette: dict, rng: random.Random) -> trimesh.Trimesh:
    width = float(recipe["width_m"])
    tires_high = int(recipe["tires_per_column"])
    columns = int(recipe["columns_per_module"])
    depth_layers = int(recipe.get("depth_layers", 1))
    tire_diameter = float(recipe["tire_outer_diameter_m"])
    tire_width = float(recipe["tire_width_m"])
    major_sections = int(recipe.get("tire_major_sections", 12))
    minor_sections = int(recipe.get("tire_minor_sections", 8))
    family = recipe["family"]
    colours = palette["categories"][family]
    rubber = [_hex(value) for value in colours["rubber"]]
    navy = [_hex(value) for value in colours.get("navy", [])]
    white = [_hex(value) for value in colours.get("white", [])]
    outer_radius = tire_diameter * 0.5
    tube_radius = tire_width * 0.5
    major_radius = outer_radius - tube_radius
    layer_step = tire_diameter * 0.72
    parts: list[trimesh.Trimesh] = []
    for layer in range(depth_layers):
        z = -(layer * layer_step)
        layer_columns = columns if layer % 2 == 0 else max(2, columns - 1)
        for level in range(tires_high):
            for column in range(layer_columns):
                x = (column - (layer_columns - 1) * 0.5) * tire_diameter
                y = tire_width * (level + 0.5)
                tire = trimesh.creation.torus(major_radius=major_radius, minor_radius=tube_radius,
                                                major_sections=major_sections,
                                                minor_sections=minor_sections)
                # Trimesh creates a Z-axis torus. A tyre barrier stacks tyres flat,
                # so rotate the axle to vertical Y; holes are visible from above,
                # while the track-facing +Z view sees tread, not circular openings.
                tire.apply_transform(trimesh.transformations.rotation_matrix(math.pi * 0.5, [1, 0, 0]))
                if family == "tire_navy_white":
                    choices = navy if (level + column + layer) % 2 == 0 else white
                    colour = rng.choice(choices)
                else:
                    colour = _tone(rng.choice(rubber), rng.uniform(0.90, 1.08))
                parts.append(_paint(_translated(tire, (x, y, z)), colour, "tire"))
    return _combine(parts)


def _trapezoid_box(width, y0, y1, bottom_depth, top_depth, color,
                   material_kind="generic") -> trimesh.Trimesh:
    x0, x1 = -width * 0.5, width * 0.5
    zb, zt = bottom_depth * 0.5, top_depth * 0.5
    vertices = np.asarray([
        [x0, y0, -zb], [x0, y0, zb], [x0, y1, zt], [x0, y1, -zt],
        [x1, y0, -zb], [x1, y0, zb], [x1, y1, zt], [x1, y1, -zt],
    ], dtype=np.float64)
    faces = np.asarray([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return _paint(trimesh.Trimesh(vertices=vertices, faces=faces, process=False),
                  color, material_kind)


def _concrete_jersey_mesh(recipe: dict, palette: dict, rng: random.Random) -> trimesh.Trimesh:
    width, height, depth = (float(recipe[key]) for key in ("width_m", "height_m", "depth_m"))
    colours = [_hex(value) for value in palette["categories"]["concrete_jersey"]["concrete"]]
    base_height = height * 0.28
    lower = _trapezoid_box(width, 0.0, base_height, depth, depth * 0.68,
                           _tone(rng.choice(colours), 0.88), "concrete")
    upper = _trapezoid_box(width, base_height, height, depth * 0.68, depth * 0.46,
                           _tone(rng.choice(colours), 1.02), "concrete")
    return _combine([lower, upper])


def _guardrail_armco_mesh(recipe: dict, palette: dict, rng: random.Random) -> trimesh.Trimesh:
    width, height, depth = (float(recipe[key]) for key in ("width_m", "height_m", "depth_m"))
    post_count = int(recipe.get("post_count", 2))
    colours = palette["categories"]["guardrail_armco"]
    steel = [_hex(value) for value in colours["steel"]]
    posts = [_hex(value) for value in colours["post"]]
    bolts = [_hex(value) for value in colours["bolt"]]
    parts: list[trimesh.Trimesh] = []
    for index in range(post_count):
        x = -width * 0.5 + width * (index + 0.5) / post_count
        parts.append(_box((0.09, height, depth * 0.62),
                          (x, height * 0.5, -depth * 0.22), rng.choice(posts), "metal"))
    plate_y = height * 0.63
    parts.append(_box((width, height * 0.46, depth * 0.18),
                      (0.0, plate_y, 0.0), _tone(rng.choice(steel), 0.92), "metal"))
    for ridge_index, y_factor in enumerate((0.43, 0.62, 0.81)):
        z = depth * (0.18 if ridge_index != 1 else 0.30)
        parts.append(_box((width, height * 0.075, depth * 0.25),
                          (0.0, height * y_factor, z), _tone(rng.choice(steel), 1.08), "metal"))
    for index in range(post_count):
        x = -width * 0.5 + width * (index + 0.5) / post_count
        bolt = trimesh.creation.cylinder(radius=0.035, height=depth * 0.18, sections=8)
        parts.append(_paint(_translated(bolt, (x, plate_y, depth * 0.22)), rng.choice(bolts), "metal"))
    return _combine(parts)


def _plastic_blocks_mesh(recipe: dict, palette: dict, rng: random.Random) -> trimesh.Trimesh:
    width, height, depth = (float(recipe[key]) for key in ("width_m", "height_m", "depth_m"))
    count = int(recipe.get("block_count", 2))
    colours = palette["categories"]["plastic_blocks"]
    navy = [_hex(value) for value in colours["navy"]]
    white = [_hex(value) for value in colours["white"]]
    block_width = width / count
    parts: list[trimesh.Trimesh] = []
    for index in range(count):
        colour = rng.choice(navy if index % 2 == 0 else white)
        x = -width * 0.5 + block_width * (index + 0.5)
        parts.append(_box((block_width * 0.96, height * 0.72, depth * 0.76),
                          (x, height * 0.52, 0.0), colour, "plastic"))
        parts.append(_box((block_width * 0.98, height * 0.20, depth),
                          (x, height * 0.10, 0.0), _tone(colour, 0.82), "plastic"))
        knob = trimesh.creation.cylinder(radius=min(block_width, depth) * 0.13,
                                          height=height * 0.10, sections=8)
        knob.apply_transform(trimesh.transformations.rotation_matrix(math.pi * 0.5, [1, 0, 0]))
        parts.append(_paint(_translated(knob, (x, height * 0.93, 0.0)),
                            _tone(colour, 1.08), "plastic"))
    return _combine(parts)


_GENERATORS = {
    "tire_black": _tire_wall_mesh,
    "tire_navy_white": _tire_wall_mesh,
    "concrete_jersey": _concrete_jersey_mesh,
    "guardrail_armco": _guardrail_armco_mesh,
    "plastic_blocks": _plastic_blocks_mesh,
}


def _textured_card_mesh(recipe: dict, repo_root: Path) -> trimesh.Trimesh:
    """Build one zero-thickness, double-sided textured barrier face."""
    width = float(recipe["width_m"])
    height = float(recipe["height_m"])
    repeat_m = float(recipe.get("texture_repeat_m", 2.0))
    texture_path = repo_root / recipe["texture"]
    if not texture_path.is_file():
        raise ValueError(f"{recipe['id']}: missing texture {texture_path}")
    vertices = np.asarray([
        [-width * 0.5, 0.0, 0.0], [width * 0.5, 0.0, 0.0],
        [width * 0.5, height, 0.0], [-width * 0.5, height, 0.0],
    ], dtype=np.float64)
    faces = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    uv = np.asarray([[0.0, 0.0], [width / repeat_m, 0.0],
                     [width / repeat_m, 1.0], [0.0, 1.0]], dtype=np.float64)
    material = PBRMaterial(
        name=f"{recipe['id']}_material",
        baseColorTexture=Image.open(texture_path).convert("RGBA"),
        metallicFactor=float(recipe.get("metallic", 0.0)),
        roughnessFactor=float(recipe.get("roughness", 1.0)),
        doubleSided=True,
        alphaMode=recipe.get("alpha_mode", "OPAQUE"),
        alphaCutoff=float(recipe.get("alpha_cutoff", 0.5)),
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return mesh


def _collision_mesh(recipe: dict) -> trimesh.Trimesh:
    layers = int(recipe.get("depth_layers", 1))
    base_depth = float(recipe["depth_m"])
    depth = base_depth + max(0, layers - 1) * base_depth * 0.72
    mesh = trimesh.creation.box(extents=(float(recipe["width_m"]), float(recipe["height_m"]), depth))
    mesh.apply_translation((0.0, float(recipe["height_m"]) * 0.5,
                            -max(0, layers - 1) * base_depth * 0.36))
    return mesh


def validate_recipe_document(spec: dict, palette: dict, contract: dict | None = None) -> None:
    if spec.get("schema_version") != 3:
        raise ValueError("barrier recipe schema_version must be 3")
    if palette.get("schema_version") != 1:
        raise ValueError("barrier palette schema_version must be 1")
    if contract is not None:
        if contract.get("schema_version") != 1:
            raise ValueError("barrier construction manifest schema_version must be 1")
        coordinates = contract.get("coordinate_system", {})
        expected_coordinates = {
            "units": "metres", "up_axis": "+Y", "module_axis": "+X",
            "track_facing_axis": "+Z", "pivot": "ground_center", "base_module_length_m": 2.0,
        }
        if coordinates != expected_coordinates:
            raise ValueError("barrier construction coordinate contract is unsupported")
        if contract.get("visual", {}).get("geometry") != "single_textured_plane":
            raise ValueError("barrier construction visual geometry is unsupported")
        if contract.get("visual", {}).get("double_sided") is not True:
            raise ValueError("barrier construction requires double-sided materials")
        if contract.get("shading", {}).get("mode") != "textured_pbr_v1":
            raise ValueError("barrier construction shading contract is unsupported")
    assets = spec.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("barrier recipe requires a non-empty assets list")
    ids: set[str] = set()
    for recipe in assets:
        asset_id = recipe.get("id")
        if not isinstance(asset_id, str) or not asset_id.startswith(("barrier_", "run_")):
            raise ValueError(f"Invalid barrier id: {asset_id!r}")
        if asset_id in ids:
            raise ValueError(f"Duplicate barrier id: {asset_id}")
        ids.add(asset_id)
        family = recipe.get("family")
        if family not in KNOWN_FAMILIES or family not in palette.get("categories", {}):
            raise ValueError(f"Unknown or unpainted barrier family: {family!r}")
        for key in ("width_m", "height_m", "depth_m", "triangle_budget"):
            if float(recipe.get(key, 0)) <= 0:
                raise ValueError(f"{asset_id}: {key} must be positive")
        allowed_lengths = contract.get("reusable_lengths_m", [2.0]) if contract else [2.0]
        if float(recipe["width_m"]) not in [float(value) for value in allowed_lengths]:
            raise ValueError(f"{asset_id}: unsupported reusable length {recipe['width_m']}")
        if not 0.45 <= float(recipe["height_m"]) <= 1.50:
            raise ValueError(f"{asset_id}: implausible barrier height")
        for key in ("texture", "texture_repeat_m"):
            if not recipe.get(key):
                raise ValueError(f"{asset_id}: {key} is required")


def validate_mesh(mesh: trimesh.Trimesh, recipe: dict, *, collision: bool) -> dict:
    asset_id = recipe["id"]
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError(f"{asset_id}: empty mesh")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError(f"{asset_id}: non-finite vertices")
    if collision and (not mesh.is_watertight or not mesh.is_winding_consistent):
        raise ValueError(f"{asset_id}: collision mesh must be watertight with consistent winding")
    if not collision and not mesh.is_winding_consistent:
        raise ValueError(f"{asset_id}: visual mesh winding is inconsistent")
    if np.any(mesh.area_faces <= 1e-9):
        raise ValueError(f"{asset_id}: degenerate triangles")
    bounds = mesh.bounds
    half_width = float(recipe["width_m"]) * 0.5
    if collision:
        if abs(float(bounds[0][0]) + half_width) > 1e-4 or abs(float(bounds[1][0]) - half_width) > 1e-4:
            raise ValueError(f"{asset_id}: collision X bounds violate module contract: {bounds[:, 0]}")
    elif (float(bounds[0][0]) < -half_width - 1e-4 or
          float(bounds[1][0]) > half_width + 1e-4 or
          float(bounds[1][0] - bounds[0][0]) < float(recipe["width_m"]) * 0.90):
        raise ValueError(f"{asset_id}: visual must fill at least 90% of its X module: {bounds[:, 0]}")
    if abs(float(bounds[0][1])) > 1e-4:
        raise ValueError(f"{asset_id}: pivot must be on the ground plane")
    if not collision and len(mesh.faces) > int(recipe["triangle_budget"]):
        raise ValueError(f"{asset_id}: triangle budget exceeded")
    return {
        "vertices": int(len(mesh.vertices)), "triangles": int(len(mesh.faces)),
        "components": int(len(mesh.split(only_watertight=False))),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "bounds_min": [round(float(value), 6) for value in bounds[0]],
        "bounds_max": [round(float(value), 6) for value in bounds[1]],
    }


def _rotate_for_audit(vectors: np.ndarray, yaw: float, pitch: float) -> np.ndarray:
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    rotated = vectors @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]).T
    rotated = rotated @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]]).T
    return rotated


def _project(vertices: np.ndarray, yaw: float, pitch: float):
    rotated = _rotate_for_audit(vertices, yaw, pitch)
    return rotated[:, :2], rotated[:, 2]


def render_audit(mesh: trimesh.Trimesh, path: Path) -> None:
    if isinstance(mesh.visual, trimesh.visual.TextureVisuals):
        texture = mesh.visual.material.baseColorTexture.convert("RGBA")
        repeats = max(1, round(float(np.max(mesh.visual.uv[:, 0]))))
        band = Image.new("RGBA", (texture.width * repeats, texture.height), (0, 0, 0, 0))
        for index in range(repeats):
            band.alpha_composite(texture, (index * texture.width, 0))
        band.thumbnail((860, 390), Image.Resampling.LANCZOS)
        image = Image.new("RGBA", (900, 450), (30, 32, 33, 255))
        image.alpha_composite(band, ((900 - band.width) // 2, (450 - band.height) // 2))
        ImageDraw.Draw(image).text((16, 14), "front / repeated UV", fill=(238, 238, 238, 255))
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return
    image = Image.new("RGBA", (900, 900), (30, 32, 33, 255))
    views = ((0.0, 0.0, "front"), (math.pi / 4, 0.0, "45 deg"),
             (math.pi / 2, 0.0, "side"), (math.pi / 4, -0.28, "iso"))
    colours = mesh.visual.vertex_colors
    audit_light = np.asarray((-0.30, 0.78, 0.55), dtype=np.float64)
    audit_light /= np.linalg.norm(audit_light)
    for index, (yaw, pitch, label) in enumerate(views):
        tx, ty = (index % 2) * 450, (index // 2) * 450
        points, depths = _project(mesh.vertices, yaw, pitch)
        minimum, maximum = points.min(axis=0), points.max(axis=0)
        scale = 350.0 / max(float(maximum[0] - minimum[0]), float(maximum[1] - minimum[1]), 1e-6)
        center = (minimum + maximum) * 0.5
        draw = ImageDraw.Draw(image)
        # A soft contact patch anchors the object without baking a directional
        # cast shadow into the asset itself.
        draw.ellipse((tx + 70, ty + 360, tx + 380, ty + 408), fill=(10, 11, 12, 105))
        rotated_normals = _rotate_for_audit(mesh.face_normals, yaw, pitch)
        faces = []
        for face_index, face in enumerate(mesh.faces):
            polygon = [(tx + 225 + (points[i][0] - center[0]) * scale,
                        ty + 215 - (points[i][1] - center[1]) * scale) for i in face]
            normal_light = max(0.0, float(rotated_normals[face_index] @ audit_light))
            preview_factor = 0.76 + normal_light * 0.31
            base_colour = np.mean(colours[face, :3], axis=0)
            shaded_colour = np.clip(base_colour * preview_factor, 0, 255).round().astype(np.uint8)
            faces.append((float(np.mean(depths[face])), polygon,
                          tuple(int(value) for value in shaded_colour)))
        for _, polygon, colour in sorted(faces, key=lambda item: item[0]):
            draw.polygon(polygon, fill=(*colour, 255))
        draw.text((tx + 12, ty + 12), label, fill=(238, 238, 238, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def render_library_catalog(assets: list[dict], review_root: Path) -> Path:
    """Create a single human-gate sheet containing every generated barrier."""
    tile_size = 450
    columns = 4
    rows = math.ceil(len(assets) / columns)
    catalog = Image.new("RGBA", (columns * tile_size, rows * tile_size), (20, 22, 24, 255))
    draw = ImageDraw.Draw(catalog)
    for index, asset in enumerate(assets):
        source = Image.open(review_root / f"{asset['id']}.png").convert("RGBA")
        source.thumbnail((tile_size - 16, tile_size - 42), Image.Resampling.LANCZOS)
        x = (index % columns) * tile_size
        y = (index // columns) * tile_size
        catalog.alpha_composite(source, (x + (tile_size - source.width) // 2, y + 30))
        draw.text((x + 10, y + 8), asset["id"], fill=(240, 240, 240, 255))
    path = review_root / "barrier_library_catalog.png"
    catalog.save(path)
    return path


def build_review_strip(mesh: trimesh.Trimesh, width_m: float, count: int = 5) -> trimesh.Trimesh:
    parts = []
    for index in range(count):
        copy = mesh.copy()
        copy.apply_translation((index * width_m, 0.0, 0.0))
        parts.append(copy)
    strip = _combine(parts)
    strip.apply_translation((-width_m * (count - 1) * 0.5, 0.0, 0.0))
    return strip


def _export_glb(mesh: trimesh.Trimesh, path: Path, node_name: str) -> bytes:
    scene = trimesh.Scene()
    scene.add_geometry(mesh, node_name=node_name, geom_name=node_name)
    payload = scene.export(file_type="glb")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def build_asset(recipe: dict, palette: dict, output_root: Path,
                review_root: Path, repo_root: Path) -> dict:
    rng = random.Random(int(recipe["seed"]))
    visual = _textured_card_mesh(recipe, repo_root)
    collision = _collision_mesh(recipe)
    visual_info = validate_mesh(visual, recipe, collision=False)
    collision_info = validate_mesh(collision, recipe, collision=True)
    strip = build_review_strip(visual, float(recipe["width_m"]))
    visual_path = output_root / f"{recipe['id']}.glb"
    collision_path = output_root / f"{recipe['id']}_collision.glb"
    strip_path = output_root / f"{recipe['id']}_strip5.glb"
    visual_bytes = _export_glb(visual, visual_path, f"{recipe['id']}_visual")
    collision_bytes = _export_glb(collision, collision_path, f"{recipe['id']}_collision")
    strip_bytes = _export_glb(strip, strip_path, f"{recipe['id']}_strip5")
    preview_path = review_root / f"{recipe['id']}.png"
    strip_preview_path = review_root / f"{recipe['id']}_strip5.png"
    render_audit(visual, preview_path)
    render_audit(strip, strip_preview_path)

    def published(path: Path) -> str:
        return (ASSET_DIR / path.relative_to(output_root)).as_posix()

    def published_review(path: Path) -> str:
        return (REVIEW_DIR / path.relative_to(review_root)).as_posix()

    return {
        "id": recipe["id"], "kind": "barrier", "family": recipe["family"],
        "visual_glb": published(visual_path),
        "collision_glb": published(collision_path),
        "strip_glb": published(strip_path),
        "preview": published_review(preview_path),
        "strip_preview": published_review(strip_preview_path),
        "visual_sha256": _sha256_bytes(visual_bytes),
        "collision_sha256": _sha256_bytes(collision_bytes),
        "strip_sha256": _sha256_bytes(strip_bytes),
        "recipe_sha256": _canonical_hash(recipe),
        "coordinate_contract": {"units": "metres", "up_axis": "+Y", "module_axis": "+X",
                                "track_facing_axis": "+Z", "pivot": "ground_center"},
        "shading": {"mode": "textured_pbr_v1", "double_sided": True,
                    "alpha_mode": recipe.get("alpha_mode", "OPAQUE"),
                    "texture": recipe["texture"], "cast_shadows_baked": False},
        "depth_layers": int(recipe.get("depth_layers", 1)),
        "visual": visual_info, "collision": collision_info, "lod": False,
    }


def build_library(spec: dict, palette: dict, contract: dict, output_root: Path,
                  review_root: Path, repo_root: Path) -> list[dict]:
    validate_recipe_document(spec, palette, contract)
    return [build_asset(recipe, palette, output_root, review_root, repo_root)
            for recipe in spec["assets"]]


def _publish_directory(staged: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    staged_names = {path.name for path in staged.iterdir()}
    for old in destination.iterdir():
        if old.name not in staged_names and old.is_file() and old.suffix.lower() in {".glb", ".json", ".png"}:
            old.unlink()
    for source in staged.iterdir():
        target = destination / source.name
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            os.replace(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate the Formula-90 barrier GLB library.")
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    recipe_path = args.recipes.resolve()
    spec = json.loads(recipe_path.read_text(encoding="utf-8"))
    palette_path = repo / spec["palette"]
    contract_path = repo / spec["construction_manifest"]
    palette = json.loads(palette_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    destination = repo / ASSET_DIR
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="barrier-library-", dir=destination.parent) as temporary:
        staged = Path(temporary)
        assets = build_library(spec, palette, contract, staged, staged / "review", repo)
        catalog_path = render_library_catalog(assets, staged / "review")
        manifest = {
            "schema_version": SCHEMA_VERSION, "generator": GENERATOR_ID,
            "shading_contract": "textured_pbr_v1_double_sided",
            "recipe_document_sha256": _sha256_file(recipe_path),
            "palette_sha256": _sha256_file(palette_path),
            "construction_manifest": spec["construction_manifest"],
            "construction_manifest_sha256": _sha256_file(contract_path),
            "human_gate_catalog": (REVIEW_DIR / catalog_path.name).as_posix(),
            "human_gate_catalog_sha256": _sha256_file(catalog_path),
            "assets": assets,
        }
        (staged / "barrier_manifest_v3.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                           encoding="utf-8")
        _publish_directory(staged, destination)
    print(json.dumps({"assets": len(assets), "manifest": str(destination / 'barrier_manifest_v3.json')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
