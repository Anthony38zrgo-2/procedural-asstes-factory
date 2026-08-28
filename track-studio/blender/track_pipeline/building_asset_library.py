from __future__ import annotations

import hashlib
import json
from pathlib import Path

from procedural_catalog import ProceduralAssetSpec


def resolve_factory_path(repo: Path, relative: str) -> Path:
    path = (repo / relative).resolve()
    if path.is_file():
        return path
    factory_path = (repo.parent / relative).resolve()
    if factory_path.is_file():
        return factory_path
    raise FileNotFoundError(f"Factory asset does not exist: {relative}")


def load_building_asset_library(repo: Path, config: dict) -> list[dict]:
    relative = config.get("procedural_environment", {}).get("fake_buildings", {}).get("asset_manifest")
    if not relative:
        return []
    manifest_path = repo / relative
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("generator") != "formula90_building_manifest_v1":
        raise ValueError(f"Unsupported building asset manifest: {manifest_path}")
    assets = manifest.get("assets", [])
    if not assets:
        raise ValueError("Building asset manifest contains no assets")
    seen = set()
    for asset in assets:
        if asset["id"] in seen:
            raise ValueError(f"Duplicate building asset: {asset['id']}")
        seen.add(asset["id"])
        path = resolve_factory_path(repo, asset["glb"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["glb_sha256"]:
            raise ValueError(f"Building asset hash mismatch: {path}")
        if asset.get("collision") is not False:
            raise ValueError(f"Scenic building must be non-collidable: {asset['id']}")
    return assets


def specs_from_building_assets(assets: list[dict]) -> tuple[ProceduralAssetSpec, ...]:
    specs = []
    for index, asset in enumerate(assets):
        width, height, depth = (float(value) for value in asset["geometry"]["extents"])
        specs.append(ProceduralAssetSpec(
            asset["id"], "fake_buildings", float(asset.get("weight", 1.0)),
            max(width, depth) * 0.58, 0.92, 1.08, width, height, depth,
            variant_index=index,
        ))
    return tuple(specs)
