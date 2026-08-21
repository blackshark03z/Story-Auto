from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    _provider_generation_retry_authorized,
    execute_generation,
    queue_regeneration,
    replace_qc_rejected_asset,
    review_production_asset,
)
from story_auto.providers.flow.session import FlowCapabilities


class Goal27QcRejectedAssetReplacementTests(unittest.TestCase):
    OLD_REQUEST_ID = "req_2f755d20c25245314761"

    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal27")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        old = {
            "request_id": self.OLD_REQUEST_ID, "fingerprint": "old-semantic-fingerprint", "purpose": "SHOT",
            "shot_id": "sh_001", "media_type": "IMAGE", "provider": "google_flow", "prompt": "quiet courtroom at dusk",
            "depends_on": [], "reference_asset_ids": [], "execution_tier": "STANDARD_PRODUCTION",
        }
        later = {
            "request_id": "req_later", "fingerprint": "later-fingerprint", "purpose": "SHOT", "shot_id": "sh_002",
            "media_type": "IMAGE", "provider": "google_flow", "prompt": "same witness later", "depends_on": [self.OLD_REQUEST_ID],
            "reference_asset_ids": [self.OLD_REQUEST_ID], "execution_tier": "STANDARD_PRODUCTION",
        }
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [old, later]})
        selected = {"path": "assets/image/original.png", "sha256": "a" * 64, "attempt": 1, "production_qc": "REJECTED"}
        attempt = {
            "attempt": 1, "status": "SUCCEEDED", "dispatch_confirmed": True,
            "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED", "provider_job_id": "flow-job-1",
            "attribution_state": "CONFIRMED", "attributed_provider_identity": {"identity": "flow-card-1"},
        }
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
            "requests": [{"request_id": self.OLD_REQUEST_ID, "request_identity_sha256": old["fingerprint"],
                          "related_identity": old["shot_id"], "media_type": "IMAGE", "provider": "google_flow",
                          "prompt_sha256": "old-prompt", "reference_asset_hashes": [], "attempts": [attempt],
                          "status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED",
                          "selected_asset": selected, "quality_reviews": [{"status": "REJECTED", "failure_class": "NATURALNESS_QC_REJECTED"}]}],
        })
        return runtime, config, paths, old, selected, attempt

    def _executor(self, calls: list[str]) -> FlowExecutor:
        def generate(request, _refs, destination: Path):
            calls.append(request["request_id"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
            return destination
        return FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)

    def test_owned_qc_rejection_creates_one_immutable_replacement_epoch(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, old_request, selected, attempt = self._project(root)
            first = queue_regeneration(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="mandatory naturalness QC rejected")
            second = replace_qc_rejected_asset(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="same operation retry")
            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(first["replacement_request_id"], second["replacement_request_id"])
            replacement_id = first["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            old_entry, replacement_entry = manifest["requests"]
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            replacement_request = requests[0]
            self.assertEqual(old_entry["request_id"], self.OLD_REQUEST_ID)
            self.assertEqual(old_entry["attempts"], [attempt])
            self.assertEqual(old_entry["selected_asset"], selected)
            self.assertEqual(old_entry["failure_class"], "NATURALNESS_QC_REJECTED")
            self.assertEqual(old_entry["status"], "QC_REJECTED_ASSET_REPLACED")
            self.assertFalse(_provider_generation_retry_authorized(old_entry))
            self.assertEqual((replacement_entry["attempts"], replacement_entry["provider_submissions"], replacement_entry["selected_asset"], replacement_entry["attribution_claim"]), ([], 0, None, "NONE"))
            self.assertEqual((replacement_request["replacement_of"], replacement_request["replacement_reason"]), (self.OLD_REQUEST_ID, "QC_REJECTED_ASSET_REPLACEMENT"))
            self.assertEqual((replacement_request["prompt"], replacement_request["shot_id"], replacement_request["purpose"]), (old_request["prompt"], old_request["shot_id"], old_request["purpose"]))
            self.assertEqual(requests[1]["depends_on"], [replacement_id])
            self.assertEqual(requests[1]["reference_asset_ids"], [replacement_id])
            self.assertTrue(_provider_generation_retry_authorized(replacement_entry))
            calls: list[str] = []
            self.assertEqual(calls, [])  # replacement creation is local-only: no provider call occurred.
            generated = execute_generation(runtime.root, config.project_id, executor=self._executor(calls), execute=True, request_ids={replacement_id})
            self.assertEqual((generated["new_submissions"], calls), (1, [replacement_id]))
            report = {"results": {key: "PASS" for key in ("SKIN_REALISM", "LIGHTING_NATURALISM", "MATERIAL_REALISM", "COMPOSITION_NATURALISM", "AI_POLISH", "CONTINUITY", "TECHNICAL_VALIDITY")}, "visible_provider_watermark": False, "reviewer": "fixture", "alignment_classification": "PASS_DIRECT"}
            review_production_asset(runtime.root, config.project_id, replacement_id, report)
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][1]["status"], "SUCCEEDED")

    def test_replacement_epoch_cannot_start_an_unbounded_qc_replacement_loop(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, _old, _selected, _attempt = self._project(root)
            result = replace_qc_rejected_asset(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="mandatory QC")
            replacement_id = result["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            replacement = manifest["requests"][1]
            replacement.update({"status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED", "selected_asset": {"attempt": 1},
                                "attempts": [{"attempt": 1, "attribution_state": "CONFIRMED"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            with self.assertRaisesRegex(FlowError, "QC_REJECTED_ASSET_REPLACEMENT_NOT_ELIGIBLE"):
                replace_qc_rejected_asset(runtime.root, config.project_id, replacement_id, reason="must not loop")


if __name__ == "__main__":
    unittest.main()
