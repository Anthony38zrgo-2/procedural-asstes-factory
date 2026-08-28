from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def lod_sheet(repo: Path, records: dict, ids: list[str], output: Path) -> None:
    cell_w, cell_h, label_h = 430, 500, 52
    sheet = Image.new("RGB", (cell_w * 2, (cell_h + label_h) * len(ids)), (23, 27, 30))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for row, asset_id in enumerate(ids):
        for col, lod in enumerate(("lod0", "lod1")):
            record = records[(asset_id, "green", lod)]
            image = Image.open(repo / record["audit"]).convert("RGB").resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            x, y = col * cell_w, row * (cell_h + label_h)
            sheet.paste(image, (x, y))
            reduction = ""
            if lod == "lod1":
                lod0 = records[(asset_id, "green", "lod0")]["triangles"]
                reduction = f" | -{100 * (1 - record['triangles'] / lod0):.1f}%"
            draw.rectangle((x, y + cell_h, x + cell_w, y + cell_h + label_h), fill=(16, 19, 21))
            draw.text((x + 12, y + cell_h + 16), f"{asset_id} | {lod.upper()} | {record['triangles']} tris{reduction}", fill=(235, 237, 229), font=font)
    sheet.save(output, compress_level=9)


def seasonal_sheet(repo: Path, records: dict, ids: list[str], output: Path) -> None:
    variants = ["green", "copper", "golden_beige", "red", "yellow"]
    cell_w, cell_h, label_h = 310, 360, 48
    sheet = Image.new("RGB", (cell_w * len(variants), (cell_h + label_h) * len(ids)), (23, 27, 30))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=17)
    for row, asset_id in enumerate(ids):
        for col, variant in enumerate(variants):
            record = records[(asset_id, variant, "lod0")]
            image = Image.open(repo / record["audit"]).convert("RGB").resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            x, y = col * cell_w, row * (cell_h + label_h)
            sheet.paste(image, (x, y))
            draw.rectangle((x, y + cell_h, x + cell_w, y + cell_h + label_h), fill=(16, 19, 21))
            draw.text((x + 10, y + cell_h + 14), f"{asset_id} | {variant}", fill=(235, 237, 229), font=font)
    sheet.save(output, compress_level=9)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    root = repo / "procedural/generated/vegetation_v5"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    records = {(item["id"], item["variant"], item["lod"]): item for item in manifest["records"]}
    review = root / "review"
    tree_ids = sorted({item["id"] for item in manifest["records"] if item["kind"] == "tree"})
    lod_sheet(repo, records, tree_ids, review / "trees_v5_lod_comparison.png")
    lod_sheet(repo, records, [f"bush_3d_{index:02d}" for index in range(1, 7)], review / "bushes_v5_lod_comparison.png")
    seasonal_sheet(repo, records, ["tree_3d_05", "bush_3d_02"], review / "vegetation_v5_seasonal_comparison.png")
    print(review)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
