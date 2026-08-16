from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render.plan import resolve_render_plan
from story_auto.core.visual.quality import MediaQualityError, validate_production_qc
from story_auto.providers.flow.postprocess import (
    FlowImagePostprocessError,
    process_flow_image,
    supported_profiles,
)
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    adopt_manual_recovery,
    execute_generation,
    invalidate_asset_attribution,
    queue_regeneration,
    reconcile_local_assets,
    reuse_exact_flow_asset,
    review_production_asset,
)
from story_auto.providers.flow.session import FlowCapabilities


QC_FIELDS = (
    "SKIN_REALISM", "LIGHTING_NATURALISM", "MATERIAL_REALISM",
    "COMPOSITION_NATURALISM", "AI_POLISH", "CONTINUITY", "TECHNICAL_VALIDITY",
)


def _report(*, visible=False):
    return {"results": {key: "PASS" for key in QC_FIELDS},
            "visible_provider_watermark": visible, "reviewer": "test operator"}


class FlowImagePostprocessTests(unittest.TestCase):
    def _project(self, root, requests):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_flow_postprocess")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": requests})
        return runtime, config, paths

    @staticmethod
    def _request(request_id="ref", *, purpose="REFERENCE", depends_on=None):
        return {"request_id": request_id, "fingerprint": request_id + "-identity", "purpose": purpose,
                "shot_id": "sh_0001" if purpose == "SHOT" else None, "media_type": "IMAGE",
                "prompt": request_id, "depends_on": depends_on or [], "provider": "google_flow",
                "output_count": 1, "execution_tier": "STANDARD_PRODUCTION"}

    @staticmethod
    def _write_flow_image(path: Path, *, variant=0, size=(1280, 720)):
        image = Image.new("RGB", size, (35 + variant * 20, 65, 95))
        draw = ImageDraw.Draw(image)
        step = 19 + variant * 7
        for offset in range(0, size[0], step):
            draw.line((offset, 0, (offset + 300 + variant * 31) % size[0], size[1]),
                      fill=(100 + variant * 30, 130, 80), width=3)
        if size == (1280, 720):
            draw.polygon([(1160, 573), (1187, 599), (1160, 625), (1133, 599)], fill="white")
        elif size == (1376, 768):
            draw.polygon([(1278, 644), (1307, 671), (1278, 698), (1249, 671)], fill="white")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")

    def _executor(self, calls, *, size=(1280, 720)):
        def generate(request, refs, path):
            calls.append((request["request_id"], list(refs)))
            self._write_flow_image(path, variant=len(calls) - 1, size=size)
            return path
        return FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)

    def test_supported_profiles_create_distinct_valid_derivatives(self):
        self.assertEqual(set(supported_profiles()), {"flow-sparkle-1280x720-v1", "flow-sparkle-1376x768-v1"})
        with tempfile.TemporaryDirectory() as root:
            for size in ((1280, 720), (1376, 768)):
                raw = Path(root) / f"raw-{size[0]}.png"
                clean = Path(root) / f"clean-{size[0]}.png"
                self._write_flow_image(raw, size=size)
                raw_before = sha256_file(raw)
                result = process_flow_image(raw, clean)
                self.assertEqual(sha256_file(raw), raw_before)
                self.assertNotEqual(result["source_sha256"], result["output_sha256"])
                self.assertEqual((result["output_metadata"]["width"], result["output_metadata"]["height"]), size)
                self.assertEqual(len(result["mask_sha256"]), 64)

    def test_production_image_preserves_raw_and_selects_lineaged_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            calls = []
            result = execute_generation(runtime.root, config.project_id, executor=self._executor(calls), execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt, selected, processing = entry["attempts"][0], entry["selected_asset"], entry["postprocess_attempts"][0]
            self.assertEqual(result["new_submissions"], 1)
            self.assertEqual((attempt["status"], processing["status"], entry["status"]), ("SUCCEEDED", "SUCCEEDED", "QC_PENDING"))
            self.assertNotEqual(attempt["asset_path"], selected["path"])
            self.assertNotEqual(attempt["asset_sha256"], selected["sha256"])
            self.assertEqual((selected["source_provider_attempt"], selected["source_sha256"]), (1, attempt["asset_sha256"]))
            self.assertEqual(sha256_file(paths.artifact_path(attempt["asset_path"])), attempt["asset_sha256"])

    def test_missing_derivative_rebuilds_locally_without_provider_submission(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            calls = []; executor = self._executor(calls)
            execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            unchanged = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            self.assertEqual((unchanged["new_submissions"], len(calls)), (0, 1))
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            paths.artifact_path(entry["selected_asset"]["path"]).unlink()
            self.assertEqual(reconcile_local_assets(runtime.root, config.project_id), {"ref"})
            result = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            repaired = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((result["new_submissions"], len(calls), len(repaired["attempts"])), (0, 1, 1))
            self.assertEqual(repaired["postprocess_attempts"][-1]["status"], "SUCCEEDED")
            self.assertTrue(paths.artifact_path(repaired["selected_asset"]["path"]).is_file())

    def test_unsupported_geometry_fails_closed_and_retries_only_local_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            calls = []; executor = self._executor(calls, size=(640, 480))
            first = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            queue_regeneration(runtime.root, config.project_id, "ref", reason="operator retry")
            second = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((first["new_submissions"], second["new_submissions"], len(calls)), (0, 0, 1))
            self.assertEqual((entry["attempts"][0]["status"], len(entry["attempts"])), ("SUCCEEDED", 1))
            self.assertEqual(entry["failure_class"], "FLOW_IMAGE_POSTPROCESS_UNSUPPORTED_GEOMETRY")
            self.assertEqual(len(entry["postprocess_attempts"]), 2)
            self.assertEqual(entry["operator_actions"][-1]["action"], "RETRY_LOCAL_POSTPROCESS")
            self.assertNotIn("selected_asset", entry)

    def test_manual_recovery_preserves_raw_and_selects_clean_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            def timeout(*_):
                raise FlowError("FLOW_TIMEOUT")
            execute_generation(runtime.root, config.project_id,
                               executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), timeout),
                               execute=True)
            recovered = Path(root) / "recovered.png"; self._write_flow_image(recovered)
            raw_sha = sha256_file(recovered)
            selected = adopt_manual_recovery(runtime.root, config.project_id, "ref", recovered,
                                             settings={"source": "operator"}, attribution="exact visible Flow result")
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt = entry["attempts"][-1]
            self.assertEqual((attempt["status"], attempt["asset_sha256"]), ("SUCCEEDED", raw_sha))
            self.assertNotEqual(selected["sha256"], raw_sha)
            self.assertEqual(selected["source_sha256"], raw_sha)

    def test_wrong_mapping_is_invalidated_without_deleting_raw_or_clean_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            execute_generation(runtime.root, config.project_id, executor=self._executor([]), execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            raw_path = paths.artifact_path(entry["attempts"][0]["asset_path"])
            clean_path = paths.artifact_path(entry["selected_asset"]["path"])
            raw_sha, clean_sha = sha256_file(raw_path), sha256_file(clean_path)
            event = invalidate_asset_attribution(runtime.root, config.project_id, "ref")
            repaired = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((sha256_file(raw_path), sha256_file(clean_path)), (raw_sha, clean_sha))
            self.assertEqual((event["reason"], repaired["failure_class"]),
                             ("OUTPUT_ATTRIBUTION_INVALID", "OUTPUT_ATTRIBUTION_INVALID"))
            self.assertEqual(repaired["attempts"][0]["attribution_status"], "INVALIDATED")
            self.assertNotIn("selected_asset", repaired)

    def test_reference_dependency_receives_clean_selected_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            requests = [self._request(), self._request("shot", purpose="SHOT", depends_on=["ref"])]
            runtime, config, paths = self._project(root, requests)
            calls = []; executor = self._executor(calls)
            execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={"ref"})
            review_production_asset(runtime.root, config.project_id, "ref", _report())
            execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={"shot"})
            entries = {item["request_id"]: item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]}
            selected = entries["ref"]["selected_asset"]
            self.assertEqual(Path(calls[1][1][0]), paths.artifact_path(selected["path"]))
            self.assertEqual(entries["shot"]["reference_asset_hashes"], [selected["sha256"]])
            self.assertNotEqual(selected["sha256"], entries["ref"]["attempts"][0]["asset_sha256"])

    def test_exact_reuse_accepts_raw_to_derivative_lineage_and_requires_fresh_qc(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            execute_generation(runtime.root, config.project_id, executor=self._executor([]), execute=True)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            requests["requests"].append(self._request("revised", purpose="SHOT"))
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
            selected = reuse_exact_flow_asset(runtime.root, config.project_id, "ref", "revised",
                                              attribution="reuse clean exact image under revised intent")
            self.assertEqual(selected["production_qc"], "PENDING")
            self.assertEqual(selected["source_lineage"]["lineage_kind"], "RAW_TO_DERIVATIVE")

    def test_watermark_qc_is_media_type_aware(self):
        with self.assertRaises(MediaQualityError) as image_error:
            validate_production_qc(_report(visible=True), provider="google_flow", media_type="IMAGE")
        self.assertEqual(image_error.exception.failure_class, "VISIBLE_PROVIDER_WATERMARK")
        accepted = validate_production_qc(_report(visible=True), provider="google_flow", media_type="VIDEO")
        self.assertEqual(accepted["watermark_disposition"], "FLOW_VISIBLE_WATERMARK_ACCEPTED_KNOWN_LIMITATION")

    def test_render_plan_resolves_exact_clean_selected_path_and_hash(self):
        with tempfile.TemporaryDirectory() as root:
            request = self._request("shot", purpose="SHOT")
            runtime, config, paths = self._project(root, [request])
            execute_generation(runtime.root, config.project_id, executor=self._executor([]), execute=True)
            report = _report(); report["alignment_classification"] = "PASS_DIRECT"
            review_production_asset(runtime.root, config.project_id, "shot", report)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            selected = manifest["requests"][0]["selected_asset"]
            plan = resolve_render_plan(
                project_id=config.project_id, project_root=paths.root, render_mode="hybrid_hook",
                alignment={"duration_seconds": 2.0},
                shot_plan={"shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 2.0}]},
                media_plan={"shots": [{"shot_id": "sh_0001", "media_type": "IMAGE",
                                         "requirement": "REQUIRED", "fallback_policy": "BLOCK"}]},
                generation_requests={"requests": [request]}, generation_manifest=manifest,
            )
            self.assertEqual((plan["segments"][0]["source_asset"], plan["segments"][0]["source_hash"]),
                             (selected["path"], selected["sha256"]))
            self.assertNotEqual(selected["path"], manifest["requests"][0]["attempts"][0]["asset_path"])


if __name__ == "__main__":
    unittest.main()
