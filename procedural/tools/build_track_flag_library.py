"""Generate the reusable double-sided 1990s navy/white track flag GLB."""
from pathlib import Path
import json

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "game/resources/environment/assets/trackside_cards/flags"


def plane(name, x0, x1, y0, y1, color):
    vertices = np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]], dtype=float)
    mesh = trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    mesh.visual.material = PBRMaterial(
        name=name, baseColorFactor=color, metallicFactor=0.0,
        roughnessFactor=0.82, doubleSided=True,
    )
    return mesh


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    navy = [0.025, 0.09, 0.22, 1.0]
    white = [0.90, 0.89, 0.84, 1.0]
    steel = PBRMaterial(name="FlagPoleSteel", baseColorFactor=[0.32, 0.35, 0.38, 1.0],
                        metallicFactor=0.72, roughnessFactor=0.48)
    pole = trimesh.creation.box(extents=(0.16, 5.50, 0.08))
    pole.apply_translation((-0.92, 2.75, -0.025))
    pole.visual.material = steel
    scene.add_geometry(pole, node_name="FlagPole")
    scene.add_geometry(plane("FlagNavyUpper", -0.84, 1.00, 4.18, 5.50, navy), node_name="NavyUpper")
    scene.add_geometry(plane("FlagWhiteBand", -0.84, 1.00, 3.52, 4.18, white), node_name="WhiteBand")
    scene.add_geometry(plane("FlagNavyLower", -0.84, 1.00, 2.86, 3.52, navy), node_name="NavyLower")
    path = OUTPUT / "track_flag_90s.glb"
    path.write_bytes(scene.export(file_type="glb"))
    manifest = {
        "schema_version": 1, "generator": "track_flag_glb_v1",
        "asset_id": "track_flag", "glb": path.relative_to(ROOT).as_posix(),
        "dimensions_m": [1.92, 5.50, 0.08], "double_sided": True,
        "collision": False,
    }
    (OUTPUT / "flag_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
