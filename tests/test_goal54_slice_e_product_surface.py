from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from story_auto.application.full_video_product import full_video_provider_product_view
from story_auto.core.artifacts import atomic_write_json
from story_auto.core.full_video_provider import full_video_provider_snapshot
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.project.production_state import ProductionStateReconciler


class Goal54SliceEProductSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.config = ProjectConfig(
            "prj_slice_e", render_mode="full_video_ai",
            settings={"full_video_provider": "elyum_seedance",
                      "elyum": {"model": "seedance-2-fast-i2v", "resolution": "480p",
                                "provider_duration_seconds": 4, "max_credits": 44}},
        )
        self.paths = create_project(self.runtime, self.config, "# Slice E\n\n## Narration\n\nFixture.")
        self.request = {"request_id": "req_e1", "purpose": "SHOT", "shot_id": "sh_0001",
                        "media_type": "VIDEO", "provider": "elyum_seedance", "fingerprint": "a" * 64,
                        "target_start": 0.0, "part_index": 1}
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), {
            "schema_version": "story-auto-generation-requests/1.0.0",
            "project_id": self.config.project_id,
            "full_video_provider_snapshot": full_video_provider_snapshot(self.config.settings),
            "requests": [self.request],
        })

    def tearDown(self):
        self.temp.cleanup()

    def _manifest(self, *, entry_status="PREVIEW_READY", attempt_status="PREVIEW_READY", known_job=True):
        attempt = {
            "attempt": 1, "status": attempt_status, "unlock_credits": 20,
            "preview_asset": {"path": "assets/video/req_e1/attempt_001_locked_preview.mp4",
                              "sha256": "b" * 64, "production_qc": "PENDING"},
            "balance_before": 110, "estimate_credits": 44,
        }
        if known_job:
            attempt["provider_job_id"] = "job_fixture"
        entry = {
            "request_id": "req_e1", "request_identity_sha256": "a" * 64,
            "related_identity": "sh_0001", "media_type": "VIDEO", "provider": "elyum_seedance",
            "status": entry_status, "attempts": [attempt],
            "preflight_events": [{"balance": 110, "estimate_credits": 44, "max_credits": 44}],
        }
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0",
            "project_id": self.config.project_id, "requests": [entry],
        })
        return entry

    def test_projection_is_safe_truthful_and_routing_remains_staged(self):
        self._manifest()
        view = full_video_provider_product_view(self.paths, self.config)
        self.assertEqual(view["provider_id"], "elyum_seedance")
        self.assertEqual(view["routing_state"], "INTEGRATION_STAGED")
        self.assertFalse(view["routing_enabled"])
        self.assertEqual(view["status"], "PREVIEW_READY")
        self.assertEqual(view["action"], "REVIEW_PREVIEW")
        self.assertTrue(view["known_job"])
        self.assertEqual(view["budget"], {"balance": 110, "estimate_credits": 44, "max_credits": 44, "unlock_credits": 20})
        self.assertEqual(view["preview_sha256"], "b" * 64)
        self.assertNotIn("provider_job_id", view)
        self.assertNotIn("url", str(view).lower())

    def test_projection_distinguishes_keep_and_clean_output_reacquisition(self):
        self._manifest(entry_status="KEEP_REQUIRED", attempt_status="KEEP_REQUIRED")
        keep_view = full_video_provider_product_view(self.paths, self.config)
        self.assertEqual(keep_view["action"], "KEEP_PREVIEW")
        self.assertIn("may spend provider credits", keep_view["continuation_behavior"])
        self._manifest(entry_status="KEEP_ACQUISITION_REQUIRED", attempt_status="KEEP_ACQUISITION_REQUIRED")
        acquire_view = full_video_provider_product_view(self.paths, self.config)
        self.assertEqual(acquire_view["action"], "REACQUIRE_KEPT_OUTPUT")
        self.assertIn("must not Keep again", acquire_view["continuation_behavior"])

    def test_reconciler_projects_preview_review_and_known_job_resume(self):
        reconciler = ProductionStateReconciler()
        entry = self._manifest()
        review = reconciler._visual_recovery(
            self.paths, {"requests": [self.request]}, {"requests": [entry]}, {"req_e1": entry}, {"req_e1"}, False,
            active_project_operation=False,
        )
        self.assertEqual((review["status"], review["reason_code"], review["next_action"]),
                         ("NEEDS_ATTENTION", "ELYUM_PREVIEW_REVIEW_REQUIRED", "Review visuals"))
        entry = self._manifest(entry_status="GENERATING", attempt_status="WAIT_UNAVAILABLE", known_job=True)
        resume = reconciler._visual_recovery(
            self.paths, {"requests": [self.request]}, {"requests": [entry]}, {"req_e1": entry}, {"req_e1"}, False,
            active_project_operation=False,
        )
        self.assertEqual((resume["status"], resume["reason_code"], resume["provider_dispatches_per_continue"]),
                         ("RECOVERY_READY", "ELYUM_JOB_RESUME_READY", 0))

    def test_ui_contract_exposes_exact_review_and_separate_consequences(self):
        script = Path(__file__).parents[1] / "story_auto" / "ui" / "static" / "app.js"
        text = script.read_text(encoding="utf-8")
        for token in ("fullVideoProviderSurface", "Accept exact preview", "Reject exact preview",
                      "Keep / unlock", "Kill rejected preview", "Retry clean output download",
                      "confirm_spend:true", "confirm_kill:true"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
