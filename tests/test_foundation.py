from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from story_auto.core.artifacts import ArtifactWriteError, atomic_write_json, atomic_write_text
from story_auto.core.checkpoint import FingerprintError, canonical_json, fingerprint
from story_auto.core.content import ContentValidationError, parse_content_markdown


class NarrationParsingTests(unittest.TestCase):
    def test_extracts_only_required_narration_section(self) -> None:
        document = parse_content_markdown(
            "# Title\n\n## Narration\n\nFirst line.\n\n### Preserved subheading\nSecond line.\n\n## Notes\nHidden.\n"
        )
        self.assertEqual(document.narration, "First line.\n\n### Preserved subheading\nSecond line.")

    def test_rejects_missing_empty_and_duplicate_sections(self) -> None:
        for source in (
            "# Title\n\nNarration without a heading.",
            "## Narration\n\n ## Other\n",
            "## Narration\nOne\n\n## Narration\nTwo\n",
        ):
            with self.subTest(source=source), self.assertRaises(ContentValidationError):
                parse_content_markdown(source)


class AtomicArtifactTests(unittest.TestCase):
    def test_writes_utf8_json_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "artifact.json"
            atomic_write_json(target, {"z": "Tiếng Việt", "a": [1, 2]})
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{\n  "a": [\n    1,\n    2\n  ],\n  "z": "Tiếng Việt"\n}\n',
            )
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["z"], "Tiếng Việt")

    def test_failed_replace_preserves_prior_file_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "artifact.txt"
            target.write_text("previous", encoding="utf-8")
            with patch("story_auto.core.artifacts.atomic.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(ArtifactWriteError):
                    atomic_write_text(target, "replacement")
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(Path(directory).glob(".artifact.txt.*.tmp")), [])


class FingerprintTests(unittest.TestCase):
    def test_canonical_inputs_have_stable_identity(self) -> None:
        first = fingerprint(namespace="story_auto.content.v1", direct_inputs={"b": 2, "a": {"y": 1, "x": 0}})
        second = fingerprint(namespace="story_auto.content.v1", direct_inputs={"a": {"x": 0, "y": 1}, "b": 2})
        changed = fingerprint(namespace="story_auto.content.v1", direct_inputs={"a": {"x": 0, "y": 2}, "b": 2})
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_rejects_invalid_namespace_and_nonfinite_json(self) -> None:
        with self.assertRaises(FingerprintError):
            fingerprint(namespace="", direct_inputs={})
        with self.assertRaises(FingerprintError):
            canonical_json({"not_finite": float("nan")})


if __name__ == "__main__":
    unittest.main()
