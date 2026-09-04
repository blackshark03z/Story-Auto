from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
import unittest

from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.project.production_state import ProductionStateReconciler, stuck_pending_evidence


def waiting_attempt(at: datetime, *, lineage="lineage-1"):
    return {
        "provider_boundary_entered_at": at.isoformat(),
        "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
        "provider_submission_recorded": True,
        "dispatch_confirmed": True,
        "provider_lineage_card_id": lineage,
        "terminal_evidence": [],
        "provider_settings": {"provider_poll_authoritative_binding": {
            "resulting_dispatch_state": "CONFIRMED",
            "resulting_attribution_state": "WAITING",
            "durable_identity_used": "card:" + lineage,
        }},
    }


class StuckPendingTests(unittest.TestCase):
    def test_only_aged_exact_confirmed_waiting_evidence_is_stuck(self):
        now = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
        old = {"status": "AMBIGUOUS", "attempts": [waiting_attempt(now - timedelta(minutes=16))]}
        recent = {"status": "AMBIGUOUS", "attempts": [waiting_attempt(now - timedelta(minutes=14))]}
        mismatch = {"status": "AMBIGUOUS", "attempts": [waiting_attempt(now - timedelta(minutes=16), lineage="x")]}
        mismatch["attempts"][0]["provider_settings"]["provider_poll_authoritative_binding"]["durable_identity_used"] = "card:y"
        undispatched = {"status": "PENDING", "created_at": (now - timedelta(hours=1)).isoformat(), "attempts": []}
        self.assertTrue(stuck_pending_evidence(old, now=now, threshold_seconds=900)["stuck"])
        self.assertFalse(stuck_pending_evidence(recent, now=now, threshold_seconds=900)["stuck"])
        self.assertFalse(stuck_pending_evidence(mismatch, now=now, threshold_seconds=900)["eligible"])
        self.assertFalse(stuck_pending_evidence(undispatched, now=now, threshold_seconds=900)["eligible"])

    def test_projection_is_actionable_and_never_authorizes_dispatch(self):
        now = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_stuck", render_mode="full_image"))
            request = {"request_id": "req_stuck", "purpose": "SHOT"}
            entry = {"request_id": "req_stuck", "status": "AMBIGUOUS",
                     "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN",
                     "attempts": [waiting_attempt(now - timedelta(minutes=16))]}
            reconciler = ProductionStateReconciler(clock=lambda: now)
            recovery = reconciler._visual_recovery(paths, {"requests": [request]}, {"requests": [entry]},
                                                   {"req_stuck": entry}, {"req_stuck"}, False,
                                                   active_project_operation=False, threshold_seconds=900)
            self.assertEqual((recovery["status"], recovery["reason_code"], recovery["next_action"]),
                             ("STUCK_PENDING", "STUCK_PENDING", "Recheck status"))
            self.assertEqual((recovery["automatic_recovery_available"], recovery["provider_dispatches_per_continue"]),
                             (False, 0))

    def test_coordinator_stops_without_invoking_visuals(self):
        state = {"pipeline_status": "STUCK_PENDING", "active_stage": "VISUALS", "stages": {},
                 "quality": {}, "blocker": {"reason_code": "STUCK_PENDING"}, "next_action": {},
                 "final_output": {}, "recovery": {}}
        invoked = []
        result = ProductionCoordinator(lambda _: state, {"visuals": lambda _: invoked.append("visuals")}).run_until("prj_stuck")
        self.assertEqual((result["outcome"], invoked), ("STUCK_PENDING", []))


if __name__ == "__main__":
    unittest.main()
