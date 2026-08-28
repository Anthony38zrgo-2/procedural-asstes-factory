from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "procedural/generated/vegetation_v5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glb_json(path: Path) -> dict:
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        raise AssertionError(path)
    length, kind = struct.unpack_from("<II", raw, 12)
    if kind != 0x4E4F534A:
        raise AssertionError("GLB JSON chunk missing")
    return json.loads(raw[20 : 20 + length].decode("utf-8").rstrip(" \x00"))


class VegetationV5LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        cls.records = {(item["id"], item["variant"], item["lod"]): item for item in cls.manifest["records"]}

    def test_complete_original_matrix_is_present(self) -> None:
        self.assertEqual(11, self.manifest["base_assets"])
        self.assertEqual(110, self.manifest["variant_assets"])
        variants = {"green", "copper", "golden_beige", "red", "yellow"}
        ids = {f"tree_3d_{index:02d}" for index in range(1, 6)} | {f"bush_3d_{index:02d}" for index in range(1, 7)}
        self.assertEqual(ids, {key[0] for key in self.records})
        for asset_id in ids:
            for variant in variants:
                for lod in ("lod0", "lod1"):
                    self.assertIn((asset_id, variant, lod), self.records)

    def test_original_base_assets_were_not_overwritten(self) -> None:
        original = json.loads((REPO / "procedural/assets/manifest.json").read_text(encoding="utf-8"))
        for item in original["assets"]:
            category = "trees" if item["kind"] == "tree" else "bushes"
            path = REPO / "procedural/assets" / category / f"{item['id']}.glb"
            self.assertEqual(item["sha256"], sha256(path))

    def test_rejected_v5_trees_are_archived_and_replaced_by_derivatives(self) -> None:
        discard = OUTPUT / "discarded_assets"
        self.assertTrue((discard / "manifest_before_tree_replacement.json").is_file())
        self.assertEqual(40, len(list((discard / "trees").glob("*.glb"))))
        self.assertEqual(12, len(list((discard / "review").glob("*.png"))))
        expected_sources = {
            "tree_3d_01": "tree_3d_02",
            "tree_3d_04": "tree_3d_02",
            "tree_3d_05": "tree_3d_03",
        }
        for asset_id, source_id in expected_sources.items():
            derived = self.records[(asset_id, "green", "lod0")]
            source = self.records[(source_id, "green", "lod0")]
            self.assertEqual(source_id, derived["source_asset_id"])
            self.assertNotEqual("approved_original", derived["derivation"])
            self.assertLess(derived["dimensions"][2], source["dimensions"][2])
            self.assertGreater(max(derived["dimensions"][:2]), max(source["dimensions"][:2]))
        removed = discard / "removed_tree_3d_06"
        self.assertEqual(10, len(list((removed / "trees").glob("*.glb"))))
        self.assertEqual(2, len(list((removed / "review").glob("*.png"))))
        self.assertNotIn("tree_3d_06", {key[0] for key in self.records})

    def test_frozen_texture_release_is_unchanged(self) -> None:
        release_path = REPO / self.manifest["texture_release"]
        self.assertEqual(self.manifest["texture_release_sha256"], sha256(release_path))
        release = json.loads(release_path.read_text(encoding="utf-8"))
        for item in release["atlases"] + release["wood_materials"]:
            self.assertEqual(item["sha256"], sha256(REPO / item["path"]))

    def test_glb_material_and_draw_mesh_contract(self) -> None:
        for record in self.manifest["records"]:
            path = REPO / record["glb"]
            self.assertEqual(record["glb_sha256"], sha256(path))
            document = glb_json(path)
            self.assertEqual(2, len(document.get("meshes", [])))
            self.assertEqual(2, len(document.get("materials", [])))
            self.assertEqual(2, len(document.get("images", [])))
            materials = {item["name"]: item for item in document["materials"]}
            foliage = materials["foliage_broadleaf_alpha_mask"]
            wood = materials["wood_broadleaf_seamless"]
            self.assertEqual("MASK", foliage["alphaMode"])
            self.assertTrue(foliage["doubleSided"])
            self.assertEqual("OPAQUE", wood["alphaMode"])
            self.assertFalse(wood["doubleSided"])

    def test_lod_budgets_grounding_and_silhouette_stability(self) -> None:
        ids = sorted({key[0] for key in self.records})
        for asset_id in ids:
            lod0 = self.records[(asset_id, "green", "lod0")]
            lod1 = self.records[(asset_id, "green", "lod1")]
            self.assertLessEqual(lod0["triangles"], lod0["triangle_budget"])
            self.assertLessEqual(lod1["triangles"], lod1["triangle_budget"])
            self.assertLess(lod1["triangles"], lod0["triangles"] * 0.66)
            self.assertLess(abs(lod0["bounds_min"][2]), 0.01)
            self.assertLess(abs(lod1["bounds_min"][2]), 0.01)
            for axis in range(3):
                ratio = lod1["dimensions"][axis] / max(lod0["dimensions"][axis], 1e-6)
                self.assertTrue(0.72 <= ratio <= 1.28)

    def test_seasonal_variants_share_geometry_statistics(self) -> None:
        for asset_id in {key[0] for key in self.records}:
            for lod in ("lod0", "lod1"):
                reference = self.records[(asset_id, "green", lod)]
                for variant in ("copper", "golden_beige", "red", "yellow"):
                    candidate = self.records[(asset_id, variant, lod)]
                    self.assertEqual(reference["triangles"], candidate["triangles"])
                    self.assertEqual(reference["vertices"], candidate["vertices"])
                    self.assertEqual(reference["dimensions"], candidate["dimensions"])

    def test_visual_audits_exist(self) -> None:
        audited = [item for item in self.manifest["records"] if item["audit"]]
        self.assertEqual(30, len(audited))
        for record in audited:
            self.assertEqual(record["audit_sha256"], sha256(REPO / record["audit"]))
        for name in ("trees_v5_lod_comparison.png", "bushes_v5_lod_comparison.png", "vegetation_v5_seasonal_comparison.png"):
            self.assertTrue((OUTPUT / "review" / name).is_file())


if __name__ == "__main__":
    unittest.main()
