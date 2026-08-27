from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from PIL import Image, ImageDraw

from build_vegetation_3d_library import build_asset


WOOD_ROLES = ("root", "trunk", "branch")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_recipes(repo: Path, manifest: dict) -> list[dict]:
    base = _load(repo / manifest["base_recipe"])
    return [recipe for recipe in base["assets"] if recipe["kind"] == manifest["kind"]]


def _validate_wood_invariant(palettes: list[dict], kind: str) -> None:
    reference = palettes[0]["categories"][kind]
    for palette in palettes[1:]:
        category = palette["categories"][kind]
        for role in WOOD_ROLES:
            if role in reference and category[role] != reference[role]:
                raise ValueError(f"Palette changes protected wood role: {role}")


def _variant_recipe(base: dict, variant: dict, index: int) -> dict:
    recipe = deepcopy(base)
    suffix = str(variant["suffix"])
    recipe["id"] = base["id"] if not suffix else f"{base['id']}_{suffix}"
    recipe["seed"] = int(variant["seed_base"]) + index + 1
    return recipe


def _contact_sheet(repo: Path, manifest: dict, recipes: list[dict], output: Path) -> None:
    variants = manifest["variants"]
    tile_w, tile_h, header_h = 250, 230, 44
    sheet = Image.new("RGBA", (tile_w * len(variants), header_h + tile_h * len(recipes)), (27, 29, 30, 255))
    draw = ImageDraw.Draw(sheet)
    for column, variant in enumerate(variants):
        draw.text((column * tile_w + 12, 14), str(variant["id"]), fill=(244, 240, 226, 255))
    for row, base in enumerate(recipes):
        for column, variant in enumerate(variants):
            recipe = _variant_recipe(base, variant, row)
            preview = repo / "game/resources/environment/generated/library_audit" / f"{recipe['id']}.png"
            image = Image.open(preview).convert("RGBA")
            image = image.crop((image.width // 2, image.height // 2, image.width, image.height))
            image.thumbnail((tile_w - 20, tile_h - 30))
            x = column * tile_w + (tile_w - image.width) // 2
            y = header_h + row * tile_h + 4
            sheet.alpha_composite(image, (x, y))
            draw.text((column * tile_w + 10, header_h + (row + 1) * tile_h - 22), recipe["id"], fill=(220, 220, 214, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build five deterministic color families of procedural trees.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    repo = args.repo.resolve()
    manifest = _load(args.manifest.resolve())
    kind = str(manifest["kind"])
    recipes = _base_recipes(repo, manifest)
    palettes = [_load(repo / variant["palette"]) for variant in manifest["variants"]]
    _validate_wood_invariant(palettes, kind)

    output_root = repo / "game/resources/environment/assets"
    audit_root = repo / "game/resources/environment/generated/library_audit"
    records = []
    for variant, palette_doc in zip(manifest["variants"], palettes):
        palette = palette_doc["categories"][kind]
        for index, base in enumerate(recipes):
            recipe = _variant_recipe(base, variant, index)
            records.append(build_asset(recipe, palette, output_root, audit_root))
            print(f"built {recipe['id']} seed={recipe['seed']}")

    review = repo / manifest["review"]
    _contact_sheet(repo, manifest, recipes, review)
    report = {
        "schema_version": 1,
        "generator": f"procedural_lanceolate_vegetation_v3_{kind}_color_library",
        "manifest": args.manifest.resolve().relative_to(repo).as_posix(),
        "wood_palette_locked": True,
        "assets": records,
        "review": review.relative_to(repo).as_posix(),
    }
    report_path = repo / manifest["report"]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assets": len(records), "review": str(review), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
