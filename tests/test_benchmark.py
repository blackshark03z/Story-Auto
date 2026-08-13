from pathlib import Path
import json
import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json
from story_auto.core.benchmark import build_benchmark_workspace, write_review_package


class ProviderBenchmarkTests(unittest.TestCase):
    def test_blind_mapping_manifest_and_review_pack_are_deterministic_and_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, mapping = build_benchmark_workspace(root, capability_evidence=[], credential_probe={"status":"BLOCKED"})
            write_review_package(root, manifest)
            self.assertEqual(len(manifest["requests"]), 16)
            self.assertEqual({item["output_settings"]["output_count"] for item in manifest["requests"]}, {1})
            self.assertNotIn("actual_model", (root / "review.html").read_text(encoding="utf-8"))
            self.assertIn("Export review JSON", (root / "review.html").read_text(encoding="utf-8"))
            self.assertIn("google_flow_web", json.loads((root / "provider_mapping.json").read_text())["mapping"]["IMAGE"].values())
            self.assertIn("gemini_web_product_mode", json.loads((root / "provider_mapping.json").read_text())["mapping"]["IMAGE"].values())
            self.assertTrue((root / "production_eligibility.json").is_file())
            self.assertTrue((root / "contact_sheet_image-a.jpg").is_file())
            manifest["requests"][0].update({
                "status": "SUCCEEDED", "local_asset": "assets/a.png", "asset_sha256": "hash",
            })
            atomic_write_json(root / "benchmark_manifest.json", manifest)
            rebuilt, _ = build_benchmark_workspace(
                root, capability_evidence=[], credential_probe={"status": "READY"},
            )
            self.assertEqual(
                (rebuilt["requests"][0]["status"], rebuilt["requests"][0]["local_asset"]),
                ("SUCCEEDED", "assets/a.png"),
            )

    def test_api_era_requests_become_immutable_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atomic_write_json(root / "benchmark_manifest.json", {
                "requests": [{
                    "request_id": "old-api", "provider": "google_gemini_api",
                    "actual_model": "gemini-3-pro-image", "attempt": 1,
                    "case": "IMAGE-A", "status": "BLOCKED", "failure_class": "RATE_LIMITED",
                }],
            })
            manifest, _ = build_benchmark_workspace(
                root, capability_evidence=[], credential_probe={"status": "HISTORICAL"},
            )
            self.assertEqual(len(manifest["requests"]), 16)
            self.assertFalse(any(item["provider"] == "google_gemini_api" for item in manifest["requests"]))
            self.assertEqual(manifest["historical_provider_requests"][0]["failure_class"], "RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
