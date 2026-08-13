from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.publishing import finalize_thumbnail, prepare_thumbnail_request, run_publishing_metadata
from story_auto.providers.flow.service import FlowExecutor, execute_generation, review_production_asset
from story_auto.providers.flow.session import FlowCapabilities
from story_auto.providers.llm.gemini import LLMResponse


class FakeGemini:
    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(self, request):
        self.calls += 1
        return LLMResponse({"title_candidates": ["A Journey at Dusk", "The Last Train Home"],
                            "description": "A fictional traveler crosses a quiet station at dusk.",
                            "thumbnail_brief": "The same traveler in a cinematic station wide shot at dusk"},
                           request.model, request.request_id, 1, 3, {"totalTokenCount": 42})


class PublishingTests(unittest.TestCase):
    def test_metadata_checkpoint_thumbnail_request_flow_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            config = ProjectConfig("prj_publish01", settings={"llm": {"provider": "gemini", "model": "gemini-3.5-flash"}})
            paths = create_project(runtime, config, "# Story\n\n## Narration\n\nA traveler crosses a quiet station at dusk.\n")
            atomic_write_json(paths.artifact_path("output/final_manifest.json"),
                              {"final_sha256": "f" * 64, "publishing_package_sha256": None})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),
                              {"schema_version": "story-auto-generation-manifest/1.0.0",
                               "project_id": config.project_id, "requests": []})
            atomic_write_json(paths.artifact_path("output/review_state.json"),
                              {"plan_approval": {"status": "APPROVED"}})
            gemini = FakeGemini()
            self.assertEqual(run_publishing_metadata(runtime.root, config.project_id, provider=gemini), "RUN")
            self.assertEqual(run_publishing_metadata(runtime.root, config.project_id, provider=gemini), "SKIP")
            self.assertEqual(gemini.calls, 1)
            request = prepare_thumbnail_request(runtime.root, config.project_id)
            self.assertEqual(request["purpose"], "THUMBNAIL")
            calls = []
            def generate(_request, _refs, path):
                calls.append(_request["request_id"])
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(path, "PNG")
                return path
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
            first = execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                       request_ids={request["request_id"]})
            second = execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                        request_ids={request["request_id"]})
            self.assertEqual((first["new_submissions"], second["new_submissions"], len(calls)), (1, 0, 1))
            qc={"results":{key:"PASS" for key in ("SKIN_REALISM","LIGHTING_NATURALISM","MATERIAL_REALISM","COMPOSITION_NATURALISM","AI_POLISH","CONTINUITY","TECHNICAL_VALIDITY")},"visible_provider_watermark":False,"reviewer":"operator"}
            review_production_asset(runtime.root,config.project_id,request["request_id"],qc)
            finalize_thumbnail(runtime.root, config.project_id)
            package = read_json(paths.artifact_path("output/publishing_package.json"))
            self.assertEqual(package["thumbnail"]["provider"], "google_flow")
            self.assertEqual(package["thumbnail"]["sha256"],
                             sha256_file(paths.artifact_path(package["thumbnail"]["path"])))
            final_manifest = read_json(paths.artifact_path("output/final_manifest.json"))
            self.assertEqual(final_manifest["publishing_package_sha256"],
                             sha256_file(paths.artifact_path("output/publishing_package.json")))


if __name__ == "__main__":
    unittest.main()
