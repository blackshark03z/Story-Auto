"""Operator-facing use cases over the canonical Story Auto core services."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, atomic_write_text, read_json
from story_auto.core.audio import parse_srt_bytes
from story_auto.application.import_readiness import inspect_import_readiness, not_required_readiness
from story_auto.application.production_commands import ProductionCommands
from story_auto.application.production_queries import ProductionQueries
from story_auto.application.flow_product import product_flow_status, required_capabilities, render_mode_availability
from story_auto.application.runtime_defaults import RuntimeDefaults
from story_auto.core.content import parse_content_markdown
from story_auto.core.planning import approve_plan, approve_shot_plan, run_planning_stages, run_visual_planning_stages
from story_auto.core.project import (AUTO_ACCEPT, MANUAL_REVIEW, ProjectConfig, RuntimeLayout, create_project,
                                     effective_qc_policy, execution_mode, load_project, stage_policy, validate_qc_policy)
from story_auto.core.project.lock import ProjectLock
from story_auto.core.publishing import finalize_thumbnail, prepare_thumbnail_request, run_publishing_metadata
from story_auto.core.render import resolve_render_plan, resolve_render_settings, run_render_stages
from story_auto.core.visual import ambient_style_label, temporal_video_qc_applicability
from story_auto.pipeline import (adopt_existing_audio, adopt_existing_srt,
                                 run_audio_stages, run_content_stage)
from story_auto.providers.flow import (
    FlowConnectionError, FlowConnectionService, FlowExecutor, FlowRuntime, adopt_manual_recovery, execute_generation, launch_dedicated_session, preflight,
    reject_selected_asset,
)
from story_auto.providers.flow.service import (queue_regeneration, replay_unresolved_request,
                                                accept_pending_visuals_by_owner, accept_selected_assets_by_owner, apply_auto_accept_policy, reopen_false_positive_production_qc, review_production_asset,
                                               supersede_ambiguous_request, reconcile_unresolved_flow_attempt)
from story_auto.providers.flow import live as flow_live
from story_auto.providers.flow.live import FlowInspector, LiveFlowGenerator
from story_auto.providers.flow.session import FlowSessionError
from story_auto.providers.flow.project_binding import (FLOW_MIGRATED_HOME_URL, FlowProjectBindingError, FlowProjectBindingService,
                                                        LiveFlowProjects, managed_binding, managed_flow_settings)
from story_auto.providers.tts.kokoro_local import KokoroLocalProvider, available_voices


class OperatorServiceError(RuntimeError):
    pass


class FeatureNotAvailableError(OperatorServiceError):
    failure_class = "FEATURE_NOT_AVAILABLE"

    def __init__(self, message: str = "Only Full Image is available in this release."):
        super().__init__(message)


_ATTENTION = {
    "KOKORO_VOICE_NOT_FOUND": {
        "title": "Selected narrator is unavailable",
        "message": "This project is explicitly bound to a Kokoro voice that is not installed. Choose an installed narrator before continuing.",
        "action": "Open settings",
        "action_id": "settings",
    },
    "KOKORO_RUNTIME_NOT_FOUND": {
        "title": "Local narrator is unavailable",
        "message": "Kokoro is not installed at this project's configured location.",
        "action": "Open settings",
        "action_id": "settings",
    },
    "KOKORO_MODEL_NOT_FOUND": {
        "title": "Local narrator model is unavailable",
        "message": "The configured Kokoro model files are missing.",
        "action": "Open settings",
        "action_id": "settings",
    },
    "KOKORO_RUNTIME_LOAD_FAILED": {
        "title": "Local narrator needs attention",
        "message": "Kokoro could not load the selected narrator before narration generation.",
        "action": "Open settings",
        "action_id": "settings",
    },
    "KOKORO_CONFIGURATION_INVALID": {
        "title": "Local narrator settings are invalid",
        "message": "Review the configured Kokoro narrator settings before continuing.",
        "action": "Open settings",
        "action_id": "settings",
    },
    "VALID_NARRATION_REQUIRED": {
        "title": "Content needs attention",
        "message": "Add one Narration section before Story Auto can begin.",
        "action": "Edit content",
        "action_id": "edit_content",
    },
    "EXECUTION_PREREQUISITE_MISSING": {
        "title": "Execution option is unavailable",
        "message": "A required canonical artifact is missing or no longer valid. Select a mode with available prerequisites or restore the required project work.",
        "action": "Review project",
        "action_id": "review_project",
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
        "title": "Flow generation needs reconciliation",
        "message": "Waiting to confirm the last Flow generation before creating another visual.",
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
    return result


_VOICE_NAMES = {"bm_george": "George", "am_michael": "Michael", "af_heart": "Heart"}


def _kokoro_settings(settings: dict[str, Any]) -> dict[str, Any]:
    tts = settings.get("tts", {}) if isinstance(settings, dict) else {}
    value = tts.get("kokoro_local", {}) if isinstance(tts, dict) else {}
    return value if isinstance(value, dict) else {}


def _kokoro_voice_options(settings: dict[str, Any]) -> tuple[list[dict[str, str]], str | None]:
    """Expose only identities present in the canonical local voice inventory."""
    try:
        voice_ids = available_voices(_kokoro_settings(settings))
    except Exception as error:
        return [], getattr(error, "failure_class", "KOKORO_CONFIGURATION_INVALID")
    return ([{"voice_id": voice_id, "name": _VOICE_NAMES.get(voice_id, voice_id)} for voice_id in voice_ids], None)


def _validate_new_project_narrator(settings: dict[str, Any]) -> None:
    """Reject a new Kokoro project whose selected identity is not installed.

    Existing projects are loaded unchanged so their historical binding remains
    visible and truthfully blocked instead of being rewritten at read time.
    """
    tts = settings.get("tts") if isinstance(settings, dict) else None
    if not isinstance(tts, dict) or tts.get("provider") != "kokoro_local":
        return
    readiness = KokoroLocalProvider().readiness(_kokoro_settings(settings))
    if not readiness.ready:
        from story_auto.core.audio import AudioPipelineError
        raise AudioPipelineError(readiness.technical_code or "KOKORO_CONFIGURATION_INVALID",
                                 provider="kokoro_local", stage="preflight")


def _safe_json(path: Path, default: Any) -> Any:
    try: return read_json(path)
    except Exception: return default


def _identity(value: dict[str, Any], prefix: str = "req_ui_") -> str:
    body=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return prefix+hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


class OperatorService:
    """The single mutation surface used by both HTTP handlers and CLI additions."""

    def __init__(self, runtime_root: Path | str, *, auto_flow_projects: bool = False, flow_projects=None):
        self.runtime=RuntimeLayout.from_root(runtime_root).ensure()
        self.flow_connections=FlowConnectionService(self.runtime)
        self.flow_project_bindings=FlowProjectBindingService(self.runtime, self.flow_connections)
        self.flow_projects=flow_projects if flow_projects is not None else (LiveFlowProjects(self.runtime) if auto_flow_projects else None)
        self.auto_flow_projects=auto_flow_projects or flow_projects is not None
        self.production_queries=ProductionQueries(self.runtime, self.flow_connections)
        self.runtime_defaults=RuntimeDefaults(self.runtime, lambda voice_id: _creation_settings({}, voice_id))

    def list_projects(self) -> list[dict[str, Any]]:
        result=[]
        for path in self.runtime.projects.glob("prj_*"):
            if not path.is_dir(): continue
            try: result.append(self.production_queries.project_list_item(path.name))
            except Exception as error: result.append({"project_id":path.name,"status":"INVALID","error":str(error)})
        return sorted(result,key=lambda item:item.get("updated_at", ""),reverse=True)

    def production_query(self, project_id: str) -> dict[str, Any]:
        """Canonical Phase A production query; reconciles compact state lazily."""
        paths, config = self._project(project_id)
        unavailable = render_mode_availability(config.render_mode)
        if not unavailable["available"]:
            # Do not reconcile or rewrite a historical deferred project just
            # to apply this release's availability policy.
            stages = {name: {"status": "NOT_STARTED", "execution": "BLOCK"} for name in ("SOURCE", "TIMING", "PLAN", "VISUALS", "QUALITY", "RENDER")}
            final_present = paths.artifact_path("output/final.mp4").is_file()
            return {"pipeline_status": unavailable["reason_code"], "active_stage": "SOURCE", "stages": stages,
                    "source_mode": config.settings.get("ui", {}).get("input_source", "STORY_CONTENT"),
                    "quality": {"policy": config.settings.get("qc_policy", AUTO_ACCEPT)}, "planning": {}, "recovery": {"status": unavailable["reason_code"],
                    "reason_code": unavailable["reason_code"], "human_message": unavailable["human_message"],
                    "automatic_recovery_available": False, "provider_dispatches_per_continue": 0,
                    "requires_owner_decision": False, "next_action": None}, "blocker": {"reason_code": unavailable["reason_code"],
                    "human_message": unavailable["human_message"], "retryable": False},
                    "next_action": None, "provider_dispatches": 0,
                    "final_output": {"present": final_present, "path": "output/final.mp4" if final_present else None}}
        return self.production_queries.production_query(project_id)

    def _require_available_render_mode(self, config) -> None:
        availability = render_mode_availability(config.render_mode)
        if not availability["available"]:
            raise FeatureNotAvailableError(availability["human_message"])

    def _deferred_feature_result(self, project_id: str) -> dict[str, Any] | None:
        _paths, config = self._project(project_id)
        availability = render_mode_availability(config.render_mode)
        if availability["available"]:
            return None
        return {"project_id": project_id, "outcome": availability["reason_code"],
                "reason_code": availability["reason_code"], "human_message": availability["human_message"],
                "provider_dispatches": 0, "retryable": False, "next_action": None, "invoked_stages": []}

    def project_workspace(self, project_id: str) -> dict[str, Any]:
        """Ordinary project-page payload: compact state first, no raw manifests."""
        paths, config=self._project(project_id)
        production=self.production_query(project_id)
        content=paths.content_file.read_text(encoding="utf-8") if paths.content_file.is_file() else ""
        tts=config.settings.get("tts",{}) if isinstance(config.settings,dict) else {}
        narrator=(tts.get("kokoro_local",{}).get("voice_id") if isinstance(tts,dict) and tts.get("provider")=="kokoro_local" else None)
        render=config.settings.get("render",{}) if isinstance(config.settings,dict) else {}
        full_image=config.settings.get("full_image",{}) if config.render_mode=="full_image" else {}
        source={"STORY_CONTENT":"Story / Content","EXISTING_AUDIO":"Existing audio","AUDIO_SRT":"Audio + SRT"}.get(production["source_mode"],"Story / Content")
        return {
            "project_id":project_id,
            "title":_content_title(content,project_id,{}),
            "status":"Complete" if production["pipeline_status"]=="COMPLETE" else ("Needs your attention" if production.get("blocker") else "In production"),
            "production":production,
            "summary":{
                "source":source,
                "narrator":_VOICE_NAMES.get(narrator,narrator) if narrator else None,
                "style":config.settings.get("ui",{}).get("production_style", "Natural cinematic"),
                "quality":"Automatic" if production["quality"]["policy"]==AUTO_ACCEPT else "Manual" if production["quality"]["policy"]==MANUAL_REVIEW else "AI review",
                "waveform":"On" if full_image.get("audio_visualizer",True) else "Off",
                "resolution":f"{render.get('width','Default')} × {render.get('height','Default')}",
            },
            "final_path":production["final_output"]["path"],
            "flow":production.get("flow"),
            "can_render_again":production["stages"]["RENDER"]["execution"] != "BLOCK",
        }

    @staticmethod
    def _decoded_import(value: dict[str, Any] | None, *, fallback_name: str, limit: int) -> tuple[str, bytes]:
        if not isinstance(value, dict):
            raise OperatorServiceError("IMPORT_SOURCE_INVALID")
        encoded=value.get("base64")
        filename=Path(str(value.get("filename",fallback_name))).name
        if not isinstance(encoded,str) or not encoded or len(encoded)>limit:
            raise OperatorServiceError("IMPORT_SOURCE_INVALID")
        try:
            return filename,base64.b64decode(encoded,validate=True)
        except Exception as error:
            raise OperatorServiceError("IMPORT_SOURCE_INVALID") from error

    def inspect_imports(self, *, source_mode: str, imported_audio: dict[str, Any] | None,
                        imported_srt: dict[str, Any] | None) -> dict[str, Any]:
        """Return the canonical readiness result for untrusted browser uploads."""
        if source_mode not in {"EXISTING_AUDIO","AUDIO_SRT"}:
            return not_required_readiness()
        try:
            audio_name,audio_payload=self._decoded_import(imported_audio,fallback_name="narration.wav",limit=180_000_000)
        except OperatorServiceError as error:
            readiness,_=inspect_import_readiness(source_mode=source_mode,audio_error=str(error))
            return readiness
        temporary_dir=self.runtime.temp/uuid.uuid4().hex; temporary_dir.mkdir(parents=True,exist_ok=False)
        try:
            audio_path=temporary_dir/audio_name; audio_path.write_bytes(audio_payload)
            srt_name = None; srt_payload = None; srt_error = None
            if source_mode=="AUDIO_SRT":
                try:
                    srt_name,srt_payload=self._decoded_import(imported_srt,fallback_name="timing.srt",limit=30_000_000)
                    if Path(srt_name).suffix.lower()!=".srt": srt_error="SRT_SOURCE_INVALID"
                except OperatorServiceError as error:
                    srt_error=str(error)
            readiness,_=inspect_import_readiness(source_mode=source_mode,audio_path=audio_path,audio_filename=audio_name,
                                                  srt_payload=srt_payload,srt_filename=srt_name,srt_error=srt_error)
            return readiness
        finally:
            shutil.rmtree(temporary_dir,ignore_errors=True)

    def create_project(self, *, project_id: str | None=None, render_mode: str | None=None,
                       ambient_style: str | None=None, content: str | None=None,
                       settings: dict[str, Any] | None=None, imported_audio: dict[str, Any] | None=None,
                       imported_srt: dict[str, Any] | None=None) -> dict[str, Any]:
        ident=project_id or "prj_"+uuid.uuid4().hex
        defaults=self.runtime_defaults.read()
        resolved_settings=self.runtime_defaults.project_snapshot(settings)
        if ambient_style is not None: resolved_settings["ambient_style"]=ambient_style
        effective_render_mode=render_mode or str(defaults["render_mode"])
        availability = render_mode_availability(effective_render_mode)
        if not availability["available"]:
            raise FeatureNotAvailableError(availability["human_message"])
        mode=execution_mode(resolved_settings)
        source_mode=str(resolved_settings.get("ui",{}).get("input_source","STORY_CONTENT"))
        if source_mode not in {"STORY_CONTENT","EXISTING_AUDIO","AUDIO_SRT"}:
            raise OperatorServiceError("INPUT_SOURCE_INVALID")
        if mode == "FULL": _validate_new_project_narrator(resolved_settings)
        if source_mode in {"EXISTING_AUDIO","AUDIO_SRT"}:
            readiness=self.inspect_imports(source_mode=source_mode,imported_audio=imported_audio,imported_srt=imported_srt)
            if readiness["status"]!="READY":
                error=OperatorServiceError(readiness["code"])
                error.readiness=readiness
                raise error
        if source_mode=="AUDIO_SRT" and not content:
            _,srt_payload=self._decoded_import(imported_srt,fallback_name="timing.srt",limit=30_000_000)
            cues,_,_=parse_srt_bytes(srt_payload)
            content="# Imported narration\n\n## Narration\n\n"+" ".join(cue.text for cue in cues)+"\n"
        if source_mode=="EXISTING_AUDIO" and not content:
            raise OperatorServiceError("EXISTING_AUDIO_TEXT_REQUIRED")
        connection=self.flow_connections.get_current_connection()
        if self.auto_flow_projects and mode!="RENDER_ONLY":
            resolved_settings=managed_flow_settings(resolved_settings,ident)
        elif connection is not None and connection.validation_status=="CONNECTED" and mode!="RENDER_ONLY":
            # Compatibility for callers that explicitly use the legacy
            # application mode.  The normal UI/CLI enables managed projects.
            resolved_settings["flow_binding"]={"connection_id":connection.connection_id,"connection_revision":connection.revision}
            resolved_settings["flow_project_binding"]={"project_identity":connection.project_identity,"project_url":connection.project_url}
        paths=create_project(self.runtime,ProjectConfig(ident,render_mode=effective_render_mode,settings=resolved_settings),content or "# Story\n\n## Narration\n\nWrite narration here.\n")
        if imported_audio is not None:
            try:
                encoded=imported_audio.get("base64") if isinstance(imported_audio,dict) else None
                filename=Path(str(imported_audio.get("filename","narration.wav"))).name if isinstance(imported_audio,dict) else "narration.wav"
                if not isinstance(encoded,str) or not encoded or len(encoded) > 180_000_000: raise OperatorServiceError("NARRATION_AUDIO_SOURCE_INVALID")
                payload=base64.b64decode(encoded,validate=True)
                temporary_dir=self.runtime.temp/uuid.uuid4().hex
                temporary_dir.mkdir(parents=True,exist_ok=False)
                temporary=temporary_dir/filename
                temporary.write_bytes(payload)
                try: adopt_existing_audio(self.runtime.root,ident,temporary,source_type="IMPORTED")
                finally:
                    if temporary.exists(): temporary.unlink()
                    if temporary_dir.exists(): temporary_dir.rmdir()
            except Exception:
                # The project remains explicit but no unverified external audio is ever bound to it.
                raise
        if imported_srt is not None:
            try:
                encoded=imported_srt.get("base64") if isinstance(imported_srt,dict) else None
                filename=Path(str(imported_srt.get("filename","timing.srt"))).name if isinstance(imported_srt,dict) else "timing.srt"
                if not isinstance(encoded,str) or not encoded or len(encoded) > 30_000_000: raise OperatorServiceError("SRT_SOURCE_INVALID")
                payload=base64.b64decode(encoded,validate=True)
                temporary_dir=self.runtime.temp/uuid.uuid4().hex
                temporary_dir.mkdir(parents=True,exist_ok=False)
                temporary=temporary_dir/filename
                temporary.write_bytes(payload)
                try: adopt_existing_srt(self.runtime.root,ident,temporary,source_type="IMPORTED")
                finally:
                    if temporary.exists(): temporary.unlink()
                    if temporary_dir.exists(): temporary_dir.rmdir()
            except Exception:
                raise
        if self.auto_flow_projects and mode!="RENDER_ONLY":
            try:
                self.flow_project_bindings.ensure(ident,self.flow_projects)
            except (FlowProjectBindingError, FlowSessionError):
                # Local creation succeeded. The binding service durably records
                # the exact setup failure; snapshot returns that status with the
                # saved project ID so clients cannot mistake this for BOUND.
                pass
        result = self.snapshot(paths.project_id)
        if self.auto_flow_projects and mode!="RENDER_ONLY":
            _, saved_config = self._project(ident)
            binding = managed_binding(saved_config)
            result["flow_setup"] = {"state":binding["state"],
                                    "failure_class":binding.get("last_setup_failure"),
                                    "activation_state":binding["activation_state"],
                                    "project_url":binding.get("project_url"),
                                    "project_identity":binding.get("project_identity")}
        return result

    def _project(self, project_id: str): return load_project(self.runtime,project_id)

    def snapshot(self, project_id: str) -> dict[str, Any]:
        paths,config=self._project(project_id)
        production=self.production_query(project_id)
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
        final_manifest=_safe_json(paths.artifact_path("output/final_manifest.json"),{})
        active_request_ids={item.get("request_id") for item in requests.get("requests",[]) if item.get("request_id")}
        entries={item.get("request_id"):item for item in manifest.get("requests",[]) if item.get("request_id") in active_request_ids}
        counts={}
        for entry in entries.values():
            counts[entry.get("status","UNKNOWN")]=counts.get(entry.get("status","UNKNOWN"),0)+1
        artifacts={name:paths.artifact_path(f"output/{name}").is_file() for name in (
            "content_manifest.json","alignment.json","story_timeline.json","continuity_bible.json","shot_plan.json",
            "media_plan.json","generation_requests.json","render_plan.json","final.mp4","publishing_package.json")}
        blocked=[]
        audio_manifest=_safe_json(paths.artifact_path("output/audio_manifest.json"),{})
        srt_manifest=_safe_json(paths.artifact_path("output/srt_manifest.json"),{})
        tts = config.settings.get("tts", {})
        narrator = {"provider": tts.get("provider", "NOT_CONFIGURED"), "voice_id": None,
                    "name": "Not configured", "status": "Not configured", "technical_code": None}
        if tts.get("provider") == "kokoro_local":
            kokoro = _kokoro_settings(config.settings)
            narrator["voice_id"] = kokoro.get("voice_id")
            narrator["name"] = _VOICE_NAMES.get(narrator["voice_id"], narrator["voice_id"] or "Selected narrator")
            readiness = KokoroLocalProvider().readiness(kokoro)
            narrator.update({"status": "Ready" if readiness.ready else "Needs attention",
                             "technical_code": readiness.technical_code})
            if not readiness.ready and readiness.technical_code:
                blocked.append(readiness.technical_code)
        visual_planning=review.get("visual_planning",{}) if isinstance(review,dict) else {}
        if content_status!="VALID": blocked.append("VALID_NARRATION_REQUIRED")
        if visual_planning.get("status")=="NEEDS_REGENERATION": blocked.append("VISUAL_PLANNING_REGENERATION_REQUIRED")
        elif review.get("plan_approval",{}).get("status")!="APPROVED" and artifacts["continuity_bible.json"]: blocked.append("PLANNING_APPROVAL_REQUIRED")
        mode=execution_mode(config.settings)
        required_flow=[] if mode=="RENDER_ONLY" else ["IMAGE"]
        _connection,flow_status=self.flow_connections.connection_for_project(project_id,required_capabilities=required_flow)
        if counts.get("AUTH_REQUIRED"): blocked.append("FLOW_AUTH_REQUIRED")
        if counts.get("CREDIT_BLOCKED"): blocked.append("PROVIDER_CREDITS_REQUIRED")
        if counts.get("FAILED_PERMANENT") or counts.get("FAILED_FATAL"): blocked.append("GENERATION_SETUP_REQUIRED")
        if counts.get("CANCELLED"): blocked.append("GENERATION_CANCELLED")
        if counts.get("AMBIGUOUS"): blocked.append("GENERATION_RECONCILIATION_REQUIRED")
        if counts.get("QC_PENDING"): blocked.append("MEDIA_QC_REQUIRED")
        # A missing connection blocks a future provider boundary, not a finished
        # project, local Render Again, or an already-recorded provider recovery.
        awaiting_provider=any(counts.get(name) for name in {"PENDING","NOT_DISPATCHED","FAILED_RETRYABLE"})
        if mode!="RENDER_ONLY" and awaiting_provider and not blocked and flow_status["status"]!="CONNECTED": blocked.append(flow_status["code"])
        shot_groups={}
        for request in requests.get("requests",[]):
            if request.get("purpose")!="SHOT": continue
            shot_groups.setdefault(request.get("shot_id") or request.get("request_id"),[]).append(request.get("request_id"))
        total_visuals=len(shot_groups)
        finished_visuals=sum(all(entries.get(request_id,{}).get("status") in {"SUCCEEDED","QC_PENDING"} for request_id in request_ids) for request_ids in shot_groups.values())
        accepted_visuals=bool(shot_groups) and all(all(entries.get(request_id,{}).get("status")=="SUCCEEDED" and entries.get(request_id,{}).get("selected_asset") for request_id in request_ids) for request_ids in shot_groups.values())
        has_audio=bool(alignment.get("audio_sha256") and audio_manifest.get("audio_sha256")==alignment.get("audio_sha256"))
        mode=execution_mode(config.settings)
        render_settings,_=resolve_render_settings(config)
        rendered_settings=final_manifest.get("composer",{}).get("settings")
        render_stale=bool(artifacts["final.mp4"] and isinstance(rendered_settings,dict) and rendered_settings and rendered_settings != render_settings)
        policy=stage_policy(mode,has_valid_audio=has_audio,has_accepted_visuals=accepted_visuals)
        for item in policy.values():
            if item.action=="BLOCK": blocked.append("EXECUTION_PREREQUISITE_MISSING")
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
        if artifacts["final.mp4"] and not render_stale:
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
        elif artifacts["final.mp4"] and not render_stale:
            user_status="Complete"; primary_action={"action":"Open final video","action_id":"open_final"}
        elif render_stale:
            progress,stage,activity=max(progress,88),"Render","Render settings changed. The existing visuals will be reused."
            user_status="Ready to render"; primary_action={"action":"Render final video","action_id":"render"}
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
        result={"project_id":project_id,"title":_content_title(content,project_id,publishing),"content_status":content_status,"render_mode":config.render_mode,
                "format_label":{"hybrid_hook":"Intro Video + Images (Coming soon)","full_video_ai":"Full Video (Coming soon)","ambient_story":"Ambient Story (deferred)","full_image":"Full Image"}[config.render_mode],
                "ambient_style":ambient_style,"ambient_style_label":ambient_style_label(ambient_style),
                "tts_provider":config.settings.get("tts",{}).get("provider","NOT_CONFIGURED"),"narrator":narrator,
                "planning_status":"ACTION_REQUIRED" if visual_planning.get("status")=="NEEDS_REGENERATION" else ("APPROVED" if review.get("plan_approval",{}).get("status")=="APPROVED" else ("VALIDATED" if artifacts["story_timeline.json"] else "NOT_STARTED")),
                "continuity_status":"READY" if artifacts["continuity_bible.json"] else "NOT_STARTED",
                "shot_plan_status":"READY" if artifacts["shot_plan.json"] else "NOT_STARTED",
                "generation_status":counts or {"NOT_STARTED":0},
                "render_status":"NOT_STARTED" if visual_planning.get("status")=="NEEDS_REGENERATION" else ("NEEDS_RENDER" if render_stale else ("COMPLETE" if artifacts["final.mp4"] else ("PLANNED" if artifacts["render_plan.json"] else "NOT_STARTED"))),
                "publishing_status":"READY" if artifacts["publishing_package.json"] else "NOT_STARTED",
                "blocked":blocked,"artifacts":artifacts,"project_path":str(paths.root),
                "user_status":user_status,"current_stage":stage,"current_activity":activity,"progress":min(100,progress),
                "completed_visuals":finished_visuals,"total_visuals":total_visuals,"primary_action":primary_action,
                "attention":attention,"work_saved":True,"updated_at":_updated_at(paths),"word_count":_word_count(narration),
                "duration_seconds":duration,"thumbnail_path":thumbnail,"final_path":"output/final.mp4" if artifacts["final.mp4"] and not render_stale and visual_planning.get("status")!="NEEDS_REGENERATION" else None,
                "visual_planning":visual_planning,"execution_mode":mode,
                "execution_policy":{name:{"action":item.action,"reason":item.reason} for name,item in policy.items()},
                "narration_source":audio_manifest.get("source_type", "GENERATE"),
                "input_source":config.settings.get("ui",{}).get("input_source","STORY_CONTENT"),
                "narration_audio":"MISSING" if not has_audio else ("IMPORTED" if audio_manifest.get("source_type")=="IMPORTED" else "REUSED"),
                "subtitle_timing":"MISSING" if not srt_manifest else ("IMPORTED" if srt_manifest.get("source_type")=="IMPORTED" else "REUSED"),
                "timing_source":alignment.get("timing_source", "DETERMINISTIC_ALIGNMENT" if has_audio else None),
                "srt_validation":srt_manifest.get("validation_result"), "srt_normalization":srt_manifest.get("normalization"),
                "timeline_match":srt_manifest.get("timeline_match",{}).get("status"),
                "accepted_visuals":accepted_visuals,"full_image":config.settings.get("full_image") if config.render_mode=="full_image" else None,
                "render_stale":render_stale,"flow_connection":flow_status,
                "flow_binding":config.settings.get("flow_binding"),"production":production}
        # The compact reconciled state owns the primary production command.  The
        # existing detailed snapshot remains available for advanced compatibility.
        if production["pipeline_status"] == "FEATURE_NOT_AVAILABLE":
            result.update({"user_status":"Unavailable","current_stage":"Unavailable",
                           "current_activity":production["recovery"]["human_message"],
                           "primary_action":{"action":"Mode unavailable","action_id":"review_project"}})
        elif production["pipeline_status"] == "COMPLETE":
            result.update({"user_status":"Complete","current_stage":"Finish","current_activity":"Final video is ready.","progress":100,
                           "primary_action":{"action":"Open final video","action_id":"open_final"}})
        elif production["pipeline_status"] == "READY" and not blocked:
            label=production["next_action"]["label"]
            stages={"SOURCE":"Content","TIMING":"Voice","PLAN":"Plan","VISUALS":"Create visuals","QUALITY":"Quality check","RENDER":"Render"}
            result.update({"user_status":label,"current_stage":stages[production["active_stage"]],
                           "current_activity":f"{label} runs the saved production path until it needs your decision.",
                           "primary_action":{"action":label,"action_id":"run_to_final"}})
        return result

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
        paths,config=self._project(project_id); self._require_available_render_mode(config); actions={"content":run_content_stage(self.runtime.root,project_id)}
        mode=execution_mode(config.settings)
        if "tts" in config.settings or mode != "FULL":
            actions["tts"],actions["alignment"]=run_audio_stages(self.runtime.root,project_id,adapter=audio_adapter)
        if mode=="RENDER_ONLY":
            snapshot=self.snapshot(project_id)
            if any(item.action=="BLOCK" for item in stage_policy(mode,has_valid_audio=bool(snapshot.get("duration_seconds")),has_accepted_visuals=bool(snapshot.get("accepted_visuals"))).values()):
                raise OperatorServiceError("No accepted visual assets are available for the current plan.")
            actions["snapshot"]=self.snapshot(project_id); return actions
        if "llm" in config.settings:
            actions["timeline"],actions["continuity"]=run_planning_stages(self.runtime.root,project_id,provider=planning_provider)
        actions["snapshot"]=self.snapshot(project_id); return actions

    def _production_commands(self) -> ProductionCommands:
        return ProductionCommands(self.production_query, {
            "prepare": lambda project_id: self.start_or_resume(project_id),
            "plan": lambda project_id: self._plan_for_production(project_id),
            "approve_plan": lambda project_id: self.approve_planning(project_id),
            "approve_shots": lambda project_id: self.approve_planning(project_id, shots=True),
            "visuals": lambda project_id: self._run_visuals_for_production(project_id),
            "quality": lambda project_id: self.apply_qc_policy(project_id),
            "render": lambda project_id: self.render(project_id),
        }, self.production_queries.record_run, self.production_queries.record_planning_failure)

    def _plan_for_production(self, project_id: str) -> Any:
        paths, _ = self._project(project_id)
        if not all(paths.artifact_path(f"output/{name}").is_file()
                   for name in ("story_timeline.json", "continuity_bible.json")):
            run_planning_stages(self.runtime.root, project_id)
            return self.planning_review(project_id)
        return self.plan_visuals(project_id)

    def _run_visuals_for_production(self, project_id: str) -> Any:
        state=self.production_query(project_id)
        if state["stages"]["VISUALS"]["status"] == "READY" and state["stages"]["PLAN"]["status"] == "COMPLETE":
            paths,_=self._project(project_id)
            if not paths.artifact_path("output/generation_requests.json").is_file():
                return self.plan_visuals(project_id)
        return self.generate(project_id)

    def run_to_final(self, project_id: str) -> dict[str, Any]:
        unavailable = self._deferred_feature_result(project_id)
        if unavailable is not None:
            return unavailable
        return self._production_commands().run_to_final(project_id)

    def continue_production(self, project_id: str) -> dict[str, Any]:
        unavailable = self._deferred_feature_result(project_id)
        if unavailable is not None:
            return unavailable
        return self._production_commands().continue_production(project_id)

    def planning_review(self, project_id: str) -> dict[str, Any]:
        paths,_=self._project(project_id)
        return {name:_safe_json(paths.artifact_path(f"output/{name}.json"),None) for name in ("story_timeline","continuity_bible","shot_plan","media_plan","generation_requests","review_state","publishing_package")}

    def plan_visuals(self, project_id: str, *, provider=None) -> dict[str, Any]:
        _,config=self._project(project_id)
        self._require_available_render_mode(config)
        if execution_mode(config.settings)=="RENDER_ONLY": raise OperatorServiceError("RENDER_ONLY reuses accepted visual assets and cannot create a visual plan.")
        run_visual_planning_stages(self.runtime.root,project_id,provider=provider); return self.planning_review(project_id)

    def set_execution_mode(self, project_id: str, mode: str) -> dict[str, Any]:
        paths,_=self._project(project_id)
        snapshot=self.snapshot(project_id)
        policy=stage_policy(mode,has_valid_audio=bool(snapshot.get("duration_seconds")),
                            has_accepted_visuals=bool(snapshot.get("accepted_visuals")))
        blocked=next((item for item in policy.values() if item.action=="BLOCK"),None)
        if blocked: raise OperatorServiceError(blocked.reason or "Execution option is unavailable.")
        project=read_json(paths.project_file); project.setdefault("settings",{}).setdefault("execution",{})["mode"]=mode
        # Validate via the project contract before changing the durable config.
        ProjectConfig.from_dict(project)
        atomic_write_json(paths.project_file,project)
        return self.snapshot(project_id)

    def set_full_image_duration(self, project_id: str, seconds: float, cadence: str | None = None) -> dict[str, Any]:
        paths,config=self._project(project_id)
        if config.render_mode != "full_image": raise OperatorServiceError("Scene duration is available only for Full Image projects.")
        project=read_json(paths.project_file); full_image=project.setdefault("settings",{}).setdefault("full_image",{})
        full_image["image_duration_seconds"]=seconds
        if cadence is not None: full_image["cadence"]=cadence
        validated=ProjectConfig.from_dict(project)
        atomic_write_json(paths.project_file,validated.to_dict())
        required=("alignment.json","story_timeline.json","continuity_bible.json")
        if all(paths.artifact_path(f"output/{name}").is_file() for name in required):
            # FULL_IMAGE planning is local/deterministic; changed window identity leaves
            # prior selected assets unbound unless their canonical request identity matches.
            run_visual_planning_stages(self.runtime.root,project_id)
        return self.snapshot(project_id)

    def set_full_image_audio_visualizer(self, project_id: str, enabled: bool) -> dict[str, Any]:
        paths,config=self._project(project_id)
        if config.render_mode != "full_image": raise OperatorServiceError("Waveform is available only for Full Image projects.")
        project=read_json(paths.project_file)
        project.setdefault("settings",{}).setdefault("full_image",{})["audio_visualizer"]=bool(enabled)
        validated=ProjectConfig.from_dict(project)
        atomic_write_json(paths.project_file,validated.to_dict())
        return self.snapshot(project_id)

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
                elif status=="AMBIGUOUS": message=f"Story Auto is waiting to confirm the last Flow generation for {label.lower()} before creating another visual."
                else: message=f"{label} could not be completed and can be retried."
                recovery_action=("manual_asset" if status=="AMBIGUOUS" else "flow_sign_in_then_requeue" if status=="AUTH_REQUIRED" else "requeue" if status in {"FAILED_RETRYABLE","FAILED_FATAL","FAILED_PERMANENT","CREDIT_BLOCKED","CANCELLED","REJECTED"} else None)
                issues.append({"label":label,"scene":index if kind=="Scene" else None,"message":message,"status":status,"request_id":request.get("request_id"),"media_type":request.get("media_type"),"technical_code":item.get("failure_class"),"retryable":status in {"QC_PENDING","FAILED_RETRYABLE","FAILED_FATAL","FAILED_PERMANENT","AUTH_REQUIRED","CREDIT_BLOCKED","CANCELLED","REJECTED"},"recovery_action":recovery_action})
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
        defaults_payload=self.runtime_defaults.read()
        latest_settings=self.runtime_defaults.creation_snapshot()
        tts=latest_settings.get("tts",{}) if isinstance(latest_settings,dict) else {}
        provider=tts.get("provider")
        kokoro_settings=tts.get("kokoro_local",{}) if isinstance(tts,dict) else {}
        llm=latest_settings.get("llm",{}) if isinstance(latest_settings,dict) else {}
        flow_status=self.flow_connections.get_connection_status(required_capabilities=[])
        historical_capabilities=dict(flow_status.get("observed_capabilities") or {})
        flow_status={**flow_status,
                     "observed_capabilities":{},
                     "historical_capabilities":historical_capabilities,
                     "capability_authority":"HISTORICAL_CONNECTION_EVIDENCE",
                     "live_validation_required":True}
        usage=shutil.disk_usage(self.runtime.root)
        voice_id=str(defaults_payload["narrator"]["voice_id"])
        inventory_settings = latest_settings if provider == "kokoro_local" else _creation_settings({}, voice_id)
        voice_options, inventory_failure = _kokoro_voice_options(inventory_settings)
        installed_voice_ids={item["voice_id"] for item in voice_options}
        default_voice_available=voice_id in installed_voice_ids
        creation_defaults=latest_settings
        kokoro_readiness=None
        if provider=="kokoro_local":
            kokoro_readiness=KokoroLocalProvider().readiness(kokoro_settings)
            voice_row={"name":"Voice",
                       "detail":f"{_VOICE_NAMES.get(voice_id,voice_id)} — local narrator" if kokoro_readiness.ready else kokoro_readiness.user_message,
                       "status":"Ready" if kokoro_readiness.ready else "Needs attention",
                       "technical_code":kokoro_readiness.technical_code}
        else:
            voice_row={"name":"Voice","detail":f"{_VOICE_NAMES.get(voice_id,voice_id)} — local narrator" if provider else "Choose a narrator for new videos",
                       "status":"Ready" if provider else "Not configured"}
        return {
            "defaults":{"render_mode":defaults_payload["render_mode"],"ambient_style":defaults_payload["ambient_style"],"voice_id":voice_id,"voice_name":_VOICE_NAMES.get(voice_id,voice_id),"production_style":defaults_payload["visual_style"],
                        "narrator_available":default_voice_available,
                        "narrator_message":None if default_voice_available else "The saved default narrator is not installed. Choose one of the installed narrators before creating a video."},
            "creation_defaults":creation_defaults,
            "voice_options":voice_options,
            "voice_inventory_failure":inventory_failure,
            "providers":[
                voice_row,
                {"name":"Visual generation","detail":"Google Flow · Live project readiness is checked before generation","status":"Connected" if flow_status["status"]=="CONNECTED" else flow_status["status"].replace("_"," ").title()},
                {"name":"AI quality","detail":"Gemini planning and quality checks","status":"Ready" if llm else "Not configured"},
            ],
            "storage":{"project_location":str(self.runtime.projects),"free_gb":round(usage.free/(1024**3),1)},
            "flow_connection":flow_status,
            "advanced":{"runtime_root":str(self.runtime.root),"gemini_model":llm.get("model","gemini-3.5-flash"),"flow_project":flow_status.get("project_identity") or "Not configured","tts_provider":provider or "Not configured",
                        "kokoro_readiness":kokoro_readiness.as_dict() if kokoro_readiness else None},
        }

    def update_runtime_defaults(self, value: dict[str, Any]) -> dict[str, Any]:
        """Update defaults for future projects; historical projects are untouched."""
        self.runtime_defaults.update(value)
        return self.settings_overview()

    def creation_defaults(self) -> dict[str, Any]:
        """Return only the data a new-video draft can safely hydrate with.

        This deliberately does not inspect existing projects.  Project snapshots
        can contain large generation manifests and belong to Home/Settings, not
        to the first interaction in the New Video dialog.
        """
        defaults_payload=self.runtime_defaults.read()
        base_settings=self.runtime_defaults.creation_snapshot()
        tts=base_settings.get("tts",{}) if isinstance(base_settings,dict) else {}
        kokoro=tts.get("kokoro_local",{}) if isinstance(tts,dict) else {}
        voice_id=str(kokoro.get("voice_id","bm_george"))
        voice_options, inventory_failure=_kokoro_voice_options(base_settings)
        installed_voice_ids={item["voice_id"] for item in voice_options}
        return {
            "defaults":{"render_mode":defaults_payload["render_mode"],"ambient_style":defaults_payload["ambient_style"],"voice_id":voice_id,
                        "narrator_available":voice_id in installed_voice_ids},
            "creation_defaults":base_settings,
            "voice_options":voice_options,
            "voice_inventory_failure":inventory_failure,
            "flow_connection":self._flow_connection_overview(),
        }

    def _flow_connection_overview(self) -> dict[str, Any]:
        status=self.flow_connections.get_connection_status(required_capabilities=[])
        historical_capabilities=dict(status.get("observed_capabilities") or {})
        return {**status,
                "observed_capabilities":{},
                "historical_capabilities":historical_capabilities,
                "capability_authority":"HISTORICAL_CONNECTION_EVIDENCE",
                "live_validation_required":True}

    def runtime_attestation(self) -> dict[str, Any]:
        """Identify the Flow implementation loaded by this UI process."""
        source=Path(flow_live.__file__).resolve()
        return {
            "process_id":os.getpid(),
            "flow_module":str(source),
            "flow_module_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "provider_surface_extractor_version":flow_live.PROVIDER_SURFACE_EXTRACTOR_VERSION,
            "poll_evidence_version":flow_live.POLL_EVIDENCE_VERSION,
        }

    def diagnostics(self, project_id: str) -> dict[str, Any]:
        return {"snapshot":self.snapshot(project_id),"planning":self.planning_review(project_id),"media":self.media_items(project_id)}

    def open_flow_sign_in(self, project_id: str) -> dict[str, str]:
        _paths, config = self._project(project_id)
        managed = managed_binding(config)
        if managed is not None and managed.get("state") != "BOUND":
            runtime = FlowRuntime(self.runtime.flow_profile, "http://127.0.0.1:9222",
                                  FLOW_MIGRATED_HOME_URL + "/about", FLOW_MIGRATED_HOME_URL)
            launch_dedicated_session(runtime)
            return {"status":"OPENED","message":"Complete Google sign-in in the Story Auto Flow window, then return and try again."}
        if managed is not None and managed.get("state") == "BOUND":
            reference = managed
        else:
            reference = config.settings.get("flow_project_binding", {}) if isinstance(config.settings, dict) else {}
        if isinstance(reference, dict) and isinstance(reference.get("project_url"), str) and isinstance(reference.get("project_identity"), str):
            runtime = FlowRuntime(self.runtime.flow_profile, "http://127.0.0.1:9222", reference["project_url"], reference["project_identity"])
        else:
            connection,_=self.flow_connections.connection_for_project(project_id)
            if connection is None: raise FlowConnectionError("FLOW_NOT_CONFIGURED")
            runtime = self.flow_connections.runtime_for_connection(connection)
        launch_dedicated_session(runtime)
        return {"status":"OPENED","message":"Complete Google sign-in in the Story Auto Flow window, then return and try again."}

    def open_flow_project(self, project_id: str) -> dict[str, str]:
        _paths, config = self._project(project_id)
        binding = managed_binding(config)
        if binding is not None:
            if binding.get("state") != "BOUND":
                raise FlowProjectBindingError("FLOW_PROJECT_SETUP_REQUIRED")
            if self.flow_projects is None:
                raise FlowProjectBindingError("FLOW_PROJECT_AUTOMATION_UNAVAILABLE")
            self.flow_project_bindings.ensure(project_id, self.flow_projects)
            return {"status":"OPENED", "message":"Opened this video's exact Flow project."}
        return self.open_flow_sign_in(project_id)

    def ensure_flow_project(self, project_id: str) -> dict[str, Any]:
        _paths, config = self._project(project_id)
        if managed_binding(config) is None:
            return self.flow_status(project_id)
        if self.flow_projects is None:
            raise FlowProjectBindingError("FLOW_PROJECT_AUTOMATION_UNAVAILABLE")
        self.flow_project_bindings.ensure(project_id, self.flow_projects)
        return self.project_workspace(project_id)

    def recheck_flow_generation(self, project_id: str) -> dict[str, Any]:
        state = self.production_query(project_id)
        recovery = state.get("recovery") if isinstance(state.get("recovery"), dict) else {}
        request_id = recovery.get("affected_request_id")
        if state.get("pipeline_status") != "STUCK_PENDING" or not isinstance(request_id, str):
            raise OperatorServiceError("STUCK_PENDING_RECHECK_NOT_AVAILABLE")
        connection, status = self.flow_connections.connection_for_project(project_id, required_capabilities=["IMAGE"])
        if connection is None or status.get("status") != "CONNECTED":
            raise FlowConnectionError(status.get("code", "FLOW_NOT_CONFIGURED"))
        runtime = self.flow_connections.runtime_for_connection(connection)
        capabilities = preflight(runtime, FlowInspector(runtime))
        executor = FlowExecutor(capabilities, LiveFlowGenerator(runtime))
        result = reconcile_unresolved_flow_attempt(self.runtime.root, project_id, request_id, executor=executor)
        return {"recheck": result, "production": self.production_query(project_id)}

    def _flow_capabilities_for_project(self, project_id: str, request_ids: set[str] | None = None) -> list[str]:
        paths, config = self._project(project_id)
        media_types = []
        requests = _safe_json(paths.artifact_path("output/generation_requests.json"), {"requests": []})
        for request in requests.get("requests", []):
            if request_ids is None or request.get("request_id") in request_ids:
                media_types.append(request.get("media_type"))
        return required_capabilities(config, media_types)

    def flow_status(self, project_id: str) -> dict[str, Any]:
        _paths, config = self._project(project_id)
        production = self.production_query(project_id)
        return product_flow_status(self.flow_connections, project_id, config,
                                   auth_required=production.get("pipeline_status") == "AUTH_REQUIRED")

    def prepare_flow_recovery(self, project_id: str) -> dict[str, Any]:
        """Return the canonical next safe Flow recovery step; never dispatch media."""
        return self.flow_status(project_id)

    def flow_connection_status(self, project_id: str | None = None) -> dict[str, Any]:
        if project_id:
            return self.flow_status(project_id)
        return self.flow_connections.get_connection_status(required_capabilities=["IMAGE"])

    def validate_flow_connection(self, project_id: str, project_url: str | None = None) -> dict[str, Any]:
        _paths, config = self._project(project_id)
        reference = config.settings.get("flow_project_binding", {}) if isinstance(config.settings, dict) else {}
        expected_url = reference.get("project_url") if isinstance(reference, dict) else None
        target = project_url or expected_url
        if not isinstance(target, str) or not target.strip():
            raise FlowConnectionError("FLOW_NOT_CONFIGURED")
        validation = self.flow_connections.validate_candidate(target, required_capabilities=self._flow_capabilities_for_project(project_id))
        if validation["status"] == "CONNECTED":
            connection = self.flow_connections.save_validated_candidate(validation)
            return {**self.flow_status(project_id), "validated": True, "connection_id": connection.connection_id}
        return {**product_flow_status(self.flow_connections, project_id, config), "validated": False}

    def rebind_flow_project(self, project_id: str, *, explicit_owner_decision: bool) -> dict[str, Any]:
        if explicit_owner_decision is not True:
            raise FlowConnectionError("FLOW_REBIND_EXPLICIT_OWNER_DECISION_REQUIRED")
        connection = self.flow_connections.get_current_connection()
        if connection is None or connection.validation_status != "CONNECTED":
            raise FlowConnectionError("FLOW_CONNECTION_NOT_VALIDATED")
        binding = self.flow_connections.bind_project(project_id, connection, explicit_owner_decision=True)
        return {**self.flow_status(project_id), "binding": binding}

    def update_flow_connection(self, project_id: str, project_url: str, *, explicit_owner_decision: bool = False) -> dict[str, Any]:
        validation=self.flow_connections.validate_candidate(project_url,required_capabilities=self._flow_capabilities_for_project(project_id))
        if validation["status"]!="CONNECTED":
            error=FlowConnectionError(validation["code"]); error.failure_class=validation["code"]
            raise error
        connection=self.flow_connections.save_validated_candidate(validation)
        if not explicit_owner_decision:
            return {**self.flow_status(project_id),"connection_id":connection.connection_id,"rebind_required":True}
        return self.rebind_flow_project(project_id, explicit_owner_decision=True)

    def update_runtime_flow_connection(self, project_url: str) -> dict[str, Any]:
        validation=self.flow_connections.validate_candidate(project_url,required_capabilities=["IMAGE"])
        if validation["status"]!="CONNECTED":
            error=FlowConnectionError(validation["code"]); error.failure_class=validation["code"]
            raise error
        connection=self.flow_connections.save_validated_candidate(validation)
        return {**validation,"connection_id":connection.connection_id,"connection_revision":connection.revision}

    def review_asset(self, project_id: str, request_id: str, report: dict[str, Any]) -> dict[str, Any]:
        review_production_asset(self.runtime.root,project_id,request_id,report); return self.media_items(project_id)

    def accept_pending_visuals_by_owner(self, project_id: str, reason: str) -> dict[str, Any]:
        return accept_pending_visuals_by_owner(self.runtime.root, project_id, reason)

    def set_qc_policy(self, project_id: str, policy: str) -> dict[str, Any]:
        policy = validate_qc_policy(policy)
        if policy not in {AUTO_ACCEPT, MANUAL_REVIEW}:
            raise OperatorServiceError("AI_REVIEW_UNSUPPORTED")
        paths, config = self._project(project_id)
        with ProjectLock(paths.runtime, project_id):
            saved = {**config.settings, "qc_policy": policy}
            atomic_write_json(paths.project_file, ProjectConfig(project_id, content_path=config.content_path,
                              render_mode=config.render_mode, settings=saved, schema_version=config.schema_version).to_dict())
        return self.production_query(project_id)["quality"]

    def query_qc_status(self, project_id: str) -> dict[str, Any]:
        return self.production_query(project_id)["quality"]

    def apply_qc_policy(self, project_id: str) -> dict[str, Any]:
        paths, config = self._project(project_id)
        policy, _explicit = effective_qc_policy(config.settings)
        if policy == AUTO_ACCEPT:
            return apply_auto_accept_policy(self.runtime.root, project_id)
        if policy == MANUAL_REVIEW:
            return self.query_qc_status(project_id)
        raise OperatorServiceError("AI_REVIEW_UNSUPPORTED")

    def accept_selected_assets(self, project_id: str, request_ids: set[str] | None, reason: str) -> dict[str, Any]:
        return accept_selected_assets_by_owner(self.runtime.root, project_id, reason, request_ids)

    def reject_selected_assets(self, project_id: str, request_ids: set[str], reason: str) -> dict[str, Any]:
        if not request_ids or not isinstance(reason, str) or not reason.strip():
            raise OperatorServiceError("OWNER_REJECTION_INVALID")
        paths, config = self._project(project_id)
        policy, _explicit = effective_qc_policy(config.settings)
        if policy != MANUAL_REVIEW:
            raise OperatorServiceError("QC_POLICY_NOT_MANUAL_REVIEW")
        for request_id in request_ids:
            reject_selected_asset(self.runtime.root, project_id, request_id, reason=reason)
        return {"status": "REJECTED", "project_id": project_id, "rejected_assets": len(request_ids), "provider_dispatch_delta": 0}

    def reopen_false_positive_production_qc(self, project_id: str, request_id: str, *, expected_asset_sha256: str,
                                            reviewer: str, reason: str) -> dict[str, Any]:
        reopen_false_positive_production_qc(
            self.runtime.root, project_id, request_id, expected_asset_sha256=expected_asset_sha256,
            reviewer=reviewer, reason=reason,
        )
        return self.media_items(project_id)

    def reject_asset(self, project_id: str, request_id: str, reason: str) -> dict[str, Any]:
        reject_selected_asset(self.runtime.root,project_id,request_id,reason=reason); return self.media_items(project_id)

    def regenerate(self, project_id: str, request_id: str, reason: str="operator requested regeneration") -> dict[str, Any]:
        queue_regeneration(self.runtime.root,project_id,request_id,reason=reason); return self.media_items(project_id)

    def replace_asset(self, project_id: str, request_id: str, source: Path | str) -> dict[str, Any]:
        current=next((item for group in self.media_items(project_id).values() for item in group if item.get("request",{}).get("request_id")==request_id),None)
        if not current: raise OperatorServiceError("request not found")
        if current.get("status")=="AMBIGUOUS": raise OperatorServiceError("MANUAL_LOCAL_OVERRIDE_AMBIGUOUS_BLOCKED")
        regeneration=queue_regeneration(self.runtime.root,project_id,request_id,reason="operator local asset replacement")
        target_request_id=regeneration.get("replacement_request_id",request_id) if isinstance(regeneration,dict) else request_id
        adopt_manual_recovery(self.runtime.root,project_id,target_request_id,Path(source),settings={"source":"operator_replacement"},attribution="operator-selected local file")
        return self.media_items(project_id)

    def supersede_ambiguous_request(self, project_id: str, request_id: str, *, reason: str,
                                    acknowledge_historical_dispatch_unknown: bool) -> dict[str, Any]:
        return supersede_ambiguous_request(self.runtime.root,project_id,request_id,reason=reason,
                                           acknowledge_historical_dispatch_unknown=acknowledge_historical_dispatch_unknown)

    def replay_unresolved_request(
            self, project_id: str, request_id: str, *, reason: str,
            acknowledge_previous_dispatch_or_cost_may_have_occurred: bool,
            acknowledge_previous_output_ownership_unresolved: bool,
            acknowledge_replacement_may_consume_provider_credit: bool) -> dict[str, Any]:
        return replay_unresolved_request(
            self.runtime.root, project_id, request_id, reason=reason,
            acknowledge_previous_dispatch_or_cost_may_have_occurred=
                acknowledge_previous_dispatch_or_cost_may_have_occurred,
            acknowledge_previous_output_ownership_unresolved=
                acknowledge_previous_output_ownership_unresolved,
            acknowledge_replacement_may_consume_provider_credit=
                acknowledge_replacement_may_consume_provider_credit,
        )

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
        self._require_available_render_mode(config)
        if config.render_mode=="full_video_ai" and (media_type,requirement)!=("VIDEO","REQUIRED"): raise OperatorServiceError("full_video_ai requires VIDEO / REQUIRED")
        if config.render_mode=="ambient_story" and (media_type,requirement)!=("IMAGE","REQUIRED"): raise OperatorServiceError("ambient_story requires IMAGE / REQUIRED")
        if config.render_mode=="full_image" and (media_type,requirement)!=("IMAGE","REQUIRED"): raise OperatorServiceError("full_image requires IMAGE / REQUIRED")
        project=read_json(paths.project_file); media=project["settings"].setdefault("media",{}); media.setdefault("overrides",{})[shot_id]={"media_type":media_type,"requirement":requirement}; atomic_write_json(paths.project_file,project)
        run_visual_planning_stages(self.runtime.root,project_id,provider=provider); return self.planning_review(project_id)

    def set_pause(self, project_id: str, paused: bool) -> dict[str, bool]:
        paths,_=self._project(project_id); atomic_write_json(paths.artifact_path("output/execution_control.json"),{"pause_requested":bool(paused)})
        return {"pause_requested":bool(paused)}

    def _managed_flow_empty_baseline_authorized(self, project_id: str, config: ProjectConfig) -> bool:
        binding = managed_binding(config)
        if not binding or binding.get("state") != "BOUND":
            return False
        paths,_ = self._project(project_id)
        manifest_path = paths.artifact_path("output/generation_manifest.json")
        if not manifest_path.is_file():
            return True
        manifest = read_json(manifest_path)
        for entry in manifest.get("requests", []):
            for attempt in entry.get("attempts", []):
                settings = attempt.get("provider_settings") if isinstance(attempt, dict) else None
                activation = settings.get("activation") if isinstance(settings, dict) else None
                if (attempt.get("provider_execution_state") not in {None, "NOT_STARTED"}
                        or attempt.get("provider_boundary_entered_at") is not None
                        or attempt.get("dispatch_confirmed") is not False
                        or attempt.get("provider_job_id") is not None
                        or attempt.get("provider_lineage_card_id") is not None
                        or not isinstance(activation, dict)
                        or activation.get("input_dispatched") is not False):
                    return False
        return True

    def generate(self, project_id: str, *, request_ids: set[str] | None=None, executor: FlowExecutor | None=None, max_requests: int | None=None) -> dict[str, Any]:
        _,config=self._project(project_id)
        self._require_available_render_mode(config)
        if execution_mode(config.settings)=="RENDER_ONLY": raise OperatorServiceError("RENDER_ONLY does not submit visual provider requests.")
        if managed_binding(config) is not None:
            if self.flow_projects is None:
                raise FlowProjectBindingError("FLOW_PROJECT_AUTOMATION_UNAVAILABLE")
            self.flow_project_bindings.ensure(project_id,self.flow_projects)
        self.set_pause(project_id,False)
        connection,status=self.flow_connections.connection_for_project(
            project_id, required_capabilities=self._flow_capabilities_for_project(project_id, request_ids))
        if connection is None or status.get("status")!="CONNECTED":
            error=FlowConnectionError(status.get("code","FLOW_NOT_CONFIGURED")); error.failure_class=status.get("code","FLOW_NOT_CONFIGURED")
            raise error
        if executor is None:
            runtime=self.flow_connections.runtime_for_connection(connection)
            capabilities=preflight(runtime,FlowInspector(runtime))
            executor=FlowExecutor(capabilities,LiveFlowGenerator(
                runtime,
                allow_empty_provider_model_baseline=self._managed_flow_empty_baseline_authorized(project_id, config),
            ))
        return execute_generation(self.runtime.root,project_id,executor=executor,execute=True,request_ids=request_ids,production_batch=True,max_requests=max_requests,
                                  flow_connection_provenance=self.flow_connections.provenance(connection))

    def build_render_plan(self, project_id: str) -> dict[str, Any]:
        paths,config=self._project(project_id); load=lambda name:read_json(paths.artifact_path(f"output/{name}.json"))
        self._require_available_render_mode(config)
        settings,_=resolve_render_settings(config)
        plan=resolve_render_plan(project_id=project_id,project_root=paths.root,render_mode=config.render_mode,alignment=load("alignment"),shot_plan=load("shot_plan"),media_plan=load("media_plan"),generation_requests=load("generation_requests"),generation_manifest=load("generation_manifest"),settings=settings)
        atomic_write_json(paths.artifact_path("output/render_plan.json"),plan); return plan

    def render(self, project_id: str, *, force_final: bool = False) -> dict[str, Any]:
        _paths, config = self._project(project_id); self._require_available_render_mode(config)
        return run_render_stages(self.runtime.root, project_id, force_final=force_final)

    def publishing(self, project_id: str, action: str, *, provider=None) -> Any:
        _paths, config = self._project(project_id)
        self._require_available_render_mode(config)
        if action=="metadata": return run_publishing_metadata(self.runtime.root,project_id,provider=provider)
        if action=="prepare_thumbnail": return prepare_thumbnail_request(self.runtime.root,project_id)
        if action=="finalize_thumbnail": return finalize_thumbnail(self.runtime.root,project_id)
        raise OperatorServiceError("unknown publishing action")

    def open_output_folder(self, project_id: str) -> str:
        paths,_=self._project(project_id); target=paths.root/"output"
        if os.name=="nt": os.startfile(target)  # type: ignore[attr-defined]
        return str(target)
