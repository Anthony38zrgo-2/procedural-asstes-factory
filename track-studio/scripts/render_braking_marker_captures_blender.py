"""Render driver-eye audit captures of the T1 and T4 braking-marker sequences."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def args_after_dash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def sample(points, fraction):
    count = len(points)
    position = (fraction % 1.0) * count
    index = int(math.floor(position)) % count
    alpha = position - math.floor(position)
    # Pipeline centerline stores X/Z; Blender environment maps circuit Z to -Y.
    current = Vector((points[index][0], -points[index][1], 0.0))
    following = Vector((points[(index + 1) % count][0], -points[(index + 1) % count][1], 0.0))
    return current.lerp(following, alpha)


def aim(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    ns = parser.parse_args(args_after_dash())
    repo = ns.repo.resolve()
    generated = repo / "track-studio/blender/generated/la_chutana"
    output = repo / "track-studio/output/la_chutana/captures/braking_markers"
    output.mkdir(parents=True, exist_ok=True)
    center = json.loads((generated / "centerline.json").read_text(encoding="utf-8"))
    points = center["points_xz"]
    lap_length = float(center["length_m"])

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.055, 0.075, 0.11)

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "BrakingMarkerAuditCamera"
    camera.data.lens = 52
    camera.data.sensor_width = 36
    scene.camera = camera

    bpy.ops.object.light_add(type="SUN")
    sun = bpy.context.object
    sun.name = "BrakingMarkerAuditSun"
    sun.rotation_euler = (math.radians(28), math.radians(-18), math.radians(24))
    sun.data.energy = 3.0
    sun.data.angle = math.radians(8)

    bpy.ops.object.light_add(type="AREA")
    fill = bpy.context.object
    fill.name = "BrakingMarkerAuditFill"
    fill.data.energy = 900
    fill.data.shape = "DISK"
    fill.data.size = 16

    zones = (("T1", 0.08), ("T4", 0.35))
    for label, braking_fraction in zones:
        camera_fraction = (braking_fraction - 225.0 / lap_length) % 1.0
        target_fraction = (braking_fraction - 185.0 / lap_length) % 1.0
        camera_base = sample(points, camera_fraction)
        target_base = sample(points, target_fraction)
        camera.location = (camera_base.x, camera_base.y, 2.05)
        target = (target_base.x, target_base.y, 1.15)
        aim(camera, target)
        fill.location = camera.location + Vector((0.0, 0.0, 8.0))
        fill.rotation_euler = (0.0, 0.0, 0.0)
        scene.render.filepath = str(output / f"la_chutana_{label.lower()}_braking_markers.png")
        bpy.ops.render.render(write_still=True)
        print(scene.render.filepath)


if __name__ == "__main__":
    main()
