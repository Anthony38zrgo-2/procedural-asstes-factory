from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class NearestTrackSample:
    distance_m: float
    fraction: float
    side: float
    signed_offset_m: float


@dataclass
class SegmentSpatialIndex:
    points: list[tuple[float, float]]
    cell_size: float
    cells: dict[tuple[int, int], list[int]]

    @classmethod
    def build(cls, points: Sequence[Sequence[float]], cell_size: float = 32.0) -> "SegmentSpatialIndex":
        pts = [(float(p[0]), float(p[1])) for p in points]
        cells: dict[tuple[int, int], list[int]] = {}
        n = len(pts)
        for i in range(n):
            ax, az = pts[i]
            bx, bz = pts[(i + 1) % n]
            min_x, max_x = sorted((ax, bx))
            min_z, max_z = sorted((az, bz))
            ix0 = math.floor(min_x / cell_size)
            ix1 = math.floor(max_x / cell_size)
            iz0 = math.floor(min_z / cell_size)
            iz1 = math.floor(max_z / cell_size)
            for ix in range(ix0, ix1 + 1):
                for iz in range(iz0, iz1 + 1):
                    cells.setdefault((ix, iz), []).append(i)
        return cls(pts, float(cell_size), cells)

    def candidates(self, x: float, z: float, radius_m: float) -> set[int]:
        r = max(float(radius_m), self.cell_size)
        ix0 = math.floor((x - r) / self.cell_size)
        ix1 = math.floor((x + r) / self.cell_size)
        iz0 = math.floor((z - r) / self.cell_size)
        iz1 = math.floor((z + r) / self.cell_size)
        result: set[int] = set()
        for ix in range(ix0, ix1 + 1):
            for iz in range(iz0, iz1 + 1):
                result.update(self.cells.get((ix, iz), ()))
        return result


def _smoothstep01(value: float) -> float:
    t = min(1.0, max(0.0, float(value)))
    return t * t * (3.0 - 2.0 * t)


def bank_degrees_at_fraction(config: dict, fraction: float) -> float:
    result = 0.0
    f = float(fraction) % 1.0
    for zone in config.get("banking", []):
        center = float(zone["center_fraction"]) % 1.0
        half = max(float(zone["half_width_fraction"]), 1e-6)
        d = abs((f - center + 0.5) % 1.0 - 0.5)
        if d <= half:
            weight = 0.5 * (1.0 + math.cos(math.pi * d / half))
            result += float(zone["degrees"]) * weight
    return result


def effective_far_ground_z(config: dict) -> float:
    road_half = float(config["road"]["width_m"]) * 0.5
    surface_z = float(config["road"].get("surface_elevation_m", 0.025))
    requested = float(config.get("terrain", {}).get("far_ground_z_m", -0.10))
    max_bank = max((abs(float(zone.get("degrees", 0.0))) for zone in config.get("banking", [])), default=0.0)
    lowest_banked_edge = surface_z - math.tan(math.radians(max_bank)) * road_half
    safety = float(config.get("terrain", {}).get("far_ground_safety_m", 0.05))
    return min(requested, lowest_banked_edge - safety)


def nearest_track_sample(index: SegmentSpatialIndex, x: float, z: float, search_radius_m: float) -> NearestTrackSample | None:
    candidates = index.candidates(float(x), float(z), search_radius_m)
    if not candidates:
        return None

    best_d2 = float("inf")
    best_fraction = 0.0
    best_side = 1.0
    best_signed = 0.0
    n = len(index.points)

    for i in candidates:
        ax, az = index.points[i]
        bx, bz = index.points[(i + 1) % n]
        vx, vz = bx - ax, bz - az
        denom = vx * vx + vz * vz
        if denom <= 1e-12:
            continue
        t = ((x - ax) * vx + (z - az) * vz) / denom
        t = max(0.0, min(1.0, t))
        qx, qz = ax + vx * t, az + vz * t
        dx, dz = x - qx, z - qz
        d2 = dx * dx + dz * dz
        if d2 >= best_d2:
            continue

        length = math.sqrt(denom)
        tx, tz = vx / length, vz / length
        nx, nz = tz, -tx
        signed = dx * nx + dz * nz
        best_d2 = d2
        best_fraction = (i + t) / n
        best_side = 1.0 if signed >= 0.0 else -1.0
        best_signed = signed

    if not math.isfinite(best_d2):
        return None
    return NearestTrackSample(math.sqrt(best_d2), best_fraction % 1.0, best_side, best_signed)


def elevation_at_fraction(config: dict, fraction: float) -> float:
    """Return the terrain elevation offset (metres) at a centerline fraction.

    Elevation controls are stored against centerline arc-length ``s_m``; they are
    converted to fractions of the total centerline length and interpolated
    linearly around the closed loop. Legacy configs without an ``elevation`` key
    (or with a non-positive length) yield a zero offset, so existing raster
    pipelines are unaffected.
    """
    elevation = config.get("elevation") or []
    length = float(config.get("centerline_length_m", 0.0) or 0.0)
    if not elevation or length <= 0.0:
        return 0.0
    controls = sorted(
        ((float(e["s_m"]) % length) / length, float(e["height_m"]))
        for e in elevation
    )
    if len(controls) == 1:
        return controls[0][1]
    f = float(fraction) % 1.0
    wrapped = controls + [(c[0] + 1.0, c[1]) for c in controls]
    lo = wrapped[0]
    for hi in wrapped[1:]:
        if lo[0] <= f <= hi[0]:
            if hi[0] - lo[0] <= 1e-12:
                return lo[1]
            t = (f - lo[0]) / (hi[0] - lo[0])
            return lo[1] * (1.0 - t) + hi[1] * t
        lo = hi
    return controls[-1][1]


def road_surface_height(config: dict, fraction: float, signed_offset_m: float) -> float:
    surface_z = float(config["road"].get("surface_elevation_m", 0.025))
    bank = math.radians(bank_degrees_at_fraction(config, fraction))
    return surface_z + math.tan(bank) * float(signed_offset_m) + elevation_at_fraction(config, fraction)


def terrain_height_from_sample(config: dict, sample: NearestTrackSample | None, *, visual: bool = False) -> float:
    """Return terrain height for a point near the track.

    Collision terrain is a continuous underlay below the road instead of a grid with
    deleted road cells. It rises to the exact road-edge height at the boundary, then
    becomes the grass/runoff surface. This prevents gaps between separate imported
    concave meshes. The visual terrain is pushed further below the road and blended
    back outside the edge, preventing coarse grid triangles from visibly clipping
    through asphalt.
    """
    terrain = config.get("terrain", {})
    far_z = effective_far_ground_z(config)
    if sample is None:
        return far_z - (float(terrain.get("visual_sink_m", 0.003)) if visual else 0.0)

    road_half = float(config["road"]["width_m"]) * 0.5
    shoulder_width = max(float(terrain.get("shoulder_falloff_m", 18.0)), 0.1)
    distance = float(sample.distance_m)

    if distance <= road_half:
        road_h = road_surface_height(config, sample.fraction, sample.signed_offset_m)
        inside = road_half - distance
        if visual:
            drop = max(0.0, float(terrain.get("visual_under_road_drop_m", 0.22)))
            blend = max(0.05, float(terrain.get("visual_under_road_blend_m", 1.4)))
        else:
            drop = max(0.0, float(terrain.get("collision_underlay_drop_m", 0.12)))
            blend = max(0.05, float(terrain.get("collision_underlay_blend_m", 1.0)))
        return road_h - drop * _smoothstep01(inside / blend)

    edge_signed = road_half * sample.side
    edge_height = road_surface_height(config, sample.fraction, edge_signed)
    outside = distance - road_half
    t = _smoothstep01(outside / shoulder_width)
    height = edge_height * (1.0 - t) + far_z * t

    if visual:
        sink = max(0.0, float(terrain.get("visual_sink_m", 0.003)))
        edge_blend = max(0.05, float(terrain.get("visual_edge_blend_m", 1.25)))
        under_edge = max(0.0, float(terrain.get("visual_under_road_drop_m", 0.22)))
        height -= sink + under_edge * (1.0 - _smoothstep01(outside / edge_blend))
    return height


def build_heightfield(points: Sequence[Sequence[float]], config: dict, *, visual: bool = False) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], dict]:
    terrain = config.get("terrain", {})
    cell = max(2.0, float(terrain.get("grid_cell_m", 6.0)))
    margin = max(20.0, float(terrain.get("far_ground_margin_m", 220.0)))
    road_half = float(config["road"]["width_m"]) * 0.5
    shoulder_width = max(float(terrain.get("shoulder_falloff_m", 18.0)), 0.1)

    pts = [(float(p[0]), float(p[1])) for p in points]
    min_x = math.floor((min(p[0] for p in pts) - margin) / cell) * cell
    max_x = math.ceil((max(p[0] for p in pts) + margin) / cell) * cell
    min_z = math.floor((min(p[1] for p in pts) - margin) / cell) * cell
    max_z = math.ceil((max(p[1] for p in pts) + margin) / cell) * cell

    nx = int(round((max_x - min_x) / cell)) + 1
    nz = int(round((max_z - min_z) / cell)) + 1
    index = SegmentSpatialIndex.build(pts, cell_size=max(24.0, cell * 4.0))
    influence = road_half + shoulder_width + cell * 2.0

    vertices: list[tuple[float, float, float]] = []
    for iz in range(nz):
        z = min_z + iz * cell
        for ix in range(nx):
            x = min_x + ix * cell
            sample = nearest_track_sample(index, x, z, influence)
            y = terrain_height_from_sample(config, sample, visual=visual)
            vertices.append((x, z, y))

    # Winding is chosen so after (x,z,height)->Blender(x,-z,height), normals point +Z.
    faces: list[tuple[int, int, int]] = []
    for iz in range(nz - 1):
        for ix in range(nx - 1):
            a = iz * nx + ix
            b = a + 1
            c = a + nx + 1
            d = a + nx
            faces.append((a, c, b))
            faces.append((a, d, c))

    stats = {
        "cell_m": cell,
        "vertices": len(vertices),
        "triangles": len(faces),
        "nx": nx,
        "nz": nz,
        "skipped_inside_quads": 0,
        "far_ground_z_m": effective_far_ground_z(config),
        "min_x": min_x,
        "max_x": max_x,
        "min_z": min_z,
        "max_z": max_z,
    }
    return vertices, faces, stats


def _blender_normal_z(vertices: Sequence[Sequence[float]], face: Sequence[int]) -> float:
    def conv(v):
        return float(v[0]), -float(v[1]), float(v[2])
    a, b, c = (conv(vertices[i]) for i in face)
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return ab[0] * ac[1] - ab[1] * ac[0]


def validate_heightfield(points: Sequence[Sequence[float]], config: dict) -> dict[str, object]:
    vertices, faces, stats = build_heightfield(points, config, visual=False)
    finite = all(all(math.isfinite(v) for v in vertex) for vertex in vertices)
    nondegenerate = True
    upward = True
    for ia, ib, ic in faces:
        ax, az, _ = vertices[ia]
        bx, bz, _ = vertices[ib]
        cx, cz, _ = vertices[ic]
        area2 = abs((bx - ax) * (cz - az) - (bz - az) * (cx - ax))
        if area2 <= 1e-9:
            nondegenerate = False
            break
        if _blender_normal_z(vertices, (ia, ib, ic)) <= 0.0:
            upward = False
            break

    road_half = float(config["road"]["width_m"]) * 0.5
    max_seam_error = 0.0
    samples = 128
    for i in range(samples):
        fraction = i / samples
        for side in (-1.0, 1.0):
            signed = road_half * side
            synthetic = NearestTrackSample(road_half, fraction, side, signed)
            terrain_h = terrain_height_from_sample(config, synthetic, visual=False)
            road_h = road_surface_height(config, fraction, signed)
            max_seam_error = max(max_seam_error, abs(terrain_h - road_h))

    safety_z = float(config.get("terrain", {}).get("safety_floor_z_m", -6.0))
    safety_thickness = float(config.get("terrain", {}).get("safety_floor_thickness_m", 0.6))
    return {
        **stats,
        "finite_vertices": finite,
        "nondegenerate_triangles": nondegenerate,
        "blender_winding_upward": upward,
        "continuous_collision_grid": stats["skipped_inside_quads"] == 0,
        "max_collision_seam_error_m": max_seam_error,
        "safety_floor_valid": safety_z < stats["far_ground_z_m"] - 1.0 and safety_thickness >= 0.2,
    }
