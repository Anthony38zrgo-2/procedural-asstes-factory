"""Read-only dependency preflight for the La Chutana quick-test builders."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parents[2]
STUDIO_ROOT = FACTORY_ROOT / "track-studio"
CONFIG = STUDIO_ROOT / "blender/track_pipeline/configs/la_chutana_factory.json"


def _resolve_factory_relative(rel: str) -> Path | None:
    """Resolve a factory-relative path like '../procedural/...' against STUDIO or FACTORY."""
    p1 = (STUDIO_ROOT / rel).resolve()
    if p1.is_file():
        return p1
    # Try factory-relative resolution (handles ../ prefix)
    if rel.startswith("../"):
        p2 = (FACTORY_ROOT / Path(rel).relative_to("../")).resolve()
        if p2.is_file():
            return p2
        # fallback: strip all leading ../ segments
        stripped = rel
        while stripped.startswith("../"):
            stripped = stripped[3:]
        p3 = (FACTORY_ROOT / stripped).resolve()
        if p3.is_file():
            return p3
    p4 = (FACTORY_ROOT / rel).resolve()
    if p4.is_file():
        return p4
    return None


def _collect_config_paths(config: dict, mode: str) -> list[str]:
    common = [
        config["reference_file"],
        config["vegetation_distribution_manifest"],
        config["curb"]["manifest"],
        config["semantic_environment"]["source_svg"],
        config["semantic_layout_config"],
    ]
    if mode == "Environment":
        common.extend([
            config["safety_barriers"]["manifest"],
            config["safety_barriers"]["asset_library_manifest"],
            config["trackside_props"]["object_catalog"],
            config["procedural_environment"]["fake_buildings"]["asset_manifest"],
        ])
    return common


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("Base", "Environment"), default="Base")
    args = parser.parse_args()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    missing = [rel for rel in _collect_config_paths(config, args.mode)
               if not (STUDIO_ROOT / rel).is_file()]

    if args.mode == "Environment":
        placements_path = STUDIO_ROOT / config["generated_dir"] / "placements.json"
        if placements_path.is_file():
            placements = json.loads(placements_path.read_text(encoding="utf-8"))
            for item in placements.get("placements", []):
                asset = item.get("asset_glb")
                if asset and not (STUDIO_ROOT / asset).is_file():
                    missing.append(asset)

        # --- Mountains authority validation (Req. 3-4) ---
        mountains = config.get("procedural_environment", {}).get("mountains", {})
        if mountains.get("enabled", False):
            rel_manifest = mountains.get("manifest")
            if not rel_manifest:
                print("preflight Environment: mountains.enabled but manifest path is missing")
                return 2
            manifest_path = _resolve_factory_relative(rel_manifest)
            if manifest_path is None:
                print(f"preflight Environment: mountains manifest not found: {rel_manifest}")
                missing.append(rel_manifest)
            else:
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    print(f"preflight Environment: cannot parse mountains manifest {manifest_path}: {exc}")
                    return 2
                if manifest.get("schema_version") != 1:
                    print(f"preflight Environment: unsupported mountains schema_version={manifest.get('schema_version')} expected 1")
                    return 2
                if manifest.get("asset") != "la_chutana_mountains_3d":
                    print(f"preflight Environment: unexpected mountains asset={manifest.get('asset')} expected la_chutana_mountains_3d")
                    return 2
                if mountains.get("collision", False) is not False:
                    print("preflight Environment: mountains.collision must be false")
                    return 2
                base_dir = manifest_path.parent
                geom = manifest.get("geometry_assets", {})
                tex = manifest.get("textures", {})
                sha_map = manifest.get("validation", {}).get("source_sha256", {})
                # Check each required file according to enabled toggles
                checks = []
                if mountains.get("near_enabled", True):
                    checks.append(("near_mountains", geom.get("near_mountains")))
                if mountains.get("far_enabled", True):
                    checks.append(("far_mountains", geom.get("far_mountains")))
                if mountains.get("sky_dome_enabled", False):
                    checks.append(("sky_dome", geom.get("sky_dome")))
                # Texture is always required when mountains enabled (shared)
                if tex.get("mountain_texture"):
                    checks.append(("mountain_texture", tex.get("mountain_texture")))
                for _key, fname in checks:
                    if not fname:
                        print(f"preflight Environment: mountains manifest missing entry for {_key}")
                        return 2
                    fpath = (base_dir / fname).resolve()
                    if not fpath.is_file():
                        print(f"preflight Environment: mountains asset missing: {fpath} (manifest declares {fname})")
                        missing.append(str(fpath))
                        continue
                    expected = sha_map.get(fname)
                    if not expected:
                        print(f"preflight Environment: manifest has no SHA for {fname}")
                        return 2
                    actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
                    if actual != expected:
                        print(f"preflight Environment: SHA mismatch for {fname}")
                        print(f"  expected {expected}")
                        print(f"  actual   {actual}")
                        print(f"  file     {fpath}")
                        return 2
                print(f"preflight Environment: mountains authority OK manifest={manifest_path} near={mountains.get('near_enabled')} far={mountains.get('far_enabled')} sky={mountains.get('sky_dome_enabled')} hashes=matched")

    unique = sorted(set(missing))
    if unique:
        print(f"preflight {args.mode}: missing {len(unique)} required files")
        for path in unique:
            print(f"  MISSING {path}")
        return 2
    print(f"preflight {args.mode}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
