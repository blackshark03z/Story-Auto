from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_auto.core.artifacts import read_json
from story_auto.providers.elyum_seedance import (
    ElyumSeedanceClient,
    ElyumSeedanceError,
    keep_experiment_preview,
    kill_experiment_preview,
    prepare_reference_upload,
    run_experiment_preview,
)


class _FakeSession:
    def __init__(self, *, make_error: ElyumSeedanceError | None = None):
        self.calls = []
        self.make_error = make_error
        self.make_calls = 0

    def call_tool(self, name, arguments=None):
        arguments = dict(arguments or {})
        self.calls.append((name, arguments))
        if name == "elyum_account":
            return {"plan": "Free", "balance": 150, "killsLeft": 1}
        if name == "elyum_estimate":
            return {"credits": 44, "model": arguments.get("model")}
        if name == "elyum_upload":
            return {"url": "/media/reference-fixture.png"}
        if name == "elyum_make_video":
            self.make_calls += 1
            if self.make_error is not None:
                raise self.make_error
            return {"jobId": "gen_job_001", "heldCredits": 44}
        if name == "elyum_wait":
            return {"status": "succeeded", "genId": "gen_result_001", "thumbnailUrl": "https://elyum.ai/media/preview.jpg"}
        if name == "elyum_job_status":
            return {"status": "running", "jobId": arguments.get("jobId")}
        if name == "elyum_keep":
            return {"status": "kept", "videoUrl": "https://elyum.ai/media/final.mp4"}
        if name == "elyum_kill":
            return {"status": "killed"}
        raise AssertionError(name)


class ElyumSeedanceClientTests(unittest.TestCase):
    def test_estimate_uses_explicit_i2v_mode(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        credits = client.estimate_video(model="seedance-2-fast-i2v", duration=4, mode="i2v")
        self.assertEqual(credits, 44)
        self.assertEqual(session.calls[0], ("elyum_estimate", {
            "kind": "video", "mode": "i2v", "model": "seedance-2-fast-i2v", "duration": 4,
        }))

    def test_upload_file_encodes_local_reference_and_returns_absolute_media_url(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            image = Path(root) / "fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            url = client.upload_file(image)
        self.assertEqual(url, "https://elyum.ai/media/reference-fixture.png")
        name, args = session.calls[0]
        self.assertEqual(name, "elyum_upload")
        self.assertEqual((args["filename"], args["mimeType"]), ("fixture.png", "image/png"))
        self.assertTrue(args["base64"])

    def test_make_video_uses_idempotent_client_ref_and_disables_provider_audio(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        job_id, _ = client.make_video(
            client_ref="story-auto-g54-abc", model="seedance-2-fast-i2v", prompt="Slow push in.",
            image_url="https://elyum.ai/media/ref.png", duration=4, resolution="480p", audio=False,
        )
        self.assertEqual(job_id, "gen_job_001")
        name, args = session.calls[0]
        self.assertEqual(name, "elyum_make_video")
        self.assertEqual(args["clientRef"], "story-auto-g54-abc")
        self.assertEqual((args["mode"], args["resolution"], args["audio"]), ("i2v", "480p", False))


class ElyumResearchLedgerTests(unittest.TestCase):
    def test_reference_upload_is_reused_by_hash(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "ledger.json"
            image = Path(root) / "fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            first = prepare_reference_upload(ledger, recipe_id="R1", reference_path=image, client=client)
            second = prepare_reference_upload(ledger, recipe_id="R1", reference_path=image, client=client)
        self.assertEqual((first["status"], second["status"]), ("UPLOADED", "REUSED"))
        self.assertEqual([name for name, _ in session.calls].count("elyum_upload"), 1)

    def test_client_ref_is_persisted_before_dispatch_and_preview_does_not_auto_keep(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "ledger.json"
            result = run_experiment_preview(
                ledger, recipe_id="R1", prompt="Slow push in.", reference_url="https://elyum.ai/media/ref.png",
                client=client, model="seedance-2-fast-i2v", max_credits=44,
            )
            stored = read_json(ledger)["experiments"]["R1"]
        self.assertEqual(result["status"], "PREVIEW_READY")
        self.assertTrue(stored["client_ref"].startswith("story-auto-g54-"))
        self.assertEqual((stored["job_id"], stored["gen_id"], stored["estimate_credits"]),
                         ("gen_job_001", "gen_result_001", 44))
        names = [name for name, _ in session.calls]
        self.assertEqual(names, ["elyum_account", "elyum_estimate", "elyum_make_video", "elyum_wait"])
        self.assertNotIn("elyum_keep", names)
        self.assertNotIn("elyum_kill", names)

    def test_uncertain_dispatch_replays_same_client_ref_on_next_call(self):
        error = ElyumSeedanceError("PROVIDER_TRANSIENT")
        session = _FakeSession(make_error=error)
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "ledger.json"
            first = run_experiment_preview(
                ledger, recipe_id="R1", prompt="Slow push in.", reference_url="https://elyum.ai/media/ref.png",
                client=client, model="seedance-2-fast-i2v", max_credits=44,
            )
            ref1 = read_json(ledger)["experiments"]["R1"]["client_ref"]
            session.make_error = None
            second = run_experiment_preview(
                ledger, recipe_id="R1", prompt="Slow push in.", reference_url="https://elyum.ai/media/ref.png",
                client=client, model="seedance-2-fast-i2v", max_credits=44,
            )
            ref2 = read_json(ledger)["experiments"]["R1"]["client_ref"]
        self.assertEqual(first["status"], "REPLAY_SAME_CLIENT_REF")
        self.assertEqual(second["status"], "PREVIEW_READY")
        self.assertEqual(ref1, ref2)
        make_args = [args for name, args in session.calls if name == "elyum_make_video"]
        self.assertEqual(len(make_args), 2)
        self.assertEqual(make_args[0]["clientRef"], make_args[1]["clientRef"])

    def test_known_job_resumes_wait_without_new_make(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "ledger.json"
            first = run_experiment_preview(
                ledger, recipe_id="R1", prompt="Slow push in.", reference_url="https://elyum.ai/media/ref.png",
                client=client, model="seedance-2-fast-i2v", max_credits=44,
            )
            session.calls.clear()
            second = run_experiment_preview(
                ledger, recipe_id="R1", prompt="Slow push in.", reference_url="https://elyum.ai/media/ref.png",
                client=client, model="seedance-2-fast-i2v", max_credits=44,
            )
        self.assertEqual((first["status"], second["status"]), ("PREVIEW_READY", "PREVIEW_READY"))
        self.assertEqual([name for name, _ in session.calls], ["elyum_wait"])

    def test_cost_bound_blocks_before_make_video(self):
        session = _FakeSession()
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            result = run_experiment_preview(
                Path(root) / "ledger.json", recipe_id="R1", prompt="Slow push in.",
                reference_url="https://elyum.ai/media/ref.png", client=client,
                model="seedance-2-fast-i2v", max_credits=43,
            )
        self.assertEqual(result["status"], "BLOCKED_COST")
        self.assertEqual([name for name, _ in session.calls], ["elyum_account", "elyum_estimate"])

    def test_insufficient_live_balance_blocks_before_make_video(self):
        session = _FakeSession()
        original = session.call_tool
        def low_balance(name, arguments=None):
            if name == "elyum_account":
                session.calls.append((name, dict(arguments or {})))
                return {"balance": 20, "plan": "Free"}
            return original(name, arguments)
        session.call_tool = low_balance
        client = ElyumSeedanceClient(key="test", session=session)
        with tempfile.TemporaryDirectory() as root:
            result = run_experiment_preview(
                Path(root) / "ledger.json", recipe_id="R1", prompt="Slow push in.",
                reference_url="https://elyum.ai/media/ref.png", client=client,
                model="seedance-2-fast-i2v", max_credits=44,
            )
        self.assertEqual(result["status"], "BLOCKED_BALANCE")
        self.assertEqual([name for name, _ in session.calls], ["elyum_account", "elyum_estimate"])

    def test_keep_and_kill_are_explicit_separate_operations(self):
        for decision in ("keep", "kill"):
            session = _FakeSession()
            client = ElyumSeedanceClient(key="test", session=session)
            with tempfile.TemporaryDirectory() as root:
                ledger = Path(root) / "ledger.json"
                run_experiment_preview(
                    ledger, recipe_id="R1", prompt="Slow push in.", reference_url="https://elyum.ai/media/ref.png",
                    client=client, model="seedance-2-fast-i2v", max_credits=44,
                )
                session.calls.clear()
                if decision == "keep":
                    result = keep_experiment_preview(ledger, recipe_id="R1", client=client)
                    self.assertEqual(result["status"], "KEPT")
                    self.assertEqual([name for name, _ in session.calls], ["elyum_keep"])
                else:
                    result = kill_experiment_preview(ledger, recipe_id="R1", client=client, reason="identity_drift")
                    self.assertEqual(result["status"], "KILLED")
                    self.assertEqual([name for name, _ in session.calls], ["elyum_kill"])


if __name__ == "__main__":
    unittest.main()
