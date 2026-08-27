# Terrain bank layer 4

This pass fixes the final static-model extraction issue: several CPU records contain an early false-positive index descriptor. The valid descriptor is selected by validating index-domain against the vertex buffer and preferring the descriptor located at/after the vertex-buffer end with minimal alignment padding.

Decoded GLB: 135/135. Newly decoded in layer 4: 21. Remaining: 0.

- 005_people.model.ru_entity_clipboard: decoded_correct_index_descriptor — 24 vertices, 12 tris, index offset 672, pad 0 bytes
- 035_bridges.model.ru_model_pcube18ru_entity_cattlegrid.ru_body_upright1: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 036_bridges.model.ru_model_pcube18ru_entity_cattlegrid.ru_body_upright2: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 037_bridges.model.ru_model_pcube14ru_entity_cattlegrid.ru_body_plank2: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 038_bridges.model.ru_model_pcube14ru_entity_cattlegrid.ru_body_plank1: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 039_bridges.model.ru_model_pcube18ru_entity_cattlegrid.ru_body_upright1_11: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 040_bridges.model.ru_model_pcube18ru_entity_cattlegrid.ru_body_upright2_12: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 041_bridges.model.ru_model_pcube14ru_entity_cattlegrid.ru_body_plank2_13: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 042_bridges.model.ru_model_pcube14ru_entity_cattlegrid.ru_body_plank1_14: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 046_bridges.model.ru_model_pcube18ru_entity_cattlegrid_uk_wide.ru_body_upright1: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 047_bridges.model.ru_model_pcube18ru_entity_cattlegrid_uk_wide.ru_body_upright2: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 048_bridges.model.ru_model_pcube14ru_entity_cattlegrid_uk_wide.ru_body_plank2: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 049_bridges.model.ru_model_pcube14ru_entity_cattlegrid_uk_wide.ru_body_plank1: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 050_bridges.model.ru_model_pcube18ru_entity_cattlegrid_uk_wide.ru_body_upright1_7: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 051_bridges.model.ru_model_pcube18ru_entity_cattlegrid_uk_wide.ru_body_upright2_8: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 052_bridges.model.ru_model_pcube14ru_entity_cattlegrid_uk_wide.ru_body_plank2_9: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 053_bridges.model.ru_model_pcube14ru_entity_cattlegrid_uk_wide.ru_body_plank1_10: decoded_correct_index_descriptor — 96 vertices, 48 tris, index offset 2688, pad 0 bytes
- 055_bridges.model.ru_entity_lowfence_bridgeside: decoded_correct_index_descriptor — 261 vertices, 95 tris, index offset 7312, pad 4 bytes
- 056_bridges.model.ru_entity_lowfence_bridgestart: decoded_correct_index_descriptor — 268 vertices, 96 tris, index offset 7504, pad 0 bytes
- 093_largesign.model.ru_entity_largesign: decoded_correct_index_descriptor — 120 vertices, 60 tris, index offset 3360, pad 0 bytes
- 125_mailbox.model.ru_model_group1ru_entity_mailbox.ru_body_bottom: decoded_correct_index_descriptor — 128 vertices, 48 tris, index offset 3584, pad 0 bytes
