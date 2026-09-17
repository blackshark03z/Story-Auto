"""Elyum Seedance acquisition for Hybrid Visual opening slots.

The canonical Opening Builder manifest remains authoritative. Elyum keeps its
locked-preview consequence lifecycle: generate -> review -> Keep/Kill.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib, json, math, shutil
from pathlib import Path
from typing import Any, Callable
import urllib.request

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.visual.opening_builder import OPENING_BUILDER_VERSION, OPENING_MANIFEST_PATH, import_opening_clip, opening_builder_view
from story_auto.providers.credentials import provider_keys
from story_auto.providers.flow.validation import AssetValidationError, validate_video
from .client import ElyumSeedanceClient, ElyumSeedanceError

PROVIDER_ID = "elyum_seedance"
OPENING_API_VERSION = "story-auto-opening-api-elyum/1.0.0"
_TERMINAL = {"failed", "error", "cancelled", "canceled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project(runtime_root: Path | str, project_id: str):
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "hybrid_hook":
        raise ElyumSeedanceError("OPENING_API_MODE_INVALID")
    return runtime, paths


def _load_slot(paths, project_id: str, slot_id: str):
    path = paths.artifact_path(OPENING_MANIFEST_PATH)
    if not path.is_file():
        raise ElyumSeedanceError("OPENING_NOT_CONFIGURED")
    manifest = read_json(path)
    if manifest.get("schema_version") != OPENING_BUILDER_VERSION or manifest.get("project_id") != project_id:
        raise ElyumSeedanceError("OPENING_MANIFEST_INVALID")
    slot = next((item for item in manifest.get("slots", []) if isinstance(item, dict) and item.get("slot_id") == slot_id), None)
    if slot is None:
        raise ElyumSeedanceError("OPENING_SLOT_NOT_FOUND")
    return manifest, slot


def _persist(paths, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    atomic_write_json(paths.artifact_path(OPENING_MANIFEST_PATH), manifest)


def _view(root: Path | str, project_id: str) -> dict[str, Any]:
    return opening_builder_view(root, project_id) or {}


def _client_ref(project_id: str, slot: dict[str, Any], model: str, duration: int, resolution: str) -> str:
    identity = {"project_id": project_id, "slot_id": slot.get("slot_id"), "prompt_sha256": slot.get("prompt_sha256"), "model": model, "duration": duration, "resolution": resolution}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return "story-auto-opening-" + digest[:48]


def _fetch(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "StoryAuto-ElyumOpening/1", "Accept": "video/mp4,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read()
        if not payload:
            raise ElyumSeedanceError("ELYUM_VIDEO_EMPTY")
        destination.write_bytes(payload)
    except ElyumSeedanceError:
        raise
    except Exception as error:
        raise ElyumSeedanceError("ELYUM_VIDEO_DOWNLOAD_FAILED") from error


def _preview_valid(paths, generation: dict[str, Any]) -> bool:
    asset = generation.get("preview_asset")
    if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
        return False
    path = paths.artifact_path(asset["path"])
    if not path.is_file():
        return False
    try:
        metadata = validate_video(path)
    except AssetValidationError:
        return False
    return metadata.get("sha256") == asset.get("sha256")


def _credential_clients(client: ElyumSeedanceClient | None = None) -> list[tuple[int, ElyumSeedanceClient]]:
    if client is not None:
        return [(1, client)]
    try:
        keys = provider_keys("elyum")
    except Exception as error:
        raise ElyumSeedanceError("CREDENTIAL_MISSING") from error
    clients = [(index, ElyumSeedanceClient(key=key)) for index, key in enumerate(keys, 1)]
    if not clients:
        raise ElyumSeedanceError("CREDENTIAL_MISSING")
    return clients


def _client_for_credential_slot(credential_slot: int, client: ElyumSeedanceClient | None = None) -> ElyumSeedanceClient:
    if client is not None:
        if credential_slot != 1:
            raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISMATCH")
        return client
    try:
        keys = provider_keys("elyum")
    except Exception as error:
        raise ElyumSeedanceError("CREDENTIAL_MISSING") from error
    if credential_slot < 1 or credential_slot > len(keys):
        raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISSING")
    return ElyumSeedanceClient(key=keys[credential_slot - 1])


def preflight_elyum_opening_slot(runtime_root: Path | str, project_id: str, slot_id: str, *,
                                 client: ElyumSeedanceClient | None = None,
                                 resolution: str = "480p") -> dict[str, Any]:
    """Read-only per-slot pool-aware Seedance preflight; never dispatches a render."""
    runtime, paths = _project(runtime_root, project_id)
    if resolution not in {"480p", "720p", "1080p"}:
        raise ElyumSeedanceError("RESOLUTION_UNSUPPORTED", resolution)
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id)
        prompt_sha = slot.get("prompt_sha256")
        target = float(slot.get("duration_seconds") or 0.0)
        provider_duration = int(math.ceil(target))
        if not str(slot.get("prompt") or "").strip() or not 4 <= provider_duration <= 30:
            raise ElyumSeedanceError("OPENING_API_SLOT_INVALID")

    observations: list[dict[str, Any]] = []
    credential_summaries: list[dict[str, Any]] = []
    for credential_slot, active in _credential_clients(client):
        readiness = active.readiness()
        if readiness.get("status") != "READY":
            continue
        try:
            balance = int(active.account_balance())
            model_ids = active.seedance_model_ids()[:12]
        except ElyumSeedanceError:
            continue
        credential_summaries.append({"credential_slot": credential_slot, "balance": balance})
        for model_id in model_ids:
            try:
                estimate = int(active.estimate_video(model=model_id, duration=provider_duration, mode="t2v", resolution=resolution))
            except ElyumSeedanceError:
                continue
            observations.append({
                "model_id": model_id,
                "estimate_credits": estimate,
                "affordable": balance >= estimate,
                "credential_slot": credential_slot,
                "balance": balance,
            })

    selected_models: list[dict[str, Any]] = []
    for model_id in dict.fromkeys(item["model_id"] for item in observations):
        candidates = [item for item in observations if item["model_id"] == model_id]
        affordable = [item for item in candidates if item["affordable"]]
        selected = min(affordable or candidates, key=lambda item: item["credential_slot"])
        selected_models.append(selected)
    max_balance = max((item["balance"] for item in credential_summaries), default=0)
    preflight = {
        "status": "READY" if selected_models else "NO_COMPATIBLE_MODEL",
        "provider": PROVIDER_ID,
        "resolution": resolution,
        "provider_duration_seconds": provider_duration,
        "prompt_sha256": prompt_sha,
        "balance": max_balance,
        "max_balance": max_balance,
        "credential_slots": credential_summaries,
        "models": selected_models,
        "checked_at": _now(),
    }
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id)
        if slot.get("prompt_sha256") != prompt_sha or int(math.ceil(float(slot.get("duration_seconds") or 0.0))) != provider_duration:
            raise ElyumSeedanceError("OPENING_PREFLIGHT_STALE")
        slot["elyum_preflight"] = preflight
        _persist(paths, manifest)
    return _view(runtime.root, project_id)


def generate_elyum_opening_preview(runtime_root: Path | str, project_id: str, slot_id: str, *, model: str,
                                   client: ElyumSeedanceClient | None = None, credential_slot: int | None = None,
                                   resolution: str = "480p", max_credits: int = 44, wait_seconds: int = 50,
                                   preview_fetcher: Callable[[str, Path], None] | None = None) -> dict[str, Any]:
    runtime, paths = _project(runtime_root, project_id)
    if client is not None and credential_slot is None:
        credential_slot = 1
    model = str(model or "").strip()
    if not model:
        raise ElyumSeedanceError("MODEL_REQUIRED")
    if resolution not in {"480p", "720p", "1080p"}:
        raise ElyumSeedanceError("RESOLUTION_UNSUPPORTED", resolution)
    job_id = None; replay = False; prompt = ""; client_ref = ""; provider_duration = 0; selected_slot = 0
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id)
        if slot.get("status") == "READY" and isinstance(slot.get("normalized_asset"), dict):
            return _view(runtime.root, project_id)
        prompt = str(slot.get("prompt") or "").strip()
        target = float(slot.get("duration_seconds") or 0.0)
        provider_duration = int(math.ceil(target))
        if not prompt or not 4 <= provider_duration <= 30:
            raise ElyumSeedanceError("OPENING_API_SLOT_INVALID")
        generation = slot.get("api_generation")
        if isinstance(generation, dict):
            if generation.get("provider") != PROVIDER_ID: raise ElyumSeedanceError("OPENING_API_PROVIDER_MISMATCH")
            if generation.get("provider_model") != model: raise ElyumSeedanceError("OPENING_API_MODEL_MISMATCH")
            stored_slot = generation.get("credential_slot")
            if credential_slot is not None and stored_slot not in {None, credential_slot}:
                raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISMATCH")
            if stored_slot is None:
                if credential_slot is None:
                    raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISSING")
                generation["credential_slot"] = credential_slot
                stored_slot = credential_slot
                _persist(paths, manifest)
            selected_slot = int(stored_slot)
            status = str(generation.get("status") or "")
            if status in {"PREVIEW_READY","KEEP_REQUIRED","PREVIEW_REJECTED","KEEP_DISPATCHING","KEEP_ACQUISITION_REQUIRED","KEEP_AMBIGUOUS","KILL_DISPATCHING","KILL_AMBIGUOUS","KILLED","SUCCEEDED","FAILED_TERMINAL"}:
                return _view(runtime.root, project_id)
            existing = generation.get("provider_job_id")
            if isinstance(existing, str) and existing.strip(): job_id = existing.strip()
            elif status == "AMBIGUOUS" and generation.get("recovery") == "REPLAY_SAME_CLIENT_REF": replay = True
            elif status not in {"PRE_DISPATCH","FAILED_PRE_DISPATCH","COST_BLOCKED","CREDIT_BLOCKED","AMBIGUOUS"}: raise ElyumSeedanceError("OPENING_API_STATE_INVALID")
            client_ref = str(generation.get("client_ref") or "")
            if not client_ref: raise ElyumSeedanceError("OPENING_API_CLIENT_REF_MISSING")
        else:
            if credential_slot is None:
                raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISSING")
            selected_slot = int(credential_slot)
            client_ref = _client_ref(project_id, slot, model, provider_duration, resolution)
            slot["api_generation"] = generation = {"schema_version": OPENING_API_VERSION, "provider": PROVIDER_ID, "provider_model": model, "credential_slot": selected_slot, "status": "PRE_DISPATCH", "provider_submissions": 0, "provider_create_calls": 0, "client_ref": client_ref, "resolution": resolution, "prompt_sha256": slot.get("prompt_sha256"), "duration_seconds": target, "provider_duration_seconds": provider_duration, "created_at": _now(), "updated_at": _now()}
            _persist(paths, manifest)
    active = _client_for_credential_slot(selected_slot, client)
    if active.readiness().get("status") != "READY":
        raise ElyumSeedanceError(active.readiness().get("reason_code") or "CREDENTIAL_MISSING")
    if job_id is None:
        balance = active.account_balance(); estimate = active.estimate_video(model=model, duration=provider_duration, mode="t2v", resolution=resolution)
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
            generation.update({"balance_before": int(balance), "estimate_credits": int(estimate), "max_credits": int(max_credits), "last_preflight_at": _now()})
            if int(estimate) > int(max_credits): generation.update({"status":"COST_BLOCKED","failure_class":"ESTIMATE_EXCEEDS_BOUND"}); _persist(paths, manifest); return _view(runtime.root, project_id)
            if int(balance) < int(estimate): generation.update({"status":"CREDIT_BLOCKED","failure_class":"INSUFFICIENT_CREDIT_BALANCE"}); _persist(paths, manifest); return _view(runtime.root, project_id)
            generation.update({"status":"PRE_DISPATCH","failure_class":None,"dispatch_state":"RECONCILE_BY_CLIENT_REF" if replay else "NOT_DISPATCHED","provider_create_calls":int(generation.get("provider_create_calls") or 0)+1,"updated_at":_now()}); _persist(paths, manifest)
        try:
            job_id, _ = active.make_video(client_ref=client_ref, model=model, prompt=prompt, duration=provider_duration, mode="t2v", aspect_ratio="16:9", resolution=resolution, audio=False)
        except ElyumSeedanceError as error:
            with ProjectLock(paths.runtime, project_id):
                manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
                if error.dispatch_state == "RECONCILE_BY_CLIENT_REF": generation.update({"status":"AMBIGUOUS","failure_class":error.failure_class,"dispatch_state":"AMBIGUOUS","recovery":"REPLAY_SAME_CLIENT_REF","updated_at":_now()})
                else: generation.update({"status":"FAILED_PRE_DISPATCH","failure_class":error.failure_class,"dispatch_state":"NOT_DISPATCHED","updated_at":_now()})
                _persist(paths, manifest)
            return _view(runtime.root, project_id)
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
            generation.update({"status":"SUBMITTED","provider_job_id":str(job_id),"provider_submissions":1,"dispatch_state":"CONFIRMED","submitted_at":_now(),"failure_class":None,"updated_at":_now()}); _persist(paths, manifest)
    try:
        result = active.wait(str(job_id), timeout_seconds=max(0,min(55,int(wait_seconds))), thumbnails=True)
    except ElyumSeedanceError as error:
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
            generation.update({"status":"WAIT_UNAVAILABLE","failure_class":error.failure_class,"last_observed_at":_now(),"updated_at":_now()}); _persist(paths, manifest)
        return _view(runtime.root, project_id)
    gen_id = active.gen_id(result); state = active.execution_state(result); urls = list(active.preview_urls(result)); unlock = active.unlock_credits(result)
    if not gen_id:
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
            generation.update({"status":"FAILED_TERMINAL" if state in _TERMINAL else "GENERATING","provider_task_status":state,"last_observed_at":_now(),"updated_at":_now()}); _persist(paths, manifest)
        return _view(runtime.root, project_id)
    if not urls: raise ElyumSeedanceError("ELYUM_PREVIEW_URL_MISSING")
    relative = f"assets/opening/elyum/{slot_id}/locked_preview.mp4"; destination = paths.artifact_path(relative)
    (preview_fetcher or _fetch)(urls[0], destination)
    try: metadata = validate_video(destination)
    except AssetValidationError as error: destination.unlink(missing_ok=True); raise ElyumSeedanceError("VIDEO_ASSET_INVALID") from error
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
        generation.update({"status":"PREVIEW_READY","provider_task_status":state,"gen_id":gen_id,"unlock_credits":unlock,"preview_asset":{"path":relative,"sha256":metadata["sha256"],"metadata":metadata,"locked":True},"failure_class":None,"last_observed_at":_now(),"updated_at":_now()}); _persist(paths, manifest)
    return _view(runtime.root, project_id)


def review_elyum_opening_preview(runtime_root: Path | str, project_id: str, slot_id: str, *, decision: str, reason: str) -> dict[str, Any]:
    decision = str(decision or "").upper()
    if decision not in {"ACCEPT","REJECT"}: raise ElyumSeedanceError("ELYUM_PREVIEW_DECISION_INVALID")
    if not str(reason or "").strip(): raise ElyumSeedanceError("ELYUM_PREVIEW_REVIEW_REASON_REQUIRED")
    runtime, paths = _project(runtime_root, project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot.get("api_generation")
        if not isinstance(generation, dict) or generation.get("provider") != PROVIDER_ID: raise ElyumSeedanceError("OPENING_API_PROVIDER_MISMATCH")
        if generation.get("status") != "PREVIEW_READY" or not _preview_valid(paths, generation): raise ElyumSeedanceError("ELYUM_PREVIEW_NOT_READY")
        generation["preview_review"] = {"decision":decision,"reason":str(reason).strip(),"preview_sha256":generation["preview_asset"]["sha256"],"reviewed_at":_now()}
        generation.update({"status":"KEEP_REQUIRED" if decision == "ACCEPT" else "PREVIEW_REJECTED","updated_at":_now()}); _persist(paths, manifest)
    return _view(runtime.root, project_id)


def keep_elyum_opening_preview(runtime_root: Path | str, project_id: str, slot_id: str, *, client: ElyumSeedanceClient | None = None, confirm_spend: bool = False, output_fetcher: Callable[[str, Path], None] | None = None) -> dict[str, Any]:
    runtime, paths = _project(runtime_root, project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot.get("api_generation")
        if not isinstance(generation, dict) or generation.get("provider") != PROVIDER_ID: raise ElyumSeedanceError("OPENING_API_PROVIDER_MISMATCH")
        selected_slot = int(generation.get("credential_slot") or (1 if client is not None else 0))
        if selected_slot < 1: raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISSING")
    active = _client_for_credential_slot(selected_slot, client)
    if active.readiness().get("status") != "READY": raise ElyumSeedanceError(active.readiness().get("reason_code") or "CREDENTIAL_MISSING")
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot.get("api_generation")
        if not isinstance(generation, dict) or int(generation.get("credential_slot") or selected_slot) != selected_slot: raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISMATCH")
        if generation.get("status") in {"KEEP_AMBIGUOUS","KEEP_DISPATCHING"}: raise ElyumSeedanceError("ELYUM_KEEP_OUTCOME_AMBIGUOUS")
        if generation.get("status") == "SUCCEEDED" and slot.get("status") == "READY":
            return _view(runtime.root, project_id)
        recovering = generation.get("status") == "KEEP_ACQUISITION_REQUIRED" and generation.get("keep_confirmed") is True
        gen_id = generation.get("gen_id")
        urls = list(generation.get("kept_output_urls") or []) if recovering else []
        if not recovering:
            if confirm_spend is not True: raise ElyumSeedanceError("ELYUM_KEEP_CONFIRMATION_REQUIRED")
            if generation.get("status") != "KEEP_REQUIRED" or not _preview_valid(paths, generation): raise ElyumSeedanceError("ELYUM_KEEP_NOT_ALLOWED")
            generation["consequence_intent"]={"action":"KEEP","recorded_at":_now(),"gen_id":gen_id,"preview_sha256":generation["preview_asset"]["sha256"],"unlock_credits":generation.get("unlock_credits"),"credential_slot":selected_slot}
            generation.update({"status":"KEEP_DISPATCHING","keep_calls_started":int(generation.get("keep_calls_started") or 0)+1,"updated_at":_now()}); _persist(paths, manifest)
    if not recovering:
        try: result = active.keep(str(gen_id))
        except ElyumSeedanceError as error:
            with ProjectLock(paths.runtime, project_id):
                manifest, slot = _load_slot(paths, project_id, slot_id); slot["api_generation"].update({"status":"KEEP_AMBIGUOUS","failure_class":error.failure_class,"updated_at":_now()}); _persist(paths, manifest)
            return _view(runtime.root, project_id)
        # Persist confirmed spend before any fallible local acquisition work.
        # Reuse the existing production adapter's private recovery-URL contract.
        urls = list(active.downloadable_urls(result))
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id)
            slot["api_generation"].update({"status":"KEEP_ACQUISITION_REQUIRED", "keep_confirmed":True,
                                            "kept_output_urls":urls, "kept_at":_now(), "updated_at":_now()})
            _persist(paths, manifest)
    if not urls:
        observed = active.wait(str(generation.get("provider_job_id")), timeout_seconds=0, thumbnails=False)
        urls = list(active.downloadable_urls(observed))
    if not urls: raise ElyumSeedanceError("ELYUM_OUTPUT_URL_MISSING")
    temp = runtime.temp / "opening_elyum" / project_id / slot_id; temp.mkdir(parents=True, exist_ok=True); source = temp / "kept.mp4"
    try:
        (output_fetcher or _fetch)(urls[0], source)
        import_opening_clip(runtime.root, project_id, slot_id, source, original_filename=f"elyum_{slot_id}.mp4",
                            _provider_identity={"provider":PROVIDER_ID, "gen_id":str(gen_id)})
    finally: shutil.rmtree(temp, ignore_errors=True)
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot["api_generation"]
        if isinstance(slot.get("source_asset"), dict): slot["source_asset"].update({"provider":PROVIDER_ID,"provider_model":generation.get("provider_model"),"provider_job_id":generation.get("provider_job_id"),"provider_gen_id":gen_id,"source_preview_sha256":generation.get("preview_asset",{}).get("sha256")})
        generation.update({"status":"SUCCEEDED","keep_confirmed":True,"completed_at":_now(),"failure_class":None,"updated_at":_now()}); _persist(paths, manifest)
    return _view(runtime.root, project_id)


def kill_elyum_opening_preview(runtime_root: Path | str, project_id: str, slot_id: str, *, reason: str, client: ElyumSeedanceClient | None = None, confirm_kill: bool = False) -> dict[str, Any]:
    if confirm_kill is not True: raise ElyumSeedanceError("ELYUM_KILL_CONFIRMATION_REQUIRED")
    if not str(reason or "").strip(): raise ElyumSeedanceError("ELYUM_KILL_REASON_REQUIRED")
    runtime, paths = _project(runtime_root, project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot.get("api_generation")
        if not isinstance(generation, dict) or generation.get("provider") != PROVIDER_ID: raise ElyumSeedanceError("OPENING_API_PROVIDER_MISMATCH")
        selected_slot = int(generation.get("credential_slot") or (1 if client is not None else 0))
        if selected_slot < 1: raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISSING")
    active = _client_for_credential_slot(selected_slot, client)
    if active.readiness().get("status") != "READY": raise ElyumSeedanceError(active.readiness().get("reason_code") or "CREDENTIAL_MISSING")
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); generation = slot.get("api_generation")
        if not isinstance(generation, dict) or int(generation.get("credential_slot") or selected_slot) != selected_slot: raise ElyumSeedanceError("ELYUM_CREDENTIAL_SLOT_MISMATCH")
        if generation.get("status") in {"KILL_AMBIGUOUS","KILL_DISPATCHING"}: raise ElyumSeedanceError("ELYUM_KILL_OUTCOME_AMBIGUOUS")
        if generation.get("status") != "PREVIEW_REJECTED": raise ElyumSeedanceError("ELYUM_KILL_NOT_ALLOWED")
        gen_id = generation.get("gen_id"); generation["consequence_intent"]={"action":"KILL","recorded_at":_now(),"gen_id":gen_id,"preview_sha256":generation.get("preview_asset",{}).get("sha256"),"reason":str(reason).strip(),"credential_slot":selected_slot}
        generation.update({"status":"KILL_DISPATCHING","kill_calls_started":int(generation.get("kill_calls_started") or 0)+1,"updated_at":_now()}); _persist(paths, manifest)
    try: active.kill(str(gen_id), reason=str(reason).strip())
    except ElyumSeedanceError as error:
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id); slot["api_generation"].update({"status":"KILL_AMBIGUOUS","failure_class":error.failure_class,"updated_at":_now()}); _persist(paths, manifest)
        return _view(runtime.root, project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id); slot["api_generation"].update({"status":"KILLED","failure_class":"PREVIEW_REJECTED","killed_at":_now(),"updated_at":_now()}); _persist(paths, manifest)
    return _view(runtime.root, project_id)
