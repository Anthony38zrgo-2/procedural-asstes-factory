from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "procedural/generated/conifers_v5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glb_json(path: Path) -> dict:
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        raise AssertionError(f"not a GLB: {path}")
    length, kind = struct.unpack_from("<II", raw, 12)
    if kind != 0x4E4F534A:
        raise AssertionError("first GLB chunk is not JSON")
    return json.loads(raw[20 : 20 + length].decode("utf-8").rstrip(" \x00"))


class ConiferV5LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        cls.recipe = json.loads((REPO / cls.manifest["recipe"]).read_text(encoding="utf-8"))
        cls.records = {(item["id"], item["lod"]): item for item in cls.manifest["records"]}

    def test_three_assets_have_two_lods(self) -> None:
        self.assertEqual(6, len(self.manifest["records"]))
        self.assertEqual({item["id"] for item in self.recipe["assets"]}, {key[0] for key in self.records})
        for asset in self.recipe["assets"]:
            self.assertIn((asset["id"], "lod0"), self.records)
            self.assertIn((asset["id"], "lod1"), self.records)

    def test_frozen_texture_release_is_unchanged(self) -> None:
        release_path = REPO / self.manifest["texture_release"]
        self.assertEqual(self.manifest["texture_release_sha256"], sha256(release_path))
        release = json.loads(release_path.read_text(encoding="utf-8"))
        for item in release["atlases"] + release["wood_materials"]:
            self.assertEqual(item["sha256"], sha256(REPO / item["path"]))

    def test_lod_reduction_and_triangle_budgets(self) -> None:
        for asset in self.recipe["assets"]:
            lod0 = self.records[(asset["id"], "lod0")]
            lod1 = self.records[(asset["id"], "lod1")]
            self.assertLessEqual(lod0["triangles"], lod0["triangle_budget"])
            self.assertLessEqual(lod1["triangles"], lod1["triangle_budget"])
            self.assertLess(lod1["triangles"], lod0["triangles"] * 0.55)

    def test_assets_are_grounded_and_foliage_reaches_tip(self) -> None:
        heights = {item["id"]: float(item["height"]) for item in self.recipe["assets"]}
        for record in self.manifest["records"]:
            self.assertLess(abs(record["bounds_min"][2]), 0.01)
            self.assertGreaterEqual(record["bounds_max"][2], heights[record["id"]] * 0.995)

    def test_glbs_have_two_draw_meshes_and_material_contract(self) -> None:
        for record in self.manifest["records"]:
            path = REPO / record["glb"]
            self.assertEqual(record["glb_sha256"], sha256(path))
            document = glb_json(path)
            self.assertEqual(2, len(document.get("meshes", [])))
            self.assertEqual(2, len(document.get("materials", [])))
            self.assertEqual(2, len(document.get("images", [])))
            materials = {item["name"]: item for item in document["materials"]}
            foliage = materials["foliage_conifer_alpha_mask"]
            wood = materials["wood_conifer_seamless"]
            self.assertEqual("MASK", foliage["alphaMode"])
            self.assertTrue(foliage["doubleSided"])
            self.assertAlmostEqual(0.42, foliage["alphaCutoff"])
            self.assertEqual("OPAQUE", wood["alphaMode"])
            self.assertFalse(wood["doubleSided"])

    def test_audit_files_match_manifest(self) -> None:
        for record in self.manifest["records"]:
            audit = REPO / record["audit"]
            self.assertTrue(audit.is_file())
            self.assertEqual(record["audit_sha256"], sha256(audit))


if __name__ == "__main__":
    unittest.main()
