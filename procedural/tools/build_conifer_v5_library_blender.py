from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args_after_double_dash() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def verify_texture_release(repo: Path, release: dict) -> tuple[dict, dict]:
    for group in ("atlases", "wood_materials"):
        for item in release[group]:
            path = repo / item["path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            actual = sha256(path)
            if actual != item["sha256"]:
                raise ValueError(f"texture release drift: {path} expected {item['sha256']} got {actual}")
    atlas = next(item for item in release["atlases"] if item["id"] == "conifer_green_512")
    wood = next(item for item in release["wood_materials"] if item["id"] == "conifer_bark_035_seamless")
    return atlas, wood


def atlas_regions(repo: Path, atlas_item: dict) -> tuple[list[dict], float]:
    manifest_path = repo / "procedural/generated/texture_pipeline/atlases" / f"{atlas_item['id']}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256(repo / manifest["atlas"]) != atlas_item["sha256"]:
        raise ValueError("atlas manifest does not resolve to the frozen texture")
    return manifest["regions"], float(manifest["alpha_cutoff"])


def make_foliage_material(atlas_path: Path, cutoff: float) -> bpy.types.Material:
    material = bpy.data.materials.new("foliage_conifer_alpha_mask")
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
    alpha_test = nodes.new("ShaderNodeMath")
    alpha_test.operation = "GREATER_THAN"
    alpha_test.inputs[1].default_value = float(cutoff)
    texture.image = bpy.data.images.load(str(atlas_path), check_existing=False)
    texture.interpolation = "Linear"
    shader.inputs["Roughness"].default_value = 0.88
    shader.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.22
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(texture.outputs["Alpha"], alpha_test.inputs[0])
    links.new(alpha_test.outputs[0], shader.inputs["Alpha"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material["gltf_alpha_mode"] = "MASK"
    material["gltf_alpha_cutoff"] = cutoff
    material["double_sided"] = True
    return material


def make_wood_material(bark_path: Path) -> bpy.types.Material:
    material = bpy.data.materials.new("wood_conifer_seamless")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(bark_path), check_existing=False)
    texture.extension = "REPEAT"
    texture.interpolation = "Linear"
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value = 0.94
    shader.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.18
    material["seamless"] = True
    material["texture_repeat"] = True
    return material


def add_tube(
    name: str,
    points: list[Vector],
    radii: list[float],
    sides: int,
    material: bpy.types.Material,
    texture_length: float,
    circumference_repeat: float = 1.0,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    face_uvs: list[list[tuple[float, float]]] = []
    distances = [0.0]
    for index in range(1, len(points)):
        distances.append(distances[-1] + (points[index] - points[index - 1]).length)
    for index, (point, radius) in enumerate(zip(points, radii)):
        if index == 0:
            tangent = (points[1] - points[0]).normalized()
        elif index == len(points) - 1:
            tangent = (points[-1] - points[-2]).normalized()
        else:
            tangent = (points[index + 1] - points[index - 1]).normalized()
        reference = Vector((0.0, 0.0, 1.0))
        if abs(tangent.dot(reference)) > 0.94:
            reference = Vector((0.0, 1.0, 0.0))
        axis_x = tangent.cross(reference).normalized()
        axis_y = tangent.cross(axis_x).normalized()
        for side in range(sides + 1):
            angle = math.tau * side / sides
            vertex = point + radius * (math.cos(angle) * axis_x + math.sin(angle) * axis_y)
            vertices.append(tuple(vertex))
    ring = sides + 1
    for segment in range(len(points) - 1):
        v0 = distances[segment] / texture_length
        v1 = distances[segment + 1] / texture_length
        for side in range(sides):
            a = segment * ring + side
            b = a + 1
            c = (segment + 1) * ring + side + 1
            d = c - 1
            faces.append((a, b, c, d))
            u0 = side / sides * circumference_repeat
            u1 = (side + 1) / sides * circumference_repeat
            face_uvs.append([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def add_cards(name: str, cards: list[dict], regions: list[dict], material: bpy.types.Material) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    face_uvs: list[list[tuple[float, float]]] = []
    for card_index, card in enumerate(cards):
        region = regions[card_index % len(regions)]
        u0, v0, u1, v1 = region["uv_bottom_left"]
        center = Vector(card["center"])
        direction = Vector(card["direction"]).normalized()
        for cross in range(2):
            yaw = math.atan2(direction.y, direction.x) + math.pi * 0.5 + cross * math.pi * 0.5
            horizontal = Vector((math.cos(yaw), math.sin(yaw), 0.0))
            vertical = Vector((-direction.x * 0.16, -direction.y * 0.16, 1.0)).normalized()
            half_w = float(card["width"]) * 0.5
            half_h = float(card["height"]) * 0.5
            base = len(vertices)
            vertices.extend(
                [
                    tuple(center - horizontal * half_w - vertical * half_h),
                    tuple(center + horizontal * half_w - vertical * half_h),
                    tuple(center + horizontal * half_w + vertical * half_h),
                    tuple(center - horizontal * half_w + vertical * half_h),
                ]
            )
            faces.append((base, base + 1, base + 2, base + 3))
            face_uvs.append([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def join_objects(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    joined = bpy.context.object
    joined.name = name
    joined.data.name = name + "_mesh"
    return joined


def sampled_indices(count: int, fraction: float) -> list[int]:
    wanted = max(2, round(count * fraction))
    if wanted >= count:
        return list(range(count))
    return sorted({round(index * (count - 1) / (wanted - 1)) for index in range(wanted)})


def trunk_point(asset: dict, z: float) -> Vector:
    height = float(asset["height"])
    lean_x, lean_y = asset["lean"]
    t = z / height
    return Vector((float(lean_x) * height * t * t, float(lean_y) * height * t * t, z))


def build_geometry(asset: dict, lod_name: str, lod: dict, regions: list[dict], foliage, wood) -> list[bpy.types.Object]:
    rng = random.Random(int(asset["seed"]) + (0 if lod_name == "lod0" else 100000))
    objects: list[bpy.types.Object] = []
    height = float(asset["height"])
    trunk_segments = 10 if lod_name == "lod0" else 7
    trunk_points = [trunk_point(asset, height * index / trunk_segments) for index in range(trunk_segments + 1)]
    base_radius = float(asset["trunk_base_radius"])
    trunk_radii = [max(base_radius * 0.13, base_radius * (1.0 - 0.87 * index / trunk_segments)) for index in range(trunk_segments + 1)]
    objects.append(add_tube("trunk", trunk_points, trunk_radii, int(lod["trunk_sides"]), wood, 1.25, 2.0))

    total_layers = int(asset["layers"])
    layer_indices = sampled_indices(total_layers, float(lod["layer_fraction"]))
    cards: list[dict] = []
    crown_start = height * float(asset["crown_start"])
    top_branch_z = height - max(0.25, height * 0.035)
    for layer_index in layer_indices:
        layer_t = layer_index / max(1, total_layers - 1)
        z = crown_start + (top_branch_z - crown_start) * layer_t
        base_reach = float(asset["max_branch_reach"]) * max(
            0.08, (1.0 - layer_t ** float(asset["crown_profile"])) ** 0.72
        )
        branch_count = max(3, round(int(asset["branches_per_layer"]) * float(lod["branch_fraction"])))
        phase_offset = layer_index * 2.399963229728653 + rng.uniform(-0.10, 0.10)
        for branch_index in range(branch_count):
            if rng.random() < float(asset["missing_branch_probability"]):
                continue
            phase = phase_offset + branch_index * math.tau / branch_count + rng.uniform(-0.075, 0.075)
            asymmetry = 1.0 + rng.uniform(-float(asset["asymmetry"]), float(asset["asymmetry"]))
            reach = max(0.12, base_reach * asymmetry)
            start = trunk_point(asset, z)
            radial = Vector((math.cos(phase), math.sin(phase), 0.0))
            lateral = Vector((-math.sin(phase), math.cos(phase), 0.0))
            droop = float(asset["droop"]) * reach * (1.05 - 0.55 * layer_t)
            mid = start + radial * (reach * 0.54) + lateral * rng.uniform(-0.06, 0.06) + Vector((0, 0, -droop * 0.25))
            end = start + radial * reach + lateral * rng.uniform(-0.08, 0.08) + Vector((0, 0, -droop))
            branch_radius = max(0.018, base_radius * (0.18 - 0.08 * layer_t))
            objects.append(
                add_tube(
                    f"branch_{layer_index:02d}_{branch_index:02d}",
                    [start, mid, end],
                    [branch_radius, branch_radius * 0.62, max(0.007, branch_radius * 0.22)],
                    int(lod["branch_sides"]),
                    wood,
                    0.72,
                )
            )
            if bool(lod["secondary_branches"]) and reach > 0.55:
                for secondary_index, along in enumerate((0.55, 0.78)):
                    side_sign = -1.0 if (secondary_index + branch_index) % 2 else 1.0
                    secondary_start = start.lerp(end, along)
                    secondary_length = reach * (0.22 if secondary_index == 0 else 0.16)
                    secondary_end = secondary_start + radial * secondary_length * 0.40 + lateral * side_sign * secondary_length
                    secondary_end.z -= droop * 0.12
                    objects.append(
                        add_tube(
                            f"twig_{layer_index:02d}_{branch_index:02d}_{secondary_index}",
                            [secondary_start, secondary_end],
                            [branch_radius * 0.42, max(0.005, branch_radius * 0.13)],
                            max(4, int(lod["branch_sides"]) - 1),
                            wood,
                            0.55,
                        )
                    )
            cluster_count = int(lod["cards_per_branch"])
            for cluster_index in range(cluster_count):
                along = 0.34 + 0.64 * cluster_index / max(1, cluster_count - 1)
                center = start.lerp(end, along)
                center += lateral * rng.uniform(-0.10, 0.10) * reach
                card_height = (0.62 + reach * 0.16) * rng.uniform(0.92, 1.08)
                card_width = (0.78 + reach * 0.30) * rng.uniform(0.92, 1.08)
                if layer_index == total_layers - 1:
                    center.z = min(height - card_height * 0.43, center.z + card_height * 0.34)
                cards.append(
                    {
                        "center": tuple(center),
                        "direction": tuple(radial),
                        "width": card_width,
                        "height": card_height,
                    }
                )
    wood_geometry = join_objects(objects, "wood_geometry")
    foliage_geometry = add_cards("foliage_cards", cards, regions, foliage)
    return [wood_geometry, foliage_geometry]


def setup_render(asset: dict, lod_name: str, output_path: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 760
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.filepath = str(output_path)
    scene.world.color = (0.026, 0.032, 0.038)
    scene.view_settings.look = "AgX - Medium High Contrast"
    reach = float(asset["max_branch_reach"])
    height = float(asset["height"])
    bpy.ops.mesh.primitive_plane_add(size=max(24.0, reach * 10.0), location=(0, 0, -0.025))
    ground = bpy.context.object
    ground.name = "audit_ground"
    ground_material = bpy.data.materials.new("audit_ground_material")
    ground_material.diffuse_color = (0.07, 0.078, 0.08, 1.0)
    ground.data.materials.append(ground_material)
    camera_distance = height * 1.55
    bpy.ops.object.camera_add(location=(height * 0.72, -camera_distance, height * 0.60))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = height * 1.12
    look_at(camera, Vector((0, 0, height * 0.48)))
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(height * 0.6, -height * 0.5, height * 1.05))
    key = bpy.context.object
    key.data.energy = 1050
    key.data.shape = "DISK"
    key.data.size = height * 0.58
    look_at(key, Vector((0, 0, height * 0.48)))
    bpy.ops.object.light_add(type="AREA", location=(-height * 0.55, height * 0.2, height * 0.62))
    fill = bpy.context.object
    fill.data.energy = 420
    fill.data.size = height * 0.42
    look_at(fill, Vector((0, 0, height * 0.48)))
    bpy.ops.object.light_add(type="SUN", location=(0, 0, height))
    bpy.context.object.data.energy = 1.25
    bpy.context.object.rotation_euler = (math.radians(30), math.radians(-18), math.radians(138))
    scene["audit_lod"] = lod_name


def patch_glb_alpha_mask(path: Path, cutoff: float) -> None:
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        raise ValueError(f"not a GLB: {path}")
    offset, chunks = 12, []
    while offset < len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        chunks.append((kind, raw[offset : offset + length]))
        offset += length
    json_kind = 0x4E4F534A
    document = json.loads(next(data for kind, data in chunks if kind == json_kind).decode("utf-8").rstrip(" \x00"))
    foliage_count = 0
    for material in document.get("materials", []):
        if "foliage" in material.get("name", "").lower():
            material["alphaMode"] = "MASK"
            material["alphaCutoff"] = cutoff
            material["doubleSided"] = True
            foliage_count += 1
        elif "wood" in material.get("name", "").lower():
            material["alphaMode"] = "OPAQUE"
            material.pop("alphaCutoff", None)
            material["doubleSided"] = False
    if foliage_count != 1:
        raise ValueError(f"expected exactly one foliage material in {path}, got {foliage_count}")
    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    rebuilt = [(kind, json_bytes if kind == json_kind else data) for kind, data in chunks]
    total = 12 + sum(8 + len(data) for _kind, data in rebuilt)
    output = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    for kind, data in rebuilt:
        output.extend(struct.pack("<II", len(data), kind))
        output.extend(data)
    path.write_bytes(output)


def mesh_statistics(objects: list[bpy.types.Object]) -> dict:
    mesh_objects = [obj for obj in objects if obj.type == "MESH"]
    triangle_count = sum(sum(max(0, len(poly.vertices) - 2) for poly in obj.data.polygons) for obj in mesh_objects)
    vertex_count = sum(len(obj.data.vertices) for obj in mesh_objects)
    vertices = [obj.matrix_world @ vertex.co for obj in mesh_objects for vertex in obj.data.vertices]
    mins = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maxs = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return {
        "triangles": triangle_count,
        "vertices": vertex_count,
        "bounds_min": [round(value, 5) for value in mins],
        "bounds_max": [round(value, 5) for value in maxs],
        "dimensions": [round(maxs[index] - mins[index], 5) for index in range(3)],
    }


def export_asset(objects: list[bpy.types.Object], glb_path: Path, cutoff: float) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_materials="EXPORT",
    )
    patch_glb_alpha_mask(glb_path, cutoff)


def build_one(repo: Path, asset: dict, lod_name: str, lod: dict, regions: list[dict], cutoff: float, atlas: dict, wood_item: dict, output_root: Path) -> dict:
    clear_scene()
    foliage = make_foliage_material(repo / atlas["path"], cutoff)
    wood = make_wood_material(repo / wood_item["path"])
    objects = build_geometry(asset, lod_name, lod, regions, foliage, wood)
    statistics = mesh_statistics(objects)
    if statistics["triangles"] > int(lod["triangle_budget"]):
        raise ValueError(f"{asset['id']} {lod_name} exceeds triangle budget: {statistics['triangles']}")
    asset_root = output_root / "assets"
    review_root = output_root / "review"
    asset_root.mkdir(parents=True, exist_ok=True)
    review_root.mkdir(parents=True, exist_ok=True)
    glb_path = asset_root / f"{asset['id']}_{lod_name}.glb"
    render_path = review_root / f"{asset['id']}_{lod_name}.png"
    export_asset(objects, glb_path, cutoff)
    setup_render(asset, lod_name, render_path)
    bpy.ops.render.render(write_still=True)
    return {
        "id": asset["id"],
        "lod": lod_name,
        "seed": int(asset["seed"]),
        "glb": glb_path.resolve().relative_to(repo).as_posix(),
        "glb_sha256": sha256(glb_path),
        "audit": render_path.resolve().relative_to(repo).as_posix(),
        "audit_sha256": sha256(render_path),
        "triangle_budget": int(lod["triangle_budget"]),
        "materials": {
            "foliage": atlas["id"],
            "wood": wood_item["id"],
            "alpha_mode": "MASK",
            "alpha_cutoff": cutoff,
        },
        **statistics,
    }


def main() -> int:
    args = args_after_double_dash()
    repo = Path.cwd().resolve()
    if "--repo" in args:
        repo = Path(args[args.index("--repo") + 1]).resolve()
    recipe_path = repo / "procedural/recipes/conifer_v5_library.json"
    if "--recipe" in args:
        recipe_path = Path(args[args.index("--recipe") + 1]).resolve()
    output_root = repo / "procedural/generated/conifers_v5"
    if "--output-root" in args:
        output_root = Path(args[args.index("--output-root") + 1]).resolve()
    try:
        output_root.relative_to(repo)
    except ValueError as error:
        raise ValueError("output root must remain inside the repository") from error
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    release_path = repo / recipe["texture_release"]
    release = json.loads(release_path.read_text(encoding="utf-8"))
    atlas, wood = verify_texture_release(repo, release)
    regions, cutoff = atlas_regions(repo, atlas)
    records = []
    for asset in recipe["assets"]:
        for lod_name in ("lod0", "lod1"):
            records.append(build_one(repo, asset, lod_name, recipe["lods"][lod_name], regions, cutoff, atlas, wood, output_root))
    report = {
        "schema_version": 1,
        "generator": recipe["generator"],
        "blender_version": bpy.app.version_string,
        "recipe": recipe_path.relative_to(repo).as_posix(),
        "recipe_sha256": sha256(recipe_path),
        "texture_release": release_path.relative_to(repo).as_posix(),
        "texture_release_sha256": sha256(release_path),
        "records": records,
    }
    report_path = output_root / "manifest.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
