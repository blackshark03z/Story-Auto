from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.page import FlowComposer
from story_auto.providers.flow.service import (FlowError, FlowExecutor, execute_generation, reconcile_local_assets,
                                                reject_selected_asset, review_production_asset)
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
    def __init__(self): self.clicked = None; self.commands=[]
    def evaluate(self, _): return {"x":10,"y":20}
    def command(self, method): self.commands.append(method)
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

    def test_preconfigured_mode_is_not_reopened_before_submit(self):
        class ModeDom(DOM):
            def choose_mode(self, _): raise AssertionError("mode menu must remain closed")
        dom=ModeDom(); FlowComposer(dom).submit("p", references=[], media_type="IMAGE", mode_already_configured=True)
        self.assertTrue(dom.controls[0].clicked)
    def test_live_generate_control_uses_native_mouse_click(self):
        from story_auto.providers.flow.live import _Control
        page=NativePage(); _Control(type("D",(),{"page":page})(),{"enabled":True,"x":10,"y":20}).click(); self.assertEqual(page.clicked,(10.0,20.0)); self.assertEqual(page.commands,["Page.bringToFront"])

    def test_not_dispatched_remains_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); calls=[]
            def no_dispatch(*_): calls.append(1); raise FlowError("FLOW_NOT_DISPATCHED")
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),no_dispatch)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(len(calls),2)
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

    def test_local_reconciliation_invalidates_only_missing_selected_asset(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,calls=self._executor()
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True)
            manifest=read_json(paths.artifact_path("output/generation_manifest.json"))
            image_entry=next(item for item in manifest["requests"] if item["request_id"]=="shot")
            paths.artifact_path(image_entry["selected_asset"]["path"]).unlink()
            self.assertEqual(reconcile_local_assets(runtime.root,cfg.project_id), {"shot"})
            reconciled=read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual(next(item for item in reconciled["requests"] if item["request_id"]=="shot")["status"], "FAILED_RETRYABLE")
            self.assertEqual(next(item for item in reconciled["requests"] if item["request_id"]=="ref")["status"], "SUCCEEDED")
            result=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True)
            self.assertEqual(result["new_submissions"],1)

    def test_visual_rejection_preserves_successful_attempt_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,_=self._executor()
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            reject_selected_asset(runtime.root,cfg.project_id,"ref",reason="visual review mismatch")
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((entry["status"],entry["failure_class"],len(entry["attempts"])),("FAILED_RETRYABLE","CREATIVE_REJECTED",1))
            self.assertEqual(entry["creative_rejections"][0]["reason"],"visual review mismatch")

    def test_dependent_generation_receives_absolute_reference_file(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,calls=self._executor()
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True)
            self.assertEqual(Path(calls[1][1][0]), paths.artifact_path("assets/image/ref/attempt_001.png"))
    def test_ambiguous_timeout_never_resubmits(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); calls=[]
            def timeout(*_): calls.append(1); raise FlowError("FLOW_TIMEOUT")
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),timeout)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(len(calls),1)
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
        self.assertEqual((smoke.output_count, reference.output_count, shot.output_count), (1,1,1)); self.assertEqual(video.workflow_mode,"REFERENCE_TO_VIDEO")
        self.assertEqual(select_model(reference,[{"name":"fallback","media_types":["IMAGE"]}])["name"],"fallback")
    def test_stale_image_output_count_is_forced_to_one(self):
        resolved=resolve_settings({"purpose":"REFERENCE","media_type":"IMAGE","output_count":4})
        self.assertEqual(resolved.output_count,1)
    def test_production_batch_allows_repeated_kinds_and_resumes_without_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,calls=self._executor()
            requests={"requests":[{"request_id":f"image_{i}","fingerprint":f"hash_{i}","purpose":"SHOT","shot_id":f"sh_{i:04d}","media_type":"IMAGE","prompt":"natural image","depends_on":[],"provider":"google_flow","output_count":1} for i in range(1,4)]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            with self.assertRaises(FlowError): execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True)
            first=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,production_batch=True)
            second=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,production_batch=True)
            self.assertEqual((first["new_submissions"],second["new_submissions"],len(calls)),(3,0,3))
    def test_production_qc_approves_or_rejects_without_erasing_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,_=self._executor()
            requests=read_json(paths.artifact_path("output/generation_requests.json")); requests["requests"][0]["execution_tier"]="STANDARD_PRODUCTION"; requests["requests"][0]["output_count"]=1; atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["status"],"QC_PENDING")
            report={"results":{key:"PASS" for key in ("SKIN_REALISM","LIGHTING_NATURALISM","MATERIAL_REALISM","COMPOSITION_NATURALISM","AI_POLISH","CONTINUITY","TECHNICAL_VALIDITY")},"visible_provider_watermark":False,"reviewer":"operator"}
            review_production_asset(runtime.root,cfg.project_id,"ref",report)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((entry["status"],len(entry["attempts"]),entry["selected_asset"]["production_qc"]),("SUCCEEDED",1,"APPROVED"))
            report["visible_provider_watermark"]=True
            review_production_asset(runtime.root,cfg.project_id,"ref",report)
            reviewed=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(reviewed["quality_reviews"][-1]["report"]["watermark_disposition"],
                             "FLOW_VISIBLE_WATERMARK_ACCEPTED_KNOWN_LIMITATION")
            self.assertEqual(len(reviewed["attempts"]),1)
    def test_pre_dispatch_failure_can_only_be_reopened_with_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"ref","status":"FAILED_PERMANENT","attempts":[{"failure_class":"FLOW_UI_CHANGED","dispatch_confirmed":False}]}]})
            from story_auto.providers.flow.service import reopen_verified_pre_dispatch_failure
            reopen_verified_pre_dispatch_failure(runtime.root,cfg.project_id,"ref")
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["status"],"FAILED_RETRYABLE")

if __name__ == "__main__": unittest.main()
