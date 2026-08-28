from __future__ import annotations

import argparse
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def args_after_dash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                       bpy.data.cameras, bpy.data.lights):
        for item in list(collection):
            if item.users == 0:
                collection.remove(item)


def texture_material(name: str, texture: Path, roughness: float, metallic: float = 0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.use_backface_culling = False
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    image = nodes.new("ShaderNodeTexImage")
    image.image = bpy.data.images.load(str(texture), check_existing=True)
    image.interpolation = "Linear"
    image.extension = "REPEAT"
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    links.new(image.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def material_library(texture_root: Path, wall_texture: str):
    return {
        "Walls": texture_material("MAT_Wall_Retextured", texture_root / wall_texture, 0.92),
        "Roof": texture_material("MAT_Roof_Terracotta_Retextured", texture_root / "terracotta_roof_albedo.png", 0.84),
        "Wood": texture_material("MAT_Wood_Retextured", texture_root / "wood_dark_albedo.png", 0.88),
        "Stone": texture_material("MAT_Stone_Retextured", texture_root / "stone_foundation_albedo.png", 0.96),
        "Windows": texture_material("MAT_Window_Retextured", texture_root / "window_dark_albedo.png", 0.32),
    }


def import_and_map(source: Path, texture_root: Path, wall_texture: str):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(source))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    materials = material_library(texture_root, wall_texture)
    meshes = []
    for obj in imported:
        if obj.type != "MESH":
            continue
        key = next((key for key in materials if key.lower() in obj.name.lower()), None)
        if key is None:
            raise RuntimeError(f"No material mapping for {obj.name}")
        if not obj.data.uv_layers:
            raise RuntimeError(f"Missing UV map: {obj.name}")
        obj.data.materials.clear()
        obj.data.materials.append(materials[key])
        meshes.append(obj)
    if len(meshes) != 5:
        raise RuntimeError(f"Expected five mapped meshes in {source}, got {len(meshes)}")
    return imported, meshes


def export_house(source: Path, destination: Path, texture_root: Path, wall_texture: str):
    clear_scene()
    imported, meshes = import_and_map(source, texture_root, wall_texture)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in imported:
        obj.select_set(True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(destination), export_format="GLB", use_selection=True,
        export_texcoords=True, export_normals=True, export_materials="EXPORT",
        export_image_format="AUTO", export_yup=True,
    )
    return len(meshes)


def look_at(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def render_catalog(outputs: list[Path], texture_root: Path, review_path: Path):
    clear_scene()
    all_meshes = []
    for index, output in enumerate(outputs):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(output))
        imported = [obj for obj in bpy.data.objects if obj not in before]
        meshes = [obj for obj in imported if obj.type == "MESH"]
        center_x = -5.0 if index == 0 else 5.0
        for obj in imported:
            obj.location.x += center_x
        all_meshes.extend(meshes)
    bpy.ops.mesh.primitive_plane_add(size=32, location=(0, 0, -0.03))
    ground = bpy.context.object
    ground.data.materials.append(texture_material("Ground", texture_root / "stone_foundation_albedo.png", 1.0))
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.055, 0.07, 0.09, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.28
    bpy.ops.object.light_add(type="AREA", location=(-7, -8, 14))
    bpy.context.object.data.energy = 1800
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 8
    bpy.ops.object.light_add(type="AREA", location=(10, 2, 9))
    bpy.context.object.data.energy = 900
    bpy.context.object.data.size = 7
    bpy.ops.object.camera_add(location=(0, -34, 11.5))
    camera = bpy.context.object
    camera.data.lens = 52
    look_at(camera, (0, 0, 4.6))
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(review_path)
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--house-01", type=Path, required=True)
    parser.add_argument("--house-02", type=Path, required=True)
    ns = parser.parse_args(args_after_dash())
    repo = ns.repo.resolve()
    output = repo / "game/resources/environment/assets/buildings"
    textures = output / "textures"
    destinations = [output / "house-peru-01.glb", output / "house-peru-02.glb"]
    export_house(ns.house_01.resolve(), destinations[0], textures, "adobe_warm_albedo.png")
    export_house(ns.house_02.resolve(), destinations[1], textures, "plaster_white_albedo.png")
    render_catalog(destinations, textures, output / "review/building_retexture_catalog.png")
    print(f"PASS retextured {len(destinations)} houses -> {output}")


if __name__ == "__main__":
    main()
