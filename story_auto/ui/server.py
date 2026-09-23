"""Loopback-only HTTP delivery for the Story Auto operator UI."""
from __future__ import annotations

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from story_auto.application import OperatorService
from story_auto.core.project import load_project

STATIC_ROOT=Path(__file__).with_name("static")
MAX_BODY=128*1024*1024


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

    def _asset(self, target: Path) -> None:
        """Stream one project asset and honor a browser's single byte range."""
        size = target.stat().st_size
        content = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        if requested is not None:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
            valid = bool(match and (match.group(1) or match.group(2)))
            if valid:
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                    valid = start < size and end >= start
                else:
                    suffix = int(last)
                    valid = suffix > 0 and size > 0
                    start = max(0, size - suffix)
                    end = size - 1
            if not valid:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
        self.send_response(HTTPStatus.PARTIAL_CONTENT if requested is not None else HTTPStatus.OK)
        self.send_header("Content-Type", content)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if requested is not None:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        remaining = end - start + 1
        try:
            with target.open("rb") as stream:
                stream.seek(start)
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self):
        try:
            parsed=urlparse(self.path); parts=[unquote(item) for item in parsed.path.split("/") if item]
            if not parts: return self._static("index.html")
            if parts[0]=="static" and len(parts)==2: return self._static(parts[1])
            if parts==["api","settings"]: return self._json(self.service.settings_overview())
            if parts==["api","flow-connection"]: return self._json(self.service.flow_connection_status())
            if parts==["api","creation-defaults"]: return self._json(self.service.creation_defaults())
            if parts==["api","runtime-attestation"]: return self._json(self.service.runtime_attestation())
            if parts==["api","projects"]: return self._json({"projects":self.service.list_projects()})
            if len(parts)>=3 and parts[:2]==["api","projects"]:
                project_id=parts[2]; view=parts[3] if len(parts)>3 else "snapshot"
                if view=="snapshot": result=self.service.snapshot(project_id)
                elif view=="production": result=self.service.production_query(project_id)
                elif view=="workspace": result=self.service.project_workspace(project_id)
                elif view=="opening": result=self.service.opening_builder(project_id)
                elif view=="content": result=self.service.get_content(project_id)
                elif view=="planning": result=self.service.planning_review(project_id)
                elif view=="media": result=self.service.media_items(project_id)
                elif view=="review": result=self.service.review_overview(project_id)
                elif view=="diagnostics": result=self.service.diagnostics(project_id)
                elif view=="asset":
                    relative=parse_qs(parsed.query).get("path",[""])[0]; paths,_=load_project(self.service.runtime,project_id); target=paths.artifact_path(relative)
                    return self._asset(target)
                else: raise ValueError("unknown view")
                return self._json(result)
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as error: self._json({"error":str(error)[-500:]},HTTPStatus.BAD_REQUEST)

    def do_POST(self):
        try:
            parts=[unquote(item) for item in urlparse(self.path).path.split("/") if item]; body=self._body()
            if parts==["api","validate-content"]:
                return self._json(self.service.inspect_content(body.get("content","")))
            if parts==["api","validate-imports"]:
                return self._json(self.service.inspect_imports(source_mode=body.get("source_mode",""),imported_audio=body.get("imported_audio"),imported_srt=body.get("imported_srt")))
            if parts==["api","settings","defaults"]:
                return self._json(self.service.update_runtime_defaults(body.get("defaults",{})))
            if parts==["api","settings","pexels","save"]:
                return self._json(self.service.save_pexels_key(body.get("keys",body.get("key",""))))
            if parts==["api","settings","pexels","test"]:
                return self._json(self.service.test_pexels_connection())
            if parts==["api","settings","pexels","clear"]:
                return self._json(self.service.clear_pexels_key())
            if parts==["api","settings","byteplus","save"]:
                return self._json(self.service.save_byteplus_key(body.get("keys",body.get("key",""))))
            if parts==["api","settings","byteplus","test"]:
                return self._json(self.service.test_byteplus_connection())
            if parts==["api","settings","byteplus","clear"]:
                return self._json(self.service.clear_byteplus_key())
            if parts==["api","settings","elyum","save"]:
                return self._json(self.service.save_elyum_key(body.get("keys",body.get("key",""))))
            if parts==["api","settings","elyum","test"]:
                return self._json(self.service.test_elyum_connection())
            if parts==["api","settings","elyum","clear"]:
                return self._json(self.service.clear_elyum_key())
            if parts==["api","settings","external-llm","configure"]:
                return self._json(self.service.configure_external_llm(base_url=body.get("base_url",""),model_alias=body.get("model_alias",""),auth_mode=body.get("auth_mode","x-api-key")))
            if parts==["api","settings","external-llm","save"]:
                return self._json(self.service.save_external_llm_keys(body.get("keys",body.get("key",""))))
            if parts==["api","settings","external-llm","test"]:
                return self._json(self.service.test_external_llm_connection())
            if parts==["api","settings","external-llm","clear"]:
                return self._json(self.service.clear_external_llm_keys())
            if parts==["api","settings","brain","gemini"]:
                return self._json(self.service.use_gemini_brain())
            if parts==["api","settings","dola","preview"]:
                return self._json(self.service.preview_dola_accounts(body.get("accounts", "")))
            if parts==["api","settings","dola","save"]:
                return self._json(self.service.save_dola_accounts(body.get("accounts", "")))
            if parts==["api","settings","dola","remove"]:
                return self._json(self.service.remove_dola_account(body.get("account_id", "")))
            if parts==["api","settings","flow-cookie","preview"]:
                return self._json(self.service.preview_flow_cookie_account(body.get('account_id',''),body.get('cookies','')))
            if parts==["api","settings","flow-cookie","save"]:
                return self._json(self.service.save_flow_cookie_account(body.get('account_id',''),body.get('cookies','')))
            if parts==["api","settings","flow-cookie","test"]:
                return self._json(self.service.test_flow_cookie_account(body.get('account_id',''),body.get('project_url','')))
            if parts==["api","settings","flow-cookie","remove"]:
                return self._json(self.service.remove_flow_cookie_account(body.get('account_id',''),body.get('expected_revision'),confirm_remove=body.get('confirm_remove') is True))
            if parts==["api","projects"]:
                return self._json(self.service.create_project(project_id=body.get("project_id"),render_mode=body.get("render_mode","full_image"),ambient_style=body.get("ambient_style"),content=body.get("content"),settings=body.get("settings"),imported_audio=body.get("imported_audio"),imported_srt=body.get("imported_srt")),HTTPStatus.CREATED)
            if parts==["api","flow-connection","validate"]:
                return self._json(self.service.flow_connections.validate_candidate(body.get("project_url", ""),required_capabilities=["IMAGE"]))
            if parts==["api","flow-connection","update"]:
                return self._json(self.service.update_runtime_flow_connection(body.get("project_url", "")))
            if len(parts)!=4 or parts[:2]!=["api","projects"] or parts[3]!="actions": raise ValueError("unknown action route")
            project_id=parts[2]; action=body.get("action")
            if action=="save_content": result=self.service.save_content(project_id,body.get("content",""))
            elif action in {"process", "run_to_final"}: result=self.service.run_to_final(project_id)
            elif action=="continue_production": result=self.service.continue_production(project_id)
            elif action=="set_execution_mode": result=self.service.set_execution_mode(project_id,body.get("mode",""))
            elif action=="set_qc_policy": result=self.service.set_qc_policy(project_id,body.get("policy",""))
            elif action=="query_qc_status": result=self.service.query_qc_status(project_id)
            elif action=="set_full_image_duration": result=self.service.set_full_image_duration(project_id,body.get("seconds"),body.get("cadence"))
            elif action=="set_full_image_audio_visualizer": result=self.service.set_full_image_audio_visualizer(project_id,body.get("enabled"))
            elif action=="approve_plan": result=self.service.approve_planning(project_id)
            elif action=="plan_visuals": result=self.service.plan_visuals(project_id)
            elif action=="approve_shots": result=self.service.approve_planning(project_id,shots=True)
            elif action=="generate": result=self.service.generate(project_id,request_ids=set(body.get("request_ids",[])) or None,max_requests=body.get("max_requests"))
            elif action=="pause": result=self.service.set_pause(project_id,True)
            elif action=="resume_generation": result=self.service.generate(project_id,max_requests=body.get("max_requests"))
            elif action=="open_flow_sign_in": result=self.service.open_flow_sign_in(project_id)
            elif action=="open_flow_project": result=self.service.open_flow_project(project_id)
            elif action=="ensure_flow_project": result=self.service.ensure_flow_project(project_id)
            elif action=="recheck_flow_generation": result=self.service.recheck_flow_generation(project_id)
            elif action=="flow_status": result=self.service.flow_status(project_id)
            elif action=="prepare_flow_recovery": result=self.service.prepare_flow_recovery(project_id)
            elif action=="validate_flow_connection": result=self.service.validate_flow_connection(project_id,body.get("project_url"))
            elif action=="rebind_flow_project": result=self.service.rebind_flow_project(project_id,explicit_owner_decision=body.get("explicit_owner_decision") is True)
            elif action=="update_flow_connection": result=self.service.update_flow_connection(project_id,body.get("project_url", ""),explicit_owner_decision=body.get("explicit_owner_decision") is True)
            elif action=="approve_asset": result=self.service.review_asset(project_id,body["request_id"],body["report"])
            elif action=="accept_pending_visuals_by_owner": result=self.service.accept_pending_visuals_by_owner(project_id,body.get("reason", ""))
            elif action=="accept_selected_assets": result=self.service.accept_selected_assets(project_id,set(body.get("request_ids", [])) or None,body.get("reason", ""))
            elif action=="reject_selected_assets": result=self.service.reject_selected_assets(project_id,set(body.get("request_ids", [])),body.get("reason", ""))
            elif action=="reopen_production_qc": result=self.service.reopen_false_positive_production_qc(
                project_id, body["request_id"], expected_asset_sha256=body["expected_asset_sha256"],
                reviewer=body.get("reviewer", "local_operator"), reason=body.get("reason", ""))
            elif action=="review_elyum_preview": result=self.service.review_full_video_preview(project_id,body["request_id"],decision=body.get("decision",""),reason=body.get("reason",""))
            elif action=="keep_elyum_preview": result=self.service.keep_full_video_preview(project_id,body["request_id"],confirm_spend=body.get("confirm_spend") is True)
            elif action=="kill_elyum_preview": result=self.service.kill_full_video_preview(project_id,body["request_id"],confirm_kill=body.get("confirm_kill") is True,reason=body.get("reason",""))
            elif action=="authorize_elyum_replacement": result=self.service.authorize_full_video_replacement(project_id,body["request_id"],reason=body.get("reason",""),confirm_replace=body.get("confirm_replace") is True,replacement_prompt=body.get("replacement_prompt"))
            elif action=="configure_opening_builder": result=self.service.configure_opening_builder(project_id,shared_context=body.get("shared_context",""),slots=body.get("slots",[]))
            elif action=="prepare_opening_builder": result=self.service.prepare_opening_builder(project_id)
            elif action=="plan_hybrid_body": result=self.service.plan_hybrid_body(project_id)
            elif action=="resolve_hybrid_stock_slot": result=self.service.resolve_hybrid_stock_slot(project_id,slot_id=body.get("slot_id",""))
            elif action=="import_hybrid_body_image": result=self.service.import_hybrid_body_image(project_id,slot_id=body.get("slot_id",""),imported_image=body.get("imported_image"),as_stock_fallback=body.get("as_stock_fallback") is True)
            elif action=="render_hybrid_preview": result=self.service.render_hybrid_preview(project_id)
            elif action=="generate_opening_api": result=self.service.generate_opening_api(project_id,slot_id=body.get("slot_id",""))
            elif action=="preflight_dola_opening": result=self.service.preflight_dola_opening(project_id,slot_id=body.get("slot_id",""),account_id=body.get("account_id",""))
            elif action=="generate_dola_opening": result=self.service.generate_dola_opening(project_id,slot_id=body.get("slot_id",""),account_id=body.get("account_id",""),confirm_generate=body.get("confirm_generate") is True,recovery_only=body.get("recovery_only") is True)
            elif action=="generate_flow_cookie_opening": result=self.service.generate_flow_cookie_opening(project_id,slot_id=body.get('slot_id',''),account_id=body.get('account_id',''),project_url=body.get('project_url',''),imported_reference=body.get('imported_reference'),confirm_generate=body.get('confirm_generate') is True,recovery_only=body.get('recovery_only') is True)
            elif action=="reset_unused_flow_cookie_opening": result=self.service.reset_unused_flow_cookie_opening(project_id,slot_id=body.get('slot_id',''),confirm_reset=body.get('confirm_reset') is True)
            elif action=="preflight_elyum_opening": result=self.service.preflight_elyum_opening(project_id,slot_id=body.get("slot_id",""))
            elif action=="generate_elyum_opening": result=self.service.generate_elyum_opening(project_id,slot_id=body.get("slot_id",""),model_id=body.get("model_id",""))
            elif action=="accept_elyum_opening": result=self.service.review_elyum_opening(project_id,slot_id=body.get("slot_id",""),decision="ACCEPT")
            elif action=="reject_elyum_opening": result=self.service.review_elyum_opening(project_id,slot_id=body.get("slot_id",""),decision="REJECT")
            elif action=="keep_elyum_opening": result=self.service.keep_elyum_opening(project_id,slot_id=body.get("slot_id",""),confirm_spend=body.get("confirm_spend") is True)
            elif action=="kill_elyum_opening": result=self.service.kill_elyum_opening(project_id,slot_id=body.get("slot_id",""))
            elif action=="import_opening_clip": result=self.service.import_opening_clip(project_id,slot_id=body.get("slot_id",""),imported_video=body.get("imported_video"))
            elif action=="reject_asset": result=self.service.reject_asset(project_id,body["request_id"],body.get("reason","operator visual rejection"))
            elif action=="regenerate": result=self.service.regenerate(project_id,body["request_id"],body.get("reason","operator requested regeneration"))
            elif action=="edit_prompt": result=self.service.edit_prompt(project_id,body["request_id"],body.get("prompt",""))
            elif action=="replace_asset": result=self.service.replace_asset(project_id,body["request_id"],body["source_path"])
            elif action=="media_override": result=self.service.set_media_override(project_id,body["shot_id"],body["media_type"],body.get("requirement","REQUIRED"))
            elif action=="build_render_plan": result=self.service.build_render_plan(project_id)
            elif action=="render": result=self.service.render(project_id)
            elif action=="render_again": result=self.service.render(project_id,force_final=True)
            elif action in {"metadata","prepare_thumbnail","finalize_thumbnail"}: result=self.service.publishing(project_id,action)
            elif action=="open_output": result={"path":self.service.open_output_folder(project_id)}
            else: raise ValueError("unknown action")
            self._json(result)
        except Exception as error:
            from story_auto.providers.dola_cookie.accounts import DolaAccountError
            if isinstance(error, DolaAccountError):
                return self._json({"error":str(error),"failure_class":"DOLA_ACCOUNT_INPUT_INVALID"},HTTPStatus.BAD_REQUEST)
            payload={"error":str(error)[-500:],"failure_class":getattr(error,"failure_class",type(error).__name__)}
            if hasattr(error,"readiness"): payload["readiness"]=error.readiness
            self._json(payload,HTTPStatus.BAD_REQUEST)

def create_server(runtime_root: Path | str, host: str="127.0.0.1", port: int=8765) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1","localhost","::1"}: raise ValueError("operator UI must bind to loopback")
    service=OperatorService(runtime_root, auto_flow_projects=True)
    handler=type("BoundOperatorHandler",(OperatorHandler,),{"service":service})
    return ThreadingHTTPServer((host,port),handler)


def serve(runtime_root: Path | str, host: str="127.0.0.1", port: int=8765) -> None:
    server=create_server(runtime_root,host,port)
    print(f"STORY_AUTO_UI=http://{server.server_address[0]}:{server.server_address[1]}",flush=True)
    try: server.serve_forever()
    finally: server.server_close()
