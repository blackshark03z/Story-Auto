"""Offline Goal31 regression coverage for caption-safe Flow prompt semantics."""
from __future__ import annotations

import copy
import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.planning.service import AMBIENT_GENERATION_PROMPT_VERSION, GENERATION_PROMPT_VERSION
from story_auto.core.visual import (
    DEFAULT_VISUAL_POLICY,
    EDITORIAL_OVERLAY_SAFETY_CONSTRAINT,
    caption_safe_effective_prompt,
    compile_ambient_image_prompt,
    compile_image_prompt,
    compile_video_prompt,
)
from story_auto.providers.flow.service import (
    _provider_generation_retry_authorized,
    replay_unresolved_request,
    replace_qc_rejected_asset,
)


CONTAMINATING_PHRASE = "negative space for readable subtitles"


def ambient_brief() -> dict:
    return {
        "visual_anchor": "A Roman general holds a decisive but restrained victory pose",
        "dominant_subject": "Scipio Africanus",
        "dominant_environment": "a grounded civic courtyard after a battle",
        "dominant_state": "a decisive accomplishment changes the balance of power",
        "important_object_or_motif": "one restrained symbol of achievement",
        "continuity_requirements": ["same young commander identity and Roman commander armor"],
        "composition_intent": "clear subject hierarchy with restrained negative space for readable subtitles",
        "optional_supporting_context": "",
        "visual_anchor_kind": "DIRECT",
    }


class Goal31CaptionSafePromptTests(unittest.TestCase):
    def test_current_compilers_preserve_breathing_room_without_editorial_overlay_instruction(self):
        self.assertEqual((GENERATION_PROMPT_VERSION, AMBIENT_GENERATION_PROMPT_VERSION),
                         ("story-auto-generation-prompt/2.8.0", "story-auto-ambient-image-prompt/2.1.0"))
        brief = ambient_brief()
        ambient = compile_ambient_image_prompt(
            brief, dict(DEFAULT_VISUAL_POLICY),
            style_directive="restrained natural realism with meaningful negative space",
        )
        self.assertIn(CONTAMINATING_PHRASE, brief["composition_intent"])
        self.assertNotIn(CONTAMINATING_PHRASE, ambient)
        self.assertIn("clean, uncluttered visual breathing room", ambient)
        for prompt in (
            ambient,
            compile_image_prompt(
                "A witness waits in a quiet courthouse with room for readable captions",
                dict(DEFAULT_VISUAL_POLICY),
            ),
            compile_video_prompt(
                subject_motion="the witness takes one grounded breath",
                environmental_motion="rain moves against the windows",
                camera_motion="STATIC",
                timing="four continuous seconds",
            ),
        ):
            self.assertIn(EDITORIAL_OVERLAY_SAFETY_CONSTRAINT, prompt)
            self.assertNotIn(CONTAMINATING_PHRASE, prompt)
            self.assertNotIn("room for readable captions", prompt.lower())

    def _qc_fixture(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal31_caption_safe", render_mode="ambient_story", settings={"ambient_style": "quiet_verdict"})
        paths = create_project(runtime, config)
        old = {
            "request_id": "req_08ec2e4e057f013e4aec", "fingerprint": "historical-caption-contaminated",
            "purpose": "SHOT", "shot_id": "sh_0003", "media_type": "IMAGE", "provider": "google_flow",
            "prompt": "Composition: clear subject hierarchy with restrained negative space for readable subtitles.",
            "depends_on": [], "reference_asset_ids": [], "execution_tier": "STANDARD_PRODUCTION",
            "ambient_style": "quiet_verdict", "visual_brief": ambient_brief(), "visual_policy": dict(DEFAULT_VISUAL_POLICY),
        }
        later = {
            "request_id": "req_later", "fingerprint": "later", "purpose": "SHOT", "shot_id": "sh_0004",
            "media_type": "IMAGE", "provider": "google_flow", "prompt": "same subject later",
            "depends_on": [old["request_id"]], "reference_asset_ids": [old["request_id"]],
        }
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [old, later]})
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": [{
            "request_id": old["request_id"], "request_identity_sha256": old["fingerprint"],
            "related_identity": old["shot_id"], "media_type": "IMAGE", "provider": "google_flow",
            "prompt_sha256": "historical", "reference_asset_hashes": [],
            "attempts": [{"attempt": 1, "dispatch_confirmed": True, "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED", "attribution_state": "CONFIRMED"}],
            "status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED",
            "selected_asset": {"attempt": 1, "sha256": "a" * 64},
            "quality_reviews": [{"status": "REJECTED", "failure_class": "NATURALNESS_QC_REJECTED"}],
        }]})
        return runtime, config, paths, old

    def test_contaminated_qc_fixture_preserves_history_and_creates_one_caption_safe_epoch(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, old = self._qc_fixture(root)
            old_snapshot = copy.deepcopy(old)
            first = replace_qc_rejected_asset(runtime.root, config.project_id, old["request_id"], reason="Goal31 caption-safe replacement")
            second = replace_qc_rejected_asset(runtime.root, config.project_id, old["request_id"], reason="idempotent retry")
            self.assertEqual((first["provider_submissions"], first["idempotent"], second["idempotent"]), (0, False, True))
            self.assertEqual(first["replacement_request_id"], second["replacement_request_id"])
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
            replacement = requests[0]
            historical = manifest[0]
            self.assertEqual(old, old_snapshot)
            self.assertEqual(historical["historical_prompt"], old_snapshot["prompt"])
            self.assertEqual(historical["qc_replacement_events"][0]["historical_prompt"], old_snapshot["prompt"])
            self.assertFalse(_provider_generation_retry_authorized(historical))
            self.assertEqual(historical["selected_asset"], {"attempt": 1, "sha256": "a" * 64})
            self.assertEqual((replacement["replacement_of"], replacement["replacement_epoch"], replacement["shot_id"]), (old["request_id"], 1, old["shot_id"]))
            self.assertEqual(replacement["visual_brief"]["visual_anchor"], old["visual_brief"]["visual_anchor"])
            self.assertNotIn(CONTAMINATING_PHRASE, replacement["prompt"])
            self.assertNotIn(CONTAMINATING_PHRASE, replacement["visual_brief"]["composition_intent"])
            self.assertIn(EDITORIAL_OVERLAY_SAFETY_CONSTRAINT, replacement["prompt"])
            self.assertEqual(replacement["prompt_construction"]["source"], "CURRENT_AMBIENT_PROMPT_CONSTRUCTION")
            self.assertEqual(requests[1]["depends_on"], [first["replacement_request_id"]])
            transaction_dir = paths.artifact_path("output/qc_rejected_asset_replacement_transactions")
            self.assertEqual(len(list(transaction_dir.glob("*.committed.json"))), 1)

    def test_replay_of_caption_safe_request_keeps_the_safe_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            config = ProjectConfig("prj_goal31_replay")
            paths = create_project(runtime, config)
            prompt = caption_safe_effective_prompt("A restrained civic scene with clean, uncluttered visual breathing room")
            old = {"request_id": "req_safe", "fingerprint": "safe-fingerprint", "purpose": "SHOT", "shot_id": "sh_0001",
                   "media_type": "IMAGE", "provider": "google_flow", "prompt": prompt, "output_count": 1,
                   "depends_on": [], "reference_asset_ids": []}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [old]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": [{
                "request_id": old["request_id"], "request_identity_sha256": old["fingerprint"], "related_identity": old["shot_id"],
                "media_type": "IMAGE", "provider": "google_flow", "prompt_sha256": "safe", "reference_asset_hashes": [],
                "attempts": [{"attempt": 1, "dispatch_confirmed": True, "attribution_state": "UNCERTAIN"}],
                "status": "AMBIGUOUS", "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN",
            }]})
            result = replay_unresolved_request(
                runtime.root, config.project_id, old["request_id"], reason="offline safe replay fixture",
                acknowledge_previous_dispatch_or_cost_may_have_occurred=True,
                acknowledge_previous_output_ownership_unresolved=True,
                acknowledge_replacement_may_consume_provider_credit=True,
            )
            replacement = read_json(paths.artifact_path("output/generation_requests.json"))["requests"][0]
            self.assertEqual(result["provider_submissions"], 0)
            self.assertEqual(replacement["prompt"], prompt)
            self.assertIn(EDITORIAL_OVERLAY_SAFETY_CONSTRAINT, replacement["prompt"])
            self.assertNotIn(CONTAMINATING_PHRASE, replacement["prompt"])


if __name__ == "__main__":
    unittest.main()
