from __future__ import annotations

import argparse
import math
from pathlib import Path

import bpy
from mathutils import Vector


def args_after_double_dash() -> list[str]:
    return __import__("sys").argv[__import__("sys").argv.index("--") + 1 :] if "--" in __import__("sys").argv else []


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def mix(a: tuple[float, float, float], b: tuple[float, float, float], amount: float) -> tuple[float, float, float]:
    return tuple(a[index] * (1.0 - amount) + b[index] * amount for index in range(3))


def noise(point: Vector, seed: float) -> float:
    value = math.sin(point.x * 12.9898 + point.y * 78.233 + point.z * 37.719 + seed) * 43758.5453
    return value - math.floor(value)


def set_srgb(element, color: tuple[float, float, float, float]) -> None:
    if hasattr(element, "color_srgb"):
        element.color_srgb = color
    else:
        element.color = color


def ensure_vertex_material(obj: bpy.types.Object, name: str, roughness: float) -> None:
    mesh = obj.data
    color = mesh.color_attributes.active_color or (mesh.color_attributes[0] if mesh.color_attributes else None)
    if color is None:
        color = mesh.color_attributes.new(name="COLOR_0", type="BYTE_COLOR", domain="CORNER")
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    vertex = nodes.new("ShaderNodeVertexColor")
    vertex.layer_name = color.name
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Specular IOR Level"].default_value = 0.18
    links.new(vertex.outputs["Color"], shader.inputs["Base Color"])
    links.new(output.inputs["Surface"], shader.outputs["BSDF"])
    mesh.materials.clear()
    mesh.materials.append(material)


def paint_mesh(obj: bpy.types.Object, role: str, minimum_z: float, maximum_z: float, canopy_center: Vector, canopy_radius: float) -> None:
    mesh = obj.data
    mesh.calc_loop_triangles()
    color = mesh.color_attributes.active_color or (mesh.color_attributes[0] if mesh.color_attributes else None)
    if color is None or color.domain != "CORNER":
        if color is not None:
            mesh.color_attributes.remove(color)
        color = mesh.color_attributes.new(name="COLOR_0", type="BYTE_COLOR", domain="CORNER")
    light_direction = Vector((-0.35, -0.45, 0.82)).normalized()
    height_span = max(maximum_z - minimum_z, 1e-6)
    for polygon in mesh.polygons:
        normal = (obj.matrix_world.to_3x3() @ polygon.normal).normalized()
        light = clamp(0.5 + 0.5 * normal.dot(light_direction))
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
            point = obj.matrix_world @ vertex.co
            height = clamp((point.z - minimum_z) / height_span)
            grain = noise(point, 19.0 if role == "wood" else 73.0)
            if role == "wood":
                root = (0.14, 0.055, 0.025)
                copper = (0.43, 0.17, 0.065)
                sunlit = (0.72, 0.38, 0.16)
                bark = mix(root, copper, clamp(0.22 + height * 0.72))
                bark = mix(bark, sunlit, clamp(light * 0.38 + grain * 0.14))
                stripe = 0.84 + 0.20 * (0.5 + 0.5 * math.sin(point.z * 7.0 + point.x * 3.0))
                painted = tuple(clamp(channel * stripe) for channel in bark)
            else:
                radial = min(1.0, (Vector((point.x, point.y, point.z)) - canopy_center).length / max(canopy_radius, 1e-6))
                deep = (0.075, 0.105, 0.035)
                olive = (0.28, 0.38, 0.105)
                leaf = (0.48, 0.57, 0.19)
                gold = (0.70, 0.62, 0.27)
                exposure = clamp(radial * 0.52 + height * 0.24 + light * 0.36)
                painted = mix(deep, olive, clamp(exposure * 1.35))
                painted = mix(painted, leaf, clamp((exposure - 0.36) * 1.15))
                if grain > 0.86:
                    painted = mix(painted, gold, (grain - 0.86) * 3.2)
                variation = 0.88 + grain * 0.22
                painted = tuple(clamp(channel * variation) for channel in painted)
            set_srgb(color.data[loop_index], (*painted, 1.0))
    mesh.update()


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(args_after_double_dash())
    input_path, output_path = args.input.resolve(), args.output.resolve()

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 2:
        raise RuntimeError(f"expected wood+foliage meshes, got {[obj.name for obj in meshes]}")
    world_vertices = [obj.matrix_world @ vertex.co for obj in meshes for vertex in obj.data.vertices]
    minimum_z, maximum_z = min(point.z for point in world_vertices), max(point.z for point in world_vertices)
    minimum_x, maximum_x = min(point.x for point in world_vertices), max(point.x for point in world_vertices)
    minimum_y, maximum_y = min(point.y for point in world_vertices), max(point.y for point in world_vertices)
    canopy_center = Vector(((minimum_x + maximum_x) * 0.5, (minimum_y + maximum_y) * 0.5, minimum_z + (maximum_z - minimum_z) * 0.70))
    canopy_radius = max(maximum_x - minimum_x, maximum_y - minimum_y, (maximum_z - minimum_z) * 0.52) * 0.55

    for obj in meshes:
        role = "foliage" if "foliage" in obj.name.lower() else "wood"
        paint_mesh(obj, role, minimum_z, maximum_z, canopy_center, canopy_radius)
        ensure_vertex_material(obj, f"Painted_{role}", 0.92 if role == "wood" else 0.84)

    horizontal_span = max(maximum_x - minimum_x, maximum_y - minimum_y)
    height_span = maximum_z - minimum_z
    preview_span = max(horizontal_span, height_span, 0.5)
    bpy.ops.mesh.primitive_plane_add(size=max(4.0, preview_span * 3.8), location=(0.0, 0.0, minimum_z - 0.025))
    ground = bpy.context.object
    ground_material = bpy.data.materials.new("Warm dry ground")
    ground_material.diffuse_color = (0.13, 0.095, 0.045, 1.0)
    ground.data.materials.append(ground_material)

    bpy.ops.object.light_add(type="AREA", location=(-5.0, -6.0, maximum_z + 5.0))
    key = bpy.context.object
    key.data.energy = 950.0
    key.data.shape = "DISK"
    key.data.size = 7.0
    look_at(key, canopy_center)
    bpy.ops.object.light_add(type="AREA", location=(5.0, 2.0, maximum_z * 0.58))
    fill = bpy.context.object
    fill.data.energy = 420.0
    fill.data.color = (0.55, 0.68, 1.0)
    fill.data.size = 5.0
    look_at(fill, canopy_center)
    bpy.ops.object.light_add(type="SUN", location=(0.0, 0.0, maximum_z + 2.0))
    sun = bpy.context.object
    sun.rotation_euler = (math.radians(28.0), math.radians(-22.0), math.radians(-35.0))
    sun.data.energy = 1.8
    sun.data.angle = math.radians(12.0)

    target = Vector((canopy_center.x, canopy_center.y, minimum_z + height_span * 0.48))
    bpy.ops.object.camera_add(location=(
        target.x + preview_span * 1.24,
        target.y - preview_span * 1.62,
        minimum_z + height_span * 0.78,
    ))
    camera = bpy.context.object
    camera.data.lens = 58.0
    look_at(camera, target)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.world.color = (0.025, 0.035, 0.055)
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.filepath = str(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    print(f"PAINT_PREVIEW={output_path}")


if __name__ == "__main__":
    main()
