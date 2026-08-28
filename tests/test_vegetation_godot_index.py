from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "procedural/generated/vegetation_catalog_godot.json"


class VegetationGodotIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))

    def test_complete_catalog_inventory(self) -> None:
        self.assertEqual(141, self.index["summary"]["asset_files"])
        self.assertEqual({"bush": 60, "conifer": 6, "grass": 25, "tree": 50}, self.index["summary"]["categories"])
        self.assertEqual(19, self.index["summary"]["unique_asset_ids"])

    def test_paths_hashes_and_godot_contract(self) -> None:
        for asset in self.index["assets"]:
            path = REPO / asset["files"]["glb"]
            self.assertEqual(asset["files"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual("res://" + asset["files"]["glb"], asset["files"]["godot_resource"])
            self.assertEqual("+Y", asset["placement"]["ground_axis"])
            self.assertGreater(asset["geometry"]["aabb_godot"]["size"][1], 0)
            self.assertGreaterEqual(asset["placement"]["ground_correction_y_m"], 0)

    def test_lod_levels_are_explicit(self) -> None:
        for asset in self.index["assets"]:
            expected = ["lod0"] if asset["category"] == "grass" else ["lod0", "lod1"]
            self.assertEqual(expected, asset["lod"]["available"])
            self.assertIn(asset["lod"]["name"], expected)
            self.assertGreater(asset["lod"]["visibility"]["end_m"], asset["lod"]["visibility"]["begin_m"])


if __name__ == "__main__":
    unittest.main()
