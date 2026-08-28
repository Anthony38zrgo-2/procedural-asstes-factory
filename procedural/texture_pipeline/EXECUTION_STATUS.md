# Texture atlas pipeline — execution status

## Conifer V5 production pilot reached

The deterministic recovered-texture pipeline has been executed through the
visual-QA gate. The approved conifer treatment is now integrated into a new,
non-destructive V5 production family while the previous vegetation library is
kept intact.

## Original vegetation V5 expansion

- Retained the approved `tree_3d_02` and `tree_3d_03` silhouettes. The active
  tree catalog ends at `tree_3d_05`; IDs `01`, `04` and `05` are deterministic
  wider/lower derivatives of the approved sources.
- Preserved all six approved original bush silhouettes without overwriting the
  legacy GLBs.
- Archived 40 rejected tree GLBs and 12 associated audit renders under
  `procedural/generated/vegetation_v5/discarded_assets`.
- Preserved the five original material variants: green, copper, golden beige,
  red and yellow.
- Archived all 10 GLBs and both audit renders for removed `tree_3d_06`.
- Generated LOD0 and LOD1 for every material variant: 110 production GLBs.
- Added four deterministic seasonal atlases and seamless broadleaf/shrub bark.
- Consolidated every GLB into two draw meshes: textured wood and alpha-tested
  double-sided foliage.
- Tree budgets are 1,478–2,186 triangles for LOD0 and 846–1,242 for LOD1.
- Bush budgets are 554–716 triangles for LOD0 and 324–416 for LOD1.
- Independent rebuild result: 110/110 GLBs byte-identical.
- The complete repository suite passes 20 automated tests.

## Conifer audit iteration 2

- Reduced conifer branch reach from 2.55 m to 1.275 m before per-layer taper.
- Added a ninth foliage/branch tier and moved foliage-card centers to 92% of
  branch reach, closing the bare gap at the trunk tip.
- Selected recovered bark source `objects_core_035` for conifer wood.
- Generated `conifer_bark_035_seamless.png` with deterministic paired-edge
  feathering. Edge MAE changed from X=32.108074/Y=27.011719 to X=0/Y=0.
- Applied repeating bark UVs to both trunk and branches.
- Kept bark opaque while foliage remains double-sided `alphaMode=MASK`.

## Completed in this pilot

- Indexed all 140 recovered `objects_core` PNG sources.
- Preserved original source hashes and heuristic candidate names.
- Computed alpha, coverage, visible bounds, luminance and duplicate metrics.
- Created a visually verified allowlist of 16 vegetation and wood sources.
- Normalized RGB below alpha and generated edge dilation without changing alpha.
- Extracted 24 traceable sprites with source rectangles, anchors and axes.
- Generated four deterministic 512 px atlases and 256 px derivatives:
  - broadleaf green;
  - broadleaf mixed autumn;
  - bush green;
  - conifer green.
- Generated mip chains down to 64 px while preserving alpha-test coverage.
- Generated per-atlas manifests with source, recipe and output hashes.
- Generated Blender 5.2 material-test GLBs using `alphaMode=MASK` and
  double-sided foliage.
- Generated atlas, mip, source, sprite and Blender visual-audit PNGs.
- Verified four atlas builds byte-for-byte with an independent rebuild.
- Froze the approved texture outputs in `releases/v1/manifest.json` by SHA-256.
- Generated young, mature and irregular deterministic conifers, each as LOD0
  and LOD1 GLB assets.
- Consolidated each GLB into two draw meshes: opaque textured wood and
  double-sided alpha-tested foliage.
- Reduced LOD1 geometry by 58.3–62.2% while preserving all crown tiers.
- Rebuilt all six assets independently: 6/6 GLBs are byte-identical and 6/6
  decoded audit PNGs are pixel-identical.
- Passed 12 automated contract tests.

## Intentionally paused until V5 visual approval

- Publishing the generated catalog as production input.
- Replacing or deprecating the previous conifer generator.
- Integrating LOD switching distances into a target engine/runtime.
- Expanding to all recovered seasonal and blossom families.
- Producing engine-specific compressed DDS outputs.
- Freezing visual regression snapshots.

These tasks depend on whether the current source selection, density, alpha
cutoff and color treatment are approved.

## Primary review files

- `procedural/generated/conifers_v5/review/conifer_v5_lod_comparison.png`
- `procedural/generated/conifers_v5/manifest.json`
- `procedural/generated/conifers_v5/reproducibility_report.json`
- `procedural/generated/vegetation_v5/review/trees_v5_lod_comparison.png`
- `procedural/generated/vegetation_v5/review/bushes_v5_lod_comparison.png`
- `procedural/generated/vegetation_v5/review/vegetation_v5_seasonal_comparison.png`
- `procedural/generated/vegetation_v5/manifest.json`
- `procedural/generated/vegetation_v5/reproducibility_report.json`

- `procedural/generated/texture_pipeline/review/source_allowlist.png`
- `procedural/generated/texture_pipeline/review/extracted_sprites.png`
- `procedural/generated/texture_pipeline/review/broadleaf_green_512_atlas_audit.png`
- `procedural/generated/texture_pipeline/review/broadleaf_green_512_blender_audit.png`
- `procedural/generated/texture_pipeline/review/broadleaf_autumn_mixed_512_atlas_audit.png`
- `procedural/generated/texture_pipeline/review/broadleaf_autumn_mixed_512_blender_audit.png`
- `procedural/generated/texture_pipeline/review/bush_green_512_atlas_audit.png`
- `procedural/generated/texture_pipeline/review/bush_green_512_blender_audit.png`
- `procedural/generated/texture_pipeline/review/conifer_green_512_atlas_audit.png`
- `procedural/generated/texture_pipeline/review/conifer_green_512_blender_audit.png`

## Review questions

1. Are the green broadleaf sprites realistic enough, or should the source set be
   restricted to darker/smaller leaves?
2. Does the bush contain sufficient empty space, or should its alpha coverage be
   reduced?
3. Does the conifer atlas read as needles/branchlets at the intended distance?
4. Is the mixed autumn atlas too saturated or pink for the target art direction?
5. Are there visible halos, hard rectangular regions or excessive loss in the
   128 px and 64 px mip previews?
