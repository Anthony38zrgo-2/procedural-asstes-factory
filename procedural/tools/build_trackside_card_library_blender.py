"""Build reusable double-sided GLB trackside cards from approved PNG sprites."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy


def args_after_dash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for block in list(datablocks):
            datablocks.remove(block)


def make_material(asset_id: str, png: Path):
    material = bpy.data.materials.new(f"{asset_id}_material")
    material.use_nodes = True
    material.surface_render_method = "DITHERED"
    material.use_transparency_overlap = False
    material.use_backface_culling = False
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.88
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(png), check_existing=False)
    texture.interpolation = "Linear"
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def build_card(asset_id: str, png: Path, width: float, height: float, category: str, target: Path):
    clear_scene()
    vertices = [
        (-width * 0.5, 0.0, 0.0),
        (width * 0.5, 0.0, 0.0),
        (width * 0.5, 0.0, height),
        (-width * 0.5, 0.0, height),
    ]
    mesh = bpy.data.meshes.new(f"{asset_id}_mesh")
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(mesh.uv_layers[0].data, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop.uv = uv
    obj = bpy.data.objects.new(asset_id, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(make_material(asset_id, png))
    obj["formula90s_trackside_card"] = True
    obj["asset_id"] = asset_id
    obj["category"] = category
    obj["double_sided"] = True
    obj["collision"] = False
    obj["width_m"] = width
    obj["height_m"] = height
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(target), export_format="GLB", use_selection=True,
        export_yup=True, export_materials="EXPORT",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    ns = parser.parse_args(args_after_dash())
    repo = ns.repo.resolve()
    source = repo / "track-studio/output/trackside_card_library_v1/source_png"
    destination = repo / "game/resources/environment/assets/trackside_cards"
    records = []
    for png in sorted(source.glob("*.png")):
        asset_id = png.stem
        if asset_id.startswith("person_"):
            category, width, height, folder = "spectator", 1.2, 1.8, "people"
        elif asset_id.startswith("sign_"):
            category, width, height, folder = "sign", 3.6, 1.8, "signs"
        else:
            continue
        glb = destination / folder / f"{asset_id}.glb"
        build_card(asset_id, png, width, height, category, glb)
        records.append({
            "id": asset_id,
            "kind": "trackside_card",
            "category": category,
            "glb": glb.relative_to(repo).as_posix(),
            "glb_sha256": sha256(glb),
            "source_png": png.relative_to(repo).as_posix(),
            "source_png_sha256": sha256(png),
            "width_m": width,
            "height_m": height,
            "double_sided": True,
            "collision": False,
            "origin": "bottom_center",
        })
    if len(records) != 15:
        raise RuntimeError(f"Expected 15 trackside cards, generated {len(records)}")
    manifest = {
        "schema_version": 1,
        "generator": "formula90_trackside_cards_v1",
        "coordinate_contract": "X width, Y thickness/normal, Z height; origin bottom-center",
        "assets": records,
    }
    manifest_path = destination / "trackside_card_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
