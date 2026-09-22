from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from story_auto.application import OperatorService
from story_auto.core.artifacts import read_json
from story_auto.providers.tts.kokoro_local import KokoroReadiness


class StableReadinessTests(unittest.TestCase):
    def test_gemini_configuration_does_not_claim_live_readiness(self):
        for configured in (False, True):
            with self.subTest(configured=configured), tempfile.TemporaryDirectory() as root:
                app = OperatorService(root)
                credential = {"configured": configured, "count": int(configured),
                              "source": "TEST", "removable": False}
                with patch("story_auto.application.operator.provider_key_status", return_value=credential):
                    overview = app.settings_overview()
                brain = next(row for row in overview["providers"] if row["name"] == "AI brain")
                self.assertEqual(brain["status"], "Configured" if configured else "Not configured")
                self.assertFalse(brain["live_verified"])

    def test_transport_failure_after_local_create_returns_saved_project(self):
        class OfflineProjects:
            def find_projects(self, name):
                raise ConnectionError("transport unavailable")

        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root, auto_flow_projects=True, flow_projects=OfflineProjects())
            with patch("story_auto.application.operator.KokoroLocalProvider.readiness",
                       return_value=KokoroReadiness("READY", "ready", None)):
                created = app.create_project(project_id="prj_saved_transport",
                                             content="# Saved story\n\n## Narration\n\nKeep this work.\n")
            self.assertEqual(created["project_id"], "prj_saved_transport")
            self.assertEqual(created["flow_setup"]["state"], "CREATE_INTENT")
            paths, _ = app._project(created["project_id"])
            binding = read_json(paths.project_file)["settings"]["provider_binding"]["flow"]
            self.assertEqual(binding["last_setup_failure"], "ConnectionError")
            self.assertEqual(binding["activation_state"], "NOT_ATTEMPTED")
            self.assertEqual(len(list(app.runtime.projects.iterdir())), 1)
