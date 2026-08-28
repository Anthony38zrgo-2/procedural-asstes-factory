"""Build the deterministic 4 m concrete-and-steel secondary fence module."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import PBRMaterial


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "game/resources/environment/assets/barriers/secondary_fence"
ASSET_ID = "barrier_fence_concrete_steel_4m"


def card(width: float, y0: float, height: float, texture: Path, repeats: float,
         material_name: str, metallic: float, roughness: float, alpha: bool) -> trimesh.Trimesh:
    vertices = np.array([
        [-width / 2, y0, 0], [width / 2, y0, 0],
        [width / 2, y0 + height, 0], [-width / 2, y0 + height, 0],
    ], dtype=float)
    faces = np.array([[0, 1, 2], [0, 2, 3]])
    uv = np.array([[0, 0], [repeats, 0], [repeats, 1], [0, 1]], dtype=float)
    material = PBRMaterial(
        name=material_name,
        baseColorTexture=Image.open(texture).convert("RGBA"),
        metallicFactor=metallic,
        roughnessFactor=roughness,
        doubleSided=True,
        alphaMode="MASK" if alpha else "OPAQUE",
        alphaCutoff=0.5,
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return mesh


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    concrete = ROOT / "assets-texturas/textures/terrain/png/112.png"
    steel = ROOT / "assets-texturas/textures/terrain/png/113.png"
    scene = trimesh.Scene()
    scene.add_geometry(card(4.0, 0.0, 0.75, concrete, 2.0,
                            "FenceConcrete112", 0.0, 0.92, False), node_name="ConcreteBase")
    scene.add_geometry(card(4.0, 0.75, 2.55, steel, 2.0,
                            "FenceSteel113", 0.72, 0.55, True), node_name="SteelMesh")
    post_material = PBRMaterial(name="FencePosts", baseColorFactor=[0.34, 0.36, 0.37, 1.0],
                                metallicFactor=0.78, roughnessFactor=0.48)
    for index, x in enumerate((-2.0, 0.0, 2.0)):
        post = trimesh.creation.box(extents=(0.075, 3.37, 0.075))
        post.apply_translation((x, 1.685, -0.025))
        post.visual.material = post_material
        scene.add_geometry(post, node_name=f"Post_{index}")
    visual = OUTPUT / f"{ASSET_ID}.glb"
    visual.write_bytes(scene.export(file_type="glb"))

    collision = trimesh.creation.box(extents=(4.0, 3.30, 0.15))
    collision.apply_translation((0.0, 1.65, 0.0))
    collision_path = OUTPUT / f"{ASSET_ID}-colonly.glb"
    collision_path.write_bytes(trimesh.Scene(collision).export(file_type="glb"))
    manifest = {
        "schema_version": 1,
        "generator": "secondary_fence_v1",
        "asset_id": ASSET_ID,
        "visual_glb": visual.relative_to(ROOT).as_posix(),
        "collision_glb": collision_path.relative_to(ROOT).as_posix(),
        "dimensions_m": [4.0, 3.30, 0.15],
        "concrete": {"texture": concrete.relative_to(ROOT).as_posix(), "height_m": 0.75},
        "steel": {"texture": steel.relative_to(ROOT).as_posix(), "height_m": 2.55},
        "posts_spacing_m": 2.0,
        "double_sided": True,
    }
    (OUTPUT / "secondary_fence_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
