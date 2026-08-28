from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path


def read_glb_json(path: Path) -> dict:
    payload = path.read_bytes()
    if payload[:4] != b"glTF" or len(payload) < 20:
        raise ValueError(f"Not a valid GLB container: {path}")
    json_length, json_kind = struct.unpack_from("<II", payload, 12)
    if json_kind != 0x4E4F534A:
        raise ValueError(f"GLB first chunk is not JSON: {path}")
    return json.loads(payload[20:20 + json_length].decode("utf-8").rstrip("\x00 "))


def validate(glb_path: Path, asset_manifest_path: Path, report_path: Path) -> dict:
    document = read_glb_json(glb_path)
    manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected = Counter(report.get("asset_counts", {}))
    if not expected:
        raise ValueError("Safety barrier report contains no library asset counts")
    known = {entry["id"] for entry in manifest.get("assets", [])}
    unknown = set(expected) - known
    if unknown:
        raise ValueError(f"Report references unknown barrier assets: {sorted(unknown)}")
    actual = Counter(
        node.get("extras", {}).get("barrier_asset_id")
        for node in document.get("nodes", [])
        if node.get("extras", {}).get("barrier_asset_id")
    )
    if actual != expected:
        raise ValueError(f"Barrier instance mismatch: expected={dict(expected)} actual={dict(actual)}")
    legacy_nodes = [
        node.get("name", "") for node in document.get("nodes", [])
        if (node.get("extras", {}).get("formula90s_continuous_tire_barrier") or
            node.get("name", "").startswith("TireBarrierVisual") or
            node.get("name", "").startswith("TireBarrierCollision"))
    ]
    if legacy_nodes:
        raise ValueError(f"Legacy barrier nodes remain in GLB: {legacy_nodes[:8]}")
    unused = known - set(actual)
    if unused:
        raise ValueError(f"Barrier library assets are not represented in runtime: {sorted(unused)}")
    mesh_names = {mesh.get("name", "") for mesh in document.get("meshes", [])}
    for asset_id in expected:
        if f"{asset_id}_visual" not in mesh_names:
            raise ValueError(f"GLB is missing library mesh {asset_id}_visual")
    return {"instances": sum(actual.values()), "asset_counts": dict(actual),
            "legacy_nodes": 0, "meshes": len(mesh_names)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.glb, args.asset_manifest, args.report)
    print("PASS barrier asset integration " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
