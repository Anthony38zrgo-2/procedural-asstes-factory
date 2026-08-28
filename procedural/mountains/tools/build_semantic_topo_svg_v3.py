#!/usr/bin/env python3
"""Build high-fidelity semantic topographic SVG v3 for Formula-90 La Chutana background.

Features:
- Complete 360-degree coverage across all 8 sectors.
- Distinct Near ring (r~230 in SVG) and Far ring (r~320 in SVG) mountain formations.
- Hierarchical elevation levels: 25m, 50m, 75m, 100m, 125m, 150m with band tags.
- Defined canyons / saddles (quebradas) on the Near ring for natural waterfall placement.
- Topological validity: all contours are clean, non-intersecting, valid closed polygons.
"""

import argparse
import math
import numpy as np
from pathlib import Path


def create_smooth_contour(center_x, center_y, base_radius, angle_start_deg, angle_end_deg,
                          radial_offsets, num_points=64):
    """Create a closed or annular sector contour smoothly interpolated."""
    angles_deg = np.linspace(angle_start_deg, angle_end_deg, num_points)
    angles_rad = np.radians(angles_deg)
    
    # Interpolate radial offsets across the angular span
    t = np.linspace(0, 1, num_points)
    r_curve = np.interp(t, np.linspace(0, 1, len(radial_offsets)), radial_offsets)
    radii = base_radius + r_curve
    
    x = center_x + radii * np.cos(angles_rad)
    y = center_y + radii * np.sin(angles_rad)
    return list(zip(x, y))


def polygon_to_svg_path(points, is_closed=True):
    """Convert list of (x, y) tuples to SVG path d attribute."""
    if not points:
        return ""
    d_parts = [f"M {points[0][0]:.1f},{points[0][1]:.1f}"]
    for pt in points[1:]:
        d_parts.append(f"L {pt[0]:.1f},{pt[1]:.1f}")
    if is_closed:
        d_parts.append("Z")
    return " ".join(d_parts)


def build_svg_v3(output_path):
    cx, cy = 400.0, 400.0
    
    # Palette colors per band
    band_colors = {
        "lower": "#a08658",
        "mid": "#806c48",
        "upper": "#605338",
        "summit": "#403928"
    }

    # 1. Base 25m contours: 8 sector polygons that encircle the track domain
    # Near ring ~ 230, Far ring ~ 320. Spans from r=150 to r=370.
    # We leave 4 narrow saddles (at 42°, 105°, 195°, 285°) for drainage / valleys.
    
    sectors_25m = [
        # (start_deg, end_deg, r_inner, r_outer, r_profile)
        (0, 40, 160, 360, [15, 30, 45, 50, 30, 10]),
        (45, 100, 155, 365, [10, 40, 60, 55, 35, 15]),
        (108, 155, 165, 360, [15, 35, 50, 45, 25, 10]),
        (160, 192, 160, 355, [10, 30, 40, 35, 20, 10]),
        (198, 245, 165, 365, [15, 45, 60, 50, 30, 15]),
        (250, 282, 160, 355, [10, 35, 45, 40, 25, 10]),
        (288, 330, 165, 370, [15, 40, 65, 55, 35, 15]),
        (333, 358, 160, 360, [10, 30, 45, 40, 25, 10]),
    ]
    
    # 2. Mid 50m contours: substantial massifs covering Near and Far rings
    sectors_50m = [
        (5, 36, 185, 345, [10, 25, 35, 25, 10]),
        (50, 95, 180, 350, [15, 35, 45, 30, 15]),
        (112, 150, 190, 340, [10, 25, 35, 25, 10]),
        (164, 188, 185, 335, [10, 20, 30, 20, 10]),
        (202, 240, 185, 350, [15, 35, 45, 30, 15]),
        (254, 278, 185, 340, [10, 25, 30, 20, 10]),
        (292, 326, 185, 355, [15, 35, 50, 35, 15]),
        (336, 355, 185, 345, [10, 25, 35, 25, 10]),
    ]

    # 3. High 75m contours: ridges on Near (r~230) and Far (r~320)
    # Divided into Far ridges and Near ridges
    sectors_75m = [
        # Far ridges (r ~ 290..340)
        (8, 33, 285, 340, [10, 20, 25, 15, 5]),
        (54, 90, 280, 345, [10, 25, 35, 25, 10]),
        (116, 145, 285, 338, [10, 20, 25, 15, 10]),
        (206, 236, 285, 345, [10, 25, 30, 20, 10]),
        (296, 322, 280, 350, [10, 25, 35, 25, 10]),
        (340, 352, 285, 340, [5, 15, 20, 15, 5]),
        
        # Near ridges (r ~ 210..250)
        (10, 30, 210, 250, [5, 15, 20, 15, 5]),
        (56, 88, 205, 255, [10, 20, 25, 15, 10]),
        (118, 142, 210, 248, [5, 15, 20, 10, 5]),
        (208, 234, 210, 255, [10, 20, 25, 15, 10]),
        (298, 320, 205, 255, [10, 20, 25, 15, 10]),
    ]

    # 4. Peaks 100m (upper/summit): high summits
    sectors_100m = [
        # Far grand summits (r ~ 300..335)
        (12, 28, 295, 335, [5, 15, 20, 15, 5]),
        (58, 84, 290, 340, [10, 20, 25, 20, 10]),
        (120, 140, 292, 335, [5, 15, 20, 15, 5]),
        (210, 230, 292, 340, [5, 15, 20, 15, 5]),
        (300, 318, 290, 342, [10, 20, 25, 15, 10]),

        # Near prominent rocky peaks (r ~ 220..242)
        (14, 24, 220, 242, [5, 10, 12, 10, 5]),
        (62, 80, 218, 246, [5, 12, 15, 12, 5]),
        (212, 226, 220, 244, [5, 10, 12, 10, 5]),
        (302, 314, 218, 246, [5, 12, 15, 10, 5]),
    ]

    # 5. Grand Summits 125m and 150m (on Far ring backdrop)
    sectors_125m = [
        (16, 25, 302, 330, [5, 10, 15, 10, 5]),
        (62, 78, 298, 335, [5, 15, 18, 15, 5]),
        (124, 136, 300, 328, [5, 10, 12, 10, 5]),
        (304, 314, 298, 336, [5, 12, 16, 12, 5]),
    ]

    sectors_150m = [
        (66, 74, 305, 330, [3, 8, 12, 8, 3]),
        (306, 312, 304, 332, [3, 8, 10, 8, 3]),
    ]

    def generate_annular_sector(start_deg, end_deg, r_inner, r_outer, profile, num_pts=32):
        """Build a closed contour representing a mountain sector with natural curving edges."""
        angles_fwd = np.linspace(start_deg, end_deg, num_pts)
        angles_rev = np.linspace(end_deg, start_deg, num_pts)
        
        # Outer arc
        t_fwd = np.linspace(0, 1, num_pts)
        p_outer = np.interp(t_fwd, np.linspace(0, 1, len(profile)), profile)
        r_out = r_outer + p_outer * 0.4
        
        # Inner arc
        p_inner = np.interp(t_fwd, np.linspace(0, 1, len(profile)), profile)
        r_in = r_inner - p_inner * 0.3
        
        pts_out = [
            (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a, r in zip(angles_fwd, r_out)
        ]
        pts_in = [
            (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a, r in zip(angles_rev, r_in[::-1])
        ]
        return pts_out + pts_in

    # Assemble SVG content
    svg_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800" version="1.1" data-units="meters" data-role="topographic-source" data-terrain-scale="1.0" data-height-scale="1.8" data-depth-scale="0.7" data-layer="far" data-distance="4000" data-origin="high-fidelity 360-degree coverage v3">',
        '<desc>Semantic topographic SVG v3 with full 360-degree coverage, organic multi-tier relief, and distinct Near/Far mountain massifs.</desc>',
        '<g id="terrain" data-role="terrain" data-layer="far" data-distance="4000" data-height-scale="1.8" data-depth-scale="0.7">',
        '<g id="boundaries" data-role="boundaries">',
        '<path id="terrain_boundary" data-role="boundary" data-boundary-type="domain" fill="none" stroke="#999999" stroke-width="1" d="M 0,0 L 800.0,0 L 800.0,800.0 L 0,800.0 Z" />',
        '</g>',
        '<g id="elevation_legend" data-role="legend" data-ignore="true">',
        '<path id="legend_25m" data-elevation="25" data-band="lower" fill="none" stroke="#a08658" stroke-width="2" d="M -100,-100 L -90,-100" />',
        '<path id="legend_50m" data-elevation="50" data-band="mid" fill="none" stroke="#806c48" stroke-width="2" d="M -100,-100 L -90,-100" />',
        '<path id="legend_75m" data-elevation="75" data-band="upper" fill="none" stroke="#605338" stroke-width="2" d="M -100,-100 L -90,-100" />',
        '<path id="legend_100m" data-elevation="100" data-band="upper" fill="none" stroke="#605338" stroke-width="2" d="M -100,-100 L -90,-100" />',
        '<path id="legend_125m" data-elevation="125" data-band="summit" fill="none" stroke="#403928" stroke-width="2" d="M -100,-100 L -90,-100" />',
        '<path id="legend_150m" data-elevation="150" data-band="summit" fill="none" stroke="#403928" stroke-width="2" d="M -100,-100 L -90,-100" />',
        '</g>',
        '<g id="contours" data-role="contours">'
    ]

    levels = [
        (25, "lower", sectors_25m),
        (50, "mid", sectors_50m),
        (75, "upper", sectors_75m),
        (100, "upper", sectors_100m),
        (125, "summit", sectors_125m),
        (150, "summit", sectors_150m),
    ]

    for elev, band, sectors in levels:
        svg_lines.append(f'<g id="contours_{elev}m" data-role="contour-level" data-elevation="{elev}">')
        for i, s in enumerate(sectors):
            s_deg, e_deg, r_in, r_out, prof = s
            pts = generate_annular_sector(s_deg, e_deg, r_in, r_out, prof)
            d_str = polygon_to_svg_path(pts)
            stroke_color = band_colors[band]
            svg_lines.append(
                f'<path id="contour_{elev}m_{i:03d}" data-role="contour" data-elevation="{elev}" data-band="{band}" '
                f'data-source-stroke="{stroke_color}" data-closed="true" data-open="false" '
                f'fill="none" stroke="{stroke_color}" stroke-width="0.5" d="{d_str}" />'
            )
        svg_lines.append('</g>')

    svg_lines.append('</g>')
    svg_lines.append('</g>')
    svg_lines.append('</svg>')

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(svg_lines), encoding="utf-8")
    print(f"Generated semantic SVG v3: {out_path} ({len(svg_lines)} lines)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the La Chutana semantic topographic SVG")
    parser.add_argument("output_path", nargs="?", default="inputs/la_chutana/la_chutana_topo.svg")
    args = parser.parse_args()
    build_svg_v3(args.output_path)
