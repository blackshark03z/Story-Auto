from pathlib import Path
import json
import tempfile
import unittest

from story_auto.core.benchmark import build_benchmark_workspace, write_review_package


class ProviderBenchmarkTests(unittest.TestCase):
    def test_blind_mapping_manifest_and_review_pack_are_deterministic_and_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, mapping = build_benchmark_workspace(root, capability_evidence=[], credential_probe={"status":"BLOCKED"})
            write_review_package(root, manifest)
            self.assertEqual(len(manifest["requests"]), 24)
            self.assertEqual({item["output_settings"]["output_count"] for item in manifest["requests"]}, {1})
            self.assertNotIn("actual_model", (root / "review.html").read_text(encoding="utf-8"))
            self.assertIn("google_flow_web", json.loads((root / "provider_mapping.json").read_text())["mapping"]["IMAGE"].values())
            self.assertTrue((root / "contact_sheet_image-a.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
