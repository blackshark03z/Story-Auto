import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from story_auto.core.artifacts import sha256_file
from story_auto.providers.flow.validation import validate_image
from story_auto.providers.gemini_media import MediaResult
from tools.goal08_benchmark import (
    _request_identity,
    _set_review_readiness,
    accept_reconciled_flow_image,
    execute_api,
)


class _FakeGeminiClient:
    def generate_image(self, *, model, prompt, references, destination, aspect_ratio, image_size):
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (128, 72), "#405060").save(destination)
        metadata = validate_image(destination)
        return MediaResult(
            destination, "google_gemini_api", model, "interactions", "request-1", None,
            "TEXT_TO_IMAGE", 1, metadata,
        )


class Goal08BenchmarkToolTests(unittest.TestCase):
    def test_request_identity_is_stable_and_sensitive_to_references(self):
        item = {
            "request_id": "image-a-a-1", "actual_model": "gemini-3-pro-image",
            "media_type": "IMAGE", "prompt_sha256": "prompt",
            "output_settings": {"aspect_ratio": "16:9", "output_count": 1},
        }
        self.assertEqual(_request_identity(item, []), _request_identity(item, []))
        self.assertNotEqual(_request_identity(item, []), _request_identity(item, ["reference"]))

    def test_execute_api_merges_valid_result_into_blind_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = {
                "request_id": "image-a-a-1", "case": "IMAGE-A", "attempt": 1,
                "provider": "google_gemini_api", "actual_model": "gemini-3-pro-image",
                "media_type": "IMAGE", "actual_prompt": "natural test image",
                "prompt_sha256": "prompt", "output_settings": {"aspect_ratio": "16:9", "output_count": 1},
                "local_asset": None, "asset_sha256": None, "status": "BLOCKED",
            }
            manifest = {"requests": [item], "benchmark_status": "BLOCKED_PROVIDER_ACCOUNT"}
            with patch("tools.goal08_benchmark.GeminiMediaClient", _FakeGeminiClient):
                execute_api(root, manifest)
            self.assertEqual(item["status"], "SUCCEEDED")
            self.assertEqual(manifest["benchmark_status"], "PROVIDER_QUALITY_REVIEW_REQUIRED")
            self.assertEqual(sha256_file(root / item["local_asset"]), item["asset_sha256"])

    def test_readiness_does_not_select_a_default(self):
        manifest = {"requests": [{"status": "SUCCEEDED"}], "selection_status": "NO_PRODUCTION_DEFAULT_CHANGE"}
        _set_review_readiness(manifest)
        self.assertEqual(manifest["benchmark_status"], "PROVIDER_QUALITY_REVIEW_REQUIRED")
        self.assertEqual(manifest["selection_status"], "NO_PRODUCTION_DEFAULT_CHANGE")

    def test_accept_reconciled_flow_image_requires_ambiguous_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "assets" / "reconciled.png"
            asset.parent.mkdir(parents=True)
            Image.new("RGB", (128, 72), "#405060").save(asset)
            item = {
                "request_id": "image-b-b-1", "actual_model": "google_flow_web", "media_type": "IMAGE",
                "status": "AMBIGUOUS", "attempt_history": [{"status": "AMBIGUOUS"}],
            }
            manifest = {"requests": [item]}
            accept_reconciled_flow_image(root, manifest, item["request_id"], asset, visible_watermark="YES")
            self.assertEqual(item["status"], "SUCCEEDED")
            self.assertEqual(item["visible_watermark"], "YES")
            self.assertEqual(item["attempt_history"][-1]["status"], "SUCCEEDED_RECONCILED")


if __name__ == "__main__":
    unittest.main()
