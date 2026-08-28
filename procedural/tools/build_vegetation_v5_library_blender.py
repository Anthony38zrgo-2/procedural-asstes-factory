from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_conifer_v5_library_blender import (
    add_cards,
    add_tube,
    clear_scene,
    join_objects,
    look_at,
    make_foliage_material,
    make_wood_material,
    mesh_statistics,
    patch_glb_alpha_mask,
    sha256,
)


def args_after_double_dash() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def verify_release(repo: Path, release: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    atlases = {item["id"]: item for item in release["atlases"]}
    wood = {item["id"]: item for item in release["wood_materials"]}
    for item in list(atlases.values()) + list(wood.values()):
        path = repo / item["path"]
        if sha256(path) != item["sha256"]:
            raise ValueError(f"texture release drift: {path}")
    return atlases, wood


def atlas_manifest(repo: Path, atlas: dict) -> dict:
    path = repo / "procedural/generated/texture_pipeline/atlases" / f"{atlas['id']}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["atlas_sha256"] != atlas["sha256"]:
        raise ValueError(f"atlas manifest drift: {atlas['id']}")
    return manifest


def trunk_point(recipe: dict, z: float) -> Vector:
    height = float(recipe["height_m"])
    width = float(recipe["width_m"])
    lean = float(recipe.get("lean", 0.0))
    t = z / max(height, 1e-6)
    return Vector((lean * width * 0.46 * t * t, math.sin(t * math.pi * 1.35) * width * 0.008, z))


def tree_structure(recipe: dict, lod: dict) -> tuple[bpy.types.Object, list[dict]]:
    rng = random.Random(int(recipe["seed"]))
    height = float(recipe["height_m"])
    width = float(recipe["width_m"])
    depth = float(recipe["depth_m"])
    trunk_radius = height * float(recipe.get("trunk_radius_ratio", 0.035))
    trunk_segments = 10 if int(lod["trunk_sides"]) >= 10 else 7
    trunk_points = [trunk_point(recipe, height * index / trunk_segments) for index in range(trunk_segments + 1)]
    trunk_radii = [max(trunk_radius * 0.12, trunk_radius * (1.0 - 0.88 * index / trunk_segments)) for index in range(trunk_segments + 1)]
    wood_objects = [add_tube("trunk", trunk_points, trunk_radii, int(lod["trunk_sides"]), bpy.data.materials["wood_broadleaf_seamless"], 1.4, 2.0)]
    anchors: list[tuple[Vector, Vector]] = [(trunk_points[-1] - Vector((0, 0, height * 0.035)), Vector((1, 0, 0)))]
    primary_count = int(recipe.get("primary_count", 6))
    branch_start = float(recipe.get("branch_start_ratio", 0.42))
    family = recipe["family"]
    for index in range(primary_count):
        phase = index * 2.399963229728653 + rng.uniform(-0.20, 0.20)
        attach_ratio = branch_start + (0.75 - branch_start) * ((index * 0.61803398875) % 1.0)
        if family == "umbrella":
            attach_ratio = 0.52 + 0.22 * ((index * 0.61803398875) % 1.0)
        attach = trunk_point(recipe, height * attach_ratio)
        asymmetry = float(recipe.get("asymmetry", 0.0))
        reach = width * rng.uniform(0.29, 0.45) * (1.0 + asymmetry * math.cos(phase))
        if family == "columnar":
            reach *= 0.72
        reach *= float(recipe.get("reach_scale", 1.0))
        radial = Vector((math.cos(phase), math.sin(phase) * depth / max(width, 1e-6), 0.0)).normalized()
        side = Vector((-radial.y, radial.x, 0.0))
        rise = height * rng.uniform(0.10, 0.22)
        if family in ("umbrella", "mature_spreading"):
            rise *= 0.74
        end = attach + radial * reach + Vector((float(recipe.get("lean", 0.0)) * width * 0.22, 0, rise))
        mid = attach.lerp(end, 0.52) + side * rng.uniform(-0.05, 0.05) * width + Vector((0, 0, height * rng.uniform(0.01, 0.035)))
        radius = trunk_radius * rng.uniform(0.31, 0.46)
        wood_objects.append(add_tube(f"branch_{index:02d}", [attach, mid, end], [radius, radius * 0.58, max(0.012, radius * 0.18)], int(lod["branch_sides"]), bpy.data.materials["wood_broadleaf_seamless"], 0.9))
        for anchor_step in range(1, 10):
            amount = anchor_step / 9.0
            point = attach.lerp(mid, amount / 0.52) if amount <= 0.52 else mid.lerp(end, (amount - 0.52) / 0.48)
            anchors.append((point, radial))
        for fork_index, along in enumerate((0.48, 0.72)):
            fork_start = mid.lerp(end, along)
            sign = -1.0 if (index + fork_index) % 2 else 1.0
            fork_dir = (radial * 0.35 + side * sign).normalized()
            fork_end = fork_start + fork_dir * reach * rng.uniform(0.22, 0.34) + Vector((0, 0, height * rng.uniform(0.035, 0.085)))
            if lod["secondary_branches"]:
                wood_objects.append(add_tube(f"twig_{index:02d}_{fork_index}", [fork_start, fork_end], [radius * 0.34, max(0.007, radius * 0.08)], max(4, int(lod["branch_sides"]) - 1), bpy.data.materials["wood_broadleaf_seamless"], 0.62))
            anchors.extend((fork_start.lerp(fork_end, amount), fork_dir) for amount in (0.34, 0.67, 1.0))
    for root_index in range(5):
        phase = math.tau * root_index / 5 + rng.uniform(-0.18, 0.18)
        start = Vector((0, 0, trunk_radius * 0.35))
        end = Vector((math.cos(phase) * trunk_radius * 2.2, math.sin(phase) * trunk_radius * 2.2, trunk_radius * 0.08))
        wood_objects.append(add_tube(f"root_{root_index}", [start, end], [trunk_radius * 0.58, trunk_radius * 0.05], 5, bpy.data.materials["wood_broadleaf_seamless"], 0.55))
    wood = join_objects(wood_objects, "wood_geometry")
    cluster_count = max(18, round(int(recipe["cluster_count"]) * float(lod["cluster_fraction"]) * 6.0))
    cards = []
    cluster_width = max(0.62, width * (0.12 if family != "columnar" else 0.15))
    cluster_height = max(0.56, height * 0.07)
    spread = float(recipe.get("leaf_cluster_spread_m", cluster_width * 0.25)) * 0.46
    for cluster_index in range(cluster_count):
        anchor, direction = anchors[cluster_index % len(anchors)]
        center = anchor + Vector((rng.uniform(-spread, spread), rng.uniform(-spread, spread), rng.uniform(-spread * 0.55, spread * 0.75)))
        center.z = min(height - cluster_height * 0.44, max(height * branch_start, center.z))
        cards.append({"center": tuple(center), "direction": tuple(direction), "width": cluster_width * rng.uniform(0.84, 1.14), "height": cluster_height * rng.uniform(0.84, 1.14)})
    return wood, cards


def bush_structure(recipe: dict, lod: dict) -> tuple[bpy.types.Object, list[dict]]:
    rng = random.Random(int(recipe["seed"]))
    height, width, depth = (float(recipe[key]) for key in ("height_m", "width_m", "depth_m"))
    base_radius = max(0.022, height * 0.026)
    stem_count = int(recipe.get("stem_count", 6))
    anchors: list[tuple[Vector, Vector]] = []
    wood_objects = []
    for index in range(stem_count):
        phase = math.tau * index / stem_count + rng.uniform(-0.30, 0.30)
        radial = Vector((math.cos(phase), math.sin(phase) * depth / max(width, 1e-6), 0.0)).normalized()
        reach = width * rng.uniform(0.22, 0.42) * (1.0 + float(recipe.get("asymmetry", 0.0)) * math.cos(phase))
        crawl = float(recipe.get("crawl", 0.0))
        tip_height = height * rng.uniform(0.68 - crawl * 0.22, 0.98 - crawl * 0.20)
        start = Vector((radial.x * width * 0.018, radial.y * depth * 0.018, base_radius))
        mid = Vector((radial.x * reach * 0.48, radial.y * reach * 0.48, tip_height * 0.47 + height * 0.08))
        end = Vector((radial.x * reach, radial.y * reach, tip_height))
        radius = base_radius * rng.uniform(0.82, 1.18)
        wood_objects.append(add_tube(f"stem_{index:02d}", [start, mid, end], [radius, radius * 0.56, max(0.006, radius * 0.16)], int(lod["branch_sides"]), bpy.data.materials["wood_broadleaf_seamless"], 0.42))
        for anchor_step in range(1, 8):
            amount = anchor_step / 7.0
            point = start.lerp(mid, amount / 0.5) if amount <= 0.5 else mid.lerp(end, (amount - 0.5) / 0.5)
            anchors.append((point, radial))
        side = Vector((-radial.y, radial.x, 0.0))
        fork_start = mid.lerp(end, 0.45)
        fork_dir = (radial * 0.25 + side * (-1 if index % 2 else 1)).normalized()
        fork_end = fork_start + fork_dir * width * rng.uniform(0.11, 0.19) + Vector((0, 0, height * rng.uniform(0.08, 0.18)))
        fork_end.z = min(height * 0.90, fork_end.z)
        if lod["secondary_branches"]:
            wood_objects.append(add_tube(f"fork_{index:02d}", [fork_start, fork_end], [radius * 0.40, max(0.005, radius * 0.09)], max(4, int(lod["branch_sides"]) - 1), bpy.data.materials["wood_broadleaf_seamless"], 0.35))
        anchors.extend((fork_start.lerp(fork_end, amount), fork_dir) for amount in (0.4, 0.7, 1.0))
    wood = join_objects(wood_objects, "wood_geometry")
    cluster_count = max(14, round(int(recipe["cluster_count"]) * float(lod["cluster_fraction"]) * 3.20))
    cards = []
    cluster_width = max(0.38, width * 0.19)
    cluster_height = max(0.28, height * 0.28)
    spread = float(recipe.get("leaf_cluster_spread_m", 0.2)) * 0.48
    for cluster_index in range(cluster_count):
        anchor, direction = anchors[cluster_index % len(anchors)]
        center = anchor + Vector((rng.uniform(-spread, spread), rng.uniform(-spread, spread), rng.uniform(-spread * 0.4, spread)))
        center.z = max(cluster_height * 0.44, min(height - cluster_height * 0.42, center.z))
        cards.append({"center": tuple(center), "direction": tuple(direction), "width": cluster_width * rng.uniform(0.82, 1.15), "height": cluster_height * rng.uniform(0.82, 1.15)})
    return wood, cards


def anchor_pair(wood: bpy.types.Object, foliage: bpy.types.Object) -> float:
    minimum = min(
        min((obj.matrix_world @ vertex.co).z for vertex in obj.data.vertices)
        for obj in (wood, foliage)
    )
    offset = -minimum
    wood.location.z += offset
    foliage.location.z += offset
    bpy.context.view_layer.update()
    return offset


def setup_render(recipe: dict, path: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 620
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(path)
    scene.world.color = (0.026, 0.032, 0.038)
    scene.view_settings.look = "AgX - Medium High Contrast"
    height, width = float(recipe["height_m"]), float(recipe["width_m"])
    bpy.ops.mesh.primitive_plane_add(size=max(18.0, width * 2.4), location=(0, 0, -0.025))
    ground = bpy.context.object
    ground_material = bpy.data.materials.new("audit_ground_material")
    ground_material.diffuse_color = (0.07, 0.078, 0.08, 1.0)
    ground.data.materials.append(ground_material)
    extent = max(height * 1.13, width * 1.18)
    bpy.ops.object.camera_add(location=(height * 0.70, -height * 1.48, height * 0.62))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = extent
    look_at(camera, Vector((0, 0, height * 0.47)))
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(height * 0.55, -height * 0.52, height * 1.02))
    key = bpy.context.object
    key.data.energy = 930 if recipe["kind"] == "tree" else 85
    key.data.size = max(3.0, height * 0.55)
    look_at(key, Vector((0, 0, height * 0.46)))
    bpy.ops.object.light_add(type="AREA", location=(-height * 0.48, height * 0.20, height * 0.62))
    fill = bpy.context.object
    fill.data.energy = 260 if recipe["kind"] == "tree" else 22
    fill.data.size = max(2.5, height * 0.42)
    look_at(fill, Vector((0, 0, height * 0.46)))
    bpy.ops.object.light_add(type="SUN", location=(0, 0, height))
    bpy.context.object.data.energy = 1.0 if recipe["kind"] == "tree" else 0.55
    bpy.context.object.rotation_euler = (math.radians(28), math.radians(-20), math.radians(140))


def export_pair(objects: list[bpy.types.Object], path: Path, cutoff: float) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_yup=True, export_materials="EXPORT")
    patch_glb_alpha_mask(path, cutoff)


def production_recipes(source: dict, spec: dict) -> list[dict]:
    by_id = {item["id"]: item for item in source["assets"]}
    tree_catalog = spec["tree_catalog"]
    output = [dict(by_id[asset_id], source_asset_id=asset_id, derivation="approved_original") for asset_id in tree_catalog["approved_sources"]]
    for derived in tree_catalog["derived"]:
        recipe = dict(by_id[derived["source"]])
        recipe.update({
            "id": derived["id"],
            "seed": int(recipe["seed"]) + int(derived["seed_offset"]),
            "height_m": float(recipe["height_m"]) * float(derived["height_scale"]),
            "width_m": float(recipe["width_m"]) * float(derived["width_scale"]),
            "depth_m": float(recipe["depth_m"]) * float(derived["depth_scale"]),
            "primary_count": int(recipe["primary_count"]) + int(derived["primary_delta"]),
            "lean": float(recipe.get("lean", 0.0)) + float(derived["lean_delta"]),
            "asymmetry": min(0.42, float(recipe.get("asymmetry", 0.0)) + float(derived["asymmetry_delta"])),
            "cluster_count": round(int(recipe["cluster_count"]) * max(0.92, float(derived["width_scale"]) * float(derived["height_scale"]))),
            "reach_scale": float(derived.get("reach_scale", 1.0)),
            "source_asset_id": derived["source"],
            "derivation": derived["derivation"],
        })
        output.append(recipe)
    output.extend(dict(item, source_asset_id=item["id"], derivation="approved_original") for item in source["assets"] if item["kind"] == "bush")
    return sorted(output, key=lambda item: item["id"])


def build_geometry_variants(repo: Path, output: Path, recipe: dict, lod_name: str, lod: dict, spec: dict, atlases: dict, wood_items: dict, representative_ids: set[str], render_audits: bool) -> list[dict]:
    clear_scene()
    wood_id = spec["wood"][recipe["kind"]]
    wood_material = make_wood_material(repo / wood_items[wood_id]["path"])
    wood_material.name = "wood_broadleaf_seamless"
    green_variant = spec["variants"]["green"]
    green_atlas_id = green_variant[f"{recipe['kind']}_atlas"]
    green_manifest = atlas_manifest(repo, atlases[green_atlas_id])
    foliage_material = make_foliage_material(repo / green_manifest["atlas"], float(green_manifest["alpha_cutoff"]))
    foliage_material.name = "foliage_broadleaf_alpha_mask"
    if recipe["kind"] == "tree":
        wood, cards = tree_structure(recipe, lod)
    else:
        wood, cards = bush_structure(recipe, lod)
    records = []
    offset = None
    render_ready = False
    for variant_name, variant in spec["variants"].items():
        atlas_id = variant[f"{recipe['kind']}_atlas"]
        manifest = atlas_manifest(repo, atlases[atlas_id])
        texture_node = next(node for node in foliage_material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage")
        texture_node.image = bpy.data.images.load(str(repo / manifest["atlas"]), check_existing=True)
        foliage = add_cards("foliage_cards", cards, manifest["regions"], foliage_material)
        if offset is None:
            offset = anchor_pair(wood, foliage)
        else:
            foliage.location.z = offset
            bpy.context.view_layer.update()
        objects = [wood, foliage]
        stats = mesh_statistics(objects)
        budget_key = "triangle_budget_tree" if recipe["kind"] == "tree" else "triangle_budget_bush"
        if stats["triangles"] > int(lod[budget_key]):
            raise ValueError(f"{recipe['id']} {lod_name} exceeds budget: {stats['triangles']}")
        category = "trees" if recipe["kind"] == "tree" else "bushes"
        asset_name = recipe["id"] + variant["suffix"] + f"_{lod_name}"
        glb_path = output / "assets" / category / f"{asset_name}.glb"
        glb_path.parent.mkdir(parents=True, exist_ok=True)
        export_pair(objects, glb_path, float(manifest["alpha_cutoff"]))
        should_render = render_audits and (variant_name == "green" or (recipe["id"] in representative_ids and lod_name == "lod0"))
        audit_path = None
        if should_render:
            audit_path = output / "review" / f"{asset_name}.png"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            if not render_ready:
                setup_render(recipe, audit_path)
                render_ready = True
            bpy.context.scene.render.filepath = str(audit_path)
            bpy.ops.render.render(write_still=True)
        records.append({
            "id": recipe["id"], "family": recipe["family"], "kind": recipe["kind"], "variant": variant_name, "lod": lod_name,
            "source_asset_id": recipe.get("source_asset_id", recipe["id"]), "derivation": recipe.get("derivation", "approved_original"),
            "seed": int(recipe["seed"]), "glb": glb_path.relative_to(repo).as_posix(), "glb_sha256": sha256(glb_path),
            "audit": audit_path.relative_to(repo).as_posix() if audit_path else None,
            "audit_sha256": sha256(audit_path) if audit_path else None,
            "atlas": atlas_id, "wood": wood_id, "alpha_mode": "MASK", "draw_meshes": 2,
            "triangle_budget": int(lod[budget_key]), **stats,
        })
        bpy.data.objects.remove(foliage, do_unlink=True)
    return records


def main() -> int:
    args = args_after_double_dash()
    repo = Path.cwd().resolve()
    if "--repo" in args:
        repo = Path(args[args.index("--repo") + 1]).resolve()
    spec_path = repo / "procedural/recipes/vegetation_v5_library.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    source_path = repo / spec["source_recipes"]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    release_path = repo / spec["texture_release"]
    release = json.loads(release_path.read_text(encoding="utf-8"))
    atlases, wood = verify_release(repo, release)
    output = repo / "procedural/generated/vegetation_v5"
    if "--output-root" in args:
        output = Path(args[args.index("--output-root") + 1]).resolve()
    if (repo / "procedural/generated").resolve() not in output.resolve().parents:
        raise ValueError("output root must remain under procedural/generated")
    representative_ids = set(spec["audit"]["seasonal_representatives"])
    render_audits = "--skip-audits" not in args
    recipes = production_recipes(source, spec)
    records = []
    for recipe in recipes:
        for lod_name in ("lod0", "lod1"):
            records.extend(build_geometry_variants(repo, output, recipe, lod_name, spec["lods"][lod_name], spec, atlases, wood, representative_ids, render_audits))
    report = {
        "schema_version": 1, "generator": spec["generator"], "blender_version": bpy.app.version_string,
        "recipe": spec_path.relative_to(repo).as_posix(), "recipe_sha256": sha256(spec_path),
        "source_recipes": source_path.relative_to(repo).as_posix(), "source_recipes_sha256": sha256(source_path),
        "texture_release": release_path.relative_to(repo).as_posix(), "texture_release_sha256": sha256(release_path),
        "base_assets": len(recipes), "variant_assets": len(records),
        "tree_catalog": spec["tree_catalog"], "records": records,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"base_assets": report["base_assets"], "variant_assets": report["variant_assets"], "manifest": str(output / 'manifest.json')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
