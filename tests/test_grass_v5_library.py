from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "procedural/generated/vegetation_v5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glb_json(path: Path) -> dict:
    raw = path.read_bytes()
    length, kind = struct.unpack_from("<II", raw, 12)
    if raw[:4] != b"glTF" or kind != 0x4E4F534A:
        raise AssertionError(path)
    return json.loads(raw[20 : 20 + length].decode("utf-8").rstrip(" \x00"))


class GrassV5LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "grass_manifest.json").read_text(encoding="utf-8"))
        cls.records = {(item["id"], item["variant"]): item for item in cls.manifest["records"]}

    def test_complete_five_by_five_catalog(self) -> None:
        self.assertEqual(5, self.manifest["base_assets"])
        self.assertEqual(25, self.manifest["glb_assets"])
        ids = {f"grass_3d_{index:02d}" for index in range(1, 6)}
        variants = {"green", "copper", "golden_beige", "red", "yellow"}
        self.assertEqual({(asset_id, variant) for asset_id in ids for variant in variants}, set(self.records))
        catalog = json.loads((ROOT / "catalog_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(135, catalog["total_glb_assets"])
        self.assertEqual(25, catalog["families"]["grass"]["glb_assets"])

    def test_glb_material_contract_and_budgets(self) -> None:
        for record in self.manifest["records"]:
            path = REPO / record["glb"]
            self.assertEqual(record["glb_sha256"], sha256(path))
            self.assertLessEqual(record["triangles"], record["triangle_budget"])
            document = glb_json(path)
            self.assertEqual(1, len(document["meshes"]))
            self.assertEqual(1, len(document["materials"]))
            material = document["materials"][0]
            self.assertEqual("MASK", material["alphaMode"])
            self.assertTrue(material["doubleSided"])

    def test_audits_and_atlases_are_traceable(self) -> None:
        for record in self.manifest["records"]:
            self.assertEqual(record["audit_sha256"], sha256(REPO / record["audit"]))
            atlas = REPO / f"procedural/generated/vegetation_v5/textures/grass/grass_{record['variant']}_512.png"
            self.assertEqual(record["atlas_sha256"], sha256(atlas))
        self.assertTrue((ROOT / "review/grass_v5_color_comparison.png").is_file())

    def test_reproducibility_report_passes(self) -> None:
        report = json.loads((ROOT / "grass_reproducibility_report.json").read_text(encoding="utf-8"))
        self.assertEqual("pass", report["result"])
        self.assertEqual(25, report["glb_byte_exact"])


if __name__ == "__main__":
    unittest.main()
