from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from story_auto.application import OperatorService
from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.providers.flow.connection import FlowConnectionError
from story_auto.providers.flow.service import FlowExecutor
from story_auto.providers.flow.session import FlowCapabilities


def validated(url: str = "https://labs.google/fx/tools/flow/project-alpha", *, image: bool = True, video: bool = True):
    return {"status": "CONNECTED", "project_url": url, "project_identity": url,
            "observed_capabilities": {"IMAGE": image, "VIDEO": video, "REFERENCE_IMAGE": image, "FRAME_VIDEO": video}}


def planned_project(app: OperatorService, project_id: str = "prj_phase_d"):
    app.flow_connections.save_validated_candidate(validated())
    app.create_project(project_id=project_id, render_mode="full_image", content="# Phase D\n\n## Narration\n\nFixture.")
    paths, _config = app._project(project_id)
    for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json"):
        atomic_write_json(paths.artifact_path(f"output/{name}"), {"fixture": name})
    atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
    atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [
        {"request_id": f"req_{index:02d}", "fingerprint": f"fixture-{index:02d}", "purpose": "SHOT", "shot_id": f"shot_{index:02d}", "media_type": "IMAGE", "prompt": "fixture", "depends_on": [], "provider": "google_flow"}
        for index in range(1, 43)
    ]})
    return paths


def reference_then_shot_project(app: OperatorService, project_id: str = "prj_reference_then_shot"):
    app.flow_connections.save_validated_candidate(validated())
    app.create_project(project_id=project_id, render_mode="full_image", content="# Reference dependency\n\n## Narration\n\nFixture.")
    paths, _config = app._project(project_id)
    for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json"):
        atomic_write_json(paths.artifact_path(f"output/{name}"), {"fixture": name})
    atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
    atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [
        {"request_id": "ref_01", "fingerprint": "reference-01", "purpose": "REFERENCE", "entity_id": "character_01", "media_type": "IMAGE", "prompt": "reference", "depends_on": [], "provider": "google_flow", "execution_tier": "STANDARD_PRODUCTION"},
        {"request_id": "shot_01", "fingerprint": "shot-01", "purpose": "SHOT", "shot_id": "shot_01", "media_type": "IMAGE", "prompt": "shot", "depends_on": ["ref_01"], "provider": "google_flow", "execution_tier": "STANDARD_PRODUCTION"},
    ]})
    return paths


class PhaseDFlowProductTests(unittest.TestCase):
    def test_compact_product_states_and_diagnostics_are_separate(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = planned_project(app)
            summary = app.production_query(paths.project_id)
            self.assertEqual(summary["flow"], {"status": "CONNECTED", "human_message": "Flow connected", "recoverable": False,
                                                "next_action": {"action": "continue_production", "label": "Continue production"}, "required": True})
            self.assertNotIn("connection_revision", summary["flow"])
            self.assertIn("flow_connection", app.diagnostics(paths.project_id)["snapshot"])

    def test_same_identity_revalidation_keeps_project_connected(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = planned_project(app)
            first = app.flow_connections.get_current_connection()
            app.flow_connections.save_validated_candidate(validated())
            second = app.flow_connections.get_current_connection()
            self.assertGreater(second.revision, first.revision)
            self.assertEqual(app.flow_status(paths.project_id)["status"], "CONNECTED")

    def test_changed_identity_blocks_before_dispatch_and_requires_explicit_rebind(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = planned_project(app)
            original = app.flow_connections.get_current_connection()
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id, "requests": [{
                "request_id": "req_01", "request_identity_sha256": "fixture-01", "status": "SUCCEEDED", "attempts": [{"attempt": 1, "flow_connection": app.flow_connections.provenance(original)}],
                "selected_asset": {"path": "assets/selected.png", "production_qc": "AUTO_ACCEPTED"},
            }]})
            app.flow_connections.save_validated_candidate(validated("https://labs.google/fx/tools/flow/project-beta"))
            self.assertEqual(app.flow_status(paths.project_id)["status"], "PROJECT_MISMATCH")
            calls = []
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("dispatch"))
            with self.assertRaisesRegex(FlowConnectionError, "FLOW_PROJECT_MISMATCH"):
                app.generate(paths.project_id, executor=executor, request_ids={"req_18"})
            self.assertEqual(calls, [])
            with self.assertRaisesRegex(FlowConnectionError, "FLOW_REBIND_EXPLICIT_OWNER_DECISION_REQUIRED"):
                app.rebind_flow_project(paths.project_id, explicit_owner_decision=False)
            app.rebind_flow_project(paths.project_id, explicit_owner_decision=True)
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["attempts"][0]["flow_connection"]
            self.assertEqual(saved, app.flow_connections.provenance(original))
            self.assertEqual(app.flow_status(paths.project_id)["status"], "CONNECTED")

    def test_capability_missing_and_render_only_are_provider_free(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = planned_project(app)
            app.flow_connections.save_validated_candidate(validated(image=False))
            self.assertEqual(app.flow_status(paths.project_id)["status"], "CAPABILITY_MISSING")
            with self.assertRaisesRegex(FlowConnectionError, "FLOW_CAPABILITY_UNAVAILABLE"):
                app.generate(paths.project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: self.fail("must not dispatch")), request_ids={"req_01"})
            app.create_project(project_id="prj_render_only", render_mode="full_image", settings={"execution": {"mode": "RENDER_ONLY"}}, content="# R\n\n## Narration\n\nFixture.")
            state = app.production_query("prj_render_only")
            self.assertFalse(state["flow"]["required"])

    def test_provider_access_block_projects_settings_action_instead_of_unhandled_slug(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = planned_project(app, "prj_provider_access")
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0",
                "project_id": paths.project_id,
                "requests": [{
                    "request_id": "req_01", "request_identity_sha256": "fixture-01",
                    "status": "CREDIT_BLOCKED", "failure_class": "CREDIT_BLOCKED", "attempts": [],
                }],
            })
            state = app.production_query(paths.project_id)
            self.assertEqual(state["recovery"]["next_action"], "Review provider access")
            self.assertEqual(state["next_action"], {"action": "settings", "label": "Review provider access"})

    def test_qc_pending_reference_unblocks_its_dependent_shot_once(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = reference_then_shot_project(app)
            dispatched = []
            def generate(request, _refs, target):
                dispatched.append(request["request_id"])
                target.parent.mkdir(parents=True, exist_ok=True)
                image = Image.new("RGB", (1280, 720), "green")
                if request["request_id"] == "shot_01":
                    ImageDraw.Draw(image).rectangle((100, 100, 600, 500), fill="navy")
                image.save(target, "PNG")
                return target
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
            first = app.generate(paths.project_id, executor=executor)
            second = app.generate(paths.project_id, executor=executor)
            state = app.production_query(paths.project_id)
            self.assertEqual((first["new_submissions"], dispatched, second["new_submissions"]),
                             (2, ["ref_01", "shot_01"], 0))
            self.assertEqual((state["stages"]["VISUALS"]["status"], state["stages"]["VISUALS"]["completed_items"]),
                             ("COMPLETE", 1))

    def test_ambiguous_attempt_remains_a_no_dispatch_barrier(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = reference_then_shot_project(app)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id,
                "requests": [{"request_id": "ref_01", "request_identity_sha256": "reference-01", "status": "AMBIGUOUS",
                              "attempts": [{"attempt": 1, "status": "SUBMITTED", "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]}],
            })
            dispatched = []
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: dispatched.append("dispatch"))
            result = app.generate(paths.project_id, executor=executor)
            self.assertEqual((result["blocked"], result["new_submissions"], dispatched), (True, 0, []))

    def test_auth_recovery_reuses_confirmed_assets_and_only_dispatches_next_request(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = planned_project(app)
            asset = paths.artifact_path("assets/confirmed.png"); asset.parent.mkdir(exist_ok=True)
            Image.new("RGB", (1280, 720), "navy").save(asset, "PNG")
            entries = []
            for index in range(1, 18):
                entries.append({"request_id": f"req_{index:02d}", "request_identity_sha256": f"fixture-{index:02d}", "status": "SUCCEEDED", "attempts": [{"attempt": 1}],
                                "selected_asset": {"path": "assets/confirmed.png", "production_qc": "AUTO_ACCEPTED"}})
            # Authentication was lost before request 18 reached the provider
            # boundary, so it has no provider attempt to replay or rewrite.
            entries.append({"request_id": "req_18", "request_identity_sha256": "fixture-18", "status": "AUTH_REQUIRED", "attempts": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id, "requests": entries})
            self.assertEqual(app.production_query(paths.project_id)["flow"]["status"], "AUTH_REQUIRED")
            entries[-1]["status"] = "NOT_DISPATCHED"
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id, "requests": entries})
            dispatched = []
            def generate(request, _refs, target):
                dispatched.append(request["request_id"])
                target.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "green").save(target, "PNG")
                return target
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
            app.generate(paths.project_id, executor=executor, request_ids={"req_18"})
            self.assertEqual(dispatched, ["req_18"])

    def test_coordinator_uses_flow_summary_before_visual_dispatch(self):
        state = {"pipeline_status": "PROJECT_MISMATCH", "active_stage": "VISUALS", "flow": {
            "status": "PROJECT_MISMATCH", "required": True, "human_message": "Open the correct Flow project to continue",
            "recoverable": True, "next_action": {"action": "open_flow_sign_in", "label": "Open expected Flow project"},
        }}
        calls = []
        result = ProductionCoordinator(lambda _: state, {name: lambda _project, name=name: calls.append(name)
                                                          for name in ("prepare", "plan", "visuals", "quality", "render")}).run_until("prj_phase_d")
        self.assertEqual((result["outcome"], calls), ("PROJECT_MISMATCH", []))

    def test_completed_project_remains_available_with_flow_offline(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_completed_offline", render_mode="full_image", content="# Done\n\n## Narration\n\nFixture.")
            paths, _config = app._project("prj_completed_offline")
            paths.artifact_path("output/final.mp4").write_bytes(b"provider-free final")
            workspace = app.project_workspace(paths.project_id)
            self.assertEqual((workspace["status"], workspace["production"]["pipeline_status"], workspace["final_path"]),
                             ("Complete", "COMPLETE", "output/final.mp4"))

    def test_ui_and_cli_use_the_canonical_recovery_surface(self):
        root = Path(__file__).parents[1]
        script = (root / "story_auto" / "ui" / "static" / "app.js").read_text(encoding="utf-8")
        cli = (root / "story_auto" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("rebind_flow_project", script)
        self.assertIn("validate_flow_connection", script)
        for command in ("flow-status", "prepare-flow-recovery", "validate-flow-connection", "rebind-flow-project", "continue-production"):
            self.assertIn(command, cli)


if __name__ == "__main__":
    unittest.main()
