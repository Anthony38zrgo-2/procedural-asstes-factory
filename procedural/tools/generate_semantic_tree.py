from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TreeRecipe:
    asset_id: str
    seed: int = 42
    depth: int = 8
    leaf_density: float = 2.4
    trunk_length: float = 122.0
    trunk_width: float = 24.0
    length_decay: float = 0.70


def _f(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def generate_tree_svg(recipe: TreeRecipe) -> str:
    """Generate a semantic recursive tree without embedding final colors or effects."""
    if not 5 <= recipe.depth <= 10:
        raise ValueError("depth must be between 5 and 10")
    rng = random.Random(recipe.seed)
    root_rng = random.Random(recipe.seed ^ 0x524F4F54)
    branches: list[str] = []
    roots: list[str] = []
    twigs: list[str] = []
    leaves: list[str] = []
    knots: list[str] = []

    def branch(x: float, y: float, length: float, angle: float, width: float, depth: int) -> None:
        radians = math.radians(angle + rng.uniform(-5.5, 5.5))
        end_x = x + math.sin(radians) * length
        end_y = y - math.cos(radians) * length
        mid_x = (x + end_x) * 0.5
        mid_y = (y + end_y) * 0.5
        perpendicular = radians + math.pi * 0.5
        bend = length * rng.uniform(-0.09, 0.09)
        control_x = mid_x + math.cos(perpendicular) * bend
        control_y = mid_y + math.sin(perpendicular) * bend * 0.55
        role = "trunk" if depth <= 1 else "branch"
        tone = "shadow" if depth <= 2 else ("base" if depth <= 5 else "light")
        branches.append(
            f'<path data-role="{role}" data-tone="{tone}" data-depth="{depth}" '
            f'd="M {_f(x)} {_f(y)} Q {_f(control_x)} {_f(control_y)} {_f(end_x)} {_f(end_y)}" '
            f'fill="none" stroke="currentColor" stroke-width="{_f(width)}" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if depth <= 1 and rng.random() > 0.48:
            position = rng.uniform(0.30, 0.70)
            knots.append(
                f'<ellipse data-role="detail" data-tone="shadow" cx="{_f(x + (end_x - x) * position)}" '
                f'cy="{_f(y + (end_y - y) * position)}" rx="{_f(width * 0.17)}" '
                f'ry="{_f(width * 0.11)}" transform="rotate({_f(math.degrees(radians))} '
                f'{_f(x + (end_x - x) * position)} {_f(y + (end_y - y) * position)})" fill="currentColor"/>'
            )
        if depth == recipe.depth:
            count = max(2, round(recipe.leaf_density + rng.uniform(-0.5, 1.4)))
            for _ in range(count):
                leaf_x = end_x + rng.uniform(-13, 13)
                leaf_y = end_y + rng.uniform(-11, 8)
                rx = rng.uniform(2.3, 5.8)
                ry = rng.uniform(1.5, 3.7)
                tone = rng.choices(["shadow", "base", "light", "highlight"], [2, 6, 3, 1])[0]
                leaves.append(
                    f'<ellipse data-role="leaf" data-tone="{tone}" cx="{_f(leaf_x)}" cy="{_f(leaf_y)}" '
                    f'rx="{_f(rx)}" ry="{_f(ry)}" transform="rotate({_f(rng.uniform(0, 180))} '
                    f'{_f(leaf_x)} {_f(leaf_y)})" fill="currentColor"/>'
                )
            if rng.random() > 0.30:
                twig_length = width * rng.uniform(2.5, 5.5)
                twig_angle = math.radians(angle + rng.uniform(-30, 30))
                twig_x = end_x + math.sin(twig_angle) * twig_length
                twig_y = end_y - math.cos(twig_angle) * twig_length
                twigs.append(
                    f'<path data-role="branch" data-tone="light" d="M {_f(end_x)} {_f(end_y)} '
                    f'L {_f(twig_x)} {_f(twig_y)}" fill="none" stroke="currentColor" '
                    f'stroke-width="{_f(max(0.65, width * 0.45))}" stroke-linecap="round"/>'
                )
            return

        children = 3 if depth in {1, 3} and rng.random() > 0.35 else 2
        if children == 2:
            offsets = (-rng.uniform(25, 43), rng.uniform(25, 43))
        else:
            offsets = (-rng.uniform(33, 49), rng.uniform(-7, 7), rng.uniform(33, 49))
        for index, offset in enumerate(offsets):
            child_length = length * (recipe.length_decay - index * 0.018 + rng.uniform(-0.025, 0.035))
            child_width = max(0.72, width * rng.uniform(0.64, 0.73))
            branch(end_x, end_y, child_length, angle + offset, child_width, depth + 1)

    root_specs = [
        (-1, -72, 10), (-1, -45, 8), (-1, -24, 6),
        (1, 24, 6), (1, 45, 8), (1, 72, 10),
    ]
    for _side, reach, width in root_specs:
        end_x = 256 + reach + root_rng.uniform(-7, 7)
        end_y = 481 + root_rng.uniform(-2, 3)
        control_x = 256 + reach * 0.36
        control_y = 473 + root_rng.uniform(2, 8)
        roots.append(
            f'<path data-role="root" data-tone="base" d="M 256 463 Q {_f(control_x)} '
            f'{_f(control_y)} {_f(end_x)} {_f(end_y)}" fill="none" stroke="currentColor" '
            f'stroke-width="{width}" stroke-linecap="round"/>'
        )
    branch(256.0, 474.0, recipe.trunk_length, 0.0, recipe.trunk_width, 0)
    content = "\n  ".join(roots + branches + knots + leaves + twigs)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" '
        f'data-schema-version="1" data-asset-id="{recipe.asset_id}" data-asset-kind="tree" '
        f'data-generator="recursive_bezier_tree_v1" data-seed="{recipe.seed}" data-depth="{recipe.depth}">\n'
        '  <desc>Deterministic recursive semantic tree with quadratic branches and terminal leaves.</desc>\n'
        f'  {content}\n</svg>\n'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a detailed semantic tree SVG")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset-id", default="tree_recursive_01")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--leaf-density", type=float, default=2.4)
    args = parser.parse_args()
    svg = generate_tree_svg(TreeRecipe(args.asset_id, args.seed, args.depth, args.leaf_density))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"generated {args.output} ({svg.count('<path')} paths, {svg.count('<ellipse')} ellipses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
