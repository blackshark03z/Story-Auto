from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from story_auto.ui import create_server
from story_auto.providers.tts.kokoro_local import KokoroReadiness


class OperatorUiTests(unittest.TestCase):
    def test_loopback_http_smoke_and_content_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            server=create_server(root,port=0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            base=f"http://127.0.0.1:{server.server_address[1]}"
            def call(path,body=None):
                data=None if body is None else json.dumps(body).encode()
                request=Request(base+path,data=data,headers={"Content-Type":"application/json"})
                with urlopen(request,timeout=5) as response: return response.status,response.read(),response.headers.get_content_type()
            try:
                status,html,kind=call("/"); self.assertEqual((status,kind),(200,"text/html")); self.assertIn(b"<title>Story Auto</title>",html)
                self.assertIn(b"Skip to main content",html); self.assertIn(b"newVideoDialog",html); self.assertIn(b" Settings</button>",html)
                _,styles,_=call("/static/styles.css"); self.assertIn(b":focus-visible",styles); self.assertIn(b"[hidden]",styles)
                _,script,_=call("/static/app.js"); self.assertNotIn(b"prompt(",script); self.assertIn(b"showModal()",script)
                status,payload,_=call("/api/runtime-attestation"); attestation=json.loads(payload)
                self.assertEqual((status,attestation["process_id"]),(200,os.getpid()))
                self.assertEqual(attestation["provider_surface_extractor_version"],"flow-provider-surface/2.5.0")
                self.assertEqual(attestation["poll_evidence_version"],"story-auto-flow-poll-evidence/1.5.0")
                self.assertEqual(len(attestation["flow_module_sha256"]),64)
                self.assertIn(b"requestPause",script); self.assertIn(b"focusWizardStep",script); self.assertIn(b"aria-invalid",script)
                self.assertIn(b"data-error-action",script); self.assertIn(b'id="busyReason"',script)
                self.assertIn(b"KOKORO_MODEL_NOT_FOUND",script); self.assertIn(b"Kokoro model files are missing",script)
                self.assertIn(b"KOKORO_RUNTIME_LOAD_FAILED",script); self.assertIn(b"Kokoro readiness",script)
                self.assertIn(b"AMBIENT_VISUAL_BRIEF_OVER_BUDGET",script); self.assertIn(b"Visual planning needs to be regenerated",script)
                self.assertIn(b"STORY_TIMELINE_INVALID",script); self.assertIn(b"Visual planning needs another attempt",script)
                self.assertIn(b"Your audio and timing are saved",script); self.assertIn(b"Retry planning",script)
                self.assertIn(b"PROJECT_LOCKED",script); self.assertIn(b"This project is still working",script)
                self.assertIn(b"ArtifactWriteError",script); self.assertIn(b"does not send another Flow request",script)
                self.assertIn(b"issue.technical_code || issue.request_id",script)
                self.assertIn(b"const projectId = state.project",script)
                self.assertIn(b"automatically creates one Flow project for each new video",script)
                self.assertIn(b"ensure_flow_project",script); self.assertIn(b"open_flow_project",script)
                self.assertIn(b"recheck_flow_generation",script)
                self.assertIn(b"state.view === 'project' && state.project === projectId",script)
                self.assertIn(b"Create again",script)
                self.assertIn(b"Use recovered file",script)
                self.assertIn(b"data-use-recovered",script)
                self.assertIn(b"Scene-to-narration match",script)
                self.assertIn(b"Choose a match verdict",script)
                self.assertIn(b"data-reopen-qc",script)
                self.assertIn(b"reopen_production_qc",script)
                self.assertIn(b"Ambient Story",script); self.assertIn(b"Quiet Verdict",script); self.assertIn(b"Hidden Mastery",script)
                self.assertIn(b'name="format"',script); self.assertIn(b'name="ambientStyle"',script)
                self.assertIn(b'Quality review',script); self.assertIn(b'name="qcPolicy"',script)
                self.assertIn(b'Accept eligible visuals',script); self.assertIn(b'accept_selected_assets',script)
                self.assertNotIn(b"zoom percentage",script); self.assertNotIn(b"particle count",script)
                status,payload,_=call("/api/projects",{"project_id":"prj_ui001","render_mode":"full_image","content":"# Story\n\n## Narration\n\nA local operator test.\n"}); self.assertEqual(status,201)
                created=json.loads(payload); self.assertEqual(created["content_status"],"VALID")
                _,payload,_=call("/api/projects/prj_ui001/actions",{"action":"save_content","content":"# Story\n\n## Narration\n\nUpdated through the shared service.\n"}); self.assertIn(b"Updated through the shared service",payload)
                _,payload,_=call("/api/projects/prj_ui001/snapshot"); self.assertEqual(json.loads(payload)["project_id"],"prj_ui001")
                with self.assertRaises(HTTPError): call("/api/projects",{"project_id":"prj_uiambient","render_mode":"ambient_story","ambient_style":"quiet_verdict","content":"# Ambient\n\n## Narration\n\nA quiet verdict story.\n"})
                with self.assertRaises(HTTPError): call("/api/projects",{"project_id":"prj_uiambient_missing","render_mode":"ambient_story","content":"# Ambient\n\n## Narration\n\nMissing style.\n"})
                with self.assertRaises(HTTPError): call("/api/projects/prj_ui001/asset?path=../project.json")
            finally:
                server.shutdown();server.server_close();thread.join(5)

    def test_non_loopback_bind_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError): create_server(root,host="0.0.0.0",port=0)

    def test_new_video_client_transitions_from_creation_response_without_list_refresh(self):
        """A created project must become visible even if a later home refresh is slow or unavailable."""
        script=(Path(__file__).parents[1]/"story_auto/ui/static/app.js").read_text(encoding="utf-8")
        success=script.split("const created = await api('/api/projects'",1)[1].split("} catch (error)",1)[0]
        self.assertIn("if (wizard.creating) return;",script)
        self.assertIn("wizard.creating = true",script)
        self.assertIn("state.project = created.project_id",success)
        self.assertIn("state.snapshot = await api(`/api/projects/${encodeURIComponent(created.project_id)}/workspace`)",success)
        self.assertIn("renderProject()",success)
        self.assertLess(success.index("state.project = created.project_id"),success.index("closeWizard()"))
        self.assertNotIn("await loadProjects()",success)
        self.assertIn("void runAction('run_to_final'",success)
        self.assertIn("wizard.creating = false; showWizardError",script)

    def test_new_video_browser_creation_transitions_while_home_refresh_is_slow(self):
        chrome=Path(os.environ.get("PROGRAMFILES(X86)",r"C:\\Program Files (x86)"))/"Google/Chrome/Application/chrome.exe"
        if not chrome.is_file(): self.skipTest("Google Chrome is not installed for the focused UI regression")
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as root, \
             patch("story_auto.application.operator.available_voices",return_value=("bm_george",)), \
             patch("story_auto.application.operator.KokoroLocalProvider.readiness",return_value=KokoroReadiness("READY","Kokoro is ready",None)):
            server=create_server(root,port=0)
            service=server.RequestHandlerClass.service
            original_list_projects=service.list_projects
            slow_home_refresh=False
            coordinator_runs=[]
            service.run_to_final=lambda project_id: coordinator_runs.append(project_id) or {"outcome":"SAFETY_BLOCKED"}
            def delayed_list_projects():
                if slow_home_refresh: time.sleep(2)
                return original_list_projects()
            service.list_projects=delayed_list_projects
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                with sync_playwright() as playwright:
                    browser=playwright.chromium.launch(headless=True,executable_path=str(chrome))
                    page=browser.new_page()
                    page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                    page.get_by_role("button",name="New video").first.click()
                    page.get_by_role("radio",name="Create from Story / Content").check()
                    page.get_by_role("button",name="Continue",exact=True).click()
                    page.get_by_label("Content",exact=True).fill("# UI response\n\n## Narration\n\nA disposable browser regression test.")
                    page.get_by_role("button",name="Continue",exact=True).click()
                    page.get_by_role("button",name="Continue",exact=True).click()
                    slow_home_refresh=True
                    page.get_by_role("button",name="Create video",exact=True).click()
                    self.assertIsNone(page.get_by_role("heading",name="UI response",exact=True).first.wait_for(timeout=750))
                    self.assertEqual(len(list((Path(root)/"projects").glob("prj_*"))),1)
                    page.wait_for_timeout(100)
                    self.assertEqual(len(coordinator_runs),1)
                    browser.close()
            finally:
                server.shutdown();server.server_close();thread.join(5)

    def test_production_action_outcomes_are_visible_without_provider_dispatch(self):
        """A 200 response from the coordinator must retain its operator meaning."""
        chrome=Path(os.environ.get("PROGRAMFILES(X86)",r"C:\\Program Files (x86)"))/"Google/Chrome/Application/chrome.exe"
        if not chrome.is_file(): self.skipTest("Google Chrome is not installed for the focused UI regression")
        from playwright.sync_api import sync_playwright
        project_id="prj_action_outcomes"
        stages={name:{"status":"COMPLETE" if name in {"SOURCE","TIMING","PLAN"} else "READY"} for name in ("SOURCE","TIMING","PLAN","VISUALS","QUALITY","RENDER")}
        stages["VISUALS"]={"status":"READY","completed_items":0,"total_items":7}
        ready={
            "project_id":project_id,"title":"Action outcomes","status":"Ready","final_path":None,"can_render_again":False,
            "summary":{"source":"Audio + SRT","style":"Ambient Story","quality":"Automatic","waveform":"On","resolution":"1920 × 1080"},
            "production":{"pipeline_status":"READY","active_stage":"VISUALS","stages":stages,"blocker":None,
                          "next_action":{"action":"run_to_final","label":"Continue production"},
                          "flow":{"required":True,"status":"CONNECTED","human_message":"Flow connected"}},
        }
        complete=deepcopy(ready); complete["status"]="Complete"; complete["final_path"]="output/final.mp4"
        complete["production"].update({"pipeline_status":"COMPLETE","active_stage":"RENDER","next_action":{"action":"open_final","label":"Open final video"}})
        with tempfile.TemporaryDirectory() as root:
            server=create_server(root,port=0); service=server.RequestHandlerClass.service
            service.create_project(project_id=project_id,render_mode="full_image",content="# Action outcomes\n\n## Narration\n\nDisposable UI fixture.")
            scenario={"workspace":ready,"result":{"outcome":"SAFETY_BLOCKED","reason_code":"FLOW_CDP_UNAVAILABLE","error":"Flow browser session is unavailable"},"next_workspace":None,"workspace_calls":0,"run_calls":0,"provider_dispatches":0,"delay":0}
            def workspace(_project_id):
                scenario["workspace_calls"]+=1
                return deepcopy(scenario["workspace"])
            def run(_project_id):
                scenario["run_calls"]+=1
                if scenario["delay"]: time.sleep(scenario["delay"])
                if scenario["next_workspace"] is not None:
                    scenario["workspace"]=deepcopy(scenario["next_workspace"])
                    scenario["next_workspace"]=None
                return deepcopy(scenario["result"])
            def generate(*_args,**_kwargs):
                scenario["provider_dispatches"]+=1
                raise AssertionError("result rendering must not dispatch media")
            service.project_workspace=workspace; service.run_to_final=run; service.generate=generate
            plan_actions=[]
            def approve_plan(_project_id):
                plan_actions.append("approve_plan")
                return {"plan_approval":"APPROVED"}
            def plan_visuals(_project_id):
                plan_actions.append("plan_visuals")
                scenario["workspace"]=deepcopy(ready)
                return {"generation_requests":"prepared"}
            service.approve_planning=approve_plan; service.plan_visuals=plan_visuals
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                with sync_playwright() as playwright:
                    browser=playwright.chromium.launch(headless=True,executable_path=str(chrome))
                    page=browser.new_page(); page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                    page.get_by_role("button",name="View project",exact=True).click()
                    def continue_production():
                        page.get_by_role("button",name="Continue production",exact=True).first.click()
                    def reload_project():
                        page.reload()
                        page.get_by_role("button",name="View project",exact=True).click()

                    continue_production()
                    self.assertIsNone(page.get_by_text("Production stopped safely",exact=True).wait_for(timeout=1500))
                    self.assertIsNone(page.get_by_text("Google Flow is not open",exact=True).wait_for(timeout=1500))
                    self.assertEqual(page.get_by_text("Project updated.",exact=True).count(),0)

                    scenario["result"]={"outcome":"SAFETY_BLOCKED","reason_code":"STAGE_NO_PROGRESS"}
                    reload_project()
                    continue_production()
                    self.assertIsNone(page.get_by_text("Production did not advance",exact=True).wait_for(timeout=1500))
                    self.assertIsNone(page.get_by_role("button",name="Refresh project",exact=True).wait_for(timeout=1500))

                    scenario["result"]={"outcome":"SAFETY_BLOCKED","reason_code":"TIMELINE_ALIGNMENT_MISMATCH","error":"TIMELINE_ALIGNMENT_MISMATCH"}
                    reload_project()
                    continue_production()
                    self.assertIsNone(page.get_by_text("Imported subtitle timing needs attention",exact=True).wait_for(timeout=1500))
                    self.assertIsNone(page.get_by_role("button",name="Review project",exact=True).wait_for(timeout=1500))
                    self.assertEqual(page.get_by_text("Story Auto couldn't continue",exact=True).count(),0)
                    self.assertEqual(page.get_by_role("button",name="Try again",exact=True).count(),0)

                    scenario["result"]={"outcome":"AUTH_REQUIRED","flow":{"status":"AUTH_REQUIRED","human_message":"Sign in to Flow to continue","next_action":{"action":"open_flow_sign_in","label":"Sign in to Flow"}}}
                    reload_project()
                    continue_production()
                    self.assertIsNone(page.get_by_role("button",name="Sign in to Flow",exact=True).wait_for(timeout=1500))

                    scenario["result"]={"outcome":"OWNER_DECISION_REQUIRED","production":{"blocker":{"human_message":"Review and approve the production plan before visuals are created.","next_action":"Review plan"},"next_action":{"action":"review_plan","label":"Review plan"}}}
                    reload_project()
                    continue_production()
                    self.assertIsNone(page.get_by_role("button",name="Review plan",exact=True).wait_for(timeout=1500))

                    # A generic outcome from the preceding action must not
                    # replace a fresh canonical plan decision in the project
                    # workspace.  Review Plan must retain the existing review
                    # route, and approval must advance the temporary project
                    # without generating provider work.
                    plan_blocked=deepcopy(ready); plan_blocked["status"]="Action needed"
                    plan_blocked["production"].update({
                        "pipeline_status":"OWNER_DECISION_REQUIRED", "active_stage":"PLAN",
                        "blocker":{"reason_code":"OWNER_DECISION_REQUIRED", "human_message":"Review and approve the production plan before visuals are created.", "next_action":"Review plan"},
                        "next_action":{"action":"review_plan", "label":"Review plan"},
                    })
                    plan_blocked["production"]["stages"]["PLAN"]={"status":"BLOCKED"}
                    scenario["workspace"]=ready; scenario["next_workspace"]=plan_blocked; scenario["result"]={"outcome":"SAFETY_BLOCKED","reason_code":"STAGE_NO_PROGRESS"}
                    reload_project(); continue_production()
                    self.assertIsNone(page.get_by_role("button",name="Review plan",exact=True).wait_for(timeout=1500))
                    self.assertEqual(page.get_by_role("button",name="Try again",exact=True).count(),0)
                    self.assertEqual(page.get_by_text("Production stopped safely",exact=True).count(),0)
                    page.get_by_role("button",name="Review plan",exact=True).click()
                    self.assertIsNone(page.get_by_role("heading",name="Review the story plan",exact=True).wait_for(timeout=1500))
                    page.get_by_role("button",name="Approve story plan",exact=True).click()
                    self.assertIsNone(page.get_by_role("button",name="Continue production",exact=True).wait_for(timeout=1500))
                    self.assertEqual(plan_actions,["approve_plan","plan_visuals"])

                    for durable_state, action_id, label in (("NEEDS_ATTENTION","review_recovery","Review recovery"), ("BLOCKED","open_flow_sign_in","Open Flow sign-in")):
                        specific=deepcopy(ready)
                        specific["production"].update({
                            "pipeline_status":durable_state, "active_stage":"VISUALS",
                            "blocker":{"reason_code":"POLICY_PROMPT_REPAIR_REQUIRED" if action_id == "review_recovery" else "AUTH_REQUIRED", "human_message":"Synthetic durable recovery action.", "next_action":label},
                            "next_action":{"action":action_id,"label":label},
                        })
                        scenario["workspace"]=ready; scenario["next_workspace"]=specific; scenario["result"]={"outcome":"SAFETY_BLOCKED","reason_code":"STAGE_NO_PROGRESS"}
                        reload_project(); continue_production()
                        self.assertIsNone(page.get_by_role("button",name=label,exact=True).wait_for(timeout=1500))
                        self.assertEqual(page.get_by_role("button",name="Try again",exact=True).count(),0)

                    running=deepcopy(ready); running["production"]["pipeline_status"]="RUNNING"; running["production"]["stages"]["VISUALS"]={"status":"RUNNING","completed_items":1,"total_items":7}
                    scenario["workspace"]=running; scenario["result"]={"outcome":"PRODUCTION_PROGRESS"}
                    reload_project()
                    self.assertEqual(page.locator("#runtimeState").text_content(),"Working")
                    self.assertIsNone(page.get_by_text("Creating visuals").first.wait_for(timeout=1500))

                    scenario["workspace"]=ready; scenario["delay"]=3; before_poll=scenario["workspace_calls"]
                    reload_project()
                    continue_production()
                    self.assertEqual(page.locator("#runtimeState").text_content(),"Working")
                    page.wait_for_timeout(2600)
                    self.assertGreater(scenario["workspace_calls"],before_poll)
                    page.wait_for_timeout(900)
                    self.assertEqual(page.locator("#runtimeState").text_content(),"Ready")
                    scenario["delay"]=0

                    # A client-owned request may still be in flight, but a
                    # fresh terminal/recovery snapshot must immediately win
                    # the user-visible activity label and primary copy.
                    for recovery_state in ("RECOVERY_READY", "NEEDS_ATTENTION", "BLOCKED", "COMPLETE"):
                        stopped=deepcopy(complete if recovery_state == "COMPLETE" else ready)
                        stopped["production"].update({"pipeline_status":recovery_state,
                                                        "recovery":{"status":recovery_state,
                                                                    "human_message":"Synthetic safe stop"}})
                        stopped["production"]["stages"]["VISUALS"]={"status":recovery_state,"completed_items":1,"total_items":7}
                        scenario["workspace"]=ready; scenario["result"]={"outcome":recovery_state}; scenario["delay"]=3
                        reload_project(); continue_production(); scenario["workspace"]=stopped
                        page.wait_for_timeout(2600)
                        self.assertEqual(page.locator("#runtimeState").text_content(),"Ready")
                        self.assertEqual(page.get_by_role("button",name="Working…",exact=True).count(),0)
                        page.wait_for_timeout(900)
                    scenario["delay"]=0

                    scenario["workspace"]=complete; scenario["result"]={"outcome":"FINAL_VIDEO_COMPLETE","production":complete["production"]}
                    reload_project()
                    self.assertIsNone(page.get_by_role("heading",name="Your final video is ready.",exact=True).wait_for(timeout=1500))
                    browser.close()
            finally:
                server.shutdown();server.server_close();thread.join(5)
        self.assertEqual(scenario["provider_dispatches"],0)

    def test_primary_operator_flow_endpoints_and_advanced_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            server=create_server(root,port=0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            base=f"http://127.0.0.1:{server.server_address[1]}"
            def call(path,body=None):
                data=None if body is None else json.dumps(body).encode()
                request=Request(base+path,data=data,headers={"Content-Type":"application/json"})
                with urlopen(request,timeout=5) as response: return response.status,json.loads(response.read())
            try:
                status,inspection=call("/api/validate-content",{"content":"# The Last Letter\n\n## Narration\n\nA letter waited on the table.\n"})
                self.assertEqual((status,inspection["status"],inspection["title"]),(200,"VALID","The Last Letter"))
                with self.assertRaises(HTTPError): call("/api/validate-content",{"content":"# Missing narration"})
                status,created=call("/api/projects",{"project_id":"prj_flow_a","render_mode":"full_image","content":"# The Last Letter\n\n## Narration\n\nA letter waited on the table.\n"})
                self.assertEqual((status,created["user_status"],created["primary_action"]["action"]),(201,"Create video","Create video"))
                _,projects=call("/api/projects"); self.assertEqual(projects["projects"][0]["title"],"The Last Letter")
                _,settings=call("/api/settings"); self.assertEqual(settings["defaults"]["voice_name"],"George")
                _,diagnostics=call("/api/projects/prj_flow_a/diagnostics")
                self.assertEqual(diagnostics["snapshot"]["project_id"],"prj_flow_a")
                self.assertIn("planning",diagnostics); self.assertIn("media",diagnostics)
            finally:
                server.shutdown();server.server_close();thread.join(5)


if __name__ == "__main__": unittest.main()
