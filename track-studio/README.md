# La Chutana GLB outsourcing quick test

This directory is a deliberately small transfer from Formula90s. Its only goal
is to prove that `procedural-asstes-factory` can independently reproduce a
playable La Chutana GLB before Track Builder/Track Studio itself is migrated.

No GLB, PNG, texture bank, building, barrier or other asset was copied from
Formula90s. The transferred files are inputs and generator code only.

## Quick start

Generate the playable base circuit (terrain, asphalt geometry, kerbs, surface
collisions, safety floor, start/finish and spawn marker):

```powershell
cd D:\procedural-asstes-factory
.\track-studio\scripts\build_la_chutana_quick_test.ps1 -Mode Base
```

Output:

```text
track-studio/output/la_chutana/la_chutana.glb
```

The base build uses flat fallback materials when the factory has not generated
its texture bank yet. This is intentional: the first test is geometry and
playability, not asset parity.

Verified locally with Blender 5.2 on 2026-08-28:

```text
GLB bytes:       7,046,160
GLB SHA-256:     ff5d1e3bd3f8f82be784ba8b2380c14e79107124b9811587b24e6d524660fedf
nodes:           33
meshes:          32
materials:       8
collision nodes: 15
PlayerSpawn:     1
Safety floor:    1
images/textures: 0/0
curb validation: PASS (10 profiles)
```

This GLB was generated inside the factory from the transferred inputs. It was
not copied from Formula90s.

After the factory generates its own buildings and barriers, attempt the complete
placement build:

```powershell
.\track-studio\scripts\build_la_chutana_quick_test.ps1 -Mode Environment
```

The preflight prints every missing factory-owned dependency and refuses to read
anything from `D:\Formula90s`.

## Directory index

### `inputs/la_chutana/`

| File | Purpose |
|---|---|
| `track.canonical.svg` | Canonical semantic circuit authority transferred from the active La Chutana revision. |
| `centerline.json` | Sampled centerline used directly by the Blender geometry builders. |
| `placements.json` | Canonical snapshot of vegetation, buildings and trackside positions. Asset paths are adapted during staging, not in this source snapshot. |

### `blender/track_pipeline/`

| File/group | Purpose |
|---|---|
| `build_track_blender.py` | Builds terrain, road, shoulders, kerbs, collision meshes, safety floor and spawn marker. |
| `build_environment_blender.py` | Applies the transferred placements and factory-owned asset libraries to the base blend. |
| `procedural_assets_blender.py` | Creates procedural cards/geometry and applies transforms. |
| `procedural_materials_blender.py` | Builds Blender materials; locally modified with asset-free flat fallbacks for this quick test. |
| `terrain_grid.py` | Deterministic terrain and height authority. |
| `safety_barrier_layout.py` | Compiles barrier segments from the transferred layout manifest. |
| `building_asset_library.py` | Reads the building library that the factory must generate. |
| `procedural_catalog.py`, `vegetation_distribution.py` | Biome and procedural placement contracts. |
| `curb_manifest.py` | Loads and validates curb profiles. |
| `blender_output.py` | Atomic `.blend`/GLB publication helpers. |
| `validate_*.py` | Minimal geometry, environment and integration validators. |
| `configs/la_chutana_factory.json` | Factory-local adaptation of the active track config. |
| `manifests/` | Track-specific curb, vegetation and barrier layout inputs; these are data contracts, not assets. |
| `layouts/la_chutana/` | Semantic layout and trackside object catalog. |
| `data/la_chutana_reference.json` | Reference dimensions/tolerances used by validation. |

### `scripts/`

| File | Purpose |
|---|---|
| `prepare_la_chutana_inputs.py` | Copies the immutable input snapshots and maps tree/bush paths to approved LOD0 assets under `procedural/generated/vegetation_v5/`. |
| `preflight_la_chutana.py` | Read-only check of files required by Base or Environment mode. |
| `build_la_chutana_quick_test.ps1` | Single entry point for staging, preflight, Blender build and validation. |

### Generated/output directories

| Directory | Purpose |
|---|---|
| `blender/generated/la_chutana/` | Disposable working data and `.blend` files. The transferred centerline/placements here are regenerated from `inputs/`. |
| `output/la_chutana/` | GLB products of this factory-owned test. |

## Assets the factory still owns and must provide

Environment mode intentionally remains blocked until the factory generates:

- Building GLBs and `game/resources/environment/assets/buildings/building_manifest.json`.
- Barrier GLBs and `game/resources/environment/assets/barriers/barrier_manifest_v3.json` compatible with the active config.
- Any desired texture bank at `track-studio/blender/generated/la_chutana/textures/active_manifest.json`.

Trees and bushes resolve to `procedural/generated/vegetation_v5/assets/`. Grass cards can use procedural flat materials during
the quick test. No source or generated asset should be copied from Formula90s to
satisfy these requirements.

## Deliberately excluded

- Track Studio Rust workspace.
- TypeScript/Tauri editor frontend.
- Godot project and runtime DLLs.
- Formula90s vehicle/gameplay code.
- Every `.glb`, `.png`, `.blend`, DLL and generated texture from Formula90s.

The transferred scripts are expected to be modified or simplified inside the
factory after this proof succeeds.
