from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


_TOOL = Path(__file__).parents[1] / "tools" / "goal54_elyum_experiment.py"
_SPEC = importlib.util.spec_from_file_location("goal54_elyum_experiment", _TOOL)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)


class Goal54ElyumExperimentCliTests(unittest.TestCase):
    def test_preview_requires_explicit_dispatch_confirmation(self):
        self.assertEqual(
            _mod.confirmation_failure("preview", confirm_dispatch=False, confirm_spend=False, confirm_kill=False),
            "CONFIRM_DISPATCH_REQUIRED",
        )
        self.assertIsNone(
            _mod.confirmation_failure("preview", confirm_dispatch=True, confirm_spend=False, confirm_kill=False)
        )

    def test_keep_and_kill_have_separate_consequence_confirmations(self):
        self.assertEqual(
            _mod.confirmation_failure("keep", confirm_dispatch=False, confirm_spend=False, confirm_kill=False),
            "CONFIRM_SPEND_REQUIRED",
        )
        self.assertEqual(
            _mod.confirmation_failure("kill", confirm_dispatch=False, confirm_spend=False, confirm_kill=False),
            "CONFIRM_KILL_REQUIRED",
        )
        self.assertIsNone(
            _mod.confirmation_failure("keep", confirm_dispatch=False, confirm_spend=True, confirm_kill=False)
        )
        self.assertIsNone(
            _mod.confirmation_failure("kill", confirm_dispatch=False, confirm_spend=False, confirm_kill=True)
        )

    def test_r1_prompt_encodes_identity_and_single_camera_motion(self):
        prompt = _mod.R1_PROMPT.lower()
        self.assertIn("teal bob", prompt)
        self.assertIn("crimson round glasses", prompt)
        self.assertIn("slow, smooth push-in only", prompt)
        self.assertIn("no pan", prompt)
        self.assertIn("no orbit", prompt)


if __name__ == "__main__":
    unittest.main()
