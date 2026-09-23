"""Offline safety checks for the Dola profile-to-DPAPI importer."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from tools.import_dola_profile_cookie import _browser_cookies_from_header


class DolaProfileImportTests(unittest.TestCase):
    def test_header_roundtrip_stays_scoped_to_dola_chat(self):
        rows = _browser_cookies_from_header("sessionid=one; sessionid_ss=two")
        self.assertEqual(rows, [
            {"name": "sessionid", "value": "one", "url": "https://www.dola.com/chat"},
            {"name": "sessionid_ss", "value": "two", "url": "https://www.dola.com/chat"},
        ])

    def test_direct_invocation_finds_candidate_checkout(self):
        for name, expected in (
            ("import_dola_profile_cookie.py", "--save"),
            ("dola_saved_cookie_read_probe.py", "--alias"),
        ):
            with self.subTest(script=name):
                script = Path(__file__).resolve().parents[1] / "tools" / name
                with tempfile.TemporaryDirectory() as outside_checkout:
                    result = subprocess.run([sys.executable, str(script), "--help"],
                                            cwd=outside_checkout, capture_output=True,
                                            text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                self.assertNotIn("ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
