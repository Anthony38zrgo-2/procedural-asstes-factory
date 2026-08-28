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


def look_at(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def center_sample(points, fraction):
    index = int((fraction % 1.0) * len(points)) % len(points)
    before = points[(index - 2) % len(points)]
    after = points[(index + 2) % len(points)]
    point = points[index]
    tangent = Vector((after[0] - before[0], -(after[1] - before[1]), 0.0)).normalized()
    normal = Vector((-tangent.y, tangent.x, 0.0))
    return Vector((point[0], -point[1], 0.3)), tangent, normal


def ensure_lighting():
    for obj in list(bpy.data.objects):
        if obj.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    world = bpy.context.scene.world or bpy.data.worlds.new("AuditWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.18, 0.24, 0.34, 1.0)
    background.inputs["Strength"].default_value = 0.42
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 80))
    sun = bpy.context.object
    sun.rotation_euler = (math.radians(31), math.radians(-18), math.radians(-32))
    sun.data.energy = 2.4
    sun.data.angle = math.radians(18)


def add_camera(location, target, lens=42, ortho_scale=None):
    bpy.ops.object.camera_add(location=location)
    camera = bpy.context.object
    if ortho_scale is not None:
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = ortho_scale
    else:
        camera.data.lens = lens
    look_at(camera, target)
    bpy.context.scene.camera = camera
    return camera


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    ns = parser.parse_args(args_after_dash())
    repo = ns.repo.resolve()
    blend = repo / "track-studio/blender/generated/la_chutana/track_environment.blend"
    output = repo / "track-studio/output/la_chutana/audit"
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    ensure_lighting()
    centerline = json.loads((repo / "track-studio/blender/generated/la_chutana/centerline.json").read_text())
    points = centerline["points_xz"]
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"

    xs = [p[0] for p in points]
    ys = [-p[1] for p in points]
    center = Vector(((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, 0.0))
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    captures = []

    captures.append(("01_aerial_overview", (center.x, center.y, span * 0.92), center, 50, span * 1.16))
    for name, fraction, lateral, back, height, lens in (
        ("02_start_finish", 0.0, -9.0, 22.0, 5.0, 44),
        ("03_fast_curve", 0.12, 12.0, 18.0, 6.0, 48),
        ("04_chicane_barriers", 0.57, -10.0, 15.0, 4.0, 52),
        ("05_technical_section", 0.81, 13.0, 20.0, 7.0, 48),
        ("06_vegetation_trackside", 0.36, -18.0, 12.0, 8.0, 55),
    ):
        point, tangent, normal = center_sample(points, fraction)
        location = point + normal * lateral - tangent * back + Vector((0, 0, height))
        target = point + tangent * 18.0 + Vector((0, 0, 1.0))
        captures.append((name, location, target, lens, None))

    placement_doc = json.loads(
        (repo / "track-studio/blender/generated/la_chutana/placements.json").read_text()
    )
    buildings = [
        item for item in placement_doc["placements"]
        if item.get("category") == "fake_buildings"
    ]
    for index, asset_id in enumerate(("house_peru_01", "house_peru_02"), start=7):
        item = next((entry for entry in buildings if entry.get("building_asset_id") == asset_id), None)
        if item is None:
            continue
        x, z = item["position_xz"]
        target = Vector((x, -z, 2.6))
        yaw = -float(item.get("yaw_rad", 0.0))
        # Houses expose their detailed facade on the local side axis.
        view_direction = Vector((-math.sin(yaw), math.cos(yaw), 0.0))
        location = target - view_direction * 16.0 + Vector((0, 0, 6.0))
        captures.append((f"{index:02d}_{asset_id}", location, target, 58, None))

    # --- Mountain horizon audit views (Req. Capturas) ---
    # Center-based cardinal horizon looks to verify 360 continuity, scale, near delante far,
    # vertical orientation and absence of gaps/cards invertidas.
    # Four low horizon views + one diagonal low overview
    horizon_height = 8.0
    horizon_target_dist = 1150.0  # near radius
    horizon_up = 45.0  # target height for mountain peaks
    mountain_views = [
        ("09_mountain_north", Vector((center.x, center.y, horizon_height)), Vector((center.x, center.y + horizon_target_dist, horizon_up))),
        ("10_mountain_east", Vector((center.x, center.y, horizon_height)), Vector((center.x + horizon_target_dist, center.y, horizon_up))),
        ("11_mountain_south", Vector((center.x, center.y, horizon_height)), Vector((center.x, center.y - horizon_target_dist, horizon_up))),
        ("12_mountain_west", Vector((center.x, center.y, horizon_height)), Vector((center.x - horizon_target_dist, center.y, horizon_up))),
        ("13_mountain_low_overview", Vector((center.x - 320, center.y - 320, 42)), Vector((center.x, center.y, 22))),
    ]
    for name, loc, tgt in mountain_views:
        captures.append((name, loc, tgt, 38 if "low_overview" in name else 44, None))

    for old in [obj for obj in bpy.data.objects if obj.type == "CAMERA"]:
        bpy.data.objects.remove(old, do_unlink=True)
    for name, location, target, lens, ortho in captures:
        camera = add_camera(location, target, lens=lens, ortho_scale=ortho)
        scene.render.filepath = str(output / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(camera, do_unlink=True)
        print(f"[audit] wrote {scene.render.filepath}")


if __name__ == "__main__":
    main()
