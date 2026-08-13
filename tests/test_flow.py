from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.page import FlowComposer
from story_auto.providers.flow.service import FlowError, FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities, FlowRuntime, FlowSessionError, launch_dedicated_session, preflight
from story_auto.providers.flow.settings import resolve_settings, select_model


class Editor:
    def __init__(self): self.value = ""
    def set_text(self, value): self.value = value
    def read_text(self): return self.value
class Button:
    def __init__(self): self.clicked = False
    def click(self): self.clicked = True
class DOM:
    def __init__(self, editors=1, controls=1): self.editors=[Editor() for _ in range(editors)]; self.controls=[Button() for _ in range(controls)]
    def active_prompt_editors(self): return self.editors
    def generate_controls(self, *_): return self.controls
    def add_references(self, _): pass
    def media_candidates(self): return []

class NativePage:
    def __init__(self): self.clicked = None
    def evaluate(self, _): return {"x":10,"y":20}
    def click(self, x, y): self.clicked=(x,y)

class Inspector:
    def __init__(self, value): self.value=value
    def inspect(self, _): return self.value
class Response:
    def __init__(self, data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def read(self): return self.data

class FlowTests(unittest.TestCase):
    def _project(self, root):
        runtime=RuntimeLayout.from_root(root); cfg=ProjectConfig("prj_flow001")
        paths=create_project(runtime,cfg)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval":{"status":"APPROVED"}})
        request=lambda ident, kind, deps=[]: {"request_id":ident,"fingerprint":ident+"hash","purpose":"REFERENCE" if ident == "ref" else "SHOT","media_type":kind,"prompt":"p","depends_on":deps,"provider":"google_flow"}
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests":[request("ref","IMAGE"),request("shot","IMAGE",["ref"])]})
        return runtime, cfg, paths
    def _executor(self):
        calls=[]
        def generate(request, refs, path):
            from PIL import Image
            calls.append((request["request_id"], refs)); path.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB", (32, 32), "navy").save(path, "PNG"); return path
        cap=FlowCapabilities(True,True,True,True,True,True)
        return FlowExecutor(cap,generate), calls
    def test_fail_closed_composer(self):
        dom=DOM(); FlowComposer(dom).submit("complete prompt", references=[], media_type="IMAGE"); self.assertTrue(dom.controls[0].clicked)
        for dom in (DOM(0),DOM(2),DOM(1,2)):
            with self.assertRaises(FlowSessionError) as caught: FlowComposer(dom).submit("p",references=[],media_type="IMAGE")
            self.assertEqual(caught.exception.failure_class,"FLOW_UI_CHANGED")

    def test_composer_baseline_runs_after_reference_attachment_before_click(self):
        events=[]
        class OrderedDom(DOM):
            def add_references(self, _): events.append("references")
        dom=OrderedDom()
        FlowComposer(dom).submit("p", references=["reference.png"], media_type="IMAGE", before_dispatch=lambda: events.append("baseline"))
        self.assertEqual(events,["references","baseline"])
        self.assertTrue(dom.controls[0].clicked)
    def test_live_generate_control_uses_native_mouse_click(self):
        from story_auto.providers.flow.live import _Control
        page=NativePage(); _Control(type("D",(),{"page":page})(),{"enabled":True,"x":10,"y":20}).click(); self.assertEqual(page.clicked,(10.0,20.0))
    def test_preflight_auth_and_project(self):
        runtime=FlowRuntime(Path("profile"),"http://test","url","story-auto")
        opener=lambda *_args,**_kw: Response(b'{"Browser":"Chrome"}')
        auth=preflight(runtime,Inspector({"login_required":True}),opener=opener); self.assertFalse(auth.authenticated)
        cap=preflight(runtime,Inspector({"project_identity":"story-auto","image":True,"video":True,"reference_image":True,"frame_video":True}),opener=opener)
        cap.require("VIDEO",True)
    def test_dedicated_session_never_uses_another_profile(self):
        with tempfile.TemporaryDirectory() as root:
            profile=Path(root)/"story-auto-profile"; runtime=FlowRuntime(profile,"http://127.0.0.1:9222","https://flow.example","story-auto"); calls=[]
            with patch("story_auto.providers.flow.session.Path.is_file", return_value=True):
                launch_dedicated_session(runtime, launcher=lambda args: calls.append(args))
            self.assertIn(f"--user-data-dir={profile}", calls[0]); self.assertIn("--remote-allow-origins=http://127.0.0.1:9222", calls[0]); self.assertNotIn("YouTube", " ".join(calls[0]))
    def test_manifest_dependency_resume_and_invalid_asset(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, cfg, paths=self._project(root); executor,calls=self._executor()
            first=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True); self.assertEqual(first["new_submissions"],2)
            second=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True); self.assertEqual(second["new_submissions"],0); self.assertEqual(len(calls),2)
            manifest=read_json(paths.artifact_path("output/generation_manifest.json")); selected=paths.artifact_path(manifest["requests"][0]["selected_asset"]["path"]); selected.unlink()
            third=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True); self.assertEqual(third["new_submissions"],1)
    def test_ambiguous_timeout_never_resubmits(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); calls=[]
            def timeout(*_): calls.append(1); raise FlowError("FLOW_TIMEOUT")
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),timeout)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(len(calls),2)
    def test_execution_gate(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); executor,_=self._executor()
            with self.assertRaises(FlowError) as caught: execute_generation(runtime.root,cfg.project_id,executor=executor)
            self.assertEqual(caught.exception.failure_class,"EXECUTION_CONFIRMATION_REQUIRED")
    def test_provider_policy_resolves_explicit_counts_and_modes(self):
        smoke=resolve_settings({"purpose":"REFERENCE","media_type":"IMAGE","execution_tier":"DEV_SMOKE","aspect_ratio":"16:9"})
        reference=resolve_settings({"purpose":"REFERENCE","media_type":"IMAGE","aspect_ratio":"16:9"})
        shot=resolve_settings({"purpose":"SHOT","media_type":"IMAGE","aspect_ratio":"16:9"})
        video=resolve_settings({"purpose":"SHOT","media_type":"VIDEO","depends_on":["ref"],"target_duration":5,"aspect_ratio":"16:9"})
        self.assertEqual((smoke.output_count, reference.output_count, shot.output_count), (1,2,1)); self.assertEqual(video.workflow_mode,"REFERENCE_TO_VIDEO")
        self.assertEqual(select_model(reference,[{"name":"fallback","media_types":["IMAGE"]}])["name"],"fallback")
    def test_pre_dispatch_failure_can_only_be_reopened_with_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"ref","status":"FAILED_PERMANENT","attempts":[{"failure_class":"FLOW_UI_CHANGED","dispatch_confirmed":False}]}]})
            from story_auto.providers.flow.service import reopen_verified_pre_dispatch_failure
            reopen_verified_pre_dispatch_failure(runtime.root,cfg.project_id,"ref")
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["status"],"FAILED_RETRYABLE")

if __name__ == "__main__": unittest.main()
