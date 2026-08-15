from __future__ import annotations

import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from story_auto.ui import create_server


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
                self.assertIn(b"const projectId = state.project",script)
                self.assertIn(b"state.view === 'project' && state.project === projectId",script)
                self.assertIn(b"Create again",script)
                self.assertIn(b"Use recovered file",script)
                self.assertIn(b"data-use-recovered",script)
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
