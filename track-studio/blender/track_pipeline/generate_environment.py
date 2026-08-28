from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import math
import xml.etree.ElementTree as ET

import numpy as np

from pipeline_common import (
    read_json,
    write_json,
    closed_polyline_length,
    interpolate_at_fraction,
    SpatialHash,
    Occupant,
    stable_rng,
)
from procedural_catalog import biome_from_config, specs_for_biome, weighted_choice
from terrain_grid import SegmentSpatialIndex, nearest_track_sample
from vegetation_distribution import COLORS, choose_asset, commit_asset, load_distribution, sector_for_fraction
from safety_barrier_layout import (barrier_conflict, barrier_envelope_at,
                                   load_safety_barrier_layout)
from building_asset_library import load_building_asset_library, specs_from_building_assets

DENSITIES = ("none", "very_low", "low", "medium", "high")
TRACKSIDE_PROP_TYPES = ("spectator", "marshal", "photographer", "flag", "sign")


def load_grass_asset_library(repo: Path, config: dict) -> list[dict]:
    settings = config.get("procedural_environment", {}).get("grass_cards", {})
    relative = settings.get("asset_manifest")
    if not relative:
        raise RuntimeError("procedural_environment.grass_cards.asset_manifest is required")
    manifest_path = (repo / relative).resolve()
    manifest = read_json(manifest_path)
    if manifest.get("generator") != "grass_cards_v5_blender":
        raise RuntimeError(f"Unsupported grass asset manifest: {manifest_path}")
    records = []
    for source in manifest.get("records", []):
        glb = (repo / source["glb"]).resolve()
        if not glb.is_file():
            glb = (repo.parent / source["glb"]).resolve()
        if not glb.is_file():
            raise RuntimeError(f"Grass GLB missing: {glb}")
        runtime_glb = "../" + glb.relative_to(repo.parent).as_posix()
        min_x, min_y = map(float, source["bounds_min"][:2])
        max_x, max_y = map(float, source["bounds_max"][:2])
        radius = max(math.hypot(x, y) for x in (min_x, max_x) for y in (min_y, max_y))
        records.append({
            "variant_id": glb.stem,
            "asset_glb": runtime_glb,
            "radius_m": radius,
            "family": source["family"],
            "color_id": source["variant"],
        })
    if not records:
        raise RuntimeError(f"Grass asset manifest contains no records: {manifest_path}")
    return records


def _semantic_prop_type(asset_id: str) -> str:
    if asset_id.startswith(("spectator_", "person_")):
        return "spectator"
    if asset_id.startswith("marshal_"):
        return "marshal"
    if asset_id == "photographer":
        return "photographer"
    if asset_id == "track_flag":
        return "flag"
    return "sign"


def load_semantic_environment(repo, config, points, distribution, color_catalogs, seed,
                              building_density, building_assets, building_specs,
                              safety_barriers, grass_assets):
    """Resolve exact SVG-authored positions while remapping vegetation to the current catalog."""
    relative = config.get("semantic_environment", {}).get("source_svg")
    if not relative:
        raise RuntimeError("semantic_environment.source_svg is required")
    source = repo / relative
    root = ET.parse(source).getroot()
    track_index = SegmentSpatialIndex.build(points.tolist(), cell_size=32.0)
    usage = {
        category: {"colors": {color: 0 for color in COLORS}, "assets": {}}
        for category in ("trees", "bushes")
    }
    placements = []
    props = []
    grass_points = []
    nodes = sorted(
        (node for node in root.iter() if node.get("data-role") == "asset-instance"),
        key=lambda node: node.get("data-instance-id", ""),
    )
    trees_cfg = config.get("procedural_environment", {}).get("trees", {})
    bushes_cfg = config.get("procedural_environment", {}).get("bushes", {})
    signs_cfg = config.get("trackside_props", {}).get("signs", {})
    people_cfg = config.get("trackside_props", {}).get("people", {})
    flags_cfg = config.get("trackside_props", {}).get("flags", {})
    catalog_relative = config.get("trackside_props", {}).get(
        "object_catalog", "blender/track_pipeline/layouts/la_chutana/object_catalog.json"
    )
    object_catalog = read_json(repo / catalog_relative).get("objects", {})
    prop_assets = {spec["asset_id"]: spec for spec in object_catalog.values()}
    glb_people = sorted(
        (spec for spec in object_catalog.values()
         if spec.get("kind") == "glb_card" and spec.get("category") in {"spectator", "photographer"}),
        key=lambda spec: spec["asset_id"],
    )
    glb_signs = sorted(
        (spec for spec in object_catalog.values()
         if spec.get("kind") == "glb_card" and spec.get("category") == "sign"),
        key=lambda spec: spec["asset_id"],
    )
    lap_length = closed_polyline_length(points)

    trees_enabled = bool(trees_cfg.get("enabled", True))
    bushes_enabled = bool(bushes_cfg.get("enabled", True))
    signs_enabled = bool(signs_cfg.get("enabled", True))
    people_enabled = bool(people_cfg.get("enabled", True))
    flags_enabled = bool(flags_cfg.get("enabled", True))

    tree_scale_mult = float(trees_cfg.get("scale_multiplier", 1.85))
    bush_scale_mult = float(bushes_cfg.get("scale_multiplier", 1.0))

    for node in nodes:
        x = float(node.get("cx"))
        z = float(node.get("cy"))
        category = node.get("data-category")
        nearest = nearest_track_sample(track_index, x, z, 400.0)
        if nearest is None:
            raise RuntimeError(f"SVG instance cannot resolve against centerline: {node.get('data-instance-id')}")
        if category == "grass":
            grass_points.append([round(x, 4), round(z, 4)])
            continue
        if category in {"trees", "bushes"}:
            if category == "trees" and not trees_enabled:
                continue
            if category == "bushes" and not bushes_enabled:
                continue
            assets = color_catalogs.get(category)
            if not assets:
                raise RuntimeError(f"Current vegetation catalog missing: {category}")
            rng = stable_rng(seed, f"semantic:{category}:{node.get('data-instance-id')}")
            asset = choose_asset(rng, category, nearest.fraction, distribution, assets, usage[category])
            commit_asset(asset, usage[category])
            scale = float(node.get("data-scale", "1"))
            if category == "trees":
                scale *= tree_scale_mult
            elif category == "bushes":
                scale *= bush_scale_mult
            placements.append({
                "category": category,
                "variant_id": asset.spec.id,
                "position_xz": [round(x, 4), round(z, 4)],
                "track_fraction": round(nearest.fraction, 7),
                "side": 1 if nearest.side >= 0 else -1,
                "distance_from_center_m": round(abs(nearest.signed_offset_m), 4),
                "distance_to_track_m": round(nearest.distance_m, 4),
                "yaw_rad": round(float(node.get("data-yaw-rad", "0")), 7),
                "scale": round(scale, 6),
                "width_scale": 1.0,
                "height_scale": 1.0,
                "radius_m": round(asset.spec.radius_m * scale, 4),
                "barrier_clearance_required_m": 0.0,
                "color_id": asset.color,
                "family": asset.family,
                "asset_glb": asset.glb,
                "semantic_instance_id": node.get("data-instance-id"),
            })
            continue
        asset_id = node.get("data-asset-id", "")
        prop_type = _semantic_prop_type(asset_id)
        if prop_type == "sign" and not signs_enabled:
            continue
        if prop_type in {"spectator", "marshal", "photographer"} and not people_enabled:
            continue
        if prop_type == "flag" and not flags_enabled:
            continue

        if prop_type in {"spectator", "marshal", "photographer"} and glb_people:
            rng = stable_rng(seed, f"semantic:trackside:{node.get('data-instance-id')}")
            selected = glb_people[int(rng.random() * len(glb_people)) % len(glb_people)]
            asset_id = selected["asset_id"]
            prop_type = str(selected["category"])
        elif prop_type == "sign" and glb_signs:
            rng = stable_rng(seed, f"semantic:trackside:{node.get('data-instance-id')}")
            selected = glb_signs[int(rng.random() * len(glb_signs)) % len(glb_signs)]
            asset_id = selected["asset_id"]

        side_val = 1 if nearest.side >= 0 else -1
        prop_spec = prop_assets.get(asset_id)
        if prop_spec is None:
            raise RuntimeError(f"Semantic prop has no object catalog contract: {asset_id}")
        if prop_type == "sign":
            placement_cfg = signs_cfg
        elif prop_type == "flag":
            placement_cfg = flags_cfg
        else:
            placement_cfg = people_cfg
        outside_offset = float(placement_cfg.get(
            "placement_offset_from_primary_outer_face_m",
            prop_spec.get("guardrail_offset_m", 0.0),
        ))
        envelope = barrier_envelope_at(
            safety_barriers, nearest.fraction, side_val, lap_length,
        )
        target_dist = float(envelope["outer_face_distance_m"]) + outside_offset
        pos, _, normal = interpolate_at_fraction(points, nearest.fraction)
        prop_x = float(pos[0]) + float(normal[0]) * side_val * target_dist
        prop_z = float(pos[1]) + float(normal[1]) * side_val * target_dist
        props.append({
            "prop_type": prop_type,
            "prop_id": node.get("data-instance-id"),
            "source_asset_id": asset_id,
            "position_xz": [round(prop_x, 4), round(prop_z, 4)],
            "track_fraction": round(nearest.fraction, 7),
            "side": side_val,
            "distance_from_center_m": round(target_dist, 4),
            "safety_segment_id": envelope["segment_id"],
            "barrier_prototype_id": envelope["prototype_id"],
            "barrier_outer_face_m": round(float(envelope["outer_face_distance_m"]), 4),
            "required_outside_offset_m": round(outside_offset, 4),
            "collision": False,
        })
    grass_cards_placed = 0
    if config.get("procedural_environment", {}).get("grass_cards", {}).get("enabled", True) and grass_points:
        target_count = min(len(grass_points), int(config.get("semantic_environment", {}).get("grass_cards_count", 2000)))
        step = max(1, len(grass_points) // target_count)
        grass_cfg = config["procedural_environment"]["grass_cards"]
        outside_clearance = float(grass_cfg.get("outside_barrier_clearance_m", 0.35))
        placement_depth = float(grass_cfg.get("outside_barrier_depth_m", 6.5))
        for g_idx in range(0, len(grass_points), step):
            if grass_cards_placed >= target_count:
                break
            gx, gz = grass_points[g_idx]
            g_nearest = nearest_track_sample(track_index, gx, gz, 400.0)
            if g_nearest is None:
                continue
            rng = stable_rng(seed, f"semantic:grass:{g_idx}")
            asset = grass_assets[g_idx % len(grass_assets)]
            scale = float(0.88 + (rng.random() * 0.28))
            yaw = float(rng.random() * math.pi * 2.0)
            g_side = 1 if g_nearest.side >= 0 else -1
            radius = float(asset["radius_m"]) * scale
            envelope = barrier_envelope_at(
                safety_barriers, g_nearest.fraction, g_side, lap_length,
            )
            # Keep the complete cluster behind the outer collision face of the
            # barrier perimeter, including its footprint and a visible margin.
            g_dist = (float(envelope["outer_face_distance_m"]) + radius +
                      outside_clearance + float(rng.random() * placement_depth))
            g_pos, _, g_normal = interpolate_at_fraction(points, g_nearest.fraction)
            card_gx = float(g_pos[0]) + float(g_normal[0]) * g_side * g_dist
            card_gz = float(g_pos[1]) + float(g_normal[1]) * g_side * g_dist
            placements.append({
                "category": "grass",
                "variant_id": asset["variant_id"],
                "position_xz": [round(card_gx, 4), round(card_gz, 4)],
                "track_fraction": round(g_nearest.fraction, 7),
                "side": g_side,
                "distance_from_center_m": round(g_dist, 4),
                "distance_to_track_m": round(g_dist, 4),
                "yaw_rad": round(yaw, 7),
                "scale": round(scale, 6),
                "width_scale": 1.0,
                "height_scale": 1.0,
                "radius_m": round(radius, 4),
                "barrier_clearance_required_m": round(float(envelope["outer_face_distance_m"]) + radius + outside_clearance, 4),
                "barrier_outer_face_m": round(float(envelope["outer_face_distance_m"]), 4),
                "safety_segment_id": envelope["segment_id"],
                "barrier_prototype_id": envelope["prototype_id"],
                "color_id": asset["color_id"],
                "family": asset["family"],
                "asset_glb": asset["asset_glb"],
                "semantic_instance_id": f"grass_{g_idx:04d}",
            })
            grass_cards_placed += 1
    building_placements = []
    building_attempts = 0
    building_clusters = 0
    if config.get("procedural_environment", {}).get("fake_buildings", {}).get("enabled", False):
        occupancy = SpatialHash(cell_size=10.0)
        for item in placements:
            occupancy.add(Occupant(
                float(item["position_xz"][0]), float(item["position_xz"][1]),
                float(item["radius_m"]), item["category"], item["variant_id"],
            ))
        building_placements, building_attempts, building_clusters = place_category(
            "fake_buildings", building_density, config, points, track_index,
            occupancy, seed, distribution, None, safety_barriers,
            building_specs, {asset["id"]: asset for asset in building_assets},
        )
        placements.extend(building_placements)

    stats = {}
    for category in ("trees", "bushes"):
        selected = [item for item in placements if item["category"] == category]
        stats[category] = {
            "authority": "canonical_svg", "placed": len(selected),
            "unique_assets": len({item["variant_id"] for item in selected}),
            "colors": {color: sum(item["color_id"] == color for item in selected) for color in COLORS},
        }
    stats["grass"] = {
        "authority": "canonical_svg_hybrid" if grass_cards_placed > 0 else "canonical_svg_texture_points",
        "placed": grass_cards_placed,
        "texture_points": len(grass_points),
    }
    stats["fake_buildings"] = {
        "authority": "manifest_glb" if building_placements else "disabled",
        "placed": len(building_placements), "attempts": building_attempts,
        "clusters": building_clusters,
        "asset_counts": {
            asset["id"]: sum(item.get("building_asset_id") == asset["id"] for item in building_placements)
            for asset in building_assets
        },
    }
    return placements, props, grass_points, stats, source


@dataclass(frozen=True)
class ClusterAnchor:
    fraction: float
    side: float
    distance_m: float


CLUSTER_DEFAULTS = {
    "grass": {"probability": 0.86, "per_km": 7.0, "fraction_sigma": 0.0060, "distance_sigma_m": 3.4},
    "bushes": {"probability": 0.76, "per_km": 4.0, "fraction_sigma": 0.0080, "distance_sigma_m": 5.0},
    "trees": {"probability": 0.62, "per_km": 2.8, "fraction_sigma": 0.0120, "distance_sigma_m": 8.0},
    "fake_buildings": {"probability": 0.52, "per_km": 1.4, "fraction_sigma": 0.0180, "distance_sigma_m": 12.0},
}


def barrier_minimum_center_distance(config: dict, category: str, radius: float) -> float:
    if category not in {"trees", "bushes"}:
        return 0.0
    road_half = float(config["road"]["width_m"]) * 0.5
    tire = config.get("tire_barriers", {})
    if not tire.get("procedural", False):
        return 0.0
    barrier_center = road_half + float(tire.get("separation_from_edge_m", 5.0))
    barrier_half = float(tire.get("collision_thickness_m", 0.28)) * 0.5
    clearance = float(config.get("vegetation_barrier_clearance_m", {}).get(category, 0.0))
    return barrier_center + barrier_half + clearance + float(radius)


def _zone_distances(config: dict, category: str) -> tuple[float, float]:
    env = config["procedural_environment"]
    zone = env["zones"][category]
    road_half = float(config["road"]["width_m"]) * 0.5
    if "min_edge_clearance_m" in zone:
        min_d = road_half + float(zone["min_edge_clearance_m"])
    else:
        min_d = float(zone["min_track_distance_m"])
    max_d = float(zone["max_track_distance_m"])
    if max_d <= min_d:
        raise ValueError(f"Invalid {category} zone: max distance must exceed minimum")
    return min_d, max_d


def _make_clusters(rng, category: str, lap_length: float, min_d: float, max_d: float) -> list[ClusterAnchor]:
    settings = CLUSTER_DEFAULTS[category]
    count = max(3, int(round(float(settings["per_km"]) * lap_length / 1000.0)))
    anchors = []
    for _ in range(count):
        anchors.append(ClusterAnchor(
            fraction=rng.random(),
            side=-1.0 if rng.random() < 0.5 else 1.0,
            distance_m=rng.uniform(min_d, max_d),
        ))
    return anchors


def _candidate_from_cluster(rng, category: str, anchor: ClusterAnchor, min_d: float, max_d: float):
    settings = CLUSTER_DEFAULTS[category]
    fraction = (anchor.fraction + rng.gauss(0.0, float(settings["fraction_sigma"]))) % 1.0
    distance = min(max_d, max(min_d, anchor.distance_m + rng.gauss(0.0, float(settings["distance_sigma_m"]))))
    return fraction, anchor.side, distance


def place_category(category, density, config, points, track_index, occupancy, seed,
                   distribution=None, asset_catalog=None, safety_barrier_layout=None,
                   building_specs=(), building_by_id=None):
    env = config["procedural_environment"]
    if category == "fake_buildings" and not env.get("fake_buildings", {}).get("enabled", True):
        return [], 0, 0
    if category == "grass" and not env.get("grass_cards", {}).get("enabled", True):
        return [], 0, 0
    profile = env["density_profiles"][density]
    lap_length = closed_polyline_length(points)
    target = int(round(float(profile[f"{category}_per_km"]) * lap_length / 1000.0))
    min_d, max_d = _zone_distances(config, category)
    biome = biome_from_config(config)
    specs = specs_for_biome(biome, category)
    rng = stable_rng(seed, f"{biome.id}:{category}")
    cluster_rng = stable_rng(seed, f"{biome.id}:{category}:clusters")
    clusters = _make_clusters(cluster_rng, category, lap_length, min_d, max_d)
    cluster_probability = float(CLUSTER_DEFAULTS[category]["probability"])

    output = []
    attempts = 0
    max_attempts = max(1000, target * 140)
    road_half = float(config["road"]["width_m"]) * 0.5
    edge_clearance = min_d - road_half
    usage = {"colors": {color: 0 for color in COLORS}, "assets": {}}

    while len(output) < target and attempts < max_attempts:
        attempts += 1
        if clusters and rng.random() < cluster_probability:
            anchor = clusters[int(rng.random() * len(clusters)) % len(clusters)]
            fraction, side, distance = _candidate_from_cluster(rng, category, anchor, min_d, max_d)
        else:
            fraction = rng.random()
            side = -1.0 if rng.random() < 0.5 else 1.0
            distance = rng.uniform(min_d, max_d)

        selected_asset = None
        selected_building = None
        if distribution and asset_catalog and category in {"trees", "bushes"}:
            selected_asset = choose_asset(rng, category, fraction, distribution, asset_catalog, usage)
            spec = selected_asset.spec
        elif category == "fake_buildings" and building_specs:
            # Deterministic round-robin guarantees that every reviewed building
            # appears before variants repeat, while placement remains seeded.
            spec = building_specs[len(output) % len(building_specs)]
            selected_building = (building_by_id or {}).get(spec.id)
            if selected_building is None:
                raise RuntimeError(f"Building spec has no manifest asset: {spec.id}")
        else:
            spec = weighted_choice(rng, specs)

        pos, tangent, normal = interpolate_at_fraction(points, fraction)
        candidate = pos + normal * (side * distance)
        nearest = nearest_track_sample(track_index, float(candidate[0]), float(candidate[1]), max_d + 40.0)
        if nearest is None:
            continue
        global_distance = float(nearest.distance_m)

        scale = rng.uniform(spec.scale_min, spec.scale_max)
        radius = max(.05, spec.radius_m * scale)
        minimum_center_distance = road_half + edge_clearance + radius
        if global_distance + 1e-6 < minimum_center_distance or global_distance > max_d + 1.0:
            continue

        if category in {"trees", "bushes"}:
            required_outside = barrier_minimum_center_distance(config, category, radius)
            if global_distance + 1e-6 < required_outside:
                continue
            if safety_barrier_layout and barrier_conflict(
                safety_barrier_layout, category, fraction, int(side), global_distance, radius
            ):
                continue

        padding = {"grass": .04, "bushes": .30, "trees": .95, "fake_buildings": 2.5}[category]
        if not occupancy.can_place(float(candidate[0]), float(candidate[1]), radius, padding):
            continue

        if category == "fake_buildings":
            yaw = math.atan2(float(tangent[1]), float(tangent[0])) + rng.uniform(-.14, .14)
            width_scale = rng.uniform(.88, 1.14)
            height_scale = rng.uniform(.92, 1.12)
        elif category == "trees":
            yaw = rng.uniform(0.0, math.tau)
            width_scale = rng.uniform(.90, 1.14)
            height_scale = rng.uniform(.96, 1.14)
        elif category == "bushes":
            yaw = rng.uniform(0.0, math.tau)
            width_scale = rng.uniform(1.02, 1.24)
            height_scale = rng.uniform(.94, 1.08)
        else:
            yaw = rng.uniform(0.0, math.tau)
            width_scale = rng.uniform(.92, 1.12)
            height_scale = rng.uniform(.90, 1.10)

        strength = {"grass": .020, "bushes": .026, "trees": .022, "fake_buildings": .014}[category]
        tint = [round(1.0 + rng.uniform(-strength, strength), 4) for _ in range(3)]

        record = {
            "category": category,
            "variant_id": spec.id,
            "position_xz": [round(float(candidate[0]), 4), round(float(candidate[1]), 4)],
            "track_fraction": round(float(fraction), 7),
            "side": int(side),
            "distance_from_center_m": round(float(distance), 4),
            "distance_to_track_m": round(float(global_distance), 4),
            "yaw_rad": round(float(yaw), 6),
            "scale": round(float(scale), 5),
            "width_scale": round(float(width_scale), 5),
            "height_scale": round(float(height_scale), 5),
            "radius_m": round(float(radius), 4),
            "barrier_clearance_required_m": round(float(required_outside), 4) if category in {"trees", "bushes"} else 0.0,
            "tint_rgb": tint,
        }
        if selected_asset is not None:
            record["color_id"] = selected_asset.color
            record["family"] = selected_asset.family
            record["asset_glb"] = selected_asset.glb
            record["sector_id"] = sector_for_fraction(distribution, fraction)["id"]
        if selected_building is not None:
            building_glb = str(selected_building["glb"])
            record["asset_glb"] = building_glb if building_glb.startswith("../") else "../" + building_glb
            record["building_asset_id"] = selected_building["id"]
            record["collision"] = False
        output.append(record)
        if selected_asset is not None:
            commit_asset(selected_asset, usage)
        occupancy.add(Occupant(float(candidate[0]), float(candidate[1]), radius, category, spec.id))

    if len(output) < target:
        raise RuntimeError(f"Could only place {len(output)}/{target} {category} after {attempts} attempts.")
    return output, attempts, len(clusters)


def generate_trackside_props(config: dict, points: np.ndarray,
                             safety_barriers: dict | None = None) -> list[dict]:
    """Place lightweight non-collidable 2D trackside cards outside the tire perimeter."""
    props_config = config.get("trackside_props", {})
    tire_config = config.get("tire_barriers", {})
    if not props_config.get("procedural", True):
        return []
    lap_length = closed_polyline_length(points)
    road_half = float(config["road"]["width_m"]) * 0.5
    outside_offset = float(props_config.get("outside_barrier_offset_m", 1.8))
    max_cards = max(0, int(props_config.get("max_visible_cards", 260)))
    spacing = props_config.get("spacing_m", {})
    output: list[dict] = []
    for type_index, prop_type in enumerate(TRACKSIDE_PROP_TYPES):
        step = max(12.0, float(spacing.get(prop_type, 80.0)))
        count = max(1, int(math.ceil(lap_length / step)))
        for index in range(count):
            if len(output) >= max_cards:
                return output
            fraction = ((index + 0.37 + type_index * 0.11) / count) % 1.0
            side = -1 if (index + type_index) % 2 else 1
            envelope = (barrier_envelope_at(safety_barriers, fraction, side, lap_length)
                        if safety_barriers else None)
            barrier_distance = (float(envelope["outer_face_distance_m"]) if envelope else
                                road_half + float(tire_config.get("separation_from_edge_m", 5.0)))
            distance = barrier_distance + outside_offset
            pos, _, _ = interpolate_at_fraction(points, fraction)
            output.append({
                "prop_type": prop_type,
                "prop_id": f"{prop_type}_{index:03d}",
                "position_xz": [round(float(pos[0]), 4), round(float(pos[1]), 4)],
                "track_fraction": round(float(fraction), 7),
                "side": side,
                "distance_from_center_m": round(distance, 4),
                **({
                    "safety_segment_id": envelope["segment_id"],
                    "barrier_prototype_id": envelope["prototype_id"],
                    "barrier_outer_face_m": round(float(envelope["outer_face_distance_m"]), 4),
                    "required_outside_offset_m": round(outside_offset, 4),
                } if envelope else {}),
                "collision": False,
            })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reproducible clustered procedural environment placement.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--trees-density", choices=DENSITIES, default="low")
    parser.add_argument("--bushes-density", choices=DENSITIES, default="low")
    parser.add_argument("--grass-density", choices=DENSITIES, default="medium")
    parser.add_argument("--buildings-density", choices=DENSITIES, default="very_low")
    parser.add_argument("--seed", type=int, default=1995)
    ns = parser.parse_args()

    cp = Path(ns.config).resolve()
    repo = cp.parents[3]
    config = read_json(cp)
    distribution, color_catalogs = load_distribution(repo, config)
    safety_barriers = load_safety_barrier_layout(repo, config)
    building_assets = load_building_asset_library(repo, config)
    building_specs = specs_from_building_assets(building_assets)
    grass_assets = load_grass_asset_library(repo, config)
    center = read_json(repo / config["generated_dir"] / "centerline.json")
    points = np.asarray(center["points_xz"], dtype=float)
    biome = biome_from_config(config)
    if config.get("semantic_environment", {}).get("enabled", False):
        placements, trackside_props, grass_points, stats, source = load_semantic_environment(
            repo, config, points, distribution, color_catalogs, ns.seed,
            ns.buildings_density, building_assets, building_specs, safety_barriers,
            grass_assets,
        )
        output = repo / config["generated_dir"] / "placements.json"
        write_json(output, {
            "track_id": config["track_id"], "biome": biome.id, "seed": ns.seed,
            "authority": "canonical_svg", "source_svg": str(source.relative_to(repo)).replace("\\", "/"),
            "stats": stats, "placements": placements,
            "trackside_props": trackside_props, "grass_texture_points_xz": grass_points,
        })
        print(f"[environment] semantic authority={source} wrote {output}")
        print(f"[environment] trees={stats['trees']['placed']} bushes={stats['bushes']['placed']} grass_texture_points={len(grass_points)} props={len(trackside_props)}")
        return 0
    occupancy = SpatialHash(cell_size=10.0)
    track_index = SegmentSpatialIndex.build(points.tolist(), cell_size=32.0)
    placements = []
    stats = {}

    for category, density in (
        ("fake_buildings", ns.buildings_density),
        ("trees", ns.trees_density),
        ("bushes", ns.bushes_density),
        ("grass", ns.grass_density),
    ):
        placed, attempts, clusters = place_category(
            category, density, config, points, track_index, occupancy, ns.seed,
            distribution, color_catalogs.get(category), safety_barriers,
            building_specs, {asset["id"]: asset for asset in building_assets},
        )
        placements.extend(placed)
        stats[category] = {"density": density, "placed": len(placed), "attempts": attempts, "clusters": clusters}
        if category in {"trees", "bushes"} and distribution:
            stats[category]["colors"] = {
                color: sum(1 for item in placed if item.get("color_id") == color) for color in COLORS
            }
            stats[category]["unique_assets"] = len({item["variant_id"] for item in placed})

    trackside_props = generate_trackside_props(config, points, safety_barriers)

    output = repo / config["generated_dir"] / "placements.json"
    write_json(output, {
        "track_id": config["track_id"],
        "biome": biome.id,
        "seed": ns.seed,
        "stats": stats,
        "placements": placements,
        "trackside_props": trackside_props,
    })
    print(f"[environment] biome={biome.id} wrote {output}")
    for category, stat in stats.items():
        print(f"[environment] {category}: {stat['placed']} ({stat['density']}) clusters={stat['clusters']} attempts={stat['attempts']}")
    print(f"[environment] trackside_props: {len(trackside_props)} non-collidable cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
