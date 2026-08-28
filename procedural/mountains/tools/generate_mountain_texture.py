#!/usr/bin/env python3
"""Generate procedural seamless mountain texture with natural coastal desert pigmentation.

Features:
- 100% horizontally seamless (tileable in U).
- Smooth continuous geological blending: coastal sand base (V=0) -> warm desert slope (V=0.4) -> sienna stone (V=0.7) -> sunbaked basalt summit (V=1.0).
- Multi-octave periodic noise, broad macro strata, and fine rock grain (no harsh zebra stripes).
- Retro arcade dithering & quantization (16/32-bit aesthetic).

Usage:
    python generate_mountain_texture.py [--output <path>] [--width 1024] [--height 512] [--seed 42]
"""

import argparse
from pathlib import Path
import numpy as np
from PIL import Image


def generate_periodic_noise(width: int, height: int, octaves: int = 5, seed: int = 42) -> np.ndarray:
    """Generate 2D noise that seamlessly wraps horizontally (periodic in X)."""
    rng = np.random.default_rng(seed)
    noise = np.zeros((height, width), dtype=np.float64)
    
    for oct in range(octaves):
        freq_x = 2 ** (oct + 1)
        freq_y = 2 ** (oct + 1)
        weight = 1.0 / (2 ** oct)
        
        num_harmonics = 8 * (oct + 1)
        for _ in range(num_harmonics):
            hx = int(rng.integers(1, max(2, freq_x * 2)))
            phase_x = rng.uniform(0, 2 * np.pi)
            hy = rng.uniform(0.5, freq_y * 1.5)
            phase_y = rng.uniform(0, 2 * np.pi)
            
            x = np.linspace(0, 2 * np.pi * hx, width, endpoint=False)
            y = np.linspace(0, 2 * np.pi * hy, height, endpoint=False)
            X, Y = np.meshgrid(x, y)
            
            wave = np.sin(X + phase_x + 0.4 * np.sin(Y * 2.0)) * np.cos(Y + phase_y)
            noise += wave * (weight / num_harmonics)
            
    noise_min = noise.min()
    noise_max = noise.max()
    if noise_max > noise_min:
        noise = (noise - noise_min) / (noise_max - noise_min)
    return noise


def build_mountain_texture(width: int = 1024, height: int = 512, seed: int = 42) -> np.ndarray:
    """Synthesize coastal desert mountain texture with smooth natural transitions."""
    v_coords = np.linspace(1.0, 0.0, height)[:, np.newaxis]
    V = np.tile(v_coords, (1, width))
    
    u_coords = np.linspace(0.0, 1.0, width, endpoint=False)[np.newaxis, :]
    U = np.tile(u_coords, (height, 1))
    
    macro_noise = generate_periodic_noise(width, height, octaves=3, seed=seed)
    strata_noise = generate_periodic_noise(width, height, octaves=5, seed=seed + 10)
    grain_noise = generate_periodic_noise(width, height, octaves=3, seed=seed + 20)
    
    # Gentle low-frequency geological elevation drift
    strata_offset = (
        0.04 * np.sin(2.0 * np.pi * U * 2.0 + macro_noise * 1.5) +
        0.02 * np.sin(2.0 * np.pi * U * 5.0 + strata_noise * 2.0) +
        0.01 * (strata_noise - 0.5)
    )
    distorted_V = np.clip(V + strata_offset, 0.0, 1.0)
    
    # --- Natural Coastal Desert Palette (Peruvian Pacific Coast: Chutana/Chilca) ---
    # Base Sand (Apron & Dunes: V = 0.00 .. 0.25)
    SAND_BASE   = np.array([216, 180, 120], dtype=np.float64)  # #D8B478 (warm coastal sand)
    SAND_MID    = np.array([200, 164, 105], dtype=np.float64)  # #C8A469
    
    # Lower Slopes (Talus & Sandy Earth: V = 0.25 .. 0.55)
    SLOPE_WARM  = np.array([184, 144,  88], dtype=np.float64)  # #B89058
    SLOPE_CLAY  = np.array([168, 122,  74], dtype=np.float64)  # #A87A4A
    
    # Mid-High Cliffs (Muted Terracotta / Sedimentary Stone: V = 0.55 .. 0.80)
    CLIFF_SIENNA = np.array([152,  98,  60], dtype=np.float64)  # #98623C (soft warm sienna)
    CLIFF_ROCK   = np.array([132,  82,  52], dtype=np.float64)  # #845234 (warm clay stone)
    
    # Summits & Crests (Sunbaked Basalt / Desert Varnish: V = 0.80 .. 1.00)
    SUMMIT_WARM  = np.array([108,  72,  48], dtype=np.float64)  # #6C4830
    SUMMIT_DARK  = np.array([ 86,  58,  40], dtype=np.float64)  # #563A28
    
    def smoothstep(edge0, edge1, x):
        t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)
    
    t0 = smoothstep(0.00, 0.25, distorted_V)[:, :, np.newaxis]
    t1 = smoothstep(0.25, 0.55, distorted_V)[:, :, np.newaxis]
    t2 = smoothstep(0.55, 0.80, distorted_V)[:, :, np.newaxis]
    t3 = smoothstep(0.80, 1.00, distorted_V)[:, :, np.newaxis]
    
    c_sand   = SAND_BASE * (1.0 - t0) + SAND_MID * t0
    c_slope  = SLOPE_WARM * (1.0 - t1) + SLOPE_CLAY * t1
    c_cliff  = CLIFF_SIENNA * (1.0 - t2) + CLIFF_ROCK * t2
    c_summit = SUMMIT_WARM * (1.0 - t3) + SUMMIT_DARK * t3
    
    w_sand   = np.clip(1.0 - smoothstep(0.00, 0.28, distorted_V), 0.0, 1.0)[:, :, np.newaxis]
    w_slope  = np.clip(smoothstep(0.15, 0.35, distorted_V) - smoothstep(0.50, 0.65, distorted_V), 0.0, 1.0)[:, :, np.newaxis]
    w_cliff  = np.clip(smoothstep(0.48, 0.65, distorted_V) - smoothstep(0.78, 0.90, distorted_V), 0.0, 1.0)[:, :, np.newaxis]
    w_summit = np.clip(smoothstep(0.75, 0.95, distorted_V), 0.0, 1.0)[:, :, np.newaxis]
    
    total_w = w_sand + w_slope + w_cliff + w_summit + 1e-6
    base_color = (c_sand * w_sand + c_slope * w_slope + c_cliff * w_cliff + c_summit * w_summit) / total_w
    
    subtle_strata = np.sin(distorted_V * 6.0 + macro_noise * 1.5) * 0.04
    subtle_macro  = (macro_noise - 0.5)[:, :, np.newaxis] * 12.0
    subtle_grain  = (grain_noise - 0.5)[:, :, np.newaxis] * 8.0
    
    rgb = base_color * (1.0 + subtle_strata[:, :, np.newaxis]) + subtle_macro + subtle_grain
    
    bayer_matrix = np.array([
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5]
    ], dtype=np.float64) / 16.0 - 0.5
    
    bayer_tile = np.tile(bayer_matrix, (height // 4 + 1, width // 4 + 1))[:height, :width, np.newaxis]
    dithered_rgb = np.clip(rgb + bayer_tile * 6.0, 0, 255)
    
    step = 4.0
    quantized_rgb = np.round(dithered_rgb / step) * step
    return np.clip(quantized_rgb, 0, 255).astype(np.uint8)


def main():
    parser = argparse.ArgumentParser(description="Generate procedural seamless mountain texture")
    parser.add_argument("--output", default="game/assets/backgrounds/la_chutana_snes_day/mountains_3d/mountain_texture.png",
                        help="Output PNG path")
    parser.add_argument("--width", type=int, default=1024, help="Texture width in pixels")
    parser.add_argument("--height", type=int, default=512, help="Texture height in pixels")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args()
    
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating procedural coastal mountain texture ({args.width}x{args.height}, seed={args.seed})...")
    img_data = build_mountain_texture(args.width, args.height, args.seed)
    
    img = Image.fromarray(img_data, mode="RGB")
    img.save(out_path, format="PNG")
    print(f"  -> Saved texture to: {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    
    codex_copy = Path("assets-lowpoly-python/background/background_layering_codex/layers/la_chutana_mountain_procedural_texture.png")
    codex_copy.parent.mkdir(parents=True, exist_ok=True)
    img.save(codex_copy, format="PNG")
    print(f"  -> Saved codex copy to: {codex_copy}")


if __name__ == "__main__":
    main()
