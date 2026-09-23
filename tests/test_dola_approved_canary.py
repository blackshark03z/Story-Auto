from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DolaApprovedCanaryCliTests(unittest.TestCase):
    def test_direct_invocation_imports_its_own_candidate_before_argument_parsing(self):
        script = Path(__file__).resolve().parents[1] / "tools" / "dola_cookie_approved_canary.py"
        with tempfile.TemporaryDirectory() as outside_checkout:
            result = subprocess.run([sys.executable, str(script), "--help"],
                                    cwd=outside_checkout, capture_output=True, text=True,
                                    timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dispatch", result.stdout)
        self.assertNotIn("ModuleNotFoundError", result.stderr)
