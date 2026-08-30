from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave

from story_auto.application.operator import OperatorService
from story_auto.ui import create_server


def _wav(seconds: int = 2) -> bytes:
    value = BytesIO()
    with wave.open(value, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * seconds)
    return value.getvalue()


class Goal52DraftLifecycleTests(unittest.TestCase):
    def test_lightweight_creation_defaults_never_enumerates_projects(self):
        with tempfile.TemporaryDirectory() as root:
            service = OperatorService(root)
            service.list_projects = lambda: (_ for _ in ()).throw(AssertionError("project enumeration is forbidden"))
            payload = service.creation_defaults()
        self.assertIn("creation_defaults", payload)
        self.assertIn("voice_options", payload)
        self.assertNotIn("projects", payload)

    def test_client_has_single_draft_owner_and_no_content_inference(self):
        script = (Path(__file__).parents[1] / "story_auto/ui/static/app.js").read_text(encoding="utf-8")
        self.assertIn("wizard: null, creationDefaults: null, nextDraftId: 0", script)
        self.assertIn("function freshDraft()", script)
        self.assertIn("if (isNew) state.wizard = freshDraft();", script)
        self.assertIn("if (draft) { draft.revision += 1; state.wizard=null; }", script)
        self.assertNotIn("if (!state.wizard.content)", script)
        open_wizard = script.split("async function openWizard()", 1)[1].split("function wizardSteps()", 1)[0]
        self.assertNotIn("/api/settings", open_wizard)
        self.assertIn("hydrateCreationDefaults(wizard)", open_wizard)
        self.assertIn("bindingIsCurrent", script)
        self.assertIn("source:draft.source, audio:draft.importedAudio, srt:draft.importedSrt", script)

    def test_real_browser_shell_is_fast_and_hydration_cannot_reset_source(self):
        chrome = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe"
        if not chrome.is_file():
            self.skipTest("Google Chrome is not installed for the focused UI regression")
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as root:
            server = create_server(root, port=0)
            service = server.RequestHandlerClass.service
            original_defaults = service.creation_defaults
            original_imports = service.inspect_imports

            def delayed_defaults():
                time.sleep(1.2)
                return original_defaults()

            def delayed_imports(**kwargs):
                time.sleep(0.8)
                return original_imports(**kwargs)

            service.creation_defaults = delayed_defaults
            service.inspect_imports = delayed_imports
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                    started = time.monotonic()
                    page.locator("#newVideoTop").click()
                    page.locator("#newVideoDialog").wait_for(state="visible", timeout=1000)
                    page.locator('input[name="inputSource"][value="STORY_CONTENT"]').wait_for(state="visible", timeout=1000)
                    self.assertLessEqual((time.monotonic() - started) * 1000, 1200)

                    page.locator('input[name="inputSource"][value="AUDIO_SRT"]').check()
                    page.wait_for_timeout(1400)
                    self.assertTrue(page.locator('input[name="inputSource"][value="AUDIO_SRT"]').is_checked())
                    page.evaluate("openWizard()")
                    self.assertTrue(page.locator('input[name="inputSource"][value="AUDIO_SRT"]').is_checked())

                    page.locator("#closeWizard").click()
                    page.locator("#newVideoTop").click()
                    self.assertTrue(page.locator('input[name="inputSource"][value="STORY_CONTENT"]').is_checked())

                    page.locator('input[name="inputSource"][value="EXISTING_AUDIO"]').check()
                    page.get_by_role("button", name="Continue", exact=True).click()
                    page.locator("#existingAudio").set_input_files({"name": "voice.wav", "mimeType": "audio/wav", "buffer": _wav()})
                    page.get_by_role("button", name="Back", exact=True).click()
                    page.locator('input[name="inputSource"][value="AUDIO_SRT"]').check()
                    page.get_by_role("button", name="Continue", exact=True).click()
                    self.assertTrue(page.locator("#existingAudio").is_visible())
                    first_srt = b"1\n00:00:00,000 --> 00:00:01,700\nfirst\n"
                    second_srt = b"1\n00:00:00,000 --> 00:00:01,700\nsecond\n"
                    page.locator("#existingSrt").set_input_files({"name": "timing-a.srt", "mimeType": "text/plain", "buffer": first_srt})
                    page.wait_for_timeout(120)
                    page.locator("#existingSrt").set_input_files({"name": "timing-b.srt", "mimeType": "text/plain", "buffer": second_srt})
                    page.wait_for_timeout(1800)
                    self.assertIn("timing-b.srt", page.locator("#wizardContent").inner_text())
                    self.assertTrue(page.locator('input[name="inputSource"][value="AUDIO_SRT"]').is_checked())
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(5)


if __name__ == "__main__":
    unittest.main()
