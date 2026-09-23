"""Offline boundaries for the isolated one-shot browser-UI canary."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import dola_browser_ui_canary as canary


class DolaBrowserUICanaryTests(unittest.TestCase):
    def test_dispatch_requires_explicit_ack_even_outside_checkout(self):
        script = Path(canary.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(script), "dispatch"],
                                    cwd=directory, capture_output=True,
                                    text=True, timeout=15, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ACK_REQUIRED", result.stderr)

    def test_preflight_only_calls_empty_composer_path(self):
        client = Mock()
        client.preflight.return_value = {"status": "UI_READY_NO_SUBMIT", "generation_submits": 0}
        with patch.object(canary, "_manifest", return_value={}), \
                patch.object(canary, "_generation", return_value={}), \
                patch.object(canary, "_client", return_value=client):
            canary._preflight()
        client.preflight.assert_called_once_with(duration=5)
        client.submit.assert_not_called()

    def test_existing_attempt_blocks_dispatch(self):
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

    def test_dispatch_calls_one_browser_client_path(self):
        manifest = {"slots": [
            {"slot_id": canary.SLOT_ID, "prompt": canary.PROMPT},
            {"slot_id": "OPENING_O2"}, {"slot_id": "OPENING_O3"},
        ]}
        client = Mock()
        with patch.object(canary, "_manifest", return_value=manifest), \
                patch.object(canary, "_client", return_value=client), \
                patch.object(canary, "_status"), \
                patch.object(canary, "generate_dola_opening") as generate:
            canary._dispatch()
        generate.assert_called_once()
        self.assertIs(generate.call_args.kwargs["client"], client)
        self.assertTrue(generate.call_args.kwargs["allow_new_submission"])

    def test_recovery_requires_exact_confirmed_browser_receipt(self):
        with patch.object(canary, "_generation", return_value={
            "provider": "dola_cookie", "transport": "browser_ui",
            "account_id": canary.ACCOUNT_ID,
            "provider_local_message_id": "native-1",
            "provider_task_id": "conversation-1", "dispatch_state": "AMBIGUOUS",
        }), patch.object(canary, "generate_dola_opening") as generate:
            with self.assertRaisesRegex(SystemExit, "NO_CONFIRMED_RECEIPT"):
                canary._recover()
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
