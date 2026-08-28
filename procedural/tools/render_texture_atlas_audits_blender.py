from __future__ import annotations

import json
import math
import os
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args_after_double_dash() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def make_material(atlas_path: Path, alpha_cutoff: float) -> bpy.types.Material:
    material = bpy.data.materials.new("foliage_alpha_mask")
    material.use_nodes = True
    material.surface_render_method = "DITHERED"
    material.use_transparency_overlap = False
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(atlas_path), check_existing=False)
    texture.interpolation = "Linear"
    shader.inputs["Roughness"].default_value = 0.86
    shader.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.24
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material["gltf_alpha_mode"] = "MASK"
    material["gltf_alpha_cutoff"] = float(alpha_cutoff)
    material["double_sided"] = True
    return material


def make_wood_material(bark_path: Path) -> bpy.types.Material:
    material = bpy.data.materials.new("wood_audit")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(bark_path), check_existing=False)
    texture.extension = "REPEAT"
    coordinates = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (3.0, 5.0, 1.0)
    links.new(coordinates.outputs["UV"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value = 0.92
    material["source_texture"] = bark_path.name
    material["seamless"] = True
    return material


def cylinder_between(name: str, start: Vector, end: Vector, radius_start: float, radius_end: float, material: bpy.types.Material) -> bpy.types.Object:
    direction = end - start
    midpoint = (start + end) * 0.5
    bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=radius_start, radius2=radius_end, depth=direction.length, end_fill_type="NGON", location=midpoint)
    obj = bpy.context.object
    obj.name = name
    obj.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    obj.data.materials.append(material)
    return obj


def make_cards(name: str, cards: list[dict], regions: list[dict], material: bpy.types.Material) -> bpy.types.Object:
    vertices, faces, uv_per_vertex = [], [], []
    for index, card in enumerate(cards):
        region = regions[index % len(regions)]
        u0, v0, u1, v1 = region["uv_bottom_left"]
        yaw = float(card["yaw"])
        horizontal = Vector((math.cos(yaw), math.sin(yaw), 0.0))
        vertical = Vector((0.0, 0.0, 1.0))
        center = Vector(card["center"])
        half_w, half_h = float(card["width"]) * 0.5, float(card["height"]) * 0.5
        base = len(vertices)
        vertices.extend((
            center - horizontal * half_w - vertical * half_h,
            center + horizontal * half_w - vertical * half_h,
            center + horizontal * half_w + vertical * half_h,
            center - horizontal * half_w + vertical * half_h,
        ))
        faces.append((base, base + 1, base + 2, base + 3))
        uv_per_vertex.extend(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uv_per_vertex[loop.vertex_index]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def tree_geometry(regions: list[dict], foliage: bpy.types.Material, wood: bpy.types.Material) -> list[bpy.types.Object]:
    objects = [cylinder_between("trunk", Vector((0, 0, 0)), Vector((0.08, 0, 6.2)), 0.36, 0.11, wood)]
    for index in range(7):
        phase = index * math.tau / 7 + 0.23
        start = Vector((0.03 * math.cos(phase), 0.03 * math.sin(phase), 2.5 + (index % 3) * 0.65))
        end = Vector((2.7 * math.cos(phase), 2.2 * math.sin(phase), 4.8 + (index % 2) * 0.7))
        objects.append(cylinder_between(f"branch_{index}", start, end, 0.13, 0.035, wood))
    cards = []
    for index in range(28):
        phase = index * 2.399963229728653
        layer = index % 5
        radius = 1.0 + 0.42 * layer
        cards.append({
            "center": (math.cos(phase) * radius, math.sin(phase) * radius * 0.82, 3.35 + 0.55 * (index % 7)),
            "yaw": phase + math.pi * 0.5 + (index % 3 - 1) * 0.22,
            "width": 2.15 + 0.18 * (index % 4),
            "height": 1.65 + 0.14 * (index % 3),
        })
    objects.append(make_cards("foliage_cards", cards, regions, foliage))
    return objects


def bush_geometry(regions: list[dict], foliage: bpy.types.Material, wood: bpy.types.Material) -> list[bpy.types.Object]:
    objects = []
    for index in range(7):
        phase = index * math.tau / 7 + 0.31
        start = Vector((0, 0, 0.03))
        end = Vector((1.15 * math.cos(phase), 0.9 * math.sin(phase), 1.55 + 0.16 * (index % 3)))
        objects.append(cylinder_between(f"stem_{index}", start, end, 0.07, 0.018, wood))
    cards = []
    for index in range(24):
        phase = index * 2.399963229728653
        radius = 0.35 + 0.13 * (index % 8)
        cards.append({
            "center": (math.cos(phase) * radius, math.sin(phase) * radius * 0.8, 0.72 + 0.16 * (index % 7)),
            "yaw": phase + math.pi * 0.5,
            "width": 1.35 + 0.12 * (index % 3),
            "height": 1.1 + 0.10 * (index % 4),
        })
    objects.append(make_cards("foliage_cards", cards, regions, foliage))
    return objects


def conifer_geometry(regions: list[dict], foliage: bpy.types.Material, wood: bpy.types.Material) -> list[bpy.types.Object]:
    objects = [cylinder_between("trunk", Vector((0, 0, 0)), Vector((0, 0, 7.4)), 0.28, 0.055, wood)]
    cards = []
    index = 0
    for layer in range(9):
        z = 1.1 + layer * 0.72
        # Audit v2: half the previous 2.55 m reach. The ninth crown layer
        # closes the former bare gap below the 7.4 m trunk tip.
        radius = max(0.20, 1.275 * (1.0 - layer / 9.5))
        for branch in range(6):
            phase = branch * math.tau / 6 + layer * 0.31
            end = Vector((radius * math.cos(phase), radius * math.sin(phase), z + 0.10))
            objects.append(cylinder_between(f"branch_{layer}_{branch}", Vector((0, 0, z)), end, 0.065, 0.012, wood))
            cards.append({"center": (end.x * 0.92, end.y * 0.92, z + 0.28), "yaw": phase + math.pi * 0.5, "width": 1.15 + radius * 0.32, "height": 0.92 + radius * 0.12})
            index += 1
    objects.append(make_cards("foliage_cards", cards, regions, foliage))
    return objects


def setup_render(family: str) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.world.color = (0.028, 0.034, 0.040)
    scene.view_settings.look = "AgX - Medium High Contrast"
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, -0.02))
    ground = bpy.context.object
    ground.name = "audit_ground"
    ground_material = bpy.data.materials.new("audit_ground_material")
    ground_material.diffuse_color = (0.075, 0.083, 0.085, 1.0)
    ground.data.materials.append(ground_material)
    target_z = 3.5 if family != "bush" else 1.0
    extent = 8.8 if family != "bush" else 4.2
    camera_position = Vector((9.5, -13.0, 7.8)) if family != "bush" else Vector((5.0, -7.0, 3.6))
    bpy.ops.object.camera_add(location=camera_position)
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = extent
    look_at(camera, Vector((0, 0, target_z)))
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(4.5, -5.5, 9.0))
    key = bpy.context.object
    key.data.energy = 950
    key.data.shape = "DISK"
    key.data.size = 6.0
    look_at(key, Vector((0, 0, target_z)))
    bpy.ops.object.light_add(type="AREA", location=(-5.0, 2.0, 5.0))
    fill = bpy.context.object
    fill.data.energy = 380
    fill.data.size = 5.0
    look_at(fill, Vector((0, 0, target_z)))
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 8))
    bpy.context.object.data.energy = 1.4
    bpy.context.object.rotation_euler = (math.radians(28), math.radians(-22), math.radians(145))


def patch_glb_alpha_mask(path: Path, cutoff: float) -> None:
    """Blender 5 exports dithered Eevee transparency as BLEND. The runtime
    contract is alpha test, so rewrite only the glTF material declaration while
    preserving geometry, embedded image and binary buffer chunks."""
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        raise ValueError(f"not a GLB: {path}")
    offset, chunks = 12, []
    while offset < len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        chunks.append((kind, raw[offset:offset + length]))
        offset += length
    json_kind = 0x4E4F534A
    document = json.loads(next(data for kind, data in chunks if kind == json_kind).decode("utf-8").rstrip(" \x00"))
    changed = 0
    for material in document.get("materials", []):
        pbr = material.get("pbrMetallicRoughness", {})
        if "baseColorTexture" not in pbr or "foliage" not in material.get("name", "").lower():
            continue
        material["alphaMode"] = "MASK"
        material["alphaCutoff"] = float(cutoff)
        material["doubleSided"] = True
        changed += 1
    if changed != 1:
        raise ValueError(f"expected one textured foliage material in {path}, found {changed}")
    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    rebuilt_chunks = []
    for kind, data in chunks:
        rebuilt_chunks.append((kind, json_bytes if kind == json_kind else data))
    total = 12 + sum(8 + len(data) for _kind, data in rebuilt_chunks)
    output = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    for kind, data in rebuilt_chunks:
        output.extend(struct.pack("<II", len(data), kind))
        output.extend(data)
    path.write_bytes(output)


def render_one(repo: Path, atlas_manifest_path: Path, review_root: Path, model_root: Path) -> dict:
    clear_scene()
    manifest = json.loads(atlas_manifest_path.read_text(encoding="utf-8"))
    atlas_path = repo / manifest["atlas"]
    foliage = make_material(atlas_path, float(manifest["alpha_cutoff"]))
    bark_manifest = json.loads((repo / "procedural/generated/texture_pipeline/wood/conifer_bark_035_seamless.json").read_text(encoding="utf-8"))
    wood = make_wood_material(repo / bark_manifest["path"])
    family = manifest["family"]
    if family == "bush":
        asset_objects = bush_geometry(manifest["regions"], foliage, wood)
    elif family == "conifer":
        asset_objects = conifer_geometry(manifest["regions"], foliage, wood)
    else:
        asset_objects = tree_geometry(manifest["regions"], foliage, wood)
    setup_render(family)
    review_root.mkdir(parents=True, exist_ok=True)
    render_path = review_root / f"{manifest['id']}_blender_audit.png"
    bpy.context.scene.render.filepath = str(render_path)
    bpy.ops.render.render(write_still=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in asset_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = asset_objects[0]
    model_root.mkdir(parents=True, exist_ok=True)
    glb_path = model_root / f"{manifest['id']}_material_test.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True, export_yup=True)
    patch_glb_alpha_mask(glb_path, float(manifest["alpha_cutoff"]))
    return {
        "id": manifest["id"],
        "family": family,
        "atlas_manifest": atlas_manifest_path.resolve().relative_to(repo).as_posix(),
        "render": render_path.resolve().relative_to(repo).as_posix(),
        "material_test_glb": glb_path.resolve().relative_to(repo).as_posix(),
        "blender_version": bpy.app.version_string,
    }


def main() -> int:
    args = args_after_double_dash()
    repo = Path.cwd()
    if "--repo" in args:
        repo = Path(args[args.index("--repo") + 1])
    repo = repo.resolve()
    output = repo / "procedural/generated/texture_pipeline"
    atlas_root = output / "atlases"
    review_root = output / "review"
    model_root = output / "material_tests"
    records = [render_one(repo, path, review_root, model_root) for path in sorted(atlas_root.glob("*.json"))]
    report = {"schema_version": 1, "generator": "blender_texture_atlas_audit_v1", "records": records}
    report_path = output / "blender_audit_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
