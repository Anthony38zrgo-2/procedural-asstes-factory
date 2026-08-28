from __future__ import annotations

import argparse
import hashlib
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
from safety_barrier_layout import SafetyBarrierLayoutError, barrier_envelope_at
from procedural_assets_blender import (
    create_prototypes,
    create_safety_barrier_ribbon_collision,
    create_safety_barrier_prototype,
    create_tire_barrier_collision,
    create_tire_barrier_card_visual,
    create_tire_barrier_visual,
    create_trackside_card,
    instantiate_prototype,
    sample_centerline,
    terrain_height,
)
from procedural_catalog import biome_from_config
from procedural_materials_blender import add_safety_barrier_materials, build_material_library
from safety_barrier_layout import compile_layout, load_safety_barrier_layout
from building_asset_library import load_building_asset_library


def resolve_factory_path(repo, relative):
    path = (repo / relative).resolve()
    if path.is_file():
        return path
    factory_path = (repo.parent / relative).resolve()
    if factory_path.is_file():
        return factory_path
    raise FileNotFoundError(f"Factory asset does not exist: {relative}")


def load_glb_vegetation_prototypes(repo, placement_items):
    prototypes = {}
    for item in placement_items:
        asset_glb = item.get("asset_glb")
        variant_id = item["variant_id"]
        if not asset_glb or variant_id in prototypes:
            continue
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(repo / asset_glb))
        sources = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
        if not sources:
            raise RuntimeError(f"GLB vegetation asset has no mesh objects: {asset_glb}")
        for source in sources:
            source.hide_render = True
            source.hide_viewport = True
            source.hide_set(True)
        prototypes[variant_id] = sources
    return prototypes


def load_trackside_card_prototypes(repo, config):
    relative = config.get("trackside_props", {}).get(
        "object_catalog", "blender/track_pipeline/layouts/la_chutana/object_catalog.json"
    )
    catalog = read_json(repo / relative).get("objects", {})
    prototypes = {}
    for spec in catalog.values():
        asset_glb = spec.get("asset_glb")
        asset_id = spec.get("asset_id")
        if not asset_glb or not asset_id:
            continue
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str((repo / asset_glb).resolve()))
        imported = [obj for obj in bpy.data.objects if obj not in before]
        sources = [obj for obj in imported if obj.type == "MESH"]
        if not sources:
            raise RuntimeError(f"Trackside GLB asset has no mesh objects: {asset_glb}")
        for source in imported:
            source.hide_render = True
            source.hide_viewport = True
            source.hide_set(True)
        prototypes[str(asset_id)] = sources
    return prototypes


def build_background_cards(repo, config, points):
    cfg = config.get("procedural_environment", {}).get("background_cards", {})
    if not cfg.get("enabled", False):
        return {"instances": 0, "layers": {}}
    manifest = read_json(resolve_factory_path(repo, cfg["asset_manifest"]))
    if manifest.get("generator") != "background_billboard_v1":
        raise RuntimeError("Unsupported background-card manifest")
    prototypes = {}
    specs_by_layer = {"far": [], "near": [], "transition": []}
    for spec in manifest.get("assets", []):
        path = resolve_factory_path(repo, spec["glb"])
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(path))
        imported = [obj for obj in bpy.data.objects if obj not in before]
        sources = [obj for obj in imported if obj.type == "MESH"]
        if not sources:
            raise RuntimeError(f"Background GLB has no mesh: {path}")
        for obj in imported:
            obj.hide_render = True
            obj.hide_viewport = True
            obj.hide_set(True)
        prototypes[spec["id"]] = sources[0]
        specs_by_layer[spec["layer"]].append(spec)

    cx = sum(float(point[0]) for point in points) / len(points)
    cy = -sum(float(point[1]) for point in points) / len(points)
    collection = bpy.data.collections.new("BackgroundCards")
    bpy.context.scene.collection.children.link(collection)
    counts = {}
    for layer in (("far", "near") if cfg.get("mountain_ribbons_enabled", False) else ()):
        specs = specs_by_layer[layer]
        radius = float(cfg[f"{layer}_radius_m"])
        height = float(cfg[f"{layer}_height_m"])
        segments = int(cfg.get("ribbon_segments", 192))
        modules = int(cfg.get("ribbon_modules", 12))
        wave = float(cfg.get("radial_wave_m", 55.0)) * (1.35 if layer == "far" else 1.0)
        vertices = []
        faces = []
        for index in range(segments + 1):
            angle = 2.0 * math.pi * index / segments
            radial = radius + wave * math.sin(angle * 3.0 + (0.8 if layer == "near" else 0.0)) + wave * .35 * math.sin(angle * 7.0)
            x, y = cx + radial * math.cos(angle), cy + radial * math.sin(angle)
            vertices.extend(((x, y, -12.0 if layer == "far" else -7.0), (x, y, height)))
            if index < segments:
                faces.append((index * 2, index * 2 + 1, index * 2 + 3, index * 2 + 2))
        mesh = bpy.data.meshes.new(f"BackgroundRibbon_{layer}_mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            module_pos = (poly.index * modules / segments) % 1.0
            module_next = ((poly.index + 1) * modules / segments) % 1.0
            if module_next < module_pos:
                module_next = 1.0
            for loop_index, uv in zip(poly.loop_indices, ((module_pos, 0), (module_pos, 1), (module_next, 1), (module_next, 0))):
                mesh.uv_layers.active.data[loop_index].uv = uv
            poly.material_index = int(poly.index * modules / segments) % len(specs)
        obj = bpy.data.objects.new(f"BackgroundRibbon_{layer}", mesh)
        collection.objects.link(obj)
        for spec in specs:
            obj.data.materials.append(prototypes[spec["id"]].data.materials[0])
        obj["background_layer"] = layer
        obj["collision"] = False
        if hasattr(obj, "visible_shadow"):
            obj.visible_shadow = False
        counts[layer] = 1

    transition_specs = specs_by_layer["transition"]
    settlement_specs = [spec for spec in transition_specs if "settlement" in spec["id"]]
    forest_specs = [spec for spec in transition_specs if "forest" in spec["id"]]
    transition_groups = (
        ("settlement", settlement_specs, int(cfg.get("settlement_count", 8)),
         float(cfg["transition_radius_m"]), float(cfg["transition_height_m"]), 0.23),
        ("forest", forest_specs, int(cfg.get("forest_count", 16)),
         float(cfg.get("forest_radius_m", cfg["transition_radius_m"])),
         float(cfg.get("forest_height_m", cfg["transition_height_m"])), 0.23 + math.pi / 16.0),
    )
    for group, specs, count, radius, height, phase in transition_groups:
        if not specs:
            raise RuntimeError(f"Background-card manifest has no {group} transition asset")
        for index in range(count):
            spec = specs[index % len(specs)]
            width = height * float(spec["aspect"])
            source = prototypes[spec["id"]]
            angle = 2.0 * math.pi * index / count + phase
            obj = source.copy()
            obj.data = source.data
            obj.name = f"Background_transition_{group}_{index:02d}_{spec['id']}"
            collection.objects.link(obj)
            obj.hide_render = False
            obj.hide_viewport = False
            obj.hide_set(False)
            if hasattr(obj, "visible_shadow"):
                obj.visible_shadow = False
            obj.location = (cx + radius * math.cos(angle), cy + radius * math.sin(angle), -7.0)
            # The authored card front normal is local -Y. This rotation points
            # it radially inward so every distant card faces the circuit.
            obj.rotation_euler[2] = angle - math.pi / 2.0
            obj.scale = (width / float(spec["aspect"]), 1.0, height)
            obj["background_layer"] = "transition"
            obj["background_group"] = group
            obj["collision"] = False
        counts[group] = count
    return {"instances": sum(counts.values()), "layers": counts}


def _resolve_mountain_manifest(repo: Path, rel: str) -> Path:
    # Mirrors resolve_factory_path but returns Path even if not yet validated
    p1 = (repo / rel).resolve()
    if p1.is_file():
        return p1
    if rel.startswith("../"):
        stripped = rel
        while stripped.startswith("../"):
            stripped = stripped[3:]
        p2 = (repo.parent / stripped).resolve()
        if p2.is_file():
            return p2
        try:
            p3 = (repo.parent / Path(rel).relative_to("../")).resolve()
            if p3.is_file():
                return p3
        except Exception:
            pass
    p4 = (repo.parent / rel).resolve()
    if p4.is_file():
        return p4
    # fallback: return first candidate for error reporting
    return p1


def _validate_mountain_manifest(repo: Path, config: dict) -> dict | None:
    mountains = config.get("procedural_environment", {}).get("mountains", {})
    if not mountains.get("enabled", False):
        return None
    rel_manifest = mountains.get("manifest")
    if not rel_manifest:
        raise RuntimeError("procedural_environment.mountains.enabled but manifest path missing")
    manifest_path = _resolve_mountain_manifest(repo, rel_manifest)
    if not manifest_path.is_file():
        raise RuntimeError(f"Mountains manifest not found: {manifest_path} (declared {rel_manifest})")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported mountains schema_version={manifest.get('schema_version')} expected 1")
    if manifest.get("asset") != "la_chutana_mountains_3d":
        raise RuntimeError(f"Unexpected mountains asset={manifest.get('asset')} expected la_chutana_mountains_3d")
    if mountains.get("collision", False) is not False:
        raise RuntimeError("Mountains collision must be false")
    base_dir = manifest_path.parent
    geom = manifest.get("geometry_assets", {})
    tex = manifest.get("textures", {})
    sha_map = manifest.get("validation", {}).get("source_sha256", {})
    coord = manifest.get("coordinate_convention", {})
    if coord.get("up") != "+Y" or coord.get("forward") != "-Z":
        raise RuntimeError(f"Unexpected mountain coordinate convention {coord}")
    checks = []
    if mountains.get("near_enabled", True):
        checks.append(("near_mountains", geom.get("near_mountains")))
    if mountains.get("far_enabled", True):
        checks.append(("far_mountains", geom.get("far_mountains")))
    if mountains.get("sky_dome_enabled", False):
        checks.append(("sky_dome", geom.get("sky_dome")))
    if tex.get("mountain_texture"):
        checks.append(("mountain_texture", tex.get("mountain_texture")))
    for _key, fname in checks:
        if not fname:
            raise RuntimeError(f"Mountains manifest missing entry for {_key}")
        fpath = (base_dir / fname).resolve()
        if not fpath.is_file():
            raise RuntimeError(f"Mountains asset missing: {fpath} (manifest declares {fname})")
        expected = sha_map.get(fname)
        if not expected:
            raise RuntimeError(f"Mountains manifest has no SHA for {fname}")
        actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Mountains SHA mismatch for {fname}: expected {expected} got {actual} file {fpath}")
    return manifest


def _detect_y_up_needs_conversion(objs) -> bool:
    """Detect if imported mountain objects still need Y-up -> Z-up conversion.
    Returns True if height is still on Y (needs Rx -90), False if already Z-up.
    """
    # Aggregate bbox size across meshes
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    has_mesh = False
    for obj in objs:
        if obj.type != "MESH":
            continue
        # Use object's bound_box (object space) - 8 corners
        for corner in obj.bound_box:
            # corner is Vector in object local space
            wx, wy, wz = corner[0], corner[1], corner[2]
            # Account for object scale (usually 1)
            wx *= obj.scale[0]
            wy *= obj.scale[1]
            wz *= obj.scale[2]
            min_x = min(min_x, wx); max_x = max(max_x, wx)
            min_y = min(min_y, wy); max_y = max(max_y, wy)
            min_z = min(min_z, wz); max_z = max(max_z, wz)
            has_mesh = True
    if not has_mesh:
        return True  # default to convert
    size_y = max_y - min_y
    size_z = max_z - min_z
    size_x = max_x - min_x
    # Y-up mountains: Y ~ 100-220, Z ~ 3600 (far) or 2976 (near). X similar to Z.
    # Z-up (already converted): Z ~ 100-220, Y ~ 3600.
    # So if size_y is the height (<300) and size_z is large (>1000), Y is still up -> needs conversion.
    # If size_z is height (<300) and size_y large -> already converted.
    if size_y < 400 and size_z > 1000:
        return True
    if size_z < 400 and size_y > 1000:
        return False
    # Fallback heuristic: height is smallest of Y/Z if one dominates
    # If still ambiguous, assume needs conversion
    return size_y < size_z


def _import_mountain_layer(repo: Path, manifest_path: Path, fname: str, layer_name: str, collection, parent_empty, cx: float, cy: float, cast_shadows: bool):
    base_dir = manifest_path.parent
    fpath = (base_dir / fname).resolve()
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(fpath))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        raise RuntimeError(f"Mountains GLB imported no objects: {fpath}")
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"Mountains GLB has no mesh: {fpath}")
    # Detect if conversion needed (global, but we check once per import batch)
    needs_conversion = _detect_y_up_needs_conversion(imported)
    # Ensure collection
    for obj in imported:
        # Move to Mountains collection
        try:
            bpy.context.scene.collection.objects.unlink(obj)
        except Exception:
            pass
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        # Mark properties
        obj["mountain_layer"] = layer_name
        obj["mountain_glb"] = fname
        obj["collision"] = False
        obj["mountain_collection"] = "Mountains"
        if hasattr(obj, "visible_shadow"):
            obj.visible_shadow = bool(cast_shadows)
        # Ensure no accidental shadow casting unless desired
        obj.hide_render = False
        obj.hide_viewport = False
        obj.hide_set(False)
    # Parenting to conversion empty
    if needs_conversion:
        for obj in imported:
            # Keep transform: parent to empty, keep world transform via matrix_parent_inverse
            if obj.parent is None:
                obj.parent = parent_empty
                obj.matrix_parent_inverse = parent_empty.matrix_world.inverted()
    else:
        # Already Z-up: just ensure parent is at least Mountains collection, but not apply extra rotation
        # Tag for report
        for obj in imported:
            obj["mountain_axis_conversion_applied"] = "importer_auto_converted"
    # Return metrics
    verts = 0
    faces = 0
    bbox_min = [float("inf"), float("inf"), float("inf")]
    bbox_max = [float("-inf"), float("-inf"), float("-inf")]
    for mesh in meshes:
        me = mesh.data
        verts += len(me.vertices)
        faces += len(me.polygons)
        for corner in mesh.bound_box:
            # Convert to world via parent_empty transformation
            world_co = parent_empty.matrix_world @ mesh.matrix_world @ Vector(corner) if needs_conversion else mesh.matrix_world @ Vector(corner)
            # Adjust for cx,cy already via parent_empty location
            bbox_min[0] = min(bbox_min[0], world_co.x)
            bbox_min[1] = min(bbox_min[1], world_co.y)
            bbox_min[2] = min(bbox_min[2], world_co.z)
            bbox_max[0] = max(bbox_max[0], world_co.x)
            bbox_max[1] = max(bbox_max[1], world_co.y)
            bbox_max[2] = max(bbox_max[2], world_co.z)
    # Fix inf if no mesh
    if bbox_min[0] == float("inf"):
        bbox_min = [0.0, 0.0, 0.0]
        bbox_max = [0.0, 0.0, 0.0]
    return {"imported": imported, "meshes": meshes, "vertices": verts, "faces": faces, "bbox_min": bbox_min, "bbox_max": bbox_max, "needs_conversion": needs_conversion}


def build_mountains(repo: Path, config: dict, points):
    mountains_cfg = config.get("procedural_environment", {}).get("mountains", {})
    if not mountains_cfg.get("enabled", False):
        return {"enabled": False, "layers": {}}
    manifest_path = _resolve_mountain_manifest(repo, mountains_cfg.get("manifest"))
    manifest = _validate_mountain_manifest(repo, config)
    if manifest is None:
        return {"enabled": False, "layers": {}}
    # Center like background cards
    cx = sum(float(p[0]) for p in points) / len(points)
    cy = -sum(float(p[1]) for p in points) / len(points)
    transform_cfg = mountains_cfg.get("transform", {})
    # Use configured rotation, default -90 X
    rot_deg = transform_cfg.get("rotation_euler_deg", [-90, 0, 0])
    # Mountains are authored at origin; if circuit centroid is far from origin, we could offset,
    # but spec says if origin matches Chutana origin, do not introduce arbitrary offsets.
    # So we keep translation at (0,0,0) unless centroid is significant (>5m) and mountain origin is 0.
    # Here we keep parent_empty at (cx,cy,0) only if needed; but default spec says translation 0.
    # We respect transform_cfg translation if provided, else use 0.
    trans = transform_cfg.get("translation_m", [0, 0, 0])
    # If centroid is near zero, translation should remain 0 regardless of cx,cy to avoid double offset.
    # We log centroid for audit.
    # Create collection
    collection = bpy.data.collections.new("Mountains")
    bpy.context.scene.collection.children.link(collection)
    # Create conversion parent empty
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(float(trans[0]), float(trans[1]), float(trans[2])))
    parent_empty = bpy.context.object
    parent_empty.name = "MountainsRoot"
    parent_empty.empty_display_size = 2.0
    # Apply rotation: convert deg to rad
    parent_empty.rotation_euler = (math.radians(float(rot_deg[0])), math.radians(float(rot_deg[1])), math.radians(float(rot_deg[2])))
    # Tag parent
    parent_empty["mountain_root"] = True
    parent_empty["mountain_axis_conversion"] = "Y-up_to_Z-up"
    parent_empty["mountain_manifest"] = str(manifest_path)
    parent_empty["collision"] = False
    parent_empty["mountain_centroid_cx"] = float(cx)
    parent_empty["mountain_centroid_cy"] = float(cy)
    if hasattr(parent_empty, "visible_shadow"):
        parent_empty.visible_shadow = False
    # Ensure parent is in Mountains collection as well
    try:
        bpy.context.scene.collection.objects.unlink(parent_empty)
    except Exception:
        pass
    collection.objects.link(parent_empty)
    cast_shadows = bool(mountains_cfg.get("cast_shadows", False))
    # Import layers
    geom = manifest.get("geometry_assets", {})
    sha_map = manifest.get("validation", {}).get("source_sha256", {})
    layers = {}
    total_vertices = 0
    total_faces = 0
    # Near
    if mountains_cfg.get("near_enabled", True):
        fname = geom.get("near_mountains")
        res = _import_mountain_layer(repo, manifest_path, fname, "near", collection, parent_empty, cx, cy, cast_shadows)
        total_vertices += res["vertices"]
        total_faces += res["faces"]
        layers["near"] = {"glb": fname, "sha256": sha_map.get(fname), "vertices": res["vertices"], "faces": res["faces"], "bbox_min": res["bbox_min"], "bbox_max": res["bbox_max"], "needs_conversion": res["needs_conversion"], "nodes": len(res["imported"]), "meshes": len(res["meshes"])}
    # Far
    if mountains_cfg.get("far_enabled", True):
        fname = geom.get("far_mountains")
        res = _import_mountain_layer(repo, manifest_path, fname, "far", collection, parent_empty, cx, cy, cast_shadows)
        total_vertices += res["vertices"]
        total_faces += res["faces"]
        layers["far"] = {"glb": fname, "sha256": sha_map.get(fname), "vertices": res["vertices"], "faces": res["faces"], "bbox_min": res["bbox_min"], "bbox_max": res["bbox_max"], "needs_conversion": res["needs_conversion"], "nodes": len(res["imported"]), "meshes": len(res["meshes"])}
    # Sky dome optional
    sky_result = None
    if mountains_cfg.get("sky_dome_enabled", False):
        sky_fname = geom.get("sky_dome")
        try:
            res = _import_mountain_layer(repo, manifest_path, sky_fname, "sky_dome", collection, parent_empty, cx, cy, False)
            total_vertices += res["vertices"]
            total_faces += res["faces"]
            layers["sky_dome"] = {"glb": sky_fname, "sha256": sha_map.get(sky_fname), "vertices": res["vertices"], "faces": res["faces"], "bbox_min": res["bbox_min"], "bbox_max": res["bbox_max"], "needs_conversion": res["needs_conversion"], "nodes": len(res["imported"]), "meshes": len(res["meshes"])}
            sky_result = "imported"
        except Exception as exc:
            print(f"[mountains] sky dome import failed (optional, skipped): {exc}")
            layers["sky_dome"] = {"enabled": False, "reason": str(exc), "glb": sky_fname}
            sky_result = f"skipped: {exc}"
    # Mark all imported meshes parented (already) and ensure collection visibility
    # Store conversion info on each mesh
    for layer_data in layers.values():
        if "needs_conversion" in layer_data:
            for obj in collection.objects:
                if obj.get("mountain_layer") == layer_data.get("glb", "") or obj.get("mountain_layer") in layers:
                    pass
    # Attach custom props to parent for audit
    parent_empty["mountain_layers"] = ",".join(layers.keys())
    parent_empty["mountain_collision"] = False
    # Check apron invasion heuristic
    # Minimal distance from track centerline to mountain bbox (approx)
    # Use mountain bbox Z (?) after conversion height is Z. But we already transformed, so bbox_z is height.
    print(f"[mountains] imported layers={list(layers.keys())} vertices={total_vertices} faces={total_faces} centroid=({cx:.2f},{cy:.2f}) needs_conversion_near={layers.get('near',{}).get('needs_conversion')} far={layers.get('far',{}).get('needs_conversion')} sky={sky_result} collection=Mountains parent_rot={rot_deg} cast_shadows={cast_shadows}")
    return {
        "enabled": True,
        "manifest": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else "",
        "centroid": [float(cx), float(cy), 0.0],
        "transform": {"rotation_euler_deg": rot_deg, "translation_m": trans, "axis_conversion": "Y-up_to_Z-up"},
        "layers": layers,
        "total_vertices": total_vertices,
        "total_faces": total_faces,
        "collision": False,
        "cast_shadows": cast_shadows,
        "collection": "Mountains",
        "parent_empty": parent_empty.name,
    }


def load_barrier_asset_library(repo, config):
    """Load and verify the optional v2 barrier asset library before Blender import."""
    relative = config.get("safety_barriers", {}).get("asset_library_manifest")
    if not relative:
        return {}
    manifest_path = repo / relative
    manifest = read_json(manifest_path)
    if (manifest.get("schema_version"), manifest.get("generator")) not in (
        (2, "procedural_barrier_v2"), (3, "gen_barriers_v2"),
    ):
        raise RuntimeError(f"Unsupported barrier asset manifest: {manifest_path}")
    entries = {}
    for entry in manifest.get("assets", []):
        asset_id = entry["id"]
        if asset_id in entries:
            raise RuntimeError(f"Duplicate barrier asset id: {asset_id}")
        for path_key, hash_key in (("visual_glb", "visual_sha256"),
                                   ("collision_glb", "collision_sha256")):
            path = resolve_factory_path(repo, entry[path_key])
            if not path.is_file():
                raise RuntimeError(f"Barrier asset missing: {path}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != entry[hash_key]:
                raise RuntimeError(f"Barrier asset hash mismatch: {path}")
        entries[asset_id] = entry
    if not entries:
        raise RuntimeError(f"Barrier asset manifest has no assets: {manifest_path}")
    return entries


def import_barrier_asset_prototype(repo, entry):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(resolve_factory_path(repo, entry["visual_glb"])))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    sources = [obj for obj in imported if obj.type == "MESH"]
    if not sources:
        raise RuntimeError(f"Barrier GLB has no mesh objects: {entry['visual_glb']}")
    for index, source in enumerate(sources):
        source.data.name = f"{entry['id']}_visual" if index == 0 else f"{entry['id']}_visual_{index}"
    for source in imported:
        source.hide_render = True
        source.hide_viewport = True
        source.hide_set(True)
    return sources


def _aim(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def building_review_viewpoint(item, points):
    target_x = float(item["position_xz"][0])
    target_y = -float(item["position_xz"][1])
    track_pos, _, _ = sample_centerline(points, float(item["track_fraction"]))
    direction_x = float(track_pos[0]) - target_x
    direction_y = -float(track_pos[1]) - target_y
    length = max(1e-6, math.hypot(direction_x, direction_y))
    distance = 28.0
    return {
        "camera": (
            target_x + direction_x / length * distance,
            target_y + direction_y / length * distance,
            3.0,
        ),
        "target": (target_x, target_y, 3.0),
    }


def render_review_captures(config, points, output_dir, prefix="vegetation", viewpoints=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.world.color = (0.08, 0.10, 0.13)
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 120))
    sun = bpy.context.object
    sun.rotation_euler = (math.radians(28), math.radians(-18), math.radians(24))
    sun.data.energy = 2.4
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.lens = 42
    scene.camera = camera

    xs = [float(point[0]) for point in points]
    zs = [float(point[1]) for point in points]
    center = ((min(xs) + max(xs)) * 0.5, -(min(zs) + max(zs)) * 0.5, 0.0)
    span = max(max(xs) - min(xs), max(zs) - min(zs))
    camera.location = (center[0], center[1], span * 0.92)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = span * 1.18
    _aim(camera, center)
    review_token = "" if prefix == "safety_barrier" else "_review"
    aerial = output_dir / f"{prefix}{review_token}_aerial.png"
    scene.render.filepath = str(aerial)
    bpy.ops.render.render(write_still=True)

    camera.data.type = "PERSP"
    camera.data.lens = 46
    captures = [aerial]
    for name, viewpoint in (viewpoints or {"trackside": 0.56}).items():
        if isinstance(viewpoint, dict):
            camera.location = tuple(float(value) for value in viewpoint["camera"])
            _aim(camera, tuple(float(value) for value in viewpoint["target"]))
        else:
            fraction = float(viewpoint)
            pos, _, _ = sample_centerline(points, fraction)
            look, _, _ = sample_centerline(points, fraction + 0.025)
            camera.location = (float(pos[0]), -float(pos[1]), 2.2)
            _aim(camera, (float(look[0]), -float(look[1]), 1.0))
        target = output_dir / f"{prefix}{review_token}_{name}.png"
        scene.render.filepath = str(target)
        bpy.ops.render.render(write_still=True)
        captures.append(target)
    return captures


def render_safety_barrier_catalog(output_dir):
    representatives = {}
    for obj in bpy.data.objects:
        if obj.get("formula90s_safety_barrier") and obj.get("barrier_type") not in representatives:
            representatives[obj.get("barrier_type")] = obj
    order = (
        "armco", "tire_black_single", "tire_black_double", "tire_black_triple",
        "tire_navy_single", "tire_navy_double", "plastic", "jersey",
    )
    clones = []
    original_visibility = {obj: obj.hide_render for obj in bpy.data.objects}
    for obj in original_visibility:
        obj.hide_render = True
    present = [barrier_type for barrier_type in order if barrier_type in representatives]
    for index, barrier_type in enumerate(present):
        source = representatives.get(barrier_type)
        if source is None:
            continue
        root = source.copy()
        root.data = None
        root.location = ((index - (len(present) - 1) * 0.5) * 3.2, 0.0, 0.0)
        root.rotation_euler = (0.0, 0.0, 0.0)
        root.scale = (1.0, 1.0, 1.0)
        root.hide_render = False
        bpy.context.scene.collection.objects.link(root)
        clones.append(root)
        for child in source.children:
            copy = child.copy()
            copy.data = child.data
            copy.parent = root
            copy.matrix_parent_inverse.identity()
            copy.hide_render = False
            copy.hide_viewport = False
            copy.hide_set(False)
            bpy.context.scene.collection.objects.link(copy)
            clones.append(copy)
    scene = bpy.context.scene
    scene.world.color = (0.08, 0.10, 0.13)
    bpy.ops.object.light_add(type="SUN", location=(0.0, -8.0, 12.0))
    catalog_sun = bpy.context.object
    catalog_sun.rotation_euler = (math.radians(32), math.radians(-18), math.radians(24))
    catalog_sun.data.energy = 3.0
    clones.append(catalog_sun)
    camera = scene.camera
    if camera is None:
        bpy.ops.object.camera_add()
        camera = bpy.context.object
        scene.camera = camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(4.5, len(present) * 3.2)
    camera.hide_render = False
    camera.location = (0.0, -12.0, 3.0)
    _aim(camera, (0.0, 0.0, 0.55))
    target = output_dir / "safety_barrier_catalog.png"
    scene.render.filepath = str(target)
    bpy.ops.render.render(write_still=True)
    for obj in reversed(clones):
        bpy.data.objects.remove(obj, do_unlink=True)
    for obj, hidden in original_visibility.items():
        if obj.name in bpy.data.objects:
            obj.hide_render = hidden
    return target


def render_trackside_asset_captures(config, points, props, output_dir, prefix):
    """Render one exterior close-up for every resolved trackside asset."""
    scene = bpy.context.scene
    camera = scene.camera
    camera.data.type = "PERSP"
    camera.data.lens = 50
    representatives = {}
    for item in props:
        representatives.setdefault(str(item.get("source_asset_id") or item["prop_type"]), item)
    captures = []
    for asset_id, item in sorted(representatives.items()):
        _, _, normal = sample_centerline(points, float(item["track_fraction"]))
        side = int(item["side"])
        x, z = (float(value) for value in item["position_xz"])
        outward = Vector((float(normal[0]) * side, -float(normal[1]) * side, 0.0)).normalized()
        camera_distance = 12.0 if item["prop_type"] == "sign" else 6.0
        target = Vector((x, -z, 1.1))
        camera.location = target + outward * camera_distance + Vector((0.0, 0.0, .35))
        _aim(camera, target)
        path = output_dir / f"{prefix}_asset_{asset_id}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        captures.append(path)
    return captures


def args_after_double_dash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pattern_color(manifest, module):
    pattern = manifest["patterns"][module["material_style"]]
    mode = pattern["mode"]
    if mode == "longitudinal_band":
        return pattern["base"]
    if mode == "sparse_panels":
        period = max(1, int(pattern["period_modules"]))
        if module["module_index"] % period:
            return pattern["base"]
        colors = pattern["colors"]
        return colors[(module["pattern_phase"] // period) % len(colors)]
    spans = [max(1, int(value)) for value in pattern["span_modules"]]
    colors = pattern["colors"]
    position = (module["module_index"] + module["pattern_phase"]) % sum(spans)
    for color, span in zip(colors, spans):
        if position < span:
            return color
        position -= span
    return colors[-1]


def build_safety_barriers(config, points, materials):
    if not config.get("safety_barriers", {}).get("procedural", True):
        return {"modules": 0, "collisions": 0, "counts": {}, "sha256": ""}
    repo = Path(config["_repo_root"])
    manifest = load_safety_barrier_layout(repo, config)
    barrier_assets = load_barrier_asset_library(repo, config)
    compiled = compile_layout(manifest, float(config["_centerline_length_m"]))
    factory_root = repo.parent
    guardrail_bitmap = (factory_root / "assets-texturas" / "textures" / "objects_styles" /
                        "png" / "093.png")
    tire_bitmap = (factory_root / "assets-texturas" / "textures" / "objects_styles" /
                   "png" / "generated" /
                   "tire_barrier_smoke_blue_5x2_seamless_512x256.png")
    add_safety_barrier_materials(materials, manifest["palette"], guardrail_bitmap, tire_bitmap)
    prototype_cache = {}
    counts = {}
    asset_counts = {}
    segment_lookup = {segment["id"]: segment for segment in compiled["segments"]}
    modules_by_segment = {}
    for module in compiled["modules"]:
        segment = segment_lookup[module["segment_id"]]
        fraction = float(module["fraction"])
        side = 1 if module["side"] == "right" else -1
        distance = float(module["center_distance_m"])
        prototype = manifest["prototypes"][module["type"]]
        if prototype["geometry"] == "guardrail_armco":
            along = module["module_index"] * float(module["length_m"])
            remaining = float(segment["compiled_length_m"]) - along - float(module["length_m"])
            terminal_length = float(manifest["defaults"]["terminal_length_m"])
            terminal_flare = float(manifest["defaults"]["terminal_flare_m"])
            if segment["terminal_start"] == "flare_out":
                distance += terminal_flare * max(0.0, 1.0 - along / terminal_length)
            if segment["terminal_end"] == "flare_out":
                distance += terminal_flare * max(0.0, 1.0 - remaining / terminal_length)
        color = _pattern_color(manifest, module)
        asset_id = prototype.get("asset_id")
        asset_entry = barrier_assets.get(asset_id) if asset_id else None
        if asset_id and asset_entry is None:
            raise RuntimeError(f"Safety barrier prototype references unknown asset: {asset_id}")
        cache_key = ("asset", asset_id) if asset_entry else (module["type"], color)
        if cache_key not in prototype_cache:
            prototype_cache[cache_key] = (
                import_barrier_asset_prototype(repo, asset_entry)
                if asset_entry else
                create_safety_barrier_prototype(module["type"], prototype, materials, color)
            )
        pos, tangent, normal = sample_centerline(points, fraction)
        pos = (pos[0] + normal[0] * side * distance,
               pos[1] + normal[1] * side * distance)
        ground = terrain_height(config, fraction, side, distance)
        yaw = math.atan2(float(tangent[1]), float(tangent[0]))
        source_length = (float(asset_entry["visual"]["bounds_max"][0]) -
                         float(asset_entry["visual"]["bounds_min"][0])
                         if asset_entry else float(prototype["module_length_m"]))
        root = instantiate_prototype(
            prototype_cache[cache_key],
            f"Safety_{module['segment_id']}_{module['module_index']:04d}_{module['type']}",
            pos[0], pos[1], ground, yaw, float(module["length_m"]) / source_length,
        )
        root["formula90s_safety_barrier"] = True
        root["segment_id"] = module["segment_id"]
        root["barrier_type"] = module["type"]
        if asset_id:
            root["barrier_asset_id"] = asset_id
            asset_counts[asset_id] = asset_counts.get(asset_id, 0) + 1
        root["pattern_phase"] = int(module["pattern_phase"])
        segment_module_count = int(segment["module_count"])
        if prototype["geometry"] == "jersey_profile":
            ramp = 1.0
            if segment["terminal_start"] == "jersey_end" and module["module_index"] < 3:
                ramp = min(ramp, (module["module_index"] + 1) / 3.0)
            from_end = segment_module_count - int(module["module_index"])
            if segment["terminal_end"] == "jersey_end" and from_end <= 3:
                ramp = min(ramp, from_end / 3.0)
            root.scale.z *= ramp
        counts[module["type"]] = counts.get(module["type"], 0) + 1
        collision_module = dict(module)
        collision_module["_position_xz"] = pos
        collision_module["_ground_z"] = ground
        modules_by_segment.setdefault(module["segment_id"], []).append(collision_module)

    collisions = 0
    for segment_id, segment_modules in modules_by_segment.items():
        first = segment_modules[0]
        profile = manifest["collision_profiles"][first["collision_profile"]]
        samples = [(item["_position_xz"], float(item["_ground_z"]))
                   for item in segment_modules]
        create_safety_barrier_ribbon_collision(
            f"SafetyCollision_{segment_id}", samples, profile,
        )
        collisions += 1
    prototype_objects = [obj for objects in prototype_cache.values() for obj in objects]
    unique_meshes = {obj.data for obj in prototype_objects if obj.data is not None}
    vertices = sum(len(mesh.vertices) for mesh in unique_meshes)
    triangles = sum(sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons)
                    for mesh in unique_meshes)
    asset_manifest_relative = config.get("safety_barriers", {}).get("asset_library_manifest")
    asset_manifest_sha256 = (
        hashlib.sha256((repo / asset_manifest_relative).read_bytes()).hexdigest()
        if asset_manifest_relative else ""
    )
    return {"modules": len(compiled["modules"]), "collisions": collisions,
            "counts": counts, "sha256": compiled["sha256"],
            "asset_counts": asset_counts,
            "asset_manifest_sha256": asset_manifest_sha256,
            "segments": compiled["segments"], "prototype_count": len(prototype_cache),
            "material_count": 6, "vertices": vertices, "triangles": triangles}


def build_secondary_fence(config, points):
    settings = config.get("secondary_fence", {})
    if not settings.get("enabled", False):
        return {"modules": 0, "collisions": 0, "coverage": 0.0, "segments": {}}
    repo = Path(config["_repo_root"])
    manifest = read_json(resolve_factory_path(repo, settings["asset_manifest"]))
    if manifest.get("generator") != "secondary_fence_v1":
        raise RuntimeError("Unsupported secondary-fence manifest")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(resolve_factory_path(repo, manifest["visual_glb"])))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    sources = [obj for obj in imported if obj.type == "MESH"]
    if not sources:
        raise RuntimeError("Secondary-fence GLB has no mesh objects")
    for source in imported:
        source.hide_render = True
        source.hide_viewport = True
        source.hide_set(True)

    lap = float(config["_centerline_length_m"])
    primary_manifest = load_safety_barrier_layout(repo, config)
    module_length = float(settings.get("module_length_m", 4.0))
    setback = float(settings.get("offset_from_primary_outer_face_m", 7.0))
    collision_enabled = bool(settings.get("collision", True))
    fence_height = float(manifest["dimensions_m"][1])
    collision_mesh = None
    if collision_enabled:
        half_l, half_d, height = module_length * 0.5, 0.075, fence_height
        verts = [
            (-half_l, -half_d, 0.0), (half_l, -half_d, 0.0),
            (half_l, half_d, 0.0), (-half_l, half_d, 0.0),
            (-half_l, -half_d, height), (half_l, -half_d, height),
            (half_l, half_d, height), (-half_l, half_d, height),
        ]
        faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                 (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7)]
        collision_mesh = bpy.data.meshes.new("SecondaryFenceCollisionMesh")
        collision_mesh.from_pydata(verts, [], faces)
        collision_mesh.update()
    segment_counts = {}
    modules = collisions = 0
    coverage_sum = 0.0
    for segment in settings.get("segments", []):
        start = float(segment["start_fraction"]) % 1.0
        end = float(segment["end_fraction"]) % 1.0
        span = (end - start) % 1.0
        coverage_sum += span
        count = max(1, int(round(span * lap / module_length)))
        side = 1 if segment["side"] == "right" else -1
        for index in range(count):
            fraction = (start + span * (index + 0.5) / count) % 1.0
            envelope = barrier_envelope_at(primary_manifest, fraction, side, lap)
            distance = float(envelope["outer_face_distance_m"]) + setback
            pos, tangent, normal = sample_centerline(points, fraction)
            x = pos[0] + normal[0] * side * distance
            z = pos[1] + normal[1] * side * distance
            ground = terrain_height(config, fraction, side, distance)
            yaw = math.atan2(float(tangent[1]), float(tangent[0]))
            root = instantiate_prototype(
                sources, f"SecondaryFence_{segment['id']}_{index:04d}",
                x, z, ground, yaw, 1.0,
            )
            root["formula90s_secondary_fence"] = True
            root["segment_id"] = segment["id"]
            root["collision"] = False
            modules += 1
            if collision_enabled:
                col = bpy.data.objects.new(
                    f"SecondaryFence_{segment['id']}_{index:04d}-colonly",
                    collision_mesh,
                )
                bpy.context.scene.collection.objects.link(col)
                col.name = f"SecondaryFence_{segment['id']}_{index:04d}-colonly"
                col.location = (x, -z, ground)
                col.rotation_euler[2] = -yaw
                col.hide_render = True
                col.display_type = "WIRE"
                col["formula90s_collision"] = True
                col["formula90s_collision_kind"] = "secondary_fence_wall"
                collisions += 1
        segment_counts[segment["id"]] = count
    # Perimeter comprises both track sides, hence lap-equivalent coverage / 2.
    coverage = coverage_sum / 2.0
    target = float(settings.get("target_perimeter_coverage", coverage))
    if abs(coverage - target) > 1e-6:
        raise RuntimeError(f"Secondary-fence coverage {coverage:.6f} does not match target {target:.6f}")
    return {"modules": modules, "collisions": collisions, "coverage": coverage,
            "segments": segment_counts, "setback_m": setback}


def build_tire_barriers(config, points, materials):
    settings = config.get("tire_barriers", {})
    authority = config.get("safety_barriers", {})
    if authority.get("legacy_tire_barriers_disabled", False):
        if settings.get("procedural", False):
            raise RuntimeError("Contradictory barrier authority: legacy tire barriers are disabled but procedural legacy generation is enabled")
        return {"visual_modules": 0, "collision_segments": 0}
    if not settings.get("procedural", True):
        return {"visual_modules": 0, "collision_segments": 0}
    sides = (1, -1) if settings.get("both_sides", True) else (1,)
    visual_modules = 0
    collision_segments = 0
    visual_mode = settings.get("visual_mode", "legacy")
    asset_glb = settings.get("visual_asset_glb")
    card_materials = None
    front_uv_bounds = (0.0, 0.0, 1.0, 1.0)
    if visual_mode == "rectangular_prism":
        manifest_path = Path(settings["prepared_manifest"])
        if not manifest_path.is_absolute():
            manifest_path = Path(config["_repo_root"]) / manifest_path
        prepared = read_json(manifest_path)
        front_entry = prepared["sources"][prepared["module"]["front_source"]]
        front = Path(front_entry["texture"])
        side_texture = Path(prepared["sources"][prepared["module"]["side_source"]]["texture"])
        top_texture = Path(prepared["sources"][prepared["module"]["top_source"]]["texture"])
        x0, y0, x1, y1 = front_entry["metrics"]["output_bbox"]
        width, height = front_entry["metrics"]["output_size"]
        front_uv_bounds = (x0 / width, 1.0 - y1 / height, x1 / width, 1.0 - y0 / height)
        from procedural_materials_blender import texture_material
        card_materials = (
            texture_material("F90_TireBarrierCardFront", front, roughness=1.0, metallic=0.0, alpha=False),
            texture_material("F90_TireBarrierCardSide", side_texture, roughness=1.0, metallic=0.0, alpha=False),
            texture_material("F90_TireBarrierCardTop", top_texture, roughness=1.0, metallic=0.0, alpha=False),
        )
        # Check for multi-barrier materials and layout sectors
        repo = Path(config["_repo_root"])
        barriers_manifest_path = repo / "assets-lowpoly-python" / "track_props" / "barriers" / "source_manifest.json"
        multi_materials = {}
        if barriers_manifest_path.exists():
            bm = read_json(barriers_manifest_path)
            bdir = barriers_manifest_path.parent
            for b_type, b_info in bm.get("types", {}).items():
                f_tex = bdir / b_info["front"]
                t_tex = bdir / b_info["top"]
                e_tex = bdir / b_info["end"]
                r_val = 0.6 if b_type == "guardrail_armco" else 1.0
                m_val = 0.7 if b_type == "guardrail_armco" else 0.0
                f_mat = texture_material(f"F90_Barrier_{b_type}_Front", f_tex, roughness=r_val, metallic=m_val, alpha=False)
                s_mat = texture_material(f"F90_Barrier_{b_type}_Side", e_tex, roughness=r_val, metallic=m_val, alpha=False)
                t_mat = texture_material(f"F90_Barrier_{b_type}_Top", t_tex, roughness=r_val, metallic=m_val, alpha=False)
                multi_materials[b_type] = (f_mat, s_mat, t_mat)
        layout_cfg_path = repo / "blender" / "track_pipeline" / "layouts" / config.get("track_id", "la_chutana") / "layout_config.json"
        barrier_sectors = None
        if layout_cfg_path.exists():
            lcfg = read_json(layout_cfg_path)
            barrier_sectors = lcfg.get("barrier_sectors", lcfg.get("legacy_barrier_sectors"))
    for side in sides:
        side_name = "Right" if side > 0 else "Left"
        if card_materials:
            visual, modules = create_tire_barrier_card_visual(
                f"TireBarrierVisual{side_name}", points, side, config, *card_materials,
                front_uv_bounds=front_uv_bounds,
                multi_materials=multi_materials if multi_materials else None,
                barrier_sectors=barrier_sectors,
                exclude_spans=settings.get("exclude_spans", []),
            )
        else:
            visual, modules = create_tire_barrier_visual(
                f"TireBarrierVisual{side_name}", points, side, config, materials["tire_barrier"],
                asset_glb=asset_glb,
            )
        collision, segments = create_tire_barrier_collision(
            f"TireBarrierCollision{side_name}", points, side, config
        )
        visual_modules += modules
        collision_segments += segments
    return {"visual_modules": visual_modules, "collision_segments": collision_segments}


TRACKSIDE_CARD_CLEARANCE_M = 1.0


def barrier_outer_face_lookup(config):
    authority = config.get("safety_barriers", {})
    manifest_rel = authority.get("manifest")
    if not authority.get("procedural") or not manifest_rel:
        return None
    manifest = read_json(Path(config["_repo_root"]) / manifest_rel)
    lap = float(config["_centerline_length_m"])

    def lookup(fraction, side):
        try:
            envelope = barrier_envelope_at(manifest, float(fraction) % 1.0, int(side), lap)
        except SafetyBarrierLayoutError:
            return None
        return float(envelope["outer_face_distance_m"])

    return lookup


def build_trackside_props(config, points, props, materials, glb_prototypes=None):
    outer_face = barrier_outer_face_lookup(config)
    props_config = config.get("trackside_props", {})
    sign_scale = float(props_config.get("signs", {}).get("scale_multiplier", 1.0))
    flag_scale = float(props_config.get("flags", {}).get("scale_multiplier", 1.0))
    created = 0
    for item in props:
        prop_type = str(item["prop_type"])
        asset_id = str(item.get("source_asset_id") or prop_type)
        if prop_type not in {"spectator", "marshal", "photographer", "flag", "sign"}:
            raise RuntimeError(f"Unknown trackside prop type: {prop_type}")
        pos, tangent, normal = sample_centerline(points, float(item["track_fraction"]))
        side = int(item["side"])
        distance = float(item["distance_from_center_m"])
        authored = item.get("position_xz")
        card_pos = ((float(authored[0]), float(authored[1])) if authored else
                    (pos[0] + normal[0] * side * distance,
                     pos[1] + normal[1] * side * distance))
        lateral = ((card_pos[0] - pos[0]) * normal[0] +
                   (card_pos[1] - pos[1]) * normal[1])
        if outer_face is not None:
            required = outer_face(float(item["track_fraction"]), side)
            if required is not None:
                min_abs = required + TRACKSIDE_CARD_CLEARANCE_M
                target = min_abs if lateral >= 0 else -min_abs
                if abs(lateral) < min_abs:
                    card_pos = (card_pos[0] + normal[0] * (target - lateral),
                                card_pos[1] + normal[1] * (target - lateral))
                    distance = abs(target)
        ground = terrain_height(config, float(item["track_fraction"]), side, distance)
        if glb_prototypes and asset_id in glb_prototypes:
            yaw = math.atan2(float(tangent[1]), float(tangent[0]))
            instance_scale = sign_scale if prop_type == "sign" else 1.0
            root = instantiate_prototype(
                glb_prototypes[asset_id],
                f"Trackside_{prop_type}_{item['prop_id']}_{asset_id}",
                float(card_pos[0]), float(card_pos[1]), ground, yaw, instance_scale,
            )
            root["formula90s_trackside_card"] = prop_type
            root["formula90s_trackside_asset_id"] = asset_id
            root["formula90s_material_authority"] = "glb_embedded"
            root["formula90s_collision"] = False
            created += 1
            continue
        if prop_type == "flag" and asset_id == "track_flag":
            mat = (materials["flag_pole"], materials["flag_navy"], materials["flag_white"])
        else:
            mat = materials.get(f"card:{asset_id}") or materials.get(f"asset:{asset_id}")
            if mat is None:
                raise RuntimeError(f"Trackside asset has no source-backed material: {asset_id}")
        create_trackside_card(
            f"Trackside_{prop_type}_{item['prop_id']}_{asset_id}",
            card_pos,
            tangent,
            normal,
            side,
            ground,
            prop_type,
            mat,
            asset_id=asset_id,
            scale_multiplier=(flag_scale if prop_type == "flag" else
                              sign_scale if prop_type == "sign" else 1.0),
        )
        created += 1
    return created


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--vegetation-review", action="store_true")
    parser.add_argument("--guardrail-review", action="store_true")
    parser.add_argument("--safety-barrier-review", action="store_true")
    parser.add_argument("--signs-review", action="store_true")
    parser.add_argument("--people-review", action="store_true")
    parser.add_argument("--buildings-review", action="store_true")
    ns = parser.parse_args(args_after_double_dash())
    cp = Path(ns.config).resolve()
    repo = cp.parents[3]
    config = read_json(cp)
    config["_repo_root"] = str(repo)
    safety_authority = config.get("safety_barriers", {})
    if safety_authority.get("scope") == "full_circuit":
        if (not safety_authority.get("legacy_guardrails_disabled", False) or
                not safety_authority.get("legacy_tire_barriers_disabled", False) or
                config.get("guardrails", {}).get("procedural", False) or
                config.get("tire_barriers", {}).get("procedural", False)):
            raise RuntimeError("Full-circuit safety barrier authority requires every legacy barrier generator to be disabled")
    building_assets = load_building_asset_library(repo, config)
    building_asset_ids = {asset["id"] for asset in building_assets}
    generated = repo / config["generated_dir"]
    runtime = repo / config["runtime_dir"]
    base = generated / "track_base.blend"
    if not base.exists():
        raise RuntimeError(f"Base track missing: {base}. Run Base mode and validate it first.")

    center = read_json(generated / "centerline.json")
    placements = read_json(generated / "placements.json")
    config["_centerline_length_m"] = center["length_m"]
    points = center["points_xz"]
    bpy.ops.wm.open_mainfile(filepath=str(base))

    materials = build_material_library(generated / "textures")
    biome = biome_from_config(config)
    prototypes = create_prototypes(materials, config)
    prototypes.update(load_glb_vegetation_prototypes(repo, placements["placements"]))
    trackside_glb_prototypes = load_trackside_card_prototypes(repo, config)
    placed = 0
    for idx, item in enumerate(placements["placements"]):
        variant_id = item["variant_id"]
        if variant_id not in prototypes:
            raise RuntimeError(f"No Blender procedural prototype for {variant_id!r} in biome {biome.id!r}")
        x, z = item["position_xz"]
        h = terrain_height(
            config,
            float(item["track_fraction"]),
            float(item["side"]),
            float(item["distance_from_center_m"]),
        )
        root = instantiate_prototype(
            prototypes[variant_id],
            f"{item['category']}_{idx:04d}_{variant_id}",
            float(x), float(z), h,
            float(item["yaw_rad"]),
            float(item["scale"]),
            item.get("tint_rgb"),
            float(item.get("width_scale", 1.0)),
            float(item.get("height_scale", 1.0)),
        )
        building_asset_id = item.get("building_asset_id")
        if building_asset_id:
            if building_asset_id not in building_asset_ids:
                raise RuntimeError(f"Placement references unknown building asset: {building_asset_id}")
            root["building_asset_id"] = building_asset_id
            root["formula90s_scenic_building"] = True
            root["collision"] = False
        placed += 1

    review_mode = (
        ns.vegetation_review or ns.guardrail_review or ns.safety_barrier_review
        or ns.signs_review or ns.people_review or ns.buildings_review
    )
    safety = ({"modules": 0, "collisions": 0, "counts": {}, "sha256": ""}
              if ns.vegetation_review else build_safety_barriers(config, points, materials))
    secondary_fence = ({"modules": 0, "collisions": 0, "coverage": 0.0, "segments": {}}
                       if review_mode else build_secondary_fence(config, points))
    tire_barriers = ({"visual_modules": 0, "collision_segments": 0}
                     if ns.vegetation_review or ns.guardrail_review
                     else build_tire_barriers(config, points, materials))
    trackside_props = (0 if ns.vegetation_review or ns.guardrail_review
                       else build_trackside_props(config, points, placements.get("trackside_props", []), materials,
                                                  trackside_glb_prototypes))
    background_cards = ({"instances": 0, "layers": {}} if review_mode
                         else build_background_cards(repo, config, points))
    mountains = ({"enabled": False, "layers": {}} if review_mode
                 else build_mountains(repo, config, points))
    review_name = (
        "safety_barrier" if ns.safety_barrier_review else
        "guardrail" if ns.guardrail_review else
        "signs" if ns.signs_review else
        "people" if ns.people_review else
        "buildings" if ns.buildings_review else
        "vegetation"
    )
    blend = generated / (f"track_{review_name}_review.blend" if review_mode else "track_environment.blend")
    glb = runtime / (f"{config['track_id']}_{review_name}_review.glb" if review_mode else f"{config['track_id']}_environment.glb")
    live = runtime / f"{config['track_id']}.glb"
    atomic_save_blend(blend, generated / "backups" / "environment")
    atomic_export_glb(glb)
    safety_report = generated / "review" / "safety_barrier_report.json"
    safety_report.parent.mkdir(parents=True, exist_ok=True)
    safety_report.write_text(json.dumps(safety, indent=2), encoding="utf-8")
    secondary_fence_report = generated / "review" / "secondary_fence_report.json"
    secondary_fence_report.write_text(json.dumps(secondary_fence, indent=2), encoding="utf-8")
    building_counts = {
        asset_id: sum(item.get("building_asset_id") == asset_id for item in placements["placements"])
        for asset_id in sorted(building_asset_ids)
    }
    building_manifest_relative = config.get("procedural_environment", {}).get("fake_buildings", {}).get("asset_manifest")
    building_report = {
        "instances": sum(building_counts.values()), "asset_counts": building_counts,
        "collision": False,
        "asset_manifest_sha256": hashlib.sha256((repo / building_manifest_relative).read_bytes()).hexdigest(),
    }
    building_report_path = generated / "review" / "building_report.json"
    building_report_path.write_text(json.dumps(building_report, indent=2), encoding="utf-8")
    # --- Mountain report (Req.10) ---
    mountain_report_path = generated / "review" / "mountain_report.json"
    # Ensure serializable copy
    mountain_serializable = json.loads(json.dumps(mountains, default=str))
    # Add extra audit fields
    mountains_cfg = config.get("procedural_environment", {}).get("mountains", {})
    manifest_path_for_report = None
    try:
        manifest_path_for_report = str(_resolve_mountain_manifest(repo, mountains_cfg.get("manifest", "")))
    except Exception:
        manifest_path_for_report = mountains_cfg.get("manifest", "")
    mountain_audit = {
        "enabled": bool(mountains.get("enabled", False)),
        "manifest": mountains_cfg.get("manifest", ""),
        "manifest_resolved": manifest_path_for_report,
        "near_enabled": bool(mountains_cfg.get("near_enabled", False)),
        "far_enabled": bool(mountains_cfg.get("far_enabled", False)),
        "sky_dome_enabled": bool(mountains_cfg.get("sky_dome_enabled", False)),
        "collision": bool(mountains.get("collision", False) if mountains.get("enabled") else False),
        "cast_shadows": bool(mountains.get("cast_shadows", False)),
        "receive_shadows": bool(mountains_cfg.get("receive_shadows", False)),
        "transform": mountains.get("transform", mountains_cfg.get("transform", {})),
        "centroid": mountains.get("centroid", []),
        "layers": mountains.get("layers", {}),
        "total_vertices": mountains.get("total_vertices", 0),
        "total_faces": mountains.get("total_faces", 0),
        "collection": mountains.get("collection", ""),
        "parent_empty": mountains.get("parent_empty", ""),
        "validation": {
            "schema_version": 1,
            "asset": "la_chutana_mountains_3d",
            "hashes_match": True if mountains.get("enabled") else None,
            "files_exist": True if mountains.get("enabled") else None,
        },
        "raw": mountain_serializable,
    }
    mountain_report_path.parent.mkdir(parents=True, exist_ok=True)
    mountain_report_path.write_text(json.dumps(mountain_audit, indent=2), encoding="utf-8")
    print(f"[mountains] report: {mountain_report_path} enabled={mountain_audit['enabled']} layers={list(mountain_audit['layers'].keys())}")
    if review_mode:
        viewpoints = ({"main_straight": 0.96, "t1": 0.08, "t4": 0.40,
                       "chicane": 0.57, "t6": 0.79}
                      if (ns.safety_barrier_review or ns.signs_review or ns.people_review) else
                      {"t1": 0.055, "t4": 0.36, "chicane": 0.535, "t6": 0.735}
                      if ns.guardrail_review else
                      {
                          f"building_{index + 1:02d}": building_review_viewpoint(item, points)
                          for index, item in enumerate(
                              [entry for entry in placements["placements"] if entry.get("building_asset_id")][:4])
                      }
                      if ns.buildings_review else None)
        captures = render_review_captures(config, points, generated / "review", review_name, viewpoints)
        if ns.people_review or ns.signs_review:
            captures.extend(render_trackside_asset_captures(
                config, points, placements.get("trackside_props", []),
                generated / "review", review_name,
            ))
        if ns.safety_barrier_review:
            catalog = render_safety_barrier_catalog(generated / "review")
            captures.append(catalog)
            print(f"[blender] safety barrier report: {safety_report}")
        print(f"[blender] human-gate captures: {' '.join(map(str, captures))}")
    else:
        atomic_publish(glb, live)
    print(f"[blender] biome={biome.id} procedural placements={placed}")
    print(f"[blender] safety barriers modules={safety['modules']} collisions={safety['collisions']} counts={safety['counts']} sha256={safety['sha256']}")
    print(f"[blender] secondary fence modules={secondary_fence['modules']} collisions={secondary_fence['collisions']} coverage={secondary_fence['coverage']:.1%} segments={secondary_fence['segments']}")
    print(f"[blender] tire barriers visual_modules={tire_barriers['visual_modules']} collision_segments={tire_barriers['collision_segments']}")
    print(f"[blender] trackside cards={trackside_props} collision=False")
    print(f"[blender] scenic buildings={building_report['instances']} counts={building_counts} collision=False")
    print(f"[blender] background cards={background_cards['instances']} layers={background_cards['layers']} collision=False")
    if mountains.get("enabled"):
        print(f"[blender] mountains enabled=True layers={list(mountains.get('layers',{}).keys())} vertices={mountains.get('total_vertices')} faces={mountains.get('total_faces')} collision=False cast_shadows={mountains.get('cast_shadows')} parent={mountains.get('parent_empty')}")
    else:
        print(f"[blender] mountains enabled=False")
    print(f"[blender] {'review only; runtime not published' if review_mode else f'published runtime: {live}'}")


if __name__ == "__main__":
    main()
