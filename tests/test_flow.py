from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.page import FlowComposer
from story_auto.providers.flow.service import (FlowError, FlowExecutor, execute_generation, reconcile_local_assets,
                                                adopt_exact_flow_recovery, adopt_manual_recovery,
                                                recover_interrupted_pre_dispatch_attempt, reject_selected_asset,
                                                reopen_uncertain_temporal_qc, reopen_verified_false_dispatch, reuse_exact_flow_asset,
                                                reopen_false_positive_production_qc, reopen_false_positive_temporal_qc, _first_unresolved,
                                                review_production_asset, review_temporal_asset, run_fresh_temporal_qc_review)
from story_auto.providers.flow.session import FlowCapabilities, FlowRuntime, FlowSessionError, launch_dedicated_session, preflight
from story_auto.providers.flow.settings import resolve_settings, select_model
from story_auto.providers.flow.live import DispatchEvidenceTracker, records_for_media
from story_auto.providers.flow.cdp import CdpPage, MAX_UNMATCHED_CDP_MESSAGES
import story_auto.providers.flow.service as flow_service


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
    def __init__(self): self.locator_selector = None; self.commands=[]; self.keys=[]; self.evaluations=0
    def evaluate(self, _):
        self.evaluations += 1
        if self.evaluations == 1: return [{"enabled":True,"x":30,"y":40}]
        if self.evaluations == 2: return True
        return [{"type":"pointerdown","isTrusted":True},{"type":"click","isTrusted":True}]
    def command(self, method, params=None): self.commands.append(method); return {"windowId":1} if method=="Browser.getWindowForTarget" else {}
    def assert_locator_activation_available(self): pass
    def locator_click(self, selector): self.locator_selector=selector
    def key(self, key, *, code=None): self.keys.append((key,code))

class Inspector:
    def __init__(self, value): self.value=value
    def inspect(self, _): return self.value
class Response:
    def __init__(self, data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def read(self): return self.data

class FlowTests(unittest.TestCase):
    def test_acquisition_filters_candidates_by_requested_media_type(self):
        records=[{"key":"stale-video","kind":"VIDEO"},{"key":"avatar","kind":"IMG","width":96},{"key":"new-image","kind":"IMG","width":1376},{"key":"video-source","kind":"SOURCE"}]
        self.assertEqual([x["key"] for x in records_for_media(records,"IMAGE")],["new-image"])
        self.assertEqual([x["key"] for x in records_for_media(records,"VIDEO")],["stale-video","video-source"])
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
            calls.append((request["request_id"], refs)); path.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB", (1280, 720), "navy").save(path, "PNG"); return path
        cap=FlowCapabilities(True,True,True,True,True,True)
        return FlowExecutor(cap,generate), calls
    def _production_report(self, *, failed_field=None, reviewer="operator", **extra):
        report={"results":{key:("FAIL" if key==failed_field else "PASS") for key in
                           ("SKIN_REALISM","LIGHTING_NATURALISM","MATERIAL_REALISM","COMPOSITION_NATURALISM","AI_POLISH","CONTINUITY","TECHNICAL_VALIDITY")},
                "visible_provider_watermark":False,"reviewer":reviewer}
        report.update(extra)
        return report
    def _goal37_rejected_fixture(self, root, *, request_id="req_2ed7c6b9c1ce863d8e9d"):
        runtime,cfg,paths=self._project(root); executor,calls=self._executor()
        requests=read_json(paths.artifact_path("output/generation_requests.json"))
        request=next(item for item in requests["requests"] if item["request_id"]=="ref")
        request.update({"request_id":request_id,"fingerprint":request_id+"hash","execution_tier":"STANDARD_PRODUCTION"})
        next(item for item in requests["requests"] if item["request_id"]=="shot")["depends_on"]=[request_id]
        atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
        execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={request_id})
        with self.assertRaisesRegex(FlowError,"NATURALNESS_QC_REJECTED"):
            review_production_asset(runtime.root,cfg.project_id,request_id,self._production_report(failed_field="AI_POLISH"))
        entry=next(item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"] if item["request_id"]==request_id)
        return runtime,cfg,paths,executor,calls,entry
    def _goal37_legacy_rejected_fixture(self, root, *, request_id="req_2ed7c6b9c1ce863d8e9d"):
        """Pre-Goal37 persisted shape: no rejection asset-binding fields."""
        from PIL import Image
        runtime,cfg,paths=self._project(root); executor,calls=self._executor()
        requests=read_json(paths.artifact_path("output/generation_requests.json"))
        request=next(item for item in requests["requests"] if item["request_id"]=="ref")
        request.update({"request_id":request_id,"fingerprint":request_id+"hash","execution_tier":"STANDARD_PRODUCTION"})
        next(item for item in requests["requests"] if item["request_id"]=="shot")["depends_on"]=[request_id]
        atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
        rel=f"assets/image/{request_id}/attempt_001.png"; asset=paths.artifact_path(rel); asset.parent.mkdir(parents=True,exist_ok=True)
        Image.new("RGB",(1280,720),"navy").save(asset,"PNG"); digest=hashlib.sha256(asset.read_bytes()).hexdigest()
        rejection={"reviewed_at":"2026-08-21T00:01:00+00:00","status":"REJECTED","failure_class":"NATURALNESS_QC_REJECTED",
                   "report":{"reviewer":"operator","results":{"AI_POLISH":"FAIL"}}}
        self.assertNotIn("selected_asset_path",rejection); self.assertNotIn("selected_asset_sha256",rejection)
        entry={"request_id":request_id,"media_type":"IMAGE","status":"FAILED_RETRYABLE","failure_class":"NATURALNESS_QC_REJECTED",
               "provider_submissions":1,"attempts":[{"attempt":1,"status":"SUCCEEDED","attribution_state":"CONFIRMED",
               "asset_path":rel,"asset_sha256":digest,"completed_at":"2026-08-21T00:00:00+00:00"}],
               "selected_asset":{"path":rel,"sha256":digest,"attempt":1,"production_qc":"REJECTED"},"quality_reviews":[rejection]}
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[entry]})
        return runtime,cfg,paths,executor,calls,entry

    def _temporal_false_positive_fixture(self, root):
        """Exact-style sh_0007 fixture: a persisted black-frame claim disproven by fresh evidence."""
        runtime,cfg,paths=self._project(root)
        request_id="req_f4ac825ecb2ccbea03d2"; rel=f"assets/video/{request_id}/attempt_001.mp4"
        asset=paths.artifact_path(rel); asset.parent.mkdir(parents=True,exist_ok=True); asset.write_bytes(b"deterministic-video-bytes")
        digest=hashlib.sha256(asset.read_bytes()).hexdigest()
        requests={"requests":[{"request_id":request_id,"fingerprint":request_id+"hash","purpose":"SHOT","shot_id":"sh_0007",
                                 "media_type":"VIDEO","prompt":"Elias continues in the dim kitchen.","depends_on":[],
                                 "provider":"google_flow","target_duration":3.0,
                                 "motion_risk_analysis":{"anatomy_risk":"LOW"}}]}
        atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
        original={"reviewed_at":"2026-08-22T15:39:17+00:00","report":{"state":"REJECT_BACKGROUND","eligible":False,
                  "notes":"full black discontinuity near 04.0s","reviewer":"old-reviewer"}}
        entry={"request_id":request_id,"request_identity_sha256":request_id+"hash","media_type":"VIDEO","provider":"google_flow",
               "status":"FAILED_RETRYABLE","failure_class":"REJECT_BACKGROUND","attempts":[{"attempt":1,"status":"SUCCEEDED",
               "attribution_state":"CONFIRMED","asset_path":rel,"asset_sha256":digest}],
               "selected_asset":{"path":rel,"sha256":digest,"attempt":1,"metadata":{"duration_seconds":8.0},
               "temporal_qc":"REJECTED","production_qc":"PENDING","temporal_reviews":[original]}}
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[entry]})
        return runtime,cfg,paths,request_id,digest,original
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

    def test_reference_readiness_is_committed_before_generate_resolution(self):
        events=[]
        class ReferenceDom(DOM):
            def add_references(self, _):
                events.append("reference_committed")
                return {"expected":1,"committed":True,"method":"fixture"}
            def generate_controls(self, *_):
                events.append("generate_resolved")
                return super().generate_controls(*_)
        result=FlowComposer(ReferenceDom()).submit("p",references=["reference.png"],media_type="IMAGE")
        self.assertEqual(events,["reference_committed","generate_resolved"])
        self.assertTrue(result["composer_ready_state"]["reference_state"]["committed"])

    def test_preconfigured_mode_is_not_reopened_before_submit(self):
        class ModeDom(DOM):
            def choose_mode(self, _): raise AssertionError("mode menu must remain closed")
        dom=ModeDom(); FlowComposer(dom).submit("p", references=[], media_type="IMAGE", mode_already_configured=True)
        self.assertTrue(dom.controls[0].clicked)
    def test_live_generate_control_reresolves_and_uses_one_locator_activation(self):
        from story_auto.providers.flow.live import _Control
        page=NativePage(); receipt=_Control(type("D",(),{"page":page})(),{"enabled":True,"x":10,"y":20}).click()
        self.assertIn("data-story-auto-flow-activation", page.locator_selector); self.assertEqual(page.keys,[])
        self.assertEqual(page.commands,["Browser.getWindowForTarget","Browser.setWindowBounds","Page.bringToFront"])
        self.assertEqual((receipt["interaction_method"],receipt["interaction_version"],receipt["trusted_click_seen"],receipt["activation_verified"]),("PLAYWRIGHT_LOCATOR",3,True,True))

    def test_click_acknowledgement_alone_is_dispatch_uncertain(self):
        tracker=DispatchEvidenceTracker()
        self.assertEqual(tracker.observe(input_dispatched=True,trusted_click_seen=True),"UNCERTAIN")
        self.assertEqual((tracker.signal,tracker.confirmation_count),("trusted_click_only",0))

    def test_attributable_provider_signal_confirms_exactly_once(self):
        tracker=DispatchEvidenceTracker()
        tracker.observe(input_dispatched=True,trusted_click_seen=True)
        self.assertEqual(tracker.observe(input_dispatched=True,attributable_job=True,legacy_ack_present=False),"UNCERTAIN")
        self.assertEqual(tracker.signal_state,"SIGNAL_OBSERVED")
        self.assertEqual(tracker.observe(input_dispatched=True,attributable_job=True,
                                         activation_verified=True,provider_acceptance_transition=True,
                                         durable_job_identity="card:provider-card-1",
                                         durable_evidence_serialized=True,
                                         evidence_poll_sequence=3),"CONFIRMED")
        tracker.observe(input_dispatched=True,attributable_output=True,legacy_ack_present=False)
        self.assertEqual(tracker.confirmation_count,1)

    def test_unrelated_dom_mutation_does_not_confirm_dispatch(self):
        tracker=DispatchEvidenceTracker()
        self.assertEqual(tracker.observe(input_dispatched=True,unrelated_dom_mutation=True),"NOT_CONFIRMED")
        self.assertEqual(tracker.confirmation_count,0)

    def test_later_reconciliation_converts_uncertain_to_confirmed_without_activation(self):
        tracker=DispatchEvidenceTracker()
        tracker.observe(input_dispatched=True,prompt_transition=True,
                        activation_verified=True,provider_acceptance_transition=True)
        self.assertEqual(tracker.state,"UNCERTAIN")
        tracker.observe(input_dispatched=True,attributable_output=True,
                        activation_verified=True,provider_acceptance_transition=True,
                        durable_evidence_serialized=True)
        self.assertEqual((tracker.state,tracker.signal,tracker.confirmation_count),("CONFIRMED","verified_activation_provider_ui_output",1))

    def test_not_dispatched_remains_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); calls=[]
            class NoDispatch:
                dispatch_confirmed = False
                last_settings = {"activation": {"input_dispatched": False},
                                 "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                                 "provider_job_id": None, "attribution_state": "NOT_ATTEMPTED"}
                def __call__(self, *_): calls.append(1); raise FlowError("FLOW_NOT_DISPATCHED")
            no_dispatch=NoDispatch()
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),no_dispatch)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(len(calls),2)

    def test_verified_pre_dispatch_activation_failure_remains_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); calls=[]
            class NoActivation:
                dispatch_confirmed = False
                last_settings = {"activation": {"input_dispatched": False},
                                 "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                                 "provider_job_id": None, "attribution_state": "NOT_ATTEMPTED"}
                def __call__(self, *_): calls.append(1); raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED")
            no_activation=NoActivation()
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),no_activation)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(len(calls),2)

    def test_interrupted_pre_dispatch_attempt_can_be_safely_reopened(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            manifest={"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{
                "request_id":"ref","request_identity_sha256":"refhash","related_identity":None,"media_type":"IMAGE",
                "provider":"google_flow","prompt_sha256":"refhash","reference_asset_hashes":[],"created_at":"now",
                "status":"GENERATING","attempts":[{"attempt":1,"status":"SUBMITTED","dispatch_confirmed":False,
                "provider_settings":None,"provider_execution_state":"NOT_STARTED","started_at":"now"}]}]}
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),manifest)
            recover_interrupted_pre_dispatch_attempt(runtime.root,cfg.project_id,"ref")
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(entry["status"],"NOT_DISPATCHED")
            self.assertEqual(entry["attempts"][-1]["failure_class"],"FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH")
    def test_preflight_auth_and_project(self):
        runtime=FlowRuntime(Path("profile"),"http://test","url","story-auto")
        opener=lambda *_args,**_kw: Response(b'{"Browser":"Chrome"}')
        auth=preflight(runtime,Inspector({"login_required":True}),opener=opener); self.assertFalse(auth.authenticated)
        cap=preflight(runtime,Inspector({"project_identity":"story-auto","image":True,"video":True,"reference_image":True,"frame_video":True}),opener=opener)
        cap.require("VIDEO",True)

    def test_preflight_cdp_command_times_out_on_unrelated_event_stream(self):
        """A busy DevTools event stream cannot keep preflight alive forever."""
        class EventOnlySocket:
            def __init__(self): self.sent=[]; self.timeouts=[]
            def send(self, payload): self.sent.append(json.loads(payload))
            def settimeout(self, value): self.timeouts.append(value)
            def recv(self): return json.dumps({"method":"Runtime.executionContextCreated"})
        socket = EventOnlySocket()
        page = CdpPage(socket, command_timeout_seconds=1.0, clock=lambda: 0.0)
        with self.assertRaises(FlowSessionError) as caught:
            page.evaluate("document.title")
        self.assertEqual(caught.exception.failure_class, "FLOW_CDP_COMMAND_TIMEOUT")
        self.assertEqual(socket.sent[0]["method"], "Runtime.evaluate")
        self.assertEqual(len(socket.sent), 1)
        self.assertEqual(len(socket.timeouts), MAX_UNMATCHED_CDP_MESSAGES + 1)
        self.assertTrue(socket.timeouts)

    def test_valid_qc_corrective_parent_is_not_reconciled_before_its_fresh_child(self):
        parent = {"request_id": "parent"}
        child = {"request_id": "child"}
        entries = {
            "parent": {"request_id": "parent", "status": "QC_CORRECTIVE_REPLANNED",
                       "attempts": [{"attempt": 1, "status": "SUCCEEDED"}]},
            "child": {"request_id": "child", "status": "PENDING", "attempts": []},
        }
        with patch("story_auto.providers.flow.service._first_invalid_request_replacement", return_value=None), \
             patch("story_auto.providers.flow.service._qc_corrective_replan_valid", return_value=True):
            self.assertIsNone(_first_unresolved(None, "project", [parent, child], entries))

    def test_transaction_hash_is_reused_only_inside_one_validation_scope(self):
        transaction = {"schema_version": "fixture", "targets": {"snapshot": list(range(100))}}
        with patch.object(flow_service, "_json_sha256", wraps=flow_service._json_sha256) as digest:
            with flow_service._transaction_read_scope():
                self.assertEqual(flow_service._prepared_transaction_sha256(transaction),
                                 flow_service._prepared_transaction_sha256(transaction))
            self.assertEqual(digest.call_count, 1)
            flow_service._prepared_transaction_sha256(transaction)
            self.assertEqual(digest.call_count, 2)
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
            third=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True); self.assertTrue(third["blocked"]); self.assertEqual(third["new_submissions"],0)

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
            self.assertTrue(result["blocked"])
            self.assertEqual(result["new_submissions"],0)

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
    def test_dispatch_uncertain_never_resubmits(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_=self._project(root); calls=[]
            def uncertain(*_): calls.append(1); raise FlowError("FLOW_DISPATCH_UNCERTAIN")
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),uncertain)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            self.assertEqual(len(calls),1)

    def test_dispatch_uncertain_blocks_next_serial_request_and_survives_resume(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); calls=[]
            requests={"requests":[{"request_id":ident,"fingerprint":ident+"hash","purpose":"SHOT","shot_id":ident,"media_type":"IMAGE","prompt":ident,"depends_on":[],"provider":"google_flow","output_count":1} for ident in ("a","b")]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            def uncertain(request, *_): calls.append(request["request_id"]); raise FlowError("FLOW_DISPATCH_UNCERTAIN")
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),uncertain)
            first=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,production_batch=True)
            second=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,production_batch=True)
            self.assertEqual(calls,["a"])
            self.assertEqual((first["blocked"],first["blocked_request_id"]),(True,"a"))
            self.assertEqual((second["new_submissions"],second["blocked_request_id"]),(0,"a"))

    def test_attribution_uncertain_cannot_select_asset_or_activate_next_request(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            requests={"requests":[{"request_id":ident,"fingerprint":ident+"hash","purpose":"SHOT","shot_id":ident,"media_type":"IMAGE","prompt":ident,"depends_on":[],"provider":"google_flow","output_count":1} for ident in ("a","b")]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            class Unattributed:
                def __init__(self): self.calls=[]; self.dispatch_confirmed=True; self.last_settings=None
                def __call__(self,request,_refs,path):
                    from PIL import Image
                    self.calls.append(request["request_id"]); path.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB",(1280,720),"blue").save(path,"PNG")
                    self.last_settings={"dispatch_confirmation_state":"CONFIRMED","dispatch_confirmation_signal":"provider_job_id","attribution_state":"UNCERTAIN","candidate_delta_count":1}
                    return path
            generate=Unattributed(); executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),generate)
            result=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,production_batch=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(generate.calls,["a"])
            self.assertEqual((entry["status"],entry["failure_class"]),("AMBIGUOUS","OUTPUT_ATTRIBUTION_UNCERTAIN"))
            self.assertNotIn("selected_asset",entry)
            self.assertTrue(result["blocked"])

    def test_attribution_ambiguous_blocks_batch_without_newest_selection(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); calls=[]
            requests={"requests":[{"request_id":ident,"fingerprint":ident+"hash","purpose":"SHOT","shot_id":ident,"media_type":"IMAGE","prompt":ident,"depends_on":[],"provider":"google_flow","output_count":1} for ident in ("a","b")]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            def ambiguous(request,*_): calls.append(request["request_id"]); raise FlowError("OUTPUT_ATTRIBUTION_AMBIGUOUS")
            result=execute_generation(runtime.root,cfg.project_id,executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),ambiguous),execute=True,production_batch=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(calls,["a"])
            self.assertEqual((entry["failure_class"],entry.get("selected_asset")),("OUTPUT_ATTRIBUTION_AMBIGUOUS",None))
            self.assertEqual((result["blocked"],result["blocked_request_id"]),(True,"a"))

    def test_successful_reconciliation_releases_queue_once_without_extra_activation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            requests={"requests":[{"request_id":ident,"fingerprint":ident+"hash","purpose":"SHOT","shot_id":ident,"media_type":"IMAGE","prompt":ident,"depends_on":[],"provider":"google_flow","output_count":1} for ident in ("a","b")]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"a","request_identity_sha256":"ahash","media_type":"IMAGE","status":"AMBIGUOUS","failure_class":"FLOW_DISPATCH_UNCERTAIN","attempts":[{"attempt":1,"status":"AMBIGUOUS","failure_class":"FLOW_DISPATCH_UNCERTAIN","dispatch_confirmed":False,"provider_settings":{"activation":{"input_dispatched":True}}}]}]})
            class ReconciledGenerator:
                def __init__(self): self.calls=[]; self.reconciles=0
                def reconcile(self,_request,_attempt,_path):
                    self.reconciles+=1
                    return {"state":"PROVEN_PRE_DISPATCH_FAILURE","evidence":{"input_dispatched":False,"signal":"provider_rejected_before_dispatch"}}
                def __call__(self,request,_refs,path):
                    from PIL import Image
                    self.calls.append(request["request_id"]); path.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB",(1280,720),request["request_id"]=="a" and "blue" or "green").save(path,"PNG"); return path
            generate=ReconciledGenerator(); result=execute_generation(runtime.root,cfg.project_id,executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),generate),execute=True,production_batch=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((generate.reconciles,generate.calls,result["new_submissions"]),(1,["a","b"],2))
            self.assertEqual(len(entry["attempts"]),2)
            self.assertEqual(entry["attempts"][0]["reconciliation_events"][0]["state"],"PROVEN_PRE_DISPATCH_FAILURE")
            self.assertNotIn("failure_class",entry["attempts"][1])

    def test_reconciliation_cannot_infer_pre_dispatch_failure_after_input_was_dispatched(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            requests={"requests":[{"request_id":ident,"fingerprint":ident+"hash","purpose":"SHOT","shot_id":ident,"media_type":"IMAGE","prompt":ident,"depends_on":[],"provider":"google_flow","output_count":1} for ident in ("a","b")]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"a","request_identity_sha256":"ahash","media_type":"IMAGE","status":"AMBIGUOUS","failure_class":"FLOW_DISPATCH_UNCERTAIN","attempts":[{"attempt":1,"status":"AMBIGUOUS","failure_class":"FLOW_DISPATCH_UNCERTAIN","dispatch_confirmed":False,"provider_settings":{"activation":{"input_dispatched":True}}}]}]})
            class UnsafeInference:
                def __init__(self): self.calls=[]; self.reconciles=0
                def reconcile(self,_request,_attempt,_path):
                    self.reconciles+=1
                    return {"state":"PROVEN_PRE_DISPATCH_FAILURE","evidence":{"input_dispatched":True,"prompt_retained":True,"candidate_delta_count":0}}
                def __call__(self,request,_refs,_path): self.calls.append(request["request_id"])
            generate=UnsafeInference()
            result=execute_generation(runtime.root,cfg.project_id,executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),generate),execute=True,production_batch=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((generate.reconciles,generate.calls),(1,[]))
            self.assertEqual((result["blocked"],result["blocked_request_id"]),(True,"a"))
            self.assertEqual((entry["status"],entry["failure_class"]),("AMBIGUOUS","FLOW_DISPATCH_UNCERTAIN"))
            self.assertEqual(entry["attempts"][0]["reconciliation_events"][0]["evidence"]["input_dispatched"],True)

    def test_manual_recovery_resolves_barrier_before_later_activation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); calls=[]
            requests=read_json(paths.artifact_path("output/generation_requests.json"))
            requests["requests"][1]["depends_on"]=[]
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"ref","request_identity_sha256":"refhash","media_type":"IMAGE","status":"AMBIGUOUS","failure_class":"OUTPUT_ATTRIBUTION_AMBIGUOUS","attempts":[{"attempt":1,"status":"AMBIGUOUS","failure_class":"OUTPUT_ATTRIBUTION_AMBIGUOUS"}]}]})
            from PIL import Image
            recovered=Path(root)/"recovered.png"; Image.new("RGB",(1280,720),"navy").save(recovered,"PNG")
            adopt_exact_flow_recovery(runtime.root,cfg.project_id,"ref",recovered,
                                      provider_identity={"asset_id":"exact"},evidence="operator selected exact provider asset identity")
            def generate(request,_refs,path): calls.append(request["request_id"]); Image.new("RGB",(1280,720),"green").save(path,"PNG"); return path
            execute_generation(runtime.root,cfg.project_id,executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),generate),execute=True,request_ids={"shot"},production_batch=True)
            self.assertEqual(calls,["shot"])

    def test_attempt_provenance_is_append_only_across_safe_retry(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            class SequencedGenerator:
                def __init__(self): self.calls=0; self.dispatch_confirmed=False; self.last_settings=None
                def __call__(self,request,refs,destination):
                    self.calls+=1
                    state="PRE_DISPATCH_FAILURE" if self.calls==1 else "CONFIRMED"
                    self.dispatch_confirmed=self.calls>1
                    self.last_settings={"activation":{"activation_time":f"time-{self.calls}","interaction_method":"CDP_TRUSTED_POINTER","interaction_version":2,"input_dispatched":self.calls>1},"composer_ready_state":{"prompt_committed":True,"reference_state":{"committed":True},"generate_enabled":True},"dispatch_confirmation_state":state,"dispatch_confirmation_signal":"input_not_dispatched" if self.calls==1 else "new_attributable_output","provider_job_id":None,"attribution_state":"NOT_ATTEMPTED" if self.calls==1 else "CONFIRMED","attribution_method":"fixture_provider_lineage" if self.calls>1 else None,"attribution_method_version":"fixture/1","attributed_provider_identity":{"identity":"fixture:output"} if self.calls>1 else None,"candidate_delta_count":1 if self.calls>1 else 0,"candidate_identities":[{"identity":"fixture:output"}] if self.calls>1 else [],"attribution_confirmation_timestamp":f"time-{self.calls}" if self.calls>1 else None}
                    if self.calls==1: raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED")
                    from PIL import Image
                    destination.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB",(1280,720),"blue").save(destination,"PNG"); return destination
            generate=SequencedGenerator(); executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),generate)
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            attempts=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["attempts"]
            self.assertEqual([item["status"] for item in attempts],["NOT_DISPATCHED","SUCCEEDED"])
            self.assertEqual([item["activation_time"] for item in attempts],["time-1","time-2"])
            self.assertEqual(attempts[1]["dispatch_confirmation_signal"],"new_attributable_output")
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
    def test_production_video_rejects_stale_bytes_selected_for_another_request(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); calls=[]
            requests={"requests":[{"request_id":f"video_{i}","fingerprint":f"hash_{i}","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","prompt":f"clip {i}","depends_on":[],"provider":"google_flow","output_count":1,"execution_tier":"STANDARD_PRODUCTION","motion_risk_analysis":{"physical_complexity":"LOW"}} for i in range(1,3)]}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            def stale_video(request, refs, path):
                calls.append(request["request_id"]); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b"same-provider-result"); return path
            executor=FlowExecutor(FlowCapabilities(True,True,True,True,True,True),stale_video)
            metadata={"duration_seconds":8.0,"width":1280,"height":720,"codec":"h264","container":"mp4","audio_present":False,"sha256":"same-hash"}
            with patch("story_auto.providers.flow.service.validate_video", return_value=metadata):
                result=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,production_batch=True)
            self.assertEqual((result["new_submissions"],calls),(1,["video_1","video_2"]))
            entries={x["request_id"]:x for x in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]}
            self.assertEqual(entries["video_1"]["status"],"QC_PENDING")
            self.assertEqual((entries["video_2"]["status"],entries["video_2"]["failure_class"]),("FAILED_RETRYABLE","FLOW_STALE_RESULT"))
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
            with self.assertRaisesRegex(FlowError, "VISIBLE_PROVIDER_WATERMARK"):
                review_production_asset(runtime.root,cfg.project_id,"ref",report)
            reviewed=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(reviewed["quality_reviews"][-1]["failure_class"], "VISIBLE_PROVIDER_WATERMARK")
            self.assertEqual(len(reviewed["attempts"]),1)

    def test_goal37_false_positive_reopen_fixture_preserves_rejection_and_requires_normal_qc(self):
        """Sanitized exact-style Trial A fixture; no live project or provider is used."""
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,executor,calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"
            original_rejection=dict(rejected["quality_reviews"][-1])
            asset_sha=rejected["selected_asset"]["sha256"]
            event=reopen_false_positive_production_qc(
                runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                reviewer="tech-lead",reason="false positive; re-review the identical confirmed asset",
            )
            reopened=next(item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"] if item["request_id"]==request_id)
            self.assertEqual(reopened["quality_reviews"][-1],original_rejection)
            self.assertEqual((reopened["status"],reopened["failure_class"],reopened["selected_asset"]["sha256"],
                              reopened["selected_asset"]["production_qc"]),("QC_PENDING",None,asset_sha,"PENDING"))
            self.assertEqual((event["disposition"],event["request_id"],event["selected_asset_sha256"],
                              event["superseded_rejection_index"],event["rejection_event_sha256"]),
                             ("FALSE_POSITIVE_REOPENED",request_id,asset_sha,0,hashlib.sha256(
                                 json.dumps(original_rejection,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode("utf-8")).hexdigest()))
            resumed=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={request_id})
            self.assertEqual((resumed["new_submissions"],len(calls)),(0,1))
            review_production_asset(runtime.root,cfg.project_id,request_id,self._production_report())
            final=next(item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"] if item["request_id"]==request_id)
            self.assertEqual(final["status"],"SUCCEEDED")

    def test_temporal_false_positive_supersession_is_exact_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,request_id,digest,original=self._temporal_false_positive_fixture(root)
            evidence={"decoded_frames":192,"minimum_luma":65.07,"frames_below_y20":0,
                      "checked_timestamps":[0.5,3.8,4.0,4.2,7.5]}
            with patch("story_auto.providers.flow.service._valid_selected",return_value=True):
                event=reopen_false_positive_temporal_qc(runtime.root,cfg.project_id,request_id,
                    expected_asset_sha256=digest,expected_attempt=1,reviewer="tech-lead",
                    reason="exact-byte review disproves claimed black frame",evidence=evidence)
                again=reopen_false_positive_temporal_qc(runtime.root,cfg.project_id,request_id,
                    expected_asset_sha256=digest,expected_attempt=1,reviewer="tech-lead",
                    reason="exact-byte review disproves claimed black frame",evidence=evidence)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(entry["selected_asset"]["temporal_reviews"][0],original)
            self.assertEqual((entry["status"],entry["failure_class"],entry["selected_asset"]["temporal_qc"]),
                             ("QC_PENDING",None,"PENDING"))
            self.assertEqual((event["selected_asset_sha256"],event["selected_attempt"],event["superseded_review_index"]),
                             (digest,1,0))
            self.assertEqual((again["supersession_id"],again["idempotent"]),(event["supersession_id"],True))
            report={"state":"PASS_TEMPORAL","eligible":True,"usable_start":0.0,"usable_end":8.0,
                    "review_identity":event["review_epoch"],"request_id":request_id,"attempt":1,"media_sha256":digest,
                    "frame_evidence":[{"index":1,"timestamp":0.5,"sha256":"a"*64}]}
            review_temporal_asset(runtime.root,cfg.project_id,request_id,report)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            fresh=entry["selected_asset"]["temporal_reviews"][-1]
            self.assertEqual((entry["selected_asset"]["temporal_qc"],fresh["review_epoch"],fresh["media_sha256"],fresh["selected_attempt"]),
                             ("APPROVED",event["review_epoch"],digest,1))

    def test_temporal_false_positive_supersession_fails_closed_for_wrong_asset_or_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_paths,request_id,digest,_original=self._temporal_false_positive_fixture(root)
            with patch("story_auto.providers.flow.service._valid_selected",return_value=True):
                for sha,attempt in (("0"*64,1),(digest,2)):
                    with self.subTest(sha=sha,attempt=attempt), self.assertRaisesRegex(FlowError,"TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID"):
                        reopen_false_positive_temporal_qc(runtime.root,cfg.project_id,request_id,
                            expected_asset_sha256=sha,expected_attempt=attempt,reviewer="tech-lead",reason="proof",evidence={"proof":"x"})

    def test_fresh_temporal_supersession_review_persists_exact_media_and_frame_binding(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,request_id,digest,_original=self._temporal_false_positive_fixture(root)
            with patch("story_auto.providers.flow.service._valid_selected",return_value=True):
                event=reopen_false_positive_temporal_qc(runtime.root,cfg.project_id,request_id,
                    expected_asset_sha256=digest,expected_attempt=1,reviewer="tech-lead",reason="proof",evidence={"proof":"x"})
                frames=[{"index":1,"timestamp":.5,"path":"fixture-frame.jpg","sha256":"a"*64}]
                result={"state":"PASS_TEMPORAL","eligible":True,"usable_start":0.0,"usable_end":8.0}
                calls=[SimpleNamespace(model="fixture",cache_hit=False,input_hash="fresh-video",request_count=1),
                       SimpleNamespace(model="fixture",cache_hit=False,input_hash="fresh-frames",request_count=1)]
                with patch("story_auto.providers.flow.service.sample_dense_frames",return_value=frames), \
                     patch("story_auto.providers.flow.service.temporal_video_qc",return_value=(result,calls)):
                    fresh=run_fresh_temporal_qc_review(runtime.root,cfg.project_id,request_id,router=object())
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            review=entry["selected_asset"]["temporal_reviews"][-1]
            self.assertEqual((fresh["review_epoch"],fresh["cache_hit"],review["media_sha256"],review["selected_attempt"]),
                             (event["review_epoch"],False,digest,1))
            self.assertEqual(review["frame_evidence"],[{"index":1,"timestamp":.5,"sha256":"a"*64}])

    def test_short_usable_window_is_bound_terminal_temporal_rejection_and_not_provider_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,request_id,digest,_original=self._temporal_false_positive_fixture(root)
            manifest=read_json(paths.artifact_path("output/generation_manifest.json")); entry=manifest["requests"][0]
            entry.update({"status":"QC_PENDING","failure_class":None})
            entry["selected_asset"].update({"temporal_qc":"PENDING","production_qc":"PENDING","temporal_reviews":[]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),manifest)
            report={"state":"USABLE_TEMPORAL_WINDOW_INVALID","eligible":False,"usable_start":0.0,"usable_end":2.5,
                    "request_id":request_id,"attempt":1,"media_sha256":digest,
                    "frame_evidence":[{"index":1,"timestamp":.5,"sha256":"a"*64}],
                    "notes":"required target 2.970833 exceeds usable 2.5 seconds"}
            with self.assertRaisesRegex(FlowError,"USABLE_TEMPORAL_WINDOW_INVALID"):
                review_temporal_asset(runtime.root,cfg.project_id,request_id,report)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            review=entry["selected_asset"]["temporal_reviews"][-1]
            self.assertEqual((entry["status"],entry["failure_class"],entry["selected_asset"]["temporal_qc"],
                              entry["selected_asset"]["production_qc"]),
                             ("FAILED_RETRYABLE","USABLE_TEMPORAL_WINDOW_INVALID","REJECTED","PENDING"))
            self.assertEqual((review["selected_asset_sha256"],review["selected_attempt"],review["media_sha256"]),
                             (digest,1,digest))
            from story_auto.providers.flow.service import _provider_generation_retry_authorized
            self.assertFalse(_provider_generation_retry_authorized(entry))

    def test_goal37_r2_reopens_exact_pre_goal37_legacy_rejection_without_rewriting_it(self):
        """The primary compatibility fixture is hand-shaped, never made by r1 QC code."""
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,executor,calls,fixture=self._goal37_legacy_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; original=dict(fixture["quality_reviews"][-1]); asset_sha=fixture["selected_asset"]["sha256"]
            event=reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                       reviewer="tech-lead",reason="reconcile exact pre-Goal37 rejection binding")
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(entry["quality_reviews"][-1],original)
            self.assertNotIn("selected_asset_path",entry["quality_reviews"][-1]); self.assertNotIn("selected_asset_sha256",entry["quality_reviews"][-1])
            self.assertEqual((event["event"],event["compatibility_mode"],event["disposition"],event["selected_asset_sha256"]),
                             ("LEGACY_QC_REJECTION_ASSET_BINDING_RECONCILED","LEGACY_PRE_GOAL37","FALSE_POSITIVE_REOPENED",asset_sha))
            self.assertEqual((entry["status"],entry["selected_asset"]["sha256"],entry["selected_asset"]["production_qc"]),
                             ("QC_PENDING",asset_sha,"PENDING"))
            resumed=execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={request_id})
            self.assertEqual((resumed["new_submissions"],calls),(0,[]))
            review_production_asset(runtime.root,cfg.project_id,request_id,self._production_report())
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["status"],"SUCCEEDED")

    def test_goal37_r2_legacy_reopen_negative_matrix_fails_closed(self):
        def denied(mutator, expected_override=None):
            with tempfile.TemporaryDirectory() as root:
                runtime,cfg,paths,_executor,_calls,fixture=self._goal37_legacy_rejected_fixture(root)
                entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
                expected=expected_override or mutator(paths,entry) or entry["selected_asset"]["sha256"]
                atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[entry]})
                with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                    reopen_false_positive_production_qc(runtime.root,cfg.project_id,"req_2ed7c6b9c1ce863d8e9d",expected_asset_sha256=expected,
                                                        reviewer="tech-lead",reason="negative legacy proof")
        def changed_asset(paths, entry):
            from PIL import Image
            target=paths.artifact_path(entry["selected_asset"]["path"]); Image.new("RGB",(1280,720),"green").save(target,"PNG")
            digest=hashlib.sha256(target.read_bytes()).hexdigest(); entry["selected_asset"]["sha256"]=digest; return digest
        def invalid_bytes(paths, entry): paths.artifact_path(entry["selected_asset"]["path"]).write_bytes(b"not an image")
        def later_attempt(_paths, entry):
            entry["attempts"].append({"attempt":2,"status":"SUCCEEDED","attribution_state":"CONFIRMED","asset_path":"later.png","asset_sha256":"f"*64,"completed_at":"2026-08-21T00:02:00+00:00"})
        def later_postprocess(_paths, entry):
            entry["postprocess_attempts"]=[{"processing_attempt":2,"status":"SUCCEEDED","source_provider_attempt":1,"source_path":"raw.png","source_sha256":"a"*64,"output_path":"later.png","output_sha256":"b"*64,"completed_at":"2026-08-21T00:02:00+00:00"}]
        def invalidated(_paths, entry): entry["attribution_invalidations"]=[{"invalidated_at":"2026-08-21T00:02:00+00:00"}]
        def manual_rebound(_paths, entry): entry["manual_recovery_events"]=[{"at":"2026-08-21T00:02:00+00:00"}]
        def later_approved(_paths, entry): entry["quality_reviews"].append({"reviewed_at":"2026-08-21T00:02:00+00:00","status":"APPROVED","report":{}})
        def wrong_rejection(_paths, entry): entry["quality_reviews"][-1]["failure_class"]="VISIBLE_PROVIDER_WATERMARK"
        def missing_history(_paths, entry): entry["quality_reviews"]=[]
        def ambiguous(_paths, entry): entry["attempts"][-1]["attribution_state"]="UNCERTAIN"
        for name,mutator in (("selected asset changed",changed_asset),("later provider attempt",later_attempt),
                             ("later postprocess",later_postprocess),("attribution invalidation",invalidated),
                             ("manual rebinding",manual_rebound),("later approved review",later_approved),
                             ("latest rejection differs",wrong_rejection),("missing history",missing_history),("unresolved",ambiguous)):
            with self.subTest(name=name): denied(mutator)
        with self.subTest(name="selected sha mismatch"): denied(lambda _paths,_entry: None, expected_override="0"*64)
        with self.subTest(name="selected bytes invalid"): denied(invalid_bytes)
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,_executor,_calls,fixture=self._goal37_legacy_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=fixture["selected_asset"]["sha256"]
            requests=read_json(paths.artifact_path("output/generation_requests.json")); requests["requests"].append({"request_id":"r2-child","replacement_of":request_id})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="replacement descendant")
            requests["requests"].pop(); atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                reviewer="tech-lead",reason="first bounded reconciliation")
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="double reconciliation")

    def test_goal37_reopen_can_fail_again_under_ordinary_qc(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,_executor,_calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=rejected["selected_asset"]["sha256"]
            reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                reviewer="tech-lead",reason="bounded false-positive appeal")
            with self.assertRaisesRegex(FlowError,"NATURALNESS_QC_REJECTED"):
                review_production_asset(runtime.root,cfg.project_id,request_id,self._production_report(failed_field="CONTINUITY"))
            entry=next(item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"] if item["request_id"]==request_id)
            self.assertEqual((entry["status"],entry["failure_class"],len(entry["quality_reviews"])),
                             ("FAILED_RETRYABLE","NATURALNESS_QC_REJECTED",2))

    def test_goal37_reopen_denies_wrong_sha_missing_or_corrupt_review_and_double_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,_executor,_calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=rejected["selected_asset"]["sha256"]
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256="0"*64,
                                                    reviewer="tech-lead",reason="wrong binding")
            manifest=read_json(paths.artifact_path("output/generation_manifest.json")); entry=manifest["requests"][0]
            entry["quality_reviews"][-1].pop("selected_asset_sha256")
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),manifest)
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="corrupt history")
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,_paths,_executor,_calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=rejected["selected_asset"]["sha256"]
            reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                reviewer="tech-lead",reason="bounded appeal")
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="second appeal")

    def test_goal37_reopen_denies_non_naturalness_invalid_bytes_and_current_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,_executor,_calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=rejected["selected_asset"]["sha256"]
            manifest=read_json(paths.artifact_path("output/generation_manifest.json")); entry=manifest["requests"][0]
            entry["failure_class"]="VISIBLE_PROVIDER_WATERMARK"; entry["quality_reviews"][-1]["failure_class"]="VISIBLE_PROVIDER_WATERMARK"
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),manifest)
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="wrong failure")
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,_executor,_calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=rejected["selected_asset"]["sha256"]
            paths.artifact_path(rejected["selected_asset"]["path"]).write_bytes(b"not an image")
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="invalid bytes")
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,_executor,_calls,rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"; asset_sha=rejected["selected_asset"]["sha256"]
            requests=read_json(paths.artifact_path("output/generation_requests.json")); requests["requests"].append(
                {"request_id":"replacement-current","replacement_of":request_id,"purpose":"REFERENCE","media_type":"IMAGE"})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            with self.assertRaisesRegex(FlowError,"QC_FALSE_POSITIVE_REOPEN_INVALID"):
                reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=asset_sha,
                                                    reviewer="tech-lead",reason="current replacement exists")

    def test_goal37_reopen_keeps_shot_alignment_required(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths,executor,_calls,_rejected=self._goal37_rejected_fixture(root)
            request_id="req_2ed7c6b9c1ce863d8e9d"
            requests=read_json(paths.artifact_path("output/generation_requests.json")); request=next(item for item in requests["requests"] if item["request_id"]==request_id)
            request.update({"purpose":"SHOT","shot_id":"sh_0001"}); atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            entry=next(item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"] if item["request_id"]==request_id)
            reopen_false_positive_production_qc(runtime.root,cfg.project_id,request_id,expected_asset_sha256=entry["selected_asset"]["sha256"],
                                                reviewer="tech-lead",reason="re-review exact shot")
            with self.assertRaisesRegex(FlowError,"VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED"):
                review_production_asset(runtime.root,cfg.project_id,request_id,self._production_report())

    def test_atmospheric_qc_requires_explicitly_planned_atmospheric_shot(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,_=self._executor()
            requests=read_json(paths.artifact_path("output/generation_requests.json")); shot=next(x for x in requests["requests"] if x["request_id"]=="shot"); shot.update({"execution_tier":"STANDARD_PRODUCTION","output_count":1,"shot_id":"sh_0001","depends_on":[]}); atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            atomic_write_json(paths.artifact_path("output/shot_plan.json"),{"shots":[{"shot_id":"sh_0001","atmospheric":False}]})
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"shot"})
            report={"results":{key:"PASS" for key in ("SKIN_REALISM","LIGHTING_NATURALISM","MATERIAL_REALISM","COMPOSITION_NATURALISM","AI_POLISH","CONTINUITY","TECHNICAL_VALIDITY")},"visible_provider_watermark":False,"reviewer":"operator","alignment_classification":"PASS_ATMOSPHERIC"}
            with self.assertRaisesRegex(FlowError,"VISUAL_NARRATION_ALIGNMENT_MISMATCH"):
                review_production_asset(runtime.root,cfg.project_id,"shot",report)
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["status"],"FAILED_RETRYABLE")
    def test_pre_dispatch_failure_can_only_be_reopened_with_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"ref","status":"FAILED_PERMANENT","attempts":[{"failure_class":"FLOW_UI_CHANGED","dispatch_confirmed":False,"provider_job_id":None,"durable_dispatch_identity":None,"provider_lineage_card_id":None,"attributed_provider_identity":None,"attribution_state":"NOT_ATTEMPTED","dispatch_confirmation_state":"PRE_DISPATCH_FAILURE","provider_settings":{"activation":{"input_dispatched":False}}}]}]})
            from story_auto.providers.flow.service import reopen_verified_pre_dispatch_failure
            reopen_verified_pre_dispatch_failure(runtime.root,cfg.project_id,"ref")
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["status"],"FAILED_RETRYABLE")
    def test_legacy_false_dispatch_timeout_requires_exact_ui_evidence_and_canonical_proof(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"ref","status":"AMBIGUOUS","attempts":[{"failure_class":"FLOW_TIMEOUT","dispatch_confirmed":True,"provider_settings":{"dispatch_ack_method":"composer_clear_or_output_transition","last_added_candidate_count":0}}]}]})
            evidence={"prompt_retained":True,"visible_media_count":0,"prompt_sha256":hashlib.sha256(b"p").hexdigest(),"screenshot_sha256":"a"*64}
            with self.assertRaisesRegex(FlowError,"GENERATION_RECONCILIATION_INVALID"):
                reopen_verified_false_dispatch(runtime.root,cfg.project_id,"ref",evidence=evidence)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((entry["status"],entry["attempts"][0]["dispatch_confirmed"]),("AMBIGUOUS",True))
    def test_uncertain_temporal_qc_retry_reuses_selected_bytes_without_generation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root)
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version":"story-auto-generation-manifest/1.0.0","project_id":cfg.project_id,"requests":[{"request_id":"shot","media_type":"VIDEO","status":"FAILED_RETRYABLE","failure_class":"TEMPORAL_VIDEO_QC_UNCERTAIN","attempts":[{"attempt":1}],"selected_asset":{"sha256":"exact-bytes","temporal_qc":"REJECTED"}}]})
            reopen_uncertain_temporal_qc(runtime.root,cfg.project_id,"shot")
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((entry["status"],entry["failure_class"],entry["selected_asset"]["sha256"],len(entry["attempts"])),
                             ("QC_PENDING","TEMPORAL_VIDEO_QC_REQUIRED","exact-bytes",1))
    def test_exact_prior_flow_asset_reuse_requires_fresh_qc_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,cfg,paths=self._project(root); executor,_=self._executor()
            execute_generation(runtime.root,cfg.project_id,executor=executor,execute=True,request_ids={"ref"})
            requests=read_json(paths.artifact_path("output/generation_requests.json"))
            requests["requests"].append({"request_id":"revised","fingerprint":"revised-hash","purpose":"SHOT","shot_id":"sh_0001","media_type":"IMAGE","prompt":"materially revised supportive intent","depends_on":[],"provider":"google_flow","execution_tier":"STANDARD_PRODUCTION"})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),requests)
            selected=reuse_exact_flow_asset(runtime.root,cfg.project_id,"ref","revised",attribution="exact prior Flow image; revised intent requires fresh QC")
            manifest={x["request_id"]:x for x in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]}
            self.assertEqual((manifest["revised"]["status"],selected["production_qc"],manifest["revised"]["attempts"][0]["source_request_id"]),
                             ("QC_PENDING","PENDING","ref"))

if __name__ == "__main__": unittest.main()
