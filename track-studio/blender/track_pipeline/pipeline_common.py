from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import random
from typing import Sequence

import numpy as np
from scipy.interpolate import CubicSpline


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def reference_pixels_to_world(reference: dict) -> np.ndarray:
    finish_x, finish_y = reference["reference_finish_pixel"]
    sx = float(reference["meters_per_pixel_x"])
    sy = float(reference["meters_per_pixel_y"])
    points = []
    for px, py in reference["trace_pixels"]:
        x = (float(py) - finish_y) * sy
        z = -(float(px) - finish_x) * sx
        points.append((x, z))
    return np.asarray(points, dtype=float)


def closed_polyline_length(points: np.ndarray) -> float:
    shifted = np.roll(points, -1, axis=0)
    return float(np.linalg.norm(shifted - points, axis=1).sum())


def fit_periodic_centerline(points: np.ndarray, spacing_m: float) -> np.ndarray:
    if len(points) < 4:
        raise ValueError("At least four points are required for a closed periodic spline.")
    pts = np.asarray(points, dtype=float)
    closed = np.vstack([pts, pts[0]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    t = np.concatenate(([0.0], np.cumsum(seg)))
    if t[-1] <= 0:
        raise ValueError("Degenerate centerline.")
    cs_x = CubicSpline(t, closed[:, 0], bc_type="periodic")
    cs_z = CubicSpline(t, closed[:, 1], bc_type="periodic")

    dense_t = np.linspace(0.0, t[-1], max(2000, int(t[-1] / 0.25)), endpoint=False)
    dense = np.column_stack([cs_x(dense_t), cs_z(dense_t)])
    dense_closed = np.vstack([dense, dense[0]])
    dense_seg = np.linalg.norm(np.diff(dense_closed, axis=0), axis=1)
    dense_s = np.concatenate(([0.0], np.cumsum(dense_seg)))
    total = dense_s[-1]

    target_count = max(32, int(round(total / spacing_m)))
    target_s = np.linspace(0.0, total, target_count, endpoint=False)
    xsrc = np.concatenate([dense[:, 0], [dense[0, 0]]])
    zsrc = np.concatenate([dense[:, 1], [dense[0, 1]]])
    return np.column_stack([
        np.interp(target_s, dense_s, xsrc),
        np.interp(target_s, dense_s, zsrc),
    ])


def cumulative_lengths(points: np.ndarray) -> np.ndarray:
    closed = np.vstack([points, points[0]])
    return np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))))


def tangents_and_normals(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    prev = np.roll(points, 1, axis=0)
    nxt = np.roll(points, -1, axis=0)
    tangent = nxt - prev
    norm = np.linalg.norm(tangent, axis=1, keepdims=True)
    tangent = tangent / np.maximum(norm, 1e-9)
    normal = np.column_stack([tangent[:, 1], -tangent[:, 0]])
    return tangent, normal


def point_segment_distance(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom <= 1e-12:
        return float(np.linalg.norm(point - a))
    t = float(np.dot(point - a, ab) / denom)
    t = max(0.0, min(1.0, t))
    return float(np.linalg.norm(point - (a + t * ab)))


def min_distance_to_closed_polyline(point: Sequence[float], points: np.ndarray) -> float:
    p = np.asarray(point, dtype=float)
    best = float("inf")
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        best = min(best, point_segment_distance(p, a, b))
    return best


def segment_intersection(a, b, c, d) -> bool:
    def orient(p, q, r):
        return float((q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0]))
    o1, o2, o3, o4 = orient(a,b,c), orient(a,b,d), orient(c,d,a), orient(c,d,b)
    eps = 1e-9
    return ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps))


def count_self_intersections(points: np.ndarray) -> int:
    n = len(points)
    count = 0
    for i in range(n):
        a, b = points[i], points[(i+1) % n]
        for j in range(i+1, n):
            if j in {i, (i+1) % n} or (j+1) % n in {i, (i+1) % n}:
                continue
            if i == 0 and j == n-1:
                continue
            c, d = points[j], points[(j+1) % n]
            if segment_intersection(a,b,c,d):
                count += 1
    return count


def signed_curvature(points: np.ndarray) -> np.ndarray:
    prev = np.roll(points, 1, axis=0)
    nxt = np.roll(points, -1, axis=0)
    a = points - prev
    b = nxt - points
    la = np.linalg.norm(a, axis=1)
    lb = np.linalg.norm(b, axis=1)
    chord = np.linalg.norm(nxt - prev, axis=1)
    cross = a[:,0]*b[:,1] - a[:,1]*b[:,0]
    area2 = np.abs(cross)
    denom = np.maximum(la * lb * chord, 1e-9)
    k = 2.0 * area2 / denom
    return np.sign(cross) * k


def interpolate_at_fraction(points: np.ndarray, fraction: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fraction = float(fraction) % 1.0
    lengths = cumulative_lengths(points)
    total = lengths[-1]
    s = fraction * total
    idx = int(np.searchsorted(lengths, s, side="right") - 1)
    idx = min(idx, len(points)-1)
    local_len = lengths[idx+1] - lengths[idx]
    t = 0.0 if local_len <= 1e-9 else (s - lengths[idx]) / local_len
    a = points[idx]
    b = points[(idx+1) % len(points)]
    pos = a * (1.0-t) + b * t
    tangent = b - a
    tangent /= max(float(np.linalg.norm(tangent)), 1e-9)
    normal = np.asarray([tangent[1], -tangent[0]])
    return pos, tangent, normal


@dataclass(frozen=True)
class Occupant:
    x: float
    z: float
    radius: float
    category: str
    asset_id: str


class SpatialHash:
    def __init__(self, cell_size: float = 8.0):
        self.cell_size = float(cell_size)
        self.cells: dict[tuple[int,int], list[Occupant]] = {}

    def _cell(self, x: float, z: float) -> tuple[int,int]:
        return (math.floor(x/self.cell_size), math.floor(z/self.cell_size))

    def _near_cells(self, x: float, z: float, radius: float):
        cx, cz = self._cell(x,z)
        r = max(1, int(math.ceil(radius/self.cell_size)))
        for ix in range(cx-r, cx+r+1):
            for iz in range(cz-r, cz+r+1):
                yield (ix,iz)

    def can_place(self, x: float, z: float, radius: float, padding: float = 0.25) -> bool:
        query = radius + padding
        for cell in self._near_cells(x,z,query):
            for other in self.cells.get(cell, []):
                min_dist = radius + other.radius + padding
                if (x-other.x)**2 + (z-other.z)**2 < min_dist**2:
                    return False
        return True

    def add(self, occupant: Occupant) -> None:
        self.cells.setdefault(self._cell(occupant.x, occupant.z), []).append(occupant)


def stable_rng(seed: int, category: str) -> random.Random:
    salt = sum((i+1)*ord(ch) for i, ch in enumerate(category))
    return random.Random(int(seed) ^ salt)
