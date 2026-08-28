from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic V5 conifer LOD review sheet")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = repo / "procedural/generated/conifers_v5"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records = {(item["id"], item["lod"]): item for item in manifest["records"]}
    asset_ids = sorted({item["id"] for item in manifest["records"]})
    cell_width, image_height, label_height = 760, 900, 64
    sheet = Image.new("RGB", (cell_width * 2, (image_height + label_height) * len(asset_ids)), (24, 28, 31))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=20)
    for row, asset_id in enumerate(asset_ids):
        for column, lod in enumerate(("lod0", "lod1")):
            record = records[(asset_id, lod)]
            image = Image.open(repo / record["audit"]).convert("RGB")
            x = column * cell_width
            y = row * (image_height + label_height)
            sheet.paste(image, (x, y))
            reduction = ""
            if lod == "lod1":
                lod0 = records[(asset_id, "lod0")]["triangles"]
                reduction = f" | reduction {100.0 * (1.0 - record['triangles'] / lod0):.1f}%"
            label = f"{asset_id} | {lod.upper()} | {record['triangles']} tris{reduction}"
            draw.rectangle((x, y + image_height, x + cell_width, y + image_height + label_height), fill=(18, 21, 23))
            draw.text((x + 18, y + image_height + 20), label, fill=(232, 235, 226), font=font)
    path = output / "review" / "conifer_v5_lod_comparison.png"
    sheet.save(path, optimize=False, compress_level=9)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
