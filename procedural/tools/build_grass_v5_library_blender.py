from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_conifer_v5_library_blender import clear_scene, look_at, make_foliage_material, mesh_statistics, patch_glb_alpha_mask, sha256


def args_after_double_dash() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def add_grass_cards(spec: dict, regions: list[dict], material: bpy.types.Material) -> bpy.types.Object:
    rng = random.Random(int(spec["seed"]))
    vertices, faces, face_uvs = [], [], []
    count = int(spec["cards"])
    width, depth, height = (float(spec[key]) for key in ("width_m", "depth_m", "height_m"))
    for index in range(count):
        angle = index * 2.399963229728653 + rng.uniform(-0.38, 0.38)
        radius = math.sqrt((index + 0.5) / count) * rng.uniform(0.20, 0.48)
        center = Vector((math.cos(angle) * width * radius, math.sin(angle) * depth * radius, 0.0))
        yaw = angle + math.pi * 0.5 + rng.uniform(-0.55, 0.55)
        horizontal = Vector((math.cos(yaw), math.sin(yaw), 0.0))
        card_h = height * rng.uniform(0.68, 1.05)
        card_w = min(width, depth) * rng.uniform(0.20, 0.32)
        lean = Vector((rng.uniform(-0.12, 0.12), rng.uniform(-0.12, 0.12), 0.0)) * card_h
        bottom = center
        middle = center + Vector((0, 0, card_h * 0.52)) + lean * 0.30
        top = center + Vector((0, 0, card_h)) + lean
        half_bottom = card_w * 0.5
        half_top = card_w * rng.uniform(0.38, 0.48)
        base = len(vertices)
        vertices.extend((tuple(bottom - horizontal * half_bottom), tuple(bottom + horizontal * half_bottom), tuple(middle + horizontal * half_bottom), tuple(middle - horizontal * half_bottom), tuple(top + horizontal * half_top), tuple(top - horizontal * half_top)))
        faces.extend(((base, base + 1, base + 2, base + 3), (base + 3, base + 2, base + 4, base + 5)))
        u0, v0, u1, v1 = regions[index % len(regions)]["uv_bottom_left"]
        vm = v0 + (v1 - v0) * 0.52
        face_uvs.extend(([(u0, v0), (u1, v0), (u1, vm), (u0, vm)], [(u0, vm), (u1, vm), (u1, v1), (u0, v1)]))
    mesh = bpy.data.meshes.new("grass_cards_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon, coords in zip(mesh.polygons, face_uvs):
        for loop_index, coord in zip(polygon.loop_indices, coords):
            uv.data[loop_index].uv = coord
    obj = bpy.data.objects.new("grass_cards", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def setup_render(spec: dict, path: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 520
    scene.render.resolution_y = 420
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(path)
    scene.world.color = (0.025, 0.030, 0.034)
    scene.view_settings.look = "AgX - Medium High Contrast"
    extent = max(float(spec["width_m"]), float(spec["depth_m"]), float(spec["height_m"]) * 2.1)
    bpy.ops.mesh.primitive_plane_add(size=5.0, location=(0, 0, -0.012))
    ground = bpy.context.object
    mat = bpy.data.materials.new("audit_ground")
    mat.diffuse_color = (0.055, 0.062, 0.058, 1.0)
    ground.data.materials.append(mat)
    bpy.ops.object.camera_add(location=(extent * 0.90, -extent * 1.25, extent * 0.72))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = extent * 1.45
    look_at(camera, Vector((0, 0, float(spec["height_m"]) * 0.35)))
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(-1.6, -2.0, 3.2))
    bpy.context.object.data.energy = 300
    bpy.context.object.data.size = 3.0
    look_at(bpy.context.object, Vector((0, 0, 0.25)))
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 2))
    bpy.context.object.data.energy = 1.15
    bpy.context.object.rotation_euler = (math.radians(30), math.radians(-22), math.radians(135))


def main() -> None:
    args = args_after_double_dash()
    repo = Path(args[args.index("--repo") + 1]).resolve() if "--repo" in args else Path.cwd().resolve()
    skip_audits = "--skip-audits" in args
    output = Path(args[args.index("--output-root") + 1]).resolve() if "--output-root" in args else repo / "procedural/generated/vegetation_v5"
    recipe_path = repo / "procedural/recipes/grass_v5_library.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    records = []
    for variant, variant_spec in recipe["variants"].items():
        atlas_manifest_path = repo / f"procedural/generated/vegetation_v5/textures/grass/grass_{variant}_512.json"
        atlas_manifest = json.loads(atlas_manifest_path.read_text(encoding="utf-8"))
        atlas_path = repo / atlas_manifest["atlas"]
        if sha256(atlas_path) != atlas_manifest["atlas_sha256"]:
            raise ValueError(f"grass atlas drift: {atlas_path}")
        for spec in recipe["assets"]:
            clear_scene()
            material = make_foliage_material(atlas_path, float(recipe["alpha_cutoff"]))
            material.name = "foliage_grass_alpha_mask"
            grass = add_grass_cards(spec, atlas_manifest["regions"], material)
            asset_name = spec["id"] + variant_spec["suffix"]
            glb_path = output / "assets/grass" / f"{asset_name}.glb"
            glb_path.parent.mkdir(parents=True, exist_ok=True)
            grass.select_set(True)
            bpy.context.view_layer.objects.active = grass
            bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True, export_yup=True, export_materials="EXPORT")
            patch_glb_alpha_mask(glb_path, float(recipe["alpha_cutoff"]))
            audit_path = None
            if not skip_audits:
                audit_path = output / "review/grass" / f"{asset_name}.png"
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                setup_render(spec, audit_path)
                bpy.ops.render.render(write_still=True)
            stats = mesh_statistics([grass])
            records.append({
                "id": spec["id"], "kind": "grass", "family": spec["profile"], "variant": variant,
                "glb": glb_path.relative_to(repo).as_posix(), "glb_sha256": sha256(glb_path),
                "audit": audit_path.relative_to(repo).as_posix() if audit_path else None,
                "audit_sha256": sha256(audit_path) if audit_path else None,
                "atlas": atlas_manifest["id"], "atlas_sha256": atlas_manifest["atlas_sha256"],
                "triangles": stats["triangles"], "vertices": stats["vertices"],
                "dimensions": stats["dimensions"], "bounds_min": stats["bounds_min"], "bounds_max": stats["bounds_max"],
                "triangle_budget": recipe["triangle_budget"], "seed": spec["seed"],
            })
    manifest = {
        "schema_version": 1, "generator": recipe["generator"], "recipe": recipe_path.relative_to(repo).as_posix(),
        "recipe_sha256": sha256(recipe_path), "base_assets": len(recipe["assets"]), "variants": len(recipe["variants"]),
        "glb_assets": len(records), "records": records,
    }
    (output / "grass_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    vegetation_manifest_path = output / "manifest.json"
    vegetation_manifest = json.loads(vegetation_manifest_path.read_text(encoding="utf-8")) if vegetation_manifest_path.is_file() else {"variant_assets": 0}
    catalog = {
        "schema_version": 1,
        "families": {
            "trees_and_bushes": {"manifest": vegetation_manifest_path.relative_to(repo).as_posix(), "glb_assets": vegetation_manifest["variant_assets"]},
            "grass": {"manifest": (output / "grass_manifest.json").relative_to(repo).as_posix(), "glb_assets": len(records)},
        },
        "total_glb_assets": vegetation_manifest["variant_assets"] + len(records),
        "colors": list(recipe["variants"]),
    }
    (output / "catalog_manifest.json").write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"base_assets": len(recipe["assets"]), "glb_assets": len(records), "manifest": str(output / "grass_manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
