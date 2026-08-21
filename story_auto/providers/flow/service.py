"""Append-only Flow generation orchestration with provider-independent request ordering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import shutil
import uuid

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.resources import ensure_free_space
from story_auto.core.visual import MediaQualityError, validate_production_qc
from .postprocess import (
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    FlowImagePostprocessError,
    process_flow_image,
    profile_evidence,
)
from .validation import AssetValidationError, validate_image, validate_video
from .session import FlowSessionError

MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
FINAL = {"SUCCEEDED", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED"}
UNRESOLVED_FLOW_FAILURES = {
    "FLOW_TIMEOUT",
    "FLOW_RESULT_AMBIGUOUS",
    "FLOW_DISPATCH_UNCERTAIN",
    "FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED",
    "FLOW_POLL_EVIDENCE_INVALID",
    "OUTPUT_ATTRIBUTION_UNCERTAIN",
    "OUTPUT_ATTRIBUTION_AMBIGUOUS",
}
UNRESOLVED_FLOW_STATES = {"GENERATING", "AMBIGUOUS"}
SUPERSEDED_AMBIGUOUS_STATUS = "SUPERSEDED_AMBIGUOUS"
ABANDONED_UNRESOLVED_STATUS = "ABANDONED_UNRESOLVED"
LEGACY_EVIDENCE_GAP_REASON = "LEGACY_BASELINE_IDENTITIES_UNAVAILABLE"
# This is a deliberately narrow, immutable classification of the one preserved
# pre-Goal-17 Trial A epoch whose provider baseline was never captured.  It is
# not inferred from timestamps, gallery order, or an error string.  New
# requests, including any that reproduce the old error shape, are excluded.
LEGACY_EPOCH_CLASSIFICATIONS = {
    ("prj_4f895eb1436c42c4ba5b908381b14fd1", "req_28728acbcab5522b8685"): {
        "kind": "PRE_GOAL17_FLOW_BASELINE_EVIDENCE_GAP",
        "authority": "OPERATIONS.md#preserved-trial-a-resume-gate",
    },
    ("prj_4f895eb1436c42c4ba5b908381b14fd1", "req_6b755dde5a6e7b5c3295"): {
        "kind": "PRE_GOAL17_FLOW_BASELINE_EVIDENCE_GAP",
        "authority": "OPERATIONS.md#preserved-trial-a-resume-gate",
    },
}
SUPERSESSION_TRANSACTION_SCHEMA = "story-auto-legacy-supersession-transaction/1.0.0"
UNRESOLVED_REPLAY_TRANSACTION_SCHEMA = "story-auto-unresolved-replay-transaction/1.0.0"
UNRESOLVED_REPLAY_GENESIS_SCHEMA = "story-auto-unresolved-replay-genesis/1.0.0"
QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA = "story-auto-qc-rejected-asset-replacement-transaction/1.0.0"
QC_REJECTED_ASSET_REPLACED_STATUS = "QC_REJECTED_ASSET_REPLACED"
QC_REJECTED_ASSET_REPLACEMENT_REASON = "QC_REJECTED_ASSET_REPLACEMENT"
CANONICAL_REPLACEMENT_PARENT_STATUSES = {
    SUPERSEDED_AMBIGUOUS_STATUS,
    ABANDONED_UNRESOLVED_STATUS,
    QC_REJECTED_ASSET_REPLACED_STATUS,
}
SUPERSESSION_TARGET_PATHS = {
    "media_plan": "output/media_plan.json",
    "generation_requests": "output/generation_requests.json",
    "generation_manifest": "output/generation_manifest.json",
}
REQUIRED_SUPERSESSION_TARGETS = {"generation_requests", "generation_manifest"}
LOCAL_IMAGE_FAILURES = {
    "FLOW_IMAGE_POSTPROCESS_FAILED",
    "FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID",
    "FLOW_IMAGE_POSTPROCESS_UNSUPPORTED_GEOMETRY",
    "FLOW_IMAGE_POSTPROCESS_DIMENSIONS_CHANGED",
    "FLOW_IMAGE_POSTPROCESS_OUTPUT_CONFLICT",
    "FLOW_IMAGE_DERIVATIVE_INVALID",
}

class FlowError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = ""):
        self.failure_class = failure_class; super().__init__(failure_class + (f": {detail}" if detail else ""))

def _now(): return datetime.now(timezone.utc).isoformat()


def _record_attempt_provider_state(attempt: dict, generator: Any) -> None:
    settings = getattr(generator, "last_settings", None)
    attempt["provider_settings"] = settings
    if not isinstance(settings, dict): return
    activation = settings.get("activation", {}) if isinstance(settings.get("activation"), dict) else {}
    composer = settings.get("composer_ready_state") if isinstance(settings.get("composer_ready_state"), dict) else None
    attempt.update({
        "activation_time": activation.get("activation_time"),
        "activation_timestamp": activation.get("activation_time"),
        "interaction_method": activation.get("interaction_method"),
        "interaction_version": activation.get("interaction_version"),
        "composer_ready_state": composer,
        "dispatch_confirmation_state": settings.get("dispatch_confirmation_state"),
        "dispatch_confirmation_signal": settings.get("dispatch_confirmation_signal"),
        "dispatch_signal_state": settings.get("dispatch_signal_state"),
        "durable_dispatch_identity": settings.get("durable_dispatch_identity"),
        "dispatch_evidence_poll_sequence": settings.get("dispatch_evidence_poll_sequence"),
        "provider_job_id": settings.get("provider_job_id"),
        "provider_lineage_card_id": settings.get("provider_lineage_card_id"),
        "pre_dispatch_baseline_fingerprint": settings.get("pre_dispatch_baseline_fingerprint"),
        "baseline_provider_identities": settings.get("baseline_provider_identities"),
        "attribution_state": settings.get("attribution_state"),
        "attribution_method": settings.get("attribution_method"),
        "attribution_method_version": settings.get("attribution_method_version"),
        "attributed_provider_identity": settings.get("attributed_provider_identity"),
        "candidate_delta_count": settings.get("candidate_delta_count"),
        "candidate_identities": settings.get("candidate_identities"),
        "candidate_observation_state": settings.get("candidate_observation_state"),
        "candidate_acquisition_state": settings.get("candidate_acquisition_state"),
        "durable_candidate_identity": settings.get("durable_candidate_identity"),
        "candidate_observed_poll_sequence": settings.get("candidate_observed_poll_sequence"),
        "attribution_confirmation_timestamp": settings.get("attribution_confirmation_timestamp"),
        "poll_evidence_version": settings.get("poll_evidence_version"),
        "provider_surface_extractor_version": settings.get("provider_surface_extractor_version"),
        "provider_poll_evidence": settings.get("provider_poll_evidence"),
        "provider_poll_decision_bindings": settings.get("provider_poll_decision_bindings"),
        "provider_poll_authoritative_binding": settings.get("provider_poll_authoritative_binding"),
        "provider_poll_max_observations": settings.get("provider_poll_max_observations"),
        "provider_poll_max_identities_per_observation": settings.get("provider_poll_max_identities_per_observation"),
        "provider_poll_max_candidates_per_observation": settings.get("provider_poll_max_candidates_per_observation"),
        "provider_poll_max_quarantined_per_observation": settings.get("provider_poll_max_quarantined_per_observation"),
        "provider_poll_max_serialized_bytes": settings.get("provider_poll_max_serialized_bytes"),
        "provider_poll_evidence_complete": settings.get("provider_poll_evidence_complete"),
        "provider_poll_observation_count": settings.get("provider_poll_observation_count"),
        "provider_poll_timeline_sha256": settings.get("provider_poll_timeline_sha256"),
        "provider_poll_timeline_complete": settings.get("provider_poll_timeline_complete"),
        "provider_poll_terminal_state": settings.get("provider_poll_terminal_state"),
        "provider_poll_timeline": settings.get("provider_poll_timeline"),
    })
def _manifest(paths, project_id):
    path = paths.artifact_path("output/generation_manifest.json")
    if not path.exists(): return path, {"schema_version": MANIFEST_VERSION, "project_id": project_id, "requests": []}
    try:
        data = read_json(path)
        if data.get("schema_version") != MANIFEST_VERSION or data.get("project_id") != project_id or not isinstance(data.get("requests"), list): raise ValueError()
        return path, data
    except Exception as error: raise FlowError("GENERATION_MANIFEST_INVALID") from error

def _entry(manifest, request):
    found = next((x for x in manifest["requests"] if x["request_id"] == request["request_id"]), None)
    if found is None:
        found = {"request_id":request["request_id"], "request_identity_sha256":request["fingerprint"], "related_identity":request.get("shot_id") or request.get("entity_id"), "media_type":request["media_type"], "provider":"google_flow", "prompt_sha256":request["fingerprint"], "reference_asset_hashes":[], "attempts":[], "status":"PENDING", "created_at":_now()}; manifest["requests"].append(found)
    elif found.get("request_identity_sha256") != request["fingerprint"]: return None
    return found

def _valid_selected(paths, entry):
    selected = entry.get("selected_asset")
    if not isinstance(selected, dict) or not isinstance(selected.get("path"), str): return False
    path = paths.artifact_path(selected["path"])
    try:
        metadata = validate_image(path) if entry["media_type"] == "IMAGE" else validate_video(path)
        return metadata["sha256"] == selected.get("sha256")
    except Exception: return False


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _historical_replacement_parent(entry: dict | None) -> bool:
    """A child absent from the live queue must itself prove a canonical edge."""
    return isinstance(entry, dict) and entry.get("status") in CANONICAL_REPLACEMENT_PARENT_STATUSES


def _manifest_identity_matches_request(entry: dict | None, request: dict | None) -> bool:
    """Bind a historical manifest entry to its committed request identity."""
    if not isinstance(entry, dict) or not isinstance(request, dict):
        return False
    prompt = request.get("prompt")
    return (
        entry.get("request_id") == request.get("request_id")
        and entry.get("request_identity_sha256") == request.get("fingerprint")
        and isinstance(prompt, str)
        and entry.get("prompt_sha256") == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        and entry.get("related_identity") == (request.get("shot_id") or request.get("entity_id"))
        and entry.get("media_type") == request.get("media_type")
        and entry.get("provider") == request.get("provider")
    )


def _legacy_epoch_classification(project_id: str, request_id: str) -> dict | None:
    value = LEGACY_EPOCH_CLASSIFICATIONS.get((project_id, request_id))
    return dict(value) if isinstance(value, dict) else None


def _legacy_ambiguous_supersession_eligible(project_id: str, request_id: str, entry: dict | None) -> dict | None:
    """Allow a new epoch only for the audited legacy evidence-gap shape.

    A normal modern AMBIGUOUS Flow request remains a hard queue barrier.  This
    exception deliberately requires the exact legacy reconciliation conclusion
    that cannot be repaired by another provider inspection.
    """
    classification = _legacy_epoch_classification(project_id, request_id)
    if classification is None: return None
    if not isinstance(entry, dict): return None
    if entry.get("status") != "AMBIGUOUS" or entry.get("failure_class") != "FLOW_DISPATCH_UNCERTAIN": return None
    if entry.get("selected_asset") is not None: return None
    attempts = entry.get("attempts") if isinstance(entry.get("attempts"), list) else []
    if not attempts: return None
    last = attempts[-1]
    if not isinstance(last, dict) or last.get("failure_class") != "FLOW_DISPATCH_UNCERTAIN": return None
    if last.get("dispatch_confirmed") is not False or last.get("provider_job_id") is not None: return None
    events = last.get("reconciliation_events") if isinstance(last.get("reconciliation_events"), list) else []
    if not events: return None
    latest = events[-1] if isinstance(events[-1], dict) else {}
    evidence = latest.get("evidence") if isinstance(latest.get("evidence"), dict) else {}
    if latest.get("state") != "REMAINS_AMBIGUOUS" or evidence.get("reason") != LEGACY_EVIDENCE_GAP_REASON:
        return None
    return classification


def _replacement_identity(request: dict, *, nonce: str, epoch: int) -> tuple[str, str]:
    """Derive a fresh identity while retaining the unchanged semantic request."""
    semantic = request.get("fingerprint")
    if not isinstance(semantic, str) or not semantic:
        raise FlowError("LEGACY_SUPERSESSION_INVALID")
    identity_input = {"semantic_fingerprint": semantic, "replacement_epoch": epoch, "epoch_nonce": nonce}
    fingerprint = hashlib.sha256(json.dumps(identity_input, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return "req_" + fingerprint[:20], fingerprint


def _immutable_replay_request_projection(request: dict) -> dict | None:
    """Return only request facts that must remain fixed for a replay epoch."""
    required_strings = ("request_id", "fingerprint", "prompt", "purpose", "media_type", "provider",
                        "replays_unresolved_request_id", "epoch_nonce")
    if not isinstance(request, dict) or any(not isinstance(request.get(key), str) or not request[key] for key in required_strings):
        return None
    if not isinstance(request.get("replay_epoch"), int) or request["replay_epoch"] < 1:
        return None
    for key in ("depends_on", "reference_asset_ids"):
        if not isinstance(request.get(key), list) or any(not isinstance(value, str) or not value for value in request[key]):
            return None
    return {
        "request_id": request["request_id"],
        "request_identity_sha256": request["fingerprint"],
        "prompt_sha256": hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest(),
        "purpose": request["purpose"],
        "entity_id": request.get("entity_id"),
        "shot_id": request.get("shot_id"),
        "media_type": request["media_type"],
        "provider": request["provider"],
        "output_count": request.get("output_count", 1),
        "execution_tier": request.get("execution_tier"),
        "depends_on": list(request["depends_on"]),
        "reference_asset_ids": list(request["reference_asset_ids"]),
        "replays_unresolved_request_id": request["replays_unresolved_request_id"],
        "replay_epoch": request["replay_epoch"],
        "epoch_nonce": request["epoch_nonce"],
    }


def _replay_genesis_projection(*, replacement: dict, queue_position: int, event: dict,
                               transaction_id: str) -> dict | None:
    request = _immutable_replay_request_projection(replacement)
    if request is None or not isinstance(queue_position, int) or queue_position < 0:
        return None
    acknowledgement_keys = (
        "previous_dispatch_or_cost_may_have_occurred_acknowledged",
        "previous_output_ownership_unresolved_acknowledged",
        "replacement_may_consume_provider_credit_acknowledged",
    )
    if (not isinstance(transaction_id, str) or not transaction_id
            or not isinstance(event.get("operator_reason"), str) or not event["operator_reason"].strip()
            or event.get("old_request_id") != request["replays_unresolved_request_id"]
            or event.get("replacement_request_id") != request["request_id"]
            or event.get("historical_provider_dispatch") not in {"CONFIRMED", "UNKNOWN"}
            or event.get("historical_attribution") != "UNRESOLVED"
            or not isinstance(event.get("attempts_sha256"), str)
            or not all(event.get(key) is True for key in acknowledgement_keys)):
        return None
    return {
        "schema_version": UNRESOLVED_REPLAY_GENESIS_SCHEMA,
        "old_request_id": event["old_request_id"],
        "replacement_request_id": request["request_id"],
        "replay_epoch": request["replay_epoch"],
        "epoch_nonce": request["epoch_nonce"],
        "operator_reason": event["operator_reason"],
        "acknowledgements": {key: True for key in acknowledgement_keys},
        "old_historical_truth": {
            "provider_dispatch": event["historical_provider_dispatch"],
            "attribution": event["historical_attribution"],
            "attempts_sha256": event["attempts_sha256"],
        },
        "replacement_request": request,
        "queue_position": queue_position,
        "creation_transaction_id": transaction_id,
    }


def _proven_safe_pre_dispatch_attempt(attempt: dict) -> bool:
    """Retry only after persisted evidence proves that input never dispatched."""
    if not isinstance(attempt, dict):
        return False
    if attempt.get("dispatch_confirmed") is not False:
        return False
    if attempt.get("provider_job_id") is not None or attempt.get("durable_dispatch_identity") is not None:
        return False
    if attempt.get("provider_lineage_card_id") is not None or attempt.get("attributed_provider_identity") is not None:
        return False
    if attempt.get("attribution_state") != "NOT_ATTEMPTED":
        return False
    if attempt.get("dispatch_confirmation_state") != "PRE_DISPATCH_FAILURE":
        return False
    settings = attempt.get("provider_settings")
    activation = settings.get("activation") if isinstance(settings, dict) and isinstance(settings.get("activation"), dict) else None
    return isinstance(activation, dict) and activation.get("input_dispatched") is False


def _verified_historical_no_dispatch_attempt(attempt: dict) -> bool:
    """Recognize only hash-bound, pre-dispatch poll evidence from the old shape.

    The historical form deliberately has no ``activation`` object.  A nested
    ``input_dispatched=false`` is insufficient by itself: every retained poll
    must be integrity-verified, pre-dispatch, and free of any dispatch or
    attribution signal.  This reader projects the old fact into the same
    semantic proof as the current activation record; it never rewrites runtime
    evidence.
    """
    if not isinstance(attempt, dict):
        return False
    if attempt.get("dispatch_confirmed") is not False:
        return False
    if attempt.get("provider_job_id") is not None or attempt.get("durable_dispatch_identity") is not None:
        return False
    if attempt.get("provider_lineage_card_id") is not None or attempt.get("attributed_provider_identity") is not None:
        return False
    if attempt.get("attribution_state") != "NOT_ATTEMPTED":
        return False
    if attempt.get("dispatch_confirmation_state") != "PRE_DISPATCH_FAILURE":
        return False
    settings = attempt.get("provider_settings")
    if not isinstance(settings, dict) or isinstance(settings.get("activation"), dict):
        return False
    snapshot = settings.get("provider_poll_evidence")
    if not isinstance(snapshot, dict) or attempt.get("poll_evidence_version") != snapshot.get("schema_version"):
        return False
    try:
        # Imported lazily because live.py uses FlowError from this module.
        from .live import ProviderPollEvidenceTimeline
        verified = ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
    except (FlowError, ValueError, TypeError):
        return False
    observations = verified.get("observations")
    if (verified.get("complete") is not True or verified.get("evidence_complete") is not True
            or verified.get("terminal_state") != "NOT_ATTEMPTED"
            or verified.get("decision_binding_count") != 0
            or not isinstance(observations, list) or not observations):
        return False
    for observation in observations:
        if not isinstance(observation, dict):
            return False
        if observation.get("phase") not in {"PRE_DISPATCH_DISCOVERY", "PRE_DISPATCH_BASELINE"}:
            return False
        if observation.get("input_dispatched") is not False:
            return False
        if observation.get("dispatch_evidence_state") != "NOT_CONFIRMED":
            return False
        if observation.get("dispatch_signal_state") != "NONE":
            return False
        if observation.get("attribution_evidence_state") != "NOT_ATTEMPTED":
            return False
        if (observation.get("provider_job_id") is not None
                or observation.get("durable_dispatch_identity") is not None
                or observation.get("lineage_card_id") is not None
                or observation.get("attributed_provider_identity") is not None):
            return False
    return True


def canonical_no_dispatch_proof(attempt: dict) -> bool:
    """Return positive proof that provider input never crossed Generate.

    Current-schema attempts use ``activation.input_dispatched=false``.  Older
    retained attempts may instead use a verified pre-dispatch poll timeline.
    Both branches prove the identical safety invariant and both fail closed.
    """
    return _proven_safe_pre_dispatch_attempt(attempt) or _verified_historical_no_dispatch_attempt(attempt)


def _produce_crash_before_provider_setup_proof(attempt: dict) -> bool:
    """Persist the current-schema proof only before the provider boundary.

    ``provider_execution_state`` is synchronously persisted as
    ``NOT_STARTED`` with the submitted attempt, then changed and persisted
    immediately before ``executor.run``.  A restart can therefore turn the
    former state into the normal current-schema proof, but never infer it after
    the provider boundary may have been entered.
    """
    if not isinstance(attempt, dict):
        return False
    if (attempt.get("status") != "SUBMITTED"
            or attempt.get("dispatch_confirmed") is not False
            or attempt.get("provider_execution_state") != "NOT_STARTED"
            or attempt.get("provider_boundary_entered_at") is not None
            or attempt.get("provider_settings") is not None):
        return False
    if any(attempt.get(key) is not None for key in (
        "provider_job_id", "durable_dispatch_identity", "provider_lineage_card_id",
        "attributed_provider_identity",
    )):
        return False
    if attempt.get("attribution_state") not in {None, "NOT_ATTEMPTED"}:
        return False
    attempt.update({
        "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
        "attribution_state": "NOT_ATTEMPTED",
        "provider_settings": {"activation": {
            "input_dispatched": False,
            "proof": "PROCESS_INTERRUPTED_BEFORE_PROVIDER_SETUP",
        }},
    })
    return canonical_no_dispatch_proof(attempt)


def _provider_generation_retry_authorized(entry: dict | None) -> bool:
    """Authorize Generate only from persisted positive no-dispatch evidence.

    A request with no attempts is a first submission.  Once an attempt exists,
    lifecycle status and failure labels are diagnostic state only; the latest
    attempt itself must prove that provider input never crossed dispatch.
    Local-only recovery paths deliberately do not use this gate.
    """
    if not isinstance(entry, dict):
        return False
    attempts = entry.get("attempts")
    if not isinstance(attempts, list) or any(not isinstance(item, dict) for item in attempts):
        return False
    return not attempts or canonical_no_dispatch_proof(attempts[-1])


def _migrate_request_references(value: Any, old_request_id: str, replacement_request_id: str) -> bool:
    """Migrate only declared dependency/selection references, never free text."""
    changed = False
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "selected_request_id" and item == old_request_id:
                value[key] = replacement_request_id; changed = True
            elif key in {"depends_on", "reference_asset_ids"} and isinstance(item, list):
                rewritten = [replacement_request_id if candidate == old_request_id else candidate for candidate in item]
                if rewritten != item: value[key] = rewritten; changed = True
            elif isinstance(item, (dict, list)):
                changed = _migrate_request_references(item, old_request_id, replacement_request_id) or changed
    elif isinstance(value, list):
        for item in value: changed = _migrate_request_references(item, old_request_id, replacement_request_id) or changed
    return changed


def _supersession_directory(paths) -> Path:
    return paths.artifact_path("output/legacy_supersession_transactions")


def _unresolved_replay_directory(paths) -> Path:
    return paths.artifact_path("output/unresolved_replay_transactions")


def _transaction_error(schema_version: str) -> str:
    if schema_version == SUPERSESSION_TRANSACTION_SCHEMA:
        return "LEGACY_SUPERSESSION_RECOVERY_INVALID"
    if schema_version == UNRESOLVED_REPLAY_TRANSACTION_SCHEMA:
        return "UNRESOLVED_REPLAY_RECOVERY_INVALID"
    if schema_version == QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA:
        return "QC_REJECTED_ASSET_REPLACEMENT_RECOVERY_INVALID"
    return "FLOW_REPLACEMENT_RECOVERY_INVALID"


def _transaction_spec(paths, schema_version: str) -> tuple[Path, str]:
    if schema_version == SUPERSESSION_TRANSACTION_SCHEMA:
        return _supersession_directory(paths), "LEGACY_SUPERSESSION_RECOVERY_INVALID"
    if schema_version == UNRESOLVED_REPLAY_TRANSACTION_SCHEMA:
        return _unresolved_replay_directory(paths), "UNRESOLVED_REPLAY_RECOVERY_INVALID"
    if schema_version == QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA:
        return paths.artifact_path("output/qc_rejected_asset_replacement_transactions"), "QC_REJECTED_ASSET_REPLACEMENT_RECOVERY_INVALID"
    raise FlowError("FLOW_REPLACEMENT_RECOVERY_INVALID")


def _transaction_paths(paths, transaction_id: str, *,
                       schema_version: str = SUPERSESSION_TRANSACTION_SCHEMA) -> tuple[Path, Path]:
    directory, _ = _transaction_spec(paths, schema_version)
    return directory / f"{transaction_id}.prepared.json", directory / f"{transaction_id}.committed.json"


def _prepared_transactions(paths, project_id: str, *,
                           schema_version: str = SUPERSESSION_TRANSACTION_SCHEMA) -> list[tuple[Path, dict]]:
    directory, error_code = _transaction_spec(paths, schema_version)
    if not directory.is_dir(): return []
    values = []
    for path in sorted(directory.glob("*.prepared.json")):
        try: value = read_json(path)
        except Exception as error: raise FlowError(error_code) from error
        if (not isinstance(value, dict)
                or value.get("schema_version") != schema_version
                or value.get("state") != "PREPARED"):
            raise FlowError(error_code)
        if value.get("project_id") != project_id:
            raise FlowError(error_code)
        transaction_id = value.get("transaction_id")
        old_request_id = value.get("old_request_id")
        replacement_request_id = value.get("replacement_request_id")
        if (not isinstance(transaction_id, str) or not transaction_id
                or path.name != f"{transaction_id}.prepared.json"
                or not isinstance(old_request_id, str) or not old_request_id
                or not isinstance(replacement_request_id, str) or not replacement_request_id
                or old_request_id == replacement_request_id):
            raise FlowError(error_code)
        _validate_transaction_targets(value, schema_version=schema_version)
        values.append((path, value))
    return values


def _validate_transaction_targets(transaction: dict, *, schema_version: str | None = None) -> None:
    schema = schema_version or transaction.get("schema_version")
    if schema not in {SUPERSESSION_TRANSACTION_SCHEMA, UNRESOLVED_REPLAY_TRANSACTION_SCHEMA,
                      QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA}:
        raise FlowError("FLOW_REPLACEMENT_RECOVERY_INVALID")
    error_code = _transaction_error(schema)
    targets = transaction.get("targets")
    if not isinstance(targets, dict):
        raise FlowError(error_code)
    names = set(targets)
    if not REQUIRED_SUPERSESSION_TARGETS.issubset(names) or not names.issubset(SUPERSESSION_TARGET_PATHS):
        raise FlowError(error_code)
    for name, value in targets.items():
        if not isinstance(value, dict) or value.get("path") != SUPERSESSION_TARGET_PATHS[name]:
            raise FlowError(error_code)
        if not isinstance(value.get("value"), dict) or value.get("sha256") != _json_sha256(value["value"]):
            raise FlowError(error_code)


def _transaction_target(transaction: dict, name: str, *, schema_version: str | None = None) -> dict | None:
    _validate_transaction_targets(transaction, schema_version=schema_version)
    value = transaction["targets"].get(name)
    if value is None: return None
    return value


def _superseded_entry_valid(paths, project_id: str, entry: dict, requests: list[dict], entries: dict[str, dict]) -> bool:
    if entry.get("status") != SUPERSEDED_AMBIGUOUS_STATUS or entry.get("selected_asset") is not None:
        return False
    request_id = entry.get("request_id")
    canonical_classification = _legacy_epoch_classification(project_id, request_id) if isinstance(request_id, str) else None
    if canonical_classification is None:
        return False
    replacement_id = entry.get("replacement_request_id")
    events = entry.get("supersession_events")
    if not isinstance(replacement_id, str) or not replacement_id or not isinstance(events, list) or not events:
        return False
    event = events[-1] if isinstance(events[-1], dict) else None
    if not isinstance(event, dict) or event.get("event") != SUPERSEDED_AMBIGUOUS_STATUS:
        return False
    if event.get("replacement_request_id") != replacement_id or event.get("prior_dispatch_state") != "UNKNOWN":
        return False
    if event.get("old_request_id") != request_id:
        return False
    if event.get("prior_attribution_state") != "UNRESOLVED" or event.get("historical_dispatch_unknown_acknowledged") is not True:
        return False
    if event.get("legacy_epoch_classification") != canonical_classification: return False
    if event.get("attempts_sha256") != _json_sha256(entry.get("attempts")):
        return False
    if event.get("reconciliation_events_sha256") != _json_sha256(entry.get("reconciliation_events")):
        return False
    replacement_entry = entries.get(replacement_id)
    if not isinstance(replacement_entry, dict) or replacement_entry.get("replaces_request_id") != request_id:
        return False
    resolved_transaction = _supersession_transaction(paths, project_id, request_id, replacement_id)
    if resolved_transaction is None:
        return False
    transaction, _receipt = resolved_transaction
    stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
    stored_manifest = transaction["targets"]["generation_manifest"]["value"].get("requests", [])
    stored_replacement = next((item for item in stored_requests if item.get("request_id") == replacement_id), None)
    stored_old = next((item for item in stored_manifest if item.get("request_id") == request_id), None)
    stored_event = (stored_old.get("supersession_events") or [None])[-1] if isinstance(stored_old, dict) else None
    if not isinstance(stored_replacement, dict) or stored_event != event:
        return False
    # This validates immutable legacy -> replacement evidence only.  The child
    # may itself be a historical replacement whose canonical descendant owns the
    # live queue state.
    return (
        replacement_entry.get("request_id") == replacement_id
        and replacement_entry.get("replaces_request_id") == request_id
        and replacement_entry.get("replacement_epoch") == stored_replacement.get("replacement_epoch")
        and replacement_entry.get("epoch_nonce") == stored_replacement.get("epoch_nonce")
        and replacement_entry.get("request_identity_sha256") == stored_replacement.get("fingerprint")
        and replacement_entry.get("prompt_sha256") == hashlib.sha256(stored_replacement.get("prompt", "").encode("utf-8")).hexdigest()
        and replacement_entry.get("related_identity") == (stored_replacement.get("shot_id") or stored_replacement.get("entity_id"))
        and replacement_entry.get("media_type") == stored_replacement.get("media_type")
        and replacement_entry.get("provider") == stored_replacement.get("provider")
    )


def _first_invalid_superseded(paths, project_id: str, entries: dict[str, dict], requests: list[dict]) -> tuple[dict, dict] | None:
    for entry in entries.values():
        if entry.get("status") == SUPERSEDED_AMBIGUOUS_STATUS and not _superseded_entry_valid(
                paths, project_id, entry, requests, entries):
            return {"request_id": entry.get("request_id")}, entry
    return None


def _abandoned_unresolved_entry_valid(paths, project_id: str, entry: dict, requests: list[dict],
                                      entries: dict[str, dict]) -> bool:
    if entry.get("status") != ABANDONED_UNRESOLVED_STATUS or entry.get("selected_asset") is not None:
        return False
    request_id = entry.get("request_id")
    replacement_id = entry.get("replacement_request_id")
    events = entry.get("unresolved_replay_events")
    if (not isinstance(request_id, str) or not isinstance(replacement_id, str)
            or not isinstance(events, list) or len(events) != 1):
        return False
    event = events[-1] if isinstance(events[-1], dict) else None
    if not isinstance(event, dict) or event.get("event") != ABANDONED_UNRESOLVED_STATUS:
        return False
    if event.get("old_request_id") != request_id or event.get("replacement_request_id") != replacement_id:
        return False
    if event.get("historical_provider_dispatch") not in {"CONFIRMED", "UNKNOWN"}:
        return False
    if event.get("historical_attribution") != "UNRESOLVED":
        return False
    if (entry.get("historical_provider_dispatch") != event.get("historical_provider_dispatch")
            or entry.get("historical_attribution") != "UNRESOLVED"
            or not isinstance(event.get("operator_reason"), str)
            or not event["operator_reason"].strip()):
        return False
    if not all(event.get(key) is True for key in (
        "previous_dispatch_or_cost_may_have_occurred_acknowledged",
        "previous_output_ownership_unresolved_acknowledged",
        "replacement_may_consume_provider_credit_acknowledged",
    )):
        return False
    if event.get("attempts_sha256") != _json_sha256(entry.get("attempts")):
        return False
    replacement_matches = [request for request in requests if request.get("request_id") == replacement_id]
    replacement = replacement_matches[0] if len(replacement_matches) == 1 else None
    replacement_entry = entries.get(replacement_id)
    if (not isinstance(replacement_entry, dict) or replacement_id == request_id
            or len(replacement_matches) > 1):
        return False
    resolved_transaction = _unresolved_replay_transaction(paths, project_id, request_id, replacement_id)
    if resolved_transaction is None:
        return False
    transaction, _receipt = resolved_transaction
    transaction_id = transaction["transaction_id"]
    stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
    stored_manifest = transaction["targets"]["generation_manifest"]["value"].get("requests", [])
    stored_replacement = next((item for item in stored_requests if item.get("request_id") == replacement_id), None)
    stored_old = next((item for item in stored_manifest if item.get("request_id") == request_id), None)
    stored_event = (stored_old.get("unresolved_replay_events") or [None])[-1] if isinstance(stored_old, dict) else None
    if not isinstance(stored_replacement, dict) or not isinstance(stored_event, dict):
        return False
    stored_genesis = stored_event.get("replay_genesis")
    if not isinstance(stored_genesis, dict):
        # Goal 20 transactions predate the explicit projection.  Their committed
        # target is the immutable genesis source; derive the same narrow
        # projection without touching preserved runtime artifacts.
        stored_genesis = _replay_genesis_projection(
            replacement=stored_replacement,
            queue_position=stored_requests.index(stored_replacement),
            event=stored_event,
            transaction_id=transaction_id,
        )
    if not isinstance(stored_genesis, dict):
        return False
    genesis_sha256 = _json_sha256(stored_genesis)
    explicit_genesis = event.get("replay_genesis")
    stored_request = stored_genesis.get("replacement_request") if isinstance(stored_genesis, dict) else None
    if (not isinstance(stored_request, dict)
            or (isinstance(explicit_genesis, dict) and (
                explicit_genesis != stored_genesis or event.get("replay_genesis_sha256") != genesis_sha256))
            or (isinstance(event.get("replay_genesis"), dict) and replacement_entry.get("replay_genesis_sha256") != genesis_sha256)
            or (isinstance(replacement_entry.get("replay_creation_transaction_id"), str)
                and replacement_entry.get("replay_creation_transaction_id") != transaction_id)
            or replacement_entry.get("replays_unresolved_request_id") != request_id
            or replacement_entry.get("replay_epoch") != stored_request.get("replay_epoch")
            or replacement_entry.get("epoch_nonce") != stored_request.get("epoch_nonce")
            or replacement_entry.get("request_identity_sha256") != stored_request.get("request_identity_sha256")
            or replacement_entry.get("prompt_sha256") != stored_request.get("prompt_sha256")
            or replacement_entry.get("related_identity") != (stored_request.get("shot_id") or stored_request.get("entity_id"))
            or replacement_entry.get("media_type") != stored_request.get("media_type")
            or replacement_entry.get("provider") != stored_request.get("provider")):
        return False
    if isinstance(replacement, dict):
        expected = _replay_genesis_projection(
            replacement=replacement,
            queue_position=requests.index(replacement),
            event=event,
            transaction_id=transaction_id,
        )
        if expected != stored_genesis:
            return False
    elif not _historical_replacement_parent(replacement_entry):
        # A missing live child is safe only when it is itself a historical
        # canonical parent. Its outgoing edge is checked independently by the
        # descendant resolver; this incoming edge remains its own transaction
        # proof rather than a claim that the child is still live.
        return False
    if ("replay_genesis_sha256" in transaction
            and transaction.get("replay_genesis_sha256") != genesis_sha256):
        return False
    attempts = replacement_entry.get("attempts")
    if not isinstance(attempts, list) or any(not isinstance(attempt, dict) for attempt in attempts):
        return False
    if not isinstance(replacement, dict):
        return _manifest_identity_matches_request(replacement_entry, stored_replacement)
    if replacement_entry.get("selected_asset") is not None and replacement_entry.get("status") not in {"SUCCEEDED", "QC_PENDING"}:
        return False
    if replacement_entry.get("status") == "PENDING":
        return attempts == []
    if replacement_entry.get("status") == "NOT_DISPATCHED":
        # Replay validity is a semantic no-dispatch decision.  It must accept
        # both the current activation proof and a verified retained timeline,
        # exactly as the retry, queue, and execution gates do.
        return bool(attempts) and attempts[-1].get("status") == "NOT_DISPATCHED" and canonical_no_dispatch_proof(attempts[-1])
    return replacement_entry.get("status") in {"GENERATING", "AMBIGUOUS", "FAILED_RETRYABLE", "SUCCEEDED", "QC_PENDING", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED"}


def _first_invalid_request_replacement(paths, project_id: str, entries: dict[str, dict],
                                       requests: list[dict]) -> tuple[dict, dict] | None:
    invalid = _first_invalid_superseded(paths, project_id, entries, requests)
    if invalid is not None:
        return invalid
    for entry in entries.values():
        if (entry.get("status") == ABANDONED_UNRESOLVED_STATUS
                and not _abandoned_unresolved_entry_valid(paths, project_id, entry, requests, entries)):
            return {"request_id": entry.get("request_id")}, entry
        if (entry.get("status") == QC_REJECTED_ASSET_REPLACED_STATUS
                and not _qc_rejected_asset_replacement_valid(paths, project_id, entry, requests, entries)):
            return {"request_id": entry.get("request_id")}, entry
    return None


def _publish_replacement_transaction(paths, transaction: dict,
                                     *, fault_injector: Callable[[str], None] | None = None) -> None:
    schema_version = transaction.get("schema_version")
    _directory, error_code = _transaction_spec(paths, schema_version)
    transaction_id = transaction.get("transaction_id")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise FlowError(error_code)
    _validate_transaction_targets(transaction, schema_version=schema_version)
    prepared_path, committed_path = _transaction_paths(paths, transaction_id, schema_version=schema_version)
    if not prepared_path.is_file():
        if fault_injector: fault_injector("prepared")
        atomic_write_json(prepared_path, transaction)
    elif read_json(prepared_path) != transaction:
        raise FlowError(error_code)
    for name in ("media_plan", "generation_requests", "generation_manifest"):
        target = _transaction_target(transaction, name, schema_version=schema_version)
        if target is None: continue
        if fault_injector: fault_injector(name)
        atomic_write_json(paths.artifact_path(target["path"]), target["value"])
    receipt = {"schema_version": schema_version, "state": "COMMITTED",
               "transaction_id": transaction_id, "prepared_sha256": _json_sha256(transaction)}
    if not committed_path.is_file():
        if fault_injector: fault_injector("committed")
        atomic_write_json(committed_path, receipt)
    elif read_json(committed_path) != receipt:
        raise FlowError(error_code)


def _publish_supersession_transaction(paths, transaction: dict,
                                      *, fault_injector: Callable[[str], None] | None = None) -> None:
    _publish_replacement_transaction(paths, transaction, fault_injector=fault_injector)


def _publish_unresolved_replay_transaction(paths, transaction: dict,
                                           *, fault_injector: Callable[[str], None] | None = None) -> None:
    _publish_replacement_transaction(paths, transaction, fault_injector=fault_injector)


def _recover_replacement_transactions(paths, project_id: str, *, schema_version: str) -> dict[str, dict]:
    _directory, error_code = _transaction_spec(paths, schema_version)
    recovered: dict[str, dict] = {}
    for _prepared_path, transaction in _prepared_transactions(paths, project_id, schema_version=schema_version):
        transaction_id = transaction.get("transaction_id")
        if not isinstance(transaction_id, str): raise FlowError(error_code)
        _prepared, committed_path = _transaction_paths(paths, transaction_id, schema_version=schema_version)
        if not committed_path.is_file():
            _publish_replacement_transaction(paths, transaction)
        else:
            try:
                receipt = read_json(committed_path)
            except Exception as error:
                raise FlowError(error_code) from error
            if (not isinstance(receipt, dict)
                    or receipt.get("schema_version") != schema_version
                    or receipt.get("state") != "COMMITTED"
                    or receipt.get("transaction_id") != transaction_id
                    or receipt.get("prepared_sha256") != _json_sha256(transaction)):
                raise FlowError(error_code)
        old_request_id = transaction.get("old_request_id")
        replacement_request_id = transaction.get("replacement_request_id")
        if not isinstance(old_request_id, str) or not isinstance(replacement_request_id, str):
            raise FlowError(error_code)
        recovered[old_request_id] = {"replacement_request_id": replacement_request_id,
                                     "transaction_id": transaction_id}
    return recovered


def _recover_pending_supersessions(paths, project_id: str) -> dict[str, dict]:
    return _recover_replacement_transactions(
        paths, project_id, schema_version=SUPERSESSION_TRANSACTION_SCHEMA
    )


def _recover_pending_unresolved_replays(paths, project_id: str) -> dict[str, dict]:
    return _recover_replacement_transactions(
        paths, project_id, schema_version=UNRESOLVED_REPLAY_TRANSACTION_SCHEMA
    )


def _recover_pending_qc_rejected_asset_replacements(paths, project_id: str) -> dict[str, dict]:
    return _recover_replacement_transactions(
        paths, project_id, schema_version=QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA
    )


def _unresolved_replay_transaction(paths, project_id: str, old_request_id: str,
                                   replacement_request_id: str) -> tuple[dict, dict] | None:
    """Find the one committed creation transaction for a replay epoch."""
    matches = []
    for _prepared_path, transaction in _prepared_transactions(
            paths, project_id, schema_version=UNRESOLVED_REPLAY_TRANSACTION_SCHEMA):
        if (transaction.get("old_request_id") == old_request_id
                and transaction.get("replacement_request_id") == replacement_request_id):
            transaction_id = transaction.get("transaction_id")
            if not isinstance(transaction_id, str):
                return None
            _prepared, committed_path = _transaction_paths(
                paths, transaction_id, schema_version=UNRESOLVED_REPLAY_TRANSACTION_SCHEMA
            )
            try:
                receipt = read_json(committed_path)
            except Exception:
                return None
            expected = {"schema_version": UNRESOLVED_REPLAY_TRANSACTION_SCHEMA, "state": "COMMITTED",
                        "transaction_id": transaction_id, "prepared_sha256": _json_sha256(transaction)}
            if receipt != expected:
                return None
            matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _supersession_transaction(paths, project_id: str, old_request_id: str,
                              replacement_request_id: str) -> tuple[dict, dict] | None:
    """Find the one committed creation transaction for a legacy replacement epoch."""
    matches = []
    for _prepared_path, transaction in _prepared_transactions(
            paths, project_id, schema_version=SUPERSESSION_TRANSACTION_SCHEMA):
        if (transaction.get("old_request_id") == old_request_id
                and transaction.get("replacement_request_id") == replacement_request_id):
            transaction_id = transaction.get("transaction_id")
            if not isinstance(transaction_id, str):
                return None
            _prepared, committed_path = _transaction_paths(
                paths, transaction_id, schema_version=SUPERSESSION_TRANSACTION_SCHEMA
            )
            try:
                receipt = read_json(committed_path)
            except Exception:
                return None
            expected = {"schema_version": SUPERSESSION_TRANSACTION_SCHEMA, "state": "COMMITTED",
                        "transaction_id": transaction_id, "prepared_sha256": _json_sha256(transaction)}
            if receipt != expected:
                return None
            matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _recover_pending_request_replacements(paths, project_id: str) -> dict[str, dict]:
    recovered = _recover_pending_supersessions(paths, project_id)
    replayed = _recover_pending_unresolved_replays(paths, project_id)
    qc_replaced = _recover_pending_qc_rejected_asset_replacements(paths, project_id)
    if set(recovered).intersection(replayed) or set(recovered).intersection(qc_replaced) or set(replayed).intersection(qc_replaced):
        raise FlowError("FLOW_REPLACEMENT_RECOVERY_INVALID")
    recovered.update(replayed)
    recovered.update(qc_replaced)
    return recovered


def _target(path: str, value: dict) -> dict:
    return {"path": path, "value": value, "sha256": _json_sha256(value)}


def supersede_ambiguous_request(runtime_root: Path | str, project_id: str, request_id: str, *,
                                reason: str, acknowledge_historical_dispatch_unknown: bool,
                                _fault_injector: Callable[[str], None] | None = None) -> dict:
    """Abandon one unrecoverable legacy Flow epoch without asserting provider truth.

    The old manifest record and its attempts/reconciliations remain immutable;
    the active request graph receives a nonce-backed replacement identity.  This
    operation performs no provider action.
    """
    if not isinstance(reason, str) or not reason.strip(): raise FlowError("LEGACY_SUPERSESSION_REASON_REQUIRED")
    if acknowledge_historical_dispatch_unknown is not True: raise FlowError("LEGACY_SUPERSESSION_UNKNOWN_ACK_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        recovered = _recover_pending_supersessions(paths, project_id)
        manifest_path, manifest = _manifest(paths, project_id)
        requests_path = paths.artifact_path("output/generation_requests.json")
        try: requests_data = read_json(requests_path)
        except Exception as error: raise FlowError("LEGACY_SUPERSESSION_INVALID") from error
        requests = requests_data.get("requests") if isinstance(requests_data, dict) else None
        if not isinstance(requests, list): raise FlowError("LEGACY_SUPERSESSION_INVALID")
        old_request = next((item for item in requests if item.get("request_id") == request_id), None)
        old_entry = next((item for item in manifest.get("requests", []) if item.get("request_id") == request_id), None)
        if not isinstance(old_request, dict):
            completed = recovered.get(request_id)
            if isinstance(old_entry, dict) and completed and _superseded_entry_valid(paths, project_id, old_entry, requests, {item.get("request_id"): item for item in manifest.get("requests", [])}):
                return {"old_request_id": request_id, "replacement_request_id": completed["replacement_request_id"],
                        "provider_submissions": 0, "status": SUPERSEDED_AMBIGUOUS_STATUS, "idempotent": True}
            raise FlowError("LEGACY_SUPERSESSION_ALREADY_SUPERSEDED")
        classification = _legacy_ambiguous_supersession_eligible(project_id, request_id, old_entry)
        if classification is None:
            raise FlowError("LEGACY_SUPERSESSION_NOT_ELIGIBLE")
        old_attempts_sha256 = _json_sha256(old_entry.get("attempts"))
        old_reconciliations_sha256 = _json_sha256(old_entry.get("reconciliation_events"))
        nonce = uuid.uuid4().hex
        epoch = int(old_request.get("replacement_epoch", 0)) + 1
        replacement_id, replacement_fingerprint = _replacement_identity(old_request, nonce=nonce, epoch=epoch)
        if any(item.get("request_id") == replacement_id for item in requests) or any(item.get("request_id") == replacement_id for item in manifest.get("requests", [])):
            raise FlowError("LEGACY_SUPERSESSION_IDENTITY_COLLISION")
        replacement = dict(old_request)
        replacement.update({"request_id": replacement_id, "fingerprint": replacement_fingerprint,
                            "replaces_request_id": request_id, "replacement_epoch": epoch,
                            "epoch_nonce": nonce})
        position = requests.index(old_request)
        requests[position] = replacement
        _migrate_request_references(requests_data, request_id, replacement_id)
        media_plan_path = paths.artifact_path("output/media_plan.json")
        media_plan = read_json(media_plan_path) if media_plan_path.is_file() else None
        media_plan_changed = isinstance(media_plan, dict) and _migrate_request_references(media_plan, request_id, replacement_id)
        event = {"at": _now(), "event": SUPERSEDED_AMBIGUOUS_STATUS, "operator_reason": reason.strip(),
                 "old_request_id": request_id, "old_status": old_entry.get("status"),
                 "old_failure_class": old_entry.get("failure_class"), "prior_dispatch_state": "UNKNOWN",
                 "prior_attribution_state": "UNRESOLVED", "replacement_request_id": replacement_id,
                 "historical_dispatch_unknown_acknowledged": True, "legacy_epoch_classification": classification,
                 "attempts_sha256": old_attempts_sha256, "reconciliation_events_sha256": old_reconciliations_sha256}
        old_entry.setdefault("supersession_events", []).append(event)
        old_entry.update({"status": SUPERSEDED_AMBIGUOUS_STATUS,
                          "failure_class": "LEGACY_SUPERSEDED_AMBIGUOUS",
                          "historical_provider_dispatch": "UNKNOWN",
                          "historical_attribution": "UNRESOLVED",
                          "replacement_request_id": replacement_id, "updated_at": event["at"]})
        manifest["requests"].append({"request_id": replacement_id, "request_identity_sha256": replacement_fingerprint,
                                     "related_identity": replacement.get("shot_id") or replacement.get("entity_id"),
                                     "media_type": replacement["media_type"], "provider": replacement.get("provider", "google_flow"),
                                     "prompt_sha256": hashlib.sha256(replacement["prompt"].encode("utf-8")).hexdigest(),
                                     "reference_asset_hashes": [], "attempts": [], "status": "PENDING", "created_at": event["at"],
                                     "replaces_request_id": request_id, "replacement_epoch": epoch, "epoch_nonce": nonce})
        if (_json_sha256(old_entry.get("attempts")) != old_attempts_sha256
                or _json_sha256(old_entry.get("reconciliation_events")) != old_reconciliations_sha256):
            raise FlowError("LEGACY_SUPERSESSION_APPEND_ONLY_VIOLATION")
        transaction_id = "supersession-" + _json_sha256({"project_id": project_id, "old_request_id": request_id,
                                                          "replacement_request_id": replacement_id})[:24]
        targets = {"generation_requests": _target("output/generation_requests.json", requests_data),
                   "generation_manifest": _target("output/generation_manifest.json", manifest)}
        if media_plan_changed: targets["media_plan"] = _target("output/media_plan.json", media_plan)
        transaction = {"schema_version": SUPERSESSION_TRANSACTION_SCHEMA, "state": "PREPARED",
                       "transaction_id": transaction_id, "project_id": project_id,
                       "old_request_id": request_id, "replacement_request_id": replacement_id,
                       "targets": targets}
        _publish_supersession_transaction(paths, transaction, fault_injector=_fault_injector)
        return {"old_request_id": request_id, "replacement_request_id": replacement_id,
                "provider_submissions": 0, "status": SUPERSEDED_AMBIGUOUS_STATUS}


def replay_unresolved_request(
        runtime_root: Path | str, project_id: str, request_id: str, *, reason: str,
        acknowledge_previous_dispatch_or_cost_may_have_occurred: bool,
        acknowledge_previous_output_ownership_unresolved: bool,
        acknowledge_replacement_may_consume_provider_credit: bool,
        _fault_injector: Callable[[str], None] | None = None) -> dict:
    """Create one fresh request epoch without resolving or rewriting provider truth.

    This is an explicit operator recovery transaction. It never calls a
    provider; the abandoned attempt history remains immutable and auditable.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("UNRESOLVED_REPLAY_REASON_REQUIRED")
    acknowledgements = {
        "previous_dispatch_or_cost_may_have_occurred_acknowledged":
            acknowledge_previous_dispatch_or_cost_may_have_occurred,
        "previous_output_ownership_unresolved_acknowledged":
            acknowledge_previous_output_ownership_unresolved,
        "replacement_may_consume_provider_credit_acknowledged":
            acknowledge_replacement_may_consume_provider_credit,
    }
    if not all(value is True for value in acknowledgements.values()):
        raise FlowError("UNRESOLVED_REPLAY_ACKNOWLEDGEMENTS_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        recovered = _recover_pending_request_replacements(paths, project_id)
        manifest_path, manifest = _manifest(paths, project_id)
        requests_path = paths.artifact_path("output/generation_requests.json")
        try:
            requests_data = read_json(requests_path)
        except Exception as error:
            raise FlowError("UNRESOLVED_REPLAY_INVALID") from error
        requests = requests_data.get("requests") if isinstance(requests_data, dict) else None
        if not isinstance(requests, list):
            raise FlowError("UNRESOLVED_REPLAY_INVALID")
        entries = {
            item.get("request_id"): item for item in manifest.get("requests", [])
            if isinstance(item, dict) and isinstance(item.get("request_id"), str)
        }
        old_request = next((item for item in requests if item.get("request_id") == request_id), None)
        old_entry = entries.get(request_id)
        if not isinstance(old_request, dict):
            completed = recovered.get(request_id)
            if (isinstance(old_entry, dict) and completed
                    and _abandoned_unresolved_entry_valid(paths, project_id, old_entry, requests, entries)):
                return {
                    "old_request_id": request_id,
                    "replacement_request_id": completed["replacement_request_id"],
                    "provider_submissions": 0,
                    "status": ABANDONED_UNRESOLVED_STATUS,
                    "idempotent": True,
                }
            raise FlowError("UNRESOLVED_REPLAY_ALREADY_COMPLETED")
        barrier = _first_unresolved(paths, project_id, requests, entries)
        if barrier is None or barrier[0].get("request_id") != request_id or barrier[1] is not old_entry:
            raise FlowError("UNRESOLVED_REPLAY_NOT_CURRENT_BARRIER")
        attempts = old_entry.get("attempts") if isinstance(old_entry, dict) else None
        if (not isinstance(old_entry, dict) or old_entry.get("selected_asset") is not None
                or not isinstance(attempts, list) or not attempts):
            raise FlowError("UNRESOLVED_REPLAY_NOT_ELIGIBLE")
        latest_attempt = attempts[-1] if isinstance(attempts[-1], dict) else None
        if (not isinstance(latest_attempt, dict)
                or latest_attempt.get("attribution_state") == "CONFIRMED"
                or not _unresolved_flow_entry(old_entry)):
            raise FlowError("UNRESOLVED_REPLAY_PROVIDER_TRUTH_NOT_UNRESOLVED")
        historical_dispatch = (
            "CONFIRMED" if any(
                isinstance(attempt, dict) and attempt.get("dispatch_confirmed") is True
                for attempt in attempts
            ) else "UNKNOWN"
        )
        old_attempts_sha256 = _json_sha256(attempts)
        nonce = uuid.uuid4().hex
        epoch = int(old_request.get("replay_epoch", old_request.get("replacement_epoch", 0))) + 1
        replacement_id, replacement_fingerprint = _replacement_identity(old_request, nonce=nonce, epoch=epoch)
        if (replacement_id == request_id
                or any(item.get("request_id") == replacement_id for item in requests)
                or replacement_id in entries):
            raise FlowError("UNRESOLVED_REPLAY_IDENTITY_COLLISION")
        replacement = dict(old_request)
        replacement.update({
            "request_id": replacement_id,
            "fingerprint": replacement_fingerprint,
            "replays_unresolved_request_id": request_id,
            "replay_epoch": epoch,
            "epoch_nonce": nonce,
        })
        position = requests.index(old_request)
        requests[position] = replacement
        _migrate_request_references(requests_data, request_id, replacement_id)
        media_plan_path = paths.artifact_path("output/media_plan.json")
        media_plan = read_json(media_plan_path) if media_plan_path.is_file() else None
        media_plan_changed = (
            isinstance(media_plan, dict)
            and _migrate_request_references(media_plan, request_id, replacement_id)
        )
        event_at = _now()
        event = {
            "at": event_at,
            "event": ABANDONED_UNRESOLVED_STATUS,
            "operator_reason": reason.strip(),
            "old_request_id": request_id,
            "old_status": old_entry.get("status"),
            "old_failure_class": old_entry.get("failure_class"),
            "historical_provider_dispatch": historical_dispatch,
            "historical_attribution": "UNRESOLVED",
            "replacement_request_id": replacement_id,
            "attempts_sha256": old_attempts_sha256,
            **acknowledgements,
        }
        transaction_id = "unresolved-replay-" + _json_sha256({
            "project_id": project_id,
            "old_request_id": request_id,
            "replacement_request_id": replacement_id,
        })[:24]
        replay_genesis = _replay_genesis_projection(
            replacement=replacement,
            queue_position=position,
            event=event,
            transaction_id=transaction_id,
        )
        if replay_genesis is None:
            raise FlowError("UNRESOLVED_REPLAY_GENESIS_INVALID")
        replay_genesis_sha256 = _json_sha256(replay_genesis)
        event.update({"replay_genesis": replay_genesis, "replay_genesis_sha256": replay_genesis_sha256})
        old_entry.setdefault("unresolved_replay_events", []).append(event)
        old_entry.update({
            "status": ABANDONED_UNRESOLVED_STATUS,
            "failure_class": "UNRESOLVED_REPLAY_CREATED",
            "historical_provider_dispatch": historical_dispatch,
            "historical_attribution": "UNRESOLVED",
            "replacement_request_id": replacement_id,
            "updated_at": event_at,
        })
        manifest["requests"].append({
            "request_id": replacement_id,
            "request_identity_sha256": replacement_fingerprint,
            "related_identity": replacement.get("shot_id") or replacement.get("entity_id"),
            "media_type": replacement["media_type"],
            "provider": replacement.get("provider", "google_flow"),
            "prompt_sha256": hashlib.sha256(replacement["prompt"].encode("utf-8")).hexdigest(),
            "reference_asset_hashes": [],
            "attempts": [],
            "status": "PENDING",
            "created_at": event_at,
            "replays_unresolved_request_id": request_id,
            "replay_epoch": epoch,
            "epoch_nonce": nonce,
            "replay_creation_transaction_id": transaction_id,
            "replay_genesis_sha256": replay_genesis_sha256,
        })
        if _json_sha256(old_entry.get("attempts")) != old_attempts_sha256:
            raise FlowError("UNRESOLVED_REPLAY_APPEND_ONLY_VIOLATION")
        targets = {
            "generation_requests": _target("output/generation_requests.json", requests_data),
            "generation_manifest": _target("output/generation_manifest.json", manifest),
        }
        if media_plan_changed:
            targets["media_plan"] = _target("output/media_plan.json", media_plan)
        transaction = {
            "schema_version": UNRESOLVED_REPLAY_TRANSACTION_SCHEMA,
            "state": "PREPARED",
            "transaction_id": transaction_id,
            "project_id": project_id,
            "old_request_id": request_id,
            "replacement_request_id": replacement_id,
            "replay_genesis_sha256": replay_genesis_sha256,
            "targets": targets,
        }
        _publish_unresolved_replay_transaction(paths, transaction, fault_injector=_fault_injector)
        return {
            "old_request_id": request_id,
            "replacement_request_id": replacement_id,
            "provider_submissions": 0,
            "status": ABANDONED_UNRESOLVED_STATUS,
            "idempotent": False,
        }


def _successful_raw_image(paths, entry):
    """Return the newest valid raw provider image explicitly awaiting cleanup."""
    for attempt in reversed(entry.get("attempts", [])):
        if (attempt.get("status") != "SUCCEEDED"
                or attempt.get("production_image_postprocess_required") is not True
                or attempt.get("attribution_status") == "INVALIDATED"
                or not isinstance(attempt.get("asset_path"), str)):
            continue
        try:
            metadata = validate_image(paths.artifact_path(attempt["asset_path"]))
        except AssetValidationError:
            continue
        if metadata["sha256"] == attempt.get("asset_sha256"):
            return attempt, metadata
    return None, None


def _clean_rel(entry: dict, attempt: dict) -> str:
    return f"assets/image/{entry['request_id']}/attempt_{attempt['attempt']:03d}_clean.png"


def _process_raw_image(paths, entry: dict, attempt: dict, *, output_rel: str | None = None) -> dict:
    """Append one local processing record and bind selected bytes on success."""
    if attempt.get("attribution_state") != "CONFIRMED" or attempt.get("attribution_status") == "INVALIDATED":
        raise FlowImagePostprocessError("OUTPUT_ATTRIBUTION_UNCONFIRMED")
    source_rel = attempt["asset_path"]
    source_sha = attempt["asset_sha256"]
    output_rel = output_rel or _clean_rel(entry, attempt)
    processing_number = len(entry.setdefault("postprocess_attempts", [])) + 1
    source_metadata = attempt.get("metadata", {})
    profile = profile_evidence(int(source_metadata.get("width", 0)), int(source_metadata.get("height", 0)))
    record = {
        "processing_attempt": processing_number,
        "status": "PROCESSING",
        "source_provider_attempt": attempt["attempt"],
        "source_path": source_rel,
        "source_sha256": source_sha,
        "output_path": output_rel,
        "processor_name": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "flow_mark_profile_version": profile["profile_version"],
        "profile_sha256": profile["profile_sha256"],
        "started_at": _now(),
    }
    entry["postprocess_attempts"].append(record)
    try:
        result = process_flow_image(paths.artifact_path(source_rel), paths.artifact_path(output_rel))
    except FlowImagePostprocessError as error:
        record.update({"status": "FAILED", "failure_class": error.failure_class,
                       "diagnostic": str(error), "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class,
                      "updated_at": _now()})
        raise
    if result["source_sha256"] != source_sha:
        record.update({"status": "FAILED", "failure_class": "FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID",
                       "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID",
                      "updated_at": _now()})
        raise FlowImagePostprocessError("FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID")
    record.update({
        "status": "SUCCEEDED",
        "output_sha256": result["output_sha256"],
        "processor_name": result["processor_name"],
        "processor_version": result["processor_version"],
        "flow_mark_profile_version": result["profile_version"],
        "profile_sha256": result["profile_sha256"],
        "mask_sha256": result["mask_sha256"],
        "completed_at": _now(),
    })
    selected = {
        "path": output_rel,
        "sha256": result["output_sha256"],
        "attempt": attempt["attempt"],
        "metadata": result["output_metadata"],
        "production_qc": "PENDING",
        "source_provider_attempt": attempt["attempt"],
        "source_path": source_rel,
        "source_sha256": source_sha,
        "postprocess_attempt": processing_number,
        "processor_name": result["processor_name"],
        "processor_version": result["processor_version"],
        "flow_mark_profile_version": result["profile_version"],
        "mask_sha256": result["mask_sha256"],
    }
    entry.update({"selected_asset": selected, "status": "QC_PENDING", "failure_class": None,
                  "updated_at": _now()})
    return selected


def _repair_local_image(paths, entry: dict, request: dict) -> bool:
    """Retry cleanup from preserved raw bytes; return whether provider dispatch must stop."""
    if request.get("media_type") != "IMAGE" or request.get("execution_tier") != "STANDARD_PRODUCTION":
        return False
    attempt, _ = _successful_raw_image(paths, entry)
    if attempt is None:
        return False
    selected = entry.get("selected_asset")
    lineage_matches = isinstance(selected, dict) and selected.get("source_provider_attempt") == attempt.get("attempt")
    local_failure = entry.get("failure_class") in LOCAL_IMAGE_FAILURES
    derivative_invalid = lineage_matches and not _valid_selected(paths, entry)
    if not local_failure and not derivative_invalid:
        return False
    try:
        _process_raw_image(paths, entry, attempt, output_rel=(selected or {}).get("path"))
    except FlowImagePostprocessError:
        pass
    return True


def _find_duplicate_selection(paths, manifest: dict, request: dict, metadata: dict, entry: dict):
    identity_field = "dhash256" if request["media_type"] == "IMAGE" else "sha256"
    for other in manifest["requests"]:
        if other is entry or other.get("media_type") != request["media_type"]:
            continue
        other_selected = other.get("selected_asset")
        if not isinstance(other_selected, dict):
            continue
        other_identity = other_selected.get("metadata", {}).get(identity_field)
        if not other_identity and request["media_type"] == "IMAGE":
            try:
                other_identity = validate_image(paths.artifact_path(other_selected["path"]))[identity_field]
            except Exception:
                other_identity = None
        same = other_identity == metadata.get(identity_field)
        if request["media_type"] == "IMAGE" and other_identity and metadata.get(identity_field):
            try:
                same = (int(other_identity, 16) ^ int(metadata[identity_field], 16)).bit_count() <= 4
            except ValueError:
                same = False
        if same:
            return other
    return None

def _runnable(request, entries): return all(entries.get(dep, {}).get("status") == "SUCCEEDED" for dep in request.get("depends_on", []))


def reconcile_local_assets(runtime_root: Path | str, project_id: str) -> set[str]:
    """Invalidate only provider selections whose exact local bytes no longer validate."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    invalidated: set[str] = set()
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        for entry in manifest["requests"]:
            if entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or _valid_selected(paths, entry):
                continue
            selected = entry.get("selected_asset") if isinstance(entry.get("selected_asset"), dict) else {}
            raw_attempt, _ = _successful_raw_image(paths, entry)
            failure_class = "FLOW_IMAGE_DERIVATIVE_INVALID" if raw_attempt is not None else "ASSET_INVALID"
            entry.setdefault("asset_invalidations", []).append({
                "detected_at": _now(), "path": selected.get("path"),
                "expected_sha256": selected.get("sha256"), "failure_class": failure_class,
            })
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": failure_class, "updated_at": _now()})
            invalidated.add(entry["request_id"])
        if invalidated:
            atomic_write_json(path, manifest)
    return invalidated


def reject_selected_asset(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str) -> None:
    """Record a visual-review rejection without deleting or rewriting its attempt."""
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("CREATIVE_REJECTION_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or not isinstance(entry.get("selected_asset"), dict):
            raise FlowError("CREATIVE_REJECTION_INVALID")
        selected = entry["selected_asset"]
        entry.setdefault("creative_rejections", []).append({"rejected_at": _now(), "asset_path": selected.get("path"),
                                                              "asset_sha256": selected.get("sha256"), "reason": reason.strip()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "CREATIVE_REJECTED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def invalidate_asset_attribution(runtime_root: Path | str, project_id: str, request_id: str,
                                 *, reason: str = "OUTPUT_ATTRIBUTION_INVALID") -> dict:
    """Quarantine a wrong request mapping without deleting provider evidence."""
    if reason != "OUTPUT_ATTRIBUTION_INVALID":
        raise FlowError("ATTRIBUTION_INVALIDATION_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if not entry or not isinstance(selected, dict):
            raise FlowError("ATTRIBUTION_INVALIDATION_INVALID")
        attempt = next((item for item in entry.get("attempts", [])
                        if item.get("attempt") == selected.get("attempt")), None)
        if not isinstance(attempt, dict):
            raise FlowError("ATTRIBUTION_INVALIDATION_INVALID")
        event = {
            "invalidated_at": _now(),
            "reason": reason,
            "provider_attempt": attempt.get("attempt"),
            "raw_path": attempt.get("asset_path"),
            "raw_sha256": attempt.get("asset_sha256"),
            "selected_path": selected.get("path"),
            "selected_sha256": selected.get("sha256"),
        }
        entry.setdefault("attribution_invalidations", []).append(event)
        attempt.setdefault("attribution_events", []).append({
            "at": event["invalidated_at"], "state": "INVALIDATED", "reason": reason,
        })
        attempt["attribution_status"] = "INVALIDATED"
        entry.pop("selected_asset", None)
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": reason, "updated_at": _now()})
        atomic_write_json(path, manifest)
        return event


def recover_interrupted_pre_dispatch_attempt(runtime_root: Path | str, project_id: str, request_id: str) -> None:
    """Recover only an attempt durably known to precede the provider boundary."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        attempt = entry.get("attempts", [])[-1] if isinstance(entry, dict) and entry.get("attempts") else None
        if not isinstance(entry, dict) or entry.get("status") != "GENERATING":
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        if not _produce_crash_before_provider_setup_proof(attempt):
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        attempt.update({"status":"NOT_DISPATCHED", "failure_class":"FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH",
                        "diagnostic":"process interrupted before the persisted provider boundary", "completed_at":_now()})
        entry.update({"status":"NOT_DISPATCHED", "failure_class":"FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH",
                      "updated_at":_now()})
        atomic_write_json(path, manifest)


def review_production_asset(runtime_root: Path | str, project_id: str, request_id: str, report: dict) -> None:
    """Approve or reject selected bytes using the complete production QC rubric."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or not isinstance(entry.get("selected_asset"), dict):
            raise FlowError("MEDIA_QC_INVALID")
        try:
            accepted = validate_production_qc(
                report, provider=entry.get("provider"), media_type=entry.get("media_type")
            )
            # Story shots require an explicit structured comparison to their
            # narration intent. Technical/media quality alone is insufficient.
            try:
                requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
            except Exception:
                requests = []
            request = next((item for item in requests if item.get("request_id") == request_id), {})
            if request.get("purpose") == "SHOT":
                classification = report.get("alignment_classification") or report.get("visual_narration_alignment")
                if classification not in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"}:
                    failure = "VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED" if not classification else "VISUAL_NARRATION_ALIGNMENT_MISMATCH"
                    raise MediaQualityError(failure)
                if classification == "PASS_ATMOSPHERIC":
                    try:
                        shots = read_json(paths.artifact_path("output/shot_plan.json")).get("shots", [])
                    except Exception:
                        shots = []
                    shot = next((item for item in shots if item.get("shot_id") == request.get("shot_id")), {})
                    if not shot.get("atmospheric"):
                        raise MediaQualityError("VISUAL_NARRATION_ALIGNMENT_MISMATCH")
        except MediaQualityError as error:
            entry.setdefault("quality_reviews", []).append({"reviewed_at": _now(), "status": "REJECTED", "failure_class": error.failure_class, "report": report})
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
            atomic_write_json(path, manifest)
            raise FlowError(error.failure_class) from error
        entry.setdefault("quality_reviews", []).append({"reviewed_at": _now(), "status": "APPROVED", "report": accepted})
        entry["selected_asset"]["production_qc"] = "APPROVED"
        if request.get("purpose") == "SHOT":
            # validate_production_qc intentionally returns only the technical
            # rubric. Keep the separately validated narrative verdict with the
            # exact selected bytes so the final render audit is self-contained.
            entry["selected_asset"]["alignment_classification"] = classification
            entry["selected_asset"]["alignment_observation"] = str(report.get("notes", "")).strip()
        temporal_ready = request.get("media_type") != "VIDEO" or entry["selected_asset"].get("temporal_qc") == "APPROVED"
        entry.update({"status": "SUCCEEDED" if temporal_ready else "QC_PENDING",
                      "failure_class": None if temporal_ready else "TEMPORAL_VIDEO_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def review_temporal_asset(runtime_root: Path | str, project_id: str, request_id: str, report: dict) -> None:
    """Apply deterministic temporal hard gates to exact selected video bytes."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if not entry or entry.get("media_type") != "VIDEO" or entry.get("status") not in {"QC_PENDING", "SUCCEEDED"} or not isinstance(selected, dict):
            raise FlowError("TEMPORAL_VIDEO_QC_INVALID")
        state = report.get("state")
        if state not in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW", "REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP", "REJECT_IDENTITY", "REJECT_BACKGROUND", "UNCERTAIN"}:
            raise FlowError("TEMPORAL_VIDEO_QC_INVALID")
        selected.setdefault("temporal_reviews", []).append({"reviewed_at": _now(), "report": report})
        if state not in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW"} or not report.get("eligible"):
            failure = "TEMPORAL_VIDEO_QC_UNCERTAIN" if state == "UNCERTAIN" else state
            selected["temporal_qc"] = "REJECTED"
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": failure, "updated_at": _now()})
            atomic_write_json(path, manifest)
            raise FlowError(failure)
        metadata = selected.get("metadata", {})
        duration = float(metadata.get("duration_seconds", 0))
        start, end = float(report.get("usable_start", 0)), float(report.get("usable_end", duration))
        if start < 0 or end <= start or end > duration + .05:
            raise FlowError("USABLE_TEMPORAL_WINDOW_INVALID")
        selected.update({"temporal_qc": "APPROVED", "usable_start": start, "usable_end": end,
                         "temporal_state": state})
        semantic_ready = selected.get("production_qc") == "APPROVED" and selected.get("alignment_classification") in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"}
        entry.update({"status": "SUCCEEDED" if semantic_ready else "QC_PENDING",
                      "failure_class": None if semantic_ready else "VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def reopen_uncertain_temporal_qc(runtime_root: Path | str, project_id: str, request_id: str) -> None:
    """Retry reasoning on the same bytes; never queue a provider generation."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if (not entry or entry.get("status") != "FAILED_RETRYABLE"
                or entry.get("failure_class") != "TEMPORAL_VIDEO_QC_UNCERTAIN"
                or not isinstance(selected, dict)):
            raise FlowError("TEMPORAL_QC_RETRY_INVALID")
        entry.setdefault("qc_retry_events", []).append({"at": _now(), "asset_sha256": selected.get("sha256"),
                                                         "reason": "retry uncertain Gemini routing/QC on identical bytes"})
        selected["temporal_qc"] = "PENDING"
        entry.update({"status": "QC_PENDING", "failure_class": "TEMPORAL_VIDEO_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def _owned_mandatory_qc_rejection(entry: dict | None) -> bool:
    """Recognize the narrow historical state that requires a fresh epoch."""
    if not isinstance(entry, dict) or not isinstance(entry.get("selected_asset"), dict):
        return False
    if entry.get("status") != "FAILED_RETRYABLE" or entry.get("replacement_of"):
        return False
    failure = entry.get("failure_class")
    reviews = entry.get("quality_reviews")
    qc_rejected = (isinstance(failure, str) and failure.endswith("_QC_REJECTED")) or (
        isinstance(reviews, list) and any(isinstance(item, dict) and item.get("status") == "REJECTED" for item in reviews)
    )
    if not qc_rejected:
        return False
    attempts = entry.get("attempts")
    selected_attempt = entry["selected_asset"].get("attempt")
    return (isinstance(attempts, list) and any(
        isinstance(attempt, dict) and attempt.get("attempt") == selected_attempt
        and attempt.get("attribution_state") == "CONFIRMED"
        for attempt in attempts
    ))


def _qc_replacement_genesis_projection(request: dict) -> dict | None:
    """The request facts fixed at replacement creation, excluding runtime state."""
    required = ("request_id", "fingerprint", "prompt", "purpose", "media_type", "provider", "replacement_of",
                "replacement_reason", "epoch_nonce")
    if not isinstance(request, dict) or any(not isinstance(request.get(key), str) or not request[key] for key in required):
        return None
    if request.get("replacement_reason") != QC_REJECTED_ASSET_REPLACEMENT_REASON:
        return None
    if not isinstance(request.get("replacement_epoch"), int) or request["replacement_epoch"] < 1:
        return None
    for key in ("depends_on", "reference_asset_ids"):
        if not isinstance(request.get(key), list) or any(not isinstance(item, str) or not item for item in request[key]):
            return None
    return {
        "request_id": request["request_id"], "fingerprint": request["fingerprint"], "prompt": request["prompt"],
        "purpose": request["purpose"], "shot_id": request.get("shot_id"), "entity_id": request.get("entity_id"),
        "media_type": request["media_type"], "provider": request["provider"], "output_count": request.get("output_count", 1),
        "execution_tier": request.get("execution_tier"), "depends_on": list(request["depends_on"]),
        "reference_asset_ids": list(request["reference_asset_ids"]), "replacement_of": request["replacement_of"],
        "replacement_reason": request["replacement_reason"], "replacement_epoch": request["replacement_epoch"],
        "epoch_nonce": request["epoch_nonce"],
    }


def _qc_rejected_asset_replacement_transaction(paths, project_id: str, old_request_id: str,
                                                replacement_request_id: str) -> tuple[dict, dict] | None:
    """Find exactly one receipt-verified immutable creation transaction."""
    matches = []
    for _path, transaction in _prepared_transactions(
            paths, project_id, schema_version=QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA):
        if (transaction.get("old_request_id") != old_request_id
                or transaction.get("replacement_request_id") != replacement_request_id):
            continue
        transaction_id = transaction.get("transaction_id")
        if not isinstance(transaction_id, str):
            return None
        _prepared, committed_path = _transaction_paths(
            paths, transaction_id, schema_version=QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA
        )
        try:
            receipt = read_json(committed_path)
        except Exception:
            return None
        expected = {"schema_version": QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA, "state": "COMMITTED",
                    "transaction_id": transaction_id, "prepared_sha256": _json_sha256(transaction)}
        if receipt != expected:
            return None
        matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _qc_rejected_asset_replacement_valid(paths, project_id: str, entry: dict, requests: list[dict],
                                         entries: dict[str, dict]) -> bool:
    """Verify immutable QC-replacement genesis, never a permanently pristine runtime entry."""
    if entry.get("status") != QC_REJECTED_ASSET_REPLACED_STATUS or not isinstance(entry.get("selected_asset"), dict):
        return False
    replacement_id = entry.get("replacement_request_id")
    events = entry.get("qc_replacement_events")
    if not isinstance(replacement_id, str) or not isinstance(events, list) or len(events) != 1:
        return False
    event = events[0] if isinstance(events[0], dict) else None
    replacement = next((item for item in requests if item.get("request_id") == replacement_id), None)
    replacement_entry = entries.get(replacement_id)
    resolved_transaction = _qc_rejected_asset_replacement_transaction(
        paths, project_id, entry.get("request_id"), replacement_id
    )
    if resolved_transaction is None:
        return False
    transaction, _receipt = resolved_transaction
    stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
    stored_manifest = transaction["targets"]["generation_manifest"]["value"].get("requests", [])
    stored_old = next((item for item in stored_manifest if item.get("request_id") == entry.get("request_id")), None)
    stored_replacement = next((item for item in stored_requests if item.get("request_id") == replacement_id), None)
    stored_replacement_entry = next((item for item in stored_manifest if item.get("request_id") == replacement_id), None)
    duplicate_requests = [item for item in requests if item.get("replacement_of") == entry.get("request_id")
                          and item.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON
                          # A later replay of this exact QC child retains older
                          # metadata for audit lineage, but its direct parent is
                          # the replay target, not this QC parent.
                          and item.get("replays_unresolved_request_id") != replacement_id]
    duplicate_entries = [item for item in entries.values() if item.get("replacement_of") == entry.get("request_id")
                         and item.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON]
    immutable_edge = bool(
        isinstance(event, dict)
        and event.get("event") == QC_REJECTED_ASSET_REPLACEMENT_REASON
        and event.get("old_request_id") == entry.get("request_id")
        and event.get("replacement_request_id") == replacement_id
        and event.get("attempts_sha256") == _json_sha256(entry.get("attempts"))
        and event.get("selected_asset_sha256") == entry["selected_asset"].get("sha256")
        and isinstance(stored_old, dict)
        and stored_old.get("attempts") == entry.get("attempts")
        and stored_old.get("selected_asset") == entry.get("selected_asset")
        and stored_old.get("failure_class") == entry.get("failure_class")
        and isinstance(stored_replacement, dict)
        and isinstance(replacement_entry, dict)
        and replacement_entry.get("replacement_of") == entry.get("request_id")
        and replacement_entry.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON
        and isinstance(replacement_entry.get("attempts"), list)
        and all(isinstance(attempt, dict) for attempt in replacement_entry["attempts"])
        and isinstance(stored_replacement_entry, dict)
        and stored_replacement_entry.get("attempts") == []
        and stored_replacement_entry.get("provider_submissions") == 0
        and stored_replacement_entry.get("selected_asset") is None
        and stored_replacement_entry.get("attribution_claim") == "NONE"
        and len(duplicate_entries) == 1
    )
    if not immutable_edge:
        return False
    if isinstance(replacement, dict):
        return (
            len(duplicate_requests) == 1
            and _qc_replacement_genesis_projection(replacement) is not None
            and _qc_replacement_genesis_projection(replacement) == _qc_replacement_genesis_projection(stored_replacement)
            and replacement_entry.get("status") in {
                "PENDING", "GENERATING", "NOT_DISPATCHED", "AMBIGUOUS", "FAILED_RETRYABLE", "QC_PENDING", "SUCCEEDED",
                "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED",
            }
        )
    return (
        not duplicate_requests
        and _historical_replacement_parent(replacement_entry)
        and _manifest_identity_matches_request(replacement_entry, stored_replacement)
    )


def _resolve_current_canonical_descendant(paths, project_id: str, request_id: str,
                                          requests: list[dict], entries: dict[str, dict]) -> str | None:
    """Resolve a current request only through independently proven replacement edges.

    Historical epochs remain immutable evidence.  This resolver intentionally
    preserves every immediate edge while allowing a valid child to have a later
    canonical descendant.  Any missing edge proof, duplicate, cycle, or active
    ambiguity denies resolution rather than reopening historical provider work.
    """
    request_by_id = {item.get("request_id"): item for item in requests if isinstance(item, dict)}
    seen: set[str] = set()
    current_id = request_id
    while isinstance(current_id, str) and current_id and current_id not in seen:
        seen.add(current_id)
        entry = entries.get(current_id)
        if not isinstance(entry, dict):
            return None
        status = entry.get("status")
        if status == ABANDONED_UNRESOLVED_STATUS:
            if not _abandoned_unresolved_entry_valid(paths, project_id, entry, requests, entries):
                return None
            child_id = entry.get("replacement_request_id")
        elif status == QC_REJECTED_ASSET_REPLACED_STATUS:
            if not _qc_rejected_asset_replacement_valid(paths, project_id, entry, requests, entries):
                return None
            child_id = entry.get("replacement_request_id")
        elif status == SUPERSEDED_AMBIGUOUS_STATUS:
            if not _superseded_entry_valid(paths, project_id, entry, requests, entries):
                return None
            child_id = entry.get("replacement_request_id")
        else:
            # Only a current request controls runnable and queue state.  An
            # ambiguous descendant stays a fail-closed barrier, never a route
            # to revive an ancestor.
            if current_id not in request_by_id or status == "AMBIGUOUS":
                return None
            return current_id
        if not isinstance(child_id, str) or not child_id or child_id in seen:
            return None
        current_id = child_id
    return None


def replace_qc_rejected_asset(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str,
                              _fault_injector: Callable[[str], None] | None = None) -> dict:
    """Atomically replace one owned mandatory-QC-rejected asset without reopening it."""
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        recovered = _recover_pending_qc_rejected_asset_replacements(paths, project_id)
        manifest_path, manifest = _manifest(paths, project_id)
        requests_path = paths.artifact_path("output/generation_requests.json")
        try:
            requests_data = read_json(requests_path)
            requests = requests_data.get("requests") if isinstance(requests_data, dict) else None
        except Exception as error:
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_INVALID") from error
        if not isinstance(requests, list):
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_INVALID")
        entries = {item.get("request_id"): item for item in manifest.get("requests", []) if isinstance(item, dict)}
        old_request = next((item for item in requests if item.get("request_id") == request_id), None)
        old_entry = entries.get(request_id)
        if not isinstance(old_request, dict):
            completed = recovered.get(request_id)
            if (isinstance(old_entry, dict) and completed
                    and _qc_rejected_asset_replacement_valid(paths, project_id, old_entry, requests, entries)):
                return {"old_request_id": request_id, "replacement_request_id": completed["replacement_request_id"],
                        "provider_submissions": 0, "status": QC_REJECTED_ASSET_REPLACED_STATUS, "idempotent": True}
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_ALREADY_COMPLETED")
        if not _owned_mandatory_qc_rejection(old_entry):
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_NOT_ELIGIBLE")
        attempts_sha256 = _json_sha256(old_entry["attempts"])
        selected_sha256 = old_entry["selected_asset"].get("sha256")
        nonce = uuid.uuid4().hex
        epoch = int(old_request.get("replacement_epoch", 0)) + 1
        replacement_id, replacement_fingerprint = _replacement_identity(old_request, nonce=nonce, epoch=epoch)
        if replacement_id in entries or any(item.get("request_id") == replacement_id for item in requests):
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_IDENTITY_COLLISION")
        replacement = dict(old_request)
        replacement.update({"request_id": replacement_id, "fingerprint": replacement_fingerprint,
                            "replaces_request_id": request_id, "replacement_of": request_id,
                            "replacement_reason": QC_REJECTED_ASSET_REPLACEMENT_REASON,
                            "replacement_epoch": epoch, "epoch_nonce": nonce})
        position = requests.index(old_request)
        requests[position] = replacement
        _migrate_request_references(requests_data, request_id, replacement_id)
        media_plan_path = paths.artifact_path("output/media_plan.json")
        media_plan = read_json(media_plan_path) if media_plan_path.is_file() else None
        media_plan_changed = isinstance(media_plan, dict) and _migrate_request_references(media_plan, request_id, replacement_id)
        at = _now()
        event = {"at": at, "event": QC_REJECTED_ASSET_REPLACEMENT_REASON, "operator_reason": reason.strip(),
                 "old_request_id": request_id, "replacement_request_id": replacement_id,
                 "old_failure_class": old_entry.get("failure_class"), "attempts_sha256": attempts_sha256,
                 "selected_asset_sha256": selected_sha256, "historical_provider_dispatch": "CONFIRMED",
                 "historical_attribution": "CONFIRMED"}
        old_entry.setdefault("qc_replacement_events", []).append(event)
        old_entry.update({"status": QC_REJECTED_ASSET_REPLACED_STATUS, "replacement_request_id": replacement_id,
                          "replacement_reason": QC_REJECTED_ASSET_REPLACEMENT_REASON, "updated_at": at})
        manifest["requests"].append({"request_id": replacement_id, "request_identity_sha256": replacement_fingerprint,
                                     "related_identity": replacement.get("shot_id") or replacement.get("entity_id"),
                                     "media_type": replacement["media_type"], "provider": replacement.get("provider", "google_flow"),
                                     "prompt_sha256": hashlib.sha256(replacement["prompt"].encode("utf-8")).hexdigest(),
                                     "reference_asset_hashes": [], "attempts": [], "provider_submissions": 0,
                                     "selected_asset": None, "attribution_claim": "NONE", "status": "PENDING", "created_at": at,
                                     "replaces_request_id": request_id, "replacement_of": request_id,
                                     "replacement_reason": QC_REJECTED_ASSET_REPLACEMENT_REASON,
                                     "replacement_epoch": epoch, "epoch_nonce": nonce})
        if _json_sha256(old_entry.get("attempts")) != attempts_sha256 or old_entry["selected_asset"].get("sha256") != selected_sha256:
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_APPEND_ONLY_VIOLATION")
        transaction_id = "qc-rejected-asset-replacement-" + _json_sha256({"project_id": project_id, "old_request_id": request_id, "replacement_request_id": replacement_id})[:24]
        targets = {"generation_requests": _target("output/generation_requests.json", requests_data),
                   "generation_manifest": _target("output/generation_manifest.json", manifest)}
        if media_plan_changed: targets["media_plan"] = _target("output/media_plan.json", media_plan)
        transaction = {"schema_version": QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA, "state": "PREPARED",
                       "transaction_id": transaction_id, "project_id": project_id, "old_request_id": request_id,
                       "replacement_request_id": replacement_id, "targets": targets}
        _publish_replacement_transaction(paths, transaction, fault_injector=_fault_injector)
        return {"old_request_id": request_id, "replacement_request_id": replacement_id,
                "provider_submissions": 0, "status": QC_REJECTED_ASSET_REPLACED_STATUS, "idempotent": False}


def queue_regeneration(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str) -> dict | None:
    """Route QC-rejected owned assets to replacement; retain proven no-dispatch retries."""
    if not isinstance(reason, str) or not reason.strip(): raise FlowError("REGENERATION_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") in {"GENERATING", "AMBIGUOUS"}: raise FlowError("REGENERATION_NOT_ALLOWED")
        if _owned_mandatory_qc_rejection(entry):
            # Release before the replacement operation takes its own project lock.
            pass
        else:
            raw_attempt, _ = _successful_raw_image(paths, entry)
            retry_local = raw_attempt is not None and entry.get("failure_class") in LOCAL_IMAGE_FAILURES
            action = "RETRY_LOCAL_POSTPROCESS" if retry_local else "REGENERATE"
            entry.setdefault("operator_actions", []).append({"action":action,"reason":reason.strip(),"at":_now()})
            entry.update({"status":"FAILED_RETRYABLE",
                          "failure_class":entry.get("failure_class") if retry_local else "OPERATOR_REGENERATION",
                          "updated_at":_now()})
            atomic_write_json(path, manifest)
            return
    return replace_qc_rejected_asset(runtime_root, project_id, request_id, reason=reason)

def reopen_verified_pre_dispatch_failure(runtime_root: Path | str, project_id: str, request_id: str) -> None:
    """Only reopen an attempt already proven safe by the canonical authority."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id); entry = next((e for e in manifest["requests"] if e.get("request_id") == request_id), None)
        if not entry or entry.get("status") != "FAILED_PERMANENT": raise FlowError("GENERATION_RECONCILIATION_INVALID")
        attempt = entry.get("attempts", [])[-1] if entry.get("attempts") else None
        safe_pre_dispatch = {"FLOW_UI_CHANGED", "FLOW_CAPABILITY_UNAVAILABLE"}
        if (not isinstance(attempt, dict) or attempt.get("failure_class") not in safe_pre_dispatch
                or not canonical_no_dispatch_proof(attempt)):
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        entry["status"] = "FAILED_RETRYABLE"; entry["reconciled_at"] = _now(); entry["reconciliation"] = "verified_no_dispatch"; atomic_write_json(path, manifest)

def reopen_verified_false_dispatch(runtime_root: Path | str, project_id: str, request_id: str,
                                   *, evidence: dict) -> None:
    """Reopen only when external evidence and canonical proof both agree."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        attempt = entry.get("attempts", [])[-1] if isinstance(entry, dict) and entry.get("attempts") else None
        settings = attempt.get("provider_settings", {}) if isinstance(attempt, dict) else {}
        try:
            request = next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
                           if item.get("request_id") == request_id)
        except Exception as error:
            raise FlowError("GENERATION_RECONCILIATION_INVALID") from error
        prompt_hash = hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest()
        screenshot_hash = evidence.get("screenshot_sha256") if isinstance(evidence, dict) else None
        valid = (entry.get("status") == "AMBIGUOUS" and attempt.get("failure_class") == "FLOW_TIMEOUT"
                 and settings.get("dispatch_ack_method") == "composer_clear_or_output_transition"
                 and settings.get("last_added_candidate_count") == 0
                 and evidence.get("prompt_retained") is True and evidence.get("visible_media_count") == 0
                 and evidence.get("prompt_sha256") == prompt_hash and isinstance(screenshot_hash, str)
                 and len(screenshot_hash) == 64 and all(c in "0123456789abcdef" for c in screenshot_hash))
        if not valid or not canonical_no_dispatch_proof(attempt):
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        attempt.update({"status":"NOT_DISPATCHED", "failure_class":"FLOW_FALSE_DISPATCH_ACK",
                        "reconciliation_evidence":dict(evidence)})
        entry.update({"status":"FAILED_RETRYABLE", "failure_class":"FLOW_FALSE_DISPATCH_ACK",
                      "reconciled_at":_now(), "reconciliation":"verified_prompt_retained_and_no_media"})
        atomic_write_json(path, manifest)

def adopt_manual_recovery(runtime_root: Path | str, project_id: str, request_id: str, source: Path, *, settings: dict, attribution: str) -> dict:
    """Adopt a local override without fabricating confirmed Flow attribution.

    Exact provider recovery is intentionally a separate, evidence-bearing path;
    an arbitrary operator file is recorded as an operator-local asset only.
    """
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest=_manifest(paths, project_id); entry=next((e for e in manifest["requests"] if e.get("request_id")==request_id),None)
        if not entry or entry.get("status") not in {"AMBIGUOUS", "NOT_DISPATCHED", "FAILED_RETRYABLE"} or not attribution: raise FlowError("MANUAL_RECOVERY_ATTRIBUTION_INSUFFICIENT")
        if entry.get("status") == "AMBIGUOUS": raise FlowError("MANUAL_LOCAL_OVERRIDE_AMBIGUOUS_BLOCKED")
        metadata=validate_image(source) if entry["media_type"]=="IMAGE" else validate_video(source)
        number=len(entry["attempts"])+1
        try: request=next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"] if item.get("request_id")==request_id)
        except Exception: request={}
        production=request.get("execution_tier")=="STANDARD_PRODUCTION"
        raw_suffix = source.suffix.lower() or (".png" if entry["media_type"] == "IMAGE" else ".mp4")
        raw_label = "operator_local_asset"
        rel=f"assets/{entry['media_type'].lower()}/{request_id}/{raw_label}_{number:03d}{raw_suffix}"
        target=paths.artifact_path(rel);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        confirmed_at = _now()
        attempt={"attempt":number,"status":"SUCCEEDED","dispatch_origin":"operator_local_override","attribution_evidence":attribution,"attribution_state":"LOCAL_OVERRIDE","attribution_method":"operator_local_asset","attribution_method_version":"operator-local-asset/1.0.0","provider_settings":settings,"asset_path":rel,"asset_sha256":metadata["sha256"],"downloaded_raw_path":rel,"raw_sha256":metadata["sha256"],"metadata":metadata,"completed_at":confirmed_at}
        entry["attempts"].append(attempt)
        selected={"path":rel,"sha256":metadata["sha256"],"attempt":number,"metadata":metadata,
                  "provenance":"OPERATOR_LOCAL_ASSET","production_qc":"PENDING" if production else "ENGINEERING_FIXTURE"}
        entry.update({"status":"QC_PENDING" if production else "SUCCEEDED","selected_asset":selected,
                      "failure_class":None,"updated_at":_now()})
        atomic_write_json(path,manifest);return selected


def adopt_exact_flow_recovery(runtime_root: Path | str, project_id: str, request_id: str, source: Path, *,
                              provider_identity: dict, evidence: str, settings: dict | None = None) -> dict:
    """Record a human-downloaded result only when exact provider identity is supplied."""
    if not isinstance(provider_identity, dict) or not any(provider_identity.get(key) for key in ("asset_id", "card_id", "identity")):
        raise FlowError("MANUAL_RECOVERY_EXACT_PROVIDER_IDENTITY_REQUIRED")
    if not isinstance(evidence, str) or not evidence.strip(): raise FlowError("MANUAL_RECOVERY_ATTRIBUTION_INSUFFICIENT")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id); entry=next((e for e in manifest["requests"] if e.get("request_id")==request_id),None)
        if not entry or entry.get("status") not in {"AMBIGUOUS", "NOT_DISPATCHED", "FAILED_RETRYABLE"}: raise FlowError("MANUAL_RECOVERY_ATTRIBUTION_INSUFFICIENT")
        try: request=next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"] if item.get("request_id")==request_id)
        except Exception as error: raise FlowError("MANUAL_RECOVERY_ATTRIBUTION_INSUFFICIENT") from error
        production=request.get("execution_tier") == "STANDARD_PRODUCTION"
        metadata=validate_image(source) if entry["media_type"]=="IMAGE" else validate_video(source)
        number=len(entry["attempts"])+1; suffix=source.suffix.lower() or (".png" if entry["media_type"] == "IMAGE" else ".mp4")
        rel=f"assets/{entry['media_type'].lower()}/{request_id}/exact_flow_recovery_{number:03d}{suffix}"
        target=paths.artifact_path(rel); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
        at=_now(); attempt={"attempt":number,"status":"SUCCEEDED","dispatch_origin":"human_exact_flow_recovery",
            "attribution_evidence":evidence.strip(),"attribution_state":"CONFIRMED","attribution_method":"operator_exact_provider_identity",
            "attribution_method_version":"operator-exact-flow-recovery/1.0.0","attributed_provider_identity":dict(provider_identity),
            "attribution_confirmation_timestamp":at,"provider_settings":settings or {},"asset_path":rel,"asset_sha256":metadata["sha256"],
            "downloaded_raw_path":rel,"raw_sha256":metadata["sha256"],"metadata":metadata,"completed_at":at}
        if production and entry["media_type"] == "IMAGE": attempt["production_image_postprocess_required"] = True
        entry["attempts"].append(attempt)
        if production and entry["media_type"] == "IMAGE":
            try: selected = _process_raw_image(paths, entry, attempt)
            except FlowImagePostprocessError as error:
                atomic_write_json(path, manifest); raise FlowError(error.failure_class, str(error)) from error
            selected["provenance"] = "EXACT_FLOW_RECOVERY"
        else:
            selected={"path":rel,"sha256":metadata["sha256"],"attempt":number,"metadata":metadata,"provenance":"EXACT_FLOW_RECOVERY",
                      "production_qc":"ENGINEERING_FIXTURE"}
            entry.update({"status":"SUCCEEDED","selected_asset":selected,"failure_class":None,"updated_at":at})
        atomic_write_json(path,manifest); return selected


def reuse_exact_flow_asset(runtime_root: Path | str, project_id: str, source_request_id: str,
                           target_request_id: str, *, attribution: str) -> dict:
    """Bind an exact prior Flow asset to a materially revised request.

    The source must be a successfully acquired, non-ambiguous attempt. The new
    request still returns to semantic and temporal QC; no prior approval is
    inherited.
    """
    if not isinstance(attribution, str) or not attribution.strip():
        raise FlowError("EXACT_ASSET_REUSE_ATTRIBUTION_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        requests = {item["request_id"]: item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]}
        target_request = requests.get(target_request_id)
        source_entry = next((item for item in manifest["requests"] if item.get("request_id") == source_request_id), None)
        source_selected = source_entry.get("selected_asset") if isinstance(source_entry, dict) else None
        if not target_request or not isinstance(source_selected, dict):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        source_attempt = next((item for item in source_entry.get("attempts", [])
                               if item.get("attempt") == source_selected.get("attempt")), None)
        if not isinstance(source_attempt, dict) or source_attempt.get("status") != "SUCCEEDED":
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        legacy_lineage = source_attempt.get("asset_sha256") == source_selected.get("sha256")
        processing = next((item for item in source_entry.get("postprocess_attempts", [])
                           if item.get("status") == "SUCCEEDED"
                           and item.get("source_provider_attempt") == source_attempt.get("attempt")
                           and item.get("source_sha256") == source_attempt.get("asset_sha256")
                           and item.get("output_sha256") == source_selected.get("sha256")), None)
        processed_lineage = (
            isinstance(processing, dict)
            and source_selected.get("source_provider_attempt") == source_attempt.get("attempt")
            and source_selected.get("source_sha256") == source_attempt.get("asset_sha256")
        )
        if not legacy_lineage and not processed_lineage:
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        try:
            raw_source = paths.artifact_path(source_attempt["asset_path"])
            raw_metadata = validate_video(raw_source) if source_entry.get("media_type") == "VIDEO" else validate_image(raw_source)
        except (KeyError, AssetValidationError):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        if raw_metadata["sha256"] != source_attempt.get("asset_sha256"):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        source = paths.artifact_path(source_selected["path"])
        if not source.is_file():
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        entry = next((item for item in manifest["requests"] if item.get("request_id") == target_request_id), None)
        if entry is None:
            entry = _entry(manifest, target_request)
        if entry is None or entry.get("status") not in {"PENDING", "NOT_DISPATCHED", "FAILED_RETRYABLE"}:
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        metadata = validate_video(source) if target_request["media_type"] == "VIDEO" else validate_image(source)
        if metadata["sha256"] != source_selected.get("sha256"):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        number = len(entry["attempts"]) + 1
        rel = f"assets/{target_request['media_type'].lower()}/{target_request_id}/exact_reuse_{number:03d}{source.suffix}"
        target = paths.artifact_path(rel); target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        source_lineage = {
            "source_request_id": source_request_id,
            "source_provider_attempt": source_attempt.get("attempt"),
            "source_raw_path": source_attempt.get("asset_path"),
            "source_raw_sha256": source_attempt.get("asset_sha256"),
            "source_selected_path": source_selected.get("path"),
            "source_selected_sha256": source_selected.get("sha256"),
            "lineage_kind": "RAW_TO_DERIVATIVE" if processed_lineage else "LEGACY_RAW_EQUALS_SELECTED",
        }
        attempt = {"attempt": number, "status": "SUCCEEDED", "dispatch_origin": "prior_exact_flow_asset_repair",
                   "source_request_id": source_request_id, "source_asset_sha256": metadata["sha256"],
                   "source_lineage": source_lineage,
                   "attribution_evidence": attribution.strip(), "attribution_state": "CONFIRMED",
                   "attribution_method": "exact_prior_confirmed_flow_asset",
                   "attribution_method_version": "exact-reuse/1.0.0",
                   "attribution_confirmation_timestamp": _now(),
                   "asset_path": rel, "asset_sha256": metadata["sha256"],
                   "metadata": metadata, "completed_at": _now()}
        entry["attempts"].append(attempt)
        entry.update({"status": "QC_PENDING", "failure_class": None, "updated_at": _now(),
                      "selected_asset": {"path": rel, "sha256": metadata["sha256"], "attempt": number,
                                         "metadata": metadata, "production_qc": "PENDING",
                                         "reuse_source_request_id": source_request_id,
                                         "source_lineage": source_lineage}})
        atomic_write_json(path, manifest)
        return entry["selected_asset"]


def _unresolved_flow_entry(entry: dict | None) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("status") in {
        SUPERSEDED_AMBIGUOUS_STATUS,
        ABANDONED_UNRESOLVED_STATUS,
        QC_REJECTED_ASSET_REPLACED_STATUS,
    }:
        return False
    if entry.get("status") in {"SUCCEEDED", "QC_PENDING"}:
        return False
    # A previous provider attempt without canonical positive no-dispatch proof
    # is a serial barrier; FAILED_RETRYABLE is never resubmission authority.
    if entry.get("attempts") and not _provider_generation_retry_authorized(entry):
        return True
    if entry.get("status") in UNRESOLVED_FLOW_STATES:
        return True
    if entry.get("failure_class") in UNRESOLVED_FLOW_FAILURES:
        return entry.get("status") not in {"SUCCEEDED", "QC_PENDING", "NOT_DISPATCHED"}
    attempt = entry.get("attempts", [])[-1] if entry.get("attempts") else None
    return isinstance(attempt, dict) and attempt.get("attribution_state") in {"UNCERTAIN", "AMBIGUOUS"}


def _first_unresolved(paths, project_id: str, requests: list[dict], entries: dict[str, dict]) -> tuple[dict, dict] | None:
    malformed = _first_invalid_request_replacement(paths, project_id, entries, requests)
    if malformed is not None:
        return malformed
    for request in requests:
        entry = entries.get(request.get("request_id"))
        if _unresolved_flow_entry(entry):
            return request, entry
    return None


def _provider_identity_history(manifest: dict, *, exclude_request_id: str | None = None,
                               exclude_attempt: int | None = None) -> list[dict]:
    """Collect provider identities already owned/quarantined by prior epochs."""
    identities = {}
    for entry in manifest.get("requests", []):
        for attempt in entry.get("attempts", []):
            if (entry.get("request_id") == exclude_request_id
                    and attempt.get("attempt") == exclude_attempt):
                continue
            settings = attempt.get("provider_settings", {}) if isinstance(attempt.get("provider_settings"), dict) else {}
            groups = [
                attempt.get("baseline_provider_identities"), settings.get("baseline_provider_identities"),
                attempt.get("candidate_identities"), settings.get("candidate_identities"),
                settings.get("quarantined_foreign_identities"),
            ]
            attributed = attempt.get("attributed_provider_identity") or settings.get("attributed_provider_identity")
            if isinstance(attributed, dict):
                groups.append([attributed])
            for group in groups:
                if not isinstance(group, list):
                    continue
                for item in group:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("asset_id") or item.get("identity") or item.get("card_id") or "")
                    if key:
                        identities[key] = item
    return list(identities.values())


def _confirm_executor_attribution(attempt: dict, generator: Any) -> None:
    """Require explicit live provenance; fixture adapters get an exact-return seam."""
    settings = getattr(generator, "last_settings", None)
    if isinstance(settings, dict) and isinstance(settings.get("provider_poll_evidence"), dict):
        # Import lazily to avoid the module-level service/live dependency cycle.
        from .live import ProviderPollEvidenceTimeline
        verified = ProviderPollEvidenceTimeline.verify_snapshot(settings["provider_poll_evidence"])
        if not verified.get("evidence_complete"):
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED")
        binding = ProviderPollEvidenceTimeline.verify_authoritative_binding(verified)
        if (settings.get("attribution_state") != binding.get("resulting_attribution_state")
                or settings.get("dispatch_confirmation_state") != binding.get("resulting_dispatch_state")
                or settings.get("dispatch_confirmation_signal") != binding.get("resulting_dispatch_signal")):
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "live authority does not match verified decision binding")
        attributed = settings.get("attributed_provider_identity")
        if (binding.get("resulting_attribution_state") == "CONFIRMED"
                and (not isinstance(attributed, dict)
                     or attributed.get("identity") != binding.get("durable_identity_used"))):
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "attribution identity is not bound to verified decision")
    if settings is None:
        confirmed_at = _now()
        attempt.update({
            "dispatch_confirmed": True,
            "dispatch_confirmation_state": "CONFIRMED",
            "dispatch_confirmation_signal": "executor_exact_result",
            "attribution_state": "CONFIRMED",
            "attribution_method": "executor_exact_destination",
            "attribution_method_version": "executor-contract/1.0.0",
            "attributed_provider_identity": {"identity": "executor:exact-destination"},
            "candidate_delta_count": 1,
            "candidate_identities": [{"identity": "executor:exact-destination"}],
            "attribution_confirmation_timestamp": confirmed_at,
        })
    if attempt.get("attribution_state") != "CONFIRMED":
        state = attempt.get("attribution_state")
        failure = "OUTPUT_ATTRIBUTION_AMBIGUOUS" if state == "AMBIGUOUS" else "OUTPUT_ATTRIBUTION_UNCERTAIN"
        raise FlowError(failure, "adapter returned bytes without confirmed request attribution")
    attempt.setdefault("attribution_events", []).append({
        "at": attempt.get("attribution_confirmation_timestamp") or _now(),
        "state": "CONFIRMED",
        "method": attempt.get("attribution_method"),
        "provider_identity": attempt.get("attributed_provider_identity"),
    })


def _finalize_attributed_result(paths, manifest: dict, entry: dict, request: dict,
                                attempt: dict, temporary: Path, source: Path) -> bool:
    """Validate/download lineage before any selected_asset can be created."""
    if attempt.get("attribution_state") != "CONFIRMED":
        raise FlowError("OUTPUT_ATTRIBUTION_UNCERTAIN")
    if not source.is_file():
        raise FlowError("ASSET_ACQUISITION_FAILED")
    if source.resolve() != temporary.resolve():
        shutil.copy2(source, temporary)
    production = request.get("execution_tier") == "STANDARD_PRODUCTION"
    metadata = validate_image(temporary) if request["media_type"] == "IMAGE" else validate_video(temporary)
    number = attempt["attempt"]
    raw_label = f"attempt_{number:03d}_raw" if production and request["media_type"] == "IMAGE" else f"attempt_{number:03d}"
    final_rel = f"assets/{request['media_type'].lower()}/{request['request_id']}/{raw_label}{temporary.suffix}"
    final_path = paths.artifact_path(final_rel)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temporary), final_path)
    attempt.update({
        "status": "SUCCEEDED", "completed_at": _now(), "asset_path": final_rel,
        "asset_sha256": metadata["sha256"], "downloaded_raw_path": final_rel,
        "raw_sha256": metadata["sha256"], "metadata": metadata,
    })
    attempt.pop("failure_class", None)
    attempt.pop("diagnostic", None)
    if production and request["media_type"] == "IMAGE":
        attempt["production_image_postprocess_required"] = True
        try:
            selected_asset = _process_raw_image(paths, entry, attempt)
        except FlowImagePostprocessError:
            selected_asset = None
    else:
        selected_asset = {
            "path": final_rel, "sha256": metadata["sha256"], "attempt": number,
            "metadata": metadata,
            "production_qc": "PENDING" if production else "ENGINEERING_FIXTURE",
        }
        entry.update({
            "status": "QC_PENDING" if production else "SUCCEEDED",
            "failure_class": None, "selected_asset": selected_asset, "updated_at": _now(),
        })
    if selected_asset is not None and production:
        duplicate = _find_duplicate_selection(paths, manifest, request, selected_asset["metadata"], entry)
        if duplicate is not None:
            entry.pop("selected_asset", None)
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_STALE_RESULT", "updated_at": _now()})
            entry.setdefault("stale_result_events", []).append({
                "detected_at": _now(), "candidate_path": selected_asset["path"],
                "candidate_sha256": selected_asset["sha256"],
                "matches_request_id": duplicate["request_id"],
            })
            selected_asset = None
    return selected_asset is not None


def _reconcile_unresolved(paths, project_id: str, manifest: dict, requests: list[dict], entries: dict[str, dict],
                          executor: "FlowExecutor") -> tuple[bool, str | None, int]:
    blocker = _first_unresolved(paths, project_id, requests, entries)
    if blocker is None:
        return True, None, 0
    request, entry = blocker
    attempt = entry.get("attempts", [])[-1] if entry.get("attempts") else None
    if not isinstance(attempt, dict):
        return False, request["request_id"], 0

    # A crash before the persisted provider boundary is the only restart case
    # proven locally.  Produce the same current-schema proof every downstream
    # retry/replay/queue consumer verifies.
    if entry.get("status") == "GENERATING" and _produce_crash_before_provider_setup_proof(attempt):
        event = {"at": _now(), "state": "PROVEN_PRE_DISPATCH_FAILURE",
                 "evidence": {"input_dispatched": False, "reason": "PROCESS_INTERRUPTED_BEFORE_PROVIDER_SETUP",
                              "canonical_no_dispatch_proof": True}}
        attempt.setdefault("reconciliation_events", []).append(event)
        attempt.update({"status": "NOT_DISPATCHED", "failure_class": "FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH",
                        "completed_at": event["at"]})
        entry.update({"status": "NOT_DISPATCHED", "failure_class": "FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH",
                      "updated_at": event["at"]})
        return True, None, 1

    temporary = paths.artifact_path(
        f"assets/attempts/{request['request_id']}/attempt_{attempt.get('attempt', 1):03d}/reconciled_provider_result."
        f"{'png' if request['media_type'] == 'IMAGE' else 'mp4'}"
    )
    temporary.parent.mkdir(parents=True, exist_ok=True)
    request_context = dict(request)
    request_context["_flow_provider_identity_history"] = _provider_identity_history(
        manifest, exclude_request_id=request["request_id"], exclude_attempt=attempt.get("attempt")
    )
    request_context["_flow_reference_paths"] = [
        str(paths.artifact_path(entries[dependency]["selected_asset"]["path"]))
        for dependency in request.get("depends_on", [])
        if dependency in entries and isinstance(entries[dependency].get("selected_asset"), dict)
    ]
    result = executor.reconcile_attempt(request_context, attempt, temporary)
    if not isinstance(result, dict):
        return False, request["request_id"], 0
    state = result.get("state")
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    event = {"at": _now(), "state": state, "prior_status": attempt.get("status"), "evidence": evidence}
    attempt.setdefault("reconciliation_events", []).append(event)
    entry.setdefault("reconciliation_events", []).append({
        "at": event["at"], "attempt": attempt.get("attempt"), "state": state,
    })
    if state == "PROVEN_PRE_DISPATCH_FAILURE" and evidence.get("input_dispatched") is False:
        recovered = dict(attempt)
        recovered.update({"status": "NOT_DISPATCHED", "failure_class": "FLOW_RECONCILED_PRE_DISPATCH_FAILURE",
                          "dispatch_confirmed": False, "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                          "attribution_state": "NOT_ATTEMPTED",
                          "provider_settings": {"activation": {"input_dispatched": False,
                                                                    "proof": "RECONCILIATION_PROVEN_PRE_DISPATCH_FAILURE"}},
                          "completed_at": event["at"]})
        if not canonical_no_dispatch_proof(recovered):
            event["state"] = "PROVEN_PRE_DISPATCH_FAILURE_CANONICAL_REJECTED"
            return False, request["request_id"], 1
        attempt.update(recovered)
        entry.update({"status": "NOT_DISPATCHED", "failure_class": "FLOW_RECONCILED_PRE_DISPATCH_FAILURE",
                      "updated_at": event["at"]})
        return True, None, 1
    if state == "CONFIRMED_OUTPUT" and evidence.get("attribution_state") == "CONFIRMED":
        attempt.update(evidence)
        attempt["dispatch_confirmed"] = True
        attempt.setdefault("attribution_events", []).append({
            "at": evidence.get("attribution_confirmation_timestamp") or event["at"],
            "state": "CONFIRMED", "method": evidence.get("attribution_method"),
            "provider_identity": evidence.get("attributed_provider_identity"),
        })
        source = Path(result.get("path") or temporary)
        _finalize_attributed_result(paths, manifest, entry, request, attempt, temporary, source)
        return True, None, 1
    if state == "CONFIRMED_DISPATCH":
        attempt["dispatch_confirmed"] = True
        entry.update({"status": "AMBIGUOUS", "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN", "updated_at": event["at"]})
    return False, request["request_id"], 1

@dataclass
class FlowExecutor:
    """A live adapter supplies generate(); it must acquire to the given temp file."""
    capabilities: Any
    generate: Any

    def run(self, request, refs, temporary: Path):
        self.capabilities.require(request["media_type"], bool(refs))
        return self.generate(request, refs, temporary)

    def reconcile_attempt(self, request, attempt, temporary: Path):
        reconcile = getattr(self.generate, "reconcile", None)
        return reconcile(request, attempt, temporary) if callable(reconcile) else None


def reconcile_unresolved_flow_attempt(runtime_root: Path | str, project_id: str,
                                      request_id: str, *, executor: FlowExecutor) -> dict:
    """Inspect one unresolved attempt without activating Flow.

    Only the earliest barrier may be resolved. A later unresolved attempt may
    still receive an append-only REMAINS_AMBIGUOUS observation so preserved
    production evidence can be audited without changing queue order.
    """
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
        entries = {entry["request_id"]: entry for entry in manifest["requests"]}
        request = next((item for item in requests if item.get("request_id") == request_id), None)
        entry = entries.get(request_id)
        if not request or not _unresolved_flow_entry(entry):
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        earliest = _first_unresolved(paths, project_id, requests, entries)
        if earliest and earliest[0]["request_id"] == request_id:
            released, blocked_request_id, count = _reconcile_unresolved(
                paths, project_id, manifest, requests, entries, executor
            )
            if count:
                atomic_write_json(path, manifest)
            return {"request_id": request_id, "released": released,
                    "blocked_request_id": blocked_request_id, "reconciliations": count,
                    "status": entry.get("status"), "failure_class": entry.get("failure_class")}

        attempt = entry.get("attempts", [])[-1] if entry.get("attempts") else None
        if not isinstance(attempt, dict):
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        temporary = paths.artifact_path(
            f"assets/attempts/{request_id}/attempt_{attempt.get('attempt', 1):03d}/reconciliation_inspection."
            f"{'png' if request['media_type'] == 'IMAGE' else 'mp4'}"
        )
        request_context = dict(request)
        request_context["_flow_provider_identity_history"] = _provider_identity_history(
            manifest, exclude_request_id=request_id, exclude_attempt=attempt.get("attempt")
        )
        request_context["_flow_reference_paths"] = [
            str(paths.artifact_path(entries[dependency]["selected_asset"]["path"]))
            for dependency in request.get("depends_on", [])
            if dependency in entries and isinstance(entries[dependency].get("selected_asset"), dict)
        ]
        result = executor.reconcile_attempt(request_context, attempt, temporary)
        if not isinstance(result, dict) or result.get("state") != "REMAINS_AMBIGUOUS":
            raise FlowError("GENERATION_RECONCILIATION_ORDER_BLOCKED")
        event = {"at": _now(), "state": "REMAINS_AMBIGUOUS", "prior_status": attempt.get("status"),
                 "evidence": result.get("evidence") if isinstance(result.get("evidence"), dict) else {}}
        attempt.setdefault("reconciliation_events", []).append(event)
        entry.setdefault("reconciliation_events", []).append({
            "at": event["at"], "attempt": attempt.get("attempt"), "state": event["state"],
        })
        atomic_write_json(path, manifest)
        return {"request_id": request_id, "released": False,
                "blocked_request_id": earliest[0]["request_id"] if earliest else request_id,
                "reconciliations": 1, "status": entry.get("status"),
                "failure_class": entry.get("failure_class")}

def execute_generation(runtime_root: Path | str, project_id: str, *, executor: FlowExecutor, execute: bool = False,
                       request_ids: set[str] | None = None, production_batch: bool = False,
                       max_requests: int | None = None) -> dict:
    """Run the bounded vertical slice while preserving every provider attempt."""
    if not execute: raise FlowError("EXECUTION_CONFIRMATION_REQUIRED", "pass explicit execute-generation permission")
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    review = read_json(paths.artifact_path("output/review_state.json"))
    if review.get("plan_approval", {}).get("status") != "APPROVED": raise FlowError("PLAN_APPROVAL_REQUIRED")
    storage=config.settings.get("storage",{})
    if not isinstance(storage,dict): raise FlowError("STORAGE_SETTINGS_INVALID")
    ensure_free_space(paths.runtime.temp,minimum_free_bytes=int(storage.get("minimum_free_bytes",64*1024*1024)))
    with ProjectLock(paths.runtime, project_id):
        # Complete every prepared request-graph replacement before selecting
        # executable requests. A partially published old epoch is never run.
        _recover_pending_request_replacements(paths, project_id)
        requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
        selected = [r for r in requests if request_ids is None or r["request_id"] in request_ids]
        if any(r.get("media_type") == "VIDEO" and not isinstance(r.get("motion_risk_analysis"), dict) for r in selected):
            raise FlowError("MOTION_PLAN_REQUIRED", "every VIDEO request requires motion-risk analysis")
        if max_requests is not None:
            if max_requests < 1: raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "max_requests must be positive")
            selected = selected[:max_requests]
        if not production_batch and len(selected) > 4: raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "bounded execution permits at most four selected requests")
        kinds = [(r.get("purpose"), r.get("media_type")) for r in selected]
        if (not production_batch and any(kinds.count(kind) > 1 for kind in kinds)) or any(kind not in {("REFERENCE", "IMAGE"), ("SHOT", "IMAGE"), ("SHOT", "VIDEO"), ("THUMBNAIL", "IMAGE")} for kind in kinds):
            raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "bounded execution permits one reference image, shot image, shot video, and thumbnail")
        path, manifest = _manifest(paths, project_id); entries = {e["request_id"]:e for e in manifest["requests"]}; submissions = 0
        control_path = paths.artifact_path("output/execution_control.json")
        paused = False; blocked_request_id = None; reconciliation_count = 0
        malformed = _first_invalid_request_replacement(paths, project_id, entries, requests)
        if malformed is not None:
            return {"selected": len(selected), "new_submissions": 0, "paused": False,
                    "blocked": True, "blocked_request_id": malformed[0]["request_id"],
                    "attention": "FLOW_GENERATION_RECONCILIATION_REQUIRED", "reconciliations": 0,
                    "manifest": "output/generation_manifest.json"}
        # A preserved raw production image is recoverable without a provider
        # activation.  Do that local-only work before asking the reconciliation
        # adapter about an unresolved provider attempt; its failure status is
        # never authority to cross the Generate boundary again.
        initial_blocker = _first_unresolved(paths, project_id, requests, entries)
        if (initial_blocker is not None
                and _repair_local_image(paths, initial_blocker[1], initial_blocker[0])):
            atomic_write_json(path, manifest)
            entries[initial_blocker[0]["request_id"]] = initial_blocker[1]
        released, blocked_request_id, reconciled = _reconcile_unresolved(
            paths, project_id, manifest, requests, entries, executor
        )
        reconciliation_count += reconciled
        if reconciled:
            atomic_write_json(path, manifest)
            entries = {entry["request_id"]: entry for entry in manifest["requests"]}
        if not released:
            return {
                "selected": len(selected), "new_submissions": 0, "paused": False,
                "blocked": True, "blocked_request_id": blocked_request_id,
                "attention": "FLOW_GENERATION_RECONCILIATION_REQUIRED",
                "reconciliations": reconciliation_count,
                "manifest": "output/generation_manifest.json",
            }
        for request in selected:
            try: paused = read_json(control_path).get("pause_requested") is True
            except Exception: paused = False
            if paused: break
            blocker = _first_unresolved(paths, project_id, requests, entries)
            if blocker is not None:
                # A preserved raw production image can be repaired locally
                # without invoking Generate.  Give that separate recovery path
                # precedence over the provider-resubmission barrier only for
                # the blocked request itself.
                if blocker[0].get("request_id") == request.get("request_id") and _repair_local_image(paths, blocker[1], request):
                    atomic_write_json(path, manifest)
                    entries[request["request_id"]] = blocker[1]
                    continue
                blocked_request_id = blocker[0]["request_id"]
                break
            if request.get("media_type") == "IMAGE" and request.get("output_count", 1) != 1:
                raise FlowError("IMAGE_OUTPUT_COUNT_MISMATCH")
            entry = _entry(manifest, request)
            if entry is None: continue # identity changed: retain old provenance, a planner-generated id is required
            if entry.get("status") == "SUCCEEDED" and _valid_selected(paths, entry): continue
            if entry.get("status") == "QC_PENDING" and _valid_selected(paths, entry): continue
            if _repair_local_image(paths, entry, request):
                atomic_write_json(path, manifest); entries[request["request_id"]] = entry
                continue
            if entry.get("status") == "AMBIGUOUS":
                blocked_request_id = request["request_id"]
                break
            if entry.get("status") in (FINAL - {"SUCCEEDED"}): continue
            if not _provider_generation_retry_authorized(entry):
                # This is intentionally independent of status/failure labels.
                # An unproven prior attempt cannot reach executor.run again.
                blocked_request_id = request["request_id"]
                break
            if not _runnable(request, entries): continue
            entry["reference_asset_hashes"] = [entries[dep]["selected_asset"]["sha256"] for dep in request.get("depends_on", [])]
            attempt_number = len(entry["attempts"]) + 1
            # Ambiguous/retryable attempts are append-only.  A finite higher
            # ceiling prevents loops while accepted-goal policy permits recovery.
            # The default permits an evidence-led correction after an initial
            # bounded retry cycle; it is a stop-loss, never a cost ceiling.
            maximum = int(config.settings.get("flow", {}).get("max_attempts", 12))
            if attempt_number > maximum:
                entry["status"] = "FAILED_PERMANENT"; entry["failure_class"]="FLOW_RETRY_STOP_LOSS"
                entry["updated_at"]=_now(); atomic_write_json(path,manifest); continue
            attempt = {"attempt":attempt_number, "status":"SUBMITTED", "started_at":_now(), "provider_mode":request["media_type"], "dispatch_confirmed":False,
                       "provider_execution_state":"NOT_STARTED"}; entry["attempts"].append(attempt); entry["status"]="GENERATING"; atomic_write_json(path, manifest)
            temp = paths.artifact_path(f"assets/attempts/{request['request_id']}/attempt_{attempt_number:03d}/provider_result.{ 'png' if request['media_type'] == 'IMAGE' else 'mp4'}")
            # Provider adapters receive concrete local files, never manifest-
            # relative paths.  In particular CDP's file-input API silently
            # cannot attach a path relative to the process working directory.
            refs = [str(paths.artifact_path(entries[d]["selected_asset"]["path"])) for d in request.get("depends_on", [])]
            try:
                temp.parent.mkdir(parents=True, exist_ok=True)
                request_context = dict(request)
                request_context["_flow_provider_identity_history"] = _provider_identity_history(
                    manifest, exclude_request_id=request["request_id"], exclude_attempt=attempt_number
                )
                request_context["_flow_reference_paths"] = list(refs)
                # Persist this marker before the only call that can reach the
                # provider.  Recovery may prove no dispatch only while the
                # durable state remains NOT_STARTED.
                attempt["provider_execution_state"] = "PROVIDER_BOUNDARY_ENTERED"
                attempt["provider_boundary_entered_at"] = _now()
                entry["provider_submissions"] = int(entry.get("provider_submissions", 0)) + 1
                atomic_write_json(path, manifest)
                result = executor.run(request_context, refs, temp)
                attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", True))
                _record_attempt_provider_state(attempt, executor.generate)
                _confirm_executor_attribution(attempt, executor.generate)
                source = Path(result or temp)
                if _finalize_attributed_result(paths, manifest, entry, request, attempt, temp, source):
                    submissions += 1
            except (FlowError, FlowSessionError) as error:
                attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", attempt.get("dispatch_confirmed", False)))
                _record_attempt_provider_state(attempt, executor.generate)
                safe_pre_dispatch_candidate = error.failure_class in {
                    "FLOW_NOT_DISPATCHED", "FLOW_PRE_DISPATCH_ACTIVATION_FAILED",
                    "OUTPUT_ATTRIBUTION_NOT_QUIESCENT",
                }
                if safe_pre_dispatch_candidate and canonical_no_dispatch_proof(attempt):
                    state = "NOT_DISPATCHED"
                elif safe_pre_dispatch_candidate or error.failure_class in UNRESOLVED_FLOW_FAILURES:
                    # Error labels and a missing job ID are not dispatch proof.
                    # Preserve a serial barrier until persisted evidence resolves it.
                    state = "AMBIGUOUS"
                elif error.failure_class == "FLOW_AUTH_REQUIRED":
                    state = "AUTH_REQUIRED"
                elif error.failure_class in {"FLOW_PROJECT_MISMATCH", "FLOW_CAPABILITY_UNAVAILABLE", "FLOW_REFERENCE_VIDEO_CAPABILITY_BLOCKED"}:
                    state = "FAILED_PERMANENT"
                else:
                    state = "FAILED_RETRYABLE"
                attempt.update({"status":state, "failure_class":error.failure_class, "diagnostic":str(error), "completed_at":_now()}); entry.update({"status":state, "failure_class":error.failure_class, "updated_at":_now()})
            except AssetValidationError as error:
                attempt.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "completed_at":_now()}); entry.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "updated_at":_now()})
            atomic_write_json(path, manifest); entries[request["request_id"]] = entry
            if _unresolved_flow_entry(entry):
                blocked_request_id = request["request_id"]
                break
    return {"selected":len(selected), "new_submissions":submissions, "paused":paused,
            "blocked":blocked_request_id is not None, "blocked_request_id":blocked_request_id,
            "attention":"FLOW_GENERATION_RECONCILIATION_REQUIRED" if blocked_request_id else None,
            "reconciliations":reconciliation_count, "manifest":"output/generation_manifest.json"}
