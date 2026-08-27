from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    for kind in ("tree", "bush"):
        files = sorted(args.input_dir.glob(f"{kind}_3d_*.png"))
        output = Image.new("RGBA", (960, 700), (30, 32, 33, 255))
        for index, source in enumerate(files):
            image = Image.open(source).convert("RGBA")
            image.thumbnail((300, 300))
            tile = Image.new("RGBA", (320, 350), (35, 37, 38, 255))
            tile.alpha_composite(image, ((320 - image.width) // 2, 10))
            ImageDraw.Draw(tile).text((12, 320), source.stem, fill=(245, 245, 245, 255))
            output.alpha_composite(tile, ((index % 3) * 320, (index // 3) * 350))
        output.save(args.input_dir / f"{kind}_comparison.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
