from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.byteplus_seedance.client import BytePlusSeedanceClient, BytePlusSeedanceError, DEFAULT_MODEL
from story_auto.providers.byteplus_seedance.service import execute_seedance_generation


class _FakeSeedance:
    provider = "byteplus_seedance"
    model = DEFAULT_MODEL

    def __init__(self, *, ambiguous: bool = False, task_status: str = "succeeded"):
        self.ambiguous = ambiguous
        self.task_status = task_status
        self.create_calls = 0
        self.get_calls = 0
        self.acquire_calls = 0

    def readiness(self):
        return {"status": "READY", "model": self.model}

    def create_task(self, **_kwargs):
        self.create_calls += 1
        if self.ambiguous:
            raise BytePlusSeedanceError("AMBIGUOUS_POST_DISPATCH", dispatch_state="AMBIGUOUS")
        return "cgt-stable-001"

    def get_task(self, task_id):
        self.get_calls += 1
        self.last_task_id = task_id
        return {"id": task_id, "status": self.task_status, "content": {"video_url": "https://example.invalid/result.mp4"},
                "usage": {"completion_tokens": 1234}}

    def acquire_video(self, _task, destination: Path):
        self.acquire_calls += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"provider-video-fixture")
        return {"duration_seconds": 5.0, "width": 1280, "height": 720, "codec": "h264",
                "container": "mp4", "audio_present": False, "sha256": "a" * 64, "download_bytes": 22}


class BytePlusSeedanceTests(unittest.TestCase):
    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        paths = create_project(runtime, ProjectConfig("prj_seedance", render_mode="full_video_ai", settings={"qc_policy": "MANUAL_REVIEW"}),
                               "# Seedance\n\n## Narration\n\nA short stable provider fixture.\n")
        request = {
            "request_id": "req_video_001", "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "VIDEO",
            "requirement": "REQUIRED", "provider": "byteplus_seedance", "prompt": "A calm tracking shot.",
            "target_duration": 5.0, "aspect_ratio": "16:9", "fingerprint": "f" * 64,
        }
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {
            "schema_version": "story-auto-generation-requests/1.0.0", "project_id": "prj_seedance", "requests": [request]
        })
        return runtime, paths, request

    def test_client_create_task_uses_direct_async_contract(self):
        calls = []
        def transport(url, method, body, key, timeout):
            calls.append((url, method, body, key, timeout))
            return {"id": "cgt-123"}, 200
        client = BytePlusSeedanceClient(key="secret-test-key", transport=transport)
        task_id = client.create_task(prompt="A slow push in.", duration=5, aspect_ratio="16:9", resolution="720p")
        self.assertEqual(task_id, "cgt-123")
        url, method, body, key, _timeout = calls[0]
        self.assertTrue(url.endswith("/contents/generations/tasks"))
        self.assertEqual((method, key, body["model"], body["generate_audio"], body["watermark"]),
                         ("POST", "secret-test-key", DEFAULT_MODEL, False, False))
        self.assertEqual((body["duration"], body["resolution"], body["ratio"]), (5, "720p", "16:9"))

    def test_success_persists_task_identity_before_selected_asset(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _request = self._project(root)
            client = _FakeSeedance()
            result = execute_seedance_generation(root, "prj_seedance", client=client, poll_interval=.01, max_poll_seconds=.1)
            self.assertEqual((result["status"], result["new_submissions"], result["completed_assets"]),
                             ("READY_FOR_QUALITY", 1, 1))
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt = entry["attempts"][0]
            self.assertEqual((entry["status"], entry["provider"], attempt["provider_job_id"]),
                             ("QC_PENDING", "byteplus_seedance", "cgt-stable-001"))
            self.assertTrue(attempt["dispatch_confirmed"])
            self.assertEqual(attempt["attribution_state"], "CONFIRMED")
            self.assertEqual(entry["selected_asset"]["production_qc"], "PENDING")
            self.assertNotIn("video_url", str(entry))

    def test_ambiguous_post_is_never_blindly_resubmitted(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _request = self._project(root)
            client = _FakeSeedance(ambiguous=True)
            first = execute_seedance_generation(root, "prj_seedance", client=client, poll_interval=.01, max_poll_seconds=.1)
            second = execute_seedance_generation(root, "prj_seedance", client=client, poll_interval=.01, max_poll_seconds=.1)
            self.assertTrue(first["blocked"] and second["blocked"])
            self.assertEqual(client.create_calls, 1)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((entry["status"], entry["failure_class"]), ("AMBIGUOUS", "AMBIGUOUS_POST_DISPATCH"))
            self.assertNotIn("provider_job_id", entry["attempts"][0])

    def test_known_task_resumes_by_poll_without_new_post(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, request = self._project(root)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": "prj_seedance", "requests": [{
                    "request_id": request["request_id"], "request_identity_sha256": request["fingerprint"],
                    "related_identity": request["shot_id"], "media_type": "VIDEO", "provider": "byteplus_seedance",
                    "status": "GENERATING", "provider_submissions": 1, "attempts": [{
                        "attempt": 1, "status": "SUBMITTED", "provider_job_id": "cgt-existing-777",
                        "dispatch_confirmed": True, "attribution_state": "CONFIRMED", "attribution_status": "CONFIRMED",
                        "provider_execution_state": "RUNNING",
                    }]
                }]
            })
            client = _FakeSeedance()
            result = execute_seedance_generation(root, "prj_seedance", client=client, poll_interval=.01, max_poll_seconds=.1)
            self.assertEqual((client.create_calls, client.get_calls, client.last_task_id), (0, 1, "cgt-existing-777"))
            self.assertEqual((result["resumed_tasks"], result["completed_assets"]), (1, 1))

    def test_completed_asset_is_reused_without_provider_call(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _request = self._project(root)
            client = _FakeSeedance()
            execute_seedance_generation(root, "prj_seedance", client=client, poll_interval=.01, max_poll_seconds=.1)
            with patch("story_auto.providers.byteplus_seedance.service.validate_video", return_value={"sha256": "a" * 64}):
                second = execute_seedance_generation(root, "prj_seedance", client=client, poll_interval=.01, max_poll_seconds=.1)
            self.assertEqual(second["new_submissions"], 0)
            self.assertEqual(client.create_calls, 1)
            self.assertEqual(client.acquire_calls, 1)


if __name__ == "__main__":
    unittest.main()
