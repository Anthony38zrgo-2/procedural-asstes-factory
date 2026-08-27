from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw

from arboreal_stylizer import stylize_arboreal_card
from semantic_svg import load_palette, pigment, serialize_svg, sha256, validate_svg

SIZE = 512


def render_one(source: Path, palette_path: Path, output_dir: Path) -> dict:
    root, analysis = validate_svg(source)
    palette = load_palette(palette_path)
    colored, pigmentation = pigment(root, palette, analysis["kind"])
    svg_bytes = serialize_svg(colored)
    png_bytes = resvg_py.svg_to_bytes(
        svg_string=svg_bytes.decode("utf-8"),
        width=SIZE,
        height=SIZE,
        skip_system_fonts=True,
        shape_rendering="geometric_precision",
    )
    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    image, art_style = stylize_arboreal_card(
        image, palette, analysis["kind"], analysis["asset_id"]
    )
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", optimize=False, compress_level=9)
    png_bytes = encoded.getvalue()
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError(f"Rasterizer produced an empty card: {source}")

    svg_dir = output_dir / "pigmented_svg"
    png_dir = output_dir / "png"
    report_dir = output_dir / "reports"
    for directory in (svg_dir, png_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)
    asset_id = analysis["asset_id"]
    (svg_dir / f"{asset_id}.svg").write_bytes(svg_bytes)
    (png_dir / f"{asset_id}.png").write_bytes(png_bytes)
    report = {
        **analysis,
        **pigmentation,
        "source": source.as_posix(),
        "size": [SIZE, SIZE],
        "alpha_bbox": list(bbox),
        "visible_pixels": sum(alpha.histogram()[1:]),
        "source_sha256": sha256(source.read_bytes()),
        "pigmented_svg_sha256": sha256(svg_bytes),
        "png_sha256": sha256(png_bytes),
        "art_style": art_style,
        "rasterizer": {"package": "resvg_py", "version": resvg_py.__version__, "engine": resvg_py.__resvg_version__},
    }
    (report_dir / f"{asset_id}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    image = Image.new("RGB", size, "#D8D8D8")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#B8B8B8")
    return image


def build_sheet(reports: list[dict], output_dir: Path) -> Path:
    thumb = 256
    label = 34
    margin = 18
    columns = 3
    rows = (len(reports) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (thumb + margin) + margin, rows * (thumb + label + margin) + margin), "#242628")
    draw = ImageDraw.Draw(sheet)
    for index, report in enumerate(reports):
        col, row = index % columns, index // columns
        x = margin + col * (thumb + margin)
        y = margin + row * (thumb + label + margin)
        card = Image.open(output_dir / "png" / f"{report['asset_id']}.png").convert("RGBA").resize((thumb, thumb), Image.Resampling.LANCZOS)
        background = checkerboard((thumb, thumb))
        background.paste(card, mask=card.getchannel("A"))
        sheet.paste(background, (x, y))
        draw.text((x, y + thumb + 7), f"{report['asset_id']} · {report['kind']}", fill="#F2F2F2")
    path = output_dir / "review_sheet.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, optimize=False)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate, pigment and rasterize semantic SVG cards")
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("render")
    one.add_argument("source", type=Path)
    one.add_argument("--palette", type=Path, required=True)
    one.add_argument("--output-dir", type=Path, required=True)
    batch = sub.add_parser("batch")
    batch.add_argument("--input-dir", type=Path, required=True)
    batch.add_argument("--palette", type=Path, required=True)
    batch.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "render":
            reports = [render_one(args.source, args.palette, args.output_dir)]
        else:
            sources = sorted(args.input_dir.glob("*.svg"))
            if not sources:
                raise ValueError(f"No SVG files found in {args.input_dir}")
            reports = [render_one(source, args.palette, args.output_dir) for source in sources]
        sheet = build_sheet(reports, args.output_dir)
        print(json.dumps({"rendered": len(reports), "review_sheet": str(sheet), "assets": [r["asset_id"] for r in reports]}, indent=2))
        return 0
    except Exception as exc:
        print(f"semantic-card error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
