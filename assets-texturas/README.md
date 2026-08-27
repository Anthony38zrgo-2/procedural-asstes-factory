# Recovered Styles Assets

Recovered from the supplied `styles.rar`.

## Contents
- `textures/terrain`: 124 decoded terrain textures (PNG + original DDS segments).
- `textures/objects_core`: 140 decoded object/vegetation textures.
- `textures/objects_styles`: 139 decoded style/sign/fence/sponsor textures.
- `sky`: 18 recovered JPEG sky presets.
- `metadata`: printable source metadata, source references, object/style names.
- `raw_compiled`: untouched CPU/GPU files for later mesh reverse engineering.
- `previews`: contact sheets.

## Important
The `.cpu/.gpu` object packs contain compiled geometry. Texture recovery is direct, but conversion of those mesh buffers to GLB/OBJ requires reverse engineering the proprietary vertex/index layout. No geometry has been fabricated.

The `candidate_source_name` fields in manifests are order-based candidates. They are reliable only where the original compiled ordering matches the source `<File>` ordering; counts differ in several packs, so verify before production renaming.
