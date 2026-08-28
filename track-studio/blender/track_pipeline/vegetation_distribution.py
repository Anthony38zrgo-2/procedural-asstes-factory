from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from procedural_catalog import ProceduralAssetSpec


COLORS = ("original", "golden_beige", "copper", "yellow", "red")


@dataclass(frozen=True)
class VegetationAsset:
    spec: ProceduralAssetSpec
    color: str
    family: str
    glb: str


def color_from_id(asset_id: str) -> str:
    for color in COLORS[1:]:
        if asset_id.endswith(f"_{color}"):
            return color
    return "original"


def load_distribution(repo: Path, config: dict) -> tuple[dict, dict[str, list[VegetationAsset]]]:
    relative = config.get("vegetation_distribution_manifest")
    if not relative:
        return {}, {}
    manifest = json.loads((repo / relative).read_text(encoding="utf-8"))
    catalogs: dict[str, list[VegetationAsset]] = {}
    generated_catalog = manifest.get("catalog_manifest")
    if generated_catalog:
        document = json.loads((repo / generated_catalog).read_text(encoding="utf-8"))
        selected_lod = manifest.get("catalog_lod", "lod0")
        for category, singular in (("trees", "tree"), ("bushes", "bush")):
            assets = []
            for index, item in enumerate(
                record for record in document["records"]
                if record["kind"] == singular and record["lod"] == selected_lod
            ):
                width, depth, height = map(float, item["dimensions"])
                lo, hi = map(float, manifest["scale"][category])
                variant = item.get("variant", "green")
                color = "original" if variant == "green" else variant
                asset_id = Path(item["glb"]).stem.removesuffix(f"_{selected_lod}")
                assets.append(VegetationAsset(
                    spec=ProceduralAssetSpec(asset_id, category, 1.0,
                                             max(width, depth) * 0.5, lo, hi,
                                             width, height, depth,
                                             variant_index=index),
                    color=color, family=str(item["family"]),
                    glb="../" + str(item["glb"]),
                ))
            catalogs[category] = assets
        return manifest, catalogs
    for category, report_path in manifest["catalogs"].items():
        report = json.loads((repo / report_path).read_text(encoding="utf-8"))
        assets = []
        for index, item in enumerate(report["assets"]):
            dims = item["dimensions_m"]
            width, height, depth = float(dims["width"]), float(dims["height"]), float(dims["depth"])
            lo, hi = map(float, manifest["scale"][category])
            assets.append(VegetationAsset(
                spec=ProceduralAssetSpec(item["id"], category, 1.0, max(width, depth) * 0.5, lo, hi, width, height, depth, variant_index=index),
                color=color_from_id(item["id"]), family=str(item["family"]), glb=str(item["glb"]),
            ))
        catalogs[category] = assets
    return manifest, catalogs


def sector_for_fraction(manifest: dict, fraction: float) -> dict:
    value = float(fraction) % 1.0
    for sector in manifest["sectors"]:
        if float(sector["from"]) <= value < float(sector["to"]):
            return sector
    return manifest["sectors"][-1]


def choose_asset(rng, category: str, fraction: float, manifest: dict, assets: list[VegetationAsset], usage: dict) -> VegetationAsset:
    sector = sector_for_fraction(manifest, fraction)
    global_weights = manifest["global_weights"][category]
    sector_weights = sector["weights"]
    unseen = [asset for asset in assets if usage["assets"].get(asset.spec.id, 0) == 0]
    if unseen:
        available_colors = {asset.color for asset in unseen}
        scored = [(color, float(sector_weights[color])) for color in COLORS if color in available_colors]
        pick = rng.random() * sum(weight for _, weight in scored)
        selected_color = scored[-1][0]
        for color, weight in scored:
            pick -= weight
            if pick <= 0.0:
                selected_color = color
                break
        candidates = [asset for asset in unseen if asset.color == selected_color]
        return candidates[int(rng.random() * len(candidates)) % len(candidates)]
    total_used = sum(usage["colors"].values())
    scored = []
    for color in COLORS:
        target = float(global_weights[color]) * (total_used + 1)
        deficit = max(0.25, target - usage["colors"][color] + 1.0)
        scored.append((color, float(sector_weights[color]) * deficit))
    pick = rng.random() * sum(weight for _, weight in scored)
    selected_color = scored[-1][0]
    for color, weight in scored:
        pick -= weight
        if pick <= 0.0:
            selected_color = color
            break
    candidates = [asset for asset in assets if asset.color == selected_color]
    minimum = min(usage["assets"].get(asset.spec.id, 0) for asset in candidates)
    least_used = [asset for asset in candidates if usage["assets"].get(asset.spec.id, 0) == minimum]
    asset = least_used[int(rng.random() * len(least_used)) % len(least_used)]
    return asset


def commit_asset(asset: VegetationAsset, usage: dict) -> None:
    usage["colors"][asset.color] += 1
    usage["assets"][asset.spec.id] = usage["assets"].get(asset.spec.id, 0) + 1
