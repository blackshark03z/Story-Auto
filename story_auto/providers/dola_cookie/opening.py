"""Dola T2V acquisition through the canonical Hybrid Opening manifest."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import time
from uuid import uuid4

from story_auto.core.project.lock import ProjectLock
from story_auto.core.visual.opening_builder import import_opening_clip
from story_auto.providers.byteplus_seedance.opening import (
    _project, _load_slot, _persist, _safe_view, _now,
)
from .accounts import DolaAccountStore
from .client import DolaCookieClient, DolaCookieError

PROVIDER_ID = "dola_cookie"


def generate_dola_opening(runtime_root, project_id, slot_id, *, account_id="",
                          client=None, max_poll_seconds=0.0, poll_interval=2.0):
    """Submit once or resume the persisted conversation; never rotate accounts."""
    runtime, paths, config = _project(runtime_root, project_id)
    policy = str(config.settings.get("hybrid_visual", {}).get("opening_provider_policy", "AUTO")).upper()
    with ProjectLock(runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id)
        existing = slot.get("api_generation") or {}
        if existing and existing.get("provider") != PROVIDER_ID:
            raise DolaCookieError("OPENING_PROVIDER_MISMATCH")
        if existing.get("status") == "SUCCEEDED":
            return _safe_view(runtime.root, project_id)
        bound_account = existing.get("account_id")
        if bound_account and account_id and bound_account != account_id:
            raise DolaCookieError("DOLA_ACCOUNT_MISMATCH")
        account_id = bound_account or account_id
        if not existing and policy not in {"AUTO", "DOLA"}:
            raise DolaCookieError("OPENING_PROVIDER_POLICY_MISMATCH")
    if not isinstance(account_id, str) or not account_id.strip():
        raise DolaCookieError("DOLA_ACCOUNT_REQUIRED")
    lock_name = "dola_account_" + hashlib.sha256(account_id.encode()).hexdigest()[:24]
    with ProjectLock(runtime, lock_name):
        active = client if client is not None else DolaCookieClient(DolaAccountStore().get_cookie(account_id))
        with ProjectLock(runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id)
            generation = slot.get("api_generation")
            prompt = str(slot.get("prompt") or "").strip()
            duration = float(slot.get("duration_seconds") or 0)
            if not prompt or not math.isfinite(duration) or not 4 <= duration <= 10:
                raise DolaCookieError("OPENING_SLOT_INVALID")
            requested_duration = 5 if duration <= 5 else 10
            if generation:
                if generation.get("provider") != PROVIDER_ID or generation.get("account_id") != account_id:
                    raise DolaCookieError("DOLA_ATTEMPT_IDENTITY_MISMATCH")
                if generation.get("prompt_sha256") != slot.get("prompt_sha256"):
                    raise DolaCookieError("DOLA_PROMPT_CHANGED")
                if generation.get("status") in {"SUCCEEDED", "FAILED_TERMINAL"}:
                    return _safe_view(runtime.root, project_id)
                if (generation.get("status") == "FAILED_PRE_DISPATCH"
                        and generation.get("dispatch_state") == "NOT_DISPATCHED"):
                    generation.update(status="PRE_DISPATCH", dispatch_state="AMBIGUOUS",
                                      submit_attempts=int(generation.get("submit_attempts", 0)) + 1,
                                      failure_class=None, updated_at=_now())
                    _persist(paths, manifest)
                elif not generation.get("provider_task_id"):
                    generation.update(status="AMBIGUOUS", failure_class="DOLA_RECEIPT_MISSING", updated_at=_now())
                    _persist(paths, manifest)
                    return _safe_view(runtime.root, project_id)
            else:
                generation = {
                    "schema_version": "story-auto-dola-opening/1.0.0", "provider": PROVIDER_ID,
                    "provider_model": "seedance_v2.0", "observed_model": None,
                    "account_id": account_id, "attempt_id": uuid4().hex,
                    "prompt_sha256": slot.get("prompt_sha256"), "duration_seconds": duration,
                    "requested_duration_seconds": requested_duration,
                    "status": "PRE_DISPATCH", "dispatch_state": "AMBIGUOUS",
                    "provider_submissions": 0, "submit_attempts": 1,
                    "created_at": _now(), "updated_at": _now(),
                }
                slot["api_generation"] = generation
                _persist(paths, manifest)
            attempt_id = generation["attempt_id"]
            task_id = generation.get("provider_task_id")

        def update(**values):
            with ProjectLock(runtime, project_id):
                current, current_slot = _load_slot(paths, project_id, slot_id)
                record = current_slot.get("api_generation") or {}
                if record.get("attempt_id") != attempt_id or record.get("account_id") != account_id:
                    raise DolaCookieError("DOLA_ATTEMPT_IDENTITY_MISMATCH")
                record.update(values, updated_at=_now())
                _persist(paths, current)

        def receipt(conversation_id):
            if not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 200:
                raise DolaCookieError("DOLA_RECEIPT_INVALID", dispatch_state="AMBIGUOUS")
            update(provider_task_id=conversation_id, status="SUBMITTED", dispatch_state="CONFIRMED",
                   provider_submissions=1, failure_class=None)

        if not task_id:
            try:
                task_id = active.submit(prompt=prompt, aspect_ratio="16:9", duration=requested_duration,
                                        on_receipt=receipt, client_request_id=attempt_id)
            except Exception as error:
                # A persisted receipt remains sufficient for poll-only recovery,
                # even if the caller/stream fails immediately afterwards.
                with ProjectLock(runtime, project_id):
                    current, current_slot = _load_slot(paths, project_id, slot_id)
                    record = current_slot["api_generation"]
                    if not record.get("provider_task_id"):
                        known_unsent = isinstance(error, DolaCookieError) and error.dispatch_state == "NOT_DISPATCHED"
                        record.update(status="FAILED_PRE_DISPATCH" if known_unsent else "AMBIGUOUS",
                                      dispatch_state="NOT_DISPATCHED" if known_unsent else "AMBIGUOUS",
                                      failure_class=error.failure_class if known_unsent else "DOLA_SUBMISSION_UNCERTAIN",
                                      updated_at=_now())
                        _persist(paths, current)
                return _safe_view(runtime.root, project_id)
            with ProjectLock(runtime, project_id):
                current, current_slot = _load_slot(paths, project_id, slot_id)
                if not task_id or current_slot["api_generation"].get("provider_task_id") != task_id:
                    raise DolaCookieError("DOLA_RECEIPT_NOT_PERSISTED", dispatch_state="AMBIGUOUS")

        deadline = time.monotonic() + max(0, float(max_poll_seconds))
        while True:
            try:
                result = active.poll(task_id, client_request_id=attempt_id)
                status = result.get("status")
                if status == "FAILED":
                    update(status="FAILED_TERMINAL", failure_class="DOLA_PROVIDER_FAILED")
                    break
                if status == "COMPLETED":
                    update(status="ACQUIRING", provider_task_status="succeeded")
                    destination = paths.artifact_path(f"assets/opening/dola/{attempt_id}.mp4")
                    # Acquire through the same conversation on every recovery;
                    # URLs never become durable task identity.
                    if not destination.exists():
                        active.download(result["video_url"], destination)
                    import_opening_clip(runtime.root, project_id, slot_id, destination,
                                        original_filename=f"dola_{slot_id}.mp4",
                                        _provider_identity={"provider": PROVIDER_ID, "provider_task_id": task_id,
                                                            "account_id": account_id})
                    break
                if status != "PENDING":
                    raise DolaCookieError("DOLA_STATUS_UNKNOWN", dispatch_state="CONFIRMED")
                update(status="GENERATING", failure_class=None)
            except Exception as error:
                code = error.failure_class if isinstance(error, DolaCookieError) else "DOLA_RECOVERY_REQUIRED"
                update(status="WAIT_UNAVAILABLE", failure_class=code)
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(max(.05, float(poll_interval)))
        return _safe_view(runtime.root, project_id)
