from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

from story_auto.core.artifacts import read_json
from story_auto.core.project import RuntimeLayout, ProjectConfig, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder
from story_auto.providers.dola_cookie.client import DolaCookieClient, DolaCookieError
from story_auto.providers.dola_cookie.opening import generate_dola_opening


class FakeDola:
    def __init__(self, *, crash=None, pending=False):
        self.submits = 0
        self.downloads = 0
        self.crash = crash
        self.pending = pending
        self.polled = []

    def submit(self, *, on_receipt, **params):
        self.submits += 1
        self.params = params
        if self.crash == "before_receipt":
            raise DolaCookieError("AMBIGUOUS", "AMBIGUOUS")
        if self.crash == "http_404":
            raise DolaCookieError("AMBIGUOUS", "AMBIGUOUS", http_status=404)
        on_receipt("conversation-fixture")
        if self.crash == "after_receipt":
            raise ConnectionError("fixture private diagnostic")
        return "conversation-fixture"

    def poll(self, task, *, client_request_id=None):
        self.polled.append(task)
        return {"status": "PENDING"} if self.pending else {"status": "COMPLETED", "video_url": "https://fixture.invalid/video"}

    def download(self, url, destination):
        self.downloads += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=navy:s=320x180:r=24:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(destination)], check=True)


class DolaOpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        runtime = RuntimeLayout.from_root(self.root).ensure()
        self.paths = create_project(runtime, ProjectConfig("prj_dola", render_mode="hybrid_hook", settings={
            "render": {"width": 320, "height": 180, "fps": 24, "pixel_format": "yuv420p"},
            "hybrid_visual": {"opening_provider_policy": "DOLA"}}))
        configure_opening_builder(self.root, "prj_dola", shared_context="A dawn journey", slot_specs=[
            {"duration_seconds": 6, "purpose": "Hook", "prompt": "Sun over the mountains"},
            {"duration_seconds": 6, "purpose": "Develop", "prompt": "The traveller walks"},
            {"duration_seconds": 6, "purpose": "Transition", "prompt": "Sun over the valley"}])

    def run_slot(self, client, account="daily"):
        return generate_dola_opening(self.root, "prj_dola", "OPENING_O1", account_id=account, client=client)

    def test_composed_receipt_download_normalize_and_repeat(self):
        client = FakeDola()
        result = self.run_slot(client)
        slot = result["slots"][0]
        self.assertTrue(slot["asset_ready"])
        self.assertEqual(slot["api_generation"]["status"], "SUCCEEDED")
        self.assertEqual(slot["source_asset"]["provider"], "dola_cookie")
        self.assertEqual(slot["source_asset"]["provider_account_id"], "daily")
        self.assertEqual(client.params["duration"], 10)
        self.assertAlmostEqual(slot["normalized_asset"]["duration_seconds"], 6, places=1)
        self.run_slot(client)
        self.assertEqual((client.submits, client.downloads), (1, 1))

    def test_missing_receipt_cannot_repeat_or_switch_account(self):
        client = FakeDola(crash="before_receipt")
        self.assertEqual(self.run_slot(client)["slots"][0]["api_generation"]["status"], "AMBIGUOUS")
        self.run_slot(client)
        with self.assertRaisesRegex(DolaCookieError, "ACCOUNT_MISMATCH"):
            self.run_slot(client, "another")
        self.assertEqual(client.submits, 1)

    def test_http_failure_preserves_safe_status_and_never_resubmits(self):
        client = FakeDola(crash="http_404")
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual((first["status"], first["dispatch_state"]), ("AMBIGUOUS", "AMBIGUOUS"))
        self.assertEqual(first["submission_http_status"], 404)
        self.run_slot(client)
        self.assertEqual(client.submits, 1)
        raw = self.paths.artifact_path("output/opening_manifest.json").read_text()
        self.assertNotIn("private diagnostic", raw)

    def test_real_client_http_failure_flows_to_manifest_without_retry(self):
        from urllib.error import HTTPError
        requests = []
        def reject(request, timeout):
            requests.append(request.get_method())
            raise HTTPError("https://www.dola.com/chat/completion", 404, "private", {}, None)
        client = DolaCookieClient("sessionid_ss=fixture", opener=reject)
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual(first["submission_http_status"], 404)
        self.assertEqual((first["status"], first["dispatch_state"]), ("AMBIGUOUS", "AMBIGUOUS"))
        self.run_slot(client)
        self.assertEqual(requests, ["POST"])
        raw = self.paths.artifact_path("output/opening_manifest.json").read_text()
        self.assertNotIn("private", raw)

    def test_receipt_survives_client_crash_and_fresh_client_resumes(self):
        client = FakeDola(crash="after_receipt")
        first = self.run_slot(client)
        self.assertEqual(first["slots"][0]["api_generation"]["status"], "SUBMITTED")
        fresh = FakeDola()
        result = self.run_slot(fresh)
        self.assertTrue(result["slots"][0]["asset_ready"])
        self.assertEqual(fresh.submits, 0)
        self.assertEqual(fresh.polled, ["conversation-fixture"])
        self.assertEqual(result["slots"][0]["api_generation"]["provider_submissions"], 1)
        raw = self.paths.artifact_path("output/opening_manifest.json").read_text()
        self.assertNotIn("fixture.invalid", raw)
        self.assertNotIn("private diagnostic", raw)

    def test_pending_is_resumed_with_same_conversation(self):
        pending = FakeDola(pending=True)
        self.assertEqual(self.run_slot(pending)["slots"][0]["api_generation"]["status"], "GENERATING")
        fresh = FakeDola(pending=True)
        self.run_slot(fresh)
        self.assertEqual(fresh.submits, 0)
        self.assertEqual(fresh.polled, ["conversation-fixture"])

    def test_expired_cookie_before_submit_allows_explicit_same_account_retry(self):
        class Expired(FakeDola):
            def submit(self, **params):
                self.submits += 1
                raise DolaCookieError("CREDENTIAL_OR_ACCESS_DENIED", "NOT_DISPATCHED")
        expired = Expired()
        self.assertEqual(self.run_slot(expired)["slots"][0]["api_generation"]["status"], "FAILED_PRE_DISPATCH")
        fresh = FakeDola(pending=True)
        result = self.run_slot(fresh)
        self.assertEqual(fresh.submits, 1)
        self.assertEqual(result["slots"][0]["api_generation"]["provider_submissions"], 1)
        self.assertEqual(result["slots"][0]["api_generation"]["submit_attempts"], 2)

    def test_three_sequential_slots_are_distinct_local_attempts(self):
        for index in range(1, 4):
            result = generate_dola_opening(self.root, "prj_dola", f"OPENING_O{index}", account_id="daily", client=FakeDola())
        self.assertTrue(result["ready"])
        manifest = read_json(self.paths.artifact_path("output/opening_manifest.json"))
        self.assertEqual(len({s["api_generation"]["attempt_id"] for s in manifest["slots"]}), 3)
        self.assertTrue(all(s["api_generation"]["provider_submissions"] == 1 for s in manifest["slots"]))
