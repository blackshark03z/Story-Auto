from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from story_auto.application.operator import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder, opening_builder_view
from story_auto.providers.byteplus_seedance.client import BytePlusSeedanceError, DEFAULT_MODEL
from story_auto.providers.byteplus_seedance.opening import generate_opening_slot_api
from story_auto.providers.credentials import clear_provider_keys, provider_key_status, provider_keys, set_provider_keys
from story_auto.ui.server import create_server


class _FakeOpeningClient:
    model = DEFAULT_MODEL
    provider = "byteplus_seedance"

    def __init__(self, root: str, project_id: str, *, ambiguous: bool = False, task_status: str = "succeeded"):
        self.root = root
        self.project_id = project_id
        self.ambiguous = ambiguous
        self.task_status = task_status
        self.create_calls = 0
        self.get_calls = 0
        self.acquire_calls = 0
        self.pre_dispatch_seen = False

    def readiness(self):
        return {"status": "READY", "model": self.model}

    def create_task(self, **_kwargs):
        self.create_calls += 1
        manifest = read_json(RuntimeLayout.from_root(self.root).projects / self.project_id / "output" / "opening_manifest.json")
        generation = manifest["slots"][0]["api_generation"]
        self.pre_dispatch_seen = generation["status"] == "PRE_DISPATCH" and generation["provider_submissions"] == 0
        if self.ambiguous:
            raise BytePlusSeedanceError("AMBIGUOUS_POST_DISPATCH", dispatch_state="AMBIGUOUS")
        return "opening-task-001"

    def get_task(self, task_id):
        self.get_calls += 1
        self.last_task_id = task_id
        return {"id": task_id, "status": self.task_status, "content": {"video_url": "https://example.invalid/opening.mp4"}}

    def acquire_video(self, _task, destination: Path):
        self.acquire_calls += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=c=navy:s=640x360:r=24:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(destination)
        ], check=True)
        return {"duration_seconds": 6.0, "width": 640, "height": 360, "codec": "h264", "container": "mp4"}


class HybridOpeningApiTests(unittest.TestCase):
    def _project(self, root: str, project_id: str = "prj_h3"):
        runtime = RuntimeLayout.from_root(root).ensure()
        paths = create_project(runtime, ProjectConfig(project_id, render_mode="hybrid_hook", settings={
            "render": {"width": 320, "height": 180, "fps": 24, "pixel_format": "yuv420p"}
        }))
        configure_opening_builder(root, project_id, shared_context="One stable protagonist at dawn.", slot_specs=[
            {"duration_seconds": 6, "purpose": "Hook", "prompt": "Opening hook with natural motion."},
            {"duration_seconds": 6, "purpose": "Develop", "prompt": "Continue the same character and location."},
            {"duration_seconds": 6, "purpose": "Transition", "prompt": "Finish the opening and transition into the story."},
        ])
        return runtime, paths

    def test_intent_is_persisted_before_post_and_success_binds_exact_slot(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths = self._project(root)
            client = _FakeOpeningClient(root, "prj_h3")
            result = generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client,
                                               poll_interval=.01, max_poll_seconds=.2)
            self.assertTrue(client.pre_dispatch_seen)
            self.assertEqual((client.create_calls, client.acquire_calls), (1, 1))
            slot = result["slots"][0]
            self.assertEqual(slot["slot_id"], "OPENING_O1")
            self.assertTrue(slot["asset_ready"])
            self.assertEqual(slot["api_generation"]["status"], "SUCCEEDED")
            self.assertEqual(slot["api_generation"]["provider_submissions"], 1)
            self.assertEqual(slot["api_generation"]["provider_task_id"], "opening-task-001")
            self.assertTrue(paths.artifact_path(slot["normalized_asset"]["path"]).is_file())

    def test_ambiguous_post_is_not_redispatched(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root)
            client = _FakeOpeningClient(root, "prj_h3", ambiguous=True)
            first = generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client,
                                              poll_interval=.01, max_poll_seconds=.01)
            second = generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client,
                                               poll_interval=.01, max_poll_seconds=.01)
            self.assertEqual(client.create_calls, 1)
            self.assertEqual(first["slots"][0]["api_generation"]["status"], "AMBIGUOUS")
            self.assertEqual(second["slots"][0]["api_generation"]["status"], "AMBIGUOUS")
            self.assertFalse(second["slots"][0]["asset_ready"])

    def test_known_task_resumes_without_new_post(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths = self._project(root)
            manifest_path = paths.artifact_path("output/opening_manifest.json")
            manifest = read_json(manifest_path)
            manifest["slots"][0]["api_generation"] = {
                "schema_version": "story-auto-opening-api-byteplus/1.0.0",
                "provider": "byteplus_seedance", "provider_model": DEFAULT_MODEL,
                "status": "SUBMITTED", "provider_submissions": 1,
                "provider_task_id": "existing-opening-task", "resolution": "720p",
                "prompt_sha256": manifest["slots"][0]["prompt_sha256"], "duration_seconds": 6.0,
            }
            atomic_write_json(manifest_path, manifest)
            client = _FakeOpeningClient(root, "prj_h3", task_status="running")
            result = generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client,
                                               poll_interval=.01, max_poll_seconds=0)
            self.assertEqual(client.create_calls, 0)
            self.assertEqual((client.get_calls, client.last_task_id), (1, "existing-opening-task"))
            self.assertEqual(result["slots"][0]["api_generation"]["provider_submissions"], 1)
            self.assertEqual(result["slots"][0]["api_generation"]["status"], "GENERATING")

    @unittest.skipUnless(os.name == "nt", "Story Auto credential persistence uses Windows DPAPI")
    def test_byteplus_key_round_trip_is_secret_free(self):
        with tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ, {"LOCALAPPDATA": local, "BYTEPLUS_MODELARK_API_KEY": ""}, clear=False):
                key = "fixture-byteplus-modelark-key-not-real"
                set_provider_keys("byteplus_modelark", [key])
                self.assertEqual(provider_keys("byteplus_modelark"), [key])
                self.assertTrue(provider_key_status("byteplus_modelark")["configured"])
                raw = (Path(local) / "StoryAuto" / "credentials.v1.json").read_text(encoding="utf-8")
                self.assertNotIn(key, raw)
                clear_provider_keys("byteplus_modelark")

    @unittest.skipUnless(os.name == "nt", "Browser credential journey requires Windows DPAPI")
    def test_browser_settings_and_opening_slot_offer_api_plus_manual(self):
        from playwright.sync_api import sync_playwright

        class FakeBytePlus:
            model = DEFAULT_MODEL
            def __init__(self, *args, **kwargs):
                try: self.key = provider_keys("byteplus_modelark")[0]
                except Exception: self.key = ""
            def readiness(self):
                return {"status": "READY" if self.key else "NOT_CONFIGURED", "provider": "BytePlus ModelArk",
                        "provider_id": "byteplus_seedance", "model": self.model, "transport": "REST_ASYNC_TASK",
                        "browser_required": False, "reason_code": None if self.key else "CREDENTIAL_MISSING"}
            def list_tasks(self, page_size=1):
                return {"items": []}

        with sync_playwright() as probe:
            chrome = Path(probe.chromium.executable_path)
        if not chrome.is_file(): self.skipTest("Playwright Chromium is not installed")

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ, {"LOCALAPPDATA": local, "BYTEPLUS_MODELARK_API_KEY": ""}, clear=False), \
                 patch("story_auto.application.operator.BytePlusSeedanceClient", FakeBytePlus), \
                 patch("story_auto.application.operator.seedance_readiness", side_effect=lambda: FakeBytePlus().readiness()), \
                 patch("story_auto.application.operator.generate_opening_slot_api", side_effect=lambda runtime_root, project_id, slot_id: opening_builder_view(runtime_root, project_id)) as generate_mock:
                app = OperatorService(root)
                runtime = RuntimeLayout.from_root(root).ensure()
                paths = create_project(runtime, ProjectConfig("prj_h3_browser", render_mode="hybrid_hook", settings={"hybrid_visual":{"cuj_enabled":True}}))
                paths.content_file.write_text("# H3\n\n## Narration\n\nA stable opening journey.\n", encoding="utf-8")
                configure_opening_builder(root, "prj_h3_browser", shared_context="One character.", slot_specs=[
                    {"duration_seconds": 6, "purpose": "Hook", "prompt": "Hook prompt"},
                    {"duration_seconds": 6, "purpose": "Develop", "prompt": "Develop prompt"},
                    {"duration_seconds": 6, "purpose": "Transition", "prompt": "Transition prompt"},
                ])
                server = create_server(root, port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                        page = browser.new_page(); page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                        page.locator("#settingsNav").click()
                        page.locator("#byteplusLiveStatus").get_by_text("Not configured", exact=True).wait_for(timeout=5000)
                        key = "fixture-byteplus-modelark-key-not-real"
                        page.locator("#byteplusApiKey").fill(key); page.locator("#saveByteplusKey").click()
                        page.locator("#byteplusLiveStatus").get_by_text("Configured", exact=True).wait_for(timeout=5000)
                        self.assertNotIn(key, page.locator("body").inner_text())
                        page.locator("#testByteplusKey").click()
                        page.locator("#byteplusLiveStatus").get_by_text("Connected", exact=True).wait_for(timeout=5000)
                        page.locator("#homeNav").click()
                        page.locator('[data-open-project="prj_h3_browser"]').click()
                        page.get_by_role("button", name="Generate with API", exact=True).first.wait_for(timeout=5000)
                        self.assertGreaterEqual(page.get_by_role("button", name="Generate with API", exact=True).count(), 1)
                        self.assertGreaterEqual(page.get_by_text("Import clip", exact=True).count(), 1)
                        page.get_by_role("button", name="Generate with API", exact=True).first.click()
                        page.wait_for_timeout(300)
                        self.assertTrue(generate_mock.called)
                        args = generate_mock.call_args.args
                        self.assertEqual((str(args[0]), args[1], args[2]), (str(Path(root)), "prj_h3_browser", "OPENING_O1"))
                        page.locator("#settingsNav").click(); page.locator("#clearByteplusKey").click()
                        page.locator("#byteplusLiveStatus").get_by_text("Not configured", exact=True).wait_for(timeout=5000)
                        browser.close()
                finally:
                    server.shutdown(); server.server_close(); thread.join(5)


if __name__ == "__main__":
    unittest.main()
