"""Pure, fail-closed Flow terminal-observation classification.

This module produces durable evidence candidates only.  It does not execute a
recovery decision, call a provider, or authorize another generation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from story_auto.core.visual.recovery import FailureFamily


TERMINAL_CLASSIFIER_VERSION = "story-auto-flow-terminal-classifier/1.0.0"
_REQUIRED_TERMINAL_SIGNALS = frozenset({"warning", "refresh", "delete_forever"})
_SIGNATURES: tuple[tuple[FailureFamily, tuple[str, ...]], ...] = (
    (FailureFamily.PROVIDER_POLICY_BLOCK, ("policy", "current events", "reputation", "chính sách", "sự kiện hiện tại")),
    (FailureFamily.PROVIDER_RATE_LIMIT, ("rate limit", "too many requests", "try again later", "giới hạn tốc độ")),
    (FailureFamily.PROVIDER_AUTH_BLOCK, ("sign in", "authentication", "session expired", "đăng nhập")),
    (FailureFamily.PROVIDER_CREDIT_BLOCK, ("insufficient credit", "not enough credits", "quota exceeded", "hết tín dụng")),
)


def _json_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_message(raw_message: object) -> str:
    return " ".join(str(raw_message or "").casefold().split())


def classify_message(raw_message: object) -> FailureFamily | None:
    """Return only a deterministic, high-confidence message family candidate."""
    normalized = _normalized_message(raw_message)
    if not normalized:
        return None
    for family, signatures in _SIGNATURES:
        if any(signature in normalized for signature in signatures):
            return family
    return None


def terminal_structural_signals(record: dict[str, Any]) -> list[str]:
    """Project trusted Flow tile structure without treating text as authority."""
    signals = record.get("terminal_structural_signals")
    if not isinstance(signals, list):
        return []
    return sorted({str(signal).strip() for signal in signals if str(signal).strip()})


def has_trusted_terminal_structure(record: dict[str, Any]) -> bool:
    return (
        record.get("state") == "FAILED"
        and record.get("failure_class") == "PROVIDER_VISIBLE_TERMINAL_FAILURE"
        and _REQUIRED_TERMINAL_SIGNALS.issubset(terminal_structural_signals(record))
    )


def _bound_card_id(attempt: dict[str, Any]) -> str | None:
    attributed = attempt.get("attributed_provider_identity")
    if isinstance(attributed, dict) and isinstance(attributed.get("card_id"), str):
        return attributed["card_id"]
    binding = attempt.get("provider_poll_authoritative_binding")
    if isinstance(binding, dict):
        durable_identity = binding.get("durable_identity_used")
        if isinstance(durable_identity, str) and durable_identity.startswith("card:"):
            return durable_identity.removeprefix("card:")
    value = attempt.get("provider_lineage_card_id")
    return value if isinstance(value, str) and value else None


def _exact_attribution(attempt: dict[str, Any], card_id: str | None) -> bool:
    if not card_id or _bound_card_id(attempt) != card_id:
        return False
    if attempt.get("attribution_state") == "CONFIRMED":
        return True
    binding = attempt.get("provider_poll_authoritative_binding")
    return (
        isinstance(binding, dict)
        and binding.get("resulting_dispatch_state") == "CONFIRMED"
        and binding.get("durable_identity_used") == f"card:{card_id}"
    )


def _dispatch_certainty(attempt: dict[str, Any]) -> str:
    if attempt.get("provider_execution_state") in {None, "NOT_STARTED"}:
        return "NOT_DISPATCHED"
    if attempt.get("dispatch_confirmed") is True or attempt.get("dispatch_confirmation_state") == "CONFIRMED":
        return "DISPATCH_CONFIRMED"
    return "DISPATCH_UNCERTAIN"


def build_terminal_evidence(*, request_id: str, attempt: dict[str, Any], observation: dict[str, Any],
                            observed_at: str, flow_project_identity: str | None = None,
                            flow_connection_revision: str | None = None) -> dict[str, Any]:
    """Bind one visible terminal observation to an attempt without side effects."""
    card_id = observation.get("card_id") if isinstance(observation.get("card_id"), str) else None
    structural_terminal = has_trusted_terminal_structure(observation)
    candidate = classify_message(observation.get("raw_message"))
    exact_attribution = _exact_attribution(attempt, card_id)
    authoritative = structural_terminal and exact_attribution
    family = candidate if authoritative and candidate is not None else (
        FailureFamily.PROVIDER_TERMINAL_UNKNOWN if authoritative else None
    )
    connection = attempt.get("flow_connection") if isinstance(attempt.get("flow_connection"), dict) else {}
    evidence = {
        "schema_version": "story-auto-flow-terminal-evidence/1.0.0",
        "provider": "google_flow",
        "request_id": request_id,
        "attempt": attempt.get("attempt"),
        "flow_project_identity": flow_project_identity or connection.get("flow_project_identity") or connection.get("project_identity"),
        "flow_connection_id": connection.get("flow_connection_id"),
        "flow_connection_revision": flow_connection_revision or connection.get("connection_revision"),
        "provider_card_id": card_id,
        "provider_job_id": observation.get("provider_job_id"),
        "observed_at": observed_at,
        "observed_provider_state": observation.get("state"),
        "terminal_structural_signals": terminal_structural_signals(observation),
        "terminal_structural_evidence": structural_terminal,
        "raw_provider_message": str(observation.get("raw_message") or ""),
        "observed_locale": observation.get("locale"),
        "classification_candidate": candidate.value if candidate is not None else None,
        "failure_family": family.value if family is not None else None,
        "classifier_version": TERMINAL_CLASSIFIER_VERSION,
        "exact_attribution_confirmed": exact_attribution,
        "authoritative": authoritative,
        "dispatch_certainty": _dispatch_certainty(attempt),
        "attribution_evidence": {
            "attribution_state": attempt.get("attribution_state"),
            "bound_card_id": _bound_card_id(attempt),
        },
    }
    digest_fields = {key: value for key, value in evidence.items() if key != "evidence_digest_sha256"}
    evidence["evidence_digest_sha256"] = _json_sha256(digest_fields)
    return evidence
