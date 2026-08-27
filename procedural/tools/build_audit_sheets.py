from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

VARIANTS = ["", "copper", "red", "golden_beige", "yellow"]
KINDS = {"tree": ("trees", 6), "bush": ("bushes", 6)}


def _load_preview(preview_root: Path, asset_id: str) -> Image.Image:
    image = Image.open(preview_root / f"{asset_id}.png").convert("RGBA")
    # bottom-right quadrant = isometric view
    return image.crop((image.width // 2, image.height // 2, image.width, image.height))


def _sheet_grid(preview_root: Path, ids: list[str], labels: list[str], output: Path, columns: int, tile_w: int, tile_h: int, title: str) -> None:
    header_h = 40
    rows = (len(ids) + columns - 1) // columns
    sheet = Image.new("RGBA", (tile_w * columns, header_h + tile_h * rows), (27, 29, 30, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 12), title, fill=(244, 240, 226, 255))
    for index, (asset_id, label) in enumerate(zip(ids, labels)):
        column, row = index % columns, index // columns
        tile = _load_preview(preview_root, asset_id)
        tile.thumbnail((tile_w - 16, tile_h - 36))
        x = column * tile_w + (tile_w - tile.width) // 2
        y = header_h + row * tile_h + 4
        sheet.alpha_composite(tile, (x, y))
        draw.text((column * tile_w + 10, header_h + (row + 1) * tile_h - 24), label, fill=(214, 214, 208, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(f"wrote {output} ({len(ids)} assets)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build three audit sheets covering every vegetation model.")
    parser.add_argument("--previews", type=Path, default=Path(__file__).resolve().parents[1] / "generated" / "library_audit")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "generated" / "audit_sheets")
    args = parser.parse_args()

    for kind, folder, count in (("tree", "trees", 6), ("bush", "bushes", 6)):
        ids, labels = [], []
        for index in range(1, count + 1):
            base_id = f"{kind}_3d_{index:02d}"
            for suffix in VARIANTS:
                ids.append(base_id + (f"_{suffix}" if suffix else ""))
                labels.append(base_id.split("_")[-1] + (" base" if not suffix else f" {suffix}"))
        _sheet_grid(args.previews, ids, labels, args.output / f"audit_sheet_{folder}.png", columns=5, tile_w=250, tile_h=230, title=f"{folder} - all color variants")

    base_ids = [f"{kind}_3d_{index:02d}" for kind in KINDS for index in range(1, 7)]
    _sheet_grid(args.previews, base_ids, [asset_id.replace("_3d_", " ") for asset_id in base_ids], args.output / "audit_sheet_base_assets.png", columns=3, tile_w=430, tile_h=400, title="base assets (isometric)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
