from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bmesh
import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_track_blender import args_after_double_dash, read_json
from curb_manifest import load_curb_manifest


def _is_closed_manifold(obj: bpy.types.Object) -> bool:
    mesh = bmesh.new()
    try:
        mesh.from_mesh(obj.data)
        return bool(mesh.edges) and all(len(edge.link_faces) == 2 for edge in mesh.edges)
    finally:
        mesh.free()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated reusable curb profiles in Blender.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(args_after_double_dash())
    config_path = Path(args.config).resolve()
    repo = config_path.parents[3]
    config = read_json(config_path)
    manifest = load_curb_manifest(config_path, config)
    blend = repo / config["generated_dir"] / "track_base.blend"
    bpy.ops.wm.open_mainfile(filepath=str(blend))

    failures: list[str] = []
    for segment in config["curb"]["segments"]:
        name = segment["name"]
        profile_id = segment["profile_id"]
        profile = manifest["profiles"][profile_id]
        visual = bpy.data.objects.get(f"Curb_{name}")
        collision = bpy.data.objects.get(f"CurbCollision_{name}-colonly")
        if visual is None or collision is None:
            failures.append(f"{name}: missing visual/collision object")
            continue
        if visual.get("formula90s_curb_profile") != profile_id:
            failures.append(f"{name}: profile metadata mismatch")
        if abs(float(visual.get("formula90s_curb_width_m", 0.0)) - float(profile["width_m"])) > 1e-6:
            failures.append(f"{name}: width metadata mismatch")
        if visual.data.uv_layers.get("UVMap") is None:
            failures.append(f"{name}: missing UVMap")
        material_names = {slot.material.name for slot in visual.material_slots if slot.material is not None}
        if material_names != {"F90_Curb_white", "F90_Curb_navy", "F90_Curb_concrete"}:
            failures.append(f"{name}: unexpected material slots {sorted(material_names)}")
        used_materials = {polygon.material_index for polygon in visual.data.polygons}
        if used_materials != {0, 1, 2}:
            failures.append(f"{name}: white/navy top bands or concrete structure are not used")
        if not _is_closed_manifold(visual) or not _is_closed_manifold(collision):
            failures.append(f"{name}: visual/collision mesh is not closed manifold")
        if not bool(collision.get("formula90s_curb_closed_collision")):
            failures.append(f"{name}: collision metadata does not declare closed geometry")
        print(
            f"[curb] {name} profile={profile_id} vertices={len(visual.data.vertices)} "
            f"faces={len(visual.data.polygons)} manifold={_is_closed_manifold(visual)}"
        )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 2
    print(f"PASS curb profiles={len(config['curb']['segments'])} catalog={','.join(sorted(manifest['profiles']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
