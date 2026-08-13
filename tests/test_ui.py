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
                status,html,kind=call("/"); self.assertEqual((status,kind),(200,"text/html")); self.assertIn(b"Story Auto Operator",html)
                status,payload,_=call("/api/projects",{"project_id":"prj_ui001","render_mode":"hybrid_hook","content":"# Story\n\n## Narration\n\nA local operator test.\n"}); self.assertEqual(status,201)
                created=json.loads(payload); self.assertEqual(created["content_status"],"VALID")
                _,payload,_=call("/api/projects/prj_ui001/actions",{"action":"save_content","content":"# Story\n\n## Narration\n\nUpdated through the shared service.\n"}); self.assertIn(b"Updated through the shared service",payload)
                _,payload,_=call("/api/projects/prj_ui001/snapshot"); self.assertEqual(json.loads(payload)["project_id"],"prj_ui001")
                with self.assertRaises(HTTPError): call("/api/projects/prj_ui001/asset?path=../project.json")
            finally:
                server.shutdown();server.server_close();thread.join(5)

    def test_non_loopback_bind_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError): create_server(root,host="0.0.0.0",port=0)


if __name__ == "__main__": unittest.main()
