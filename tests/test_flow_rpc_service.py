"""Composed canonical service + live route + RPC journal (offline provider)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.providers.flow.live import LiveFlowGenerator
from story_auto.providers.flow.rpc_transport import FlowRpcGenerator
from story_auto.providers.flow.service import execute_generation, FlowExecutor
from story_auto.providers.flow.session import FlowCapabilities, FlowRuntime
from tests import test_flow
from tests.test_flow_rpc_transport import Session, PROJECT


class RpcServiceTests(unittest.TestCase):
    def test_cookie_session_never_falls_back_to_cdp(self):
        from story_auto.providers.flow.service import FlowError
        flow = FlowRuntime(Path('profile'), 'cookie-owned://named', f'https://flow.google.com/project/{PROJECT}', PROJECT)
        factory = lambda _: None
        generator = LiveFlowGenerator(flow, rpc_session_factory=factory)
        with patch.dict('os.environ', {'STORY_AUTO_FLOW_RPC_EXPERIMENTAL':'0'}), \
             patch('story_auto.providers.flow.live.CdpPage.open') as cdp:
            with self.assertRaisesRegex(FlowError, 'FLOW_RPC_DISABLED'):
                generator({'media_type':'VIDEO'}, [], Path('unused.mp4'))
            with self.assertRaisesRegex(FlowError, 'FLOW_COOKIE_CAPABILITY_UNSUPPORTED'):
                generator({'media_type':'IMAGE'}, [], Path('unused.png'))
            cdp.assert_not_called()

    def test_injected_session_used_for_dispatch_and_recovery(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            helper = test_flow.FlowTests()
            runtime, cfg, paths = helper._project(root)
            image_executor, _ = helper._executor()
            execute_generation(runtime.root,cfg.project_id,executor=image_executor,execute=True,request_ids={'ref'})
            requests = read_json(paths.artifact_path('output/generation_requests.json'))
            requests['requests'][1].update(media_type='VIDEO',target_duration=8,motion_risk_analysis={'physical_complexity':'LOW'})
            atomic_write_json(paths.artifact_path('output/generation_requests.json'),requests)
            flow = FlowRuntime(Path(root)/'account','cookie-owned://test',f'https://flow.google.com/project/{PROJECT}',PROJECT)
            session = Session()
            session.fail_submit = True
            opened = []
            def factory(bound):
                opened.append(bound)
                return session
            generator = LiveFlowGenerator(flow,timeout_seconds=0,rpc_session_factory=factory)
            executor = FlowExecutor(FlowCapabilities(True,True,False,True,False,True),generator)
            metadata = {'duration_seconds':8,'width':1280,'height':720,'sha256':hashlib.sha256(b'fixture-video').hexdigest()}
            with patch.dict('os.environ',{'STORY_AUTO_FLOW_RPC_EXPERIMENTAL':'1','STORY_AUTO_FLOW_RPC_PROJECT':PROJECT}), \
                 patch('story_auto.providers.flow.rpc_transport.validate_video',return_value=metadata), \
                 patch('story_auto.providers.flow.service.validate_video',return_value=metadata):
                execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={'shot'})
                first = read_json(paths.artifact_path('output/generation_manifest.json'))['requests'][-1]
                self.assertEqual(first['status'],'AMBIGUOUS')
                execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={'shot'})
            final = read_json(paths.artifact_path('output/generation_manifest.json'))['requests'][-1]
            self.assertEqual(final['status'],'SUCCEEDED')
            self.assertEqual((session.uploads,session.submits),(1,1))
            self.assertEqual(opened,[flow,flow])

    def test_three_shot_batch_has_distinct_outputs_and_resume_is_idle(self):
        import hashlib
        from uuid import UUID, uuid5
        from tests.test_flow_rpc_contract import record
        with tempfile.TemporaryDirectory() as root:
            helper = test_flow.FlowTests()
            runtime, cfg, paths = helper._project(root)
            image_executor, _ = helper._executor()
            execute_generation(runtime.root, cfg.project_id, executor=image_executor, execute=True, request_ids={"ref"})
            document = read_json(paths.artifact_path("output/generation_requests.json"))
            template = document["requests"][1]
            shots = [dict(template, request_id=f"shot{i}", fingerprint=f"shot{i}", prompt=f"Scene {i}", media_type="VIDEO", target_duration=8, motion_risk_analysis={"physical_complexity": "LOW"}) for i in range(3)]
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [document["requests"][0], *shots]})
            flow_runtime = FlowRuntime(Path(root)/"profile", "http://127.0.0.1:9222", f"https://flow.google.com/project/{PROJECT}", PROJECT)
            sessions = []
            class UniqueSession(Session):
                def catalog(self):
                    if not self.prompt: return []
                    return [record(identity=str(uuid5(UUID(PROJECT), self.prompt)), prompt=self.prompt)]
            def factory(runtime, **kwargs):
                session = UniqueSession()
                sessions.append(session)
                return FlowRpcGenerator(runtime, session_factory=lambda _: session, timeout_seconds=0)
            metadata = {"duration_seconds": 8, "width": 1280, "height": 720, "sha256": hashlib.sha256(b"fixture-video").hexdigest()}
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), LiveFlowGenerator(flow_runtime))
            with patch.dict("os.environ", {"STORY_AUTO_FLOW_RPC_EXPERIMENTAL": "1", "STORY_AUTO_FLOW_RPC_PROJECT": PROJECT}), \
                 patch("story_auto.providers.flow.rpc_transport.FlowRpcGenerator", side_effect=factory), \
                 patch("story_auto.providers.flow.rpc_transport.validate_video", return_value=metadata), \
                 patch("story_auto.providers.flow.service.validate_video", return_value=metadata):
                first = execute_generation(runtime.root, cfg.project_id, executor=executor, execute=True, production_batch=True)
                second = execute_generation(runtime.root, cfg.project_id, executor=executor, execute=True, production_batch=True)
            self.assertEqual((first["new_submissions"], second["new_submissions"]), (3, 0))
            self.assertEqual(sum(s.submits for s in sessions), 3)
            entries = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][1:]
            self.assertEqual(len({e["attempts"][0]["attributed_provider_identity"]["identity"] for e in entries}), 3)
            self.assertTrue(all(e["status"] == "SUCCEEDED" and len(e["attempts"]) == 1 for e in entries))

    def test_lost_response_canonical_recovery_selects_without_second_submit(self):
        with tempfile.TemporaryDirectory() as root:
            helper = test_flow.FlowTests()
            runtime, cfg, paths = helper._project(root)
            image_executor, _ = helper._executor()
            execute_generation(runtime.root, cfg.project_id, executor=image_executor, execute=True, request_ids={"ref"})
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            shot = requests["requests"][1]
            shot.update(media_type="VIDEO", target_duration=8, motion_risk_analysis={"physical_complexity": "LOW"})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
            flow_runtime = FlowRuntime(Path(root)/"profile", "http://127.0.0.1:9222", f"https://flow.google.com/project/{PROJECT}", PROJECT)
            session = Session()
            session.fail_submit = True
            generator = LiveFlowGenerator(flow_runtime)
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generator)
            factory = lambda runtime, **kwargs: FlowRpcGenerator(runtime, session_factory=lambda _: session, timeout_seconds=0)
            import hashlib
            metadata = {"duration_seconds": 8, "width": 1280, "height": 720, "sha256": hashlib.sha256(b"fixture-video").hexdigest()}
            with patch.dict("os.environ", {"STORY_AUTO_FLOW_RPC_EXPERIMENTAL": "1", "STORY_AUTO_FLOW_RPC_PROJECT": PROJECT}), \
                 patch("story_auto.providers.flow.rpc_transport.FlowRpcGenerator", side_effect=factory), \
                 patch("story_auto.providers.flow.rpc_transport.validate_video", return_value=metadata), \
                 patch("story_auto.providers.flow.service.validate_video", return_value=metadata):
                execute_generation(runtime.root, cfg.project_id, executor=executor, execute=True, request_ids={"shot"})
                first = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][-1]
                self.assertEqual(first["status"], "AMBIGUOUS")
                self.assertEqual(session.submits, 1)
                execute_generation(runtime.root, cfg.project_id, executor=executor, execute=True, request_ids={"shot"})
                final = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][-1]
                self.assertEqual(final["status"], "SUCCEEDED")
                self.assertEqual(len(final["attempts"]), 1)
                self.assertEqual((session.uploads, session.submits), (1, 1))
                self.assertTrue(paths.artifact_path(final["selected_asset"]["path"]).is_file())
