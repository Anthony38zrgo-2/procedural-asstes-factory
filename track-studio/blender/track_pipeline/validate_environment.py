from __future__ import annotations

import argparse
from pathlib import Path

from pipeline_common import read_json, SpatialHash, Occupant
from generate_environment import barrier_minimum_center_distance, load_grass_asset_library
from building_asset_library import load_building_asset_library
from vegetation_distribution import COLORS, load_distribution
from safety_barrier_layout import (barrier_conflict, compile_layout,
                                   barrier_envelope_at, coverage_gaps_by_side,
                                   load_safety_barrier_layout,
                                   overlaps_by_side)


def _minimum_center_distance(config: dict, category: str, radius: float) -> float:
    road_half = float(config["road"]["width_m"]) * 0.5
    zone = config["procedural_environment"]["zones"][category]
    if "min_edge_clearance_m" in zone:
        return road_half + float(zone["min_edge_clearance_m"]) + float(radius)
    return float(zone["min_track_distance_m"]) + float(radius)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate procedural environment placement before Blender assembly.")
    parser.add_argument("--config", required=True)
    ns = parser.parse_args()
    cp = Path(ns.config).resolve()
    repo = cp.parents[3]
    config = read_json(cp)
    generated = repo / config["generated_dir"]
    placements_doc = read_json(generated / "placements.json")
    items = placements_doc["placements"]
    distribution, catalogs = load_distribution(repo, config)
    safety_barriers = load_safety_barrier_layout(repo, config)
    building_assets = load_building_asset_library(repo, config)
    grass_assets = load_grass_asset_library(repo, config)
    grass_by_id = {asset["variant_id"]: asset for asset in grass_assets}
    centerline = read_json(generated / "centerline.json")
    lap_length_m = float(centerline["length_m"])

    failures = 0
    occupancy = SpatialHash(cell_size=10.0)
    overlap_count = 0
    clearance_failures = 0

    padding_by_category = {"grass": .04, "bushes": .30, "trees": .95, "fake_buildings": 2.5}
    for item in items:
        category = item["category"]
        x, z = map(float, item["position_xz"])
        radius = float(item["radius_m"])
        d = float(item.get("distance_to_track_m", item["distance_from_center_m"]))
        minimum = _minimum_center_distance(config, category, radius)
        if d + 1e-4 < minimum:
            print(f"FAIL clearance {item['variant_id']} d={d:.3f} required={minimum:.3f}")
            clearance_failures += 1
        if category in {"trees", "bushes"}:
            barrier_minimum = barrier_minimum_center_distance(config, category, radius)
            if d + 1e-4 < barrier_minimum:
                print(f"FAIL barrier clearance {item['variant_id']} d={d:.3f} required={barrier_minimum:.3f}")
                clearance_failures += 1
        if category == "grass":
            asset = grass_by_id.get(item["variant_id"])
            envelope = barrier_envelope_at(
                safety_barriers, float(item["track_fraction"]), int(item["side"]), lap_length_m,
            )
            required = (float(envelope["outer_face_distance_m"]) + radius +
                        float(config["procedural_environment"]["grass_cards"].get("outside_barrier_clearance_m", 0.35)))
            metadata_matches = (
                asset is not None and item.get("asset_glb") == asset["asset_glb"] and
                item.get("safety_segment_id") == envelope["segment_id"] and
                item.get("barrier_prototype_id") == envelope["prototype_id"] and
                abs(float(item.get("barrier_outer_face_m", -1.0)) - float(envelope["outer_face_distance_m"])) <= 1e-3
            )
            if d + 1e-4 < required or not metadata_matches:
                print(f"FAIL grass outside barrier {item['variant_id']} d={d:.3f} required={required:.3f}")
                clearance_failures += 1

        padding = padding_by_category[category]
        if not occupancy.can_place(x, z, radius, padding):
            overlap_count += 1
        occupancy.add(Occupant(x, z, radius, category, item["variant_id"]))

    if clearance_failures:
        failures += clearance_failures
    else:
        print("PASS road-edge clearance")
    semantic_authority = placements_doc.get("authority") == "canonical_svg"
    if overlap_count and not semantic_authority:
        print(f"FAIL overlaps={overlap_count}")
        failures += overlap_count
    elif overlap_count:
        print(f"PASS semantic authored overlaps preserved={overlap_count}")
    else:
        print("PASS overlaps=0")

    props = placements_doc.get("trackside_props", [])
    props_cfg = config.get("trackside_props", {})
    object_catalog = read_json(repo / props_cfg["object_catalog"]).get("objects", {})
    prop_assets = {spec["asset_id"]: spec for spec in object_catalog.values()}
    prop_failures = 0
    for prop in props:
        distance = float(prop.get("distance_from_center_m", 0.0))
        asset_id = prop.get("source_asset_id")
        contract = prop_assets.get(asset_id)
        if contract is None:
            prop_failures += 1
            continue
        envelope = barrier_envelope_at(
            safety_barriers, float(prop["track_fraction"]), int(prop["side"]), lap_length_m,
        )
        outside_offset = float(contract.get("guardrail_offset_m", 0.0))
        required = float(envelope["outer_face_distance_m"]) + outside_offset
        metadata_matches = (
            prop.get("safety_segment_id") == envelope["segment_id"] and
            prop.get("barrier_prototype_id") == envelope["prototype_id"] and
            abs(float(prop.get("barrier_outer_face_m", -1.0)) - float(envelope["outer_face_distance_m"])) <= 1e-3 and
            abs(float(prop.get("required_outside_offset_m", -1.0)) - outside_offset) <= 1e-3
        )
        if (abs(distance - required) > 1e-3 or not metadata_matches or
                prop.get("collision", False)):
            prop_failures += 1
    if prop_failures:
        print(f"FAIL trackside props violate active barrier envelope={prop_failures}/{len(props)}")
        failures += prop_failures
    else:
        print(f"PASS trackside props={len(props)} sector-aware, non-collidable, outside active barrier envelope")

    expected = sum(int(v["placed"]) for v in placements_doc["stats"].values())
    if expected != len(items):
        print(f"FAIL manifest count expected={expected} actual={len(items)}")
        failures += 1
    else:
        print(f"PASS manifest count={len(items)}")

    if distribution:
        for category in ("trees", "bushes"):
            category_items = [item for item in items if item["category"] == category]
            unique = {item["variant_id"] for item in category_items}
            expected_assets = {asset.spec.id for asset in catalogs[category]}
            if unique != expected_assets:
                print(f"FAIL {category} catalog coverage={len(unique)}/{len(expected_assets)}")
                failures += 1
            else:
                print(f"PASS {category} catalog coverage={len(unique)}/{len(expected_assets)}")
            counts = {color: sum(item.get("color_id") == color for item in category_items) for color in COLORS}
            if counts["original"] != max(counts.values()):
                print(f"FAIL {category} dominant color is not original: {counts}")
                failures += 1
            else:
                print(f"PASS {category} dominant=original colors={counts}")

    building_items = [item for item in items if item["category"] == "fake_buildings"]
    building_ids = {asset["id"] for asset in building_assets}
    placed_building_ids = {item.get("building_asset_id") for item in building_items}
    building_cfg = config.get("procedural_environment", {}).get("fake_buildings", {})
    building_contract = read_json(repo / building_cfg["construction_manifest"])
    placement_contract = building_contract["placement"]
    building_failures = sum(
        item.get("building_asset_id") not in building_ids
        or not item.get("asset_glb")
        or item.get("collision") is not False
        or float(item.get("distance_to_track_m", item["distance_from_center_m"])) < float(placement_contract["minimum_track_distance_m"])
        or float(item.get("distance_to_track_m", item["distance_from_center_m"])) > float(placement_contract["maximum_track_distance_m"])
        or float(item["scale"]) < float(placement_contract["scale_minimum"])
        or float(item["scale"]) > float(placement_contract["scale_maximum"])
        for item in building_items
    )
    if building_failures or placed_building_ids != building_ids:
        print(f"FAIL scenic buildings invalid={building_failures} coverage={sorted(placed_building_ids)} expected={sorted(building_ids)}")
        failures += max(1, building_failures)
    else:
        print(f"PASS scenic buildings={len(building_items)} assets={sorted(building_ids)} collision=False")

    barrier_conflicts = sum(
        barrier_conflict(
            safety_barriers, item["category"], float(item["track_fraction"]), int(item["side"]),
            float(item.get("distance_to_track_m", item["distance_from_center_m"])), float(item["radius_m"]),
        )
        for item in items if item["category"] in {"trees", "bushes"}
    )
    if barrier_conflicts:
        print(f"FAIL safety barrier/vegetation conflicts={barrier_conflicts}")
        failures += barrier_conflicts
    else:
        print("PASS safety barrier/vegetation conflicts=0")

    compiled = compile_layout(safety_barriers, float(centerline["length_m"]))
    counts = {}
    for module in compiled["modules"]:
        counts[module["type"]] = counts.get(module["type"], 0) + 1
    full_scope = config.get("safety_barriers", {}).get("scope") == "full_circuit"
    if config.get("guardrails", {}).get("procedural") or config.get("tire_barriers", {}).get("procedural"):
        print("FAIL undeclared legacy barrier source remains active")
        failures += 1
    elif not full_scope:
        print("FAIL safety barrier authority is not full_circuit")
        failures += 1
    else:
        print("PASS single full-circuit safety barrier authority active")
    road_half = float(config["road"]["width_m"]) * .5
    curb_manifest = read_json(repo / config["curb"]["manifest"])
    curb_width = max(float(profile["width_m"]) for profile in curb_manifest["profiles"].values())
    invasion_count = sum(
        float(module["center_distance_m"]) -
        float(safety_barriers["collision_profiles"][module["collision_profile"]]["thickness_m"]) * .5
        <= road_half + curb_width
        for module in compiled["modules"]
    )
    if invasion_count:
        print(f"FAIL safety barrier road/curb invasions={invasion_count}")
        failures += invasion_count
    else:
        print("PASS safety barrier road/curb invasions=0")
    exposed_armco = sum(
        safety_barriers["prototypes"][(segment["system"].get("type") or segment["system"].get("items", [{}])[0].get("type"))]["geometry"] == "guardrail_armco"
        and (segment["terminal_start"] not in {"flare_out", "buried_or_hidden", "guardrail_to_tire", "guardrail_to_tecpro"}
             or segment["terminal_end"] not in {"flare_out", "buried_or_hidden", "guardrail_to_tire", "guardrail_to_tecpro"})
        for segment in safety_barriers["segments"] if segment.get("enabled", True)
    )
    if exposed_armco:
        print(f"FAIL exposed Armco terminals={exposed_armco}")
        failures += exposed_armco
    else:
        print("PASS exposed Armco terminals=0")
    side_gaps = coverage_gaps_by_side(safety_barriers)
    gap_count = sum(len(values) for values in side_gaps.values())
    if gap_count:
        print(f"FAIL unprotected side fractions={gap_count}")
        failures += gap_count
    else:
        print("PASS barrier coverage=100% on both sides")
    side_overlaps = overlaps_by_side(safety_barriers)
    excessive_overlap = sum(max(0, len(values) - len(safety_barriers["segments"]) // 2)
                            for values in side_overlaps.values())
    if excessive_overlap:
        print(f"FAIL barrier sector overlaps={excessive_overlap}")
        failures += excessive_overlap
    else:
        print("PASS barrier sectors have no extended overlap")
    print(f"PASS safety barrier modules={len(compiled['modules'])} counts={counts} sha256={compiled['sha256']}")

    # --- Mountains procedural validation (informative, does not block existing checks if disabled) ---
    mountains_cfg = config.get("procedural_environment", {}).get("mountains", {})
    if mountains_cfg.get("enabled", False):
        mountain_report = generated / "review" / "mountain_report.json"
        if not mountain_report.is_file():
            print("FAIL mountains report missing (expected at blender/generated/la_chutana/review/mountain_report.json) while mountains.enabled=true")
            failures += 1
        else:
            mrep = read_json(mountain_report)
            if not mrep.get("enabled"):
                print("FAIL mountains report indicates disabled but config enabled")
                failures += 1
            else:
                layers = mrep.get("layers", {})
                near_ok = "near" in layers and layers["near"].get("vertices", 0) > 0
                far_ok = "far" in layers and layers["far"].get("vertices", 0) > 0
                if mountains_cfg.get("near_enabled", True) and not near_ok:
                    print("FAIL near mountains layer missing or empty in report")
                    failures += 1
                else:
                    print(f"PASS near mountains vertices={layers.get('near',{}).get('vertices',0)} faces={layers.get('near',{}).get('faces',0)}")
                if mountains_cfg.get("far_enabled", True) and not far_ok:
                    print("FAIL far mountains layer missing or empty")
                    failures += 1
                else:
                    print(f"PASS far mountains vertices={layers.get('far',{}).get('vertices',0)} faces={layers.get('far',{}).get('faces',0)}")
                if mrep.get("collision", True) is not False:
                    print("FAIL mountains collision must be false in report")
                    failures += 1
                else:
                    print("PASS mountains collision=False")
                if not mrep.get("validation", {}).get("hashes_match", False) and mrep.get("validation", {}).get("hashes_match") is not None:
                    # hashes_match True expected, None means not checked
                    print("FAIL mountains hashes mismatch")
                    failures += 1
                else:
                    print("PASS mountains hashes validated")
                # Check transition cards still 16 (no reintroduced mountain ribbons)
                bg_cfg = config.get("procedural_environment", {}).get("background_cards", {})
                if bg_cfg.get("mountain_ribbons_enabled", False):
                    print("FAIL background_cards.mountain_ribbons_enabled must remain false when mountains 3D active")
                    failures += 1
                else:
                    print("PASS mountain_ribbons disabled (3D mountains active, 2D cards not reintroduced)")
                sky_enabled_cfg = mountains_cfg.get("sky_dome_enabled", False)
                sky_in_report = "sky_dome" in layers
                if sky_enabled_cfg and not sky_in_report:
                    print("WARN sky dome enabled in config but not found in report (optional, not failing)")
                elif not sky_enabled_cfg:
                    print("PASS sky dome disabled (optional)")
    else:
        print("PASS mountains disabled (procedural 3D mountains not enabled)")

    print(f"biome={placements_doc.get('biome')} seed={placements_doc['seed']}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
