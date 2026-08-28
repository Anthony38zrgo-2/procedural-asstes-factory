from __future__ import annotations

import argparse
from pathlib import Path
import json
import math
import sys

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from blender_output import atomic_export_glb, atomic_publish, atomic_save_blend
from curb_manifest import load_curb_manifest, material_for_longitudinal
from procedural_materials_blender import build_material_library
from terrain_grid import (
    NearestTrackSample,
    bank_degrees_at_fraction,
    build_heightfield,
    effective_far_ground_z,
    terrain_height_from_sample,
)


def args_after_double_dash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def godot_xz_to_blender(x, z, height=0.0):
    return Vector((float(x), -float(z), float(height)))


def cross_frame(points, i, config):
    n = len(points)
    prev = godot_xz_to_blender(*points[(i - 1) % n])
    nxt = godot_xz_to_blender(*points[(i + 1) % n])
    tangent = (nxt - prev).normalized()
    normal = Vector((-tangent.y, tangent.x, 0))
    return tangent, normal, math.radians(bank_degrees_at_fraction(config, i / n))


def mesh_object(name, verts, faces, materials=None, planar_uv_scale_m=None, normalized_uv_bounds=None):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for mat in materials or []:
        obj.data.materials.append(mat)

    if planar_uv_scale_m or normalized_uv_bounds:
        uv = mesh.uv_layers.new(name="UVMap")
        if normalized_uv_bounds:
            min_x, min_y, max_x, max_y = normalized_uv_bounds
            sx = max(float(max_x - min_x), 1e-6)
            sy = max(float(max_y - min_y), 1e-6)
            for poly in mesh.polygons:
                for loop in poly.loop_indices:
                    vi = mesh.loops[loop].vertex_index
                    co = mesh.vertices[vi].co
                    uv.data[loop].uv = ((co.x - min_x) / sx, (co.y - min_y) / sy)
        else:
            scale = max(float(planar_uv_scale_m), .001)
            for poly in mesh.polygons:
                for loop in poly.loop_indices:
                    vi = mesh.loops[loop].vertex_index
                    co = mesh.vertices[vi].co
                    uv.data[loop].uv = (co.x / scale, co.y / scale)
    return obj


def build_ribbon(points, half_width, top_z, name, material, collision_name, config):
    n = len(points)
    left, right = [], []
    for i, p in enumerate(points):
        _, normal, bank = cross_frame(points, i, config)
        center = godot_xz_to_blender(p[0], p[1], top_z)
        rise = math.tan(bank) * half_width
        left.append(center - normal * half_width + Vector((0, 0, -rise)))
        right.append(center + normal * half_width + Vector((0, 0, rise)))
    verts = []
    for a, b in zip(left, right):
        verts.extend([tuple(a), tuple(b)])
    faces = [(2*i, 2*((i+1)%n), 2*((i+1)%n)+1, 2*i+1) for i in range(n)]
    road = mesh_object(name, verts, faces, [material], 5.0)
    col = mesh_object(collision_name, verts, faces)
    col.hide_render = True
    col.display_type = "WIRE"
    return road


def build_edge_line(points, side, road_half, line_width, config, material, top_z):
    n = len(points)
    sign = 1 if side == "right" else -1
    verts = []
    inner = road_half - line_width
    for i, p in enumerate(points):
        _, normal, bank = cross_frame(points, i, config)
        center = godot_xz_to_blender(p[0], p[1], top_z + .003)
        for offset in (inner, road_half):
            signed = sign * offset
            verts.append(tuple(center + normal * signed + Vector((0, 0, math.tan(bank) * signed))))
    faces = [(2*i, 2*((i+1)%n), 2*((i+1)%n)+1, 2*i+1) for i in range(n)]
    return mesh_object(("Right" if sign > 0 else "Left") + "EdgeLine", verts, faces, [material])


def curb_indices(n, start, end):
    a = int(math.floor(start * n)) % n
    b = int(math.ceil(end * n)) % n
    return list(range(a, b + 1)) if a <= b else list(range(a, n)) + list(range(0, b + 1))


def build_curb(points, segment, road_half, manifest, materials, config, top_z):
    indices = curb_indices(len(points), float(segment["start_fraction"]), float(segment["end_fraction"]))
    side = 1 if segment["side"] == "right" else -1
    profile_id = str(segment["profile_id"])
    profile_spec = manifest["profiles"][profile_id]
    profile = profile_spec["points"]
    width = float(profile_spec["width_m"])
    base_depth = float(profile_spec["base_depth_m"])
    pattern = manifest["patterns"][profile_spec["pattern"]]
    material_ids = list(manifest["palette"])
    material_indices = {material_id: index for index, material_id in enumerate(material_ids)}
    verts = []
    columns = len(profile)
    row_distance_m = [0.0]
    for previous_idx, idx in zip(indices, indices[1:]):
        previous = points[previous_idx]
        current = points[idx]
        segment_length = math.hypot(float(current[0]) - float(previous[0]), float(current[1]) - float(previous[1]))
        row_distance_m.append(row_distance_m[-1] + segment_length)
    for idx in indices:
        _, normal, bank = cross_frame(points, idx, config)
        normal *= side
        p = points[idx]
        center = godot_xz_to_blender(p[0], p[1], top_z)
        edge = center + normal * road_half + Vector((0, 0, math.tan(bank) * road_half * side))
        for column, (off, h) in enumerate(profile):
            vertex = edge + normal * float(off) + Vector((0, 0, float(h) + math.tan(bank) * float(off) * side))
            if column == columns - 1:
                outer_distance = road_half + float(off)
                sample = NearestTrackSample(outer_distance, idx / len(points), side, outer_distance * side)
                vertex.z = terrain_height_from_sample(config, sample, visual=False) + 0.002
            verts.append(tuple(vertex))
    top_vertex_count = len(verts)
    for idx in indices:
        _, normal, bank = cross_frame(points, idx, config)
        normal *= side
        p = points[idx]
        center = godot_xz_to_blender(p[0], p[1], top_z)
        edge = center + normal * road_half + Vector((0, 0, math.tan(bank) * road_half * side))
        for off, _ in profile:
            verts.append(tuple(edge + normal * float(off) + Vector((0, 0, -base_depth + math.tan(bank) * float(off) * side))))

    faces = []
    face_materials = []

    def append_face(face, material_id):
        faces.append(tuple(face))
        face_materials.append(material_indices[material_id])

    for row in range(len(indices) - 1):
        midpoint_distance = (row_distance_m[row] + row_distance_m[row + 1]) * 0.5
        material_id = material_for_longitudinal(pattern, midpoint_distance)
        for column in range(columns - 1):
            a = row * columns + column
            b = (row + 1) * columns + column
            top_face = (a, b, b + 1, a + 1)
            va, vb, vc = (Vector(verts[index]) for index in top_face[:3])
            if (vb - va).cross(vc - va).z < 0.0:
                top_face = tuple(reversed(top_face))
            append_face(top_face, material_id)
            append_face(tuple(top_vertex_count + index for index in reversed(top_face)), "concrete")

        top_inner = row * columns
        next_top_inner = (row + 1) * columns
        bottom_inner = top_vertex_count + top_inner
        next_bottom_inner = top_vertex_count + next_top_inner
        append_face((top_inner, bottom_inner, next_bottom_inner, next_top_inner), "concrete")

        top_outer = row * columns + columns - 1
        next_top_outer = (row + 1) * columns + columns - 1
        bottom_outer = top_vertex_count + top_outer
        next_bottom_outer = top_vertex_count + next_top_outer
        append_face((top_outer, next_top_outer, next_bottom_outer, bottom_outer), "concrete")

    for row, reverse in ((0, True), (len(indices) - 1, False)):
        for column in range(columns - 1):
            top_left = row * columns + column
            top_right = top_left + 1
            bottom_left = top_vertex_count + top_left
            bottom_right = bottom_left + 1
            face = (top_left, top_right, bottom_right, bottom_left)
            append_face(tuple(reversed(face)) if reverse else face, "concrete")

    material_slots = [materials[f"curb:{material_id}"] for material_id in material_ids]
    obj = mesh_object(
        "Curb_" + segment["name"], verts, faces,
        material_slots,
    )
    for polygon, material_index in zip(obj.data.polygons, face_materials):
        polygon.material_index = material_index
    uv = obj.data.uv_layers.new(name="UVMap")
    for polygon in obj.data.polygons:
        for loop in polygon.loop_indices:
            vertex_index = obj.data.loops[loop].vertex_index
            local_index = vertex_index % top_vertex_count
            row = local_index // columns
            column = local_index % columns
            uv.data[loop].uv = (
                float(profile[column][0]) / width,
                row_distance_m[row] / float(pattern["stripe_length_m"]),
            )
    obj["formula90s_curb_profile"] = profile_id
    obj["formula90s_curb_width_m"] = width
    obj["formula90s_curb_base_depth_m"] = base_depth
    obj["formula90s_curb_pattern"] = profile_spec["pattern"]
    col = mesh_object("CurbCollision_" + segment["name"] + "-colonly", verts, faces)
    col.hide_render = True
    col.display_type = "WIRE"
    col["formula90s_curb_profile"] = profile_id
    col["formula90s_curb_closed_collision"] = True


def _upward_triangles(verts, quads):
    out = []
    for q in quads:
        candidates = ((q[0],q[1],q[2]), (q[0],q[2],q[3]))
        for tri in candidates:
            a,b,c = (Vector(verts[i]) for i in tri)
            nz = (b-a).cross(c-a).z
            out.append(tri if nz >= 0 else (tri[0],tri[2],tri[1]))
    return out


def _curb_occupies_fraction(config, side, fraction):
    return any(
        segment["side"] == side
        and float(segment["start_fraction"]) <= fraction <= float(segment["end_fraction"])
        for segment in config.get("curb", {}).get("segments", [])
    )


def build_roadside_shoulder(points, side, config, material):
    road_half = float(config["road"]["width_m"]) * 0.5
    width = max(0.0, float(config.get("terrain", {}).get("roadside_visual_width_m", 1.4)))
    if width <= 0.01:
        return None
    sign = 1.0 if side == "right" else -1.0
    verts = []
    n = len(points)
    surface_z = float(config["road"].get("surface_elevation_m", 0.025))
    for i, p in enumerate(points):
        _, normal, bank = cross_frame(points, i, config)
        center = godot_xz_to_blender(p[0], p[1], surface_z)
        edge_signed = road_half * sign
        edge_h = math.tan(bank) * edge_signed
        edge = center + normal * edge_signed + Vector((0, 0, edge_h + 0.0015))
        outer_d = road_half + width
        sample = NearestTrackSample(outer_d, i / n, sign, outer_d * sign)
        outer_h = terrain_height_from_sample(config, sample, visual=False)
        outer = center + normal * (outer_d * sign)
        outer.z = outer_h + 0.0015
        verts.extend([tuple(edge), tuple(outer)])
    faces = [
        (2*i, 2*((i+1)%n), 2*((i+1)%n)+1, 2*i+1)
        for i in range(n)
        if not _curb_occupies_fraction(config, side, (i + 0.5) / n)
    ]
    return mesh_object(
        ("Right" if sign > 0 else "Left") + "RoadsideVisual",
        verts, faces, [material], planar_uv_scale_m=3.0,
    )


def build_roadside_collision(points, side, config):
    road_half = float(config["road"]["width_m"]) * 0.5
    width = max(.25, float(config.get("terrain",{}).get("roadside_collision_width_m",2.0)))
    sign = 1.0 if side == "right" else -1.0
    verts = []
    n = len(points)
    surface_z = float(config["road"].get("surface_elevation_m",0.025))
    for i,p in enumerate(points):
        _,normal,bank = cross_frame(points,i,config)
        center = godot_xz_to_blender(p[0],p[1],surface_z)
        edge_signed = road_half*sign
        edge = center + normal*edge_signed + Vector((0,0,math.tan(bank)*edge_signed))
        outer_d = road_half+width
        sample = NearestTrackSample(outer_d,i/n,sign,outer_d*sign)
        outer_h = terrain_height_from_sample(config,sample,visual=False)
        outer = center+normal*(outer_d*sign)
        outer.z = outer_h
        verts.extend([tuple(edge),tuple(outer)])
    quads = [
        (2*i,2*((i+1)%n),2*((i+1)%n)+1,2*i+1)
        for i in range(n)
        if not _curb_occupies_fraction(config, side, (i + 0.5) / n)
    ]
    faces = _upward_triangles(verts,quads)
    obj = mesh_object(("GrassEdgeCollisionRight" if sign>0 else "GrassEdgeCollisionLeft")+"-colonly",verts,faces)
    obj.hide_render=True
    obj.display_type="WIRE"
    obj["formula90s_exact_road_grass_bridge"] = True
    return obj


def build_terrain(points, config, material):
    cverts, faces, stats = build_heightfield(points, config, visual=False)
    vverts, vfaces, _ = build_heightfield(points, config, visual=True)
    if vfaces != faces:
        raise RuntimeError("Visual/collision terrain topology diverged unexpectedly")
    convert = lambda vv: [(x, -z, y) for x, z, y in vv]
    texture_world_size_m = max(
        1.0,
        float(config.get("terrain", {}).get("texture_world_size_m", 96.0)),
    )
    visual = mesh_object(
        "GrassTerrainVisual",
        convert(vverts), faces, [material], planar_uv_scale_m=texture_world_size_m,
    )
    col = mesh_object("GrassTerrainCollision-colonly", convert(cverts), faces)
    col.hide_render = True
    col.display_type = "WIRE"
    visual["formula90s_terrain_grid_cell_m"] = stats["cell_m"]
    col["formula90s_terrain_grid_cell_m"] = stats["cell_m"]
    col["formula90s_collision_grid_continuous"] = True
    col["formula90s_collision_winding"] = "upward"
    return stats


def build_safety_floor(stats, config):
    terrain = config.get("terrain", {})
    z = float(terrain.get("safety_floor_z_m", -6.0))
    thickness = max(0.2, float(terrain.get("safety_floor_thickness_m", 0.6)))
    margin = max(10.0, float(terrain.get("safety_floor_margin_m", 80.0)))
    width = float(stats["max_x"] - stats["min_x"]) + margin * 2.0
    depth = float(stats["max_z"] - stats["min_z"]) + margin * 2.0
    cx = (float(stats["max_x"]) + float(stats["min_x"])) * 0.5
    cz_godot = (float(stats["max_z"]) + float(stats["min_z"])) * 0.5
    cy = -cz_godot
    bpy.ops.mesh.primitive_cube_add(location=(cx, cy, z - thickness * 0.5))
    obj = bpy.context.object
    obj.name = "GrassSafetyFloor-colonly"
    obj.scale = (width * 0.5, depth * 0.5, thickness * 0.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.hide_render = True
    obj.display_type = "WIRE"
    obj["formula90s_failsafe_only"] = True
    return obj


def build_start_finish(config, material):
    width = float(config["road"]["width_m"])
    line_width = float(config["start_finish"]["line_width_m"])
    z = float(config["road"]["surface_elevation_m"])
    mesh = bpy.data.meshes.new("StartFinishMesh")
    mesh.from_pydata(
        [(-width * .5, -line_width * .5, z + .014),
         ( width * .5, -line_width * .5, z + .014),
         ( width * .5,  line_width * .5, z + .014),
         (-width * .5,  line_width * .5, z + .014)],
        [], [(0, 1, 2, 3)],
    )
    uv = mesh.uv_layers.new(name="UVMap")
    # 062 contains 8 x 16 checker cells. Rotate it so the long texture axis
    # crosses the track, repeating to yield ~32 x 2 near-square cells.
    for loop, coord in zip(uv.data, ((0.0, 0.0), (0.0, 2.0), (0.25, 2.0), (0.25, 0.0))):
        loop.uv = coord
    line = bpy.data.objects.new("StartFinish", mesh)
    bpy.context.collection.objects.link(line)
    line.data.materials.append(material)


def build_spawn_marker(config):
    spawn = float(config["start_finish"]["spawn_before_m"])
    z = float(config["road"]["surface_elevation_m"])
    marker = bpy.data.objects.new("PlayerSpawn", None)
    marker.location = godot_xz_to_blender(0, spawn, z)
    bpy.context.scene.collection.objects.link(marker)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    ns = parser.parse_args(args_after_double_dash())
    cp = Path(ns.config).resolve()
    repo = cp.parents[3]
    config = read_json(cp)
    curb_manifest = load_curb_manifest(cp, config)
    center = read_json(repo / config["generated_dir"] / "centerline.json")
    points = center["points_xz"]
    clear_scene()
    generated = repo / config["generated_dir"]
    runtime = repo / config["runtime_dir"]
    materials = build_material_library(generated / "textures", curb_manifest)
    z = float(config["road"]["surface_elevation_m"])
    half = float(config["road"]["width_m"]) * .5

    stats = build_terrain(points, config, materials["ground"])
    build_safety_floor(stats, config)
    build_ribbon(points, half, z, "RoadVisual", materials["asphalt"], "RoadCollision-colonly", config)
    build_roadside_shoulder(points, "left", config, materials["shoulder"])
    build_roadside_shoulder(points, "right", config, materials["shoulder"])
    build_roadside_collision(points, "left", config)
    build_roadside_collision(points, "right", config)
    lw = float(config["road"]["edge_line_width_m"])
    build_edge_line(points, "left", half, lw, config, materials["edge_line"], z)
    build_edge_line(points, "right", half, lw, config, materials["edge_line"], z)
    for segment in config["curb"]["segments"]:
        build_curb(points, segment, half, curb_manifest, materials, config, z)
    build_start_finish(config, materials["start_finish"])
    build_spawn_marker(config)

    generated.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    blend = generated / "track_base.blend"
    glb = runtime / f"{config['track_id']}_base.glb"
    live = runtime / f"{config['track_id']}.glb"
    atomic_save_blend(blend, generated / "backups" / "base")
    atomic_export_glb(glb)
    atomic_publish(glb, live)
    print(f"[blender] terrain grid vertices={stats['vertices']} triangles={stats['triangles']} cell={stats['cell_m']:.2f}m")
    print(f"[blender] terrain far z={effective_far_ground_z(config):.3f}m safety_floor={config.get('terrain',{}).get('safety_floor_z_m',-6.0):.2f}m")
    print(f"[blender] published runtime: {live}")


if __name__ == "__main__":
    main()
