"""Operator-facing use cases over the canonical Story Auto core services."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, atomic_write_text, read_json
from story_auto.core.content import parse_content_markdown
from story_auto.core.planning import approve_plan, approve_shot_plan, run_planning_stages, run_visual_planning_stages
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project
from story_auto.core.publishing import finalize_thumbnail, prepare_thumbnail_request, run_publishing_metadata
from story_auto.core.render import resolve_render_plan, run_render_stages
from story_auto.pipeline import run_audio_stages, run_content_stage
from story_auto.providers.flow import (
    FlowExecutor, FlowRuntime, adopt_manual_recovery, execute_generation, preflight,
    reject_selected_asset,
)
from story_auto.providers.flow.service import queue_regeneration, review_production_asset
from story_auto.providers.flow.live import FlowInspector, LiveFlowGenerator


class OperatorServiceError(RuntimeError):
    pass


def _safe_json(path: Path, default: Any) -> Any:
    try: return read_json(path)
    except Exception: return default


def _identity(value: dict[str, Any], prefix: str = "req_ui_") -> str:
    body=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return prefix+hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


class OperatorService:
    """The single mutation surface used by both HTTP handlers and CLI additions."""

    def __init__(self, runtime_root: Path | str):
        self.runtime=RuntimeLayout.from_root(runtime_root).ensure()

    def list_projects(self) -> list[dict[str, Any]]:
        result=[]
        for path in sorted(self.runtime.projects.glob("prj_*")):
            if not path.is_dir(): continue
            try: result.append(self.snapshot(path.name))
            except Exception as error: result.append({"project_id":path.name,"status":"INVALID","error":str(error)})
        return result

    def create_project(self, *, project_id: str | None=None, render_mode: str="hybrid_hook",
                       content: str | None=None, settings: dict[str, Any] | None=None) -> dict[str, Any]:
        ident=project_id or "prj_"+uuid.uuid4().hex
        paths=create_project(self.runtime,ProjectConfig(ident,render_mode=render_mode,settings=settings or {}),content or "# Story\n\n## Narration\n\nWrite narration here.\n")
        return self.snapshot(paths.project_id)

    def _project(self, project_id: str): return load_project(self.runtime,project_id)

    def snapshot(self, project_id: str) -> dict[str, Any]:
        paths,config=self._project(project_id)
        content=paths.content_file.read_text(encoding="utf-8") if paths.content_file.is_file() else ""
        try: parse_content_markdown(content); content_status="VALID"
        except Exception: content_status="ACTION_REQUIRED"
        review=_safe_json(paths.artifact_path("output/review_state.json"),{})
        manifest=_safe_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[]})
        counts={}
        for entry in manifest.get("requests",[]): counts[entry.get("status","UNKNOWN")]=counts.get(entry.get("status","UNKNOWN"),0)+1
        artifacts={name:paths.artifact_path(f"output/{name}").is_file() for name in (
            "content_manifest.json","alignment.json","story_timeline.json","continuity_bible.json","shot_plan.json",
            "media_plan.json","generation_requests.json","render_plan.json","final.mp4","publishing_package.json")}
        blocked=[]
        if content_status!="VALID": blocked.append("VALID_NARRATION_REQUIRED")
        if review.get("plan_approval",{}).get("status")!="APPROVED" and artifacts["continuity_bible.json"]: blocked.append("PLANNING_APPROVAL_REQUIRED")
        if counts.get("QC_PENDING"): blocked.append("MEDIA_QC_REQUIRED")
        if counts.get("AUTH_REQUIRED"): blocked.append("FLOW_AUTH_REQUIRED")
        return {"project_id":project_id,"content_status":content_status,"render_mode":config.render_mode,
                "tts_provider":config.settings.get("tts",{}).get("provider","NOT_CONFIGURED"),
                "planning_status":"APPROVED" if review.get("plan_approval",{}).get("status")=="APPROVED" else ("VALIDATED" if artifacts["story_timeline.json"] else "NOT_STARTED"),
                "continuity_status":"READY" if artifacts["continuity_bible.json"] else "NOT_STARTED",
                "shot_plan_status":"READY" if artifacts["shot_plan.json"] else "NOT_STARTED",
                "generation_status":counts or {"NOT_STARTED":0},
                "render_status":"COMPLETE" if artifacts["final.mp4"] else ("PLANNED" if artifacts["render_plan.json"] else "NOT_STARTED"),
                "publishing_status":"READY" if artifacts["publishing_package.json"] else "NOT_STARTED",
                "blocked":blocked,"artifacts":artifacts,"project_path":str(paths.root)}

    def get_content(self, project_id: str) -> dict[str, str]:
        paths,_=self._project(project_id); text=paths.content_file.read_text(encoding="utf-8")
        try: narration=parse_content_markdown(text).narration; status="VALID"
        except Exception as error: narration=""; status=str(error)
        return {"content":text,"narration":narration,"status":status}

    def save_content(self, project_id: str, content: str) -> dict[str, str]:
        parse_content_markdown(content)
        paths,_=self._project(project_id); atomic_write_text(paths.content_file,content)
        return self.get_content(project_id)

    def start_or_resume(self, project_id: str, *, planning_provider=None, audio_adapter=None) -> dict[str, Any]:
        paths,config=self._project(project_id); actions={"content":run_content_stage(self.runtime.root,project_id)}
        if "tts" in config.settings:
            actions["tts"],actions["alignment"]=run_audio_stages(self.runtime.root,project_id,adapter=audio_adapter)
        if "llm" in config.settings:
            if "tts" not in config.settings: raise OperatorServiceError("planning requires configured TTS")
            actions["timeline"],actions["continuity"]=run_planning_stages(self.runtime.root,project_id,provider=planning_provider)
        actions["snapshot"]=self.snapshot(project_id); return actions

    def planning_review(self, project_id: str) -> dict[str, Any]:
        paths,_=self._project(project_id)
        return {name:_safe_json(paths.artifact_path(f"output/{name}.json"),None) for name in ("story_timeline","continuity_bible","shot_plan","media_plan","generation_requests","review_state","publishing_package")}

    def plan_visuals(self, project_id: str, *, provider=None) -> dict[str, Any]:
        run_visual_planning_stages(self.runtime.root,project_id,provider=provider); return self.planning_review(project_id)

    def approve_planning(self, project_id: str, *, shots: bool=False) -> dict[str, Any]:
        (approve_shot_plan if shots else approve_plan)(self.runtime.root,project_id)
        return self.planning_review(project_id)

    def media_items(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        paths,_=self._project(project_id); requests=_safe_json(paths.artifact_path("output/generation_requests.json"),{"requests":[]}); manifest=_safe_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[]})
        entries={item.get("request_id"):item for item in manifest.get("requests",[])}; references=[]; shots=[]
        for request in requests.get("requests",[]):
            entry=entries.get(request.get("request_id"),{})
            item={"request":request,"status":entry.get("status","PENDING"),"selected_asset":entry.get("selected_asset"),"attempts":entry.get("attempts",[]),"quality_reviews":entry.get("quality_reviews",[]),"failure_class":entry.get("failure_class")}
            (references if request.get("purpose")=="REFERENCE" else shots).append(item)
        return {"references":references,"shots":shots}

    def review_asset(self, project_id: str, request_id: str, report: dict[str, Any]) -> dict[str, Any]:
        review_production_asset(self.runtime.root,project_id,request_id,report); return self.media_items(project_id)

    def reject_asset(self, project_id: str, request_id: str, reason: str) -> dict[str, Any]:
        reject_selected_asset(self.runtime.root,project_id,request_id,reason=reason); return self.media_items(project_id)

    def regenerate(self, project_id: str, request_id: str, reason: str="operator requested regeneration") -> dict[str, Any]:
        queue_regeneration(self.runtime.root,project_id,request_id,reason=reason); return self.media_items(project_id)

    def replace_asset(self, project_id: str, request_id: str, source: Path | str) -> dict[str, Any]:
        queue_regeneration(self.runtime.root,project_id,request_id,reason="operator local asset replacement")
        adopt_manual_recovery(self.runtime.root,project_id,request_id,Path(source),settings={"source":"operator_replacement"},attribution="operator-selected local file")
        return self.media_items(project_id)

    def edit_prompt(self, project_id: str, request_id: str, prompt: str) -> dict[str, Any]:
        if not isinstance(prompt,str) or not prompt.strip(): raise OperatorServiceError("prompt is required")
        paths,_=self._project(project_id); request_path=paths.artifact_path("output/generation_requests.json"); value=read_json(request_path); mapping={}; found=False
        for request in value.get("requests",[]):
            old=request["request_id"]
            changed=old==request_id
            deps=[mapping.get(dep,dep) for dep in request.get("depends_on",[])]
            changed=changed or deps!=request.get("depends_on",[])
            if old==request_id: request["prompt"]=prompt.strip(); found=True
            request["depends_on"]=deps
            if changed:
                seed={key:item for key,item in request.items() if key not in {"request_id","fingerprint"}}
                request["fingerprint"]=hashlib.sha256(json.dumps(seed,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
                request["request_id"]=_identity(seed); request["replaces_request_id"]=old; mapping[old]=request["request_id"]
        if not found: raise OperatorServiceError("request not found")
        atomic_write_json(request_path,value)
        media_path=paths.artifact_path("output/media_plan.json")
        if media_path.is_file():
            media=read_json(media_path)
            for item in media.get("shots",[]):
                if item.get("selected_request_id") in mapping: item["selected_request_id"]=mapping[item["selected_request_id"]]
            atomic_write_json(media_path,media)
        return self.media_items(project_id)

    def set_media_override(self, project_id: str, shot_id: str, media_type: str, requirement: str="REQUIRED", *, provider=None) -> dict[str, Any]:
        paths,config=self._project(project_id); media_type=media_type.upper(); requirement=requirement.upper()
        if config.render_mode=="full_video_ai" and (media_type,requirement)!=("VIDEO","REQUIRED"): raise OperatorServiceError("full_video_ai requires VIDEO / REQUIRED")
        project=read_json(paths.project_file); media=project["settings"].setdefault("media",{}); media.setdefault("overrides",{})[shot_id]={"media_type":media_type,"requirement":requirement}; atomic_write_json(paths.project_file,project)
        run_visual_planning_stages(self.runtime.root,project_id,provider=provider); return self.planning_review(project_id)

    def set_pause(self, project_id: str, paused: bool) -> dict[str, bool]:
        paths,_=self._project(project_id); atomic_write_json(paths.artifact_path("output/execution_control.json"),{"pause_requested":bool(paused)})
        return {"pause_requested":bool(paused)}

    def generate(self, project_id: str, *, request_ids: set[str] | None=None, executor: FlowExecutor | None=None, max_requests: int | None=None) -> dict[str, Any]:
        self.set_pause(project_id,False)
        if executor is None:
            paths,config=self._project(project_id); runtime=FlowRuntime.from_settings(paths.runtime,config.settings); capabilities=preflight(runtime,FlowInspector(runtime)); executor=FlowExecutor(capabilities,LiveFlowGenerator(runtime))
        return execute_generation(self.runtime.root,project_id,executor=executor,execute=True,request_ids=request_ids,production_batch=True,max_requests=max_requests)

    def build_render_plan(self, project_id: str) -> dict[str, Any]:
        paths,config=self._project(project_id); load=lambda name:read_json(paths.artifact_path(f"output/{name}.json"))
        settings=config.settings.get("render",{})
        plan=resolve_render_plan(project_id=project_id,project_root=paths.root,render_mode=config.render_mode,alignment=load("alignment"),shot_plan=load("shot_plan"),media_plan=load("media_plan"),generation_requests=load("generation_requests"),generation_manifest=load("generation_manifest"),settings=settings)
        atomic_write_json(paths.artifact_path("output/render_plan.json"),plan); return plan

    def render(self, project_id: str) -> dict[str, Any]: return run_render_stages(self.runtime.root,project_id)

    def publishing(self, project_id: str, action: str, *, provider=None) -> Any:
        if action=="metadata": return run_publishing_metadata(self.runtime.root,project_id,provider=provider)
        if action=="prepare_thumbnail": return prepare_thumbnail_request(self.runtime.root,project_id)
        if action=="finalize_thumbnail": return finalize_thumbnail(self.runtime.root,project_id)
        raise OperatorServiceError("unknown publishing action")

    def open_output_folder(self, project_id: str) -> str:
        paths,_=self._project(project_id); target=paths.root/"output"
        if os.name=="nt": os.startfile(target)  # type: ignore[attr-defined]
        return str(target)
