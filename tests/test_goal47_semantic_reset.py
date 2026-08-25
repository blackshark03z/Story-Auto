from __future__ import annotations

import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowError,
    _validate_effective_scene_geometry_provider_input,
    semantic_reset_exhausted_correction,
)


class Goal47SemanticResetTests(unittest.TestCase):
    ROOT = "req_root"
    TIP = "req_epoch3"

    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal47")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/shot_plan.json"), {"shots": [{
            "shot_id": "sh_0003", "subject": "Chief Udo",
            "action": "runs his index finger down the printed transaction list onto a repeated name.",
            "composition_intent": "High-angle detail shot emphasizing the written name on the bank statement.",
            "prop_ids": ["prop_bank_statements"],
        }]})
        requests = [{
            "request_id": self.TIP, "fingerprint": "epoch3", "purpose": "SHOT", "shot_id": "sh_0003",
            "media_type": "VIDEO", "provider": "google_flow", "prompt": "full replan epoch 3: loc_family_home porch",
            "depends_on": [], "reference_asset_ids": ["char_udo", "prop_bank_statements", "loc_family_home"],
            "execution_tier": "STANDARD_PRODUCTION", "creative_correction_epoch": 3,
            "replacement_of": "req_epoch2", "replacement_reason": "QC_REJECTED_ASSET_REPLACEMENT",
        }]
        entries = []
        parent = None
        for epoch, request_id in enumerate((self.ROOT, "req_epoch1", "req_epoch2", self.TIP)):
            prompt = "original loc_family_home" if epoch == 0 else f"full replan epoch {epoch}: exterior porch"
            attempt = {"attempt": 1, "dispatch_confirmed": True, "dispatch_confirmation_state": "CONFIRMED",
                       "attribution_state": "CONFIRMED", "attributed_provider_identity": {"identity": f"asset-{epoch}"}}
            entry = {"request_id": request_id, "request_identity_sha256": f"f{epoch}", "related_identity": "sh_0003",
                     "media_type": "VIDEO", "provider": "google_flow", "prompt_sha256": f"p{epoch}",
                     "reference_asset_hashes": [f"exterior-{epoch}"], "attempts": [attempt], "provider_submissions": 1,
                     "selected_asset": {"attempt": 1, "path": f"assets/video/{request_id}/clean.mp4", "sha256": str(epoch) * 64},
                     "status": "FAILED_RETRYABLE", "failure_class": "VISUAL_NARRATION_ALIGNMENT_MISMATCH",
                     "quality_reviews": [{"status": "REJECTED", "failure_class": "VISUAL_NARRATION_ALIGNMENT_MISMATCH"}],
                     "historical_prompt": prompt}
            if parent:
                entry["replacement_of"] = parent
            entries.append(entry); parent = request_id
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": requests})
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": entries,
        })
        return runtime, config, paths

    def test_exactly_one_fresh_reset_locks_core_and_excludes_failed_reference_family(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            result = semantic_reset_exhausted_correction(runtime.root, config.project_id, self.TIP, reason="wrong exterior family")
            self.assertEqual((result["provider_submissions"], result["status"]), (0, "SEMANTIC_RESET_PENDING"))
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
            reset = requests[0]
            reset_entry = next(item for item in manifest if item["request_id"] == result["reset_request_id"])
            self.assertNotIn("creative_correction_epoch", reset)  # never epoch 4
            self.assertEqual((reset_entry["attempts"], reset_entry["provider_submissions"], reset_entry["selected_asset"]), ([], 0, None))
            self.assertEqual(reset["reference_asset_ids"], ["prop_bank_statements"])
            self.assertNotIn("char_udo", reset["reference_asset_ids"])
            self.assertNotIn("loc_family_home", reset["reference_asset_ids"])
            self.assertIn("INTERIOR", reset["prompt"])
            self.assertIn("location_type=INTERIOR", reset["prompt"])
            self.assertIn("APPROACH_DOCUMENT -> CONTACT_DOCUMENT -> TRACE_DOCUMENT", reset["prompt"])
            geometry = reset["scene_geometry_contract"]
            self.assertEqual(geometry["location_type"], "INTERIOR")
            self.assertEqual(geometry["composition"]["desk_document"], "CENTER_LOWER/FOREGROUND/DOMINANT")
            self.assertEqual(geometry["action_progression"], ["APPROACH_DOCUMENT", "CONTACT_DOCUMENT", "TRACE_DOCUMENT"])
            self.assertEqual(geometry["reference_policy"]["omitted_conflicting_reference_asset_ids"], ["char_udo", "loc_family_home"])
            validation = _validate_effective_scene_geometry_provider_input(reset, [])
            self.assertFalse(validation["stale_prompt_or_reasoning_cache_reused"])
            self.assertEqual(len(reset["semantic_reset_material_delta"]["failed_generation_inputs"]), 4)
            self.assertNotIn("full replan epoch 3", reset["prompt"])
            with self.assertRaisesRegex(FlowError, "SEMANTIC_RESET_ALREADY_USED"):
                semantic_reset_exhausted_correction(runtime.root, config.project_id, self.TIP, reason="second reset")

    def test_geometry_validation_rejects_a_compiled_prompt_that_loses_interior_contract(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            result = semantic_reset_exhausted_correction(runtime.root, config.project_id, self.TIP, reason="wrong exterior family")
            reset = read_json(paths.artifact_path("output/generation_requests.json"))["requests"][0]
            reset["prompt"] = "exterior porch and outdoor doorway"
            with self.assertRaisesRegex(FlowError, "SCENE_GEOMETRY_PROVIDER_INPUT_INVALID"):
                _validate_effective_scene_geometry_provider_input(reset, [])

    def test_ambiguous_historical_epoch_is_ineligible_and_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][1]["attempts"][0]["attribution_state"] = "AMBIGUOUS"
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            before = read_json(paths.artifact_path("output/generation_manifest.json"))
            with self.assertRaisesRegex(FlowError, "SEMANTIC_RESET_NOT_ELIGIBLE"):
                semantic_reset_exhausted_correction(runtime.root, config.project_id, self.TIP, reason="must fail closed")
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), before)


if __name__ == "__main__":
    unittest.main()
