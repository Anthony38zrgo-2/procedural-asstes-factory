"""Stage canonical La Chutana inputs for the factory quick test.

This script never reads Formula90s. It copies the transferred snapshots into the
working generated directory and rewrites vegetation GLB paths to the approved
LOD0 library under procedural/generated/vegetation_v5.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil


FACTORY_ROOT = Path(__file__).resolve().parents[2]
STUDIO_ROOT = FACTORY_ROOT / "track-studio"
INPUT_ROOT = STUDIO_ROOT / "inputs" / "la_chutana"
GENERATED_ROOT = STUDIO_ROOT / "blender" / "generated" / "la_chutana"


def main() -> None:
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INPUT_ROOT / "centerline.json", GENERATED_ROOT / "centerline.json")

    document = json.loads((INPUT_ROOT / "placements.json").read_text(encoding="utf-8"))
    rewritten = 0
    for placement in document.get("placements", []):
        asset = placement.get("asset_glb")
        if not asset:
            continue
        category = placement.get("category")
        if category in {"trees", "bushes"}:
            source_name = Path(asset).stem
            # tree_3d_06 was explicitly removed from the approved v5 release.
            # Preserve its seasonal suffix while using the approved tree_3d_05
            # replacement rather than reaching into discarded_assets.
            if source_name.startswith("tree_3d_06"):
                source_name = source_name.replace("tree_3d_06", "tree_3d_05", 1)
                placement["variant_id"] = source_name
            kind = "trees" if category == "trees" else "bushes"
            placement["asset_glb"] = (
                f"../procedural/generated/vegetation_v5/assets/{kind}/"
                f"{source_name}_lod0.glb"
            )
            rewritten += 1
        elif asset.startswith("game/resources/environment/assets/buildings/"):
            placement["asset_glb"] = "../" + asset
            rewritten += 1

    (GENERATED_ROOT / "placements.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    print(f"staged centerline.json and placements.json; rewritten_asset_paths={rewritten}")


if __name__ == "__main__":
    main()
