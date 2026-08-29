import tempfile
import unittest

from story_auto.application import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.connection import (FlowConnectionError, FlowConnectionService,
                                                   normalize_project_url)
from story_auto.providers.flow.service import FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities


def validated(url="https://labs.google/fx/tools/flow/project-alpha"):
    return {"status":"CONNECTED", "project_url":url, "project_identity":url,
            "observed_capabilities":{"IMAGE":True,"VIDEO":True,"REFERENCE_IMAGE":True,"FRAME_VIDEO":True}}


class FlowConnectionTests(unittest.TestCase):
    def test_normalization_and_revision_are_canonical(self):
        with tempfile.TemporaryDirectory() as root:
            service=FlowConnectionService(root)
            first=service.save_validated_candidate(validated("HTTPS://LABS.GOOGLE/fx/tools/flow/project-alpha/"))
            second=service.save_validated_candidate(validated("https://labs.google/fx/tools/flow/project-beta"))
            self.assertEqual(first.connection_id,second.connection_id)
            self.assertEqual((first.revision,second.revision),(1,2))
            self.assertEqual(second.project_url,"https://labs.google/fx/tools/flow/project-beta")
            self.assertEqual(service.get_connection_status(required_capabilities=["IMAGE"])["status"],"CONNECTED")

    def test_invalid_url_is_rejected_before_browser_access(self):
        with self.assertRaisesRegex(FlowConnectionError,"FLOW_URL_INVALID"):
            normalize_project_url("https://example.test/not-flow?secret=no")

    def test_legacy_project_adopts_only_before_provider_attempts(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root); service=FlowConnectionService(runtime)
            connection=service.save_validated_candidate(validated())
            paths=create_project(runtime,ProjectConfig("prj_legacy",settings={"flow":{"project_url":"https://labs.google/fx/tools/flow/old","project_identity":"old"}}))
            binding=service.bind_project("prj_legacy",connection)
            saved=read_json(paths.project_file)["settings"]
            self.assertEqual(binding,{"connection_id":connection.connection_id,"connection_revision":1})
            self.assertNotIn("flow",saved)
            self.assertEqual(saved["flow_binding"],binding)

    def test_historical_attempt_prevents_rebinding(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root); service=FlowConnectionService(runtime)
            connection=service.save_validated_candidate(validated())
            paths=create_project(runtime,ProjectConfig("prj_history",settings={"flow":{"project_url":"https://labs.google/fx/tools/flow/old","project_identity":"old"}}))
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[{"request_id":"req_1","attempts":[{"attempt":1}]}]})
            with self.assertRaisesRegex(FlowConnectionError,"FLOW_REBIND_HISTORY_IMMUTABLE"):
                service.bind_project("prj_history",connection)
            self.assertIn("flow",read_json(paths.project_file)["settings"])

    def test_new_project_inherits_validated_runtime_binding(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            connection=app.flow_connections.save_validated_candidate(validated())
            app.create_project(project_id="prj_inherited",content="# Story\n\n## Narration\n\nReady.")
            _paths,config=app._project("prj_inherited")
            self.assertEqual(config.settings["flow_binding"],{"connection_id":connection.connection_id,"connection_revision":connection.revision})

    def test_provider_attempt_snapshots_connection_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root); paths=create_project(runtime,ProjectConfig("prj_provenance"))
            atomic_write_json(paths.artifact_path("output/review_state.json"),{"plan_approval":{"status":"APPROVED"}})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[{"request_id":"req_1","fingerprint":"a","purpose":"REFERENCE","media_type":"IMAGE","prompt":"p","depends_on":[],"provider":"google_flow"}]})
            def generate(_request, _refs, target):
                from PIL import Image
                target.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB",(1280,720),"navy").save(target,"PNG"); return target
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),generate)
            provenance={"flow_connection_id":"flow_test","flow_connection_revision":7,"flow_project_identity":"project","flow_project_url":"https://labs.google/fx/tools/flow/project","dedicated_profile_identity":"runtime/browser/flow-profile"}
            execute_generation(runtime.root,"prj_provenance",executor=executor,execute=True,flow_connection_provenance=provenance)
            attempt=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["attempts"][0]
            self.assertEqual(attempt["flow_connection"],provenance)


if __name__ == "__main__":
    unittest.main()
