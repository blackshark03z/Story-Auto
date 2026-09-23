"""Offline matching for an ambiguous Dola attempt's read-only lookup."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.dola_cookie_attempt_reconcile import _matches


class DolaAttemptReconcileTests(unittest.TestCase):
    def test_only_top_level_input_and_linked_video_match(self):
        video = {"bot_reply_message_id": "input-1", "content": json.dumps([{"block_type": 2074}])}
        input_message = {"local_message_id": "attempt-1", "message_id": "input-1",
                         "conversation_id": "conv-1", "content": json.dumps([{"block_type": 10000}])}
        self.assertEqual(_matches([input_message, video], "attempt-1", "conv-1"), (True, True))
        self.assertEqual(_matches([{"metadata": input_message}, video], "attempt-1", "conv-1"),
                         (False, False))
        self.assertEqual(_matches([input_message, video], "attempt-1", "other-conv"),
                         (False, False))
        self.assertEqual(_matches([{**video, "local_message_id": "attempt-1"}],
                                  "attempt-1", "conv-1"), (False, False))

    def test_direct_invocation_loads_own_candidate(self):
        script = Path(__file__).resolve().parents[1] / "tools" / "dola_cookie_attempt_reconcile.py"
        with tempfile.TemporaryDirectory() as outside_checkout:
            result = subprocess.run([sys.executable, str(script), "--help"],
                                    cwd=outside_checkout, capture_output=True,
                                    text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--output", result.stdout)


if __name__ == "__main__":
    unittest.main()
