"""Interruption and replacement probes for the real Opening acquisition boundary."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from story_auto.core.artifacts import read_json, atomic_write_json
from story_auto.core.visual.opening_builder import (
    configure_opening_builder, import_opening_clip, OpeningBuilderError,
)
from story_auto.providers.byteplus_seedance.opening import generate_opening_slot_api
from story_auto.providers.elyum_seedance.opening import (
    generate_elyum_opening_preview, review_elyum_opening_preview,
    keep_elyum_opening_preview,
)
from tests import test_hybrid_opening_api as byteplus_fixture
from tests import test_hybrid_opening_elyum as elyum_fixture
from tests.test_hybrid_opening_api import _FakeOpeningClient
from tests.test_hybrid_opening_elyum import FakeElyum, MODEL, _video


class OpeningRecoveryTests(unittest.TestCase):
    def test_acquired_asset_identity_survives_adapter_exit_before_final_save(self):
        with tempfile.TemporaryDirectory() as root:
            _, paths = byteplus_fixture.HybridOpeningApiTests()._project(root)
            client = _FakeOpeningClient(root, "prj_h3")

            def stop_after_import(*args, **kwargs):
                import_opening_clip(*args, **kwargs)
                raise KeyboardInterrupt("adapter exited after acquisition commit")

            with patch("story_auto.providers.byteplus_seedance.opening.import_opening_clip", side_effect=stop_after_import):
                with self.assertRaises(KeyboardInterrupt):
                    generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client)
            slot = read_json(paths.artifact_path("output/opening_manifest.json"))["slots"][0]
            self.assertEqual(slot["api_generation"]["status"], "SUCCEEDED")
            self.assertEqual(slot["source_asset"]["provider_task_id"], "opening-task-001")
            resumed = generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client)
            self.assertTrue(resumed["slots"][0]["asset_ready"])
            self.assertEqual((client.create_calls, client.acquire_calls), (1,1))

    def test_byteplus_process_interruption_after_post_does_not_repeat_post(self):
        with tempfile.TemporaryDirectory() as root:
            byteplus_fixture.HybridOpeningApiTests()._project(root)
            client = _FakeOpeningClient(root, "prj_h3", task_status="running")
            original_create = client.create_task

            def interrupted(**kwargs):
                original_create(**kwargs)
                raise KeyboardInterrupt("process ended before task id was saved")

            with patch.object(client, "create_task", side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client)
            resumed = generate_opening_slot_api(root, "prj_h3", "OPENING_O1", client=client, max_poll_seconds=0)
            self.assertEqual(client.create_calls, 1)
            self.assertEqual(resumed["slots"][0]["api_generation"]["status"], "AMBIGUOUS")

    def test_manual_import_cannot_hide_unresolved_provider_effect(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = byteplus_fixture.HybridOpeningApiTests()._project(root)
            source = runtime.temp / "manual.mp4"
            _video(source)
            manifest_path = paths.artifact_path("output/opening_manifest.json")
            for provider, status in [("byteplus_seedance", "AMBIGUOUS"), ("byteplus_seedance", "SUBMITTED"),
                                     ("elyum_seedance", "PREVIEW_READY"), ("elyum_seedance", "KEEP_AMBIGUOUS")]:
                with self.subTest(provider=provider, status=status):
                    manifest = read_json(manifest_path)
                    manifest["slots"][0]["api_generation"] = {"provider": provider, "status": status}
                    atomic_write_json(manifest_path, manifest)
                    before = manifest_path.read_bytes()
                    with self.assertRaisesRegex(OpeningBuilderError, "OPENING_PROVIDER_EFFECT_UNRESOLVED"):
                        import_opening_clip(root, "prj_h3", "OPENING_O1", source)
                    self.assertEqual(manifest_path.read_bytes(), before)

    def test_replan_cannot_erase_unresolved_provider_effect(self):
        with tempfile.TemporaryDirectory() as root:
            _, paths = byteplus_fixture.HybridOpeningApiTests()._project(root)
            manifest_path = paths.artifact_path("output/opening_manifest.json")
            manifest = read_json(manifest_path)
            manifest["slots"][0]["api_generation"] = {"provider": "elyum_seedance", "status": "PREVIEW_READY"}
            atomic_write_json(manifest_path, manifest)
            before = manifest_path.read_bytes()
            with self.assertRaisesRegex(OpeningBuilderError, "OPENING_PLAN_LOCKED"):
                configure_opening_builder(root, "prj_h3", shared_context="Changed continuity", slot_specs=[
                    {"duration_seconds": 6, "purpose": "Hook", "prompt": "Changed hook"},
                    {"duration_seconds": 6, "purpose": "Develop", "prompt": "Changed action"},
                    {"duration_seconds": 6, "purpose": "Bridge", "prompt": "Changed bridge"},
                ])
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_confirmed_keep_download_failure_recovers_without_another_keep(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = elyum_fixture.ElyumHybridOpeningTests()
            runtime = fixture._project(root)
            client = FakeElyum()
            generate_elyum_opening_preview(root, "prj_elyum_opening", "OPENING_O1", model=MODEL,
                                          client=client, preview_fetcher=fixture._fetch)
            review_elyum_opening_preview(root, "prj_elyum_opening", "OPENING_O1", decision="ACCEPT", reason="Use preview")
            with self.assertRaises(OSError):
                keep_elyum_opening_preview(root, "prj_elyum_opening", "OPENING_O1", client=client, confirm_spend=True,
                                          output_fetcher=lambda *_: (_ for _ in ()).throw(OSError("local download failed")))
            manifest = read_json(runtime.projects / "prj_elyum_opening" / "output" / "opening_manifest.json")
            generation = manifest["slots"][0]["api_generation"]
            self.assertTrue(generation.get("keep_confirmed"))
            self.assertEqual(generation["status"], "KEEP_ACQUISITION_REQUIRED")
            unchanged = generate_elyum_opening_preview(root, "prj_elyum_opening", "OPENING_O1", model=MODEL,
                                                       client=client, preview_fetcher=fixture._fetch)
            self.assertEqual(unchanged["slots"][0]["api_generation"]["status"], "KEEP_ACQUISITION_REQUIRED")
            recovered = keep_elyum_opening_preview(root, "prj_elyum_opening", "OPENING_O1", client=client,
                                                  output_fetcher=fixture._fetch_original)
            self.assertTrue(recovered["slots"][0]["asset_ready"])
            self.assertEqual(client.keep_calls, 1)
            self.assertEqual(client.make_calls, 1)
            self.assertNotIn("kept_output_urls", recovered["slots"][0]["api_generation"])
            self.assertEqual(recovered["slots"][0]["source_asset"]["provider"], "elyum_seedance")
            self.assertEqual(recovered["slots"][0]["source_asset"]["provider_gen_id"], generation["gen_id"])
            keep_elyum_opening_preview(root, "prj_elyum_opening", "OPENING_O1", client=client,
                                      output_fetcher=lambda *_: self.fail("completed acquisition must be reused"))
            self.assertEqual(client.keep_calls, 1)


if __name__ == "__main__":
    unittest.main()
