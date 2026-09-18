from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path

from story_auto.ui import create_server
from tests.browser_support import system_chrome_path


class HomeActionFreshnessTests(unittest.TestCase):
    """Home is a cached discovery surface, never authority for the next effect."""

    def setUp(self):
        chrome = system_chrome_path()
        if chrome is None:
            self.skipTest("Google Chrome is not installed for browser acceptance")
        from playwright.sync_api import sync_playwright

        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.server = create_server(self.root.name, port=0)
        self.service = self.server.RequestHandlerClass.service
        self.workspace_calls = []
        self.actions = []
        self.asset_requests = []
        self.release = threading.Event()
        self.started = threading.Event()
        self.delay_project = None
        self.fail_workspace = False
        self.cards = [self.card("prj_home", "run_to_final", "Continue production")]
        self.workspaces = {"prj_home": self.workspace("prj_home")}
        self.service.list_projects = lambda: deepcopy(self.cards)

        def get_workspace(project_id):
            self.workspace_calls.append(project_id)
            snapshot = deepcopy(self.workspaces[project_id])
            if project_id == self.delay_project:
                self.started.set()
                if not self.release.wait(10):
                    raise AssertionError("fixture workspace response was not released")
            if self.fail_workspace:
                raise ValueError("Synthetic workspace refresh failure")
            return snapshot

        self.service.project_workspace = get_workspace
        self.service.run_to_final = lambda project_id: self.actions.append(project_id) or {"outcome": "SAFETY_BLOCKED"}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(headless=True, executable_path=str(chrome))
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 1366, "height": 768})
        self.page.on("request", lambda request: self.asset_requests.append(request.url) if "/asset?" in request.url else None)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close_server(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    @staticmethod
    def card(project_id, action, label):
        return {"project_id": project_id, "title": project_id, "render_mode": "full_image",
                "user_status": "Complete" if action == "open_final" else "Ready", "progress": 100,
                "current_activity": label, "updated_at": "2026-09-18T00:00:00Z", "attention": [],
                "primary_action": {"action_id": action, "action": label},
                "final_path": "output/old-final.mp4" if action == "open_final" else None}

    @staticmethod
    def workspace(project_id):
        return {"project_id": project_id, "title": project_id, "status": "Ready", "final_path": None,
                "can_render_again": False,
                "summary": {"source": "Audio + SRT", "style": "Full Image", "quality": "Automatic",
                            "waveform": "On", "resolution": "1920 × 1080"},
                "production": {"pipeline_status": "READY", "active_stage": "VISUALS", "blocker": None,
                               "stages": {name: {"status": "READY"} for name in ("SOURCE", "TIMING", "PLAN", "VISUALS", "QUALITY", "RENDER")},
                               "next_action": {"action": "run_to_final", "label": "Continue production"},
                               "flow": {"required": False, "status": "CONNECTED", "human_message": "Fixture ready"}}}

    def home(self):
        self.page.goto(self.base)
        self.page.get_by_role("button", name="View project", exact=True).first.wait_for()

    def capture(self, name):
        destination = os.environ.get("STORY_AUTO_CUJ_EVIDENCE_DIR")
        if not destination:
            return
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path / f"{name}.png"), full_page=True)
        (path / f"{name}.json").write_text(json.dumps({
            "url": self.page.url, "viewport": self.page.viewport_size,
            "workspace_calls": self.workspace_calls, "action_calls": self.actions,
            "asset_requests": self.asset_requests, "fixture": "isolated fake service; no providers",
        }, indent=2), encoding="utf-8")

    def test_stale_final_refreshes_without_opening_asset_or_starting_production(self):
        self.cards = [self.card("prj_home", "open_final", "Open final video")]
        self.home()
        self.page.get_by_role("button", name="Open final video", exact=True).click()
        self.page.get_by_text("This project has changed. Review its current state before continuing.", exact=True).wait_for()
        self.assertEqual(self.workspace_calls, ["prj_home"])
        self.assertEqual(self.actions, [])
        self.assertEqual(self.asset_requests, [])
        self.assertEqual(self.page.get_by_role("link", name="Open final video").count(), 0)
        self.capture("stale-final-desktop")
        self.page.set_viewport_size({"width": 760, "height": 820})
        self.capture("stale-final-narrow")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 760)

    def test_review_intent_cannot_turn_into_production_after_refresh(self):
        self.cards = [self.card("prj_home", "review_plan", "Review plan")]
        self.home()
        self.page.get_by_role("button", name="Review plan", exact=True).click()
        self.page.get_by_text("This project has changed. Review its current state before continuing.", exact=True).wait_for()
        self.assertEqual(self.actions, [])
        self.page.get_by_role("button", name="Continue production", exact=True).first.click()
        self.page.get_by_text("Production stopped safely", exact=True).wait_for()
        self.assertEqual(self.actions, ["prj_home"])

    def test_unchanged_continue_dispatches_once(self):
        self.home()
        self.page.get_by_role("button", name="Continue production", exact=True).click()
        self.page.get_by_text("Production stopped safely", exact=True).wait_for()
        self.assertEqual(self.actions, ["prj_home"])

    def test_failed_refresh_cannot_dispatch(self):
        self.fail_workspace = True
        self.home()
        self.page.get_by_role("button", name="Continue production", exact=True).click()
        self.page.get_by_role("heading", name="Could not open project", exact=True).wait_for()
        self.assertEqual(self.actions, [])
        self.assertEqual(self.page.evaluate("state.snapshot"), None)

    def test_leaving_for_home_cancels_pending_card_intent(self):
        self.delay_project = "prj_home"
        self.home()
        self.page.get_by_role("button", name="Continue production", exact=True).click()
        self.assertTrue(self.started.wait(3))
        self.page.locator("#homeNav").click()
        self.page.get_by_role("button", name="View project", exact=True).wait_for()
        with self.page.expect_response(lambda response: response.url.endswith("/workspace")):
            self.release.set()
        self.page.wait_for_function("state.busy === false")
        self.assertEqual(self.page.locator("#viewTitle").inner_text(), "Home")
        self.assertEqual(self.actions, [])
        self.assertEqual(self.page.evaluate("state.snapshot"), None)

    def test_slow_project_cannot_overwrite_later_project_or_dispatch(self):
        self.cards.append(self.card("prj_other", "run_to_final", "Continue production"))
        self.workspaces["prj_other"] = self.workspace("prj_other")
        self.delay_project = "prj_home"
        self.home()
        self.page.locator('[data-project="prj_home"]').click()
        self.assertTrue(self.started.wait(3))
        self.page.locator('[data-open-project="prj_other"]').click()
        self.page.get_by_role("heading", name="prj_other", exact=True).first.wait_for()
        with self.page.expect_response(lambda response: "/prj_home/workspace" in response.url):
            self.release.set()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate("state.snapshot.project_id"), "prj_other")
        self.assertEqual(self.actions, [])

    def test_opening_then_closing_new_video_cancels_pending_card_intent(self):
        self.delay_project = "prj_home"
        self.page.route("**/api/creation-defaults", lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))
        self.home()
        self.page.get_by_role("button", name="Continue production", exact=True).click()
        self.assertTrue(self.started.wait(3))
        self.page.locator("#newVideoTop").click()
        self.page.get_by_role("dialog").wait_for()
        self.page.locator("#closeWizard").click()
        with self.page.expect_response(lambda response: response.url.endswith("/workspace")):
            self.release.set()
        self.page.wait_for_function("state.busy === false")
        self.assertEqual(self.actions, [])
        self.assertIsNone(self.page.evaluate("state.snapshot"))

    def test_completed_card_opens_fresh_result_and_repeat_creation(self):
        self.cards = [self.card("prj_home", "open_final", "Open final video")]
        complete = self.workspaces["prj_home"]
        complete.update(status="Complete", final_path="output/current-final.mp4")
        complete["production"].update(pipeline_status="COMPLETE", next_action={"action": "open_final", "label": "Open final video"})
        self.page.route("**/api/creation-defaults", lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))
        self.page.route("**/asset?**", lambda route: route.fulfill(status=200, content_type="video/mp4", body=b""))
        self.home()
        self.page.get_by_role("button", name="Open final video", exact=True).click()
        self.page.get_by_role("heading", name="Your final video is ready.", exact=True).wait_for()
        self.assertIn("current-final.mp4", self.page.get_by_role("link", name="Open final video", exact=True).get_attribute("href"))
        self.assertFalse(any("old-final" in url for url in self.asset_requests))
        self.assertEqual(self.actions, [])
        self.capture("fresh-final-desktop")
        self.page.set_viewport_size({"width": 760, "height": 820})
        self.capture("fresh-final-narrow")
        self.page.get_by_role("button", name="Create another video", exact=True).click()
        self.page.get_by_role("dialog").wait_for()
        self.assertIsNone(self.page.evaluate("state.wizard.createdProjectId ?? null"))
