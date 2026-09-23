"""Offline exact-once guards for the fresh-profile Dola canary."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import dola_cookie_profile_canary as canary


class DolaProfileCanaryTests(unittest.TestCase):
    def test_direct_invocation_resolves_candidate_and_requires_ack(self):
        script = Path(canary.__file__).resolve()
        with tempfile.TemporaryDirectory() as outside_checkout:
            help_result = subprocess.run([sys.executable, str(script), "--help"],
                                         cwd=outside_checkout, capture_output=True,
                                         text=True, timeout=15, check=False)
            unacked = subprocess.run([sys.executable, str(script), "dispatch"],
                                     cwd=outside_checkout, capture_output=True,
                                     text=True, timeout=15, check=False)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--ack-one-request", help_result.stdout)
        self.assertNotEqual(unacked.returncode, 0)
        self.assertIn("ACK_REQUIRED", unacked.stderr)

    def test_existing_attempt_cannot_be_redispatched(self):
        manifest = {"slots": [
            {"slot_id": canary.SLOT_ID, "prompt": canary.PROMPT,
             "api_generation": {"status": "AMBIGUOUS"}},
            {"slot_id": "OPENING_O2"}, {"slot_id": "OPENING_O3"},
        ]}
        with patch.object(canary, "_manifest", return_value=manifest), \
                patch.object(canary, "generate_dola_opening") as generate:
            with self.assertRaisesRegex(SystemExit, "ATTEMPT_EXISTS"):
                canary._dispatch()
        generate.assert_not_called()

    def test_dispatch_calls_one_authorized_submission_path(self):
        manifest = {"slots": [
            {"slot_id": canary.SLOT_ID, "prompt": canary.PROMPT},
            {"slot_id": "OPENING_O2"}, {"slot_id": "OPENING_O3"},
        ]}
        with patch.object(canary, "_manifest", return_value=manifest), \
                patch.object(canary, "_status"), \
                patch.object(canary, "generate_dola_opening") as generate:
            canary._dispatch()
        generate.assert_called_once()
        self.assertTrue(generate.call_args.kwargs["allow_new_submission"])

    def test_recovery_only_checks_confirmed_receipt(self):
        manifest = {"slots": [{"slot_id": canary.SLOT_ID, "api_generation": {
            "provider": "dola_cookie", "account_id": canary.ACCOUNT_ID,
            "provider_task_id": "confirmed-receipt", "dispatch_state": "CONFIRMED",
        }}]}
        with patch.object(canary, "_manifest", return_value=manifest), \
                patch.object(canary, "_status"), \
                patch.object(canary, "generate_dola_opening") as generate:
            canary._recover()
        self.assertFalse(generate.call_args.kwargs["allow_new_submission"])


if __name__ == "__main__":
    unittest.main()
