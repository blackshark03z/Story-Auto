"""Operator-facing use cases over the canonical Story Auto core services."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, atomic_write_text, read_json
from story_auto.core.content import parse_content_markdown
from story_auto.core.planning import approve_plan, approve_shot_plan, run_planning_stages, run_visual_planning_stages
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project
from story_auto.core.publishing import finalize_thumbnail, prepare_thumbnail_request, run_publishing_metadata
from story_auto.core.render import resolve_render_plan, resolve_render_settings, run_render_stages
from story_auto.core.visual import ambient_style_label, temporal_video_qc_applicability
from story_auto.pipeline import run_audio_stages, run_content_stage
from story_auto.providers.flow import (
    FlowExecutor, FlowRuntime, adopt_manual_recovery, execute_generation, launch_dedicated_session, preflight,
    reject_selected_asset,
)
from story_auto.providers.flow.service import queue_regeneration, review_production_asset
from story_auto.providers.flow.live import FlowInspector, LiveFlowGenerator
from story_auto.providers.tts.kokoro_local import KokoroLocalProvider


class OperatorServiceError(RuntimeError):
    pass


_ATTENTION = {
    "VALID_NARRATION_REQUIRED": {
        "title": "Content needs attention",
        "message": "Add one Narration section before Story Auto can begin.",
        "action": "Edit content",
        "action_id": "edit_content",
    },
    "PLANNING_APPROVAL_REQUIRED": {
        "title": "Review the production plan",
        "message": "Story Auto prepared the story plan and needs your approval before it creates visuals.",
        "action": "Review plan",
        "action_id": "review_plan",
    },
    "VISUAL_PLANNING_REGENERATION_REQUIRED": {
        "title": "Visual planning needs attention",
        "message": "Visual planning needs to be regenerated before Story Auto can create images.",
        "action": "Regenerate visual plan",
        "action_id": "review_plan",
    },
    "MEDIA_QC_REQUIRED": {
        "title": "Review generated visuals",
        "message": "Some generated scenes need a quick quality decision before production can continue.",
        "action": "Review visuals",
        "action_id": "review_visuals",
    },
    "FLOW_AUTH_REQUIRED": {
        "title": "Google sign-in required",
        "message": "Story Auto needs access to Google Flow before it can continue creating visuals.",
        "action": "Open Flow sign-in",
        "action_id": "open_flow_sign_in",
    },
    "PROVIDER_CREDITS_REQUIRED": {
        "title": "Provider credits required",
        "message": "Add credits to the visual provider account before Story Auto can continue.",
        "action": "Review recovery steps",
        "action_id": "review_project",
    },
    "GENERATION_SETUP_REQUIRED": {
        "title": "Visual setup needs attention",
        "message": "A provider capability or project setting must be corrected before visual creation can continue.",
        "action": "Review recovery steps",
        "action_id": "review_project",
    },
    "GENERATION_CANCELLED": {
        "title": "Visual creation was cancelled",
        "message": "Review the affected visual before deciding whether to create it again.",
        "action": "Review project",
        "action_id": "review_project",
    },
    "GENERATION_RECONCILIATION_REQUIRED": {
        "title": "Confirm a Flow result",
        "message": "Story Auto could not confirm whether Flow created a visual. Check Flow and attach the recovered file before continuing.",
        "action": "Review recovery",
        "action_id": "review_project",
    },
}


def _content_title(content: str, project_id: str, publishing: dict[str, Any]) -> str:
    selected = publishing.get("selected_title")
    if isinstance(selected, str) and selected.strip():
        return selected.strip()
    for line in content.splitlines():
        if re.match(r"^#\s+\S", line):
            return line[2:].strip()
    words = project_id.removeprefix("prj_").replace("_", " ").replace("-", " ").split()
    return " ".join(word.upper() if word.lower().startswith("v") and word[1:].isdigit() else word.capitalize() for word in words) or "Untitled video"


def _updated_at(paths) -> str:
    candidates = [paths.project_file, paths.content_file]
    output = paths.root / "output"
    if output.is_dir():
        candidates.extend(path for path in output.iterdir() if path.is_file())
    stamp = max((path.stat().st_mtime for path in candidates if path.is_file()), default=paths.root.stat().st_mtime)
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _word_count(narration: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", narration, flags=re.UNICODE))


def _creation_settings(settings: dict[str, Any], voice_id: str) -> dict[str, Any]:
    """Build new-project defaults from a small secret-free global allowlist."""
    llm=settings.get("llm",{}) if isinstance(settings,dict) else {}
    flow=settings.get("flow",{}) if isinstance(settings,dict) else {}
    tts=settings.get("tts",{}) if isinstance(settings,dict) else {}
    kokoro=tts.get("kokoro_local",{}) if isinstance(tts,dict) else {}
    result={
        "llm":{"provider":str(llm.get("provider","gemini")),"model":str(llm.get("model","gemini-3.5-flash"))},
        "tts":{"provider":"kokoro_local","allow_cross_provider_fallback":False,"kokoro_local":{
            "voice_id":voice_id,
            "runtime_path":str(kokoro.get("runtime_path") or Path(os.environ.get("STORY_AUTO_KOKORO_RUNTIME","D:/kokoro"))),
            "device":str(kokoro.get("device","cpu")),
            "speed":float(kokoro.get("speed",1.0)),
            "language":str(kokoro.get("language","b")),
        }},
    }
    model_cache=kokoro.get("model_cache") or os.environ.get("STORY_AUTO_KOKORO_MODEL_CACHE")
    model_snapshot=kokoro.get("model_snapshot") or os.environ.get("STORY_AUTO_KOKORO_MODEL_SNAPSHOT")
    if isinstance(model_cache,str) and model_cache.strip():
        result["tts"]["kokoro_local"]["model_cache"]=model_cache
    if isinstance(model_snapshot,str) and model_snapshot.strip():
        result["tts"]["kokoro_local"]["model_snapshot"]=model_snapshot
    if isinstance(llm.get("max_attempts"),int): result["llm"]["max_attempts"]=llm["max_attempts"]
    safe_flow={key:str(flow[key]) for key in ("cdp_url","project_url","project_identity") if isinstance(flow.get(key),str)}
    if safe_flow: result["flow"]=safe_flow
    return result


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
        for path in self.runtime.projects.glob("prj_*"):
            if not path.is_dir(): continue
            try: result.append(self.snapshot(path.name))
            except Exception as error: result.append({"project_id":path.name,"status":"INVALID","error":str(error)})
        return sorted(result,key=lambda item:item.get("updated_at", ""),reverse=True)

    def create_project(self, *, project_id: str | None=None, render_mode: str="hybrid_hook",
                       ambient_style: str | None=None, content: str | None=None,
                       settings: dict[str, Any] | None=None) -> dict[str, Any]:
        ident=project_id or "prj_"+uuid.uuid4().hex
        resolved_settings=dict(settings or {})
        if ambient_style is not None: resolved_settings["ambient_style"]=ambient_style
        paths=create_project(self.runtime,ProjectConfig(ident,render_mode=render_mode,settings=resolved_settings),content or "# Story\n\n## Narration\n\nWrite narration here.\n")
        return self.snapshot(paths.project_id)

    def _project(self, project_id: str): return load_project(self.runtime,project_id)

    def snapshot(self, project_id: str) -> dict[str, Any]:
        paths,config=self._project(project_id)
        content=paths.content_file.read_text(encoding="utf-8") if paths.content_file.is_file() else ""
        try:
            narration=parse_content_markdown(content).narration; content_status="VALID"
        except Exception:
            narration=""; content_status="ACTION_REQUIRED"
        review=_safe_json(paths.artifact_path("output/review_state.json"),{})
        manifest=_safe_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[]})
        requests=_safe_json(paths.artifact_path("output/generation_requests.json"),{"requests":[]})
        alignment=_safe_json(paths.artifact_path("output/alignment.json"),{})
        publishing=_safe_json(paths.artifact_path("output/publishing_package.json"),{})
        active_request_ids={item.get("request_id") for item in requests.get("requests",[]) if item.get("request_id")}
        entries={item.get("request_id"):item for item in manifest.get("requests",[]) if item.get("request_id") in active_request_ids}
        counts={}
        for entry in entries.values():
            counts[entry.get("status","UNKNOWN")]=counts.get(entry.get("status","UNKNOWN"),0)+1
        artifacts={name:paths.artifact_path(f"output/{name}").is_file() for name in (
            "content_manifest.json","alignment.json","story_timeline.json","continuity_bible.json","shot_plan.json",
            "media_plan.json","generation_requests.json","render_plan.json","final.mp4","publishing_package.json")}
        blocked=[]
        visual_planning=review.get("visual_planning",{}) if isinstance(review,dict) else {}
        if content_status!="VALID": blocked.append("VALID_NARRATION_REQUIRED")
        if visual_planning.get("status")=="NEEDS_REGENERATION": blocked.append("VISUAL_PLANNING_REGENERATION_REQUIRED")
        elif review.get("plan_approval",{}).get("status")!="APPROVED" and artifacts["continuity_bible.json"]: blocked.append("PLANNING_APPROVAL_REQUIRED")
        if counts.get("AUTH_REQUIRED"): blocked.append("FLOW_AUTH_REQUIRED")
        if counts.get("CREDIT_BLOCKED"): blocked.append("PROVIDER_CREDITS_REQUIRED")
        if counts.get("FAILED_PERMANENT") or counts.get("FAILED_FATAL"): blocked.append("GENERATION_SETUP_REQUIRED")
        if counts.get("CANCELLED"): blocked.append("GENERATION_CANCELLED")
        if counts.get("AMBIGUOUS"): blocked.append("GENERATION_RECONCILIATION_REQUIRED")
        if counts.get("QC_PENDING"): blocked.append("MEDIA_QC_REQUIRED")
        shot_groups={}
        for request in requests.get("requests",[]):
            if request.get("purpose")!="SHOT": continue
            shot_groups.setdefault(request.get("shot_id") or request.get("request_id"),[]).append(request.get("request_id"))
        total_visuals=len(shot_groups)
        finished_visuals=sum(all(entries.get(request_id,{}).get("status") in {"SUCCEEDED","QC_PENDING"} for request_id in request_ids) for request_ids in shot_groups.values())
        progress=0
        stage="Content"
        activity="Add approved narration to begin."
        if content_status=="VALID": progress,stage,activity=12,"Voice","Ready to create narration."
        if artifacts["alignment.json"]: progress,stage,activity=28,"Plan","Narration is ready. Planning the visual story."
        if artifacts["story_timeline.json"]: progress,stage,activity=40,"Plan","Story structure and continuity are ready."
        if artifacts["generation_requests.json"]:
            ratio=(finished_visuals/total_visuals) if total_visuals else 0
            progress,stage=45+round(35*ratio),"Create visuals"
            activity=f"Creating visuals — {finished_visuals} of {total_visuals} scenes" if total_visuals else "Visuals are ready to create."
        if counts.get("QC_PENDING"):
            progress,stage,activity=max(progress,78),"Quality check",f"Checking quality — {counts['QC_PENDING']} scene{'s' if counts['QC_PENDING']!=1 else ''} need review"
        if artifacts["render_plan.json"]:
            progress,stage,activity=max(progress,88),"Render","Rendering the final video."
        if artifacts["final.mp4"]:
            progress,stage,activity=100,"Finish","Final video is ready."

        plan_status=review.get("plan_approval",{}).get("status")
        if blocked:
            if blocked[0]=="MEDIA_QC_REQUIRED":
                progress,stage,activity=min(progress,94),"Quality check",f"{counts.get('QC_PENDING',0)} scene{'s' if counts.get('QC_PENDING',0)!=1 else ''} need quality review"
            elif blocked[0]=="FLOW_AUTH_REQUIRED":
                progress,stage,activity=min(progress,74),"Create visuals","Visual creation is waiting for Google sign-in."
            elif blocked[0]=="PLANNING_APPROVAL_REQUIRED":
                progress,stage,activity=min(progress,44),"Plan","The story plan is ready for review."
            elif blocked[0]=="VISUAL_PLANNING_REGENERATION_REQUIRED":
                progress,stage,activity=min(progress,44),"Plan","Visual planning needs to be regenerated."
            elif blocked[0] in {"PROVIDER_CREDITS_REQUIRED","GENERATION_SETUP_REQUIRED","GENERATION_CANCELLED","GENERATION_RECONCILIATION_REQUIRED"}:
                progress,stage,activity=min(progress,74),"Create visuals",_ATTENTION[blocked[0]]["message"]
            user_status="Needs your attention"
            primary_action=_ATTENTION.get(blocked[0],{"action":"Review project","action_id":"review_project"})
        elif artifacts["final.mp4"]:
            user_status="Complete"; primary_action={"action":"Open final video","action_id":"open_final"}
        elif any(counts.get(name) for name in {"PENDING","NOT_DISPATCHED","FAILED_RETRYABLE"}):
            user_status=activity; primary_action={"action":"Resume","action_id":"resume_generation"}
        elif artifacts["generation_requests.json"] and total_visuals and finished_visuals>=total_visuals:
            user_status="Ready to render"; primary_action={"action":"Render final video","action_id":"render"}
        elif artifacts["generation_requests.json"] and plan_status=="APPROVED":
            user_status="Ready to create visuals"; primary_action={"action":"Start visual creation","action_id":"resume_generation"}
        elif content_status=="VALID":
            user_status="Ready to start"; primary_action={"action":"Start production","action_id":"process"}
        else:
            user_status="Content needed"; primary_action={"action":"Add content","action_id":"edit_content"}

        thumbnail=publishing.get("thumbnail",{}).get("path") if isinstance(publishing,dict) else None
        duration=alignment.get("duration_seconds") if isinstance(alignment,dict) else None
        attention=[{**_ATTENTION.get(code,{"title":"Project needs attention","message":"Review the project details before continuing.","action":"Review project","action_id":"review_project"}),"code":code} for code in blocked]
        ambient_style=config.settings.get("ambient_style") if config.render_mode=="ambient_story" else None
        return {"project_id":project_id,"title":_content_title(content,project_id,publishing),"content_status":content_status,"render_mode":config.render_mode,
                "format_label":{"hybrid_hook":"Cinematic opening","full_video_ai":"Full video animation","ambient_story":"Ambient Story"}[config.render_mode],
                "ambient_style":ambient_style,"ambient_style_label":ambient_style_label(ambient_style),
                "tts_provider":config.settings.get("tts",{}).get("provider","NOT_CONFIGURED"),
                "planning_status":"ACTION_REQUIRED" if visual_planning.get("status")=="NEEDS_REGENERATION" else ("APPROVED" if review.get("plan_approval",{}).get("status")=="APPROVED" else ("VALIDATED" if artifacts["story_timeline.json"] else "NOT_STARTED")),
                "continuity_status":"READY" if artifacts["continuity_bible.json"] else "NOT_STARTED",
                "shot_plan_status":"READY" if artifacts["shot_plan.json"] else "NOT_STARTED",
                "generation_status":counts or {"NOT_STARTED":0},
                "render_status":"NOT_STARTED" if visual_planning.get("status")=="NEEDS_REGENERATION" else ("COMPLETE" if artifacts["final.mp4"] else ("PLANNED" if artifacts["render_plan.json"] else "NOT_STARTED")),
                "publishing_status":"READY" if artifacts["publishing_package.json"] else "NOT_STARTED",
                "blocked":blocked,"artifacts":artifacts,"project_path":str(paths.root),
                "user_status":user_status,"current_stage":stage,"current_activity":activity,"progress":min(100,progress),
                "completed_visuals":finished_visuals,"total_visuals":total_visuals,"primary_action":primary_action,
                "attention":attention,"work_saved":True,"updated_at":_updated_at(paths),"word_count":_word_count(narration),
                "duration_seconds":duration,"thumbnail_path":thumbnail,"final_path":"output/final.mp4" if artifacts["final.mp4"] and visual_planning.get("status")!="NEEDS_REGENERATION" else None,
                "visual_planning":visual_planning}

    def get_content(self, project_id: str) -> dict[str, str]:
        paths,_=self._project(project_id); text=paths.content_file.read_text(encoding="utf-8")
        try: narration=parse_content_markdown(text).narration; status="VALID"
        except Exception as error: narration=""; status=str(error)
        return {"content":text,"narration":narration,"status":status}

    def inspect_content(self, content: str) -> dict[str, Any]:
        narration=parse_content_markdown(content).narration
        words=_word_count(narration)
        title=_content_title(content,"prj_untitled",{})
        return {"status":"VALID","title":title,"word_count":words,"estimated_duration_seconds":round(words/150*60)}

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
        entries={item.get("request_id"):item for item in manifest.get("requests",[])}; references=[]; shots=[]; thumbnails=[]
        for request in requests.get("requests",[]):
            entry=entries.get(request.get("request_id"),{})
            item={"request":request,"status":entry.get("status","PENDING"),"selected_asset":entry.get("selected_asset"),"attempts":entry.get("attempts",[]),"quality_reviews":entry.get("quality_reviews",[]),"failure_class":entry.get("failure_class")}
            purpose=request.get("purpose")
            (references if purpose=="REFERENCE" else thumbnails if purpose=="THUMBNAIL" else shots).append(item)
        return {"references":references,"shots":shots,"thumbnails":thumbnails}

    def review_overview(self, project_id: str) -> dict[str, Any]:
        snapshot=self.snapshot(project_id); planning=self.planning_review(project_id); media=self.media_items(project_id)
        items=media["references"]+media["shots"]+media["thumbnails"]
        problems={"QC_PENDING","FAILED_RETRYABLE","FAILED_FATAL","FAILED_PERMANENT","AUTH_REQUIRED","CREDIT_BLOCKED","CANCELLED","AMBIGUOUS","REJECTED"}
        issues=[]
        for kind,group in (("Reference",media["references"]),("Scene",media["shots"]),("Thumbnail",media["thumbnails"])):
            for index,item in enumerate(group,1):
                status=item.get("status","PENDING")
                if status not in problems: continue
                request=item.get("request",{}); label=kind if kind=="Thumbnail" else f"{kind} {index}"
                if status=="QC_PENDING": message=f"{label} is ready for your quality review."
                elif status=="AUTH_REQUIRED": message=f"{label} is waiting for Google sign-in. Sign in, then choose Create again."
                elif status=="CREDIT_BLOCKED": message=f"{label} is waiting for provider credits. Add credits, then choose Create again."
                elif status=="FAILED_PERMANENT": message=f"{label} needs a provider setup or capability correction. Fix it, then choose Create again."
                elif status=="CANCELLED": message=f"{label} was cancelled. Choose Create again when you are ready."
                elif status=="AMBIGUOUS": message=f"Story Auto could not confirm whether Flow created {label.lower()}. Check Flow; if the result exists, download it and use the recovered file."
                else: message=f"{label} could not be completed and can be retried."
                recovery_action=("manual_asset" if status=="AMBIGUOUS" else "flow_sign_in_then_requeue" if status=="AUTH_REQUIRED" else "requeue" if status in {"FAILED_RETRYABLE","FAILED_FATAL","FAILED_PERMANENT","CREDIT_BLOCKED","CANCELLED","REJECTED"} else None)
                issues.append({"label":label,"scene":index if kind=="Scene" else None,"message":message,"status":status,"request_id":request.get("request_id"),"media_type":request.get("media_type"),"retryable":status in {"QC_PENDING","FAILED_RETRYABLE","FAILED_FATAL","FAILED_PERMANENT","AUTH_REQUIRED","CREDIT_BLOCKED","CANCELLED","REJECTED"},"recovery_action":recovery_action})
        pending=sum(1 for item in items if item.get("status") in problems)
        planning_state=(planning.get("review_state") or {}).get("visual_planning",{})
        planning_failed=planning_state.get("status")=="NEEDS_REGENERATION"
        visual_items=media["references"]+media["shots"]
        selected_visuals=[item for item in visual_items if item.get("status")=="SUCCEEDED" and item.get("selected_asset")]
        all_visuals_checked=bool(visual_items) and len(selected_visuals)==len(visual_items)
        if planning_failed:
            visual_match="Not available yet"
        elif not visual_items:
            visual_match="Not checked"
        elif not selected_visuals:
            visual_match="Needs review" if pending else "Pending"
        elif pending:
            visual_match="Needs review"
        else:
            visual_match="Passed" if all_visuals_checked else "Pending"
        if planning_failed:
            issues.insert(0,{"label":"Visual planning","scene":None,"message":"Visual planning needs to be regenerated before images can be created.","status":"NEEDS_REGENERATION","request_id":None,"media_type":None,"retryable":False,"recovery_action":None,"technical_code":planning_state.get("failure_class")})
        temporal_qc=temporal_video_qc_applicability(snapshot["render_mode"])
        has_video=any(item.get("request",{}).get("media_type")=="VIDEO" for item in items)
        video_problem=any(item.get("request",{}).get("media_type")=="VIDEO" and item.get("status") in problems for item in items)
        publishing=planning.get("publishing_package") or {}
        return {
            "project_id":project_id,"title":snapshot["title"],"duration_seconds":snapshot.get("duration_seconds"),
            "final_path":snapshot.get("final_path"),"publishing":publishing,
            "quality":[
                {"label":"Visual match","status":visual_match},
                {"label":"Motion quality","status":"Not applicable" if temporal_qc=="NOT_APPLICABLE" else ("Needs review" if video_problem else ("Passed" if has_video else "Waiting"))},
                {"label":"Naturalness","status":"Not available yet" if planning_failed else ("Needs review" if pending else ("Passed" if all_visuals_checked else ("Pending" if visual_items else "Waiting")))},
                {"label":"Final render","status":"Passed" if snapshot.get("final_path") else "Waiting"},
            ],
            "issues":issues,"work_saved":True,"temporal_video_qc":temporal_qc,
        }

    def settings_overview(self) -> dict[str, Any]:
        projects=self.list_projects()
        latest_settings={}
        if projects:
            try: _,config=self._project(projects[0]["project_id"]); latest_settings=config.settings
            except Exception: latest_settings={}
        tts=latest_settings.get("tts",{}) if isinstance(latest_settings,dict) else {}
        provider=tts.get("provider")
        kokoro_settings=tts.get("kokoro_local",{}) if isinstance(tts,dict) else {}
        flow=latest_settings.get("flow",{}) if isinstance(latest_settings,dict) else {}
        llm=latest_settings.get("llm",{}) if isinstance(latest_settings,dict) else {}
        flow_auth=any("FLOW_AUTH_REQUIRED" in item.get("blocked",[]) for item in projects)
        usage=shutil.disk_usage(self.runtime.root)
        voice_id=kokoro_settings.get("voice_id","bm_george") if isinstance(kokoro_settings,dict) else "bm_george"
        voices={"bm_george":"George","am_michael":"Michael","af_heart":"Heart"}
        creation_defaults=_creation_settings(latest_settings,voice_id)
        kokoro_readiness=None
        if provider=="kokoro_local":
            kokoro_readiness=KokoroLocalProvider().readiness(kokoro_settings)
            voice_row={"name":"Voice",
                       "detail":f"{voices.get(voice_id,voice_id)} — local narrator" if kokoro_readiness.ready else kokoro_readiness.user_message,
                       "status":"Ready" if kokoro_readiness.ready else "Needs attention",
                       "technical_code":kokoro_readiness.technical_code}
        else:
            voice_row={"name":"Voice","detail":f"{voices.get(voice_id,voice_id)} — local narrator" if provider else "Choose a narrator for new videos",
                       "status":"Ready" if provider else "Not configured"}
        return {
            "defaults":{"render_mode":"hybrid_hook","ambient_style":"quiet_verdict","voice_id":voice_id,"voice_name":voices.get(voice_id,voice_id),"production_style":"Natural cinematic"},
            "creation_defaults":creation_defaults,
            "providers":[
                voice_row,
                {"name":"Visual generation","detail":"Google Flow","status":"Sign-in required" if flow_auth else ("Ready" if flow else "Not configured")},
                {"name":"AI quality","detail":"Gemini planning and quality checks","status":"Ready" if llm else "Not configured"},
            ],
            "storage":{"project_location":str(self.runtime.projects),"free_gb":round(usage.free/(1024**3),1)},
            "advanced":{"runtime_root":str(self.runtime.root),"gemini_model":llm.get("model","gemini-3.5-flash"),"flow_project":flow.get("project_identity","Not configured"),"tts_provider":provider or "Not configured",
                        "kokoro_readiness":kokoro_readiness.as_dict() if kokoro_readiness else None},
        }

    def diagnostics(self, project_id: str) -> dict[str, Any]:
        return {"snapshot":self.snapshot(project_id),"planning":self.planning_review(project_id),"media":self.media_items(project_id)}

    def open_flow_sign_in(self, project_id: str) -> dict[str, str]:
        paths,config=self._project(project_id)
        launch_dedicated_session(FlowRuntime.from_settings(paths.runtime,config.settings))
        return {"status":"OPENED","message":"Complete Google sign-in in the Story Auto Flow window, then return and try again."}

    def review_asset(self, project_id: str, request_id: str, report: dict[str, Any]) -> dict[str, Any]:
        review_production_asset(self.runtime.root,project_id,request_id,report); return self.media_items(project_id)

    def reject_asset(self, project_id: str, request_id: str, reason: str) -> dict[str, Any]:
        reject_selected_asset(self.runtime.root,project_id,request_id,reason=reason); return self.media_items(project_id)

    def regenerate(self, project_id: str, request_id: str, reason: str="operator requested regeneration") -> dict[str, Any]:
        queue_regeneration(self.runtime.root,project_id,request_id,reason=reason); return self.media_items(project_id)

    def replace_asset(self, project_id: str, request_id: str, source: Path | str) -> dict[str, Any]:
        current=next((item for group in self.media_items(project_id).values() for item in group if item.get("request",{}).get("request_id")==request_id),None)
        if not current: raise OperatorServiceError("request not found")
        if current.get("status")!="AMBIGUOUS": queue_regeneration(self.runtime.root,project_id,request_id,reason="operator local asset replacement")
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
        if config.render_mode=="ambient_story" and (media_type,requirement)!=("IMAGE","REQUIRED"): raise OperatorServiceError("ambient_story requires IMAGE / REQUIRED")
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
        settings,_=resolve_render_settings(config)
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
