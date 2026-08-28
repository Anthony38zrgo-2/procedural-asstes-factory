from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

LONGITUDES = ("west", "center", "east")
ALTITUDES = ("low", "medium", "high")


@dataclass(frozen=True)
class BiomeKey:
    continent: str
    longitude: str
    altitude: str

    @property
    def id(self) -> str:
        return f"{self.continent}_{self.longitude}_{self.altitude}"


@dataclass(frozen=True)
class ProceduralAssetSpec:
    id: str
    category: str
    weight: float
    radius_m: float
    scale_min: float
    scale_max: float
    width_m: float
    height_m: float
    depth_m: float = 0.0
    planes: int = 0
    variant_index: int = 0


def normalize_biome(continent, longitude, altitude) -> BiomeKey:
    c = str(continent).lower()
    lon = str(longitude).lower()
    alt = str(altitude).lower()
    if c != "south_america":
        raise KeyError("Only south_america is currently supported")
    if lon not in LONGITUDES:
        raise KeyError(f"longitude must be one of {LONGITUDES}")
    if alt not in ALTITUDES:
        raise KeyError(f"altitude must be one of {ALTITUDES}")
    return BiomeKey(c, lon, alt)


def biome_from_config(config) -> BiomeKey:
    env = config["procedural_environment"]
    b = env.get("biome", {})
    return normalize_biome(
        b.get("continent", env.get("region", "south_america")),
        b.get("longitude", "west"),
        b.get("altitude", "low"),
    )


def supported_biomes() -> tuple[BiomeKey, ...]:
    return tuple(BiomeKey("south_america", lon, alt) for lon in LONGITUDES for alt in ALTITUDES)


def _shift(c, green=0.0, dry=0.0, dark=0.0):
    r, g, b = c
    return (
        max(0.0, min(1.0, r + dry - dark)),
        max(0.0, min(1.0, g + green - dark)),
        max(0.0, min(1.0, b + dry * 0.35 - dark * 0.55)),
    )


def palette_for(b: BiomeKey) -> dict:
    wet = {"west": -0.04, "center": 0.02, "east": 0.09}[b.longitude]
    cold = {"low": 0.0, "medium": 0.018, "high": 0.040}[b.altitude]
    green = _shift((0.30, 0.38, 0.18), green=wet - cold, dark=cold * 0.35)
    dry = _shift((0.47, 0.42, 0.23), green=wet * 0.20, dry=-wet * 0.18, dark=cold * 0.18)
    dirt = _shift((0.43, 0.31, 0.20), green=wet * 0.06, dark=cold * 0.10)
    mix = {
        "west": (0.40, 0.44, 0.16),
        "center": (0.55, 0.32, 0.13),
        "east": (0.71, 0.19, 0.10),
    }[b.longitude]
    if b.altitude == "high":
        mix = (mix[0] * 0.84, mix[1] * 1.18, mix[2])

    def variants(base, contrast):
        return tuple(
            _shift(
                base,
                green=(i - 1.5) * contrast * 0.20,
                dry=(1.5 - i) * contrast * 0.14,
                dark=(i % 2) * contrast * 0.12,
            )
            for i in range(4)
        )

    return {
        "terrain": {"green": green, "dry": dry, "dirt": dirt, "mix": mix},
        "tree": variants(_shift(green, green=-0.012, dark=0.050), 0.15),
        "bush": variants(_shift(green, green=0.025, dry=0.055, dark=0.010), 0.17),
        "grass": variants(_shift(dry, green=0.014), 0.18),
        "structures": variants((0.56, 0.53, 0.47), 0.12),
    }


def _profile(b: BiomeKey) -> dict[str, tuple[ProceduralAssetSpec, ...]]:
    moisture = {"west": 0.94, "center": 1.0, "east": 1.09}[b.longitude]
    altitude_height = {"low": 1.03, "medium": 1.0, "high": 0.91}[b.altitude]
    prefix = b.id

    tree_dims = ((7.4, 11.8), (8.4, 13.8), (6.6, 15.4), (9.2, 12.8))
    bush_dims = ((4.8, 1.9), (5.7, 2.2), (4.3, 1.7), (6.2, 2.05))
    grass_dims = ((0.90, 0.62), (1.08, 0.78), (0.82, 0.56), (1.00, 0.72))
    build_dims = (
        (18.0, 9.3, 11.7),
        (32.0, 11.9, 16.2),
        (14.4, 12.7, 9.9),
        (23.4, 10.5, 13.5),
    )
    bw = {"west": 1.0, "center": 0.97, "east": 1.07}[b.longitude]
    bh = {"low": 0.97, "medium": 1.0, "high": 1.10}[b.altitude]
    bd = {"west": 1.0, "center": 0.97, "east": 1.06}[b.longitude]

    trees = tuple(
        ProceduralAssetSpec(
            f"{prefix}_tree_{i+1:02d}", "trees", 1.0,
            w * 0.48 * moisture, 0.88, 1.18,
            w * moisture, h * altitude_height * moisture,
            planes=3, variant_index=i,
        )
        for i, (w, h) in enumerate(tree_dims)
    )
    bushes = tuple(
        ProceduralAssetSpec(
            f"{prefix}_bush_{i+1:02d}", "bushes", 1.0,
            w * 0.48, 0.84, 1.20,
            w, h * (0.97 + 0.08 * moisture),
            planes=2, variant_index=i,
        )
        for i, (w, h) in enumerate(bush_dims)
    )
    grass = tuple(
        ProceduralAssetSpec(
            f"{prefix}_grass_{i+1:02d}", "grass", 1.0,
            w * 0.35, 0.78, 1.22,
            w, h,
            planes=1, variant_index=i,
        )
        for i, (w, h) in enumerate(grass_dims)
    )
    buildings = tuple(
        ProceduralAssetSpec(
            f"{prefix}_building_{i+1:02d}", "fake_buildings", 1.0,
            max(w * bw, d * bd) * 0.58, 0.92, 1.08,
            w * bw, h * bh, d * bd,
            variant_index=i,
        )
        for i, (w, h, d) in enumerate(build_dims)
    )
    return {"trees": trees, "bushes": bushes, "grass": grass, "fake_buildings": buildings}


def specs_for_biome(b: BiomeKey, category: str) -> tuple[ProceduralAssetSpec, ...]:
    return _profile(b)[category]


def spec_map_for_biome(b: BiomeKey) -> dict[str, ProceduralAssetSpec]:
    return {s.id: s for values in _profile(b).values() for s in values}


def weighted_choice(rng, specs: Iterable[ProceduralAssetSpec]) -> ProceduralAssetSpec:
    vals = tuple(specs)
    if not vals:
        raise ValueError("weighted_choice requires at least one spec")
    total = sum(max(0.0, s.weight) for s in vals)
    pick = rng.random() * total if total else 0.0
    run = 0.0
    for s in vals:
        run += max(0.0, s.weight)
        if pick <= run:
            return s
    return vals[-1]
