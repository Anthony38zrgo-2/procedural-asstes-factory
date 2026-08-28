# Deterministic vegetation texture pipeline

This pipeline inventories recovered textures without modifying them, extracts a
reviewed set of foliage sprites, and packs deterministic 256/512 atlases.

Run from the repository root with the Python interpreter declared by the local
environment:

```powershell
python procedural/tools/build_texture_atlas_library.py --repo . --clean
python procedural/tools/build_texture_atlas_library.py --repo . --verify
```

Blender audits are generated separately so image processing remains usable in
headless Python environments:

```powershell
blender --background --python procedural/tools/render_texture_atlas_audits_blender.py -- --repo .
```

Generated review files live under
`procedural/generated/texture_pipeline/review`. Source images under
`assets-texturas` are treated as immutable.

The approved texture set is frozen by content hash in
`procedural/texture_pipeline/releases/v1/manifest.json`. Build the V5 conifer
production pilot and its visual comparison with:

```powershell
blender --background --python procedural/tools/build_conifer_v5_library_blender.py -- --repo .
python procedural/tools/build_conifer_v5_review.py --repo .
python -m unittest discover -s tests -v
```

V5 GLBs, manifests and audit PNGs are written under
`procedural/generated/conifers_v5`. The legacy vegetation assets are not
overwritten.

Build the complete V5 migration of the original broadleaf and bush catalog:

```powershell
blender --background --python procedural/tools/build_vegetation_v5_library_blender.py -- --repo .
python procedural/tools/build_vegetation_v5_review.py --repo .
python -m unittest discover -s tests -v
```

This produces 110 GLBs under `procedural/generated/vegetation_v5`: eleven base
silhouettes, five material variants and two LOD levels. The original files in
`procedural/assets` remain unchanged.

The current tree catalog uses `tree_3d_02` and `tree_3d_03` as approved source
silhouettes. IDs `01/04` are wider/lower derivatives of `02`; ID `05` is a
wider/lower derivative of `03`. The removed `tree_3d_06` and rejected prior V5
trees remain recoverable in
`procedural/generated/vegetation_v5/discarded_assets` and are excluded from the
production manifest.

## Grass V5 catalog extension

Build the deterministic grass atlases and the five-by-five card catalog:

```powershell
python procedural/tools/build_grass_texture_atlases.py --repo .
blender --background --python procedural/tools/build_grass_v5_library_blender.py -- --repo .
python procedural/tools/build_grass_v5_review.py --repo .
```

This adds 25 production GLBs under `procedural/generated/vegetation_v5/assets/grass`:
five grounded grass profiles in green, copper, golden beige, red and yellow.
The combined `catalog_manifest.json` exposes 135 vegetation GLBs while retaining
the original tree and bush manifest unchanged.

Generate the engine-facing global index with:

```powershell
python procedural/tools/build_vegetation_godot_index.py --repo .
```

`procedural/generated/vegetation_catalog_godot.json` indexes every tree, bush,
grass and conifer GLB with Godot paths, dimensions, converted AABBs, grounded
placement transforms, explicit LOD levels, hashes and visibility guidance.
