"""Offline Goal 25 revision-2 recovery proof symmetry tests."""
from __future__ import annotations

import hashlib
import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    _provider_generation_retry_authorized,
    _unresolved_flow_entry,
    canonical_no_dispatch_proof,
    execute_generation,
    recover_interrupted_pre_dispatch_attempt,
    reopen_verified_false_dispatch,
    reopen_verified_pre_dispatch_failure,
)
from story_auto.providers.flow.session import FlowCapabilities


REQUEST_ID = "req_goal25_r2_recovery"


def _current_no_dispatch_attempt(*, failure_class: str = "FLOW_UI_CHANGED") -> dict:
    return {
        "attempt": 1,
        "status": "SUBMITTED",
        "failure_class": failure_class,
        "dispatch_confirmed": False,
        "provider_job_id": None,
        "durable_dispatch_identity": None,
        "provider_lineage_card_id": None,
        "attributed_provider_identity": None,
        "attribution_state": "NOT_ATTEMPTED",
        "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
        "provider_settings": {"activation": {"input_dispatched": False}},
    }


class Goal25Revision2RecoveryProofTests(unittest.TestCase):
    def _project(self, root: str, *, entry_status: str = "GENERATING", attempt: dict | None = None):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal25_r2_fixture")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [{
            "request_id": REQUEST_ID, "fingerprint": "goal25-r2", "purpose": "REFERENCE",
            "entity_id": "subject", "media_type": "IMAGE", "provider": "google_flow",
            "prompt": "subject reference", "output_count": 1, "depends_on": [], "reference_asset_ids": [],
        }]})
        attempt = attempt or {
            "attempt": 1, "status": "SUBMITTED", "dispatch_confirmed": False,
            "provider_settings": None, "provider_execution_state": "NOT_STARTED",
        }
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
            "requests": [{
                "request_id": REQUEST_ID, "request_identity_sha256": "goal25-r2", "related_identity": "subject",
                "media_type": "IMAGE", "provider": "google_flow", "prompt_sha256": "goal25-r2",
                "reference_asset_hashes": [], "attempts": [attempt], "status": entry_status,
                "failure_class": attempt.get("failure_class"),
            }],
        })
        return runtime, config, paths

    @staticmethod
    def _entry(paths):
        return read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]

    def test_crash_before_provider_setup_produces_the_shared_canonical_proof_and_reenters(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            recover_interrupted_pre_dispatch_attempt(runtime.root, config.project_id, REQUEST_ID)
            entry = self._entry(paths)
            attempt = entry["attempts"][-1]
            self.assertTrue(canonical_no_dispatch_proof(attempt))
            self.assertTrue(_provider_generation_retry_authorized(entry))
            self.assertFalse(_unresolved_flow_entry(entry))

            calls = []

            class ProviderBoundaryReached(Exception):
                pass

            def provider_boundary(request, _references, _destination):
                calls.append(request["request_id"])
                raise ProviderBoundaryReached("offline provider boundary reached")

            with self.assertRaises(ProviderBoundaryReached):
                execute_generation(
                    runtime.root, config.project_id,
                    executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider_boundary),
                    execute=True, request_ids={REQUEST_ID}, max_requests=1,
                )
            self.assertEqual(calls, [REQUEST_ID])

    def test_reconciler_produces_the_same_current_schema_proof_before_any_provider_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            result = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: None),
                execute=True, request_ids=set(),
            )
            entry = self._entry(paths)
            self.assertEqual((result["reconciliations"], entry["status"]), (1, "NOT_DISPATCHED"))
            self.assertTrue(canonical_no_dispatch_proof(entry["attempts"][-1]))
            self.assertTrue(_provider_generation_retry_authorized(entry))
            self.assertFalse(_unresolved_flow_entry(entry))

    def test_reconciler_cannot_release_a_contradictory_attempt_with_a_current_shaped_proof(self):
        with tempfile.TemporaryDirectory() as root:
            attempt = {"attempt": 1, "status": "GENERATING", "dispatch_confirmed": False,
                       "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED", "provider_settings": {},
                       "provider_job_id": "job:retained-contradiction"}
            runtime, config, paths = self._project(root, attempt=attempt)

            class ContradictoryReconciler:
                def reconcile(self, *_args):
                    return {"state": "PROVEN_PRE_DISPATCH_FAILURE", "evidence": {"input_dispatched": False}}

            result = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), ContradictoryReconciler()),
                execute=True, request_ids=set(),
            )
            entry = self._entry(paths)
            self.assertEqual((result["blocked"], result["blocked_request_id"], entry["status"]),
                             (True, REQUEST_ID, "GENERATING"))
            self.assertFalse(canonical_no_dispatch_proof(entry["attempts"][-1]))
            self.assertFalse(_provider_generation_retry_authorized(entry))

    def test_provider_boundary_or_ambiguous_crash_never_produces_no_dispatch_proof(self):
        for label, marker in {
            "provider_boundary_entered": "PROVIDER_BOUNDARY_ENTERED",
            "ambiguous_crash_point": "UNKNOWN",
        }.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
                attempt = manifest["requests"][0]["attempts"][-1]
                attempt["provider_execution_state"] = marker
                atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
                with self.assertRaisesRegex(FlowError, "GENERATION_RECONCILIATION_INVALID"):
                    recover_interrupted_pre_dispatch_attempt(runtime.root, config.project_id, REQUEST_ID)
                entry = self._entry(paths)
                self.assertFalse(canonical_no_dispatch_proof(entry["attempts"][-1]))
                self.assertFalse(_provider_generation_retry_authorized(entry))

    def test_status_and_absence_signals_never_authorize_crash_recovery(self):
        cases = {
            "dispatch_confirmed_false_only": {"dispatch_confirmed": False},
            "provider_settings_none_only": {"provider_settings": None},
            "submitted_generating_only": {"status": "SUBMITTED", "dispatch_confirmed": False,
                                             "provider_settings": None},
        }
        for label, attempt in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root, attempt=attempt)
                with self.assertRaisesRegex(FlowError, "GENERATION_RECONCILIATION_INVALID"):
                    recover_interrupted_pre_dispatch_attempt(runtime.root, config.project_id, REQUEST_ID)
                entry = self._entry(paths)
                self.assertFalse(canonical_no_dispatch_proof(entry["attempts"][-1]))
                self.assertFalse(_provider_generation_retry_authorized(entry))

    def test_reopen_helpers_require_the_same_canonical_proof_or_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            attempt = _current_no_dispatch_attempt()
            runtime, config, paths = self._project(root, entry_status="FAILED_PERMANENT", attempt=attempt)
            reopen_verified_pre_dispatch_failure(runtime.root, config.project_id, REQUEST_ID)
            entry = self._entry(paths)
            self.assertEqual(entry["status"], "FAILED_RETRYABLE")
            self.assertTrue(canonical_no_dispatch_proof(entry["attempts"][-1]))

        with tempfile.TemporaryDirectory() as root:
            runtime, config, _ = self._project(root, entry_status="FAILED_PERMANENT",
                                                attempt={"failure_class": "FLOW_UI_CHANGED", "dispatch_confirmed": False})
            with self.assertRaisesRegex(FlowError, "GENERATION_RECONCILIATION_INVALID"):
                reopen_verified_pre_dispatch_failure(runtime.root, config.project_id, REQUEST_ID)

        with tempfile.TemporaryDirectory() as root:
            attempt = _current_no_dispatch_attempt(failure_class="FLOW_TIMEOUT")
            attempt["provider_settings"].update({
                "dispatch_ack_method": "composer_clear_or_output_transition",
                "last_added_candidate_count": 0,
            })
            runtime, config, paths = self._project(root, entry_status="AMBIGUOUS", attempt=attempt)
            evidence = {"prompt_retained": True, "visible_media_count": 0,
                        "prompt_sha256": hashlib.sha256(b"subject reference").hexdigest(),
                        "screenshot_sha256": "a" * 64}
            reopen_verified_false_dispatch(runtime.root, config.project_id, REQUEST_ID, evidence=evidence)
            entry = self._entry(paths)
            self.assertTrue(canonical_no_dispatch_proof(entry["attempts"][-1]))
            self.assertTrue(_provider_generation_retry_authorized(entry))

        with tempfile.TemporaryDirectory() as root:
            runtime, config, _ = self._project(root, entry_status="AMBIGUOUS", attempt={
                "failure_class": "FLOW_TIMEOUT", "dispatch_confirmed": True,
                "provider_settings": {"dispatch_ack_method": "composer_clear_or_output_transition",
                                      "last_added_candidate_count": 0},
            })
            evidence = {"prompt_retained": True, "visible_media_count": 0,
                        "prompt_sha256": hashlib.sha256(b"subject reference").hexdigest(),
                        "screenshot_sha256": "a" * 64}
            with self.assertRaisesRegex(FlowError, "GENERATION_RECONCILIATION_INVALID"):
                reopen_verified_false_dispatch(runtime.root, config.project_id, REQUEST_ID, evidence=evidence)


if __name__ == "__main__":
    unittest.main()
