# Terrain Bank Layer 5 — Skeleton + Animation

Recovered exactly:
- 4 skeleton resources (hierarchy, node names, 4x4 bind/global matrices).
- 10 animation clip containers, including exact duration, FPS, frame count, node/bone counts and original compressed payload.
- Skeleton-only GLB files for inspection/import.

Animation keyframe compression:
- The MINA container and its timing/header are decoded.
- The proprietary compressed quaternion/translation key stream is preserved byte-for-byte but is not yet fully decoded to standard glTF channels.
- Three wind-turbine rotate GLBs are supplied as usable reconstructions using the exact recovered 4.958333 s / 24 FPS / 119-frame timing. Their rotation keys are reconstructed from the semantic `rotate` clip and are explicitly marked as reconstructed.

Human skeleton:
- 22 nodes, 18 animated bones. Names include Pelvis, Spine, SpineTop, shoulders, elbows, hands, hand sockets, neck/head, hips, knees, feet and toes.
- Human clips recovered as raw MINA payload + metadata: clipboard, standarmscrossed, video, photo, crouchphoto, crouchvideo, all.
