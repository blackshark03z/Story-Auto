import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from story_auto.core.artifacts import read_json
from story_auto.providers.flow.validation import validate_image
from story_auto.providers.gemini_web.capabilities import inspect_capabilities
from story_auto.providers.gemini_web.page import GeminiWebDom
from story_auto.providers.gemini_web.session import GeminiWebRuntime, launch_dedicated_session
from story_auto.providers.gemini_web.service import execute_web_request


class _Page:
    state = {}

    @classmethod
    def open(cls, runtime):
        return cls()

    def evaluate(self, expression):
        return self.state

    def close(self):
        pass


class GeminiWebTests(unittest.TestCase):
    def test_media_records_exclude_image_mode_template_zero_state(self):
        class CapturingPage:
            expression = ""

            def evaluate(self, expression):
                self.expression = expression
                return []

        page = CapturingPage()
        self.assertEqual(GeminiWebDom(page).media_records(), [])
        self.assertIn("media-gen-template-card", page.expression)
        self.assertIn("zero-state-container", page.expression)

    def test_exact_reconciled_prompt_can_be_resubmitted_without_retyping(self):
        class ExistingPromptDom(GeminiWebDom):
            def editor_state(self):
                return {"text": "same prompt"}

        ExistingPromptDom(object()).set_prompt("same   prompt")

    def test_runtime_is_dedicated_and_uses_independent_port(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = GeminiWebRuntime.from_root(directory)
            self.assertEqual(runtime.cdp_url, "http://127.0.0.1:9223")
            self.assertEqual(runtime.profile, Path(directory).resolve() / "browser" / "gemini-profile")

    def test_launch_uses_only_owned_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = GeminiWebRuntime.from_root(directory)
            calls = []
            with patch("story_auto.providers.gemini_web.session._chrome_path", return_value=Path("chrome.exe")):
                launch_dedicated_session(runtime, launcher=lambda args, **kwargs: calls.append((args, kwargs)))
            args = calls[0][0]
            self.assertIn(f"--user-data-dir={runtime.profile}", args)
            self.assertIn("--remote-debugging-port=9223", args)
            self.assertNotIn("9222", " ".join(args))

    def test_capabilities_are_observed_without_inventing_model(self):
        _Page.state = {
            "url": "https://gemini.google.com/app", "title": "Gemini",
            "text": "Create image Create video 16:9 8s", "controls": ["Create image", "Create video"],
            "account": "Google Account: owner@example.invalid", "fileInputs": 1, "editors": 1,
        }
        with patch("story_auto.providers.gemini_web.capabilities.GeminiWebPage", _Page):
            found = inspect_capabilities(GeminiWebRuntime.from_root("runtime/test"))
        self.assertTrue(found.authenticated)
        self.assertTrue(found.image)
        self.assertTrue(found.video)
        self.assertTrue(found.reference_image)
        self.assertEqual(found.observed_mode_identity, "Create image | Create video")
        self.assertNotIn("example.invalid", json.dumps(found.to_dict()))

    def test_missing_account_is_auth_required(self):
        _Page.state = {
            "url": "https://gemini.google.com/app", "title": "Gemini", "text": "Sign in",
            "controls": ["Sign in"], "account": "", "fileInputs": 0, "editors": 0,
        }
        with patch("story_auto.providers.gemini_web.capabilities.GeminiWebPage", _Page):
            found = inspect_capabilities(GeminiWebRuntime.from_root("runtime/test"))
        self.assertFalse(found.authenticated)
        self.assertEqual(found.detail, "AUTH_REQUIRED")

    def test_append_only_execution_skips_valid_selection(self):
        class Generator:
            last_settings = {"output_count": 1}
            calls = 0

            def __call__(self, request, references, destination):
                self.calls += 1
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (128, 72), "#445566").save(destination)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            destination = root / "assets" / "candidate.png"
            request = {
                "request_id": "image-a-web-1", "request_identity_sha256": "identity",
                "media_type": "IMAGE", "prompt": "natural image", "output_count": 1,
            }
            generator = Generator()
            self.assertEqual(execute_web_request(
                manifest_path=ledger, artifact_root=root, request=request, references=[],
                destination=destination, generator=generator,
            ), "RUN")
            self.assertEqual(execute_web_request(
                manifest_path=ledger, artifact_root=root, request=request, references=[],
                destination=destination, generator=generator,
            ), "SKIP")
            self.assertEqual(generator.calls, 1)
            entry = read_json(ledger)["requests"][0]
            self.assertEqual(entry["attempts"][0]["status"], "SUCCEEDED")
            self.assertEqual(entry["selected_asset"]["sha256"], validate_image(destination)["sha256"])


if __name__ == "__main__":
    unittest.main()
