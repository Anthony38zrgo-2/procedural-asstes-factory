from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from validate_barrier_asset_integration import read_glb_json


def validate(glb_path: Path, placements_path: Path) -> dict:
    document = read_glb_json(glb_path)
    placements = json.loads(placements_path.read_text(encoding="utf-8"))
    expected = Counter(item["source_asset_id"] for item in placements.get("trackside_props", []))
    nodes = [node for node in document.get("nodes", [])
             if node.get("extras", {}).get("formula90s_trackside_card")]
    actual = Counter(node["extras"].get("formula90s_trackside_asset_id") for node in nodes)
    if actual != expected:
        raise ValueError(f"Trackside asset mismatch: expected={dict(expected)} actual={dict(actual)}")
    invalid = []
    for node in nodes:
        extras = node.get("extras", {})
        asset_id = extras.get("formula90s_trackside_asset_id")
        authority = extras.get("formula90s_material_authority")
        required_authority = ("procedural_navy_white_flag" if asset_id == "track_flag"
                              else "source_texture")
        if authority != required_authority or extras.get("formula90s_collision") is not False:
            invalid.append(node.get("name", ""))
    if invalid:
        raise ValueError(f"Trackside fallback/collision contract failed: {invalid}")
    material_names = {material.get("name", "") for material in document.get("materials", [])}
    if "F90_TracksideFlag" in material_names:
        raise ValueError("Legacy red flag fallback material remains in GLB")
    return {
        "instances": sum(actual.values()), "asset_counts": dict(actual),
        "legacy_red_flag_materials": 0, "collision": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--placements", type=Path, required=True)
    args = parser.parse_args()
    print("PASS trackside asset integration " + json.dumps(
        validate(args.glb, args.placements), sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
