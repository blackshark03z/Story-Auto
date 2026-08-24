from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
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
                self.assertIn(b"requestPause",script); self.assertIn(b"focusWizardStep",script); self.assertIn(b"aria-invalid",script)
                self.assertIn(b"data-error-action",script); self.assertIn(b'id="busyReason"',script)
                self.assertIn(b"KOKORO_MODEL_NOT_FOUND",script); self.assertIn(b"Kokoro model files are missing",script)
                self.assertIn(b"KOKORO_RUNTIME_LOAD_FAILED",script); self.assertIn(b"Kokoro readiness",script)
                self.assertIn(b"AMBIENT_VISUAL_BRIEF_OVER_BUDGET",script); self.assertIn(b"Visual planning needs to be regenerated",script)
                self.assertIn(b"PROJECT_LOCKED",script); self.assertIn(b"This project is still working",script)
                self.assertIn(b"ArtifactWriteError",script); self.assertIn(b"does not send another Flow request",script)
                self.assertIn(b"issue.technical_code || issue.request_id",script)
                self.assertIn(b"const projectId = state.project",script)
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
                self.assertNotIn(b"zoom percentage",script); self.assertNotIn(b"particle count",script)
                status,payload,_=call("/api/projects",{"project_id":"prj_ui001","render_mode":"hybrid_hook","content":"# Story\n\n## Narration\n\nA local operator test.\n"}); self.assertEqual(status,201)
                created=json.loads(payload); self.assertEqual(created["content_status"],"VALID")
                _,payload,_=call("/api/projects/prj_ui001/actions",{"action":"save_content","content":"# Story\n\n## Narration\n\nUpdated through the shared service.\n"}); self.assertIn(b"Updated through the shared service",payload)
                _,payload,_=call("/api/projects/prj_ui001/snapshot"); self.assertEqual(json.loads(payload)["project_id"],"prj_ui001")
                status,payload,_=call("/api/projects",{"project_id":"prj_uiambient","render_mode":"ambient_story","ambient_style":"quiet_verdict","content":"# Ambient\n\n## Narration\n\nA quiet verdict story.\n"})
                ambient=json.loads(payload); self.assertEqual((status,ambient["render_mode"],ambient["ambient_style_label"]),(201,"ambient_story","Quiet Verdict"))
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
        self.assertIn("state.snapshot = created",success)
        self.assertIn("renderProject()",success)
        self.assertLess(success.index("state.project = created.project_id"),success.index("closeWizard()"))
        self.assertNotIn("await loadProjects()",success)
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
                    page.get_by_label("Content",exact=True).fill("# UI response\n\n## Narration\n\nA disposable browser regression test.")
                    page.get_by_role("button",name="Continue",exact=True).click()
                    page.get_by_role("button",name="Continue",exact=True).click()
                    slow_home_refresh=True
                    page.get_by_role("button",name="Create video",exact=True).click()
                    self.assertIsNone(page.get_by_role("heading",name="UI response",exact=True).first.wait_for(timeout=750))
                    self.assertEqual(len(list((Path(root)/"projects").glob("prj_*"))),1)
                    browser.close()
            finally:
                server.shutdown();server.server_close();thread.join(5)

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
                status,created=call("/api/projects",{"project_id":"prj_flow_a","render_mode":"hybrid_hook","content":"# The Last Letter\n\n## Narration\n\nA letter waited on the table.\n"})
                self.assertEqual((status,created["user_status"],created["primary_action"]["action"]),(201,"Ready to start","Start production"))
                _,projects=call("/api/projects"); self.assertEqual(projects["projects"][0]["title"],"The Last Letter")
                _,settings=call("/api/settings"); self.assertEqual(settings["defaults"]["voice_name"],"George")
                _,diagnostics=call("/api/projects/prj_flow_a/diagnostics")
                self.assertEqual(diagnostics["snapshot"]["project_id"],"prj_flow_a")
                self.assertIn("planning",diagnostics); self.assertIn("media",diagnostics)
            finally:
                server.shutdown();server.server_close();thread.join(5)


if __name__ == "__main__": unittest.main()
