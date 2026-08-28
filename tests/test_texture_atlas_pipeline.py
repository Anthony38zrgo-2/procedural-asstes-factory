from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "procedural/generated/texture_pipeline"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glb_document(path: Path) -> dict:
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        raise AssertionError(f"not GLB: {path}")
    length = struct.unpack_from("<I", raw, 12)[0]
    return json.loads(raw[20:20 + length].decode("utf-8").rstrip(" \x00"))


class TextureAtlasPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = json.loads((OUTPUT / "library_manifest.json").read_text(encoding="utf-8"))

    def test_expected_inventory_and_pilots_exist(self) -> None:
        self.assertEqual(self.library["source_count"], 140)
        self.assertGreaterEqual(self.library["approved_source_count"], 10)
        self.assertGreaterEqual(self.library["sprite_count"], 12)
        self.assertEqual({item["family"] for item in self.library["atlases"]}, {"broadleaf", "bush", "conifer"})
        self.assertGreaterEqual(self.library["atlas_count"], 4)

    def test_sources_are_immutable_and_traceable(self) -> None:
        catalog = json.loads((OUTPUT / "catalog/source_catalog.json").read_text(encoding="utf-8"))
        for source in catalog["sources"]:
            path = REPO / source["path"]
            self.assertTrue(path.exists())
            self.assertEqual(sha256(path), source["sha256"])
            self.assertNotIn("procedural/generated", source["path"])

    def test_atlas_hashes_and_uv_regions(self) -> None:
        for atlas in self.library["atlases"]:
            self.assertEqual(sha256(REPO / atlas["atlas"]), atlas["atlas_sha256"])
            self.assertEqual(sha256(REPO / atlas["atlas_256"]), atlas["atlas_256_sha256"])
            for region in atlas["regions"]:
                u0, v0, u1, v1 = region["uv_bottom_left"]
                self.assertTrue(0.0 <= u0 < u1 <= 1.0)
                self.assertTrue(0.0 <= v0 < v1 <= 1.0)

    def test_mips_preserve_alpha_coverage(self) -> None:
        for atlas in self.library["atlases"]:
            coverages = [float(mip["coverage"]) for mip in atlas["mips"]]
            self.assertLessEqual(max(coverages) - min(coverages), 0.008)
            cutoff = round(float(atlas["alpha_cutoff"]) * 255)
            for mip in atlas["mips"]:
                image = np.asarray(Image.open(REPO / mip["path"]).convert("RGBA"), dtype=np.uint8)
                actual = float(np.mean(image[:, :, 3] >= cutoff))
                self.assertAlmostEqual(actual, float(mip["coverage"]), places=5)

    def test_material_tests_use_alpha_mask(self) -> None:
        report = json.loads((OUTPUT / "blender_audit_report.json").read_text(encoding="utf-8"))
        audited_ids = {record["id"] for record in report["records"]}
        self.assertTrue(audited_ids.issubset({atlas["id"] for atlas in self.library["atlases"]}))
        self.assertGreaterEqual(len(audited_ids), 4)
        for record in report["records"]:
            document = glb_document(REPO / record["material_test_glb"])
            textured = [material for material in document.get("materials", []) if "baseColorTexture" in material.get("pbrMetallicRoughness", {})]
            self.assertEqual(len(textured), 2)
            foliage = [material for material in textured if "foliage" in material.get("name", "").lower()]
            wood = [material for material in textured if "wood" in material.get("name", "").lower()]
            self.assertEqual(len(foliage), 1)
            self.assertEqual(len(wood), 1)
            self.assertEqual(foliage[0].get("alphaMode"), "MASK")
            self.assertTrue(foliage[0].get("doubleSided"))
            self.assertNotIn("alphaMode", wood[0])

    def test_wood_textures_are_byte_seamless(self) -> None:
        materials = self.library.get("wood_materials", [])
        self.assertEqual(len(materials), 3)
        for bark in materials:
            self.assertEqual(bark["after"], {"x_edge_mae": 0.0, "y_edge_mae": 0.0})
            image = np.asarray(Image.open(REPO / bark["path"]).convert("RGB"), dtype=np.uint8)
            self.assertTrue(np.array_equal(image[:, 0], image[:, -1]))
            self.assertTrue(np.array_equal(image[0], image[-1]))
            self.assertEqual(sha256(REPO / bark["path"]), bark["sha256"])


if __name__ == "__main__":
    unittest.main()
