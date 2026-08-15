"""Loopback-only HTTP delivery for the Story Auto operator UI."""
from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from story_auto.application import OperatorService
from story_auto.core.project import load_project

STATIC_ROOT=Path(__file__).with_name("static")
MAX_BODY=1024*1024


class OperatorHandler(BaseHTTPRequestHandler):
    service: OperatorService
    server_version="StoryAutoOperator/1.0"

    def log_message(self, format: str, *args) -> None:  # keep provider/session details out of access logs
        return

    def _json(self, value, status=HTTPStatus.OK):
        payload=json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(payload))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(payload)

    def _body(self):
        length=int(self.headers.get("Content-Length","0"))
        if length<0 or length>MAX_BODY: raise ValueError("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _static(self, name: str):
        target=(STATIC_ROOT/name).resolve()
        if not target.is_relative_to(STATIC_ROOT.resolve()) or not target.is_file(): self.send_error(HTTPStatus.NOT_FOUND); return
        payload=target.read_bytes(); content=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type",content); self.send_header("Content-Length",str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def do_GET(self):
        try:
            parsed=urlparse(self.path); parts=[unquote(item) for item in parsed.path.split("/") if item]
            if not parts: return self._static("index.html")
            if parts[0]=="static" and len(parts)==2: return self._static(parts[1])
            if parts==["api","settings"]: return self._json(self.service.settings_overview())
            if parts==["api","projects"]: return self._json({"projects":self.service.list_projects()})
            if len(parts)>=3 and parts[:2]==["api","projects"]:
                project_id=parts[2]; view=parts[3] if len(parts)>3 else "snapshot"
                if view=="snapshot": result=self.service.snapshot(project_id)
                elif view=="content": result=self.service.get_content(project_id)
                elif view=="planning": result=self.service.planning_review(project_id)
                elif view=="media": result=self.service.media_items(project_id)
                elif view=="review": result=self.service.review_overview(project_id)
                elif view=="diagnostics": result=self.service.diagnostics(project_id)
                elif view=="asset":
                    relative=parse_qs(parsed.query).get("path",[""])[0]; paths,_=load_project(self.service.runtime,project_id); target=paths.artifact_path(relative)
                    payload=target.read_bytes(); content=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    self.send_response(HTTPStatus.OK); self.send_header("Content-Type",content); self.send_header("Content-Length",str(len(payload))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(payload); return
                else: raise ValueError("unknown view")
                return self._json(result)
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as error: self._json({"error":str(error)[-500:]},HTTPStatus.BAD_REQUEST)

    def do_POST(self):
        try:
            parts=[unquote(item) for item in urlparse(self.path).path.split("/") if item]; body=self._body()
            if parts==["api","validate-content"]:
                return self._json(self.service.inspect_content(body.get("content","")))
            if parts==["api","projects"]:
                return self._json(self.service.create_project(project_id=body.get("project_id"),render_mode=body.get("render_mode","hybrid_hook"),content=body.get("content"),settings=body.get("settings")),HTTPStatus.CREATED)
            if len(parts)!=4 or parts[:2]!=["api","projects"] or parts[3]!="actions": raise ValueError("unknown action route")
            project_id=parts[2]; action=body.get("action")
            if action=="save_content": result=self.service.save_content(project_id,body.get("content",""))
            elif action=="process": result=self.service.start_or_resume(project_id)
            elif action=="approve_plan": result=self.service.approve_planning(project_id)
            elif action=="plan_visuals": result=self.service.plan_visuals(project_id)
            elif action=="approve_shots": result=self.service.approve_planning(project_id,shots=True)
            elif action=="generate": result=self.service.generate(project_id,request_ids=set(body.get("request_ids",[])) or None,max_requests=body.get("max_requests"))
            elif action=="pause": result=self.service.set_pause(project_id,True)
            elif action=="resume_generation": result=self.service.generate(project_id,max_requests=body.get("max_requests"))
            elif action=="open_flow_sign_in": result=self.service.open_flow_sign_in(project_id)
            elif action=="approve_asset": result=self.service.review_asset(project_id,body["request_id"],body["report"])
            elif action=="reject_asset": result=self.service.reject_asset(project_id,body["request_id"],body.get("reason","operator visual rejection"))
            elif action=="regenerate": result=self.service.regenerate(project_id,body["request_id"],body.get("reason","operator requested regeneration"))
            elif action=="edit_prompt": result=self.service.edit_prompt(project_id,body["request_id"],body.get("prompt",""))
            elif action=="replace_asset": result=self.service.replace_asset(project_id,body["request_id"],body["source_path"])
            elif action=="media_override": result=self.service.set_media_override(project_id,body["shot_id"],body["media_type"],body.get("requirement","REQUIRED"))
            elif action=="build_render_plan": result=self.service.build_render_plan(project_id)
            elif action=="render": result=self.service.render(project_id)
            elif action in {"metadata","prepare_thumbnail","finalize_thumbnail"}: result=self.service.publishing(project_id,action)
            elif action=="open_output": result={"path":self.service.open_output_folder(project_id)}
            else: raise ValueError("unknown action")
            self._json(result)
        except Exception as error: self._json({"error":str(error)[-500:],"failure_class":getattr(error,"failure_class",type(error).__name__)},HTTPStatus.BAD_REQUEST)

def create_server(runtime_root: Path | str, host: str="127.0.0.1", port: int=8765) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1","localhost","::1"}: raise ValueError("operator UI must bind to loopback")
    service=OperatorService(runtime_root)
    handler=type("BoundOperatorHandler",(OperatorHandler,),{"service":service})
    return ThreadingHTTPServer((host,port),handler)


def serve(runtime_root: Path | str, host: str="127.0.0.1", port: int=8765) -> None:
    server=create_server(runtime_root,host,port)
    print(f"STORY_AUTO_UI=http://{server.server_address[0]}:{server.server_address[1]}",flush=True)
    try: server.serve_forever()
    finally: server.server_close()
