from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SUPPORTED_GEOMETRY = {
    "guardrail_armco", "painted_tire_prism", "beveled_block",
    "continuous_wall", "jersey_profile",
}
SUPPORTED_TERMINALS = {
    "flare_out", "buried_or_hidden", "guardrail_to_tire",
    "guardrail_to_tecpro", "wall_to_tecpro", "jersey_end", "closed",
}
TERMINALS_BY_GEOMETRY = {
    "guardrail_armco": {"flare_out", "buried_or_hidden", "guardrail_to_tire", "guardrail_to_tecpro"},
    "painted_tire_prism": {"buried_or_hidden", "guardrail_to_tire", "wall_to_tecpro"},
    "beveled_block": {"buried_or_hidden", "guardrail_to_tecpro", "wall_to_tecpro"},
    "continuous_wall": {"closed", "buried_or_hidden", "wall_to_tecpro"},
    "jersey_profile": {"jersey_end", "closed", "buried_or_hidden"},
}


class SafetyBarrierLayoutError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SafetyBarrierLayoutError(message)


def stable_decision(track_id: str, seed: int, segment_id: str, side: str,
                    module_index: int, decision_kind: str) -> int:
    key = "\x1f".join((track_id, str(seed), segment_id, side,
                        str(module_index), decision_kind))
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def fraction_span(start: float, end: float) -> float:
    span = (end - start) % 1.0
    return 1.0 if abs(span) < 1e-12 and start != end else span


def fraction_in_span(value: float, start: float, end: float) -> bool:
    value %= 1.0
    start %= 1.0
    end %= 1.0
    if start <= end:
        return start <= value <= end
    return value >= start or value <= end


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    _require(manifest.get("schema_version") == 2, "Unsupported safety barrier schema")
    _require(bool(manifest.get("track_id")), "Missing track_id")
    _require(isinstance(manifest.get("seed"), int), "seed must be an integer")
    prototypes = manifest.get("prototypes", {})
    patterns = manifest.get("patterns", {})
    profiles = manifest.get("collision_profiles", {})
    _require(bool(prototypes), "No safety barrier prototypes")
    for prototype_id, prototype in prototypes.items():
        _require(prototype.get("geometry") in SUPPORTED_GEOMETRY,
                 f"Unsupported geometry: {prototype_id}")
        _require(float(prototype.get("module_length_m", 0)) > 0,
                 f"Invalid module length: {prototype_id}")
        _require(prototype.get("collision_profile") in profiles,
                 f"Unknown collision profile: {prototype_id}")
        _require(prototype.get("material_style") in patterns,
                 f"Unknown pattern: {prototype_id}")

    seen: set[str] = set()
    for segment in manifest.get("segments", []):
        segment_id = segment.get("id")
        _require(bool(segment_id) and segment_id not in seen,
                 f"Duplicate or missing segment id: {segment_id}")
        seen.add(segment_id)
        _require(segment.get("side") in {"left", "right"},
                 f"Invalid side: {segment_id}")
        for field in ("start_fraction", "end_fraction"):
            value = segment.get(field)
            _require(isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0,
                     f"Invalid {field}: {segment_id}")
        _require(float(segment.get("center_distance_m", 0)) > 0,
                 f"Invalid center distance: {segment_id}")
        _require(segment.get("terminal_start") in SUPPORTED_TERMINALS,
                 f"Invalid start terminal: {segment_id}")
        _require(segment.get("terminal_end") in SUPPORTED_TERMINALS,
                 f"Invalid end terminal: {segment_id}")
        system = segment.get("system", {})
        _require(system.get("mode") in {"single", "sequence"},
                 f"Invalid system mode: {segment_id}")
        if system.get("mode") == "single":
            _require(system.get("type") in prototypes,
                     f"Unknown prototype: {segment_id}")
        else:
            items = system.get("items", [])
            _require(bool(items), f"Empty sequence: {segment_id}")
            for item in items:
                _require(item.get("type") in prototypes,
                         f"Unknown sequence prototype: {segment_id}")
                _require(float(item.get("length_m", 0)) > 0,
                         f"Invalid sequence length: {segment_id}")
        first_type = system.get("type") if system.get("mode") == "single" else system["items"][0]["type"]
        last_type = system.get("type") if system.get("mode") == "single" else system["items"][-1]["type"]
        first_geometry = prototypes[first_type]["geometry"]
        last_geometry = prototypes[last_type]["geometry"]
        _require(segment["terminal_start"] in TERMINALS_BY_GEOMETRY[first_geometry],
                 f"Incompatible start terminal: {segment_id}")
        _require(segment["terminal_end"] in TERMINALS_BY_GEOMETRY[last_geometry],
                 f"Incompatible end terminal: {segment_id}")
    return manifest


def load_safety_barrier_layout(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    relative = config.get("safety_barriers", {}).get("manifest")
    if not relative:
        raise SafetyBarrierLayoutError("Missing safety_barriers.manifest")
    with (repo / relative).open("r", encoding="utf-8") as handle:
        return validate_manifest(json.load(handle))


def _module_record(manifest: dict[str, Any], segment: dict[str, Any], prototype_id: str,
                   module_index: int, distance_m: float, length_m: float,
                   lap_length_m: float) -> dict[str, Any]:
    prototype = manifest["prototypes"][prototype_id]
    start = float(segment["start_fraction"])
    fraction = (start + (distance_m + length_m * 0.5) / lap_length_m) % 1.0
    phase = stable_decision(manifest["track_id"], manifest["seed"], segment["id"],
                            segment["side"], module_index, "pattern_phase")
    variation = stable_decision(manifest["track_id"], manifest["seed"], segment["id"],
                                segment["side"], module_index, "visual_variation")
    return {
        "segment_id": segment["id"], "module_index": module_index,
        "type": prototype_id, "side": segment["side"],
        "fraction": round(fraction, 12),
        "center_distance_m": float(segment["center_distance_m"]),
        "length_m": round(length_m, 6),
        "collision_profile": prototype["collision_profile"],
        "material_style": prototype["material_style"],
        "pattern_phase": phase % 4096,
        "visual_variation": variation % 2,
    }


def compile_layout(manifest: dict[str, Any], lap_length_m: float) -> dict[str, Any]:
    validate_manifest(manifest)
    _require(lap_length_m > 0, "Invalid lap length")
    modules: list[dict[str, Any]] = []
    compiled_segments: list[dict[str, Any]] = []
    for segment in manifest["segments"]:
        if not segment.get("enabled", True):
            continue
        span_m = fraction_span(float(segment["start_fraction"]),
                               float(segment["end_fraction"])) * lap_length_m
        system = segment["system"]
        items = ([{"type": system["type"], "length_m": span_m}]
                 if system["mode"] == "single" else list(system["items"]))
        repeat = system["mode"] == "single" or bool(system.get("repeat", False))
        distance = 0.0
        item_index = 0
        segment_modules: list[dict[str, Any]] = []
        while distance < span_m - 1e-6:
            if item_index >= len(items):
                if not repeat:
                    break
                item_index = 0
            item = items[item_index]
            prototype_id = item["type"]
            item_remaining = min(float(item["length_m"]), span_m - distance)
            module_length = float(manifest["prototypes"][prototype_id]["module_length_m"])
            while item_remaining > 1e-6:
                length = min(module_length, item_remaining)
                record = _module_record(manifest, segment, prototype_id,
                                        len(segment_modules), distance, length,
                                        lap_length_m)
                segment_modules.append(record)
                modules.append(record)
                distance += length
                item_remaining -= length
            item_index += 1
        _require(span_m - distance <= 0.25,
                 f"Undeclared barrier gap exceeds 0.25m: {segment['id']}")
        compiled_segments.append({
            **segment, "span_m": round(span_m, 6),
            "compiled_length_m": round(distance, 6),
            "module_count": len(segment_modules),
        })
    canonical = json.dumps(modules, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 2, "track_id": manifest["track_id"],
        "seed": manifest["seed"], "segments": compiled_segments,
        "modules": modules,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def barrier_envelope_at(manifest: dict[str, Any], fraction: float, side: int,
                        lap_length_m: float) -> dict[str, Any]:
    """Resolve the active barrier and its outer collision face at a lap position."""
    validate_manifest(manifest)
    _require(lap_length_m > 0, "Invalid lap length")
    side_name = "right" if side > 0 else "left"
    segment = next((entry for entry in manifest["segments"]
                    if entry.get("enabled", True) and entry["side"] == side_name
                    and fraction_in_span(fraction, float(entry["start_fraction"]),
                                         float(entry["end_fraction"]))), None)
    if segment is None:
        raise SafetyBarrierLayoutError(
            f"No active safety barrier at fraction={fraction:.7f} side={side_name}"
        )
    system = segment["system"]
    if system["mode"] == "single":
        prototype_id = system["type"]
    else:
        items = system["items"]
        cycle_m = sum(float(item["length_m"]) for item in items)
        local_m = ((float(fraction) - float(segment["start_fraction"])) % 1.0) * lap_length_m
        cursor = local_m % cycle_m if system.get("repeat", False) else local_m
        prototype_id = items[-1]["type"]
        for item in items:
            length_m = float(item["length_m"])
            if cursor < length_m:
                prototype_id = item["type"]
                break
            cursor -= length_m
    prototype = manifest["prototypes"][prototype_id]
    profile = manifest["collision_profiles"][prototype["collision_profile"]]
    center_distance = float(segment["center_distance_m"])
    thickness = float(profile["thickness_m"])
    return {
        "segment_id": segment["id"], "side": side_name,
        "prototype_id": prototype_id,
        "center_distance_m": center_distance,
        "collision_thickness_m": thickness,
        "outer_face_distance_m": center_distance + thickness * 0.5,
    }


def barrier_conflict(manifest: dict[str, Any], category: str, fraction: float,
                     side: int, distance: float, radius: float) -> bool:
    side_name = "right" if side > 0 else "left"
    default_clearance = manifest.get("defaults", {}).get("vegetation_clearance_m", {})
    for segment in manifest.get("segments", []):
        if not segment.get("enabled", True) or segment.get("side") != side_name:
            continue
        if not fraction_in_span(fraction, float(segment["start_fraction"]),
                                float(segment["end_fraction"])):
            continue
        clearance = segment.get("vegetation_clearance_m", default_clearance)
        required = float(clearance.get(category, 0.0))
        if abs(float(distance) - float(segment["center_distance_m"])) < radius + required:
            return True
    return False


def exterior_coverage_gaps(manifest: dict[str, Any], samples: int = 2000) -> list[float]:
    """Return sampled lap fractions with no declared barrier on either side.

    This is a gameplay containment check, not a requirement to place barriers on
    both sides or to build one visually continuous perimeter.
    """
    active = [segment for segment in manifest.get("segments", []) if segment.get("enabled", True)]
    return [
        index / samples for index in range(samples)
        if not any(fraction_in_span(index / samples, float(segment["start_fraction"]),
                                    float(segment["end_fraction"]))
                   for segment in active)
    ]


def coverage_gaps_by_side(manifest: dict[str, Any], samples: int = 2000) -> dict[str, list[float]]:
    active = [segment for segment in manifest.get("segments", []) if segment.get("enabled", True)]
    return {
        side: [index / samples for index in range(samples) if not any(
            segment["side"] == side and fraction_in_span(
                index / samples, float(segment["start_fraction"]), float(segment["end_fraction"])
            ) for segment in active
        )]
        for side in ("left", "right")
    }


def overlaps_by_side(manifest: dict[str, Any], samples: int = 2000) -> dict[str, list[float]]:
    active = [segment for segment in manifest.get("segments", []) if segment.get("enabled", True)]
    return {
        side: [index / samples for index in range(samples) if sum(
            segment["side"] == side and fraction_in_span(
                index / samples, float(segment["start_fraction"]), float(segment["end_fraction"])
            ) for segment in active
        ) > 1]
        for side in ("left", "right")
    }
