from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class CurbManifestError(ValueError):
    pass


def load_curb_manifest(config_path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    repo = config_path.parents[3]
    relative = config.get("curb", {}).get("manifest")
    if not relative:
        raise CurbManifestError("Track config is missing curb.manifest")
    path = repo / relative
    if not path.exists():
        raise CurbManifestError(f"Curb manifest does not exist: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_curb_manifest(manifest)
    validate_curb_assignments(config.get("curb", {}).get("segments", []), manifest)
    return manifest


def validate_curb_manifest(manifest: dict[str, Any]) -> None:
    if int(manifest.get("schema_version", 0)) != 1:
        raise CurbManifestError("Unsupported curb manifest schema_version")
    palette = manifest.get("palette", {})
    patterns = manifest.get("patterns", {})
    profiles = manifest.get("profiles", {})
    if not palette or not patterns or set(profiles) != {"flat", "raised", "sausage"}:
        raise CurbManifestError("Curb manifest must define palette, patterns, and flat/raised/sausage profiles")

    for material_id, material in palette.items():
        color = material.get("color", [])
        if len(color) != 3 or not all(0.0 <= float(channel) <= 1.0 for channel in color):
            raise CurbManifestError(f"Invalid curb palette color: {material_id}")

    for pattern_id, pattern in patterns.items():
        sequence = pattern.get("sequence", [])
        stripe_length = float(pattern.get("stripe_length_m", 0.0))
        if pattern.get("axis") != "longitudinal" or stripe_length <= 0.0 or len(sequence) < 2:
            raise CurbManifestError(f"Invalid curb pattern: {pattern_id}")
        for material_id in sequence:
            if material_id not in palette:
                raise CurbManifestError(f"Unknown curb material in pattern {pattern_id}: {material_id}")

    expected_usage = {"flat": "medium_speed", "raised": "high_speed", "sausage": "chicane"}
    for profile_id, profile in profiles.items():
        if profile.get("usage") != expected_usage[profile_id]:
            raise CurbManifestError(f"Unexpected usage for curb profile: {profile_id}")
        width = float(profile.get("width_m", 0.0))
        if not math.isclose(width, 1.508, abs_tol=1e-6):
            raise CurbManifestError(f"Curb profile must be exactly 1.508 m wide: {profile_id}")
        if float(profile.get("base_depth_m", 0.0)) <= 0.0:
            raise CurbManifestError(f"Curb profile needs positive base depth: {profile_id}")
        if profile.get("pattern") not in patterns:
            raise CurbManifestError(f"Unknown pattern for curb profile: {profile_id}")
        points = profile.get("points", [])
        if len(points) < 3 or not math.isclose(float(points[0][0]), 0.0, abs_tol=1e-6):
            raise CurbManifestError(f"Invalid curb profile start: {profile_id}")
        if not math.isclose(float(points[-1][0]), width, abs_tol=1e-6):
            raise CurbManifestError(f"Curb profile does not end at width_m: {profile_id}")
        max_height = float(profile["limits"]["max_height_m"])
        max_slope = float(profile["limits"]["max_abs_slope"])
        previous_x = -1.0
        for index, point in enumerate(points):
            x, height = map(float, point)
            if x <= previous_x or height < 0.0 or height > max_height:
                raise CurbManifestError(f"Invalid curb profile point {index}: {profile_id}")
            previous_x = x
        for left, right in zip(points, points[1:]):
            run = float(right[0]) - float(left[0])
            slope = abs((float(right[1]) - float(left[1])) / run)
            if slope > max_slope + 1e-6:
                raise CurbManifestError(f"Curb profile slope exceeds limit: {profile_id}")


def validate_curb_assignments(segments: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    profiles = manifest["profiles"]
    occupied: dict[str, list[tuple[float, float, str]]] = {"left": [], "right": []}
    names: set[str] = set()
    for segment in segments:
        name = str(segment.get("name", ""))
        side = str(segment.get("side", ""))
        profile_id = str(segment.get("profile_id", ""))
        zone = str(segment.get("zone", ""))
        start = float(segment.get("start_fraction", -1.0))
        end = float(segment.get("end_fraction", -1.0))
        if not name or name in names:
            raise CurbManifestError(f"Duplicate or empty curb segment name: {name}")
        names.add(name)
        if side not in occupied or profile_id not in profiles or not (0.0 <= start < end <= 1.0):
            raise CurbManifestError(f"Invalid curb assignment: {name}")
        if profiles[profile_id]["usage"] != zone:
            raise CurbManifestError(f"Curb zone/profile mismatch: {name}")
        for other_start, other_end, other_name in occupied[side]:
            if max(start, other_start) < min(end, other_end):
                raise CurbManifestError(f"Overlapping curb assignments on {side}: {other_name}/{name}")
        occupied[side].append((start, end, name))


def material_for_longitudinal(pattern: dict[str, Any], distance_m: float) -> str:
    stripe_length = float(pattern["stripe_length_m"])
    sequence = pattern["sequence"]
    stripe_index = int(math.floor(max(0.0, float(distance_m)) / stripe_length))
    return str(sequence[stripe_index % len(sequence)])
