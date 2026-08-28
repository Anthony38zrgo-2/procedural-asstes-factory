"""Build reusable double-sided GLB braking-distance cards for La Chutana."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy


WIDTH_M = 2.4
HEIGHT_M = 0.8
NUMBERS = ("200", "150", "100", "050")


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


def build_card(asset_id: str, png: Path, target: Path):
    clear_scene()
    mesh = bpy.data.meshes.new(f"{asset_id}_mesh")
    mesh.from_pydata(
        [(-WIDTH_M / 2, 0, 0), (WIDTH_M / 2, 0, 0),
         (WIDTH_M / 2, 0, HEIGHT_M), (-WIDTH_M / 2, 0, HEIGHT_M),
         (-WIDTH_M / 2, 0.01, 0), (WIDTH_M / 2, 0.01, 0),
         (WIDTH_M / 2, 0.01, HEIGHT_M), (-WIDTH_M / 2, 0.01, HEIGHT_M)],
        [], [(0, 1, 2, 3), (4, 7, 6, 5)],
    )
    mesh.uv_layers.new(name="UVMap")
    uvs = (
        (0, 0), (1, 0), (1, 1), (0, 1),
        (1, 0), (1, 1), (0, 1), (0, 0),
    )
    for loop, uv in zip(mesh.uv_layers[0].data, uvs):
        loop.uv = uv

    material = bpy.data.materials.new(f"{asset_id}_material")
    material.use_nodes = True
    material.use_backface_culling = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.92
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(png), check_existing=False)
    texture.interpolation = "Linear"
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    obj = bpy.data.objects.new(asset_id, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj["formula90s_braking_marker"] = True
    obj["asset_id"] = asset_id
    obj["distance_m"] = int(asset_id.removeprefix("braking_"))
    obj["double_sided"] = True
    obj["collision"] = False
    obj["width_m"] = WIDTH_M
    obj["height_m"] = HEIGHT_M
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
    source = repo / "assets-texturas/textures/objects_styles/png/braking_cards"
    destination = repo / "game/resources/environment/assets/trackside_cards/braking"
    records = []
    for number in NUMBERS:
        asset_id = f"braking_{number}"
        png = source / f"{asset_id}.png"
        if not png.is_file():
            raise FileNotFoundError(png)
        glb = destination / f"{asset_id}.glb"
        build_card(asset_id, png, glb)
        records.append({
            "id": asset_id, "kind": "braking_marker_card", "distance_m": int(number),
            "glb": glb.relative_to(repo).as_posix(), "glb_sha256": sha256(glb),
            "source_png": png.relative_to(repo).as_posix(), "source_png_sha256": sha256(png),
            "width_m": WIDTH_M, "height_m": HEIGHT_M, "double_sided": True,
            "collision": False, "origin": "bottom_center",
        })
    manifest = {
        "schema_version": 1, "generator": "la_chutana_braking_marker_cards_v1",
        "coordinate_contract": "X width, Y thickness/normal, Z height; origin bottom-center",
        "assets": records,
    }
    manifest_path = destination / "braking_marker_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
