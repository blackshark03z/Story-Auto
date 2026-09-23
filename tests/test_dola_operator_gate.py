"""The ordinary operator path remains closed without an exact Dola gate."""
from __future__ import annotations

import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from story_auto.application.operator import OperatorService, OperatorServiceError
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder
from story_auto.providers.dola_cookie.client import DolaCookieError


class DolaOperatorGateTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = temporary.name
        runtime = RuntimeLayout.from_root(self.root).ensure()
        create_project(runtime, ProjectConfig("prj_dola", render_mode="hybrid_hook", settings={
            "hybrid_visual": {"opening_provider_policy": "DOLA"},
        }))
        configure_opening_builder(self.root, "prj_dola", shared_context="River",
                                  slot_specs=[
                                      {"duration_seconds": 5, "purpose": "First", "prompt": "A river"},
                                      {"duration_seconds": 8, "purpose": "Second", "prompt": "A bridge"},
                                      {"duration_seconds": 5, "purpose": "Third", "prompt": "A village"},
                                  ])
        self.service = OperatorService(self.root)
        self.store = Mock()
        self.store.list_accounts.return_value = [{"account_id": "daily", "configured": True}]
        self.store.get_cookie.return_value = "sessionid=fixture"
        self.client = Mock(profile_binding="a" * 64)
        self.client.preflight.return_value = {"status": "UI_READY_NO_SUBMIT", "generation_submits": 0}
        store_patch = patch("story_auto.application.operator.DolaAccountStore", return_value=self.store)
        browser_patch = patch("story_auto.providers.dola_cookie.browser_ui.DolaBrowserUIClient",
                              return_value=self.client)
        store_patch.start(); browser_patch.start()
        self.addCleanup(store_patch.stop); self.addCleanup(browser_patch.stop)

    def test_default_route_cannot_submit(self):
        with patch.dict(os.environ, {"STORY_AUTO_DOLA_BROWSER_UI_ENABLED": "",
                                     "STORY_AUTO_DOLA_BROWSER_UI_PROJECT": "",
                                     "STORY_AUTO_DOLA_BROWSER_UI_ACCOUNT": ""}):
            status = self.service.dola_connection_status("prj_dola")
            self.assertFalse(status["generation_enabled"])
            with self.assertRaisesRegex(DolaCookieError, "SESSION_NOT_VERIFIED"):
                self.service.generate_dola_opening("prj_dola", slot_id="OPENING_O1",
                                                   account_id="daily", confirm_generate=True)
        self.client.preflight.assert_not_called()

    def test_exact_project_account_slot_and_confirmation_are_required(self):
        with patch.dict(os.environ, {"STORY_AUTO_DOLA_BROWSER_UI_ENABLED": "1",
                                     "STORY_AUTO_DOLA_BROWSER_UI_PROJECT": "prj_dola",
                                     "STORY_AUTO_DOLA_BROWSER_UI_ACCOUNT": "daily"}):
            status = self.service.dola_connection_status("prj_dola")
            self.assertTrue(status["browser_gate_configured"])
            self.assertFalse(status["generation_enabled"])
            with self.assertRaisesRegex(OperatorServiceError, "CONFIRMATION_REQUIRED"):
                self.service.generate_dola_opening("prj_dola", slot_id="OPENING_O1",
                                                   account_id="daily")
            checked = self.service.preflight_dola_opening(
                "prj_dola", slot_id="OPENING_O1", account_id="daily")
            self.assertEqual(checked["verified_slot_id"], "OPENING_O1")
            self.assertTrue(checked["generation_enabled"])
            self.client.preflight.assert_called_once_with(duration=5)
            with self.assertRaisesRegex(OperatorServiceError, "PREFLIGHT_REQUIRED"):
                self.service.generate_dola_opening("prj_dola", slot_id="OPENING_O2",
                                                   account_id="daily", confirm_generate=True)
            with patch("story_auto.providers.dola_cookie.opening.generate_dola_opening") as generate:
                self.service.generate_dola_opening("prj_dola", slot_id="OPENING_O1",
                                                   account_id="daily", confirm_generate=True)
            generate.assert_called_once()
            self.assertIs(generate.call_args.kwargs["client"], self.client)
            self.assertTrue(generate.call_args.kwargs["allow_new_submission"])
            self.assertEqual(self.client.preflight.call_count, 2)

            self.client.profile_binding = "b" * 64
            self.assertFalse(self.service.dola_connection_status("prj_dola")["generation_enabled"])
            self.assertFalse(self.service.dola_connection_status("another_project")["generation_enabled"])
            with self.assertRaisesRegex(OperatorServiceError, "GATE_NOT_ENABLED"):
                self.service.preflight_dola_opening("prj_dola", slot_id="OPENING_O1",
                                                    account_id="another")

    def test_cookie_refresh_during_final_preflight_refuses_without_journal(self):
        with patch.dict(os.environ, {"STORY_AUTO_DOLA_BROWSER_UI_ENABLED": "1",
                                     "STORY_AUTO_DOLA_BROWSER_UI_PROJECT": "prj_dola",
                                     "STORY_AUTO_DOLA_BROWSER_UI_ACCOUNT": "daily"}):
            self.service.preflight_dola_opening("prj_dola", slot_id="OPENING_O1", account_id="daily")
            refreshed = Mock(profile_binding="b" * 64)
            with patch.object(self.service, "_dola_browser_client",
                              side_effect=[self.client, self.client, refreshed]):
                with patch("story_auto.providers.dola_cookie.opening.generate_dola_opening") as generate:
                    with self.assertRaisesRegex(DolaCookieError, "COOKIE_CHANGED_BEFORE_DISPATCH"):
                        self.service.generate_dola_opening("prj_dola", slot_id="OPENING_O1",
                                                           account_id="daily", confirm_generate=True)
                    generate.assert_not_called()
            self.assertFalse((self.service.opening_builder("prj_dola")["slots"][0]
                              .get("api_generation")))

    def test_only_proven_unsent_attempt_can_be_rechecked(self):
        with patch.dict(os.environ, {"STORY_AUTO_DOLA_BROWSER_UI_ENABLED": "1",
                                     "STORY_AUTO_DOLA_BROWSER_UI_PROJECT": "prj_dola",
                                     "STORY_AUTO_DOLA_BROWSER_UI_ACCOUNT": "daily"}):
            slot = {"slot_id": "OPENING_O1", "duration_seconds": 5,
                    "api_generation": {"provider": "dola_cookie", "account_id": "daily",
                                       "status": "FAILED_PRE_DISPATCH", "dispatch_state": "NOT_DISPATCHED",
                                       "provider_submissions": 0}}
            with patch.object(self.service, "opening_builder", return_value={"slots": [slot]}):
                self.assertTrue(self.service.preflight_dola_opening(
                    "prj_dola", slot_id="OPENING_O1", account_id="daily")["generation_enabled"])
                slot["api_generation"].update(status="AMBIGUOUS", dispatch_state="AMBIGUOUS")
                with self.assertRaisesRegex(OperatorServiceError, "SLOT_INVALID"):
                    self.service.preflight_dola_opening("prj_dola", slot_id="OPENING_O1",
                                                        account_id="daily")


if __name__ == "__main__":
    unittest.main()
