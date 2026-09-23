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
from story_auto.application import OperatorService


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
        if self.crash == "read_diagnostic":
            raise DolaCookieError("DOLA_UI_RESULT_IDENTITY_UNVERIFIED", "AMBIGUOUS",
                                  read_diagnostic="DOLA_RESULT_IDENTITY_MISMATCH|DOLA_READ_TIMEOUT")
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

    def test_linked_master_variant_is_recorded_with_canonical_import(self):
        class MasterDola(FakeDola):
            def poll(self, task, *, client_request_id=None):
                result = super().poll(task, client_request_id=client_request_id)
                if result["status"] == "COMPLETED":
                    result["media_variant"] = "master"
                return result

        slot = self.run_slot(MasterDola())["slots"][0]
        self.assertEqual(slot["api_generation"]["media_variant"], "master")
        self.assertEqual(slot["source_asset"]["provider"], "dola_cookie")

    def test_recovery_does_not_relabel_old_preview_as_master(self):
        class MasterDola(FakeDola):
            def poll(self, task, *, client_request_id=None):
                result = super().poll(task, client_request_id=client_request_id)
                if result["status"] == "COMPLETED":
                    result["media_variant"] = "master"
                return result

        client = MasterDola(pending=True)
        first = self.run_slot(client)["slots"][0]["api_generation"]
        legacy = self.paths.artifact_path(f"assets/opening/dola/{first['attempt_id']}.mp4")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"old-preview-fixture")
        client.pending = False
        slot = self.run_slot(client)["slots"][0]
        self.assertEqual(client.submits, 1)
        self.assertEqual(client.downloads, 1)
        self.assertEqual(slot["api_generation"]["media_variant"], "master")
        self.assertEqual(slot["api_generation"]["acquired_sha256"], slot["source_asset"]["sha256"])
        self.assertTrue(self.paths.artifact_path(
            f"assets/opening/dola/{first['attempt_id']}-master.mp4").is_file())
        self.assertEqual(legacy.read_bytes(), b"old-preview-fixture")

    def test_missing_receipt_cannot_repeat_or_switch_account(self):
        client = FakeDola(crash="before_receipt")
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual(first["status"], "AMBIGUOUS")
        self.assertEqual(first["submission_diagnostic"], "AMBIGUOUS")
        self.run_slot(client)
        with self.assertRaisesRegex(DolaCookieError, "ACCOUNT_MISMATCH"):
            self.run_slot(client, "another")
        self.assertEqual(client.submits, 1)

    def test_ambiguous_read_diagnostic_is_saved_without_a_receipt(self):
        client = FakeDola(crash="read_diagnostic")
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual(first["status"], "AMBIGUOUS")
        self.assertEqual(first["submission_diagnostic"],
                         "DOLA_UI_RESULT_IDENTITY_UNVERIFIED")
        self.assertEqual(first["submission_read_diagnostic"],
                         "DOLA_RESULT_IDENTITY_MISMATCH|DOLA_READ_TIMEOUT")
        self.assertFalse(first.get("provider_task_id"))
        self.run_slot(client)
        self.assertEqual(client.submits, 1)

    def test_browser_ui_persists_native_request_mapping_before_receipt(self):
        class BrowserClient(FakeDola):
            transport = "browser_ui"
            profile_binding = "a" * 64
            def submit(self, *, on_native_request, on_receipt, **params):
                self.submits += 1
                on_native_request("native-1")
                on_receipt("conversation-fixture")
                return "conversation-fixture"
            def poll(self, task, *, client_request_id=None):
                self.polled.append((task, client_request_id))
                return {"status": "PENDING"}
        client = BrowserClient()
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual(first["transport"], "browser_ui")
        self.assertEqual(first["profile_binding"], "a" * 64)
        self.assertEqual(first["provider_local_message_id"], "native-1")
        self.assertEqual(client.polled, [("conversation-fixture", "native-1")])
        self.assertEqual(client.submits, 1)
        fresh = BrowserClient()
        self.run_slot(fresh)
        self.assertEqual(fresh.submits, 0)
        self.assertEqual(fresh.polled, [("conversation-fixture", "native-1")])

    def test_browser_ui_missing_native_id_never_confirms_receipt_or_resends(self):
        class MissingNative(FakeDola):
            transport = "browser_ui"
            profile_binding = "b" * 64
            def submit(self, *, on_receipt, **params):
                self.submits += 1
                on_receipt("conversation-fixture")
                return "conversation-fixture"
        client = MissingNative()
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual(first["status"], "AMBIGUOUS")
        self.assertFalse(first.get("provider_task_id"))
        self.run_slot(client)
        self.assertEqual(client.submits, 1)

    def test_browser_ui_unreceipted_attempt_cannot_change_transport_or_profile(self):
        class UnreceiptedBrowser(FakeDola):
            transport = "browser_ui"
            profile_binding = "c" * 64
            def submit(self, *, on_native_request, **params):
                self.submits += 1
                on_native_request("native-1")
                raise DolaCookieError("NO_RECEIPT", "AMBIGUOUS")
        browser = UnreceiptedBrowser()
        first = self.run_slot(browser)["slots"][0]["api_generation"]
        self.assertEqual((first["status"], first["submission_diagnostic"]),
                         ("AMBIGUOUS", "NO_RECEIPT"))
        direct = FakeDola()
        with self.assertRaisesRegex(DolaCookieError, "TRANSPORT_MISMATCH"):
            self.run_slot(direct)
        browser.profile_binding = "d" * 64
        with self.assertRaisesRegex(DolaCookieError, "PROFILE_BINDING_MISMATCH"):
            self.run_slot(browser)
        self.assertEqual((browser.submits, direct.submits), (1, 0))

    def test_browser_ui_known_unsent_can_rebind_refreshed_cookie_with_history(self):
        class UnsentBrowser(FakeDola):
            transport = "browser_ui"
            profile_binding = "a" * 64
            def submit(self, **params):
                self.submits += 1
                raise DolaCookieError("SESSION_EXPIRED", "NOT_DISPATCHED")

        class RefreshedBrowser(FakeDola):
            transport = "browser_ui"
            profile_binding = "b" * 64
            def submit(self, *, on_native_request, on_receipt, **params):
                self.submits += 1
                on_native_request("native-refreshed")
                on_receipt("conversation-fixture")
                return "conversation-fixture"
            def poll(self, task, *, client_request_id=None):
                return {"status": "PENDING"}

        first = UnsentBrowser()
        initial = self.run_slot(first)["slots"][0]["api_generation"]
        self.assertEqual((initial["status"], initial["dispatch_state"]),
                         ("FAILED_PRE_DISPATCH", "NOT_DISPATCHED"))
        refreshed = RefreshedBrowser()
        result = self.run_slot(refreshed)["slots"][0]["api_generation"]
        self.assertEqual((first.submits, refreshed.submits), (1, 1))
        self.assertEqual(result["profile_binding"], "b" * 64)
        self.assertEqual(result["previous_profile_bindings"], ["a" * 64])
        self.assertEqual((result["provider_submissions"], result["submit_attempts"]), (1, 2))

    def test_unverified_application_session_cannot_create_a_dola_attempt(self):
        client = FakeDola()
        with self.assertRaisesRegex(DolaCookieError, "DOLA_SESSION_NOT_VERIFIED"):
            generate_dola_opening(self.root, "prj_dola", "OPENING_O1", account_id="daily",
                                  client=client, allow_new_submission=False)
        self.assertEqual(client.submits, 0)
        manifest = read_json(self.paths.artifact_path("output/opening_manifest.json"))
        self.assertFalse(manifest["slots"][0].get("api_generation"))
        with self.assertRaisesRegex(DolaCookieError, "DOLA_SESSION_NOT_VERIFIED"):
            OperatorService(self.root).generate_dola_opening("prj_dola", slot_id="OPENING_O1", account_id="daily")
        self.assertEqual(client.submits, 0)

    def test_unverified_gate_still_allows_poll_only_confirmed_recovery(self):
        first = FakeDola(pending=True)
        self.run_slot(first)
        recovery = FakeDola(pending=True)
        generate_dola_opening(self.root, "prj_dola", "OPENING_O1", account_id="daily",
                              client=recovery, allow_new_submission=False)
        self.assertEqual((first.submits, recovery.submits), (1, 0))
        self.assertEqual(recovery.polled, ["conversation-fixture"])

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

    def test_missing_receipt_persists_only_safe_response_diagnostics(self):
        from io import BytesIO
        class Response:
            status = 200
            headers = {"Content-Type": "application/json; charset=utf-8"}
            def __init__(self): self.body = BytesIO(b'{"error":"private-secret"}')
            def read(self, amount=-1): return self.body.read(amount)
            def __enter__(self): return self
            def __exit__(self, *args): return None
        requests = []
        def respond(request, timeout):
            requests.append(request.get_method())
            return Response()
        client = DolaCookieClient("sessionid_ss=fixture", opener=respond)
        first = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual((first["submission_http_status"], first["submission_response_kind"],
                          first["submission_receipt_state"]), (200, "JSON", "NO_ACK"))
        self.run_slot(client)
        self.assertEqual(requests, ["POST"])
        self.assertNotIn("private-secret", self.paths.artifact_path("output/opening_manifest.json").read_text())

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

    def test_duration_question_waits_for_operator_without_a_second_submit(self):
        class NeedsOperator(FakeDola):
            def poll(self, task, *, client_request_id=None):
                self.polled.append(task)
                return {"status": "NEEDS_OPERATOR", "reason": "DOLA_DURATION_CONFIRMATION_REQUIRED"}

        client = NeedsOperator()
        generation = self.run_slot(client)["slots"][0]["api_generation"]
        self.assertEqual(generation["status"], "OPERATOR_DECISION_REQUIRED")
        self.assertEqual(generation["failure_class"], "DOLA_DURATION_CONFIRMATION_REQUIRED")
        self.assertEqual((generation["submit_attempts"], generation["provider_submissions"]), (1, 1))
        fresh = NeedsOperator()
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
