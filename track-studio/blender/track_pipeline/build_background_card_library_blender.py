from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from blender_output import atomic_export_glb


def material(name: str, texture: Path):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    mat["gltf2_unlit"] = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(texture))
    tex.interpolation = "Linear"
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Roughness"].default_value = 1.0
    return mat


def create_card(asset_id: str, texture: Path):
    image = bpy.data.images.load(str(texture), check_existing=True)
    aspect = image.size[0] / image.size[1]
    h, w = 1.0, aspect
    mesh = bpy.data.meshes.new(f"{asset_id}_mesh")
    mesh.from_pydata(
        [(-w / 2, 0, 0), (w / 2, 0, 0), (w / 2, 0, h), (-w / 2, 0, h)],
        [], [(0, 1, 2, 3)],
    )
    mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(mesh.uv_layers.active.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop.uv = uv
    obj = bpy.data.objects.new(asset_id, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material(f"{asset_id}_unlit", texture))
    obj["background_card"] = True
    obj["collision"] = False
    return obj


def main():
    repo = Path(__file__).resolve().parents[2]
    root = repo.parent / "game/resources/environment/assets/background_cards"
    textures = root / "textures"
    output = root / "glb"
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for texture in sorted(textures.glob("*.png")):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        obj = create_card(texture.stem, texture)
        target = output / f"{texture.stem}.glb"
        atomic_export_glb(target)
        layer = "far" if "far" in texture.stem else "near" if "near" in texture.stem else "transition"
        assets.append({
            "id": texture.stem, "layer": layer,
            "glb": "../" + target.relative_to(repo.parent).as_posix(),
            "texture": "../" + texture.relative_to(repo.parent).as_posix(),
            "aspect": obj.dimensions.x / obj.dimensions.z,
            "collision": False, "double_sided": True, "unlit": True,
        })
    manifest = {"schema_version": 1, "generator": "background_billboard_v1", "assets": assets}
    (root / "background_card_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
