from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def args_after_dash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    ns = parser.parse_args(args_after_dash())
    repo = ns.repo.resolve()
    glb = repo / "game/resources/environment/assets/barriers/secondary_fence/barrier_fence_concrete_steel_4m.glb"
    output = repo / "game/resources/environment/assets/barriers/secondary_fence/review/fence_module.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    world = bpy.data.worlds.new("FencePreviewWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.08, 0.10, 0.13, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55
    bpy.ops.object.light_add(type="AREA", location=(-3.0, -4.0, 6.0))
    bpy.context.object.data.energy = 1100
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 5.0
    bpy.ops.object.light_add(type="AREA", location=(4.0, 1.0, 3.0))
    bpy.context.object.data.energy = 650
    bpy.context.object.data.size = 4.0
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, -0.01))
    ground = bpy.context.object
    mat = bpy.data.materials.new("Ground")
    mat.diffuse_color = (0.16, 0.14, 0.11, 1)
    ground.data.materials.append(mat)
    bpy.ops.object.camera_add(location=(5.4, -7.8, 4.2))
    camera = bpy.context.object
    camera.data.lens = 58
    look_at(camera, (0, 0, 1.65))
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    scene.view_settings.look = "AgX - Medium High Contrast"
    bpy.ops.render.render(write_still=True)
    print(f"[preview] wrote {output}")


if __name__ == "__main__":
    main()
