from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    root = repo / "procedural/generated/vegetation_v5"
    manifest = json.loads((root / "grass_manifest.json").read_text(encoding="utf-8"))
    records = {(item["id"], item["variant"]): item for item in manifest["records"]}
    ids = [f"grass_3d_{index:02d}" for index in range(1, 6)]
    variants = ["green", "copper", "golden_beige", "red", "yellow"]
    cell_w, cell_h, label_h = 310, 250, 42
    sheet = Image.new("RGB", (cell_w * 5, (cell_h + label_h) * 5), (22, 26, 29))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    for row, asset_id in enumerate(ids):
        for col, variant in enumerate(variants):
            record = records[(asset_id, variant)]
            audit = Image.open(repo / record["audit"]).convert("RGB").resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            x, y = col * cell_w, row * (cell_h + label_h)
            sheet.paste(audit, (x, y))
            draw.rectangle((x, y + cell_h, x + cell_w, y + cell_h + label_h), fill=(15, 18, 20))
            draw.text((x + 9, y + cell_h + 12), f"{asset_id} | {variant} | {record['triangles']} tris", fill=(235, 237, 229), font=font)
    path = root / "review/grass_v5_color_comparison.png"
    sheet.save(path, compress_level=9)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
