from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


_TOOL = Path(__file__).parents[1] / "tools" / "goal54_make_reference_fixture.py"
_SPEC = importlib.util.spec_from_file_location("goal54_make_reference_fixture", _TOOL)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)


class Goal54ReferenceFixtureTests(unittest.TestCase):
    def test_fixture_is_deterministic_1280x720_rgb_png(self):
        with tempfile.TemporaryDirectory() as root:
            one = Path(root) / "one.png"
            two = Path(root) / "two.png"
            sha_one = _mod.write_reference(one)
            sha_two = _mod.write_reference(two)
            self.assertEqual(sha_one, sha_two)
            self.assertEqual(hashlib.sha256(one.read_bytes()).hexdigest(), sha_one)
            with Image.open(one) as image:
                self.assertEqual(image.size, (1280, 720))
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.format, "PNG")


if __name__ == "__main__":
    unittest.main()
