"""Pure, fail-closed Flow terminal-observation classification.

This module produces durable evidence candidates only.  It does not execute a
recovery decision, call a provider, or authorize another generation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from story_auto.core.visual.recovery import FailureFamily


TERMINAL_CLASSIFIER_VERSION = "story-auto-flow-terminal-classifier/1.1.0"
_REQUIRED_TERMINAL_SIGNALS = frozenset({"warning", "refresh", "delete_forever"})
_POLICY_REJECTION_TERMS = (
    "blocked", "rejected", "not allowed", "cannot generate", "can't generate",
    "unable to generate due to",
)
_POLICY_CONTEXT_TERMS = (
    "policy", "safety", "reputation", "current events",
    "chính sách", "an toàn", "danh tiếng", "sự kiện hiện tại",
)
_RATE_LIMIT_SIGNATURES = (
    "rate limit", "rate-limit", "too many requests", "request frequency limit",
    "giới hạn tốc độ", "quá nhiều yêu cầu",
)
_AUTH_SIGNATURES = (
    "authentication required", "login required", "sign in required",
    "session expired", "session has expired", "please sign in to continue",
    "must sign in to continue", "yêu cầu xác thực", "phiên đã hết hạn",
    "cần đăng nhập để tiếp tục",
)
_CREDIT_SIGNATURES = (
    "insufficient credit", "insufficient credits", "not enough credit",
    "not enough credits", "out of credits", "credits exhausted",
    "credit quota exceeded", "credit quota exhausted", "hết tín dụng",
    "không đủ tín dụng",
)


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_message(raw_message: object) -> str:
    return " ".join(str(raw_message or "").casefold().split())


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def classify_message(raw_message: object) -> FailureFamily | None:
    """Return only a deterministic, high-confidence message family candidate."""
    normalized = _normalized_message(raw_message)
    if not normalized:
        return None
    if _contains_any(normalized, _RATE_LIMIT_SIGNATURES):
        return FailureFamily.PROVIDER_RATE_LIMIT
    if (_contains_any(normalized, _POLICY_REJECTION_TERMS)
            and _contains_any(normalized, _POLICY_CONTEXT_TERMS)):
        return FailureFamily.PROVIDER_POLICY_BLOCK
    if _contains_any(normalized, _AUTH_SIGNATURES):
        return FailureFamily.PROVIDER_AUTH_BLOCK
    if _contains_any(normalized, _CREDIT_SIGNATURES):
        return FailureFamily.PROVIDER_CREDIT_BLOCK
    return None


def terminal_structural_signals(record: dict[str, Any]) -> list[str]:
    """Project trusted Flow tile structure without treating text as authority."""
    signals = record.get("terminal_structural_signals")
    if not isinstance(signals, list):
        return []
    return sorted({str(signal).strip() for signal in signals if str(signal).strip()})


def terminal_observation_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Return the exact bounded terminal projection stored inside a raw poll."""
    raw_signals = record.get("terminal_structural_signals")
    return {
        "card_id": record.get("card_id") if isinstance(record.get("card_id"), str) else None,
        "provider_job_id": (
            record.get("provider_job_id")
            if isinstance(record.get("provider_job_id"), str) and record.get("provider_job_id")
            else None
        ),
        "state": record.get("state"),
        "failure_class": record.get("failure_class"),
        "terminal_structural_signals": list(raw_signals) if isinstance(raw_signals, list) else [],
        "raw_message": str(record.get("raw_message") or ""),
        "locale": record.get("locale"),
    }


def has_trusted_terminal_structure(record: dict[str, Any]) -> bool:
    return (
        record.get("state") == "FAILED"
        and record.get("failure_class") == "PROVIDER_VISIBLE_TERMINAL_FAILURE"
        and _REQUIRED_TERMINAL_SIGNALS.issubset(terminal_structural_signals(record))
    )


def _nonempty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _revision_value(value: object) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return _nonempty_string(value)


def _identity_suffix(value: object, prefix: str) -> str | None:
    text = _nonempty_string(value)
    return text.removeprefix(prefix) if text and text.startswith(prefix) else None


def _provider_binding(attempt: dict[str, Any]) -> dict[str, Any]:
    binding = attempt.get("provider_poll_authoritative_binding")
    return binding if isinstance(binding, dict) else {}


def _direct_card_ids(attempt: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    attributed = attempt.get("attributed_provider_identity")
    if isinstance(attributed, dict):
        card_id = _nonempty_string(attributed.get("card_id"))
        identity_card = _identity_suffix(attributed.get("identity"), "card:")
        if card_id:
            values.add(card_id)
        if identity_card:
            values.add(identity_card)
    lineage_card = _nonempty_string(attempt.get("provider_lineage_card_id"))
    if lineage_card:
        values.add(lineage_card)
    return values


def _bound_card_ids(attempt: dict[str, Any]) -> set[str]:
    values = _direct_card_ids(attempt)
    binding_card = _identity_suffix(
        _provider_binding(attempt).get("durable_identity_used"), "card:",
    )
    if binding_card:
        values.add(binding_card)
    return values


def _direct_job_ids(attempt: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    top_level = _nonempty_string(attempt.get("provider_job_id"))
    if top_level:
        values.add(top_level)
    attributed = attempt.get("attributed_provider_identity")
    if isinstance(attributed, dict):
        for key in ("provider_job_id", "job_id"):
            job_id = _nonempty_string(attributed.get(key))
            if job_id:
                values.add(job_id)
        identity_job = _identity_suffix(attributed.get("identity"), "job:")
        if identity_job:
            values.add(identity_job)
    dispatch_job = _identity_suffix(attempt.get("durable_dispatch_identity"), "job:")
    if dispatch_job:
        values.add(dispatch_job)
    return values


def _bound_job_ids(attempt: dict[str, Any]) -> set[str]:
    values = _direct_job_ids(attempt)
    binding_job = _identity_suffix(
        _provider_binding(attempt).get("durable_identity_used"), "job:",
    )
    if binding_job:
        values.add(binding_job)
    return values


def _binding_is_verified(binding: dict[str, Any],
                         verified_poll_evidence: dict[str, Any] | None) -> bool:
    binding_sha256 = _nonempty_string(binding.get("binding_sha256"))
    return bool(
        binding_sha256
        and verified_poll_evidence
        and any(
            isinstance(item, dict)
            and item.get("binding_sha256") == binding_sha256
            and item == binding
            for item in verified_poll_evidence.get("decision_bindings", [])
        )
    )


def _binding_proves_job(binding: dict[str, Any], job_id: str,
                        verified_poll_evidence: dict[str, Any] | None) -> bool:
    durable = _nonempty_string(binding.get("durable_identity_used"))
    return bool(
        _binding_is_verified(binding, verified_poll_evidence)
        and binding.get("resulting_dispatch_state") == "CONFIRMED"
        and binding.get("resulting_attribution_state") == "CONFIRMED"
        and durable in {job_id, f"job:{job_id}"}
    )


def _binding_identity_contradicts(attempt: dict[str, Any], card_id: str,
                                  observation_job_id: str | None) -> bool:
    durable = _nonempty_string(_provider_binding(attempt).get("durable_identity_used"))
    if not durable:
        return False
    binding_card = _identity_suffix(durable, "card:")
    if binding_card is not None:
        return binding_card != card_id
    binding_job = _identity_suffix(durable, "job:")
    if binding_job is not None and observation_job_id is not None:
        return binding_job != observation_job_id
    if (observation_job_id and not durable.startswith(("card:", "asset:"))):
        return durable != observation_job_id
    known_jobs = _bound_job_ids(attempt)
    return bool(observation_job_id and durable in known_jobs and durable != observation_job_id)


def _exact_attribution(attempt: dict[str, Any], observation: dict[str, Any],
                       verified_poll_evidence: dict[str, Any] | None) -> bool:
    card_id = _nonempty_string(observation.get("card_id"))
    card_ids = _bound_card_ids(attempt)
    direct_card_ids = _direct_card_ids(attempt)
    direct_job_ids = _direct_job_ids(attempt)
    observation_job_id = _nonempty_string(observation.get("provider_job_id"))
    binding = _provider_binding(attempt)
    if not card_id or len(card_ids) != 1 or card_id not in card_ids:
        return False
    if direct_card_ids:
        if len(direct_card_ids) != 1 or card_id not in direct_card_ids:
            return False
    elif not (
        _binding_is_verified(binding, verified_poll_evidence)
        and binding.get("durable_identity_used") == f"card:{card_id}"
    ):
        return False
    if len(direct_job_ids) > 1:
        return False
    if _binding_identity_contradicts(attempt, card_id, observation_job_id):
        return False

    if observation_job_id is not None and direct_job_ids:
        if observation_job_id not in direct_job_ids:
            return False
    elif observation_job_id is not None:
        if not _binding_proves_job(binding, observation_job_id, verified_poll_evidence):
            return False
    elif direct_job_ids:
        only_job_id = next(iter(direct_job_ids))
        if not _binding_proves_job(binding, only_job_id, verified_poll_evidence):
            return False

    if attempt.get("attribution_state") == "CONFIRMED":
        return True
    return bool(
        _binding_is_verified(binding, verified_poll_evidence)
        and binding.get("resulting_dispatch_state") == "CONFIRMED"
        and binding.get("resulting_attribution_state") == "CONFIRMED"
    )


def _attempt_evidence_consistent(attempt: dict[str, Any]) -> bool:
    if len(_bound_card_ids(attempt)) > 1 or len(_bound_job_ids(attempt)) > 1:
        return False
    state = attempt.get("provider_execution_state")
    binding = _provider_binding(attempt)
    confirmed_provider_facts = (
        attempt.get("dispatch_confirmed") is True
        or attempt.get("dispatch_confirmation_state") == "CONFIRMED"
        or attempt.get("attribution_state") == "CONFIRMED"
        or bool(_bound_card_ids(attempt))
        or bool(_bound_job_ids(attempt))
        or binding.get("resulting_dispatch_state") == "CONFIRMED"
        or binding.get("resulting_attribution_state") == "CONFIRMED"
    )
    if state in {None, "NOT_STARTED"} and confirmed_provider_facts:
        return False
    if (attempt.get("dispatch_confirmed") is False
            and attempt.get("dispatch_confirmation_state") == "CONFIRMED"):
        return False
    return True


def _provider_state_allows_terminal(attempt: dict[str, Any]) -> bool:
    return attempt.get("provider_execution_state") not in {None, "NOT_STARTED"}


def _connection_provenance(attempt: dict[str, Any], *,
                           flow_project_identity: str | None,
                           flow_connection_revision: str | int | None) -> tuple[
                               dict[str, str | int | None], bool,
                           ]:
    connection = attempt.get("flow_connection")
    if not isinstance(connection, dict):
        return {
            "flow_connection_id": None,
            "flow_connection_revision": None,
            "flow_project_identity": None,
        }, False

    connection_ids = {
        value for value in (
            _nonempty_string(connection.get("flow_connection_id")),
            _nonempty_string(connection.get("connection_id")),
        ) if value
    }
    revisions = {
        value for value in (
            _revision_value(connection.get("connection_revision")),
            _revision_value(connection.get("flow_connection_revision")),
        ) if value
    }
    projects = {
        value for value in (
            _nonempty_string(connection.get("flow_project_identity")),
            _nonempty_string(connection.get("project_identity")),
        ) if value
    }
    values = {
        "flow_connection_id": next(iter(connection_ids)) if len(connection_ids) == 1 else None,
        "flow_connection_revision": next(iter(revisions)) if len(revisions) == 1 else None,
        "flow_project_identity": next(iter(projects)) if len(projects) == 1 else None,
    }
    complete = all(values.values())
    overrides_match = (
        (flow_project_identity is None or flow_project_identity == values["flow_project_identity"])
        and (
            flow_connection_revision is None
            or flow_connection_revision == values["flow_connection_revision"]
        )
    )
    return values, bool(complete and overrides_match)


def _verified_terminal_source(provider_poll_evidence: dict[str, Any] | None,
                              observation: dict[str, Any], *,
                              source_poll_sequence: int | None,
                              source_observation_sha256: str | None) -> tuple[
                                  dict[str, Any] | None,
                                  str | None,
                                  dict[str, Any] | None,
                              ]:
    if not isinstance(provider_poll_evidence, dict):
        return None, None, None
    try:
        # Lazy import avoids the service/live module dependency cycle.
        from .live import ProviderPollEvidenceTimeline
        verified = ProviderPollEvidenceTimeline.verify_snapshot(provider_poll_evidence)
    except Exception:
        return None, None, None
    if verified.get("evidence_complete") is not True:
        return None, None, None
    head = _nonempty_string(verified.get("evidence_head_sha256"))
    if not head:
        return None, None, None

    hinted = source_poll_sequence is not None or source_observation_sha256 is not None
    if hinted and (
        not isinstance(source_poll_sequence, int)
        or not _nonempty_string(source_observation_sha256)
    ):
        return None, None, None

    projection = terminal_observation_projection(observation)
    matches = []
    for source in verified.get("observations", []):
        if hinted and (
            source.get("poll_sequence") != source_poll_sequence
            or source.get("observation_sha256") != source_observation_sha256
        ):
            continue
        terminal_observations = source.get("terminal_observations")
        if not isinstance(terminal_observations, list):
            continue
        if any(
            isinstance(item, dict)
            and terminal_observation_projection(item) == projection
            for item in terminal_observations
        ):
            matches.append(source)
    if not matches:
        return None, None, None
    source = matches[-1]
    return source, head, verified


def _dispatch_certainty(attempt: dict[str, Any], *, consistent: bool) -> str:
    if not consistent:
        return "DISPATCH_UNCERTAIN"
    if attempt.get("provider_execution_state") in {None, "NOT_STARTED"}:
        return "NOT_DISPATCHED"
    if (
        attempt.get("dispatch_confirmed") is True
        or attempt.get("dispatch_confirmation_state") == "CONFIRMED"
    ):
        return "DISPATCH_CONFIRMED"
    return "DISPATCH_UNCERTAIN"


def build_terminal_evidence(*, request_id: str, attempt: dict[str, Any],
                            observation: dict[str, Any], observed_at: str,
                            provider_poll_evidence: dict[str, Any] | None = None,
                            source_poll_sequence: int | None = None,
                            source_observation_sha256: str | None = None,
                            flow_project_identity: str | None = None,
                            flow_connection_revision: str | int | None = None) -> dict[str, Any]:
    """Bind one visible terminal observation to verified durable poll evidence."""
    terminal_projection = terminal_observation_projection(observation)
    source, evidence_head, verified_poll_evidence = _verified_terminal_source(
        provider_poll_evidence,
        terminal_projection,
        source_poll_sequence=source_poll_sequence,
        source_observation_sha256=source_observation_sha256,
    )
    source_verified = source is not None
    structural_terminal = has_trusted_terminal_structure(terminal_projection)
    candidate = classify_message(terminal_projection.get("raw_message"))
    attempt_consistent = _attempt_evidence_consistent(attempt)
    provider_state_allows_terminal = _provider_state_allows_terminal(attempt)
    provenance, connection_confirmed = _connection_provenance(
        attempt,
        flow_project_identity=flow_project_identity,
        flow_connection_revision=flow_connection_revision,
    )
    exact_attribution = _exact_attribution(
        attempt, terminal_projection, verified_poll_evidence,
    )
    authoritative = bool(
        source_verified
        and structural_terminal
        and exact_attribution
        and attempt_consistent
        and provider_state_allows_terminal
        and connection_confirmed
    )
    family = candidate if authoritative and candidate is not None else (
        FailureFamily.PROVIDER_TERMINAL_UNKNOWN if authoritative else None
    )

    terminal_sha256 = _json_sha256(terminal_projection)
    canonical_source_identity = (
        _json_sha256({
            "source_observation_sha256": source["observation_sha256"],
            "terminal_observation_sha256": terminal_sha256,
        })
        if source_verified else None
    )
    evidence = {
        "schema_version": "story-auto-flow-terminal-evidence/1.1.0",
        "provider": "google_flow",
        "request_id": request_id,
        "attempt": attempt.get("attempt"),
        **provenance,
        "provider_card_id": terminal_projection.get("card_id"),
        "provider_job_id": terminal_projection.get("provider_job_id"),
        "observed_at": observed_at,
        "observed_provider_state": terminal_projection.get("state"),
        "terminal_structural_signals": terminal_structural_signals(terminal_projection),
        "terminal_structural_evidence": structural_terminal,
        "terminal_observation": terminal_projection,
        "terminal_observation_sha256": terminal_sha256,
        "source_poll_sequence": source.get("poll_sequence") if source_verified else None,
        "source_observation_sha256": (
            source.get("observation_sha256") if source_verified else None
        ),
        "provider_poll_evidence_head_sha256": evidence_head if source_verified else None,
        "source_poll_verified": source_verified,
        "canonical_source_identity_sha256": canonical_source_identity,
        "raw_provider_message": terminal_projection["raw_message"],
        "observed_locale": terminal_projection.get("locale"),
        "classification_candidate": candidate.value if candidate is not None else None,
        "failure_family": family.value if family is not None else None,
        "classifier_version": TERMINAL_CLASSIFIER_VERSION,
        "exact_attribution_confirmed": exact_attribution,
        "attempt_evidence_consistent": attempt_consistent,
        "connection_provenance_confirmed": connection_confirmed,
        "authoritative": authoritative,
        "dispatch_certainty": _dispatch_certainty(attempt, consistent=attempt_consistent),
        "attribution_evidence": {
            "attribution_state": attempt.get("attribution_state"),
            "bound_card_ids": sorted(_bound_card_ids(attempt)),
            "bound_provider_job_ids": sorted(_bound_job_ids(attempt)),
            "provider_poll_authoritative_binding_sha256": (
                _provider_binding(attempt).get("binding_sha256")
            ),
        },
    }
    digest_fields = {
        key: value for key, value in evidence.items() if key != "evidence_digest_sha256"
    }
    evidence["evidence_digest_sha256"] = _json_sha256(digest_fields)
    return evidence
