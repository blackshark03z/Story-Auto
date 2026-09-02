from __future__ import annotations

import hashlib
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from story_auto.application import OperatorService
from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project


def _fixture(app: OperatorService, project_id: str, policy: str, count: int = 2):
    app.create_project(project_id=project_id, render_mode="full_image", settings={"qc_policy": policy},
                       content="# Policy fixture\n\n## Narration\n\nProvider-free visual evidence.")
    paths, _ = app._project(project_id)
    asset = paths.artifact_path("assets/selected.png")
    asset.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1280, 720), "navy").save(asset, "PNG")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    requests, entries = [], []
    for number in range(count):
        request_id = f"req_qc_{number:03d}"
        fingerprint = hashlib.sha256(request_id.encode()).hexdigest()
        request = {"request_id": request_id, "fingerprint": fingerprint, "purpose": "SHOT",
                   "shot_id": f"sh_{number:04d}", "media_type": "IMAGE", "provider": "google_flow", "prompt": "fixture"}
        entry = {"request_id": request_id, "request_identity_sha256": fingerprint,
                 "related_identity": request["shot_id"], "media_type": "IMAGE", "provider": "google_flow",
                 "status": "QC_PENDING", "failure_class": None,
                 "attempts": [{"attempt": 1, "status": "SUCCEEDED", "attribution_state": "CONFIRMED",
                               "asset_path": "assets/selected.png", "asset_sha256": digest}],
                 "selected_asset": {"path": "assets/selected.png", "sha256": digest, "attempt": 1,
                                    "production_qc": "PENDING"}}
        requests.append(request); entries.append(entry)
    atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": requests})
    atomic_write_json(paths.artifact_path("output/generation_manifest.json"),
                      {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": project_id, "requests": entries})
    return paths


class PhaseBQualityPolicyTests(unittest.TestCase):
    def test_new_projects_persist_auto_default_and_legacy_projects_keep_manual_effective_policy(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_default", content="# Default\n\n## Narration\n\nText.")
            paths, config = app._project("prj_default")
            self.assertEqual(config.settings["qc_policy"], "AUTO_ACCEPT")
            legacy = create_project(RuntimeLayout.from_root(root), ProjectConfig("prj_legacy", settings={}), "# Legacy\n\n## Narration\n\nText.")
            project = read_json(legacy.project_file); project["settings"].pop("qc_policy")
            atomic_write_json(legacy.project_file, project)
            self.assertEqual(app.query_qc_status("prj_legacy")["policy"], "MANUAL_REVIEW")
            self.assertNotIn("qc_policy", read_json(legacy.project_file)["settings"])

    def test_auto_accept_records_system_policy_decisions_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto", "AUTO_ACCEPT", 42)
            first = app.apply_qc_policy("prj_auto")
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual((first["accepted_assets"], first["provider_dispatch_delta"], first["ineligible_assets"]), (42, 0, []))
            self.assertTrue(all(item["status"] == "SUCCEEDED" and item["selected_asset"]["production_qc"] == "AUTO_ACCEPTED" for item in saved["requests"]))
            decision = saved["requests"][0]["quality_reviews"][-1]
            self.assertEqual((decision["decision"], decision["disposition"], decision["actor"], decision["policy"]),
                             ("ACCEPT", "AUTO_ACCEPTED", "SYSTEM", "AUTO_ACCEPT"))
            self.assertEqual(app.query_qc_status("prj_auto")["status"], "COMPLETE")
            second = app.apply_qc_policy("prj_auto")
            self.assertEqual((second["accepted_assets"], second["already_auto_accepted_assets"]), (0, 42))
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), saved)

    def test_auto_accept_never_accepts_failed_ambiguous_missing_or_wrong_type_assets(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_negative", "AUTO_ACCEPT", 4)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["selected_asset"]["path"] = "assets/missing.png"
            wrong_type = paths.artifact_path("assets/wrong-type.txt"); wrong_type.write_text("not an image", encoding="utf-8")
            manifest["requests"][1]["selected_asset"].update({"path": "assets/wrong-type.txt", "sha256": hashlib.sha256(wrong_type.read_bytes()).hexdigest()})
            manifest["requests"][2].update({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_TIMEOUT"})
            manifest["requests"][3].update({"status": "AMBIGUOUS", "failure_class": "OUTPUT_ATTRIBUTION_AMBIGUOUS"})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            result = app.apply_qc_policy("prj_auto_negative")
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual(result["accepted_assets"], 0)
            self.assertEqual(saved["requests"][0]["selected_asset"]["production_qc"], "PENDING")
            self.assertEqual(saved["requests"][1]["selected_asset"]["production_qc"], "PENDING")
            self.assertEqual((saved["requests"][2]["status"], saved["requests"][3]["status"]), ("FAILED_RETRYABLE", "AMBIGUOUS"))

    def test_manual_review_pauses_then_batch_accepts_exact_assets_without_duplicate_decisions(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_manual", "MANUAL_REVIEW", 2)
            pending = app.query_qc_status("prj_manual")
            self.assertEqual((pending["status"], pending["requires_owner_decision"], pending["pending_review"]), ("BLOCKED", True, 2))
            first = app.accept_selected_assets("prj_manual", {"req_qc_000", "req_qc_001"}, "Owner approved the selected batch.")
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual((first["accepted_assets"], first["provider_dispatch_delta"]), (2, 0))
            self.assertEqual(saved["quality_batches"][-1]["asset_set"], [
                {"request_id": "req_qc_000", "path": "assets/selected.png", "sha256": saved["requests"][0]["selected_asset"]["sha256"]},
                {"request_id": "req_qc_001", "path": "assets/selected.png", "sha256": saved["requests"][1]["selected_asset"]["sha256"]},
            ])
            self.assertEqual(app.query_qc_status("prj_manual")["status"], "COMPLETE")
            replay = app.accept_selected_assets("prj_manual", {"req_qc_000", "req_qc_001"}, "Owner approved the selected batch.")
            self.assertEqual(replay["accepted_assets"], 0)
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), saved)

    def test_coordinator_runs_automatic_quality_but_manual_policy_returns_owner_decision(self):
        auto_states = iter([
            {"pipeline_status": "READY", "active_stage": "QUALITY", "stages": {}},
            {"pipeline_status": "READY", "active_stage": "RENDER", "stages": {}},
            {"pipeline_status": "COMPLETE", "active_stage": "RENDER", "stages": {}},
        ])
        calls = []
        coordinator = ProductionCoordinator(lambda _: next(auto_states), {"quality": lambda _: calls.append("quality") or {"accepted_assets": 2, "provider_dispatch_delta": 0}, "render": lambda _: calls.append("render")})
        self.assertEqual(coordinator.run_until("prj_auto")["outcome"], "FINAL_VIDEO_COMPLETE")
        self.assertEqual(calls, ["quality", "render"])
        manual = {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "QUALITY", "stages": {}}
        coordinator = ProductionCoordinator(lambda _: manual, {"quality": lambda _: self.fail("manual policy must not run automatically")})
        self.assertEqual(coordinator.run_until("prj_manual")["outcome"], "OWNER_DECISION_REQUIRED")

    def test_coordinator_auto_approves_validated_plans_only_for_automatic_policy(self):
        automatic = iter([
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "evidence": [{"path": "output/generation_requests.json", "present": False}]},
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "evidence": [{"path": "output/generation_requests.json", "present": False}, {"path": "output/review_state.json", "present": True}]},
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "evidence": [{"path": "output/generation_requests.json", "present": True}]},
            {"pipeline_status": "COMPLETE", "active_stage": "RENDER", "stages": {}},
        ])
        calls = []
        coordinator = ProductionCoordinator(
            lambda _: next(automatic),
            {"approve_plan": lambda _: calls.append("approve_plan"),
             "plan": lambda _: calls.append("plan"),
             "approve_shots": lambda _: calls.append("approve_shots")},
        )
        result = coordinator.run_until("prj_auto_plan")
        self.assertEqual((result["outcome"], result["invoked_stages"], calls),
                         ("FINAL_VIDEO_COMPLETE", ["approve_plan", "plan", "approve_shots"], ["approve_plan", "plan", "approve_shots"]))

    def test_coordinator_compiles_directly_when_story_plan_is_already_approved(self):
        automatic = iter([
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "planning": {"story_plan_approved": True, "visual_plan_approved": False},
             "evidence": [{"path": "output/generation_requests.json", "present": False}]},
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "planning": {"story_plan_approved": False, "visual_plan_approved": False},
             "evidence": [{"path": "output/generation_requests.json", "present": True}]},
            {"pipeline_status": "COMPLETE", "active_stage": "RENDER", "stages": {}},
        ])
        calls = []
        coordinator = ProductionCoordinator(
            lambda _: next(automatic),
            {"approve_plan": lambda _: self.fail("approved story plan must not be approved again"),
             "plan": lambda _: calls.append("plan"),
             "approve_shots": lambda _: calls.append("approve_shots")},
        )
        result = coordinator.run_until("prj_auto_approved_story")
        self.assertEqual((result["outcome"], result["invoked_stages"], calls),
                         ("FINAL_VIDEO_COMPLETE", ["plan", "approve_shots"], ["plan", "approve_shots"]))

    def test_auto_accept_compiled_requests_continue_without_an_owner_plan_stop(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            _fixture(app, "prj_unapproved_compiled", "AUTO_ACCEPT", 1)
            state = app.production_query("prj_unapproved_compiled")
            self.assertEqual((state["pipeline_status"], state["stages"]["PLAN"]["status"]),
                             ("READY", "BLOCKED"))

    def test_manual_review_compiled_requests_remain_an_owner_plan_stop(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            _fixture(app, "prj_manual_unapproved_compiled", "MANUAL_REVIEW", 1)
            state = app.production_query("prj_manual_unapproved_compiled")
            self.assertEqual((state["pipeline_status"], state["active_stage"], state["stages"]["PLAN"]["status"]),
                             ("OWNER_DECISION_REQUIRED", "PLAN", "BLOCKED"))

    def test_operator_coordinator_auto_accepts_then_continues_to_render_without_provider_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_coordinator", "AUTO_ACCEPT", 2)
            for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json", "render_plan.json"):
                atomic_write_json(paths.artifact_path(f"output/{name}"), {"fixture": name})
            atomic_write_json(paths.artifact_path("output/review_state.json"), {
                "plan_approval": {"status": "APPROVED", "bound_hashes": {
                    name: sha256_file(paths.artifact_path(f"output/{filename}"))
                    for name, filename in (("timeline", "story_timeline.json"), ("continuity", "continuity_bible.json"),
                                           ("shot_plan", "shot_plan.json"), ("media_plan", "media_plan.json"))
                }}
            })
            renders = []
            def render(_project_id):
                renders.append(_project_id)
                paths.artifact_path("output/final.mp4").write_bytes(b"provider-free-final")
                return {"final": "fixture"}
            with patch.object(app, "render", side_effect=render):
                result = app.run_to_final("prj_auto_coordinator")
            self.assertEqual((result["outcome"], result["invoked_stages"], renders),
                             ("FINAL_VIDEO_COMPLETE", ["quality", "render"], ["prj_auto_coordinator"]))
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertTrue(all(item["selected_asset"]["production_qc"] == "AUTO_ACCEPTED" for item in manifest["requests"]))

    def test_reserved_ai_review_is_serializable_but_not_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_ai", settings={"qc_policy": "AI_REVIEW"}, content="# AI\n\n## Narration\n\nText.")
            self.assertEqual(app.query_qc_status("prj_ai")["policy"], "AI_REVIEW")
            with self.assertRaisesRegex(Exception, "AI_REVIEW_UNSUPPORTED"):
                app.apply_qc_policy("prj_ai")


if __name__ == "__main__":
    unittest.main()
