#!/usr/bin/env python3
"""Generate topographic terrain for Formula-90 backgrounds from semantic SVG.

Parses a semantic topographic SVG (with data-elevation, data-band, data-closed,
data-open attributes), validates contours, clips open contours against the terrain
boundary, and extrudes them to 3D geometry (inner face only, 360 ring) with
vertex colors by elevation band.

Usage:
    python generate_topo_terrain.py <svg_path> <output_dir>
"""

import argparse
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Polygon, LineString, Point, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid


# --- Configuration ---

SVG_NS = "http://www.w3.org/2000/svg"

# Band colors from SVG legend (for vertex colors)
BAND_COLORS = {
    "base":   [0xc0, 0xa0, 0x68],
    "lower":  [0xa0, 0x86, 0x58],
    "mid":    [0x80, 0x6c, 0x48],
    "upper":  [0x60, 0x53, 0x38],
    "summit": [0x40, 0x39, 0x28],
}

ELEV_THRESHOLDS = [0.0, 25.0, 50.0, 75.0, 100.0, 150.0]
COLOR_KEYS = ["base", "base", "lower", "mid", "upper", "summit"]


def interpolate_elevation_color(elevation: float) -> np.ndarray:
    """Interpolate vertex color smoothly based on continuous elevation."""
    if elevation <= 0.0:
        return np.array(BAND_COLORS["base"], dtype=np.float64)
    if elevation >= 150.0:
        return np.array(BAND_COLORS["summit"], dtype=np.float64)

    for idx in range(len(ELEV_THRESHOLDS) - 1):
        e0 = ELEV_THRESHOLDS[idx]
        e1 = ELEV_THRESHOLDS[idx + 1]
        if e0 <= elevation <= e1:
            t = (elevation - e0) / (e1 - e0)
            c0 = np.array(BAND_COLORS[COLOR_KEYS[idx]], dtype=np.float64)
            c1 = np.array(BAND_COLORS[COLOR_KEYS[idx + 1]], dtype=np.float64)
            return c0 * (1.0 - t) + c1 * t
    return np.array(BAND_COLORS["summit"], dtype=np.float64)


def smooth_circular_heightmap(heightmap: np.ndarray, sigma: float = 4.0) -> np.ndarray:
    """Apply Gaussian smoothing with circular boundary conditions (360-degree wrap-around)."""
    n = len(heightmap)
    extended = np.tile(heightmap, 3)
    smoothed = gaussian_filter1d(extended, sigma=sigma, mode="wrap")
    return smoothed[n:2 * n]


ELEVATION_ORDER = [0, 25, 50, 75, 100, 125, 150]
MIN_CONTOUR_AREA = 50.0
SIMPLIFY_TOLERANCE = 2.0
SEGMENTS_ANGULAR = 640

SKY_DOME_RADIUS = 1800.0
SKY_DOME_RINGS = 16
SKY_DOME_SEGMENTS = 64
ZENITH_COLOR = [0.18, 0.42, 0.82]
HORIZON_COLOR = [0.55, 0.68, 0.80]
GROUND_COLOR = [0.82, 0.70, 0.48]


# --- SVG Parsing ---

def parse_svg_path_d(d: str) -> list:
    """Parse SVG path d attribute into list of (x, y) points.

    Supports M, L, Z commands.
    """
    points = []
    tokens = re.findall(r'[MLZmlz]|[-+]?[0-9]*\.?[0-9]+', d)

    i = 0
    current_cmd = None
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            current_cmd = token
            i += 1
        elif current_cmd in ('M', 'L'):
            x = float(token)
            y = float(tokens[i + 1])
            points.append((x, y))
            i += 2
            if current_cmd == 'M':
                current_cmd = 'L'
        elif current_cmd == 'Z':
            i += 1
        else:
            i += 1

    return points


def parse_svg_contours(svg_path: str) -> tuple:
    """Parse semantic SVG and extract contour polygons by elevation.

    Returns (contours_by_elev, metadata, boundary_polygon).
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()

    terrain = root.find(f".//{{{SVG_NS}}}g[@id='terrain']")
    if terrain is None:
        raise ValueError("SVG missing #terrain group")

    metadata = {
        "height_scale": float(terrain.attrib.get("data-height-scale", "1.8")),
        "depth_scale": float(terrain.attrib.get("data-depth-scale", "0.7")),
        "distance": float(terrain.attrib.get("data-distance", "3000")),
        "layer": terrain.attrib.get("data-layer", "far"),
    }

    boundary_path = terrain.find(f".//{{{SVG_NS}}}path[@id='terrain_boundary']")
    if boundary_path is None:
        raise ValueError("SVG missing #terrain_boundary")
    boundary_points = parse_svg_path_d(boundary_path.attrib.get("d", ""))
    boundary_polygon = Polygon(boundary_points)
    if not boundary_polygon.is_valid:
        boundary_polygon = make_valid(boundary_polygon)

    contours_group = terrain.find(f".//{{{SVG_NS}}}g[@id='contours']")
    if contours_group is None:
        raise ValueError("SVG missing #contours group")

    contours_by_elev = {}
    total_paths = 0
    filtered_paths = 0

    for level_group in contours_group:
        elev = int(level_group.attrib.get("data-elevation", "0"))
        paths = level_group.findall(f"{{{SVG_NS}}}path")

        level_contours = []
        for path_el in paths:
            if path_el.attrib.get("data-ignore", "false") == "true":
                continue

            band = path_el.attrib.get("data-band", "base")
            is_closed = path_el.attrib.get("data-closed", "false") == "true"
            is_open = path_el.attrib.get("data-open", "false") == "true"

            d = path_el.attrib.get("d", "")
            points = parse_svg_path_d(d)

            if len(points) < 3:
                filtered_paths += 1
                continue

            total_paths += 1

            if is_open:
                points = clip_open_contour(points, boundary_polygon)
                if len(points) < 3:
                    filtered_paths += 1
                    continue

            try:
                poly = Polygon(points)
                if not poly.is_valid:
                    poly = make_valid(poly)
                    if poly.is_empty:
                        filtered_paths += 1
                        continue

                # Handle GeometryCollection from make_valid
                if isinstance(poly, (GeometryCollection, MultiPolygon)):
                    polygons = [g for g in poly.geoms if isinstance(g, Polygon)]
                    if not polygons:
                        filtered_paths += 1
                        continue
                    poly = max(polygons, key=lambda p: p.area)

                if not isinstance(poly, Polygon):
                    filtered_paths += 1
                    continue

                if poly.area < MIN_CONTOUR_AREA:
                    filtered_paths += 1
                    continue

                level_contours.append({
                    "points": points,
                    "polygon": poly,
                    "band": band,
                    "elevation": elev,
                    "is_closed": is_closed,
                })
            except Exception:
                filtered_paths += 1
                continue

        contours_by_elev[elev] = level_contours

    print(f"  Parsed {total_paths} contours, filtered {filtered_paths}")
    stats = {"source_contours": total_paths, "filtered": filtered_paths, "accepted": total_paths - filtered_paths}
    return contours_by_elev, metadata, boundary_polygon, stats


def clip_open_contour(points: list, boundary_polygon) -> list:
    """Clip an open contour against the terrain boundary.

    The contour touches the domain edge. We close it along the boundary by:
    1. Finding the real crossing points of the polyline with the boundary ring.
    2. Building the boundary arc between them in BOTH directions.
    3. Choosing the arc that yields the smaller in-domain polygon (the short arc),
       which is the correct topographic interpretation for a band touching the edge.
    """
    line = LineString(points)
    boundary_ring = boundary_polygon.boundary
    inter = line.intersection(boundary_ring)

    if inter.is_empty:
        return points

    # Collect real crossing points
    cross_pts = []
    if hasattr(inter, "geoms"):
        for g in inter.geoms:
            if hasattr(g, "coords"):
                cross_pts.append(g.coords[0])
    elif hasattr(inter, "coords"):
        cross_pts.append(inter.coords[0])

    if len(cross_pts) < 2:
        return points

    # Nearest crossing to each polyline end
    p_start = np.array(points[0])
    p_end = np.array(points[-1])
    s_idx = min(range(len(cross_pts)), key=lambda i: np.linalg.norm(np.array(cross_pts[i]) - p_start))
    e_idx = min(range(len(cross_pts)), key=lambda i: np.linalg.norm(np.array(cross_pts[i]) - p_end))
    if s_idx == e_idx:
        return points

    # Build both candidate closures and pick the smaller in-domain polygon
    bcoords = list(boundary_polygon.exterior.coords)[:-1]  # ring without duplicate closure
    n = len(bcoords)

    def nearest_boundary_idx(pt):
        return min(range(n), key=lambda i: np.linalg.norm(np.array(bcoords[i]) - pt))

    i_s = nearest_boundary_idx(np.array(cross_pts[s_idx]))
    i_e = nearest_boundary_idx(np.array(cross_pts[e_idx]))

    def boundary_arc(forward: bool) -> list:
        arc = []
        i = i_s
        while True:
            arc.append(tuple(bcoords[i % n]))
            if i % n == i_e:
                break
            i = i + 1 if forward else i - 1
        return arc

    candidates = []
    for forward in (True, False):
        arc = boundary_arc(forward)
        poly = Polygon(arc + points[::-1])
        if poly.is_valid and not poly.is_empty:
            in_domain = poly.intersection(boundary_polygon)
            if hasattr(in_domain, "geoms"):
                polys = [g for g in in_domain.geoms if isinstance(g, Polygon)]
                in_domain = max(polys, key=lambda p: p.area) if polys else None
            if in_domain is not None and not in_domain.is_empty:
                candidates.append(in_domain)

    if not candidates:
        return points

    # Choose the closure with the smallest area (short arc around the domain)
    best = min(candidates, key=lambda p: p.area)
    return list(best.exterior.coords)


# --- Contour Validation ---

def validate_contours(contours_by_elev: dict) -> dict:
    """Validate contours: no self-intersections, simplify if needed."""
    validated = {}

    for elev, contours in contours_by_elev.items():
        valid_contours = []
        for c in contours:
            poly = c["polygon"]

            if not poly.is_valid:
                poly = make_valid(poly)
                if poly.is_empty:
                    continue

            # make_valid may return GeometryCollection or MultiPolygon
            # Extract the largest Polygon
            if isinstance(poly, (GeometryCollection, MultiPolygon)):
                polygons = [g for g in poly.geoms if isinstance(g, Polygon)]
                if not polygons:
                    continue
                poly = max(polygons, key=lambda p: p.area)
                if poly.is_empty:
                    continue

            if not isinstance(poly, Polygon):
                continue

            if len(poly.exterior.coords) > 200:
                poly = poly.simplify(2.0, preserve_topology=True)

            c["polygon"] = poly
            c["points"] = list(poly.exterior.coords)
            valid_contours.append(c)

        validated[elev] = valid_contours

    return validated


# --- Radial Sampling ---

def _sample_point_elevation(svg_x: float, svg_y: float, contours_by_elev: dict,
                            tolerance: float = 0.5) -> tuple:
    """Return (elevation, band_color) for a single SVG point using data-elevation only.

    tolerance is in SVG units, proportional to the sampling step (default 0.5).
    """
    pt = Point(svg_x, svg_y)
    max_elev = 0
    best_color = BAND_COLORS["base"]
    for elev in ELEVATION_ORDER:
        if elev not in contours_by_elev:
            continue
        for c in contours_by_elev[elev]:
            poly = c["polygon"]
            if poly.contains(pt) or poly.distance(pt) < tolerance:
                if elev > max_elev:
                    max_elev = elev
                    best_color = BAND_COLORS.get(c["band"], BAND_COLORS["base"])
    return max_elev, best_color


def sample_contours_radial(contours_by_elev: dict, radius: float,
                           segments: int, svg_size: float,
                           height_scale: float, distance: float) -> tuple:
    """Sample contour elevations along a circular ring with continuous organic shaping.

    1. Samples raw discrete elevations from topographic contours.
    2. Fills continuous zero gaps.
    3. Applies circular Gaussian smoothing (sigma=4.5) to convert step staircases
       into continuous mountain slopes and valleys.
    4. Sharpens mountain apexes to preserve peak heights.
    5. Computes continuous color gradient from base sand to summit rock.

    Returns (heightmap, colormap) arrays.
    """
    angles = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    raw_elevations = np.zeros(segments)

    cx, cy = svg_size / 2, svg_size / 2
    svg_to_world = distance / svg_size

    for i, angle in enumerate(angles):
        ray_x = radius * np.cos(angle)
        ray_z = radius * np.sin(angle)

        svg_x = cx + ray_x / svg_to_world
        svg_y = cy + ray_z / svg_to_world

        max_elev, _ = _sample_point_elevation(svg_x, svg_y, contours_by_elev)
        raw_elevations[i] = max_elev

    raw_heightmap = raw_elevations * height_scale
    raw_heightmap = _fill_continuous_gaps(raw_heightmap, segments, height_scale)

    # 1. Circular smooth transition across 360 degrees (eliminates flat box steps)
    smoothed_heightmap = smooth_circular_heightmap(raw_heightmap, sigma=4.5)

    # 2. Apex / peak sharpening: preserve peak altitudes so summits remain towering
    peak_mask = raw_heightmap > (smoothed_heightmap * 1.05)
    final_heightmap = smoothed_heightmap.copy()
    final_heightmap[peak_mask] = np.maximum(smoothed_heightmap[peak_mask], raw_heightmap[peak_mask] * 0.95)
    # Re-smooth with light sigma=1.5 for seamless continuity
    final_heightmap = smooth_circular_heightmap(final_heightmap, sigma=1.5)

    # 3. Continuous colormap based on elevation gradient
    colormap = np.zeros((segments, 3), dtype=np.uint8)
    for i in range(segments):
        elev_equiv = final_heightmap[i] / max(height_scale, 0.001)
        col = interpolate_elevation_color(elev_equiv)
        colormap[i] = [int(np.clip(c, 0, 255)) for c in col]

    return final_heightmap, colormap


def _fill_continuous_gaps(heightmap: np.ndarray, segments: int,
                          height_scale: float = 1.0) -> np.ndarray:
    """Prevent continuous 80deg gaps: if a stretch of zeros > 40deg, keep variation.

    Ensures Near layer never disappears for a large sector.
    Uses 25m * height_scale as minimal visible height (ring-appropriate scale).
    """
    # Threshold: 40 deg ~ 71 segments (640*40/360)
    gap_threshold = int(segments * 40 / 360)
    filled = heightmap.copy()
    i = 0
    while i < segments:
        if filled[i] != 0:
            i += 1
            continue
        j = i
        while j < segments and filled[j] == 0:
            j += 1
        gap_len = j - i
        if gap_len > gap_threshold:
            left_idx = (i - 1) % segments
            right_idx = j % segments
            min_visible = 25.0 * height_scale
            left_val = heightmap[left_idx] if heightmap[left_idx] != 0 else min_visible
            right_val = heightmap[right_idx] if heightmap[right_idx] != 0 else min_visible
            for k in range(i, j):
                t = (k - i) / max(gap_len, 1)
                filled[k] = left_val * (1 - t) + right_val * t
        i = j if j > i else i + 1
    return filled


def sample_contours_radial_per_row(contours_by_elev: dict, radius: float, depth: float,
                                   segments: int, svg_size: float,
                                   height_scale: float, distance: float, rows: int = 4) -> tuple:
    """Sample elevations per radial row to create real topographic variation.

    Each row (inner_base, inner_slope, peak, outer_slope) samples at a different
    radius offset, so each level has distinct silhouette from actual contours.
    Returns (heightmaps_per_row, colormaps_per_row) each shape (rows, segments).
    """
    cx, cy = svg_size / 2, svg_size / 2
    svg_to_world = distance / svg_size
    r_offsets = [-depth * 0.5, -depth * 0.2, 0.0, depth * 0.15]

    heightmaps = np.zeros((rows, segments))
    colormaps = np.zeros((rows, segments, 3), dtype=np.uint8)

    for row in range(rows):
        r = radius + r_offsets[row]
        for i in range(segments):
            angle = (i / segments) * 2 * np.pi
            svg_x = cx + r * np.cos(angle) / svg_to_world
            svg_y = cy + r * np.sin(angle) / svg_to_world
            elev, color = _sample_point_elevation(svg_x, svg_y, contours_by_elev)
            heightmaps[row, i] = elev * height_scale
            colormaps[row, i] = color

    # Fill gaps per row
    for row in range(rows):
        heightmaps[row] = _fill_continuous_gaps(heightmaps[row], colormaps[row], segments, height_scale)

    return heightmaps, colormaps


# --- 3D Ring Generation ---

def generate_terrain_ring(heightmap, colormap, radius, segments, depth, rows=4):
    """Legacy wrapper: generate inner-facing wall from single heightmap.

    Uses per-row topographic sampling for real variation when heightmap is 1D.
    Prefer generate_terrain_ring_from_contours for full contour fidelity.
    """
    # Single heightmap -> expand to per-row via multipliers (fallback)
    h_max = heightmap.max() if heightmap.max() > 0 else 1.0
    r_offsets = [-depth * 0.5, -depth * 0.2, 0.0, depth * 0.15]
    h_multipliers = [0.0, 0.4, 1.0, 0.6]
    row_tints = [
        [0.5, 0.45, 0.4],
        [0.8, 0.75, 0.7],
        [1.0, 1.0, 1.0],
        [0.6, 0.55, 0.5],
    ]
    vertices = []
    faces = []
    vertex_colors = []
    for i in range(segments):
        angle = (i / segments) * 2 * np.pi
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        h = heightmap[i]
        base_color = colormap[i]
        for row in range(rows):
            r = radius + r_offsets[row]
            x = r * cos_a
            z = r * sin_a
            y = h * h_multipliers[row]
            vertices.append([x, y, z])
            tint = row_tints[row]
            r_c = int(np.clip(base_color[0] * tint[0], 0, 255))
            g_c = int(np.clip(base_color[1] * tint[1], 0, 255))
            b_c = int(np.clip(base_color[2] * tint[2], 0, 255))
            vertex_colors.append([r_c, g_c, b_c, 255])
    for i in range(segments - 1):
        for row in range(rows - 1):
            v0 = i * rows + row
            v1 = i * rows + row + 1
            v2 = (i + 1) * rows + row
            v3 = (i + 1) * rows + row + 1
            faces.append([v0, v2, v1])
            faces.append([v2, v3, v1])
    for row in range(rows - 1):
        v0 = (segments - 1) * rows + row
        v1 = (segments - 1) * rows + row + 1
        v2 = row
        v3 = row + 1
        faces.append([v0, v2, v1])
        faces.append([v2, v3, v1])
    mesh = trimesh.Trimesh(
        vertices=np.array(vertices, dtype=np.float64),
        faces=np.array(faces, dtype=np.int64),
        vertex_colors=np.array(vertex_colors, dtype=np.uint8),
        process=False,
    )
    return mesh


def generate_terrain_ring_from_contours(contours_by_elev: dict, radius: float, segments: int,
                                        depth: float, svg_size: float, height_scale: float,
                                        distance: float, is_near: bool = False,
                                        u_repeats: float = 36.0,
                                        texture_image: Image.Image | None = None):
    """Generate terrain ring with continuous organic profile, apron skirt, UVs and baked lighting.

    Profile multipliers per row:
        Near: inner_apron_ext (R=300), inner_base, lower_talus, mid_cliff, summit_ridge, rear_crest, outer_skirt, inter_apron (R=1488)
        Far: inner_base (R=1488), lower_talus, mid_cliff, summit_ridge, rear_crest, outer_skirt, horizon_base (R=1800)
    """
    peak_heightmap, peak_colormap = sample_contours_radial(
        contours_by_elev, radius, segments, svg_size, height_scale, distance
    )

    if is_near:
        rows = 9
        r_offsets = [
            660.0 - radius,      # Row 0: Extended Apron outer edge (R = 660m, slips safely under grass runoff)
            860.0 - radius,      # Row 1: Extended Apron mid plane (R = 860m)
            -depth * 0.50,       # Row 2: Inner base (R = 1073m)
            -depth * 0.30,       # Row 3: Lower talus (R = 1103.8m)
            -depth * 0.10,       # Row 4: Mid cliff (R = 1134.6m)
            0.0,                 # Row 5: Summit ridge (R = 1150m)
            depth * 0.15,        # Row 6: Rear crest (R = 1173.1m)
            depth * 0.35,        # Row 7: Outer skirt (R = 1203.9m)
            1488.0 - radius,     # Row 8: Inter-mountain connector (R = 1488m, meets Far ring)
        ]
        h_multipliers = [0.0, 0.0, 0.0, 0.25, 0.65, 1.0, 0.65, 0.15, 0.0]
        v_coords = [0.0, 0.06, 0.15, 0.35, 0.60, 0.95, 0.60, 0.20, 0.05]
        row_y_offsets = [-0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        row_tints = [
            [0.65, 0.60, 0.55],  # Extended apron edge (sand)
            [0.65, 0.60, 0.55],  # Extended apron mid (sand)
            [0.60, 0.55, 0.50],  # Inner apron base
            [0.80, 0.75, 0.70],  # Lower talus
            [0.95, 0.90, 0.85],  # Mid cliff
            [1.10, 1.05, 1.00],  # Summit ridge
            [0.85, 0.80, 0.75],  # Rear crest
            [0.55, 0.50, 0.45],  # Outer skirt
            [0.60, 0.55, 0.50],  # Inter-mountain connector (sand)
        ]
    else:
        rows = 7
        r_offsets = [
            -depth * 0.50,       # Row 0: Inner base (R = 1488m)
            -depth * 0.30,       # Row 1: Lower talus (R = 1532.8m)
            -depth * 0.10,       # Row 2: Mid cliff (R = 1577.6m)
            0.0,                 # Row 3: Summit ridge (R = 1600m)
            depth * 0.15,        # Row 4: Rear crest (R = 1633.6m)
            depth * 0.35,        # Row 5: Outer skirt (R = 1678.4m)
            1800.0 - radius,     # Row 6: Outer horizon connector (R = 1800m, meets Sky Dome)
        ]
        h_multipliers = [0.0, 0.25, 0.65, 1.0, 0.65, 0.15, 0.0]
        v_coords = [0.05, 0.35, 0.60, 0.95, 0.60, 0.20, 0.0]
        row_y_offsets = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        row_tints = [
            [0.60, 0.55, 0.50],  # Inner base
            [0.80, 0.75, 0.70],  # Lower talus
            [0.95, 0.90, 0.85],  # Mid cliff
            [1.10, 1.05, 1.00],  # Summit ridge
            [0.85, 0.80, 0.75],  # Rear crest
            [0.55, 0.50, 0.45],  # Outer skirt
            [0.55, 0.50, 0.45],  # Outer horizon base
        ]

    vertices = []
    faces = []
    base_vertex_colors = []
    uvs = []

    for i in range(segments):
        angle = (i / segments) * 2 * np.pi
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        h_peak = peak_heightmap[i]
        base_color = peak_colormap[i]
        u = (i / segments) * u_repeats
        for row in range(rows):
            r = radius + r_offsets[row]
            x = r * cos_a
            z = r * sin_a
            y = h_peak * h_multipliers[row] + row_y_offsets[row]
            vertices.append([x, y, z])
            v = v_coords[row]
            uvs.append([u, v])
            tint = row_tints[row]
            r_c = base_color[0] * tint[0]
            g_c = base_color[1] * tint[1]
            b_c = base_color[2] * tint[2]
            base_vertex_colors.append([r_c, g_c, b_c])

    # Regular quads: winding flipped so normals face inward+up (visible from track)
    for i in range(segments - 1):
        for row in range(rows - 1):
            v0 = i * rows + row
            v1 = i * rows + row + 1
            v2 = (i + 1) * rows + row
            v3 = (i + 1) * rows + row + 1
            faces.append([v0, v2, v1])
            faces.append([v2, v3, v1])

    # Seam quads (wrap-around)
    for row in range(rows - 1):
        v0 = (segments - 1) * rows + row
        v1 = (segments - 1) * rows + row + 1
        v2 = row
        v3 = row + 1
        faces.append([v0, v2, v1])
        faces.append([v2, v3, v1])

    verts_arr = np.array(vertices, dtype=np.float64)
    faces_arr = np.array(faces, dtype=np.int64)

    # Compute normals and bake directional low-poly lighting
    mesh_temp = trimesh.Trimesh(vertices=verts_arr, faces=faces_arr, process=False)
    vertex_normals = mesh_temp.vertex_normals

    # Directional sun vector from South-East at 45 deg elevation
    sun_dir = np.array([0.4, 0.8, -0.45], dtype=np.float64)
    sun_dir /= np.linalg.norm(sun_dir)

    vertex_colors = []
    for idx, norm in enumerate(vertex_normals):
        dot = np.dot(norm, sun_dir)
        # Low-poly arcade diffuse + ambient lighting curve
        light = np.clip(0.65 + 0.35 * dot, 0.45, 1.15)
        bc = base_vertex_colors[idx]
        r_lit = int(np.clip(bc[0] * light, 0, 255))
        g_lit = int(np.clip(bc[1] * light, 0, 255))
        b_lit = int(np.clip(bc[2] * light, 0, 255))
        vertex_colors.append([r_lit, g_lit, b_lit, 255])

    mesh = trimesh.Trimesh(
        vertices=verts_arr,
        faces=faces_arr,
        vertex_colors=np.array(vertex_colors, dtype=np.uint8),
        process=False,
    )
    material = trimesh.visual.material.PBRMaterial(
        name="LaChutanaMountainMaterial",
        baseColorFactor=np.array([255, 255, 255, 255], dtype=np.uint8),
        baseColorTexture=texture_image,
        metallicFactor=0.0,
        roughnessFactor=1.0,
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.array(uvs, dtype=np.float64),
        material=material,
    )
    return mesh


# --- Waterfall Detection ---

def detect_waterfalls(heightmap, segments, count=3, min_distance=80):
    """Detect waterfall placement candidates in valleys/saddles on the Near ring."""
    h_min = heightmap.min()
    h_max = heightmap.max()
    if h_max <= h_min:
        return []
    h_norm = (heightmap - h_min) / (h_max - h_min)
    candidates = []
    window = max(segments // 20, 10)
    for i in range(window, segments - window):
        # Valleys on Near ring with substantial elevation
        if heightmap[i] < h_max * 0.15 or heightmap[i] > h_max * 0.75:
            continue
        left_max = np.max(h_norm[max(0, i - window):i])
        right_max = np.max(h_norm[i + 1:min(segments, i + window + 1)])
        local_avg = (left_max + right_max) / 2.0
        if h_norm[i] < local_avg * 0.92:
            steepness = (local_avg - h_norm[i]) / max(local_avg, 0.01)
            candidates.append({
                "segment": i,
                "height_pct": float(h_norm[i]),
                "steepness": float(steepness),
                "score": float(steepness * 0.6 + (1.0 - abs(h_norm[i] - 0.4)) * 0.4),
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    selected = []
    for cand in candidates:
        if len(selected) >= count:
            break
        too_close = any(abs(cand["segment"] - s["segment"]) < min_distance for s in selected)
        if not too_close:
            selected.append(cand)
    return selected


# --- Sky Dome ---

def generate_sky_dome():
    """Generate hemisphere with gradient vertex colors and subterranean ground bowl."""
    vertices = []
    faces = []
    vertex_colors = []

    zenith = np.array(ZENITH_COLOR)
    horizon = np.array(HORIZON_COLOR)
    ground = np.array(GROUND_COLOR)

    # Top vertex (zenith)
    vertices.append([0.0, SKY_DOME_RADIUS, 0.0])
    vertex_colors.append([int(zenith[0]*255), int(zenith[1]*255), int(zenith[2]*255), 255])

    total_rings = SKY_DOME_RINGS + 4
    for ring in range(1, total_rings + 1):
        if ring <= SKY_DOME_RINGS:
            t = ring / SKY_DOME_RINGS
            phi = t * (np.pi / 2)
            y = SKY_DOME_RADIUS * np.cos(phi)
            r = SKY_DOME_RADIUS * np.sin(phi)
            if t < 0.70:
                col = zenith
            else:
                col = zenith + (horizon - zenith) * ((t - 0.70) / 0.30)
        else:
            sub_t = (ring - SKY_DOME_RINGS) / 4.0
            phi = (np.pi / 2) + sub_t * (0.15 * np.pi)
            y = SKY_DOME_RADIUS * np.cos(phi)
            r = SKY_DOME_RADIUS * np.sin(phi)
            col = ground * (1.0 - sub_t * 0.25)

        col_u8 = [int(np.clip(c * 255, 0, 255)) for c in col]
        for seg in range(SKY_DOME_SEGMENTS):
            theta = (seg / SKY_DOME_SEGMENTS) * 2 * np.pi
            x = r * np.cos(theta)
            z = r * np.sin(theta)
            vertices.append([x, y, z])
            vertex_colors.append([col_u8[0], col_u8[1], col_u8[2], 255])

    for seg in range(SKY_DOME_SEGMENTS):
        next_seg = (seg + 1) % SKY_DOME_SEGMENTS
        faces.append([0, 1 + seg, 1 + next_seg])

    for ring in range(total_rings - 1):
        base_curr = 1 + ring * SKY_DOME_SEGMENTS
        base_next = 1 + (ring + 1) * SKY_DOME_SEGMENTS
        for seg in range(SKY_DOME_SEGMENTS):
            next_seg = (seg + 1) % SKY_DOME_SEGMENTS
            faces.append([base_curr + seg, base_next + seg, base_curr + next_seg])
            faces.append([base_curr + next_seg, base_next + seg, base_next + next_seg])

    mesh = trimesh.Trimesh(
        vertices=np.array(vertices, dtype=np.float64),
        faces=np.array(faces, dtype=np.int64),
        vertex_colors=np.array(vertex_colors, dtype=np.uint8),
        process=False,
    )
    return mesh


# --- Semantic SVG Redesign Generator ---

def generate_semantic_svg(output_path: str, seed: int = 7, svg_size: float = 800.0):
    """Redesign the semantic topographic SVG so contours cover the outer radii.

    Domain represents DISTANCE=4000m so both rings fit with margin:
      near (1150m) -> r_svg 230, far (1600m) -> r_svg 320 (center at 400,400).
    Topography is a deterministic set of Gaussian peaks on the outer band, so
    contour rings CLOSE inside the domain (no giant open polygons).

    Accepts more empty area: sectors between peaks stay below 25m -> no contours;
    the gap filler keeps the layer visible.
    """
    res = 400  # grid resolution for the heightfield
    x = np.linspace(0, svg_size, res)
    y = np.linspace(0, svg_size, res)
    X, Y = np.meshgrid(x, y)
    cx = cy = svg_size / 2.0
    R = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)

    rng = np.random.default_rng(seed)

    # Deterministic Gaussian peaks on the outer band.
    # far band: r 300-330, h 60-75  (75*1.7 = 127.5m world)
    # near band: r 215-245, h 35-55 (55*0.9 = 49.5m world; a few taller reach 75*0.9)
    peaks = []
    n_far = 8
    n_near = 6
    for i in range(n_far):
        ang = rng.uniform(0, 2 * np.pi)
        r_p = rng.uniform(300.0, 330.0)
        h_p = rng.uniform(60.0, 75.0)
        sigma = rng.uniform(42.0, 55.0)
        peaks.append((cx + r_p * np.cos(ang), cy + r_p * np.sin(ang), h_p, sigma))
    for i in range(n_near):
        ang = rng.uniform(0, 2 * np.pi)
        r_p = rng.uniform(215.0, 245.0)
        h_p = rng.uniform(35.0, 55.0)
        sigma = rng.uniform(36.0, 46.0)
        peaks.append((cx + r_p * np.cos(ang), cy + r_p * np.sin(ang), h_p, sigma))

    heights = np.zeros_like(R)
    for (px, py, h_p, sigma) in peaks:
        d2 = (X - px) ** 2 + (Y - py) ** 2
        heights += h_p * np.exp(-d2 / (2.0 * sigma * sigma))

    # Decay near the domain edge so contour rings close inside the boundary
    decay = np.clip(1.0 - (R - 360.0) / 45.0, 0.0, 1.0)
    heights = heights * decay
    heights = np.clip(heights, 0.0, 100.0)

    # Contour levels: 25/50/75 (no 100 — keep far ring <=75m so far*1.7<=127m)
    levels = [25.0, 50.0, 75.0]

    fig, ax = plt.subplots()
    cs = ax.contour(X, Y, heights, levels=levels)
    plt.close(fig)

    band_names = {25.0: "lower", 50.0: "mid", 75.0: "upper"}
    band_strokes = {25.0: "#a08658", 50.0: "#806c48", 75.0: "#605338"}

    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(svg_size)}" height="{int(svg_size)}" '
        f'viewBox="0 0 {int(svg_size)} {int(svg_size)}" version="1.1" data-units="meters" '
        f'data-role="topographic-source" data-terrain-scale="1.0" data-height-scale="1.7" '
        f'data-depth-scale="0.7" data-layer="far" data-distance="4000" '
        f'data-origin="deterministic redesign for outer-radius rings">'
    )
    lines.append('<desc>Semantic topographic SVG (redesigned). Use data-elevation as the sole height '
                 'source. Ignore any group with data-ignore="true".</desc>')
    lines.append('<g id="terrain" data-role="terrain" data-layer="far" data-distance="4000" '
                 'data-height-scale="1.7" data-depth-scale="0.7">')
    lines.append('<g id="boundaries" data-role="boundaries">')
    lines.append(f'<path id="terrain_boundary" data-role="boundary" data-boundary-type="domain" '
                 f'fill="none" stroke="#999999" stroke-width="1" d="M 0,0 L {svg_size},0 L '
                 f'{svg_size},{svg_size} L 0,{svg_size} Z" /></g>')
    # Legend (ignored by parser)
    lines.append('<g id="elevation_legend" data-role="legend" data-ignore="true">')
    for lev in levels:
        lines.append(f'<path id="legend_{int(lev)}m" data-elevation="{int(lev)}" data-band="{band_names[lev]}" '
                     f'fill="none" stroke="{band_strokes[lev]}" stroke-width="2" d="M -100,-100 L -90,-100" />')
    lines.append('</g>')
    # Contours
    lines.append('<g id="contours" data-role="contours">')
    for li, lev in enumerate(levels):
        lines.append(f'<g id="contours_{int(lev)}m" data-role="contour-level" data-elevation="{int(lev)}">')
        segs = cs.allsegs[li]
        for si, seg in enumerate(segs):
            pts = np.asarray(seg)
            if len(pts) < 3:
                continue
            # closed if first and last points coincide
            closed = bool(np.hypot(*(pts[0] - pts[-1])) < 0.5)
            d_parts = []
            for pi, (px, py) in enumerate(pts):
                cmd = "M" if pi == 0 else "L"
                d_parts.append(f"{cmd}{px:.1f},{py:.1f}")
            if closed:
                d_parts.append("Z")
            lines.append(
                f'<path id="contour_{int(lev)}m_{si:03d}" data-role="contour" data-elevation="{int(lev)}" '
                f'data-band="{band_names[lev]}" data-source-stroke="{band_strokes[lev]}" '
                f'data-closed="{str(closed).lower()}" data-open="{str(not closed).lower()}" '
                f'fill="none" stroke="{band_strokes[lev]}" stroke-width="0.5" d="{" ".join(d_parts)}" />'
            )
        lines.append('</g>')
    lines.append('</g>')
    lines.append('</g>')
    lines.append('</svg>')

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"Redesigned semantic SVG written: {output_path}")

    # Report sampled elevations at the ring radii (SVG units)
    for label, r_svg in [("near(1150m)", 1150.0 / (4000.0 / svg_size)),
                         ("far(1600m)", 1600.0 / (4000.0 / svg_size))]:
        elevs = []
        for a in np.linspace(0, 2 * np.pi, 640, endpoint=False):
            px = svg_size / 2 + r_svg * np.cos(a)
            py = svg_size / 2 + r_svg * np.sin(a)
            ix = int(np.clip(px / svg_size * (res - 1), 0, res - 1))
            iy = int(np.clip(py / svg_size * (res - 1), 0, res - 1))
            h = heights[iy, ix]
            elevs.append(h)
        elevs = np.asarray(elevs)
        print(f"  {label}: r_svg={r_svg:.0f} height range {elevs.min():.1f}-{elevs.max():.1f}m, "
              f"zeros {(elevs < 25).sum()}/640")


# --- Utilities ---

def compute_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Main Pipeline ---

def main():
    parser = argparse.ArgumentParser(description="Generate topographic terrain from semantic SVG")
    parser.add_argument("svg_path", help="Path to semantic topographic SVG")
    parser.add_argument("output_dir", help="Output directory for GLBs and manifest")
    parser.add_argument("--generate-svg", metavar="OUT", default=None,
                        help="Redesign and write a new semantic SVG to OUT, then use it")
    args = parser.parse_args()

    svg_path = args.svg_path
    if args.generate_svg:
        generate_semantic_svg(args.generate_svg)
        svg_path = args.generate_svg
        print(f"Using redesigned SVG: {svg_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Parse SVG
    print(f"Parsing SVG: {svg_path}")
    contours_by_elev, metadata, boundary, parse_stats = parse_svg_contours(svg_path)
    print(f"  Metadata: height_scale={metadata['height_scale']}, "
          f"depth_scale={metadata['depth_scale']}, "
          f"distance={metadata['distance']}, layer={metadata['layer']}")

    total_contours = parse_stats["source_contours"]
    print(f"  Total contours: {total_contours}")

    # 2. Validate contours
    print("Validating contours...")
    contours_by_elev = validate_contours(contours_by_elev)
    total_valid = sum(len(v) for v in contours_by_elev.values())
    print(f"  Valid contours: {total_valid}")

    # 3. Generate terrain rings directly from contours (per-row sampling)
    # Deterministic: world_height = data-elevation * height_scale (data-elevation sole source)
    svg_size = 800.0
    distance = metadata["distance"]
    base_height_scale = metadata["height_scale"]
    # Visual balance: Near 1150m (50-110m), Far 1600m (90-240m)
    # Radios outside track ground (990m) and drivable bounds (711m).
    radius_far = 1600.0
    radius_near = 1150.0
    height_scale_far = 1.5   # 150m summit -> 225m, 100m peak -> 150m (within 90-240m)
    height_scale_near = 1.0  # 100m peak -> 100m, 75m -> 75m (within 50-110m)
    depth_far = 320.0 * metadata["depth_scale"]
    depth_near = 220.0 * metadata["depth_scale"]

    # Generate the deterministic texture before exporting the rings so each
    # GLB carries the authored material instead of trimesh's 2x2 gray fallback.
    print("Generating procedural mountain texture...")
    from generate_mountain_texture import build_mountain_texture
    tex_path = str(output_dir / "mountain_texture.png")
    tex_data = build_mountain_texture(1024, 512, seed=42)
    tex_img = Image.fromarray(tex_data, mode="RGB")
    tex_img.save(tex_path, format="PNG")
    print(f"  -> {tex_path}")

    print("Generating far mountains terrain ring (radius=%.0f, depth=%.0f, height_scale=%.1f)..." % (radius_far, depth_far, height_scale_far))
    far_ring = generate_terrain_ring_from_contours(
        contours_by_elev, radius_far, SEGMENTS_ANGULAR, depth_far, svg_size, height_scale_far, distance,
        is_near=False, u_repeats=48.0, texture_image=tex_img
    )
    far_path = str(output_dir / "far_mountains_ring.glb")
    scene = trimesh.Scene()
    scene.add_geometry(far_ring)
    scene.export(far_path)
    print(f"  -> {far_path} ({far_ring.vertices.shape[0]} verts, {far_ring.faces.shape[0]} faces)")
    # Derive heightmap for waterfall detection from far ring peak row (row index 3 in 7-row profile)
    far_heightmap = np.array([far_ring.vertices[i*7+3][1] for i in range(SEGMENTS_ANGULAR)])

    print("Generating near mountains terrain ring with Apron (radius=%.0f, depth=%.0f, height_scale=%.1f)..." % (radius_near, depth_near, height_scale_near))
    near_ring = generate_terrain_ring_from_contours(
        contours_by_elev, radius_near, SEGMENTS_ANGULAR, depth_near, svg_size, height_scale_near, distance,
        is_near=True, u_repeats=36.0, texture_image=tex_img
    )
    near_path = str(output_dir / "near_mountains_ring.glb")
    scene = trimesh.Scene()
    scene.add_geometry(near_ring)
    scene.export(near_path)
    print(f"  -> {near_path} ({near_ring.vertices.shape[0]} verts, {near_ring.faces.shape[0]} faces)")
    # Peak row index 5 in 9-row near ring profile
    near_heightmap = np.array([near_ring.vertices[i*9+5][1] for i in range(SEGMENTS_ANGULAR)])
    print(f"  Far height range: {far_heightmap.min():.1f}m to {far_heightmap.max():.1f}m")
    print(f"  Near height range: {near_heightmap.min():.1f}m to {near_heightmap.max():.1f}m")

    # 5. Detect waterfalls (on near ring, fixed in geometry)
    print("Detecting waterfall placements...")
    waterfall_candidates = detect_waterfalls(near_heightmap, SEGMENTS_ANGULAR, count=3)
    waterfalls = []
    for wf in waterfall_candidates:
        angle = (wf["segment"] / SEGMENTS_ANGULAR) * 2 * np.pi
        x = radius_near * np.cos(angle)
        z = radius_near * np.sin(angle)
        y = near_heightmap[wf["segment"]]
        waterfalls.append({
            "segment": wf["segment"],
            "angle_rad": round(angle, 4),
            "position": [round(float(x), 2), round(float(y), 2), round(float(z), 2)],
            "scale_y": 1.4 if wf["steepness"] > 0.3 else 1.15,
        })
    print(f"  Found {len(waterfalls)} waterfall placements")

    # 6. Generate sky dome
    print("Generating sky dome...")
    sky_dome = generate_sky_dome()
    sky_path = str(output_dir / "sky_dome.glb")
    scene = trimesh.Scene()
    scene.add_geometry(sky_dome)
    scene.export(sky_path)
    print(f"  -> {sky_path} ({sky_dome.vertices.shape[0]} verts, {sky_dome.faces.shape[0]} faces)")

    # 7. Copy source SVG
    svg_copy = str(output_dir / "la_chutana_topo.svg")
    shutil.copy2(svg_path, svg_copy)
    print(f"  SVG copy: {svg_copy}")

    # 9. Compute hashes
    far_hash = compute_sha256(far_path)
    near_hash = compute_sha256(near_path)
    sky_hash = compute_sha256(sky_path)
    tex_hash = compute_sha256(tex_path)

    # 10. Write manifest (relative paths, no absolute Windows paths)
    rel_svg = Path(svg_path).name

    manifest = {
        "schema_version": 1,
        "asset": "la_chutana_mountains_3d",
        "coordinate_convention": {
            "forward": "-Z", "up": "+Y", "right": "+X", "unit": "meter"
        },
        "geometry_assets": {
            "far_mountains": "far_mountains_ring.glb",
            "near_mountains": "near_mountains_ring.glb",
            "sky_dome": "sky_dome.glb"
        },
        "textures": {
            "mountain_texture": "mountain_texture.png"
        },
        "generation": {
            "method": "svg_topographic_extrusion",
            "source_svg": rel_svg,
            "height_transform": "world_height = data-elevation * height_scale (data-elevation sole source)",
            "height_scale_base": base_height_scale,
            "height_scale_far": height_scale_far,
            "height_scale_near": height_scale_near,
            "depth_scale": metadata["depth_scale"],
            "distance": distance,
            "source_layer": metadata["layer"],
            "source_contours": total_contours,
            "accepted_contours": total_valid,
            "rejected_contours": total_contours - total_valid,
            "rejection_reason": "area < %.1f or invalid polygon" % MIN_CONTOUR_AREA,
            "simplify_tolerance": SIMPLIFY_TOLERANCE,
            "min_contour_area": MIN_CONTOUR_AREA,
            "near": {
                "layer": "near",
                "radius": radius_near,
                "depth": depth_near,
                "height_scale": height_scale_near,
                "height_min": float(near_heightmap.min()),
                "height_max": float(near_heightmap.max()),
                "target_height_range": [50, 110],
                "terrain_rows": 9,
                "apron_inner_radius": 660.0,
            },
            "far": {
                "layer": "far",
                "radius": radius_far,
                "depth": depth_far,
                "height_scale": height_scale_far,
                "height_min": float(far_heightmap.min()),
                "height_max": float(far_heightmap.max()),
                "target_height_range": [90, 240],
                "terrain_rows": 7,
            },
            "sky": {
                "radius": SKY_DOME_RADIUS,
                "rings": SKY_DOME_RINGS,
                "segments": SKY_DOME_SEGMENTS,
            },
            "segments": SEGMENTS_ANGULAR,
        },
        "waterfalls": waterfalls,
        "validation": {
            "source_sha256": {
                "far_mountains_ring.glb": far_hash,
                "near_mountains_ring.glb": near_hash,
                "sky_dome.glb": sky_hash,
                "mountain_texture.png": tex_hash
            }
        }
    }

    manifest_path = str(output_dir / "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest: {manifest_path}")

    # 10. Write build report
    build_report = {
        "far_mountains": {
            "vertices": int(far_ring.vertices.shape[0]),
            "faces": int(far_ring.faces.shape[0]),
            "bbox_min": far_ring.bounds[0].tolist(),
            "bbox_max": far_ring.bounds[1].tolist(),
            "dimensions": (far_ring.bounds[1] - far_ring.bounds[0]).tolist()
        },
        "near_mountains": {
            "vertices": int(near_ring.vertices.shape[0]),
            "faces": int(near_ring.faces.shape[0]),
            "bbox_min": near_ring.bounds[0].tolist(),
            "bbox_max": near_ring.bounds[1].tolist(),
            "dimensions": (near_ring.bounds[1] - near_ring.bounds[0]).tolist()
        },
        "sky_dome": {
            "vertices": int(sky_dome.vertices.shape[0]),
            "faces": int(sky_dome.faces.shape[0]),
            "bbox_min": sky_dome.bounds[0].tolist(),
            "bbox_max": sky_dome.bounds[1].tolist(),
            "dimensions": (sky_dome.bounds[1] - sky_dome.bounds[0]).tolist()
        },
        "contours": total_valid,
        "elevation_levels": list(contours_by_elev.keys()),
        "heightmap_far_range": [float(far_heightmap.min()), float(far_heightmap.max())],
        "heightmap_near_range": [float(near_heightmap.min()), float(near_heightmap.max())]
    }

    report_path = str(output_dir / "build_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(build_report, f, indent=2)
    print(f"Build report: {report_path}")

    print("\n=== SVG TOPOGRAPHIC TERRAIN GENERATION COMPLETE ===")


if __name__ == "__main__":
    main()
