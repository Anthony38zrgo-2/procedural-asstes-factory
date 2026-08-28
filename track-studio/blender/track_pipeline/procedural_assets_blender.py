from __future__ import annotations

import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from procedural_catalog import biome_from_config, specs_for_biome
from terrain_grid import bank_degrees_at_fraction, effective_far_ground_z


def _closed_polyline_length(points) -> float:
    total = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        total += math.hypot(float(next_point[0]) - float(point[0]), float(next_point[1]) - float(point[1]))
    return total


def godot_xz_to_blender(x: float, z: float, height: float = 0.0) -> Vector:
    return Vector((float(x), -float(z), float(height)))


def sample_centerline(points, fraction):
    n = len(points)
    f = (fraction % 1.0) * n
    i = int(math.floor(f)) % n
    t = f - math.floor(f)
    ax, az = points[i]
    bx, bz = points[(i + 1) % n]
    x = ax + (bx - ax) * t
    z = az + (bz - az) * t
    tx = bx - ax
    tz = bz - az
    length = max(math.hypot(tx, tz), 1e-9)
    tx /= length
    tz /= length
    return (x, z), (tx, tz), (tz, -tx)


def terrain_height(config, fraction, side, distance_from_center_m):
    road_half = float(config["road"]["width_m"]) * 0.5
    surface = float(config["road"].get("surface_elevation_m", 0.025))
    falloff = max(float(config.get("terrain", {}).get("shoulder_falloff_m", 18.0)), 0.1)
    far = effective_far_ground_z(config)
    bank = math.radians(bank_degrees_at_fraction(config, fraction))
    edge = surface + math.tan(bank) * road_half * side
    t = min(1.0, max(0.0, (float(distance_from_center_m) - road_half) / falloff))
    t = t * t * (3 - 2 * t)
    return edge * (1 - t) + far * t


def _mesh_object(name, verts, faces, materials=None, face_materials=None, uv_by_face=None):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for mat in materials or []:
        obj.data.materials.append(mat)
    if face_materials:
        for i, m in enumerate(face_materials):
            if i < len(mesh.polygons):
                mesh.polygons[i].material_index = int(m)
    if uv_by_face:
        uv = mesh.uv_layers.new(name="UVMap")
        for pi, poly in enumerate(mesh.polygons):
            for li, loop in enumerate(poly.loop_indices):
                uv.data[loop].uv = uv_by_face[pi][li]
    return obj


def _card(name, width, height, material, angle_rad=0.0):
    half = width * 0.5
    ca = math.cos(angle_rad)
    sa = math.sin(angle_rad)

    def p(x, z):
        return (x * ca, x * sa, z)

    verts = [p(-half, 0), p(half, 0), p(half, height), p(-half, height)]
    faces = [(0, 1, 2, 3), (3, 2, 1, 0)]
    uv = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], [(1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]]
    return _mesh_object(
        name,
        verts,
        faces,
        [material],
        face_materials=[0, 0],
        uv_by_face=uv,
    )


def _hide(objs):
    for obj in objs:
        obj.hide_render = True
        obj.hide_viewport = True
        obj.hide_set(True)
    return objs


def _crossed(prefix, width, height, material, planes):
    planes = max(1, int(planes))
    return _hide([
        _card(f"{prefix}_P{i+1}", width, height, material, math.pi * i / planes)
        for i in range(planes)
    ])


def _building(prefix, width, height, depth, facade, roof):
    w = width * 0.5
    d = depth * 0.5
    verts = [
        (-w, -d, 0), (w, -d, 0), (w, d, 0), (-w, d, 0),
        (-w, -d, height), (w, -d, height), (w, d, height), (-w, d, height),
    ]
    faces = [(0,1,5,4), (1,2,6,5), (2,3,7,6), (3,0,4,7), (4,5,6,7)]
    uv = [[(0,0),(1,0),(1,1),(0,1)]] * 5
    return _hide([_mesh_object(prefix, verts, faces, [facade, roof], [0,0,0,0,1], uv)])


def create_prototypes(materials, config):
    biome = biome_from_config(config)
    tree_planes = max(1, int(config.get("procedural_environment", {}).get("tree_planes", 2)))
    out = {}
    for category in ("trees", "bushes", "grass", "fake_buildings"):
        if category == "grass" and not config.get("procedural_environment", {}).get("grass_cards", {}).get("enabled", True):
            continue
        if category == "fake_buildings" and not config.get("procedural_environment", {}).get("fake_buildings", {}).get("enabled", True):
            continue
        for spec in specs_for_biome(biome, category):
            mat = materials.get(f"asset:{spec.id}")
            if mat is None:
                # Source-backed GLB prototypes are loaded after this fallback
                # catalog. An active surface manifest need not fabricate flat
                # materials for assets that already embed their own textures.
                continue
            if category == "trees":
                out[spec.id] = _crossed(f"Proto_{spec.id}", spec.width_m, spec.height_m, mat, tree_planes)
            elif category == "bushes":
                out[spec.id] = _crossed(f"Proto_{spec.id}", spec.width_m, spec.height_m, mat, 2)
            elif category == "grass":
                out[spec.id] = _crossed(f"Proto_{spec.id}", spec.width_m, spec.height_m, mat, 2)
            else:
                out[spec.id] = _building(
                    f"Proto_{spec.id}", spec.width_m, spec.height_m, spec.depth_m,
                    mat, materials["roof"],
                )
    return out


def instantiate_prototype(
    source_objects,
    name,
    x,
    z,
    height,
    yaw,
    scale,
    tint_rgb=None,
    width_scale: float = 1.0,
    height_scale: float = 1.0,
):
    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    root.location = godot_xz_to_blender(x, z, height)
    root.rotation_euler[2] = -float(yaw)
    horizontal = float(scale) * float(width_scale)
    vertical = float(scale) * float(height_scale)
    root.scale = (horizontal, horizontal, vertical)
    if tint_rgb is not None:
        root["formula90s_tint_rgb"] = list(tint_rgb)
    for src in source_objects:
        copy = src.copy()
        copy.data = src.data if src.data is not None else None
        copy.hide_render = False
        copy.hide_viewport = False
        copy.hide_set(False)
        bpy.context.scene.collection.objects.link(copy)
        copy.parent = root
    return root


def _cube(name, size_xyz, location, material=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = tuple(float(v) for v in size_xyz)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        obj.data.materials.append(material)
    return obj


def _armco_beam(name, length, depth, height, center, material):
    profile = [
        (-height * 0.50, -depth * 0.32),
        (-height * 0.25, depth * 0.50),
        (0.0, -depth * 0.18),
        (height * 0.25, depth * 0.50),
        (height * 0.50, -depth * 0.32),
    ]
    verts = []
    for x in (-length * 0.5, length * 0.5):
        for z, y in profile:
            verts.append((x, y, center + z))
            verts.append((x, y - depth * 0.18, center + z))
    faces = []
    ring = len(profile) * 2
    for side in range(2):
        offset = side * ring
        for index in range(len(profile) - 1):
            a = offset + index * 2
            faces.append((a, a + 2, a + 3, a + 1))
    for index in range(ring):
        nxt = (index + 1) % ring
        faces.append((index, ring + index, ring + nxt, nxt))
    return _mesh_object(name, verts, faces, [material])


def create_guardrail_prototype(config, materials, rail_count=3):
    s = config["guardrails"]
    length = float(s.get("module_length_m", 4))
    depth = float(s.get("visual_depth_m", .11))
    height = float(s.get("beam_height_m", .34))
    center = float(s.get("beam_center_height_m", .58))
    ph = float(s.get("post_height_m", .82))
    pw = float(s.get("post_width_m", .10))
    pd = float(s.get("post_depth_m", .12))
    mat = materials["guardrail"]
    objs = []
    beam_height = height * 0.48
    centers = (center - 0.16, center + 0.16) if rail_count == 2 else (center - 0.22, center + 0.06, center + 0.34)
    for i, beam_center in enumerate(centers):
        objs.append(_armco_beam(f"Proto_Armco_{rail_count}_{i}", length + 0.18, depth, beam_height, beam_center, mat))
    spacing = max(1, float(s.get("post_spacing_m", 2)))
    count = max(2, int(math.floor(length / spacing)) + 1)
    for i in range(count):
        objs.append(_cube(
            f"Proto_Guardrail_Post_{i}",
            (pw, pd, ph),
            (-length*.5 + i*(length/max(1,count-1)), 0, ph*.5),
            mat,
        ))
    return _hide(objs), length


def create_guardrail_collision(name, pos, tangent, length, ground_z, config):
    s = config["guardrails"]
    h = float(s["collision_height_m"])
    t = float(s["collision_thickness_m"])
    x, z = pos
    bpy.ops.mesh.primitive_cube_add(location=godot_xz_to_blender(x, z, ground_z + h*.5))
    obj = bpy.context.object
    obj.name = name + "-colonly"
    tx, tz = tangent
    obj.rotation_euler[2] = math.atan2(-tz, tx)
    obj.scale = (length*.5, t*.5, h*.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.hide_render = True
    obj.display_type = "WIRE"
    return obj


def create_safety_barrier_prototype(prototype_id, spec, materials, color_key):
    length = float(spec["module_length_m"])
    color = materials[f"safety:{color_key}"]
    navy = materials["safety:navy"]
    steel_dark = materials["safety:steel_dark"]
    geometry = spec["geometry"]
    objects = []
    if geometry == "guardrail_armco":
        rail_count = int(spec.get("rail_count", 2))
        height = 0.90 if rail_count == 2 else 1.14
        half = (length + 0.12) * 0.5
        verts = [(-half, 0.0, 0.0), (half, 0.0, 0.0),
                 (half, 0.0, height), (-half, 0.0, height)]
        uv_bottom = 1.0 / 3.0 if rail_count == 2 else 0.0
        objects.append(_mesh_object(
            f"Proto_{prototype_id}_BitmapCard", verts, [(0, 1, 2, 3)],
            [materials["safety:guardrail_card"]],
            uv_by_face=[[(0, uv_bottom), (1, uv_bottom), (1, 1), (0, 1)]],
        ))
    elif geometry == "painted_tire_prism":
        # The source bitmap already contains the painted tire-stack pattern.
        # Mapping it to generic cubes projected the whole image onto every face,
        # producing a noisy grid of blocks instead of a readable tire wall.
        half = length * 0.5
        depth = 0.18
        height = 1.12
        verts = [
            (-half, -depth, 0.0), (half, -depth, 0.0),
            (half, -depth, height), (-half, -depth, height),
            (half, depth, 0.0), (-half, depth, 0.0),
            (-half, depth, height), (half, depth, height),
        ]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
        tire_uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        objects.append(_mesh_object(
            f"Proto_{prototype_id}_PaintedCards", verts, faces,
            [materials["safety:tire_wall"]],
            uv_by_face=[tire_uv, tire_uv],
        ))
    elif geometry == "beveled_block":
        half = length * 0.5
        verts = [(-half,-.34,0),(half,-.34,0),(half,.34,0),(-half,.34,0),
                 (-half,-.28,1.18),(half,-.28,1.18),(half,.20,1.18),(-half,.20,1.18)]
        faces = [(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7),(0,3,2,1)]
        objects.append(_mesh_object(f"Proto_{prototype_id}_Block", verts, faces, [color]))
        objects.append(_cube(f"Proto_{prototype_id}_Band", (length + .01, .03, .12),
                             (0, -.295, .68), navy if color_key == "white" else materials["safety:white"]))
    elif geometry == "continuous_wall":
        objects.append(_cube(f"Proto_{prototype_id}_Wall", (length, .42, 1.42),
                             (0, 0, .71), color))
    elif geometry == "jersey_profile":
        half = length * .5
        profile = [(-.42,0),(.42,0),(.25,.52),(.18,1.15),(-.18,1.15),(-.25,.52)]
        verts = [(x, y, z) for x in (-half, half) for y, z in profile]
        ring = len(profile)
        faces = []
        for index in range(ring):
            nxt = (index + 1) % ring
            faces.append((index, nxt, ring + nxt, ring + index))
        faces.extend((tuple(range(ring - 1, -1, -1)), tuple(range(ring, ring * 2))))
        objects.append(_mesh_object(f"Proto_{prototype_id}_Jersey", verts, faces, [color]))
    else:
        raise RuntimeError(f"Unsupported safety barrier geometry: {geometry}")
    return _hide(objects)


def create_safety_barrier_collision(name, pos, tangent, length, ground_z, profile):
    height = float(profile["height_m"])
    thickness = float(profile["thickness_m"])
    x, z = pos
    bpy.ops.mesh.primitive_cube_add(location=godot_xz_to_blender(x, z, ground_z + height * .5))
    obj = bpy.context.object
    obj.name = name + "-colonly"
    tx, tz = tangent
    obj.rotation_euler[2] = math.atan2(-tz, tx)
    obj.scale = (length * .5, thickness * .5, height * .5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.hide_render = True
    obj.display_type = "WIRE"
    obj["formula90s_collision_kind"] = "safety_barrier_wall"
    return obj


def create_safety_barrier_ribbon_collision(name, samples, profile):
    """Build one closed collision ribbon that follows an entire curved segment."""
    height = float(profile["height_m"])
    half_thickness = float(profile["thickness_m"]) * 0.5
    if len(samples) < 2:
        raise RuntimeError(f"Collision ribbon requires at least two samples: {name}")
    centers = [godot_xz_to_blender(pos[0], pos[1], ground) for pos, ground in samples]
    verts = []
    for index, center in enumerate(centers):
        previous = centers[max(0, index - 1)]
        following = centers[min(len(centers) - 1, index + 1)]
        tangent = following - previous
        tangent.z = 0.0
        if tangent.length_squared < 1e-9:
            tangent = Vector((1.0, 0.0, 0.0))
        tangent.normalize()
        lateral = Vector((-tangent.y, tangent.x, 0.0)) * half_thickness
        left = center - lateral
        right = center + lateral
        verts.extend((tuple(left), tuple(right),
                      tuple(left + Vector((0, 0, height))),
                      tuple(right + Vector((0, 0, height)))))
    faces = []
    for index in range(len(centers) - 1):
        a = index * 4
        b = (index + 1) * 4
        faces.extend(((a, b, b + 2, a + 2),
                      (a + 1, a + 3, b + 3, b + 1),
                      (a + 2, b + 2, b + 3, a + 3),
                      (a, a + 1, b + 1, b)))
    last = (len(centers) - 1) * 4
    faces.extend(((0, 2, 3, 1), (last, last + 1, last + 3, last + 2)))
    obj = _mesh_object(name + "-colonly", verts, faces)
    obj.hide_render = True
    obj.display_type = "WIRE"
    obj["formula90s_collision_kind"] = "safety_barrier_ribbon"
    return obj


def _append_low_poly_tire(vertices, faces, center: Vector, tangent_b: Vector, outward_b: Vector, major: float, minor: float):
    major_segments = 8
    minor_segments = 4
    start = len(vertices)
    tangent_b = tangent_b.normalized()
    outward_b = outward_b.normalized()
    up = Vector((0.0, 0.0, 1.0))
    for i in range(major_segments):
        theta = math.tau * i / major_segments
        radial = tangent_b * math.cos(theta) + up * math.sin(theta)
        for j in range(minor_segments):
            phi = math.tau * j / minor_segments
            point = center + radial * (major + minor * math.sin(phi)) + outward_b * (minor * math.cos(phi))
            vertices.append(tuple(point))
    for i in range(major_segments):
        ni = (i + 1) % major_segments
        for j in range(minor_segments):
            nj = (j + 1) % minor_segments
            a = start + i * minor_segments + j
            b = start + ni * minor_segments + j
            c = start + ni * minor_segments + nj
            d = start + i * minor_segments + nj
            faces.append((a, b, c, d))


def create_tire_barrier_visual(name, points, side, config, material, asset_glb=None):
    tire_cfg = config["tire_barriers"]
    road_half = float(config["road"]["width_m"]) * 0.5
    distance = road_half + float(tire_cfg.get("separation_from_edge_m", 5.0))
    lap = _closed_polyline_length(points)

    if asset_glb:
        # Reusable Jordan 3x2 module: import once, hide as prototype, then
        # linked-duplicate per module along the centerline. The module's X axis
        # runs along the wall; module length is its measured along-track width.
        module_length = float(tire_cfg.get("module_length_m", 1.8))
        count = max(1, int(math.ceil(lap / module_length)))
        root = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(root)
        root["formula90s_continuous_tire_barrier"] = True
        root["formula90s_collision"] = False
        for index in range(count):
            fraction = (index + 0.5) / count
            pos, tangent, normal = sample_centerline(points, fraction)
            ground = terrain_height(config, fraction, side, distance)
            center = godot_xz_to_blender(pos[0] + normal[0] * side * distance, pos[1] + normal[1] * side * distance, ground)
            tangent_b = Vector((tangent[0], -tangent[1], 0.0))
            duplicate = _import_asset_instance(asset_glb, f"{name}_m{index:04d}")
            duplicate.parent = root
            duplicate.location = center
            # Rotate the module so its local X (wall direction) aligns with the tangent.
            yaw = math.atan2(tangent_b.y, tangent_b.x)
            duplicate.rotation_euler[2] = yaw
        return root, count

    module_length = max(0.8, float(tire_cfg.get("module_length_m", 2.4)))
    radius = max(0.12, float(tire_cfg.get("tire_major_radius_m", 0.34)))
    minor = max(0.04, float(tire_cfg.get("tire_minor_radius_m", 0.11)))
    rows = max(1, int(tire_cfg.get("stack_rows", 2)))
    per_row = max(1, int(tire_cfg.get("tires_per_row", 2)))
    count = max(1, int(math.ceil(lap / module_length)))
    vertices = []
    faces = []
    for index in range(count):
        fraction = (index + 0.5) / count
        pos, tangent, normal = sample_centerline(points, fraction)
        ground = terrain_height(config, fraction, side, distance)
        center = godot_xz_to_blender(pos[0] + normal[0] * side * distance, pos[1] + normal[1] * side * distance, ground)
        tangent_b = Vector((tangent[0], -tangent[1], 0.0))
        outward_b = Vector((side * normal[0], -side * normal[1], 0.0))
        for row in range(rows):
            height = radius + minor + row * (2.0 * radius * 0.82)
            for col in range(per_row):
                along = (col - (per_row - 1) * 0.5) * radius * 1.62
                tire_center = center + tangent_b * along + Vector((0.0, 0.0, height))
                _append_low_poly_tire(vertices, faces, tire_center, tangent_b, outward_b, radius, minor)
    obj = _mesh_object(name, vertices, faces, [material])
    obj["formula90s_continuous_tire_barrier"] = True
    obj["formula90s_collision"] = False
    return obj, count


def _sector_barrier_type(fraction, sectors):
    if not sectors:
        return "tire_black"
    f = float(fraction) % 1.0
    for sector in sectors:
        start_f = float(sector["start_fraction"])
        end_f = float(sector["end_fraction"])
        if start_f <= end_f:
            if start_f <= f < end_f:
                return sector.get("barrier_type", "tire_black")
        else:
            if f >= start_f or f < end_f:
                return sector.get("barrier_type", "tire_black")
    return "tire_black"


def _fraction_in_spans(fraction, spans):
    value = float(fraction) % 1.0
    for span in spans or ():
        start = float(span["start_fraction"]) % 1.0
        end = float(span["end_fraction"]) % 1.0
        if (start <= end and start <= value < end) or (start > end and (value >= start or value < end)):
            return True
    return False


def create_tire_barrier_card_visual(
    name, points, side, config, front_material, side_material, top_material,
    front_uv_bounds=(0.0, 0.0, 1.0, 1.0),
    multi_materials=None,
    barrier_sectors=None,
    exclude_spans=None,
):
    """Build a closed, continuous rectangular barrier ribbon supporting multiple barrier styles."""
    tire_cfg = config["tire_barriers"]
    road_half = float(config["road"]["width_m"]) * 0.5
    distance = road_half + float(tire_cfg.get("separation_from_edge_m", 5.0))
    module_length = max(0.25, float(tire_cfg.get("module_length_m", 0.68)))
    visual_height = max(0.5, float(tire_cfg.get("visual_height_m", 1.45)))
    visual_depth = max(0.1, float(tire_cfg.get("visual_depth_m", 0.32)))
    side_repeats = max(1, int(tire_cfg.get("side_repeats", 5)))
    count = max(1, int(math.ceil(_closed_polyline_length(points) / module_length)))
    vertices = []
    faces = []
    face_materials = []
    uv_by_face = []
    up = Vector((0.0, 0.0, visual_height))
    u0, v0, u1, v1 = front_uv_bounds

    all_materials = [front_material, side_material, top_material]
    type_to_offset = {}
    if multi_materials:
        all_materials = []
        registered_types = list(multi_materials.keys())
        for b_type in registered_types:
            type_to_offset[b_type] = len(all_materials)
            all_materials.extend(multi_materials[b_type])

    for index in range(count):
        fraction = index / count
        pos, tangent, normal = sample_centerline(points, fraction)
        ground = terrain_height(config, fraction, side, distance)
        center = godot_xz_to_blender(
            pos[0] + normal[0] * side * distance,
            pos[1] + normal[1] * side * distance,
            ground,
        )
        tangent_b = Vector((tangent[0], -tangent[1], 0.0)).normalized()
        outward_b = Vector((side * normal[0], -side * normal[1], 0.0)).normalized()

        half_side = outward_b * (visual_depth * 0.5)
        inner = center - half_side
        outer = center + half_side
        vertices.extend((tuple(inner), tuple(outer), tuple(inner + up), tuple(outer + up)))

    for index in range(count):
        next_index = (index + 1) % count
        i = index * 4
        j = next_index * 4
        fraction = index / count
        next_fraction = next_index / count
        if _fraction_in_spans(fraction, exclude_spans) or _fraction_in_spans(next_fraction, exclude_spans):
            continue
        mat_offset = 0
        if multi_materials and barrier_sectors:
            b_type = _sector_barrier_type(fraction, barrier_sectors)
            mat_offset = type_to_offset.get(b_type, 0)

        faces.extend(((i + 1, j + 1, j + 3, i + 3), (j, i, i + 2, j + 2), (i + 2, i + 3, j + 3, j + 2), (j, j + 1, i + 1, i)))
        face_materials.extend((mat_offset + 0, mat_offset + 1, mat_offset + 2, mat_offset + 2))
        front_u0 = u0 + (u1 - u0) * index
        front_u1 = u0 + (u1 - u0) * (index + 1)
        uv_by_face.extend((
            [(front_u0, v0), (front_u1, v0), (front_u1, v1), (front_u0, v1)],
            [(index, 0), (index + 1, 0), (index + 1, side_repeats), (index, side_repeats)],
            [(index, 0), (index, 1), (index + 1, 1), (index + 1, 0)],
            [(index, 0), (index + 1, 0), (index + 1, 1), (index, 1)],
        ))

    obj = _mesh_object(name, vertices, faces, all_materials, face_materials, uv_by_face)
    obj["formula90s_continuous_tire_barrier"] = True
    obj["formula90s_collision"] = False
    obj["formula90s_barrier_geometry"] = "continuous_rectangular_ribbon"
    obj["formula90s_quads_per_segment"] = 4
    obj["formula90s_vertices_per_segment"] = 4
    obj["formula90s_side_repeats"] = side_repeats
    return obj, count


def _import_asset_instance(asset_glb, instance_name):
    """Import a GLB asset once into a hidden prototype and return a linked copy
    as a fresh object instance. The imported source objects are removed after
    the prototype is captured so repeated calls stay cheap."""
    cache = getattr(bpy, "_tire_module_prototype_meshes", None)
    if cache is None:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(Path(asset_glb).resolve()))
        imported = [obj for obj in bpy.data.objects if obj not in before]
        root = None
        for obj in imported:
            if obj.type == "EMPTY" and obj.name.startswith("TireBarrierJordan6"):
                root = obj
                break
        if root is None:
            raise RuntimeError("tire barrier GLB is missing the TireBarrierJordan6 root")
        meshes = [obj for obj in root.children if obj.type == "MESH"]
        if len(meshes) != 1:
            raise RuntimeError(f"tire barrier GLB expected 1 fused module mesh, got {len(meshes)}")
        for obj in imported:
            obj.hide_render = True
            obj.hide_viewport = True
            obj.hide_set(True)
        bpy._tire_module_prototype_meshes = meshes
    meshes = bpy._tire_module_prototype_meshes
    duplicate = bpy.data.objects.new(instance_name, None)
    bpy.context.scene.collection.objects.link(duplicate)
    for child in meshes:
        copy = child.copy()
        copy.data = child.data
        bpy.context.scene.collection.objects.link(copy)
        copy.parent = duplicate
        copy.matrix_basis = child.matrix_basis.copy()
        copy.hide_render = False
        copy.hide_viewport = False
        copy.hide_set(False)
    duplicate.hide_render = False
    duplicate.hide_viewport = False
    duplicate.hide_set(False)
    return duplicate


def create_tire_barrier_collision(name, points, side, config):
    tire_cfg = config["tire_barriers"]
    module_length = max(2.0, float(tire_cfg.get("module_length_m", 2.4)) * 2.0)
    thickness = max(0.08, float(tire_cfg.get("collision_thickness_m", 0.28)))
    height = max(0.5, float(tire_cfg.get("collision_height_m", 1.45)))
    road_half = float(config["road"]["width_m"]) * 0.5
    distance = road_half + float(tire_cfg.get("separation_from_edge_m", 5.0))
    lap = _closed_polyline_length(points)
    count = max(8, int(math.ceil(lap / module_length)))
    vertices = []
    for index in range(count):
        fraction = index / count
        pos, _, normal = sample_centerline(points, fraction)
        ground = terrain_height(config, fraction, side, distance)
        barrier = np.array([pos[0] + normal[0] * side * distance, pos[1] + normal[1] * side * distance], dtype=float)
        outward = np.array([normal[0] * side, normal[1] * side], dtype=float)
        inner = barrier - outward * (thickness * 0.5)
        outer = barrier + outward * (thickness * 0.5)
        vertices.extend([
            tuple(godot_xz_to_blender(inner[0], inner[1], ground)),
            tuple(godot_xz_to_blender(outer[0], outer[1], ground)),
            tuple(godot_xz_to_blender(inner[0], inner[1], ground + height)),
            tuple(godot_xz_to_blender(outer[0], outer[1], ground + height)),
        ])
    faces = []
    exclude_spans = tire_cfg.get("exclude_spans", [])
    for index in range(count):
        next_index = (index + 1) % count
        if (_fraction_in_spans(index / count, exclude_spans) or
                _fraction_in_spans(next_index / count, exclude_spans)):
            continue
        i = index * 4
        j = next_index * 4
        faces.extend([
            (i, j, j + 2, i + 2),
            (i + 1, i + 3, j + 3, j + 1),
            (i + 2, j + 2, j + 3, i + 3),
            (i, i + 1, j + 1, j),
        ])
    obj = _mesh_object(name + "-colonly", vertices, faces)
    obj.hide_render = True
    obj.display_type = "WIRE"
    obj["formula90s_collision"] = True
    obj["formula90s_collision_kind"] = "continuous_tire_barrier_wall"
    return obj, count


def trackside_card_shape(prop_type: str) -> list[tuple[float, float]]:
    shapes = {
        "spectator": [(-0.18, 0.0), (0.18, 0.0), (0.14, 0.55), (0.09, 0.73), (0.0, 0.93), (-0.09, 0.73), (-0.14, 0.55)],
        "marshal": [(-0.20, 0.0), (0.20, 0.0), (0.16, 0.62), (0.10, 0.84), (0.0, 1.04), (-0.10, 0.84), (-0.16, 0.62)],
        "photographer": [(-0.25, 0.0), (0.25, 0.0), (0.22, 0.35), (0.08, 0.48), (0.18, 0.62), (-0.02, 0.70), (-0.20, 0.58), (-0.08, 0.36)],
        "flag": [(-0.04, 0.0), (0.04, 0.0), (0.04, 1.75), (0.40, 1.62), (0.04, 1.42), (-0.04, 1.42)],
        "sign": [(-0.70, 0.0), (0.70, 0.0), (0.70, 1.15), (-0.70, 1.15)],
    }
    if prop_type not in shapes:
        raise KeyError(prop_type)
    return shapes[prop_type]


def create_trackside_card(
    name, pos, tangent, normal, side, ground, prop_type, material,
    asset_id=None, scale_multiplier=1.0,
):
    dims = {
        "sign": (7.2, 2.4),
        "spectator": (1.40, 1.75),
        "marshal": (1.50, 1.80),
        "photographer": (1.20, 1.35),
        "flag": (0.80, 2.20),
    }
    scale_multiplier = float(scale_multiplier)
    width, height = dims.get(prop_type, (1.5, 1.75))
    width *= scale_multiplier
    height *= scale_multiplier
    tangent_b = Vector((float(tangent[0]), -float(tangent[1]), 0.0)).normalized()
    center = godot_xz_to_blender(pos[0], pos[1], ground)
    if prop_type == "flag":
        pole_material, navy_material, white_material = material
        def flag_vertex(along, height_value):
            return tuple(center + tangent_b * along + Vector((0.0, 0.0, height_value)))
        bands = [
            (-0.38 * scale_multiplier, -0.30 * scale_multiplier, 0.0, height, 0),
            (-0.30 * scale_multiplier, 0.40 * scale_multiplier, height * .76, height, 1),
            (-0.30 * scale_multiplier, 0.40 * scale_multiplier, height * .64, height * .76, 2),
            (-0.30 * scale_multiplier, 0.40 * scale_multiplier, height * .52, height * .64, 1),
        ]
        vertices = []
        faces = []
        face_materials = []
        for x0, x1, z0, z1, material_index in bands:
            base = len(vertices)
            vertices.extend((flag_vertex(x0, z0), flag_vertex(x1, z0),
                             flag_vertex(x1, z1), flag_vertex(x0, z1)))
            faces.append((base, base + 1, base + 2, base + 3))
            face_materials.append(material_index)
        obj = _mesh_object(name, vertices, faces,
                           [pole_material, navy_material, white_material],
                           face_materials=face_materials)
        obj["formula90s_trackside_card"] = prop_type
        obj["formula90s_trackside_asset_id"] = asset_id or "track_flag"
        obj["formula90s_material_authority"] = "procedural_navy_white_flag"
        obj["formula90s_collision"] = False
        return obj
    half = width * 0.5
    v0 = tuple(center - tangent_b * half)
    v1 = tuple(center + tangent_b * half)
    v2 = tuple(center + tangent_b * half + Vector((0.0, 0.0, height)))
    v3 = tuple(center - tangent_b * half + Vector((0.0, 0.0, height)))
    vertices = [v0, v1, v2, v3]
    faces = [(0, 1, 2, 3)]
    uv_by_face = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
    obj = _mesh_object(name, vertices, faces, [material], face_materials=[0], uv_by_face=uv_by_face)
    obj["formula90s_trackside_card"] = prop_type
    obj["formula90s_trackside_asset_id"] = asset_id or prop_type
    obj["formula90s_material_authority"] = "source_texture"
    obj["formula90s_collision"] = False
    return obj
