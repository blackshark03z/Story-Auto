"""Product-safe Full Video provider projection for the operator UI.

The projection reads only canonical project config and durable production
artifacts.  It never reads Goal 54 research ledgers, provider credentials, or
signed provider URLs, and it never performs a provider call.
"""
from __future__ import annotations

from typing import Any

from story_auto.core.artifacts import read_json
from story_auto.core.full_video_provider import (DEFAULT_FULL_VIDEO_PROVIDER,
                                                 full_video_provider_snapshot)


_PROVIDER_LABELS = {
    "byteplus_seedance": "BytePlus ModelArk / Seedance",
    "elyum_seedance": "Elyum / Seedance",
}


def _safe_json(path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return read_json(path)
    except Exception:
        return fallback


def _latest_attempt(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    attempts = entry.get("attempts") if isinstance(entry, dict) else None
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
        return None
    return attempts[-1]


def _entry_for_display(paths, provider_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    requests_value = _safe_json(paths.artifact_path("output/generation_requests.json"), {})
    manifest = _safe_json(paths.artifact_path("output/generation_manifest.json"), {})
    requests = [item for item in requests_value.get("requests", []) if isinstance(item, dict)] if isinstance(requests_value, dict) else []
    entries = [item for item in manifest.get("requests", []) if isinstance(item, dict)] if isinstance(manifest, dict) else []
    by_id = {item.get("request_id"): item for item in entries if isinstance(item.get("request_id"), str)}
    ordered = [item for item in requests if item.get("purpose") == "SHOT" and item.get("media_type") == "VIDEO" and item.get("provider") == provider_id]
    ordered.sort(key=lambda item: (float(item.get("target_start") or 0.0), int(item.get("part_index") or 0), str(item.get("request_id") or "")))
    selected_request = None
    selected_entry = None
    for request in ordered:
        entry = by_id.get(request.get("request_id"))
        if not isinstance(entry, dict) or entry.get("status") != "SUCCEEDED":
            selected_request, selected_entry = request, entry
            break
    if selected_request is None and ordered:
        selected_request = ordered[-1]
        selected_entry = by_id.get(selected_request.get("request_id"))
    return selected_request, selected_entry


def _continuation_text(status: str, attempt: dict[str, Any] | None, routing_enabled: bool) -> str:
    known_job = isinstance(attempt, dict) and isinstance(attempt.get("provider_job_id"), str) and bool(attempt.get("provider_job_id"))
    if status == "NOT_STARTED":
        return ("No provider task exists yet. Production routing is still locked until Goal 54 UAT is accepted."
                if not routing_enabled else "No provider task exists yet. Continue may create the first provider task after preflight.")
    if status in {"GENERATING", "WAIT_UNAVAILABLE", "SUBMITTED"} and known_job:
        return "Continue resumes the existing provider job; it must not create a replacement generation."
    if status in {"AMBIGUOUS", "REPLAY_SAME_CLIENT_REF"}:
        return "The create outcome is ambiguous. Recovery reuses the saved client identity only; a new logical attempt is not authorized."
    if status == "PREVIEW_READY":
        return "The exact locked preview is ready for Owner review. No Keep or Kill consequence has run yet."
    if status == "KEEP_REQUIRED":
        return "The Owner accepted this exact preview. Keep/unlock is the next explicit consequence and may spend provider credits."
    if status == "PREVIEW_REJECTED":
        return "The Owner rejected this exact preview. Kill is explicit; no replacement generation is automatic."
    if status == "KEEP_ACQUISITION_REQUIRED":
        return "Keep is already confirmed. Only clean-output acquisition may be retried; Story Auto must not Keep again."
    if status in {"KEEP_AMBIGUOUS", "KILL_AMBIGUOUS", "KEEP_DISPATCHING", "KILL_DISPATCHING"}:
        return "A provider consequence outcome is ambiguous. Automatic retry is blocked until it is reconciled."
    if status == "KILLED":
        return "The rejected provider result was killed. A replacement requires a separate explicit Owner authorization."
    if status in {"REPLACEMENT_AUTHORIZED", "PRE_DISPATCH"} and isinstance(attempt, dict) and attempt.get("replacement_authorized") is True:
        return "The Owner authorized exactly one replacement attempt. Continue will preflight it before any provider mutation."
    if status == "SUCCEEDED":
        return "The clean output is acquired locally and hash-bound to the accepted preview."
    if status == "CREDIT_BLOCKED":
        return "Generation is blocked before mutation because the observed provider balance is insufficient."
    if status == "COST_BLOCKED":
        return "Generation is blocked before mutation because the quote exceeds this project's credit bound."
    if status in {"FAILED_TERMINAL", "FAILED_RETRYABLE", "PREVIEW_ACQUISITION_FAILED"}:
        return "Provider recovery is required. Story Auto will not silently create a replacement generation."
    return "Story Auto is preserving the durable provider state; no implicit replacement is authorized."


def full_video_provider_product_view(paths, config) -> dict[str, Any] | None:
    """Return a compact safe projection for Full Video product surfaces."""
    if config.render_mode != "full_video_ai":
        return None
    snapshot = full_video_provider_snapshot(config.settings)
    provider_id = snapshot.get("provider_id", DEFAULT_FULL_VIDEO_PROVIDER)
    request, entry = _entry_for_display(paths, provider_id)
    attempt = _latest_attempt(entry)
    status = str((attempt or {}).get("status") or (entry or {}).get("status") or "NOT_STARTED")
    preflight_events = entry.get("preflight_events") if isinstance(entry, dict) else None
    preflight = preflight_events[-1] if isinstance(preflight_events, list) and preflight_events and isinstance(preflight_events[-1], dict) else None
    preview = attempt.get("preview_asset") if isinstance(attempt, dict) and isinstance(attempt.get("preview_asset"), dict) else None
    selected = entry.get("selected_asset") if isinstance(entry, dict) and isinstance(entry.get("selected_asset"), dict) else None
    routing_enabled = snapshot.get("production_enabled") is True
    unlock_credits = attempt.get("unlock_credits") if isinstance(attempt, dict) else None
    review = attempt.get("preview_review") if isinstance(attempt, dict) and isinstance(attempt.get("preview_review"), dict) else None
    action = None
    if status == "PREVIEW_READY":
        action = "REVIEW_PREVIEW"
    elif status == "KEEP_REQUIRED":
        action = "KEEP_PREVIEW"
    elif status == "PREVIEW_REJECTED":
        action = "KILL_PREVIEW"
    elif status == "KEEP_ACQUISITION_REQUIRED":
        action = "REACQUIRE_KEPT_OUTPUT"
    elif status in {"KEEP_AMBIGUOUS", "KILL_AMBIGUOUS", "KEEP_DISPATCHING", "KILL_DISPATCHING"}:
        action = "RECONCILE_CONSEQUENCE"
    elif status == "KILLED":
        action = "AUTHORIZE_REPLACEMENT"
    return {
        "provider_id": provider_id,
        "provider_label": _PROVIDER_LABELS.get(provider_id, provider_id),
        "generation_mode": snapshot.get("generation_mode"),
        "routing_enabled": routing_enabled,
        "routing_state": "PRODUCTION_ENABLED" if routing_enabled else "INTEGRATION_STAGED",
        "request_id": request.get("request_id") if isinstance(request, dict) else None,
        "status": status,
        "failure_class": entry.get("failure_class") if isinstance(entry, dict) else None,
        "known_job": bool(isinstance(attempt, dict) and isinstance(attempt.get("provider_job_id"), str) and attempt.get("provider_job_id")),
        "continuation_behavior": _continuation_text(status, attempt, routing_enabled),
        "budget": {
            "balance": preflight.get("balance") if isinstance(preflight, dict) else (attempt.get("balance_before") if isinstance(attempt, dict) else None),
            "estimate_credits": preflight.get("estimate_credits") if isinstance(preflight, dict) else (attempt.get("estimate_credits") if isinstance(attempt, dict) else None),
            "max_credits": preflight.get("max_credits") if isinstance(preflight, dict) else None,
            "unlock_credits": unlock_credits,
        },
        "preview_path": preview.get("path") if isinstance(preview, dict) else None,
        "preview_sha256": preview.get("sha256") if isinstance(preview, dict) else None,
        "preview_review": {
            "decision": review.get("decision"), "reason": review.get("reason"), "reviewed_at": review.get("reviewed_at")
        } if isinstance(review, dict) else None,
        "selected_path": selected.get("path") if isinstance(selected, dict) else None,
        "selected_sha256": selected.get("sha256") if isinstance(selected, dict) else None,
        "action": action,
        "owner_decision_required": action in {"REVIEW_PREVIEW", "KEEP_PREVIEW", "KILL_PREVIEW", "RECONCILE_CONSEQUENCE", "AUTHORIZE_REPLACEMENT"},
    }
