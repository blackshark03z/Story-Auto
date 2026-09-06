"""Append-only Flow generation orchestration with provider-independent request ordering."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import hashlib
import gzip
import io
import json
import copy
import os
import re
import shutil
import uuid

from story_auto.core.artifacts import atomic_write_bytes, atomic_write_json, read_json, sha256_file
from story_auto.core.planning.qc_corrective import (
    FULL_REPLAN,
    QCCorrectiveReplanError,
    SEMANTIC_ONLY,
    compile_qc_corrected_request,
    plan_qc_corrective_intent,
)
from story_auto.core.planning.service import PlanningError, validate_generation_requests
from story_auto.core.gemini_qc import (MOTION_PLAN_VERSION, TERMINAL_TEMPORAL_FAILURES,
                                       plan_motion, sample_dense_frames, temporal_video_qc)
from story_auto.core.project import (AUTO_ACCEPT, MANUAL_REVIEW, RuntimeLayout, effective_qc_policy,
                                     load_project)
from story_auto.core.project.lock import ProjectLock
from story_auto.core.resources import ensure_free_space
from story_auto.core.visual.recovery import (
    AttemptOutcome,
    DispatchCertainty,
    FailureFamily,
    RecoveryInput,
    RecoveryAction,
    evaluate_recovery,
)
from story_auto.core.visual.recovery_executor import (
    FlowSessionSingleFlight,
    RecoveryExecutionGate,
    RecoveryRetryTiming,
)
from story_auto.core.render import MediaError, derive_trim_retime_video
from story_auto.core.visual import (
    CAPTION_SAFE_PROMPT_VERSION,
    NATURALNESS_QC_FIELDS,
    MediaQualityError,
    ambient_prompt_directive,
    caption_safe_composition_intent,
    caption_safe_effective_prompt,
    compile_ambient_image_prompt,
    default_visual_policy,
    validate_production_qc,
)
from story_auto.providers.llm import GeminiReasoningRouter
from story_auto.providers.llm.gemini import LLMMedia
from .postprocess import (
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    VIDEO_PROCESSOR_NAME,
    VIDEO_PROCESSOR_VERSION,
    FlowImagePostprocessError,
    FlowVideoPostprocessError,
    process_flow_image,
    process_flow_video,
    profile_evidence,
)
from .validation import AssetValidationError, validate_image, validate_video
from .session import FlowSessionError
from .terminal_evidence import build_terminal_evidence


_transaction_read_cache: ContextVar[dict[object, Any] | None] = ContextVar(
    "flow_transaction_read_cache", default=None)


@contextmanager
def _transaction_read_scope():
    """Reuse already-validated immutable transaction payloads in one operation only."""
    existing = _transaction_read_cache.get()
    if existing is not None:
        yield existing
        return
    token = _transaction_read_cache.set({})
    try:
        yield _transaction_read_cache.get()
    finally:
        _transaction_read_cache.reset(token)


def _prepared_transaction_sha256(transaction: dict) -> str:
    """Hash a validated transaction once per validation operation."""
    cache = _transaction_read_cache.get()
    cache_key = ("prepared_sha256", id(transaction))
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    value = _json_sha256(transaction)
    if cache is not None:
        cache[cache_key] = value
    return value

MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
AUTOMATIC_IMAGE_QC_VERSION = "story-auto-automatic-image-qc/1.0.0"
AUTOMATIC_IMAGE_QC_SCHEMA = {
    "type": "object",
    "required": ["results", "visible_provider_watermark", "alignment_classification",
                 "confidence", "observed", "contradictions"],
    "properties": {
        "results": {
            "type": "object",
            "required": list(NATURALNESS_QC_FIELDS),
            "properties": {
                field: {"type": "string", "enum": ["PASS", "FAIL", "NOT_APPLICABLE"]}
                for field in NATURALNESS_QC_FIELDS
            },
        },
        "visible_provider_watermark": {"type": "boolean"},
        "alignment_classification": {
            "type": "string",
            "enum": ["PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC",
                     "FAIL_MISMATCH", "UNCERTAIN"],
        },
        "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]},
        "observed": {"type": "string"},
        "contradictions": {"type": "array", "items": {"type": "string"}},
    },
}
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
SESSION_PREPARATION_FAILURES = {
    "FLOW_REFERENCE_UPLOAD_FAILED", "FLOW_CDP_UNAVAILABLE",
    "FLOW_CDP_COMMAND_TIMEOUT", "FLOW_UI_CHANGED", "FLOW_GENERATE_DISABLED",
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
MAX_CREATIVE_CORRECTION_EPOCHS = 3
SEMANTIC_RESET_TRANSACTION_SCHEMA = "story-auto-semantic-reset-transaction/1.0.0"
SEMANTIC_RESET_PENDING_STATUS = "SEMANTIC_RESET_PENDING"
SEMANTIC_RESET_EXHAUSTED_STATUS = "SEMANTIC_RESET_EXHAUSTED"
SEMANTIC_RESET_REASON = "CORRECTION_CHAIN_EXHAUSTED_SEMANTIC_RESET"
MAX_SEMANTIC_RESETS_PER_LOGICAL_VISUAL = 1
SCENE_GEOMETRY_CONTRACT_VERSION = "story-auto-scene-geometry/1.0.0"
CREATIVE_CORRECTION_FULL_REPLAN_VERSION = "story-auto-creative-correction-full-replan/1.0.0"
QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA = "story-auto-qc-corrective-replan-transaction/1.0.0"
QC_CORRECTIVE_REPLANNED_STATUS = "QC_CORRECTIVE_REPLANNED"
QC_CORRECTIVE_REPLAN_REASON = "QC_CORRECTIVE_REPLAN"
QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA = "story-auto-qc-corrective-pre-dispatch-supersession-transaction/1.0.0"
QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS = "QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED"
QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON = "QC_CORRECTIVE_PRE_DISPATCH_REFERENCE_POLICY_SUPERSESSION"
TRANSACTION_ARCHIVE_SCHEMA = "story-auto-transaction-archive/1.0.0"
# Flow currently accepts a single reference upload.  Corrective planning must
# preserve that provider contract rather than letting dependency ordering choose
# the effective visual semantics.
FLOW_REFERENCE_CAPACITY = 1
CANONICAL_REPLACEMENT_PARENT_STATUSES = {
    SUPERSEDED_AMBIGUOUS_STATUS,
    ABANDONED_UNRESOLVED_STATUS,
    QC_REJECTED_ASSET_REPLACED_STATUS,
    SEMANTIC_RESET_PENDING_STATUS,
    QC_CORRECTIVE_REPLANNED_STATUS,
    QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS,
}
PRUNABLE_TERMINAL_MEDIA_STATUSES = {
    QC_REJECTED_ASSET_REPLACED_STATUS,
    QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS,
    QC_CORRECTIVE_REPLANNED_STATUS,
    SUPERSEDED_AMBIGUOUS_STATUS,
    ABANDONED_UNRESOLVED_STATUS,
    "FAILED_PERMANENT",
    "FAILED_RETRYABLE",
}
TERMINAL_MEDIA_TOMBSTONE_SCHEMA = "story-auto-terminal-media-tombstone/1.0.0"
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
LOCAL_VIDEO_FAILURES = {
    "FLOW_VIDEO_POSTPROCESS_FAILED",
    "FLOW_VIDEO_POSTPROCESS_SOURCE_INVALID",
    "FLOW_VIDEO_POSTPROCESS_UNSUPPORTED_GEOMETRY",
    "FLOW_VIDEO_POSTPROCESS_DIMENSIONS_CHANGED",
    "FLOW_VIDEO_POSTPROCESS_DURATION_CHANGED",
    "FLOW_VIDEO_POSTPROCESS_OUTPUT_CONFLICT",
    "FLOW_VIDEO_DERIVATIVE_INVALID",
}
TEMPORAL_SALVAGE_EVENT = "LOCAL_TEMPORAL_TRIM_RETIME"
TEMPORAL_SALVAGE_MAX_SLOWDOWN = 1.08
VIDEO_MARK_REMOVAL_EVENT = "LOCAL_FLOW_VIDEO_MARK_REMOVAL"
FALSE_POSITIVE_PRODUCTION_QC_FAILURES = {
    "NATURALNESS_QC_REJECTED",
    "VISIBLE_PROVIDER_WATERMARK",
    "VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED",
}

class FlowError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = ""):
        self.failure_class = failure_class; super().__init__(failure_class + (f": {detail}" if detail else ""))

def _now(): return datetime.now(timezone.utc).isoformat()


def _persisted_provider_settings(settings: Any) -> Any:
    """Keep detailed poll evidence external and the attempt operationally small.

    ``FlowLiveGenerator.last_settings`` deliberately exposes convenient
    projections of a poll snapshot to the live execution path.  Persisting
    those projections alongside the snapshot multiplied a single immutable
    evidence record in every completed attempt.  Once a content-addressed
    external reference exists, the manifest retains only that reference and
    compact decision summaries.  Fixtures and legacy attempts without a
    verified external reference keep their embedded snapshot fail-closed.
    """
    if not isinstance(settings, dict):
        return settings
    persisted = copy.deepcopy(settings)
    evidence_ref = persisted.get("provider_poll_evidence_ref")
    if isinstance(evidence_ref, dict) and isinstance(evidence_ref.get("sha256"), str):
        persisted.pop("provider_poll_evidence", None)
        persisted.pop("provider_poll_decision_bindings", None)
        persisted.pop("provider_poll_timeline", None)
    elif isinstance(persisted.get("provider_poll_evidence"), dict):
        persisted.pop("provider_poll_decision_bindings", None)
        persisted.pop("provider_poll_timeline", None)
    return persisted


def _record_attempt_provider_state(attempt: dict, generator: Any) -> None:
    settings = getattr(generator, "last_settings", None)
    attempt["provider_settings"] = _persisted_provider_settings(settings)
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
        "provider_poll_evidence_ref": settings.get("provider_poll_evidence_ref"),
        "provider_surface_extractor_version": settings.get("provider_surface_extractor_version"),
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
    })
def _manifest(paths, project_id):
    path = paths.artifact_path("output/generation_manifest.json")
    if not path.exists(): return path, {"schema_version": MANIFEST_VERSION, "project_id": project_id, "requests": []}
    try:
        data = read_json(path)
        if data.get("schema_version") != MANIFEST_VERSION or data.get("project_id") != project_id or not isinstance(data.get("requests"), list): raise ValueError()
        return path, data
    except Exception as error: raise FlowError("GENERATION_MANIFEST_INVALID") from error


def _external_poll_evidence_path(paths, request_id: str, attempt: dict, reference: dict) -> Path:
    if reference.get("path_scope") != "ATTEMPT_DIRECTORY":
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "unsupported evidence path scope")
    name = reference.get("path")
    if (not isinstance(name, str) or not name or Path(name).name != name
            or "/" in name or "\\" in name):
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "invalid evidence artifact name")
    number = attempt.get("attempt")
    if not isinstance(number, int) or number < 1:
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "invalid attempt evidence identity")
    return paths.artifact_path(
        f"assets/attempts/{request_id}/attempt_{number:03d}/{name}"
    )


def _hydrate_attempt_external_poll_evidence(paths, request_id: str, attempt: dict) -> dict:
    """Return an in-memory attempt whose external evidence is hash verified."""
    hydrated = copy.deepcopy(attempt)
    settings = hydrated.get("provider_settings")
    if not isinstance(settings, dict) or isinstance(settings.get("provider_poll_evidence"), dict):
        return hydrated
    reference = settings.get("provider_poll_evidence_ref")
    if not isinstance(reference, dict):
        return hydrated
    path = _external_poll_evidence_path(paths, request_id, hydrated, reference)
    expected_sha = reference.get("sha256")
    if (not path.is_file() or not isinstance(expected_sha, str)
            or sha256_file(path) != expected_sha):
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "external evidence is missing or corrupt")
    try:
        from .live import ProviderPollEvidenceTimeline
        snapshot = read_json(path)
        verified = ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
    except Exception as error:
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "external evidence failed verification") from error
    if (reference.get("schema_version") != snapshot.get("schema_version")
            or reference.get("evidence_head_sha256") != snapshot.get("evidence_head_sha256")
            or reference.get("timeline_sha256") != snapshot.get("timeline_sha256")
            or reference.get("observation_count") != verified.get("observation_count")):
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "external evidence reference does not match")
    settings["provider_poll_evidence"] = snapshot
    return hydrated


def _verified_embedded_poll_evidence_reference(paths, request_id: str, attempt: dict) -> dict | None:
    settings = attempt.get("provider_settings")
    snapshot = settings.get("provider_poll_evidence") if isinstance(settings, dict) else None
    if not isinstance(snapshot, dict):
        return None
    number = attempt.get("attempt")
    if not isinstance(number, int) or number < 1:
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "invalid embedded evidence attempt")
    path = paths.artifact_path(
        f"assets/attempts/{request_id}/attempt_{number:03d}/provider_poll_evidence.json"
    )
    if not path.is_file():
        # Keep the embedded snapshot in the manifest when no independently
        # durable artifact exists.
        return None
    from .live import POLL_EVIDENCE_VERSION, ProviderPollEvidenceTimeline
    verified_embedded = ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
    persisted = read_json(path)
    verified_persisted = ProviderPollEvidenceTimeline.verify_snapshot(persisted)
    if (verified_embedded.get("timeline_sha256") != verified_persisted.get("timeline_sha256")
            or snapshot.get("evidence_head_sha256") != persisted.get("evidence_head_sha256")):
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "embedded evidence artifact differs")
    return {
        "schema_version": persisted.get("schema_version"),
        "path_scope": "ATTEMPT_DIRECTORY",
        "path": path.name,
        "sha256": sha256_file(path),
        "evidence_head_sha256": persisted.get("evidence_head_sha256"),
        "timeline_sha256": persisted.get("timeline_sha256"),
        "observation_count": persisted.get("observation_count"),
        "terminal_state": persisted.get("terminal_state"),
        "evidence_complete": persisted.get("evidence_complete"),
        "legacy_embedded_externalized": persisted.get("schema_version") != POLL_EVIDENCE_VERSION,
    }


def _append_poll_evidence_history(attempt: dict, reference: dict | None) -> None:
    if not isinstance(reference, dict):
        return
    history = attempt.setdefault("provider_poll_evidence_history", [])
    if not isinstance(history, list):
        raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "poll evidence history is malformed")
    if not any(
        isinstance(item, dict) and item.get("sha256") == reference.get("sha256")
        for item in history
    ):
        history.append(copy.deepcopy(reference))


def externalize_legacy_poll_evidence(runtime_root: Path | str, project_id: str) -> dict:
    """Externalize only one project's verified embedded evidence.

    Legacy source artifacts are read and hashed but never rewritten.  A compact
    sidecar is generated, verified, and content-bound before its embedded copy
    is removed from the operational manifest.
    """
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest_path, manifest = _manifest(paths, project_id)
        before_size = manifest_path.stat().st_size if manifest_path.is_file() else 0
        prepared = []
        prepared_history = []
        from .live import POLL_EVIDENCE_VERSION, ProviderPollEvidenceTimeline

        for entry in manifest.get("requests", []):
            request_id = entry.get("request_id")
            if not isinstance(request_id, str):
                continue
            for attempt in entry.get("attempts", []):
                if not isinstance(attempt, dict):
                    continue
                settings = attempt.get("provider_settings")
                if not isinstance(settings, dict):
                    continue
                embedded = settings.get("provider_poll_evidence")
                if not isinstance(embedded, dict):
                    number = attempt.get("attempt")
                    current_reference = settings.get("provider_poll_evidence_ref")
                    history = attempt.get("provider_poll_evidence_history", [])
                    source_path = paths.artifact_path(
                        f"assets/attempts/{request_id}/attempt_{number:03d}/provider_poll_evidence.json"
                    ) if isinstance(number, int) and number > 0 else None
                    source_already_bound = (
                        isinstance(current_reference, dict)
                        and current_reference.get("path") == "provider_poll_evidence.json"
                    ) or any(
                        isinstance(item, dict) and (
                            item.get("path") == "provider_poll_evidence.json"
                            or (isinstance(item.get("legacy_source"), dict)
                                and item["legacy_source"].get("path") == "provider_poll_evidence.json")
                        )
                        for item in (history if isinstance(history, list) else [])
                    )
                    if source_path is None or not source_path.is_file() or source_already_bound:
                        continue
                    source_sha = sha256_file(source_path)
                    source_snapshot = read_json(source_path)
                    ProviderPollEvidenceTimeline.verify_snapshot(source_snapshot)
                    compact_path = source_path
                    compact_snapshot = source_snapshot
                    if source_snapshot.get("schema_version") != POLL_EVIDENCE_VERSION:
                        compact_path = source_path.with_name("provider_poll_evidence.compact.json")
                        compact_snapshot = ProviderPollEvidenceTimeline.compact_legacy_snapshot(source_snapshot)
                        atomic_write_json(compact_path, compact_snapshot)
                    ProviderPollEvidenceTimeline.verify_snapshot(read_json(compact_path))
                    history_reference = {
                        "schema_version": compact_snapshot["schema_version"],
                        "path_scope": "ATTEMPT_DIRECTORY",
                        "path": compact_path.name,
                        "sha256": sha256_file(compact_path),
                        "evidence_head_sha256": compact_snapshot["evidence_head_sha256"],
                        "timeline_sha256": compact_snapshot["timeline_sha256"],
                        "observation_count": compact_snapshot["observation_count"],
                        "terminal_state": compact_snapshot.get("terminal_state"),
                        "evidence_complete": compact_snapshot.get("evidence_complete"),
                    }
                    if compact_path != source_path:
                        history_reference["legacy_source"] = {
                            "schema_version": source_snapshot.get("schema_version"),
                            "path_scope": "ATTEMPT_DIRECTORY",
                            "path": source_path.name,
                            "sha256": source_sha,
                            "evidence_head_sha256": source_snapshot.get("evidence_head_sha256"),
                        }
                    prepared_history.append((attempt, history_reference, source_path, source_sha))
                    continue
                verified_embedded = ProviderPollEvidenceTimeline.verify_snapshot(embedded)
                number = attempt.get("attempt")
                if not isinstance(number, int) or number < 1:
                    raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "invalid legacy attempt identity")
                source_path = paths.artifact_path(
                    f"assets/attempts/{request_id}/attempt_{number:03d}/provider_poll_evidence.json"
                )
                if not source_path.is_file():
                    raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "legacy evidence artifact is missing")
                source_sha = sha256_file(source_path)
                source_snapshot = read_json(source_path)
                verified_source = ProviderPollEvidenceTimeline.verify_snapshot(source_snapshot)
                if (verified_source.get("timeline_sha256") != verified_embedded.get("timeline_sha256")
                        or source_snapshot.get("evidence_head_sha256") != embedded.get("evidence_head_sha256")):
                    raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "embedded and external legacy evidence differ")

                if source_snapshot.get("schema_version") == POLL_EVIDENCE_VERSION:
                    compact_path = source_path
                    compact_snapshot = source_snapshot
                else:
                    compact_path = source_path.with_name("provider_poll_evidence.compact.json")
                    compact_snapshot = ProviderPollEvidenceTimeline.compact_legacy_snapshot(source_snapshot)
                    atomic_write_json(compact_path, compact_snapshot)
                ProviderPollEvidenceTimeline.verify_snapshot(read_json(compact_path))
                if sha256_file(source_path) != source_sha:
                    raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "legacy evidence source changed")
                reference = {
                    "schema_version": compact_snapshot["schema_version"],
                    "path_scope": "ATTEMPT_DIRECTORY",
                    "path": compact_path.name,
                    "sha256": sha256_file(compact_path),
                    "evidence_head_sha256": compact_snapshot["evidence_head_sha256"],
                    "timeline_sha256": compact_snapshot["timeline_sha256"],
                    "observation_count": compact_snapshot["observation_count"],
                    "terminal_state": compact_snapshot.get("terminal_state"),
                    "evidence_complete": compact_snapshot.get("evidence_complete"),
                    "dispatch_state": attempt.get("dispatch_confirmation_state"),
                    "attribution_state": attempt.get("attribution_state"),
                }
                if compact_path != source_path:
                    reference["legacy_source"] = {
                        "schema_version": source_snapshot.get("schema_version"),
                        "path_scope": "ATTEMPT_DIRECTORY",
                        "path": source_path.name,
                        "sha256": source_sha,
                        "evidence_head_sha256": source_snapshot.get("evidence_head_sha256"),
                    }
                prepared.append((attempt, settings, reference, source_path, source_sha))

        for attempt, settings, reference, source_path, source_sha in prepared:
            settings["provider_poll_evidence_ref"] = reference
            settings.pop("provider_poll_evidence", None)
            settings.pop("provider_poll_timeline", None)
            settings.pop("provider_poll_decision_bindings", None)
            attempt["provider_poll_evidence_ref"] = copy.deepcopy(reference)
            if sha256_file(source_path) != source_sha:
                raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "legacy evidence source changed")
        for attempt, reference, source_path, source_sha in prepared_history:
            _append_poll_evidence_history(attempt, reference)
            if sha256_file(source_path) != source_sha:
                raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "legacy evidence source changed")
        if prepared or prepared_history:
            atomic_write_json(manifest_path, manifest)
        after_size = manifest_path.stat().st_size if manifest_path.is_file() else 0
        return {
            "project_id": project_id,
            "externalized_attempts": len(prepared),
            "historical_evidence_bound": len(prepared_history),
            "manifest_size_before": before_size,
            "manifest_size_after": after_size,
        }


def _session_preparation_blocker(manifest: dict) -> dict | None:
    """Return one durable, proven provider-session blocker, if present."""
    value = manifest.get("session_preparation_blocker") if isinstance(manifest, dict) else None
    if not isinstance(value, dict): return None
    required = ("failure_class", "request_id", "media_type", "at", "diagnostic")
    if (value.get("scope") != "FLOW_SESSION" or value.get("canonical_no_dispatch_proof") is not True
            or value.get("failure_class") not in SESSION_PREPARATION_FAILURES
            or value.get("media_type") != "VIDEO"
            or not all(isinstance(value.get(key), str) and value[key] for key in required)):
        return None
    return value

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
    # The activation record can only authorize a retry when it was produced
    # before the durable executor/provider boundary.  An adapter may discover
    # an input-not-dispatched condition after that boundary, but it is not a
    # sufficient substitute for the pre-boundary proof: a crash or a provider
    # surface race could otherwise turn an ambiguous attempt into a retry.
    if (attempt.get("provider_execution_state") not in {None, "NOT_STARTED"}
            or attempt.get("provider_boundary_entered_at") is not None):
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
    if (attempt.get("provider_execution_state") not in {None, "NOT_STARTED"}
            or attempt.get("provider_boundary_entered_at") is not None):
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


def _materialize_persisted_pre_dispatch_proof(attempt: dict, *, proof: str) -> bool:
    """Project the coordinator's unentered provider boundary into canonical proof."""
    if not isinstance(attempt, dict):
        return False
    if (attempt.get("provider_execution_state") != "NOT_STARTED"
            or attempt.get("provider_boundary_entered_at") is not None
            or attempt.get("dispatch_confirmed") is not False
            or attempt.get("provider_submission_recorded") is True):
        return False
    if any(attempt.get(key) is not None for key in (
        "provider_job_id", "durable_dispatch_identity", "provider_lineage_card_id",
        "attributed_provider_identity",
    )):
        return False
    if attempt.get("attribution_state") not in {None, "NOT_ATTEMPTED"}:
        return False
    settings = attempt.get("provider_settings")
    if settings is not None and not isinstance(settings, dict):
        return False
    settings = dict(settings or {})
    activation = settings.get("activation")
    if activation is not None and (
            not isinstance(activation, dict) or activation.get("input_dispatched") is not False):
        return False
    if any(settings.get(key) is not None for key in (
        "provider_job_id", "durable_dispatch_identity", "provider_lineage_card_id",
        "attributed_provider_identity", "dispatch_confirmation_signal",
    )):
        return False
    if settings.get("dispatch_confirmation_state") not in {None, "NOT_CONFIRMED", "PRE_DISPATCH_FAILURE"}:
        return False
    if settings.get("dispatch_signal_state") not in {None, "NONE"}:
        return False
    if settings.get("attribution_state") not in {None, "NOT_ATTEMPTED"}:
        return False
    if settings.get("provider_poll_terminal_state") not in {None, "NOT_ATTEMPTED"}:
        return False
    snapshot = settings.get("provider_poll_evidence")
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            return False
        try:
            from .live import ProviderPollEvidenceTimeline
            verified = ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
        except (FlowError, ValueError, TypeError):
            return False
        for observation in verified.get("observations", []):
            if (observation.get("phase") not in {"PRE_DISPATCH_DISCOVERY", "PRE_DISPATCH_BASELINE"}
                    or observation.get("input_dispatched") is not False
                    or observation.get("dispatch_evidence_state") != "NOT_CONFIRMED"
                    or observation.get("dispatch_signal_state") != "NONE"
                    or observation.get("attribution_evidence_state") != "NOT_ATTEMPTED"
                    or observation.get("durable_dispatch_identity") is not None
                    or observation.get("lineage_card_id") is not None):
                return False
    settings["activation"] = {"input_dispatched": False, "proof": proof}
    settings["dispatch_confirmation_state"] = "PRE_DISPATCH_FAILURE"
    settings["attribution_state"] = "NOT_ATTEMPTED"
    attempt.update({
        "provider_settings": settings,
        "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
        "attribution_state": "NOT_ATTEMPTED",
    })
    return canonical_no_dispatch_proof(attempt)


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
    return _materialize_persisted_pre_dispatch_proof(
        attempt, proof="PROCESS_INTERRUPTED_BEFORE_PROVIDER_SETUP",
    )


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


def _recovery_input_from_entry(entry: dict | None, *, rate_limit_backoff_ready: bool = False) -> RecoveryInput:
    """Project current durable Flow evidence into the Slice 1 decision input.

    Status is intentionally not used as authority.  A retry is possible only
    from the existing positive pre-dispatch proof or hash-bound terminal
    evidence; every other persisted shape is ambiguity until reconciled.
    """
    attempts = entry.get("attempts") if isinstance(entry, dict) else None
    if not isinstance(attempts, list) or any(not isinstance(item, dict) for item in attempts):
        return RecoveryInput(FailureFamily.DISPATCH_AMBIGUOUS, AttemptOutcome.FAILED,
                             DispatchCertainty.DISPATCH_UNCERTAIN)
    submissions = entry.get("provider_submissions", 0)
    if not isinstance(submissions, int) or submissions < 0:
        return RecoveryInput(FailureFamily.DISPATCH_AMBIGUOUS, AttemptOutcome.FAILED,
                             DispatchCertainty.DISPATCH_UNCERTAIN)
    if not attempts:
        return RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                             DispatchCertainty.NOT_DISPATCHED, provider_attempt_count=submissions)
    latest = attempts[-1]
    retry_count = sum(
        1 for item in attempts
        if item.get("recovery_action") == "AUTO_RETRY"
        and item.get("provider_submission_recorded") is True
    )
    if canonical_no_dispatch_proof(latest):
        return RecoveryInput(
            FailureFamily.PRE_DISPATCH_FAILURE, AttemptOutcome.FAILED,
            DispatchCertainty.NOT_DISPATCHED, canonical_no_dispatch_proof=True,
            transient_redispatch_count=retry_count, provider_attempt_count=submissions,
            legacy_request_status=entry.get("status"),
        )
    terminal_log = latest.get("terminal_evidence")
    terminal = terminal_log[-1] if isinstance(terminal_log, list) and terminal_log else None
    if isinstance(terminal, dict) and terminal.get("authoritative") is True:
        try:
            family = FailureFamily(terminal.get("failure_family"))
        except (TypeError, ValueError):
            family = FailureFamily.PROVIDER_TERMINAL_UNKNOWN
        return RecoveryInput(
            family, AttemptOutcome.FAILED, DispatchCertainty.TERMINAL_CONFIRMED,
            terminal_evidence_confirmed=True,
            exact_attribution_confirmed=terminal.get("exact_attribution_confirmed") is True,
            rate_limit_backoff_ready=(rate_limit_backoff_ready
                                      and family is FailureFamily.PROVIDER_RATE_LIMIT),
            transient_redispatch_count=retry_count, provider_attempt_count=submissions,
            legacy_request_status=entry.get("status"),
        )
    return RecoveryInput(FailureFamily.DISPATCH_AMBIGUOUS, AttemptOutcome.FAILED,
                         DispatchCertainty.DISPATCH_UNCERTAIN,
                         transient_redispatch_count=retry_count,
                         provider_attempt_count=submissions,
                         legacy_request_status=entry.get("status"))


def _flow_session_identity(paths, config, executor: "FlowExecutor") -> str:
    """Bind a lock to the resolved browser profile plus CDP endpoint only."""
    runtime = getattr(executor.generate, "runtime", None)
    profile = getattr(runtime, "profile", paths.runtime.flow_profile)
    cdp_url = getattr(runtime, "cdp_url", None)
    if not isinstance(cdp_url, str) or not cdp_url.strip():
        flow = config.settings.get("flow", {}) if isinstance(config.settings, dict) else {}
        cdp_url = str(flow.get("cdp_url", "http://127.0.0.1:9222"))
    normalized_profile = os.path.normcase(str(Path(profile).expanduser().resolve()))
    normalized_cdp = cdp_url.strip().rstrip("/").casefold()
    return f"profile={normalized_profile}|cdp={normalized_cdp}"


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
    if schema_version == SEMANTIC_RESET_TRANSACTION_SCHEMA:
        return "SEMANTIC_RESET_RECOVERY_INVALID"
    if schema_version == QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA:
        return "QC_CORRECTIVE_REPLAN_RECOVERY_INVALID"
    if schema_version == QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA:
        return "QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_RECOVERY_INVALID"
    return "FLOW_REPLACEMENT_RECOVERY_INVALID"


def _transaction_spec(paths, schema_version: str) -> tuple[Path, str]:
    if schema_version == SUPERSESSION_TRANSACTION_SCHEMA:
        return _supersession_directory(paths), "LEGACY_SUPERSESSION_RECOVERY_INVALID"
    if schema_version == UNRESOLVED_REPLAY_TRANSACTION_SCHEMA:
        return _unresolved_replay_directory(paths), "UNRESOLVED_REPLAY_RECOVERY_INVALID"
    if schema_version == QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA:
        return paths.artifact_path("output/qc_rejected_asset_replacement_transactions"), "QC_REJECTED_ASSET_REPLACEMENT_RECOVERY_INVALID"
    if schema_version == SEMANTIC_RESET_TRANSACTION_SCHEMA:
        return paths.artifact_path("output/semantic_reset_transactions"), "SEMANTIC_RESET_RECOVERY_INVALID"
    if schema_version == QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA:
        return paths.artifact_path("output/qc_corrective_replan_transactions"), "QC_CORRECTIVE_REPLAN_RECOVERY_INVALID"
    if schema_version == QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA:
        return (paths.artifact_path("output/qc_corrective_pre_dispatch_supersession_transactions"),
                "QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_RECOVERY_INVALID")
    raise FlowError("FLOW_REPLACEMENT_RECOVERY_INVALID")


def _transaction_paths(paths, transaction_id: str, *,
                       schema_version: str = SUPERSESSION_TRANSACTION_SCHEMA) -> tuple[Path, Path]:
    directory, _ = _transaction_spec(paths, schema_version)
    return directory / f"{transaction_id}.prepared.json", directory / f"{transaction_id}.committed.json"


def _prepared_archive_paths(prepared_path: Path) -> tuple[Path, Path]:
    return (prepared_path.with_name(prepared_path.name + ".gz"),
            prepared_path.with_name(prepared_path.name + ".archive.json"))


def _read_archived_prepared_transaction(archive_path: Path, error_code: str) -> dict:
    """Read a lossless, receipt-bound archive of a committed transaction."""
    if not archive_path.name.endswith(".prepared.json.gz"):
        raise FlowError(error_code)
    prepared_path = archive_path.with_suffix("")
    _archive, receipt_path = _prepared_archive_paths(prepared_path)
    try:
        receipt = read_json(receipt_path)
        if (not isinstance(receipt, dict)
                or receipt.get("schema_version") != TRANSACTION_ARCHIVE_SCHEMA
                or receipt.get("state") != "ARCHIVED"
                or receipt.get("original_path") != prepared_path.name
                or receipt.get("archive_path") != archive_path.name
                or receipt.get("archive_sha256") != sha256_file(archive_path)
                or not isinstance(receipt.get("prepared_sha256"), str)):
            raise ValueError()
        with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or _prepared_transaction_sha256(value) != receipt["prepared_sha256"]:
            raise ValueError()
        return value
    except Exception as error:
        raise FlowError(error_code) from error


def _read_prepared_transaction(path: Path, error_code: str) -> dict:
    if path.name.endswith(".prepared.json.gz"):
        return _read_archived_prepared_transaction(path, error_code)
    try:
        value = read_json(path)
    except Exception as error:
        raise FlowError(error_code) from error
    if not isinstance(value, dict):
        raise FlowError(error_code)
    return value


def _prepared_transactions(paths, project_id: str, *,
                           schema_version: str = SUPERSESSION_TRANSACTION_SCHEMA) -> list[tuple[Path, dict]]:
    directory, error_code = _transaction_spec(paths, schema_version)
    cache = _transaction_read_cache.get()
    cache_key = ("prepared", str(directory.resolve()), project_id, schema_version)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    if not directory.is_dir(): return []
    raw_paths = sorted(directory.glob("*.prepared.json"))
    archived_paths = sorted(directory.glob("*.prepared.json.gz"))
    raw_bases = {path.name for path in raw_paths}
    if any(path.with_suffix("").name in raw_bases for path in archived_paths):
        raise FlowError(error_code)
    values = []
    for path in [*raw_paths, *archived_paths]:
        value = _read_prepared_transaction(path, error_code)
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
                or path.name != f"{transaction_id}.prepared.json" + (".gz" if path.name.endswith(".gz") else "")
                or not isinstance(old_request_id, str) or not old_request_id
                or not isinstance(replacement_request_id, str) or not replacement_request_id
                or old_request_id == replacement_request_id):
            raise FlowError(error_code)
        _validate_transaction_targets(value, schema_version=schema_version)
        values.append((path, value))
    if cache is not None:
        cache[cache_key] = values
    return values


def _validate_transaction_targets(transaction: dict, *, schema_version: str | None = None) -> None:
    schema = schema_version or transaction.get("schema_version")
    if schema not in {SUPERSESSION_TRANSACTION_SCHEMA, UNRESOLVED_REPLAY_TRANSACTION_SCHEMA,
                      QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA,
                      SEMANTIC_RESET_TRANSACTION_SCHEMA,
                      QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA,
                      QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA}:
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
    with _transaction_read_scope():
        invalid = _first_invalid_superseded(paths, project_id, entries, requests)
        if invalid is not None:
            return invalid
        for request in requests:
            if isinstance(request, dict) and not _qc_ancestry_metadata_has_direct_origin(paths, project_id, request):
                return request, entries.get(request.get("request_id"), {"request_id": request.get("request_id")})
            if isinstance(request, dict) and not _qc_corrective_metadata_has_direct_origin(paths, project_id, request):
                return request, entries.get(request.get("request_id"), {"request_id": request.get("request_id")})
        for entry in entries.values():
            if not _qc_ancestry_metadata_has_direct_origin(paths, project_id, entry):
                return {"request_id": entry.get("request_id")}, entry
            if not _qc_corrective_metadata_has_direct_origin(paths, project_id, entry):
                return {"request_id": entry.get("request_id")}, entry
            if (entry.get("status") == ABANDONED_UNRESOLVED_STATUS
                    and not _abandoned_unresolved_entry_valid(paths, project_id, entry, requests, entries)):
                return {"request_id": entry.get("request_id")}, entry
            if (entry.get("status") == QC_REJECTED_ASSET_REPLACED_STATUS
                    and not _qc_rejected_asset_replacement_valid(paths, project_id, entry, requests, entries)):
                return {"request_id": entry.get("request_id")}, entry
            if (entry.get("status") == SEMANTIC_RESET_PENDING_STATUS
                    and not _semantic_reset_parent_valid(paths, project_id, entry, requests, entries)):
                return {"request_id": entry.get("request_id")}, entry
            if (entry.get("status") == QC_CORRECTIVE_REPLANNED_STATUS
                    and not _qc_corrective_replan_valid(paths, project_id, entry, requests, entries)):
                return {"request_id": entry.get("request_id")}, entry
            if (entry.get("status") == QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS
                    and not _qc_corrective_pre_dispatch_supersession_valid(paths, project_id, entry, requests, entries)):
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
        archive_path, _receipt_path = _prepared_archive_paths(prepared_path)
        if archive_path.is_file():
            if _read_archived_prepared_transaction(archive_path, error_code) != transaction:
                raise FlowError(error_code)
        else:
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
               "transaction_id": transaction_id, "prepared_sha256": _prepared_transaction_sha256(transaction)}
    if not committed_path.is_file():
        if fault_injector: fault_injector("committed")
        atomic_write_json(committed_path, receipt)
    elif read_json(committed_path) != receipt:
        raise FlowError(error_code)


def _archive_committed_prepared_transaction(prepared_path: Path, committed_path: Path,
                                            *, schema_version: str, project_id: str) -> int:
    """Replace one committed transaction file with a lossless verified archive.

    The transaction payload and its committed receipt are validated before any
    bytes are removed.  The archive receipt carries both the semantic prepared
    hash and the exact original byte hash, so a missing or altered archive
    fails closed during any future recovery/read operation.
    """
    error_code = _transaction_error(schema_version)
    transaction = _read_prepared_transaction(prepared_path, error_code)
    if (transaction.get("schema_version") != schema_version
            or transaction.get("state") != "PREPARED"
            or transaction.get("project_id") != project_id):
        raise FlowError(error_code)
    transaction_id = transaction.get("transaction_id")
    if not isinstance(transaction_id, str) or prepared_path.name != f"{transaction_id}.prepared.json":
        raise FlowError(error_code)
    _validate_transaction_targets(transaction, schema_version=schema_version)
    try:
        committed = read_json(committed_path)
    except Exception as error:
        raise FlowError(error_code) from error
    expected_receipt = {"schema_version": schema_version, "state": "COMMITTED",
                        "transaction_id": transaction_id,
                        "prepared_sha256": _prepared_transaction_sha256(transaction)}
    if committed != expected_receipt:
        raise FlowError(error_code)
    archive_path, archive_receipt_path = _prepared_archive_paths(prepared_path)
    original_bytes = prepared_path.stat().st_size
    original_sha256 = sha256_file(prepared_path)
    if not archive_path.is_file():
        compressed = io.BytesIO()
        with prepared_path.open("rb") as source, gzip.GzipFile(
                fileobj=compressed, mode="wb", compresslevel=6, mtime=0) as destination:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                destination.write(chunk)
        atomic_write_bytes(archive_path, compressed.getvalue())
    receipt_core = {
        "schema_version": TRANSACTION_ARCHIVE_SCHEMA,
        "state": "ARCHIVED",
        "transaction_id": transaction_id,
        "original_path": prepared_path.name,
        "original_sha256": original_sha256,
        "original_bytes": original_bytes,
        "archive_path": archive_path.name,
        "archive_sha256": sha256_file(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "prepared_sha256": expected_receipt["prepared_sha256"],
    }
    if archive_receipt_path.is_file():
        existing = read_json(archive_receipt_path)
        if (not isinstance(existing, dict) or not isinstance(existing.get("archived_at"), str)
                or {key: value for key, value in existing.items() if key != "archived_at"} != receipt_core):
            raise FlowError(error_code)
    else:
        receipt = {**receipt_core, "archived_at": _now()}
        atomic_write_json(archive_receipt_path, receipt)
    _read_archived_prepared_transaction(archive_path, error_code)
    prepared_path.unlink()
    return original_bytes - archive_path.stat().st_size - archive_receipt_path.stat().st_size


def compact_committed_replacement_transactions(paths, project_id: str) -> dict:
    """Losslessly compact only committed append-only transaction snapshots.

    A prepared transaction without its committed receipt is deliberately left
    online: it remains a live recovery operation.  This function never touches
    request assets, selected media, attempts, manifests, or provider state.
    """
    schemas = (
        SUPERSESSION_TRANSACTION_SCHEMA,
        UNRESOLVED_REPLAY_TRANSACTION_SCHEMA,
        QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA,
        SEMANTIC_RESET_TRANSACTION_SCHEMA,
        QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA,
        QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA,
    )
    archived = 0
    reclaimed = 0
    with _transaction_read_scope():
        for schema_version in schemas:
            directory, _error_code = _transaction_spec(paths, schema_version)
            if not directory.is_dir():
                continue
            for prepared_path in sorted(directory.glob("*.prepared.json")):
                transaction_id = prepared_path.name.removesuffix(".prepared.json")
                committed_path = directory / f"{transaction_id}.committed.json"
                if not committed_path.is_file():
                    continue
                reclaimed += _archive_committed_prepared_transaction(
                    prepared_path, committed_path,
                    schema_version=schema_version, project_id=project_id,
                )
                archived += 1
    return {"archived_transactions": archived, "reclaimed_bytes": reclaimed}


def _media_paths_in(value: Any) -> set[str]:
    keys = {"asset_path", "downloaded_raw_path", "source_path", "output_path", "selected_path", "raw_path", "path"}
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item.startswith("assets/"):
                found.add(item.replace("\\", "/"))
            found.update(_media_paths_in(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_media_paths_in(item))
    return found


def _append_terminal_observations(request: dict, attempt: dict, generator: Any) -> list[dict]:
    """Append classified terminal observations without changing dispatch authority."""
    settings = getattr(generator, "last_settings", None)
    persisted_settings = attempt.get("provider_settings")
    live_settings = settings if isinstance(settings, dict) else {}
    if not isinstance(persisted_settings, dict):
        persisted_settings = {}
    observations = live_settings.get("terminal_observations", persisted_settings.get("terminal_observations"))
    provider_poll_evidence = live_settings.get(
        "provider_poll_evidence", persisted_settings.get("provider_poll_evidence")
    )
    source_hints = live_settings.get(
        "terminal_observation_sources", persisted_settings.get("terminal_observation_sources")
    )
    if not isinstance(observations, list):
        return []
    appended = []
    evidence_log = attempt.setdefault("terminal_evidence", [])
    if not isinstance(evidence_log, list):
        raise FlowError("FLOW_TERMINAL_EVIDENCE_INVALID")
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            continue
        source_hint = (
            source_hints[index]
            if isinstance(source_hints, list) and index < len(source_hints)
            and isinstance(source_hints[index], dict)
            else {}
        )
        evidence = build_terminal_evidence(
            request_id=request["request_id"],
            attempt=attempt,
            observation=observation,
            observed_at=_now(),
            provider_poll_evidence=(
                provider_poll_evidence if isinstance(provider_poll_evidence, dict) else None
            ),
            source_poll_sequence=source_hint.get("source_poll_sequence"),
            source_observation_sha256=source_hint.get("source_observation_sha256"),
        )
        source_identity = evidence.get("canonical_source_identity_sha256")
        if source_identity and any(
            item.get("canonical_source_identity_sha256") == source_identity
            for item in evidence_log if isinstance(item, dict)
        ):
            continue
        if any(item.get("evidence_digest_sha256") == evidence["evidence_digest_sha256"]
               for item in evidence_log if isinstance(item, dict)):
            continue
        evidence_log.append(evidence)
        appended.append(evidence)
    return appended


def _terminal_media_tombstone_directory(paths) -> Path:
    return paths.artifact_path("output/terminal_media_tombstones")


def _terminal_media_tombstones(paths, project_id: str) -> dict[str, dict]:
    directory = _terminal_media_tombstone_directory(paths)
    values: dict[str, dict] = {}
    if not directory.is_dir():
        return values
    for path in sorted(directory.glob("*.json")):
        try:
            value = read_json(path)
        except Exception as error:
            raise FlowError("TERMINAL_MEDIA_TOMBSTONE_INVALID") from error
        if (not isinstance(value, dict)
                or value.get("schema_version") != TERMINAL_MEDIA_TOMBSTONE_SCHEMA
                or value.get("project_id") != project_id
                or value.get("state") != "PRUNED"
                or not isinstance(value.get("sha256"), str)
                or len(value["sha256"]) != 64
                or not isinstance(value.get("original_path"), str)):
            raise FlowError("TERMINAL_MEDIA_TOMBSTONE_INVALID")
        if value["sha256"] in values:
            raise FlowError("TERMINAL_MEDIA_TOMBSTONE_INVALID")
        values[value["sha256"]] = value
    return values


def _assert_media_not_tombstoned(paths, project_id: str, sha256: str) -> None:
    if sha256 in _terminal_media_tombstones(paths, project_id):
        raise FlowError("TERMINAL_MEDIA_PRUNED")


def compact_terminal_media(paths, project_id: str) -> dict:
    """Tombstone only terminal media with no live byte consumer.

    The manifest remains untouched.  A tombstone is atomically persisted and
    re-read before its binary is removed, so subsequent recovery/adoption sees
    the historic provenance but cannot treat absent bytes as an asset.
    """
    _manifest_path, manifest = _manifest(paths, project_id)
    requests = read_json(paths.artifact_path("output/generation_requests.json"))
    if not isinstance(requests, dict):
        raise FlowError("TERMINAL_MEDIA_COMPACTION_INVALID")
    protected_paths = _media_paths_in(requests)
    for name in ("output/media_plan.json", "output/render_manifest.json"):
        artifact = paths.artifact_path(name)
        if artifact.is_file():
            protected_paths.update(_media_paths_in(read_json(artifact)))
    for schema_version in (
        SUPERSESSION_TRANSACTION_SCHEMA, UNRESOLVED_REPLAY_TRANSACTION_SCHEMA,
        QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA, SEMANTIC_RESET_TRANSACTION_SCHEMA,
        QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA, QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA,
    ):
        directory, error_code = _transaction_spec(paths, schema_version)
        if not directory.is_dir():
            continue
        for prepared_path in directory.glob("*.prepared.json"):
            transaction_id = prepared_path.name.removesuffix(".prepared.json")
            if not (directory / f"{transaction_id}.committed.json").is_file():
                protected_paths.update(_media_paths_in(_read_prepared_transaction(prepared_path, error_code)))
    candidates: list[tuple[dict, dict, str, Path]] = []
    for entry in manifest["requests"]:
        entry_paths = _media_paths_in(entry)
        if entry.get("status") in PRUNABLE_TERMINAL_MEDIA_STATUSES:
            selected_paths = _media_paths_in(entry.get("selected_asset"))
            for rel in entry_paths - selected_paths:
                asset = paths.artifact_path(rel)
                if asset.is_file() and rel not in protected_paths:
                    candidates.append((entry, next((attempt for attempt in entry.get("attempts", [])
                                                    if rel in _media_paths_in(attempt)), {}), rel, asset))
        else:
            protected_paths.update(entry_paths)
    tombstones = _terminal_media_tombstones(paths, project_id)
    pruned = 0
    reclaimed = 0
    for entry, attempt, rel, asset in candidates:
        if not asset.is_file() or rel in protected_paths:
            continue
        sha256 = sha256_file(asset)
        if sha256 in tombstones:
            raise FlowError("TERMINAL_MEDIA_TOMBSTONE_INVALID")
        if asset.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            metadata = validate_image(asset)
        elif asset.suffix.lower() in {".mp4", ".mov"}:
            metadata = validate_video(asset)
        else:
            metadata = {"bytes": asset.stat().st_size}
        receipt = {
            "schema_version": TERMINAL_MEDIA_TOMBSTONE_SCHEMA,
            "state": "PRUNED",
            "project_id": project_id,
            "original_path": rel,
            "sha256": sha256,
            "metadata": metadata,
            "request_id": entry.get("request_id"),
            "attempt": attempt.get("attempt") if isinstance(attempt, dict) else None,
            "disposition": entry.get("status"),
            "terminal_reason": entry.get("failure_class") or entry.get("status"),
            "quality_reviews_sha256": _json_sha256(entry.get("quality_reviews")),
            "lineage": {key: entry.get(key) for key in (
                "replacement_request_id", "replaces_request_id", "replacement_of", "replays_unresolved_request_id")
                if entry.get(key) is not None},
            "prune_reason": "TERMINAL_MEDIA_NO_LIVE_BYTE_CONSUMER",
            "pruned_at": _now(),
        }
        tombstone_path = _terminal_media_tombstone_directory(paths) / f"{sha256}.json"
        atomic_write_json(tombstone_path, receipt)
        if _terminal_media_tombstones(paths, project_id).get(sha256) != receipt:
            raise FlowError("TERMINAL_MEDIA_TOMBSTONE_INVALID")
        bytes_before = asset.stat().st_size
        asset.unlink()
        reclaimed += bytes_before
        pruned += 1
    return {"terminal_media_pruned": pruned, "reclaimed_bytes": reclaimed}


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
                    or receipt.get("prepared_sha256") != _prepared_transaction_sha256(transaction)):
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


def _recover_pending_qc_corrective_replans(paths, project_id: str) -> dict[str, dict]:
    return _recover_replacement_transactions(
        paths, project_id, schema_version=QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA
    )


def _recover_pending_qc_corrective_pre_dispatch_supersessions(paths, project_id: str) -> dict[str, dict]:
    return _recover_replacement_transactions(
        paths, project_id, schema_version=QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA
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
                        "transaction_id": transaction_id, "prepared_sha256": _prepared_transaction_sha256(transaction)}
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
                        "transaction_id": transaction_id, "prepared_sha256": _prepared_transaction_sha256(transaction)}
            if receipt != expected:
                return None
            matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _recover_pending_request_replacements(paths, project_id: str) -> dict[str, dict]:
    recovered = _recover_pending_supersessions(paths, project_id)
    replayed = _recover_pending_unresolved_replays(paths, project_id)
    qc_replaced = _recover_pending_qc_rejected_asset_replacements(paths, project_id)
    qc_corrected = _recover_pending_qc_corrective_replans(paths, project_id)
    qc_pre_dispatch = _recover_pending_qc_corrective_pre_dispatch_supersessions(paths, project_id)
    groups = (recovered, replayed, qc_replaced, qc_corrected, qc_pre_dispatch)
    if any(set(left).intersection(right) for index, left in enumerate(groups) for right in groups[index + 1:]):
        raise FlowError("FLOW_REPLACEMENT_RECOVERY_INVALID")
    recovered.update(replayed)
    recovered.update(qc_replaced)
    recovered.update(qc_corrected)
    recovered.update(qc_pre_dispatch)
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


def _successful_raw_video(paths, entry):
    """Return the newest valid raw provider video explicitly awaiting cleanup."""
    for attempt in reversed(entry.get("attempts", [])):
        if (attempt.get("status") != "SUCCEEDED"
                or attempt.get("production_video_postprocess_required") is not True
                or attempt.get("attribution_status") == "INVALIDATED"
                or not isinstance(attempt.get("asset_path"), str)):
            continue
        try:
            metadata = validate_video(paths.artifact_path(attempt["asset_path"]))
        except AssetValidationError:
            continue
        if metadata["sha256"] == attempt.get("asset_sha256"):
            return attempt, metadata
    return None, None


def _clean_video_rel(entry: dict, attempt: dict) -> str:
    return f"assets/video/{entry['request_id']}/attempt_{attempt['attempt']:03d}_clean.mp4"


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


def _process_raw_video(paths, entry: dict, attempt: dict, *, output_rel: str | None = None) -> dict:
    """Append one local video-cleanup record and bind the clean selected bytes."""
    if attempt.get("attribution_state") != "CONFIRMED" or attempt.get("attribution_status") == "INVALIDATED":
        raise FlowVideoPostprocessError("OUTPUT_ATTRIBUTION_UNCONFIRMED")
    source_rel = attempt["asset_path"]
    source_sha = attempt["asset_sha256"]
    output_rel = output_rel or _clean_video_rel(entry, attempt)
    processing_number = len(entry.setdefault("video_postprocess_attempts", [])) + 1
    source_metadata = attempt.get("metadata", {})
    profile = profile_evidence(int(source_metadata.get("width", 0)), int(source_metadata.get("height", 0)))
    record = {
        "processing_attempt": processing_number, "status": "PROCESSING",
        "source_provider_attempt": attempt["attempt"], "source_path": source_rel,
        "source_sha256": source_sha, "output_path": output_rel,
        "processor_name": VIDEO_PROCESSOR_NAME, "processor_version": VIDEO_PROCESSOR_VERSION,
        "flow_mark_profile_version": profile["profile_version"], "profile_sha256": profile["profile_sha256"],
        "started_at": _now(),
    }
    entry["video_postprocess_attempts"].append(record)
    try:
        result = process_flow_video(paths.artifact_path(source_rel), paths.artifact_path(output_rel))
    except FlowVideoPostprocessError as error:
        record.update({"status": "FAILED", "failure_class": error.failure_class,
                       "diagnostic": str(error), "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class,
                      "updated_at": _now()})
        raise
    if result["source_sha256"] != source_sha:
        record.update({"status": "FAILED", "failure_class": "FLOW_VIDEO_POSTPROCESS_SOURCE_INVALID",
                       "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_VIDEO_POSTPROCESS_SOURCE_INVALID",
                      "updated_at": _now()})
        raise FlowVideoPostprocessError("FLOW_VIDEO_POSTPROCESS_SOURCE_INVALID")
    record.update({
        "status": "SUCCEEDED", "output_sha256": result["output_sha256"],
        "processor_name": result["processor_name"], "processor_version": result["processor_version"],
        "flow_mark_profile_version": result["profile_version"], "profile_sha256": result["profile_sha256"],
        "mask_sha256": result["mask_sha256"], "completed_at": _now(),
    })
    selected = {
        "path": output_rel, "sha256": result["output_sha256"], "attempt": attempt["attempt"],
        "metadata": result["output_metadata"], "production_qc": "PENDING", "temporal_qc": "PENDING",
        "source_provider_attempt": attempt["attempt"], "source_path": source_rel,
        "source_sha256": source_sha, "video_postprocess_attempt": processing_number,
        "processor_name": result["processor_name"], "processor_version": result["processor_version"],
        "flow_mark_profile_version": result["profile_version"], "mask_sha256": result["mask_sha256"],
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

def _runnable(request, entries, paths=None):
    """Allow only a validated selected dependency to seed another request.

    Production post-processing puts a confirmed selected asset into
    ``QC_PENDING`` while its creative review remains open.  That review state
    must not prevent a dependent shot from using the exact selected reference;
    it also must not make a raw, missing, or ambiguous provider result runnable.
    """
    for dependency in request.get("depends_on", []):
        entry = entries.get(dependency)
        if not isinstance(entry, dict):
            return False
        if entry.get("status") not in {"SUCCEEDED", "QC_PENDING"}:
            return False
        if not isinstance(entry.get("selected_asset"), dict):
            return False
        if paths is not None and not _valid_selected(paths, entry):
            return False
    return True


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
            raw_video_attempt, _ = _successful_raw_video(paths, entry)
            failure_class = ("FLOW_IMAGE_DERIVATIVE_INVALID" if raw_attempt is not None
                             else "FLOW_VIDEO_DERIVATIVE_INVALID" if raw_video_attempt is not None
                             else "ASSET_INVALID")
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


def recover_confirmed_output_after_manifest_persistence_failure(
        runtime_root: Path | str, project_id: str, request_id: str) -> dict:
    """Finish one provider-bound IMAGE attempt whose result write was interrupted.

    This is deliberately not a retry or an operator adoption path.  It accepts
    only the exact attempt-scoped, hash-verified provider timeline and the
    deterministic clean derivative already produced from that attempt's raw
    bytes.  The original submitted attempt remains the sole provider attempt;
    recovery appends durable state to it after the manifest becomes writable.
    """
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not isinstance(entry, dict):
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_INVALID")
        attempts = entry.get("attempts")
        attempt = attempts[-1] if isinstance(attempts, list) and attempts else None
        attempt_number = attempt.get("attempt") if isinstance(attempt, dict) else None
        if (
            entry.get("status") != "GENERATING"
            or entry.get("selected_asset") is not None
            or not isinstance(attempt_number, int)
            or attempt.get("status") != "SUBMITTED"
            or attempt.get("provider_execution_state") != "PROVIDER_BOUNDARY_ENTERED"
            or attempt.get("dispatch_confirmed") is not False
            or attempt.get("attribution_state") not in {None, "NOT_ATTEMPTED"}
            or int(entry.get("provider_submissions", 0)) != attempt_number
        ):
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_INVALID")
        try:
            request = next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
                           if item.get("request_id") == request_id)
        except Exception as error:
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_INVALID") from error
        if request.get("media_type") != "IMAGE" or request.get("execution_tier") != "STANDARD_PRODUCTION":
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_INVALID")

        evidence_path = paths.artifact_path(
            f"assets/attempts/{request_id}/attempt_{attempt_number:03d}/provider_poll_evidence.json"
        )
        raw_rel = f"assets/image/{request_id}/attempt_{attempt_number:03d}_raw.png"
        clean_rel = f"assets/image/{request_id}/attempt_{attempt_number:03d}_clean.png"
        raw_path = paths.artifact_path(raw_rel)
        clean_path = paths.artifact_path(clean_rel)
        if not evidence_path.is_file() or not raw_path.is_file() or not clean_path.is_file():
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_EVIDENCE_MISSING")
        try:
            from .live import ProviderPollEvidenceTimeline
            evidence = read_json(evidence_path)
            verified = ProviderPollEvidenceTimeline.verify_snapshot(evidence)
            binding = ProviderPollEvidenceTimeline.verify_authoritative_binding(evidence)
            raw_metadata = validate_image(raw_path)
            clean_metadata = validate_image(clean_path)
        except (ValueError, AssetValidationError, OSError) as error:
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_EVIDENCE_INVALID") from error
        if (
            not verified.get("evidence_complete")
            or binding.get("resulting_dispatch_state") != "CONFIRMED"
            or binding.get("resulting_attribution_state") != "CONFIRMED"
            or not isinstance(binding.get("durable_identity_used"), str)
            or not binding["durable_identity_used"]
        ):
            raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_EVIDENCE_INVALID")

        # Rebuild a disposable deterministic derivative to prove that the
        # already-present clean file is exactly derived from this raw provider
        # output.  The verified production file itself is never overwritten.
        verification_path = clean_path.with_name(
            f".{clean_path.stem}.manifest-recovery-{uuid.uuid4().hex}{clean_path.suffix}"
        )
        try:
            processed = process_flow_image(raw_path, verification_path)
            if processed.get("output_sha256") != clean_metadata.get("sha256"):
                raise FlowError("MANIFEST_PERSISTENCE_RECOVERY_DERIVATIVE_MISMATCH")
        except FlowImagePostprocessError as error:
            raise FlowError(error.failure_class, str(error)) from error
        finally:
            verification_path.unlink(missing_ok=True)

        at = _now()
        original_attempt_sha256 = _json_sha256(attempt)
        recovery = {
            "recovered_at": at,
            "recovery_kind": "CONFIRMED_OUTPUT_AFTER_MANIFEST_PERSISTENCE_FAILURE",
            "pre_recovery_attempt_sha256": original_attempt_sha256,
            "provider_poll_evidence_path": str(evidence_path.relative_to(paths.root)).replace("\\", "/"),
            "provider_poll_evidence_sha256": sha256_file(evidence_path),
            "authoritative_binding_sha256": binding.get("binding_sha256"),
            "durable_provider_identity": binding["durable_identity_used"],
            "raw_path": raw_rel,
            "raw_sha256": raw_metadata["sha256"],
            "selected_path": clean_rel,
            "selected_sha256": clean_metadata["sha256"],
        }
        attempt.update({
            "status": "SUCCEEDED",
            "completed_at": at,
            "dispatch_confirmed": True,
            "dispatch_confirmation_state": "CONFIRMED",
            "dispatch_confirmation_signal": binding.get("resulting_dispatch_signal"),
            "durable_dispatch_identity": binding["durable_identity_used"],
            "attribution_state": "CONFIRMED",
            "attribution_method": "persisted_provider_poll_timeline",
            "attribution_method_version": "flow-provider-tile-lineage/1.0.0",
            "attributed_provider_identity": {"identity": binding["durable_identity_used"]},
            "attribution_confirmation_timestamp": at,
            "asset_path": raw_rel,
            "asset_sha256": raw_metadata["sha256"],
            "downloaded_raw_path": raw_rel,
            "raw_sha256": raw_metadata["sha256"],
            "metadata": raw_metadata,
            "production_image_postprocess_required": True,
            "provider_settings": {
                "provider_poll_evidence": verified,
                "provider_poll_authoritative_binding": binding,
                "dispatch_confirmation_state": "CONFIRMED",
                "dispatch_confirmation_signal": binding.get("resulting_dispatch_signal"),
                "attribution_state": "CONFIRMED",
                "attributed_provider_identity": {"identity": binding["durable_identity_used"]},
            },
        })
        attempt.setdefault("attribution_events", []).append({
            "at": at, "state": "CONFIRMED", "method": attempt["attribution_method"],
            "provider_identity": attempt["attributed_provider_identity"],
            "recovered_after_manifest_persistence_failure": True,
        })
        attempt.setdefault("manifest_persistence_recoveries", []).append(recovery)
        processing_number = len(entry.setdefault("postprocess_attempts", [])) + 1
        entry["postprocess_attempts"].append({
            "processing_attempt": processing_number,
            "status": "SUCCEEDED",
            "source_provider_attempt": attempt_number,
            "source_path": raw_rel,
            "source_sha256": raw_metadata["sha256"],
            "output_path": clean_rel,
            "output_sha256": clean_metadata["sha256"],
            "processor_name": processed["processor_name"],
            "processor_version": processed["processor_version"],
            "flow_mark_profile_version": processed["profile_version"],
            "profile_sha256": processed["profile_sha256"],
            "mask_sha256": processed["mask_sha256"],
            "completed_at": at,
            "recovered_after_manifest_persistence_failure": True,
        })
        selected = {
            "path": clean_rel,
            "sha256": clean_metadata["sha256"],
            "attempt": attempt_number,
            "metadata": clean_metadata,
            "production_qc": "PENDING",
            "source_provider_attempt": attempt_number,
            "source_path": raw_rel,
            "source_sha256": raw_metadata["sha256"],
            "postprocess_attempt": processing_number,
            "processor_name": processed["processor_name"],
            "processor_version": processed["processor_version"],
            "flow_mark_profile_version": processed["profile_version"],
            "mask_sha256": processed["mask_sha256"],
            "provenance": "CONFIRMED_OUTPUT_MANIFEST_PERSISTENCE_RECOVERY",
        }
        entry.setdefault("manifest_persistence_recoveries", []).append(recovery)
        entry.update({"selected_asset": selected, "status": "QC_PENDING", "failure_class": None, "updated_at": at})
        atomic_write_json(path, manifest)
        return selected


def review_production_asset(runtime_root: Path | str, project_id: str, request_id: str, report: dict) -> None:
    """Approve or reject selected bytes using the complete production QC rubric."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or not isinstance(entry.get("selected_asset"), dict):
            raise FlowError("MEDIA_QC_INVALID")
        selected = entry["selected_asset"]
        try:
            requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
        except Exception:
            requests = []
        request = next((item for item in requests if item.get("request_id") == request_id), {})
        review_epoch = selected.get("active_production_review_epoch")
        if review_epoch is not None:
            if (not isinstance(report, dict) or report.get("review_identity") != review_epoch
                    or report.get("request_id") != request_id
                    or report.get("attempt") != selected.get("attempt")
                    or report.get("media_sha256") != selected.get("sha256")):
                raise FlowError("PRODUCTION_QC_FRESH_EVIDENCE_INVALID")
        try:
            accepted = validate_production_qc(
                report, provider=entry.get("provider"), media_type=entry.get("media_type")
            )
            # Story shots require an explicit structured comparison to their
            # narration intent. Technical/media quality alone is insufficient.
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
            # A malformed operator submission is not a quality finding.  Do
            # not turn it into a durable rejection: there is no reviewed
            # evidence to supersede, and the caller can submit the completed
            # rubric again without any generation action.
            if error.failure_class == "MEDIA_QC_INVALID":
                raise FlowError(error.failure_class) from error
            # Bind every new rejection to the selected bytes.  A later appeal
            # can then prove it is asking to re-review this asset, not a
            # different file substituted after the original decision.
            rejection = {
                "reviewed_at": _now(), "status": "REJECTED", "failure_class": error.failure_class,
                "report": report, "selected_asset_path": selected.get("path"),
                "selected_asset_sha256": selected.get("sha256"),
            }
            if review_epoch is not None:
                rejection.update({"review_epoch": review_epoch, "selected_attempt": selected.get("attempt"),
                                  "media_sha256": selected.get("sha256")})
                selected.pop("active_production_review_epoch", None)
            entry.setdefault("quality_reviews", []).append(rejection)
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
            atomic_write_json(path, manifest)
            raise FlowError(error.failure_class) from error
        approval = {"reviewed_at": _now(), "status": "APPROVED", "report": accepted}
        if review_epoch is not None:
            approval.update({"review_epoch": review_epoch, "selected_asset_path": selected.get("path"),
                             "selected_asset_sha256": selected.get("sha256"),
                             "selected_attempt": selected.get("attempt"), "media_sha256": selected.get("sha256")})
            selected["completed_production_review_epoch"] = review_epoch
            selected.pop("active_production_review_epoch", None)
        entry.setdefault("quality_reviews", []).append(approval)
        selected["production_qc"] = "APPROVED"
        if request.get("purpose") == "SHOT":
            # validate_production_qc intentionally returns only the technical
            # rubric. Keep the separately validated narrative verdict with the
            # exact selected bytes so the final render audit is self-contained.
            selected["alignment_classification"] = classification
            selected["alignment_observation"] = str(report.get("notes", "")).strip()
        temporal_ready = request.get("media_type") != "VIDEO" or selected.get("temporal_qc") == "APPROVED"
        entry.update({"status": "SUCCEEDED" if temporal_ready else "QC_PENDING",
                      "failure_class": None if temporal_ready else "TEMPORAL_VIDEO_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def _technical_integrity_eligible(paths, entry: dict, request: dict | None) -> bool:
    """Prove an asset passed the non-editorial gate before a policy may decide it."""
    selected = entry.get("selected_asset")
    source_attempt = selected.get("source_provider_attempt", selected.get("attempt")) if isinstance(selected, dict) else None
    attempt = next((item for item in entry.get("attempts", [])
                    if isinstance(item, dict) and item.get("attempt") == source_attempt), None)
    identity_matches = (
        isinstance(request, dict)
        and entry.get("request_identity_sha256") == request.get("fingerprint")
        and entry.get("related_identity") == (request.get("shot_id") or request.get("entity_id"))
        and entry.get("media_type") == request.get("media_type")
        and entry.get("provider") == request.get("provider")
    )
    ownership_safe = (
        isinstance(attempt, dict)
        and attempt.get("status") == "SUCCEEDED"
        and attempt.get("attribution_state") == "CONFIRMED"
        and attempt.get("attribution_status") != "INVALIDATED"
        and not any(isinstance(item, dict) and (
            str(item.get("status", "")).startswith("FAILED") or item.get("status") == "AMBIGUOUS"
            or item.get("attribution_state") in {"UNCERTAIN", "AMBIGUOUS"}
        ) for item in entry.get("attempts", []))
    )
    return (entry.get("status") == "QC_PENDING" and entry.get("failure_class") is None
            and isinstance(selected, dict) and selected.get("production_qc") == "PENDING"
            and identity_matches and ownership_safe and _valid_selected(paths, entry))


def _automatic_image_qc(paths, request: dict, entry: dict,
                        router: GeminiReasoningRouter) -> tuple[dict, dict]:
    """Evaluate exact selected IMAGE bytes against the production rubric and shot intent."""
    selected = entry["selected_asset"]
    asset_path = paths.artifact_path(selected["path"])
    try:
        shots = read_json(paths.artifact_path("output/shot_plan.json")).get("shots", [])
    except Exception as error:
        raise FlowError("AUTOMATIC_QC_CANONICAL_INPUT_INVALID") from error
    shot = next((item for item in shots if isinstance(item, dict)
                 and item.get("shot_id") == request.get("shot_id")), None)
    if request.get("purpose") == "SHOT" and not isinstance(shot, dict):
        raise FlowError("AUTOMATIC_QC_CANONICAL_INPUT_INVALID")
    intent = {
        "request_id": request.get("request_id"),
        "shot_id": request.get("shot_id"),
        "prompt": request.get("prompt"),
        "shot": shot,
    }
    prompt = (
        "Review this exact production image. Evaluate every naturalness field strictly from visible evidence. "
        "Mark AI_POLISH FAIL for conspicuous synthetic, waxy, overprocessed, malformed, or implausible details. "
        "Mark TECHNICAL_VALIDITY FAIL for corrupt, unusable, severely blurred, or compositionally broken output. "
        "Detect any visible provider watermark. Compare the visible subject, action, location, critical props, "
        "story beat, and continuity to the structured request and shot. PASS_ATMOSPHERIC is allowed only when "
        "the shot explicitly has atmospheric=true. Use UNCERTAIN rather than guessing. Return structured JSON only.\n"
        + json.dumps(intent, ensure_ascii=False, sort_keys=True)
    )
    result = router.reason(
        task="automatic_image_qc", prompt=prompt, schema=AUTOMATIC_IMAGE_QC_SCHEMA,
        tier="BULK", media=(LLMMedia(asset_path.read_bytes(), "image/png", "exact selected production image"),),
        prompt_version="automatic-image-qc/1.0.0", schema_version=AUTOMATIC_IMAGE_QC_VERSION,
        qc_policy_version="auto-accept-production/1.0.0", confidence_field="confidence",
    )
    value = result.value
    report = {
        "results": value.get("results"),
        "visible_provider_watermark": value.get("visible_provider_watermark"),
        "reviewer": "GeminiReasoningRouter",
        "notes": str(value.get("observed", "")).strip(),
    }
    evaluation = {
        "schema_version": AUTOMATIC_IMAGE_QC_VERSION,
        "request_id": request.get("request_id"),
        "selected_asset_path": selected.get("path"),
        "selected_asset_sha256": selected.get("sha256"),
        "model": result.model,
        "credential_alias": result.credential_alias,
        "project_alias": result.project_alias,
        "cache_hit": result.cache_hit,
        "fallback_count": result.fallback_count,
        "request_count": result.request_count,
        "input_hash": result.input_hash,
        "report": {**report, "alignment_classification": value.get("alignment_classification"),
                   "confidence": value.get("confidence"),
                   "observed": str(value.get("observed", "")).strip(),
                   "contradictions": list(value.get("contradictions") or [])},
    }
    try:
        validated = validate_production_qc(report, provider=entry.get("provider"),
                                           media_type=entry.get("media_type"))
    except MediaQualityError as error:
        if error.failure_class == "MEDIA_QC_INVALID":
            raise FlowError("GEMINI_QC_UNCERTAIN") from error
        error.automated_quality_evaluation = evaluation
        raise
    classification = value.get("alignment_classification")
    contradictions = value.get("contradictions")
    confidence = value.get("confidence")
    if contradictions or classification == "FAIL_MISMATCH":
        error = MediaQualityError("VISUAL_NARRATION_ALIGNMENT_MISMATCH")
        error.automated_quality_evaluation = evaluation
        raise error
    if classification == "PASS_ATMOSPHERIC" and not (shot or {}).get("atmospheric"):
        error = MediaQualityError("VISUAL_NARRATION_ALIGNMENT_MISMATCH")
        error.automated_quality_evaluation = evaluation
        raise error
    if classification not in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"} or confidence in {"LOW", "UNCERTAIN"}:
        raise FlowError("GEMINI_QC_UNCERTAIN")
    evaluation["report"] = {**validated, "alignment_classification": classification,
                            "confidence": confidence, "observed": str(value.get("observed", "")).strip(),
                            "contradictions": list(contradictions or [])}
    return evaluation["report"], evaluation


def _record_automatic_qc_rejection(entry: dict, error: MediaQualityError,
                                   evaluation: dict | None = None) -> None:
    selected = entry["selected_asset"]
    at = _now()
    rejection = {
        "reviewed_at": at, "status": "REJECTED", "failure_class": error.failure_class,
        "selected_asset_path": selected.get("path"),
        "selected_asset_sha256": selected.get("sha256"),
        "selected_attempt": selected.get("source_provider_attempt", selected.get("attempt")),
    }
    if evaluation is not None:
        rejection["automated_quality_evaluation"] = evaluation
    entry.setdefault("quality_reviews", []).append(rejection)
    selected["production_qc"] = "REJECTED"
    entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": at})


def _record_editorial_acceptance(entry: dict, *, policy: str, actor: str, disposition: str,
                                 reason: str | None, scope: str) -> dict:
    selected = entry["selected_asset"]
    source_attempt = selected.get("source_provider_attempt", selected.get("attempt"))
    decision = {
        "reviewed_at": _now(), "status": "OWNER_ACCEPTED" if actor == "OWNER" else "AUTO_ACCEPTED",
        "decision": "ACCEPT", "disposition": disposition, "actor": actor, "policy": policy,
        "scope": scope, "selected_asset_path": selected.get("path"),
        "selected_asset_sha256": selected.get("sha256"), "selected_attempt": source_attempt,
        "ownership_state": "CONFIRMED", "technical_integrity": "PASSED",
    }
    if reason:
        decision["reason"] = reason
    entry.setdefault("quality_reviews", []).append(decision)
    selected["production_qc"] = "OWNER_ACCEPTED" if actor == "OWNER" else "AUTO_ACCEPTED"
    entry.update({"status": "SUCCEEDED", "failure_class": None, "updated_at": decision["reviewed_at"]})
    return decision


def apply_auto_accept_policy(runtime_root: Path | str, project_id: str, *,
                             router: GeminiReasoningRouter | None = None) -> dict:
    """Apply AUTO_ACCEPT after technical/provenance and automated image QC pass.

    This command has no Flow boundary. Failed, unreadable, wrong-type, ambiguous,
    or uncertain assets are never accepted.
    """
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    policy, _explicit = effective_qc_policy(config.settings)
    if policy != AUTO_ACCEPT:
        raise FlowError("QC_POLICY_NOT_AUTO_ACCEPT")
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        try:
            requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
        except Exception as error:
            raise FlowError("GENERATION_REQUESTS_INVALID") from error
        by_id = {item.get("request_id"): item for item in requests if isinstance(item, dict)}
        active_router = router
        accepted = already_accepted = rejected = 0
        ineligible: list[str] = []
        for entry in manifest["requests"]:
            if not isinstance(entry, dict):
                continue
            selected = entry.get("selected_asset")
            if entry.get("status") == "SUCCEEDED" and isinstance(selected, dict) and selected.get("production_qc") == "AUTO_ACCEPTED":
                already_accepted += 1
                continue
            if entry.get("status") != "QC_PENDING":
                continue
            if not _technical_integrity_eligible(paths, entry, by_id.get(entry.get("request_id"))):
                ineligible.append(str(entry.get("request_id", "")))
                continue
            request = by_id[entry["request_id"]]
            if entry.get("media_type") != "IMAGE":
                ineligible.append(str(entry.get("request_id", "")))
                continue
            if active_router is None:
                active_router = GeminiReasoningRouter(
                    cache_dir=paths.runtime.cache / "gemini_reasoning",
                    ledger_path=paths.runtime.evidence / "gemini_reasoning_ledger.json",
                )
            try:
                report, evaluation = _automatic_image_qc(paths, request, entry, active_router)
            except MediaQualityError as error:
                _record_automatic_qc_rejection(
                    entry, error, getattr(error, "automated_quality_evaluation", None))
                rejected += 1
                continue
            decision = _record_editorial_acceptance(
                entry, policy=AUTO_ACCEPT, actor="SYSTEM", disposition="AUTO_ACCEPTED",
                reason=None, scope="ASSET")
            decision["automated_quality_evaluation"] = evaluation
            entry["selected_asset"]["alignment_classification"] = report["alignment_classification"]
            entry["selected_asset"]["alignment_observation"] = report["observed"]
            accepted += 1
        if accepted or rejected:
            atomic_write_json(path, manifest)
        return {"status": "AUTO_ACCEPTED", "project_id": project_id, "accepted_assets": accepted,
                "already_auto_accepted_assets": already_accepted, "ineligible_assets": ineligible,
                "rejected_assets": rejected,
                "provider_dispatch_delta": 0}


def accept_selected_assets_by_owner(runtime_root: Path | str, project_id: str, reason: str,
                                    request_ids: set[str] | None = None) -> dict:
    """Apply a truthful Manual-review owner decision to selected eligible assets.

    This is intentionally distinct from ``review_production_asset``: it records
    that manual visual review was skipped by the owner, rather than fabricating
    a per-asset manual-review report.  It never dispatches a provider request.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("OWNER_ACCEPTANCE_REASON_REQUIRED")
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    policy, _explicit = effective_qc_policy(config.settings)
    if policy != MANUAL_REVIEW:
        raise FlowError("QC_POLICY_NOT_MANUAL_REVIEW")
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        try:
            requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
        except Exception as error:
            raise FlowError("GENERATION_REQUESTS_INVALID") from error
        requests_by_id = {item.get("request_id"): item for item in requests if isinstance(item, dict)}
        requested = set(request_ids) if request_ids is not None else None
        accepted = already_accepted = 0
        accepted_images = accepted_videos = 0
        ineligible: list[str] = []
        accepted_asset_set: list[dict] = []
        for entry in manifest["requests"]:
            if not isinstance(entry, dict):
                continue
            selected = entry.get("selected_asset")
            request_id = entry.get("request_id")
            if requested is not None and request_id not in requested:
                continue
            if (entry.get("status") == "SUCCEEDED" and isinstance(selected, dict)
                    and selected.get("production_qc") == "OWNER_ACCEPTED"):
                already_accepted += 1
                continue
            if entry.get("status") != "QC_PENDING":
                continue
            if not _technical_integrity_eligible(paths, entry, requests_by_id.get(request_id)):
                if requested is not None:
                    raise FlowError("OWNER_ACCEPTANCE_ASSET_INELIGIBLE", str(request_id or ""))
                ineligible.append(str(request_id or ""))
                continue
            scope = "BATCH" if requested is None or len(requested) != 1 else "SELECTED"
            _record_editorial_acceptance(entry, policy=MANUAL_REVIEW, actor="OWNER",
                                         disposition="MANUAL_REVIEW_SKIPPED", reason=reason.strip(), scope=scope)
            accepted_asset_set.append({"request_id": request_id, "path": selected.get("path"), "sha256": selected.get("sha256")})
            accepted += 1
            if entry.get("media_type") == "IMAGE": accepted_images += 1
            elif entry.get("media_type") == "VIDEO": accepted_videos += 1
        if accepted:
            manifest.setdefault("quality_batches", []).append({
                "recorded_at": _now(), "decision": "ACCEPT", "scope": "BATCH" if requested is None or len(requested) != 1 else "SELECTED",
                "actor": "OWNER", "policy": MANUAL_REVIEW, "disposition": "MANUAL_REVIEW_SKIPPED",
                "reason": reason.strip(), "asset_set": accepted_asset_set,
            })
            atomic_write_json(path, manifest)
        return {
            "status": "OWNER_ACCEPTED", "project_id": project_id, "accepted_assets": accepted,
            "accepted_images": accepted_images, "accepted_videos": accepted_videos,
            "already_owner_accepted_assets": already_accepted, "already_owner_accepted_images": already_accepted,
            "ineligible_assets": ineligible, "new_image_requests": 0, "video_requests": 0, "provider_dispatch_delta": 0,
        }


def accept_pending_visuals_by_owner(runtime_root: Path | str, project_id: str, reason: str) -> dict:
    """Compatibility name for accepting every technically eligible pending asset."""
    return accept_selected_assets_by_owner(runtime_root, project_id, reason, None)


def reopen_malformed_production_qc_report(runtime_root: Path | str, project_id: str, request_id: str,
                                          *, expected_asset_sha256: str, reviewer: str, reason: str) -> dict:
    """Reopen one exact asset after a legacy malformed-QC rejection.

    Older callers could persist ``MEDIA_QC_INVALID`` as a rejection even
    though no naturalness decision was made.  This narrow recovery preserves
    that record, proves it still binds the current confirmed bytes, and starts
    a fresh identity-bound QC epoch.  It never calls a provider or changes an
    attempt.
    """
    if (not isinstance(expected_asset_sha256, str)
            or len(expected_asset_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_asset_sha256.lower())
            or not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(reason, str) or not reason.strip()):
        raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        matches = [item for item in manifest["requests"]
                   if isinstance(item, dict) and item.get("request_id") == request_id]
        if len(matches) != 1:
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        entry = matches[0]
        selected = entry.get("selected_asset")
        events = entry.get("malformed_production_qc_reopen_events")
        if events not in (None, []) and not isinstance(events, list):
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        if events:
            existing = events[-1] if len(events) == 1 and isinstance(events[-1], dict) else None
            if (isinstance(existing, dict) and existing.get("request_id") == request_id
                    and existing.get("selected_asset_sha256") == expected_asset_sha256.lower()
                    and isinstance(selected, dict)
                    and existing.get("selected_attempt") == selected.get("attempt")
                    and selected.get("active_production_review_epoch") == existing.get("review_epoch")
                    and entry.get("status") == "QC_PENDING"):
                return {**existing, "idempotent": True}
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        if (entry.get("status") != "FAILED_RETRYABLE"
                or entry.get("failure_class") != "MEDIA_QC_INVALID"
                or not isinstance(selected, dict)
                or selected.get("sha256") != expected_asset_sha256.lower()
                or not _valid_selected(paths, entry)):
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        reviews = entry.get("quality_reviews")
        rejection = reviews[-1] if isinstance(reviews, list) and reviews else None
        if (not isinstance(rejection, dict) or rejection.get("status") != "REJECTED"
                or rejection.get("failure_class") != "MEDIA_QC_INVALID"
                or rejection.get("selected_asset_path") != selected.get("path")
                or rejection.get("selected_asset_sha256") != expected_asset_sha256.lower()
                or not isinstance(rejection.get("report"), dict)):
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        try:
            validate_production_qc(rejection["report"], provider=entry.get("provider"), media_type=entry.get("media_type"))
        except MediaQualityError as error:
            if error.failure_class != "MEDIA_QC_INVALID":
                raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID") from error
        else:
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        selected_attempt = selected.get("attempt")
        attempts = entry.get("attempts")
        attempt = next((item for item in attempts if isinstance(item, dict) and item.get("attempt") == selected_attempt), None) if isinstance(attempts, list) else None
        if (not isinstance(selected_attempt, int) or not isinstance(attempt, dict)
                or attempt.get("status") != "SUCCEEDED" or attempt.get("attribution_state") != "CONFIRMED"):
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        try:
            requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
        except Exception as error:
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID") from error
        descendants = [item for item in [*requests, *manifest["requests"]] if isinstance(item, dict)
                       and item.get("request_id") != request_id
                       and (item.get("replacement_of") == request_id or item.get("replaces_request_id") == request_id)]
        if entry.get("replacement_request_id") or descendants:
            raise FlowError("MALFORMED_PRODUCTION_QC_REOPEN_INVALID")
        rejection_index = len(reviews) - 1
        rejection_sha256 = _json_sha256(rejection)
        event = {
            "at": _now(), "event": "MALFORMED_PRODUCTION_QC_REOPENED",
            "disposition": "MALFORMED_REPORT_SUPERSEDED", "reviewer": reviewer.strip(),
            "reason": reason.strip(), "request_id": request_id,
            "selected_asset_path": selected.get("path"), "selected_asset_sha256": expected_asset_sha256.lower(),
            "selected_attempt": selected_attempt, "superseded_rejection_index": rejection_index,
            "rejection_event_sha256": rejection_sha256,
            "review_epoch": "production-qc-malformed-" + _json_sha256({
                "request_id": request_id, "asset_sha256": expected_asset_sha256.lower(),
                "attempt": selected_attempt, "rejection_event_sha256": rejection_sha256,
            })[:24],
        }
        entry.setdefault("malformed_production_qc_reopen_events", []).append(event)
        selected["production_qc"] = "PENDING"
        selected["active_production_review_epoch"] = event["review_epoch"]
        entry.update({"status": "QC_PENDING", "failure_class": None, "updated_at": _now()})
        atomic_write_json(path, manifest)
        return {**event, "idempotent": False}


def reopen_false_positive_production_qc(runtime_root: Path | str, project_id: str, request_id: str,
                                        *, expected_asset_sha256: str, reviewer: str, reason: str) -> dict:
    """Append a narrowly bound appeal event, then return identical bytes to QC.

    This never authorizes Flow execution and never changes the rejected review.
    It is deliberately restricted to an exact eligible production-QC rejection whose
    persisted review either binds the selected asset directly or is a proven
    pre-Goal37 legacy record with no intervening ownership-changing history.
    """
    if (not isinstance(expected_asset_sha256, str)
            or len(expected_asset_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_asset_sha256.lower())
            or not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(reason, str) or not reason.strip()):
        raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        matches = [item for item in manifest["requests"] if isinstance(item, dict) and item.get("request_id") == request_id]
        if len(matches) != 1:
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        entry = matches[0]
        selected = entry.get("selected_asset")
        events = entry.get("qc_false_positive_reopen_events")
        if events not in (None, []) and not isinstance(events, list):
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        if events:
            existing = events[-1] if len(events) == 1 and isinstance(events[-1], dict) else None
            if (isinstance(existing, dict) and existing.get("request_id") == request_id
                    and existing.get("selected_asset_sha256") == expected_asset_sha256.lower()
                    and existing.get("selected_attempt") == (selected or {}).get("attempt")
                    and isinstance(selected, dict)
                    and isinstance(existing.get("review_epoch"), str) and existing["review_epoch"]
                    and selected.get("active_production_review_epoch") == existing.get("review_epoch")
                    and entry.get("status") == "QC_PENDING"):
                return {**existing, "idempotent": True}
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        failure_class = entry.get("failure_class")
        if (entry.get("status") != "FAILED_RETRYABLE"
                or failure_class not in FALSE_POSITIVE_PRODUCTION_QC_FAILURES
                or not isinstance(selected, dict)
                or selected.get("sha256") != expected_asset_sha256.lower()
                or not _valid_selected(paths, entry)):
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        reviews = entry.get("quality_reviews")
        if not isinstance(reviews, list) or not reviews:
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        rejection_index = len(reviews) - 1
        rejection = reviews[rejection_index]
        if (not isinstance(rejection, dict) or rejection.get("status") != "REJECTED"
                or rejection.get("failure_class") != failure_class
                or not isinstance(rejection.get("report"), dict)):
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        try:
            requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
        except Exception as error:
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID") from error
        current = [item for item in requests if isinstance(item, dict) and item.get("request_id") == request_id]
        if len(current) != 1:
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        descendants = [
            item for item in [*requests, *manifest["requests"]] if isinstance(item, dict)
            and item.get("request_id") != request_id
            and (item.get("replacement_of") == request_id or item.get("replaces_request_id") == request_id)
        ]
        if entry.get("replacement_request_id") or descendants:
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        selected_attempt = selected.get("attempt")
        attempt = next((item for item in entry.get("attempts", [])
                        if isinstance(item, dict) and item.get("attempt") == selected_attempt), None)
        if (not isinstance(selected_attempt, int) or not isinstance(attempt, dict)
                or attempt.get("status") != "SUCCEEDED" or attempt.get("attribution_state") != "CONFIRMED"):
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        binding_fields = (rejection.get("selected_asset_path"), rejection.get("selected_asset_sha256"))
        if binding_fields == (selected.get("path"), expected_asset_sha256.lower()):
            compatibility_mode = None
            event_type = "QC_FALSE_POSITIVE_REOPENED"
        elif binding_fields == (None, None) and _legacy_qc_rejection_binding_proven(entry, selected, rejection):
            compatibility_mode = "LEGACY_PRE_GOAL37"
            event_type = "LEGACY_QC_REJECTION_ASSET_BINDING_RECONCILED"
        else:
            raise FlowError("QC_FALSE_POSITIVE_REOPEN_INVALID")
        event = {
            "at": _now(), "event": event_type, "disposition": "FALSE_POSITIVE_REOPENED", "reviewer": reviewer.strip(),
            "reason": reason.strip(), "request_id": request_id, "selected_asset_path": selected.get("path"),
            "selected_asset_sha256": expected_asset_sha256.lower(), "superseded_rejection_index": rejection_index,
            "rejection_event_sha256": _json_sha256(rejection), "selected_attempt": selected_attempt,
        }
        if failure_class == "VISIBLE_PROVIDER_WATERMARK":
            event["review_epoch"] = "production-qc-" + _json_sha256({
                "request_id": request_id, "asset_sha256": expected_asset_sha256.lower(),
                "attempt": selected_attempt, "rejection_event_sha256": event["rejection_event_sha256"],
            })[:24]
        if compatibility_mode is not None:
            event["compatibility_mode"] = compatibility_mode
        entry.setdefault("qc_false_positive_reopen_events", []).append(event)
        selected["production_qc"] = "PENDING"
        if failure_class == "VISIBLE_PROVIDER_WATERMARK":
            selected["active_production_review_epoch"] = event["review_epoch"]
        entry.update({"status": "QC_PENDING", "failure_class": None, "updated_at": _now()})
        atomic_write_json(path, manifest)
        return {**event, "idempotent": False}


def _legacy_qc_rejection_binding_proven(entry: dict, selected: dict, rejection: dict) -> bool:
    """Prove a pre-Goal37 unbound rejection still refers to these exact bytes.

    Legacy reviews contain no asset identity.  They are eligible only when the
    surrounding append-only state provides one unambiguous selected-provider
    attempt and no state change that could have rebound the review to another
    asset.  Absence is never treated as evidence where a required fact is
    missing.
    """
    if not isinstance(rejection.get("reviewed_at"), str):
        return False
    try:
        reviewed_at = datetime.fromisoformat(rejection["reviewed_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    attempts = entry.get("attempts")
    selected_attempt = selected.get("source_provider_attempt", selected.get("attempt"))
    if (not isinstance(attempts, list) or not isinstance(selected_attempt, int) or selected_attempt < 1
            or selected.get("attempt") not in {None, selected_attempt}
            or len(attempts) != selected_attempt or any(not isinstance(item, dict) for item in attempts)):
        return False
    attempt = attempts[-1] if attempts else None
    if (not isinstance(attempt, dict) or attempt.get("attempt") != selected_attempt
            or attempt.get("status") != "SUCCEEDED" or attempt.get("attribution_state") != "CONFIRMED"
            or attempt.get("attribution_status") == "INVALIDATED"
            or attempt.get("dispatch_origin") in {"operator_local_override", "human_exact_flow_recovery"}
            or not isinstance(attempt.get("completed_at"), str)):
        return False
    try:
        selected_at = datetime.fromisoformat(attempt["completed_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    if selected_at > reviewed_at:
        return False
    if selected.get("postprocess_attempt") is None:
        if attempt.get("asset_path") != selected.get("path") or attempt.get("asset_sha256") != selected.get("sha256"):
            return False
        if entry.get("postprocess_attempts") not in (None, []):
            return False
    else:
        records = entry.get("postprocess_attempts")
        processing_number = selected.get("postprocess_attempt")
        if (not isinstance(processing_number, int) or not isinstance(records, list)
                or len(records) != processing_number or not records or not isinstance(records[-1], dict)):
            return False
        processed = records[-1]
        if (processed.get("status") != "SUCCEEDED"
                or processed.get("source_provider_attempt") != selected_attempt
                or processed.get("source_path") != attempt.get("asset_path")
                or processed.get("source_sha256") != attempt.get("asset_sha256")
                or processed.get("output_path") != selected.get("path")
                or processed.get("output_sha256") != selected.get("sha256")
                or not isinstance(processed.get("completed_at"), str)):
            return False
        try:
            if datetime.fromisoformat(processed["completed_at"].replace("Z", "+00:00")) > reviewed_at:
                return False
        except ValueError:
            return False
    # Any one of these records proves that a later mutation/recovery can no
    # longer be distinguished from the legacy review's original selected asset.
    for key in ("attribution_invalidations", "manual_recovery_events", "asset_rebindings", "selected_asset_events"):
        if entry.get(key) not in (None, []):
            return False
    return True


def _repair_local_video(paths, entry: dict, request: dict) -> bool:
    """Retry cleanup from preserved raw video bytes, never Flow generation."""
    if request.get("media_type") != "VIDEO" or request.get("execution_tier") != "STANDARD_PRODUCTION":
        return False
    attempt, _ = _successful_raw_video(paths, entry)
    if attempt is None:
        return False
    selected = entry.get("selected_asset")
    lineage_matches = isinstance(selected, dict) and selected.get("source_provider_attempt") == attempt.get("attempt")
    local_failure = entry.get("failure_class") in LOCAL_VIDEO_FAILURES
    # A production/temporal rejection is durable evidence about these exact
    # selected bytes.  It is never a missing derivative and must not be
    # silently turned back into QC_PENDING by local reconciliation.
    derivative_invalid = (entry.get("status") in {"SUCCEEDED", "QC_PENDING"}
                          and lineage_matches and not _valid_selected(paths, entry))
    if not local_failure and not derivative_invalid:
        return False
    try:
        _process_raw_video(paths, entry, attempt, output_rel=(selected or {}).get("path"))
    except FlowVideoPostprocessError:
        pass
    return True


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
        if state not in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW", *TERMINAL_TEMPORAL_FAILURES, "UNCERTAIN"}:
            raise FlowError("TEMPORAL_VIDEO_QC_INVALID")
        review = {
            "reviewed_at": _now(), "report": report,
            "selected_asset_path": selected.get("path"),
            "selected_asset_sha256": selected.get("sha256"),
            "selected_attempt": selected.get("attempt"),
            "media_sha256": selected.get("sha256"),
        }
        review_epoch = selected.get("active_temporal_review_epoch")
        if review_epoch is not None:
            frame_evidence = report.get("frame_evidence")
            if (report.get("review_identity") != review_epoch
                    or report.get("request_id") != request_id
                    or report.get("attempt") != selected.get("attempt")
                    or report.get("media_sha256") != selected.get("sha256")
                    or not isinstance(frame_evidence, list) or not frame_evidence
                    or any(not isinstance(item, dict) or not isinstance(item.get("sha256"), str)
                           or len(item["sha256"]) != 64 for item in frame_evidence)):
                raise FlowError("TEMPORAL_VIDEO_QC_FRESH_EVIDENCE_INVALID")
            review.update({"review_epoch": review_epoch, "frame_evidence": frame_evidence})
        elif isinstance(report.get("frame_evidence"), list):
            review["frame_evidence"] = report["frame_evidence"]
        selected.setdefault("temporal_reviews", []).append(review)
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
        if review_epoch is not None:
            selected["completed_temporal_review_epoch"] = review_epoch
            selected.pop("active_temporal_review_epoch", None)
        semantic_ready = selected.get("production_qc") == "APPROVED" and selected.get("alignment_classification") in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"}
        entry.update({"status": "SUCCEEDED" if semantic_ready else "QC_PENDING",
                      "failure_class": None if semantic_ready else "VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def create_local_video_mark_removal(runtime_root: Path | str, project_id: str, request_id: str, *,
                                    expected_source_sha256: str) -> dict:
    """Append one exact-byte Flow-mark cleanup derivative for a rejected video.

    This never retries or changes a provider attempt.  It is limited to one
    visible-watermark rejection that is bound to the current confirmed source
    bytes; the original selected asset and rejection remain immutable history.
    """
    expected_sha = expected_source_sha256.lower() if isinstance(expected_source_sha256, str) else ""
    if len(expected_sha) != 64 or any(char not in "0123456789abcdef" for char in expected_sha):
        raise FlowError("VIDEO_MARK_REMOVAL_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if (not isinstance(entry, dict) or entry.get("media_type") != "VIDEO"
                or entry.get("status") != "FAILED_RETRYABLE"
                or entry.get("failure_class") != "VISIBLE_PROVIDER_WATERMARK"
                or not isinstance(selected, dict) or selected.get("sha256") != expected_sha
                or not _valid_selected(paths, entry)
                or entry.get("video_mark_removals") not in (None, [])):
            raise FlowError("VIDEO_MARK_REMOVAL_NOT_ELIGIBLE")
        source_path = paths.artifact_path(selected["path"])
        if sha256_file(source_path) != expected_sha:
            raise FlowError("VIDEO_MARK_REMOVAL_NOT_ELIGIBLE")
        source_attempt = selected.get("attempt")
        attempt = next((item for item in entry.get("attempts", [])
                        if isinstance(item, dict) and item.get("attempt") == source_attempt), None)
        if (not isinstance(source_attempt, int) or not isinstance(attempt, dict)
                or attempt.get("status") != "SUCCEEDED"
                or attempt.get("attribution_state") != "CONFIRMED"
                or attempt.get("asset_path") != selected.get("path")
                or attempt.get("asset_sha256") != expected_sha):
            raise FlowError("VIDEO_MARK_REMOVAL_NOT_ELIGIBLE")
        reviews = entry.get("quality_reviews")
        latest = reviews[-1] if isinstance(reviews, list) and reviews else None
        if (not isinstance(latest, dict) or latest.get("status") != "REJECTED"
                or latest.get("failure_class") != "VISIBLE_PROVIDER_WATERMARK"
                or latest.get("selected_asset_path") != selected.get("path")
                or latest.get("selected_asset_sha256") != expected_sha):
            raise FlowError("VIDEO_MARK_REMOVAL_NOT_ELIGIBLE")
        transform = {
            "operation": VIDEO_MARK_REMOVAL_EVENT,
            "parent_asset_path": selected["path"],
            "parent_asset_sha256": expected_sha,
            "parent_provider_attempt": source_attempt,
            "semantic_content_insertion": False,
            "provider_submission": False,
        }
        transform_sha = _json_sha256(transform)
        rel = f"assets/video/{request_id}/derived/video_mark_removal_{transform_sha[:16]}.mp4"
        output = paths.artifact_path(rel)
        staged = output.with_name(output.stem + ".staged" + output.suffix)
        if output.exists() or staged.exists():
            raise FlowError("VIDEO_MARK_REMOVAL_OUTPUT_CONFLICT")
        try:
            result = process_flow_video(source_path, staged)
            staged.replace(output)
        except FlowVideoPostprocessError as error:
            if staged.exists():
                staged.unlink()
            raise FlowError(error.failure_class, str(error)) from error
        derived_sha = result.get("output_sha256")
        if not isinstance(derived_sha, str) or sha256_file(output) != derived_sha:
            raise FlowError("VIDEO_MARK_REMOVAL_DERIVATIVE_INVALID")
        event = {
            "event": "VIDEO_MARK_REMOVAL_CREATED",
            "at": _now(),
            "source_entry_state": {"status": entry.get("status"), "failure_class": entry.get("failure_class")},
            "source_selected_asset": copy.deepcopy(selected),
            "source_selected_asset_sha256": expected_sha,
            "source_rejection": copy.deepcopy(latest),
            "transform": transform,
            "transform_sha256": transform_sha,
            "derived_asset_path": rel,
            "derived_asset_sha256": derived_sha,
            "derived_metadata": result["output_metadata"],
            "processor_name": result["processor_name"],
            "processor_version": result["processor_version"],
            "flow_mark_profile_version": result["profile_version"],
            "mask_sha256": result["mask_sha256"],
        }
        derived = {
            "path": rel, "sha256": derived_sha, "attempt": source_attempt,
            "metadata": result["output_metadata"], "production_qc": "PENDING", "temporal_qc": "PENDING",
            "provenance": VIDEO_MARK_REMOVAL_EVENT, "parent_asset_path": selected["path"],
            "parent_asset_sha256": expected_sha, "parent_provider_attempt": source_attempt,
            "transform": transform, "transform_sha256": transform_sha,
            "processor_name": result["processor_name"], "processor_version": result["processor_version"],
            "flow_mark_profile_version": result["profile_version"], "mask_sha256": result["mask_sha256"],
        }
        entry.setdefault("video_mark_removals", []).append(event)
        entry.update({"selected_asset": derived, "status": "QC_PENDING", "failure_class": None, "updated_at": _now()})
        atomic_write_json(path, manifest)
        return {"selected_asset": derived, "source_asset_sha256": expected_sha,
                "provider_submissions": entry.get("provider_submissions", 0), "idempotent": False}


def create_local_temporal_salvage(runtime_root: Path | str, project_id: str, request_id: str, *,
                                  expected_source_sha256: str, clean_start: float, clean_end: float,
                                  target_duration: float) -> dict:
    """Append one bounded trim/retime child asset for a terminal temporal reject.

    This is intentionally not a Flow recovery: provider attempts, dispatch, and
    attribution are left untouched.  The rejected selected asset is preserved
    as a complete immutable snapshot in the append-only salvage event while a
    newly derived byte sequence enters a fresh, asset-bound QC epoch.
    """
    expected_sha = expected_source_sha256.lower() if isinstance(expected_source_sha256, str) else ""
    if (len(expected_sha) != 64 or any(char not in "0123456789abcdef" for char in expected_sha)
            or not all(isinstance(value, (int, float)) for value in (clean_start, clean_end, target_duration))):
        raise FlowError("TEMPORAL_SALVAGE_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        try:
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            request = next(item for item in requests if item.get("request_id") == request_id)
        except Exception as error:
            raise FlowError("TEMPORAL_SALVAGE_INVALID") from error
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if (not isinstance(entry, dict) or entry.get("media_type") != "VIDEO"
                or entry.get("status") != "FAILED_RETRYABLE"
                or entry.get("failure_class") != "USABLE_TEMPORAL_WINDOW_INVALID"
                or not isinstance(selected, dict) or selected.get("sha256") != expected_sha
                or selected.get("temporal_qc") != "REJECTED" or not _valid_selected(paths, entry)
                or entry.get("temporal_asset_salvages") not in (None, [])):
            raise FlowError("TEMPORAL_SALVAGE_NOT_ELIGIBLE")
        source_path = paths.artifact_path(selected["path"])
        if sha256_file(source_path) != expected_sha:
            raise FlowError("TEMPORAL_SALVAGE_NOT_ELIGIBLE")
        source_attempt = selected.get("attempt")
        attempt = next((item for item in entry.get("attempts", [])
                        if isinstance(item, dict) and item.get("attempt") == source_attempt), None)
        if (not isinstance(source_attempt, int) or not isinstance(attempt, dict)
                or attempt.get("attribution_state") != "CONFIRMED"
                or attempt.get("asset_path") != selected.get("path")
                or attempt.get("asset_sha256") != expected_sha):
            raise FlowError("TEMPORAL_SALVAGE_NOT_ELIGIBLE")
        reviews = selected.get("temporal_reviews")
        latest = reviews[-1] if isinstance(reviews, list) and reviews else None
        latest_report = latest.get("report") if isinstance(latest, dict) else None
        if (not isinstance(latest_report, dict)
                or latest_report.get("state") != "USABLE_TEMPORAL_WINDOW_INVALID"):
            raise FlowError("TEMPORAL_SALVAGE_NOT_ELIGIBLE")
        reported_start = float(latest_report.get("usable_start", -1))
        reported_end = float(latest_report.get("usable_end", -1))
        canonical_target = float(request.get("target_duration", 0))
        if (abs(target_duration - canonical_target) > .0005 or clean_start != reported_start
                or clean_end > reported_end + 1e-9 or clean_end <= clean_start):
            raise FlowError("TEMPORAL_SALVAGE_WINDOW_INVALID")
        slowdown = target_duration / (clean_end - clean_start)
        if slowdown < 1 or slowdown > TEMPORAL_SALVAGE_MAX_SLOWDOWN + 1e-9:
            raise FlowError("TEMPORAL_SALVAGE_SLOWDOWN_INVALID")
        transform = {"operation": TEMPORAL_SALVAGE_EVENT, "parent_asset_sha256": expected_sha,
                     "parent_asset_path": selected["path"], "parent_provider_attempt": source_attempt,
                     "clean_start": clean_start, "clean_end": clean_end, "target_duration": target_duration,
                     "slowdown_factor": slowdown, "maximum_slowdown": TEMPORAL_SALVAGE_MAX_SLOWDOWN,
                     "synthetic_scene_generation": False, "semantic_content_insertion": False}
        transform_sha = _json_sha256(transform)
        rel = f"assets/video/{request_id}/derived/temporal_salvage_{transform_sha[:16]}.mp4"
        output = paths.artifact_path(rel)
        if output.exists():
            raise FlowError("TEMPORAL_SALVAGE_OUTPUT_CONFLICT")
        staged = output.with_name(output.stem + ".staged" + output.suffix)
        if staged.exists():
            raise FlowError("TEMPORAL_SALVAGE_OUTPUT_CONFLICT")
        try:
            metadata = derive_trim_retime_video(source_path, staged, clean_start=clean_start, clean_end=clean_end,
                                                 target_duration=target_duration,
                                                 maximum_slowdown=TEMPORAL_SALVAGE_MAX_SLOWDOWN)
            staged.replace(output)
        except MediaError as error:
            if staged.exists():
                staged.unlink()
            raise FlowError(error.failure_class, str(error)) from error
        derived_sha = metadata.get("sha256")
        if not isinstance(derived_sha, str) or sha256_file(output) != derived_sha:
            raise FlowError("TEMPORAL_SALVAGE_DERIVATIVE_INVALID")
        salvage_id = "temporal-salvage-" + transform_sha[:20]
        event = {"event": "TEMPORAL_SALVAGE_CREATED", "salvage_id": salvage_id, "at": _now(),
                 "source_entry_state": {"status": entry.get("status"), "failure_class": entry.get("failure_class")},
                 "source_selected_asset": copy.deepcopy(selected), "source_selected_asset_sha256": expected_sha,
                 "transform": transform, "transform_sha256": transform_sha,
                 "derived_asset_path": rel, "derived_asset_sha256": derived_sha,
                 "derived_metadata": metadata}
        review_epoch = "derived-" + transform_sha[:24]
        derived = {"path": rel, "sha256": derived_sha, "attempt": source_attempt, "metadata": metadata,
                   "production_qc": "PENDING", "temporal_qc": "PENDING",
                   "provenance": TEMPORAL_SALVAGE_EVENT, "parent_asset_path": selected["path"],
                   "parent_asset_sha256": expected_sha, "parent_provider_attempt": source_attempt,
                   "transform": transform, "transform_sha256": transform_sha,
                   "active_temporal_review_epoch": review_epoch}
        entry.setdefault("temporal_asset_salvages", []).append(event)
        entry.update({"selected_asset": derived, "status": "QC_PENDING",
                      "failure_class": "TEMPORAL_VIDEO_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)
        return {"salvage_id": salvage_id, "review_epoch": review_epoch, "selected_asset": derived,
                "source_asset_sha256": expected_sha, "provider_submissions": entry.get("provider_submissions", 0)}


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


def reopen_false_positive_temporal_qc(runtime_root: Path | str, project_id: str, request_id: str, *,
                                      expected_asset_sha256: str, expected_attempt: int,
                                      reviewer: str, reason: str, evidence: dict) -> dict:
    """Append one exact-byte temporal-QC false-positive appeal.

    This is the temporal sibling of ``reopen_false_positive_production_qc``.
    It preserves the rejected temporal review and merely creates a fresh,
    cache-distinct review epoch for the identical confirmed provider asset.
    """
    if (not isinstance(expected_asset_sha256, str) or len(expected_asset_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_asset_sha256.lower())
            or not isinstance(expected_attempt, int) or expected_attempt < 1
            or not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(reason, str) or not reason.strip()
            or not isinstance(evidence, dict) or not evidence):
        raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        matches = [item for item in manifest["requests"] if isinstance(item, dict) and item.get("request_id") == request_id]
        if len(matches) != 1:
            raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
        entry = matches[0]
        selected = entry.get("selected_asset")
        if (entry.get("media_type") != "VIDEO" or not isinstance(selected, dict)
                or selected.get("sha256") != expected_asset_sha256.lower()
                or selected.get("attempt") != expected_attempt
                or sha256_file(paths.artifact_path(str(selected.get("path", "")))) != expected_asset_sha256.lower()
                or not _valid_selected(paths, entry)):
            raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
        attempts = entry.get("attempts")
        attempt = next((item for item in attempts if isinstance(item, dict) and item.get("attempt") == expected_attempt), None) if isinstance(attempts, list) else None
        if (not isinstance(attempt, dict) or attempt.get("attribution_state") != "CONFIRMED"
                or attempt.get("asset_path") != selected.get("path")
                or attempt.get("asset_sha256") != expected_asset_sha256.lower()):
            raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
        reviews = selected.get("temporal_reviews")
        source_index = len(reviews) - 1 if isinstance(reviews, list) else -1
        source_review = reviews[source_index] if source_index >= 0 else None
        source_report = source_review.get("report") if isinstance(source_review, dict) else None
        source_state = source_report.get("state") if isinstance(source_report, dict) else None
        source_sha = _json_sha256(source_review)
        events = entry.get("temporal_qc_false_positive_supersessions")
        if events is not None and not isinstance(events, list):
            raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
        # Repeating the same still-active appeal must be a no-op.  This check
        # deliberately precedes the terminal-rejection state check because the
        # first call has already moved the asset to QC_PENDING.
        if events:
            existing = events[-1] if isinstance(events[-1], dict) else None
            if (isinstance(existing, dict) and entry.get("status") == "QC_PENDING"
                    and selected.get("temporal_qc") == "PENDING"
                    and existing.get("superseded_review_sha256") == source_sha
                    and existing.get("selected_asset_sha256") == expected_asset_sha256.lower()
                    and existing.get("selected_attempt") == expected_attempt):
                return {**existing, "idempotent": True}
            raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
        if (entry.get("status") != "FAILED_RETRYABLE" or entry.get("failure_class") != source_state
                or selected.get("temporal_qc") != "REJECTED"
                or not isinstance(source_state, str) or not source_state.startswith("REJECT_")):
            raise FlowError("TEMPORAL_QC_FALSE_POSITIVE_REOPEN_INVALID")
        supersession_id = "temporal-qc-fp-" + _json_sha256({
            "project_id": project_id, "request_id": request_id, "attempt": expected_attempt,
            "asset_sha256": expected_asset_sha256.lower(), "superseded_review_sha256": source_sha,
        })[:24]
        review_epoch = "temporal-review-" + _json_sha256({"supersession_id": supersession_id, "epoch": 1})[:24]
        event = {
            "at": _now(), "event": "TEMPORAL_QC_FALSE_POSITIVE_SUPERSEDED",
            "disposition": "FALSE_POSITIVE_REOPENED", "supersession_id": supersession_id,
            "request_id": request_id, "selected_asset_path": selected.get("path"),
            "selected_asset_sha256": expected_asset_sha256.lower(), "selected_attempt": expected_attempt,
            "superseded_review_index": source_index, "superseded_review_sha256": source_sha,
            "superseded_temporal_state": source_state, "review_epoch": review_epoch,
            "reviewer": reviewer.strip(), "reason": reason.strip(), "evidence": evidence,
        }
        entry.setdefault("temporal_qc_false_positive_supersessions", []).append(event)
        selected["temporal_qc"] = "PENDING"
        selected["active_temporal_review_epoch"] = review_epoch
        entry.update({"status": "QC_PENDING", "failure_class": None, "updated_at": event["at"]})
        atomic_write_json(path, manifest)
        return {**event, "idempotent": False}


def run_fresh_temporal_qc_review(runtime_root: Path | str, project_id: str, request_id: str, *,
                                 router: GeminiReasoningRouter | None = None) -> dict:
    """Perform the mandatory cache-distinct temporal review opened by an appeal."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    manifest_path, manifest = _manifest(paths, project_id)
    entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
    if not isinstance(entry, dict) or entry.get("status") != "QC_PENDING" or entry.get("media_type") != "VIDEO":
        raise FlowError("TEMPORAL_VIDEO_QC_FRESH_REVIEW_INVALID")
    selected = entry.get("selected_asset")
    review_epoch = selected.get("active_temporal_review_epoch") if isinstance(selected, dict) else None
    if (not isinstance(selected, dict) or not isinstance(review_epoch, str) or not review_epoch
            or not _valid_selected(paths, entry)):
        raise FlowError("TEMPORAL_VIDEO_QC_FRESH_REVIEW_INVALID")
    requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
    request = next((item for item in requests if isinstance(item, dict) and item.get("request_id") == request_id), None)
    if not isinstance(request, dict):
        raise FlowError("TEMPORAL_VIDEO_QC_FRESH_REVIEW_INVALID")
    metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
    duration = float(metadata.get("duration_seconds", 0))
    if duration <= 0:
        raise FlowError("TEMPORAL_VIDEO_QC_FRESH_REVIEW_INVALID")
    video = paths.artifact_path(selected["path"])
    risk = str((request.get("motion_risk_analysis") or {}).get("anatomy_risk", "LOW")).upper()
    frame_dir = paths.runtime.temp / "temporal_qc" / request_id / review_epoch
    frames = sample_dense_frames(video, frame_dir, risk=risk, duration=duration)
    intent = {"request_id": request_id, "shot_id": request.get("shot_id"), "prompt": request.get("prompt"),
              "corrected_semantic_intent": request.get("corrected_semantic_intent"),
              "motion_risk_analysis": request.get("motion_risk_analysis")}
    active_router = router or GeminiReasoningRouter(
        cache_dir=paths.runtime.cache / "gemini_reasoning",
        ledger_path=paths.runtime.evidence / "gemini_reasoning_ledger.json",
    )
    result, calls = temporal_video_qc(active_router, video=video, intent=intent, frames=frames,
                                      duration=duration, target_duration=float(request.get("target_duration", duration)),
                                      review_epoch=review_epoch)
    report = {**result, "review_identity": review_epoch, "request_id": request_id,
              "attempt": selected.get("attempt"), "media_sha256": selected.get("sha256"),
              "media_path": selected.get("path"), "frame_evidence": [
                  {"index": item["index"], "timestamp": item["timestamp"], "sha256": item["sha256"]}
                  for item in frames],
              "reviewer": "GeminiReasoningRouter",
              "gemini": [{"model": item.model, "cache_hit": item.cache_hit,
                           "input_hash": item.input_hash, "request_count": item.request_count}
                          for item in calls]}
    review_temporal_asset(runtime_root, project_id, request_id, report)
    return {"request_id": request_id, "review_epoch": review_epoch,
            "media_sha256": selected.get("sha256"), "cache_hit": all(item.cache_hit for item in calls),
            "report": report}


def _owned_mandatory_qc_rejection(entry: dict | None) -> bool:
    """Recognize the narrow historical state that requires a fresh epoch."""
    if not isinstance(entry, dict) or not isinstance(entry.get("selected_asset"), dict):
        return False
    if entry.get("status") != "FAILED_RETRYABLE":
        return False
    failure = entry.get("failure_class")
    reviews = entry.get("quality_reviews")
    qc_rejected = (isinstance(failure, str) and failure.endswith("_QC_REJECTED")) or (
        isinstance(reviews, list) and any(isinstance(item, dict) and item.get("status") == "REJECTED" for item in reviews)
    )
    creative_rejections = entry.get("creative_rejections")
    creative_rejected = (
        failure == "CREATIVE_REJECTED"
        and isinstance(creative_rejections, list)
        and any(isinstance(item, dict) and isinstance(item.get("reason"), str) and item["reason"].strip()
                for item in creative_rejections)
    )
    if not (qc_rejected or creative_rejected):
        return False
    attempts = entry.get("attempts")
    selected_attempt = entry["selected_asset"].get("attempt")
    return (isinstance(attempts, list) and any(
        isinstance(attempt, dict) and attempt.get("attempt") == selected_attempt
        and attempt.get("attribution_state") == "CONFIRMED"
        for attempt in attempts
    ))


def _creative_correction_epoch(request: dict, entry: dict) -> int:
    """Return the correction epoch only for one owned, attributed lineage tip."""
    epoch = request.get("creative_correction_epoch", entry.get("creative_correction_epoch"))
    if epoch is None:
        # Older transactions use replacement_epoch for more than creative QC
        # lineage.  Only an immediately prior canonical QC replacement counts
        # as creative correction epoch one.
        epoch = 1 if request.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON else 0
    if not isinstance(epoch, int) or epoch < 0:
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_INVALID")
    if not _owned_mandatory_qc_rejection(entry):
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_NOT_ELIGIBLE")
    selected_attempt = entry["selected_asset"].get("attempt")
    attempt = next((item for item in entry.get("attempts", [])
                    if isinstance(item, dict) and item.get("attempt") == selected_attempt), None)
    if not isinstance(attempt, dict) or attempt.get("attribution_state") != "CONFIRMED":
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_NOT_ELIGIBLE")
    dispatch_confirmed = (attempt.get("dispatch_confirmation_state") == "CONFIRMED"
                          or attempt.get("dispatch_confirmed") is True)
    if not dispatch_confirmed or attempt.get("attribution_state") in {"UNCERTAIN", "AMBIGUOUS"}:
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_NOT_ELIGIBLE")
    return epoch


def _creative_correction_root_id(request: dict, entries: dict[str, dict]) -> str:
    current = request.get("request_id")
    root = request.get("root_request_id")
    if isinstance(root, str) and root:
        return root
    seen: set[str] = set()
    while isinstance(current, str) and current and current not in seen:
        seen.add(current)
        parent = entries.get(current, {}).get("replacement_of")
        if not isinstance(parent, str) or not parent:
            return current
        current = parent
    raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_LINEAGE_INVALID")


def _deterministic_creative_full_replan(paths, request: dict, entry: dict, *, epoch: int,
                                        root_request_id: str, operator_reason: str) -> tuple[str, dict]:
    """Compile a material reference/shot correction without trusting a rejected prompt.

    This is deliberately deterministic.  The persisted proof describes every
    provider-facing semantic decision before Flow's activation boundary.
    """
    if epoch < 2:
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_INVALID")
    purpose = request.get("purpose")
    entity_id = request.get("entity_id")
    subject = action = location = composition = ""
    exclusions: list[str] = [
        "no overlay text or captions", "no placeholder imagery", "no conflicting ethnic or family identity",
    ]
    canonical_source: dict = {"purpose": purpose, "entity_id": entity_id, "shot_id": request.get("shot_id")}
    try:
        continuity = read_json(paths.artifact_path("output/continuity_bible.json"))
    except Exception as error:
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_CANONICAL_INPUT_INVALID") from error
    if purpose == "REFERENCE":
        entities = [item for kind in ("characters", "locations", "props")
                    for item in continuity.get(kind, []) if isinstance(item, dict)]
        entity = next((item for item in entities if item.get("entity_id") == entity_id), None)
        if not isinstance(entity, dict) or not isinstance(entity.get("name"), str) or not entity["name"].strip():
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_CANONICAL_INPUT_INVALID")
        name = entity["name"].strip()
        constraints = [item.strip() for item in entity.get("constraints", []) if isinstance(item, str) and item.strip()]
        subject = f"the canonical {name}, depicting the family identity required by the story"
        action = "a static archival family portrait within the physical photograph"
        location = "an aged framed photograph in the Nigerian family home"
        composition = "tight, eye-level prop reference with the complete frame visible and no unrelated people"
        exclusions.extend(("no conflicting family identity", "no modern living family portrait", "no duplicate people"))
        canonical_source.update({"entity_name": name, "constraints": constraints})
    elif purpose == "SHOT":
        try:
            shot_plan = read_json(paths.artifact_path("output/shot_plan.json"))
        except Exception as error:
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_CANONICAL_INPUT_INVALID") from error
        shot = next((item for item in shot_plan.get("shots", []) if item.get("shot_id") == request.get("shot_id")), None)
        if not isinstance(shot, dict):
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_CANONICAL_INPUT_INVALID")
        subject = str(shot.get("subject", "")).strip()
        action = str(shot.get("action", "")).strip()
        location = str(shot.get("location_id", "")).strip()
        composition = str(shot.get("composition_intent", "")).strip()
        if not all((subject, action, location, composition)):
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_CANONICAL_INPUT_INVALID")
        canonical_source["shot"] = {key: shot.get(key) for key in ("shot_id", "subject", "action", "location_id", "composition_intent")}
    else:
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_NOT_ELIGIBLE")
    rejections = entry.get("creative_rejections") or entry.get("quality_reviews") or []
    rejection = rejections[-1] if rejections else {"failure_class": entry.get("failure_class")}
    rejection_reason = operator_reason.strip() or (rejection.get("reason") if isinstance(rejection, dict) else "explicit creative review rejection")
    semantic_delta = [
        "semantic composition rebuilt from canonical logical visual",
        "subject, action, location, and framing recompiled independently of rejected prompt",
        "conflicting family identity and prior rejected asset explicitly excluded",
        "effective references reselected from canonical intent only",
    ]
    prompt = caption_safe_effective_prompt(
        f"Canonical full replan for correction epoch {epoch}. Subject: {subject}. Action: {action}. "
        f"Location: {location}. Composition: {composition}. Canonical constraints: "
        f"{'; '.join(canonical_source.get('constraints', [])) or 'preserve the canonical logical visual'}. "
        f"Review rejection to correct: {rejection_reason}. Exclusions: {'; '.join(exclusions)}."
    )
    prior = {"prompt": request.get("prompt"), "depends_on": request.get("depends_on", []),
             "reference_asset_ids": request.get("reference_asset_ids", [])}
    current = {"prompt": prompt, "depends_on": [], "reference_asset_ids": []}
    if _json_sha256(prior) == _json_sha256(current):
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_MATERIAL_DELTA_REQUIRED")
    proof = {
        "version": CREATIVE_CORRECTION_FULL_REPLAN_VERSION, "mode": FULL_REPLAN,
        "root_request_id": root_request_id, "supersedes_request_id": request["request_id"],
        "correction_epoch": epoch, "canonical_source": canonical_source,
        "subject": subject, "action": action, "location": location, "composition": composition,
        "effective_reference_entity_ids": [], "exclusions": exclusions, "semantic_delta": semantic_delta,
        "prior_generation_input_sha256": _json_sha256(prior),
        "replanned_generation_input_sha256": _json_sha256(current),
        "material_delta_fields": ["prompt", "semantic_composition", "subject", "action", "location", "exclusions", "effective_references"],
        "rejection_evidence_sha256": _json_sha256(rejection),
    }
    return prompt, proof


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
    prompt_construction = request.get("prompt_construction")
    if prompt_construction is not None:
        if not isinstance(prompt_construction, dict):
            return None
        expected_prompt_sha256 = hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest()
        if (
            prompt_construction.get("version") != CAPTION_SAFE_PROMPT_VERSION
            or not isinstance(prompt_construction.get("source"), str)
            or not isinstance(prompt_construction.get("historical_prompt_sha256"), str)
            or prompt_construction.get("effective_prompt_sha256") != expected_prompt_sha256
        ):
            return None
    full_replan = request.get("creative_correction_replan_proof")
    creative_epoch = request.get("creative_correction_epoch", 0)
    if creative_epoch >= 2:
        if (not isinstance(full_replan, dict)
                or full_replan.get("version") != CREATIVE_CORRECTION_FULL_REPLAN_VERSION
                or full_replan.get("mode") != FULL_REPLAN
                or full_replan.get("supersedes_request_id") != request["replacement_of"]
                or full_replan.get("correction_epoch") != creative_epoch
                or full_replan.get("replanned_generation_input_sha256") == full_replan.get("prior_generation_input_sha256")
                or not isinstance(full_replan.get("material_delta_fields"), list)):
            return None
    return {
        "request_id": request["request_id"], "fingerprint": request["fingerprint"], "prompt": request["prompt"],
        "purpose": request["purpose"], "shot_id": request.get("shot_id"), "entity_id": request.get("entity_id"),
        "media_type": request["media_type"], "provider": request["provider"], "output_count": request.get("output_count", 1),
        "execution_tier": request.get("execution_tier"), "depends_on": list(request["depends_on"]),
        "reference_asset_ids": list(request["reference_asset_ids"]), "replacement_of": request["replacement_of"],
        "replacement_reason": request["replacement_reason"], "replacement_epoch": request["replacement_epoch"],
        "epoch_nonce": request["epoch_nonce"],
        **({"prompt_construction": dict(prompt_construction)} if prompt_construction is not None else {}),
        **({"root_request_id": request.get("root_request_id"), "supersedes_request_id": request.get("supersedes_request_id"),
            "correction_epoch": request.get("correction_epoch"), "creative_correction_epoch": creative_epoch,
            "creative_correction_replan_proof": full_replan}
           if creative_epoch >= 2 else {}),
    }


_QC_CORRECTIVE_PROMPT_CONSTRAINT_PREFIX = "Corrective prompt constraint:"


def _qc_corrective_prompt_constraint(reason: str) -> str | None:
    """Extract one explicit, bounded prompt delta from an operator QC reason.

    A creative rejection normally preserves the caption-safe prompt.  An
    operator can opt into a materially different replacement only by putting a
    concise constraint after the stable prefix.  This makes the change visible
    in both the durable QC event and the replacement prompt, instead of
    silently retrying the same generation input.
    """
    normalized = " ".join(reason.split())
    if not normalized.startswith(_QC_CORRECTIVE_PROMPT_CONSTRAINT_PREFIX):
        return None
    constraint = normalized[len(_QC_CORRECTIVE_PROMPT_CONSTRAINT_PREFIX):].strip()
    if not 12 <= len(constraint) <= 480:
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_CONSTRAINT_INVALID")
    return constraint


def _current_caption_safe_qc_replacement_prompt(request: dict, *, corrective_constraint: str | None = None) -> tuple[str, dict]:
    """Build a new QC epoch from current safe semantics, never by rewriting history."""
    historical_prompt = request.get("prompt")
    if not isinstance(historical_prompt, str) or not historical_prompt.strip():
        raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_INVALID")
    source = "CURRENT_CAPTION_SAFE_SANITIZATION"
    brief = request.get("visual_brief")
    style_id = request.get("ambient_style")
    if isinstance(brief, dict) or isinstance(style_id, str):
        if not isinstance(brief, dict) or not isinstance(style_id, str) or not style_id:
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_PROMPT_RECONSTRUCTION_INVALID")
        try:
            prompt = compile_ambient_image_prompt(
                brief,
                default_visual_policy(),
                style_directive=ambient_prompt_directive(style_id),
            )
        except (ValueError, TypeError) as error:
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_PROMPT_RECONSTRUCTION_INVALID") from error
        source = "CURRENT_AMBIENT_PROMPT_CONSTRUCTION"
    else:
        try:
            prompt = caption_safe_effective_prompt(historical_prompt)
        except ValueError as error:
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_PROMPT_RECONSTRUCTION_INVALID") from error
    if corrective_constraint is not None:
        prompt = f"{prompt}\n\nAuthoritative QC corrective constraint: {corrective_constraint}"
    construction = {
        "version": CAPTION_SAFE_PROMPT_VERSION,
        "source": source,
        "historical_prompt_sha256": hashlib.sha256(historical_prompt.encode("utf-8")).hexdigest(),
        "effective_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if corrective_constraint is not None:
        construction.update({
            "corrective_constraint": corrective_constraint,
            "corrective_constraint_sha256": hashlib.sha256(corrective_constraint.encode("utf-8")).hexdigest(),
        })
    return prompt, construction


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
                    "transaction_id": transaction_id, "prepared_sha256": _prepared_transaction_sha256(transaction)}
        if receipt != expected:
            return None
        matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _direct_qc_replacement_child_ids(paths, project_id: str, old_request_id: str) -> list[str] | None:
    """Return receipt-proven *direct* QC children, never copied ancestry fields.

    A replay inherits the request it replaces, including its prior QC ancestry.
    That ancestry is useful audit data, but it is not evidence that the replay
    was directly created by the older QC transition.  The committed QC creation
    transaction records the only immutable parent -> child operation boundary.
    """
    children: list[str] = []
    try:
        transactions = _prepared_transactions(
            paths, project_id, schema_version=QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA
        )
    except FlowError:
        return None
    for _path, transaction in transactions:
        if transaction.get("old_request_id") != old_request_id:
            continue
        transaction_id = transaction.get("transaction_id")
        child_id = transaction.get("replacement_request_id")
        if (not isinstance(transaction_id, str) or not transaction_id
                or not isinstance(child_id, str) or not child_id or child_id == old_request_id):
            return None
        _prepared, committed_path = _transaction_paths(
            paths, transaction_id, schema_version=QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA
        )
        try:
            receipt = read_json(committed_path)
        except Exception:
            return None
        expected_receipt = {
            "schema_version": QC_REJECTED_ASSET_REPLACEMENT_TRANSACTION_SCHEMA,
            "state": "COMMITTED",
            "transaction_id": transaction_id,
            "prepared_sha256": _prepared_transaction_sha256(transaction),
        }
        if receipt != expected_receipt:
            return None
        stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
        stored_manifest = transaction["targets"]["generation_manifest"]["value"].get("requests", [])
        stored_child = next((item for item in stored_requests if item.get("request_id") == child_id), None)
        stored_parent = next((item for item in stored_manifest if item.get("request_id") == old_request_id), None)
        events = stored_parent.get("qc_replacement_events") if isinstance(stored_parent, dict) else None
        if (not isinstance(stored_child, dict)
                or _qc_replacement_genesis_projection(stored_child) is None
                or stored_child.get("replacement_of") != old_request_id
                or stored_child.get("replacement_reason") != QC_REJECTED_ASSET_REPLACEMENT_REASON
                or not isinstance(events, list)
                or not any(isinstance(event, dict)
                           and event.get("event") == QC_REJECTED_ASSET_REPLACEMENT_REASON
                           and event.get("old_request_id") == old_request_id
                           and event.get("replacement_request_id") == child_id
                           for event in events)):
            return None
        children.append(child_id)
    return children


def _qc_ancestry_metadata_has_direct_origin(paths, project_id: str, item: dict) -> bool:
    """Reject orphaned QC ancestry fields without treating descendants as duplicates."""
    parent_id = item.get("replacement_of")
    reason = item.get("replacement_reason")
    # Historical QC parents record the reason of their outgoing edge but do
    # not themselves carry incoming QC ancestry.
    if parent_id is None:
        return True
    if (not isinstance(parent_id, str) or not parent_id
            or reason != QC_REJECTED_ASSET_REPLACEMENT_REASON
            or not isinstance(item.get("request_id"), str) or not item["request_id"]):
        return False
    direct_children = _direct_qc_replacement_child_ids(paths, project_id, parent_id)
    if direct_children is None:
        return False
    if item["request_id"] in direct_children:
        return True
    # A descendant may retain older QC ancestry, but must prove its own
    # immediate replay edge. This is lineage-integrity checking, not duplicate
    # direct-child detection.
    replay_parent = item.get("replays_unresolved_request_id")
    return (isinstance(replay_parent, str) and bool(replay_parent)
            and _unresolved_replay_transaction(paths, project_id, replay_parent, item["request_id"]) is not None)


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
    direct_children = _direct_qc_replacement_child_ids(paths, project_id, entry.get("request_id"))
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
        and direct_children == [replacement_id]
    )
    if not immutable_edge:
        return False
    if isinstance(replacement, dict):
        return (
            _qc_replacement_genesis_projection(replacement) is not None
            and _qc_replacement_genesis_projection(replacement) == _qc_replacement_genesis_projection(stored_replacement)
            and replacement_entry.get("status") in {
                "PENDING", "GENERATING", "NOT_DISPATCHED", "AMBIGUOUS", "FAILED_RETRYABLE", "QC_PENDING", "SUCCEEDED",
                "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED",
            }
        )
    return (
        _historical_replacement_parent(replacement_entry)
        and _manifest_identity_matches_request(replacement_entry, stored_replacement)
    )


def _semantic_reset_transaction(paths, project_id: str, exhausted_request_id: str,
                                reset_request_id: str) -> tuple[dict, dict] | None:
    matches = []
    for _path, transaction in _prepared_transactions(paths, project_id, schema_version=SEMANTIC_RESET_TRANSACTION_SCHEMA):
        if (transaction.get("old_request_id") != exhausted_request_id
                or transaction.get("replacement_request_id") != reset_request_id):
            continue
        transaction_id = transaction.get("transaction_id")
        if not isinstance(transaction_id, str):
            return None
        _prepared, committed = _transaction_paths(paths, transaction_id, schema_version=SEMANTIC_RESET_TRANSACTION_SCHEMA)
        try:
            receipt = read_json(committed)
        except Exception:
            return None
        if receipt != {"schema_version": SEMANTIC_RESET_TRANSACTION_SCHEMA, "state": "COMMITTED",
                       "transaction_id": transaction_id, "prepared_sha256": _prepared_transaction_sha256(transaction)}:
            return None
        matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _semantic_reset_parent_valid(paths, project_id: str, entry: dict, requests: list[dict],
                                 entries: dict[str, dict]) -> bool:
    if entry.get("status") != SEMANTIC_RESET_PENDING_STATUS:
        return False
    child_id = entry.get("semantic_reset_request_id")
    if not isinstance(child_id, str) or not child_id:
        return False
    resolved = _semantic_reset_transaction(paths, project_id, entry.get("request_id"), child_id)
    child = next((item for item in requests if item.get("request_id") == child_id), None)
    child_entry = entries.get(child_id)
    if resolved is None or not isinstance(child, dict) or not isinstance(child_entry, dict):
        return False
    transaction, _receipt = resolved
    stored_child = next((item for item in transaction["targets"]["generation_requests"]["value"].get("requests", [])
                         if item.get("request_id") == child_id), None)
    stored_entry = next((item for item in transaction["targets"]["generation_manifest"]["value"].get("requests", [])
                         if item.get("request_id") == child_id), None)
    core = child.get("semantic_reset_core")
    return bool(
        child.get("semantic_reset_of_exhausted_request_id") == entry.get("request_id")
        and child.get("creative_correction_epoch") is None
        and child.get("replacement_of") is None
        and isinstance(core, dict) and core.get("location") == "INTERIOR"
        and core.get("composition") == "DESK_DOCUMENT_DETAIL"
        and core.get("interaction") == "INDEX_FINGER_TRACES_TRANSACTION_LIST"
        and isinstance(core.get("forbidden"), list) and {"exterior", "porch", "outdoor", "veranda"}.issubset(set(core["forbidden"]))
        and child.get("reference_asset_ids") == core.get("compatible_reference_asset_ids")
        and isinstance(child_entry.get("attempts"), list)
        and child_entry.get("status") in {"PENDING", "GENERATING", "NOT_DISPATCHED", "AMBIGUOUS", "FAILED_RETRYABLE",
                                           "QC_PENDING", "SUCCEEDED", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED"}
        and isinstance(stored_child, dict) and stored_child == child
        and isinstance(stored_entry, dict) and stored_entry.get("attempts") == []
        and stored_entry.get("provider_submissions") == 0 and stored_entry.get("selected_asset") is None
    )


def _qc_rejection_evidence_projection(entry: dict) -> dict:
    """Facts from the rejected epoch that a correction is forbidden to rewrite."""
    return {
        "attempts": entry.get("attempts"),
        "provider_submissions": entry.get("provider_submissions"),
        "selected_asset": entry.get("selected_asset"),
        "quality_reviews": entry.get("quality_reviews"),
        "failure_class": entry.get("failure_class"),
    }


def _terminal_qc_rejection(entry: dict | None) -> bool:
    """Require an attributed selected asset and the latest authoritative QC rejection."""
    if (not isinstance(entry, dict) or entry.get("status") != "FAILED_RETRYABLE"
            or not isinstance(entry.get("selected_asset"), dict)):
        return False
    failure = entry.get("failure_class")
    reviews = entry.get("quality_reviews")
    if (not isinstance(failure, str) or not failure.endswith("_QC_REJECTED")
            or not isinstance(reviews, list) or not reviews):
        return False
    latest = reviews[-1]
    if (not isinstance(latest, dict) or latest.get("status") != "REJECTED"
            or latest.get("failure_class") != failure):
        return False
    selected_attempt = entry["selected_asset"].get("attempt")
    attempts = entry.get("attempts")
    return isinstance(attempts, list) and any(
        isinstance(attempt, dict)
        and attempt.get("attempt") == selected_attempt
        and attempt.get("attribution_state") == "CONFIRMED"
        for attempt in attempts
    )


def _qc_corrective_replan_genesis_projection(request: dict) -> dict | None:
    required = (
        "request_id", "fingerprint", "prompt", "purpose", "media_type", "provider",
        "root_request_id", "supersedes_request_id", "correction_nonce", "correction_reason",
    )
    if (not isinstance(request, dict)
            or any(not isinstance(request.get(key), str) or not request[key] for key in required)
            or request.get("correction_reason") != QC_CORRECTIVE_REPLAN_REASON
            or request.get("purpose") != "SHOT"
            or request.get("media_type") not in {"IMAGE", "VIDEO"}
            or not isinstance(request.get("correction_epoch"), int)
            or request["correction_epoch"] < 1):
        return None
    for key in ("depends_on", "reference_asset_ids"):
        if (not isinstance(request.get(key), list)
                or any(not isinstance(item, str) or not item for item in request[key])):
            return None
    if request["media_type"] == "VIDEO" and not isinstance(request.get("motion_risk_analysis"), dict):
        return None
    provenance = request.get("corrective_replan_provenance")
    if (not isinstance(provenance, dict)
            or provenance.get("root_request_id") != request["root_request_id"]
            or provenance.get("supersedes_request_id") != request["supersedes_request_id"]
            or provenance.get("correction_epoch") != request["correction_epoch"]
            or provenance.get("provider") != "gemini"
            or not isinstance(provenance.get("model"), str)
            or not provenance["model"]
            or not isinstance(provenance.get("canonical_inputs"), dict)
            or not isinstance(provenance.get("corrected_semantic_intent"), dict)
            or not isinstance(provenance.get("semantic_delta"), list)
            or not isinstance(provenance.get("reference_selection_delta"), dict)):
        return None
    return {
        "request_id": request["request_id"],
        "fingerprint": request["fingerprint"],
        "prompt": request["prompt"],
        "purpose": request["purpose"],
        "shot_id": request.get("shot_id"),
        "media_type": request["media_type"],
        "provider": request["provider"],
        "output_count": request.get("output_count", 1),
        "execution_tier": request.get("execution_tier"),
        "depends_on": list(request["depends_on"]),
        "reference_asset_ids": list(request["reference_asset_ids"]),
        "root_request_id": request["root_request_id"],
        "supersedes_request_id": request["supersedes_request_id"],
        "correction_epoch": request["correction_epoch"],
        "correction_nonce": request["correction_nonce"],
        "correction_reason": request["correction_reason"],
        "corrected_semantic_intent": request.get("corrected_semantic_intent"),
        **({"motion_risk_analysis": request.get("motion_risk_analysis"),
            "corrective_motion_evidence": request.get("corrective_motion_evidence")}
           if request["media_type"] == "VIDEO" else {}),
        "corrective_replan_provenance": provenance,
    }


def _qc_corrective_replan_transaction(paths, project_id: str, supersedes_request_id: str,
                                      correction_request_id: str) -> tuple[dict, dict] | None:
    matches = []
    for _path, transaction in _prepared_transactions(
            paths, project_id, schema_version=QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA):
        if (transaction.get("old_request_id") != supersedes_request_id
                or transaction.get("replacement_request_id") != correction_request_id):
            continue
        transaction_id = transaction.get("transaction_id")
        if not isinstance(transaction_id, str):
            return None
        _prepared, committed_path = _transaction_paths(
            paths, transaction_id, schema_version=QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA)
        try:
            receipt = read_json(committed_path)
        except Exception:
            return None
        expected = {
            "schema_version": QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA,
            "state": "COMMITTED",
            "transaction_id": transaction_id,
            "prepared_sha256": _prepared_transaction_sha256(transaction),
        }
        if receipt != expected:
            return None
        matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _direct_qc_corrective_child_ids(paths, project_id: str, supersedes_request_id: str) -> list[str] | None:
    children = []
    try:
        transactions = _prepared_transactions(
            paths, project_id, schema_version=QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA)
    except FlowError:
        return None
    for _path, transaction in transactions:
        if transaction.get("old_request_id") != supersedes_request_id:
            continue
        child_id = transaction.get("replacement_request_id")
        if not isinstance(child_id, str) or not child_id:
            return None
        if _qc_corrective_replan_transaction(paths, project_id, supersedes_request_id, child_id) is None:
            return None
        children.append(child_id)
    return children


def _qc_corrective_pre_dispatch_transaction(paths, project_id: str, old_request_id: str,
                                            replacement_request_id: str) -> tuple[dict, dict] | None:
    matches = []
    for _path, transaction in _prepared_transactions(
            paths, project_id, schema_version=QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA):
        if (transaction.get("old_request_id") != old_request_id
                or transaction.get("replacement_request_id") != replacement_request_id):
            continue
        transaction_id = transaction.get("transaction_id")
        if not isinstance(transaction_id, str):
            return None
        _prepared, committed_path = _transaction_paths(
            paths, transaction_id, schema_version=QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA)
        try:
            receipt = read_json(committed_path)
        except Exception:
            return None
        expected = {
            "schema_version": QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA,
            "state": "COMMITTED", "transaction_id": transaction_id,
            "prepared_sha256": _prepared_transaction_sha256(transaction),
        }
        if receipt != expected:
            return None
        matches.append((transaction, receipt))
    return matches[0] if len(matches) == 1 else None


def _direct_qc_corrective_pre_dispatch_child_ids(paths, project_id: str, old_request_id: str) -> list[str] | None:
    children = []
    try:
        transactions = _prepared_transactions(
            paths, project_id, schema_version=QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA)
    except FlowError:
        return None
    for _path, transaction in transactions:
        if transaction.get("old_request_id") != old_request_id:
            continue
        child_id = transaction.get("replacement_request_id")
        if (not isinstance(child_id, str) or not child_id
                or _qc_corrective_pre_dispatch_transaction(paths, project_id, old_request_id, child_id) is None):
            return None
        children.append(child_id)
    return children


def _qc_corrective_pre_dispatch_genesis_projection(request: dict) -> dict | None:
    required = ("request_id", "fingerprint", "prompt", "purpose", "media_type", "provider",
                "root_request_id", "supersedes_request_id", "correction_nonce", "correction_reason")
    if (not isinstance(request, dict)
            or any(not isinstance(request.get(key), str) or not request[key] for key in required)
            or request.get("purpose") != "SHOT"
            or request.get("media_type") not in {"IMAGE", "VIDEO"}
            or request.get("correction_reason") != QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON
            or not isinstance(request.get("correction_epoch"), int)
            or request["correction_epoch"] < 1
            or request.get("reference_asset_ids") != [] or request.get("depends_on") != []):
        return None
    provenance = request.get("pre_dispatch_supersession_provenance")
    if (not isinstance(provenance, dict)
            or provenance.get("root_request_id") != request["root_request_id"]
            or provenance.get("supersedes_request_id") != request["supersedes_request_id"]
            or provenance.get("correction_epoch") != request["correction_epoch"]
            or provenance.get("reference_capacity") != FLOW_REFERENCE_CAPACITY
            or not isinstance(provenance.get("source_request_sha256"), str)
            or not provenance["source_request_sha256"]
            or not isinstance(provenance.get("reference_policy"), dict)):
        return None
    return {
        "request_id": request["request_id"], "fingerprint": request["fingerprint"],
        "prompt": request["prompt"], "purpose": request["purpose"], "shot_id": request.get("shot_id"),
        "media_type": request["media_type"], "provider": request["provider"],
        "output_count": request.get("output_count", 1), "execution_tier": request.get("execution_tier"),
        "depends_on": [], "reference_asset_ids": [], "root_request_id": request["root_request_id"],
        "supersedes_request_id": request["supersedes_request_id"],
        "correction_epoch": request["correction_epoch"], "correction_nonce": request["correction_nonce"],
        "correction_reason": request["correction_reason"],
        "corrected_semantic_intent": request.get("corrected_semantic_intent"),
        "motion_risk_analysis": request.get("motion_risk_analysis") if request["media_type"] == "VIDEO" else None,
        "corrective_motion_evidence": request.get("corrective_motion_evidence") if request["media_type"] == "VIDEO" else None,
        "pre_dispatch_supersession_provenance": provenance,
    }


def _qc_corrective_pre_dispatch_supersession_valid(paths, project_id: str, entry: dict,
                                                    requests: list[dict], entries: dict[str, dict]) -> bool:
    if (entry.get("status") != QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS
            or entry.get("selected_asset") is not None
            or entry.get("attempts") != []
            or entry.get("provider_submissions", 0) != 0):
        return False
    child_id = entry.get("pre_dispatch_supersession_request_id")
    events = entry.get("pre_dispatch_supersession_events")
    if not isinstance(child_id, str) or not isinstance(events, list) or len(events) != 1:
        return False
    event = events[0] if isinstance(events[0], dict) else None
    if (not isinstance(event, dict)
            or event.get("event") != QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON
            or event.get("old_request_id") != entry.get("request_id")
            or event.get("replacement_request_id") != child_id
            or event.get("attempts_sha256") != _json_sha256([])
            or event.get("provider_submissions") != 0):
        return False
    resolved = _qc_corrective_pre_dispatch_transaction(paths, project_id, entry.get("request_id"), child_id)
    if resolved is None:
        return False
    transaction, _receipt = resolved
    stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
    stored_manifest = transaction["targets"]["generation_manifest"]["value"].get("requests", [])
    stored_parent = next((item for item in stored_manifest if item.get("request_id") == entry.get("request_id")), None)
    stored_child = next((item for item in stored_requests if item.get("request_id") == child_id), None)
    stored_child_entry = next((item for item in stored_manifest if item.get("request_id") == child_id), None)
    child = next((item for item in requests if item.get("request_id") == child_id), None)
    child_entry = entries.get(child_id)
    if (not isinstance(stored_parent, dict) or stored_parent != entry
            or not isinstance(stored_child, dict)
            or _qc_corrective_pre_dispatch_genesis_projection(stored_child) is None
            or not isinstance(stored_child_entry, dict)
            or stored_child_entry.get("attempts") != []
            or stored_child_entry.get("provider_submissions") != 0
            or stored_child_entry.get("selected_asset") is not None
            or stored_child_entry.get("attribution_claim") != "NONE"
            or not isinstance(child_entry, dict)
            or _direct_qc_corrective_pre_dispatch_child_ids(paths, project_id, entry.get("request_id")) != [child_id]):
        return False
    if isinstance(child, dict):
        return (_qc_corrective_pre_dispatch_genesis_projection(child)
                == _qc_corrective_pre_dispatch_genesis_projection(stored_child)
                and child_entry.get("status") in {"PENDING", "GENERATING", "NOT_DISPATCHED", "AMBIGUOUS",
                                                    "FAILED_RETRYABLE", "QC_PENDING", "SUCCEEDED", "FAILED_PERMANENT",
                                                    "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED"})
    return _historical_replacement_parent(child_entry) and _manifest_identity_matches_request(child_entry, stored_child)


def _qc_corrective_metadata_has_direct_origin(paths, project_id: str, item: dict) -> bool:
    fields = ("root_request_id", "supersedes_request_id", "correction_epoch", "correction_nonce",
              "correction_reason", "corrective_replan_provenance")
    if not any(field in item for field in fields):
        return True
    # The historical parent records its outgoing operation; only the child
    # carries incoming root/superseded/correction-epoch genesis metadata.
    if (item.get("status") == QC_CORRECTIVE_REPLANNED_STATUS
            and item.get("correction_reason") == QC_CORRECTIVE_REPLAN_REASON
            and isinstance(item.get("correction_request_id"), str)
            and "supersedes_request_id" not in item):
        return True
    if (item.get("status") == QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS
            and isinstance(item.get("pre_dispatch_supersession_request_id"), str)):
        # The dedicated parent validator below verifies this outgoing edge.
        return True
    # A pre-dispatch child can later receive an ordinary mandatory-QC
    # replacement.  Its outgoing QC edge is checked separately; this branch
    # proves the retained incoming pre-dispatch origin without mistaking the
    # QC replacement child for that origin.
    if (item.get("status") == QC_REJECTED_ASSET_REPLACED_STATUS
            and item.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON
            and item.get("correction_reason") == QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON):
        request_id = item.get("request_id")
        parent_id = item.get("supersedes_request_id")
        return (isinstance(request_id, str) and bool(request_id)
                and isinstance(parent_id, str) and bool(parent_id)
                and _qc_corrective_pre_dispatch_transaction(paths, project_id, parent_id, request_id) is not None)
    # A canonical unresolved replay retains its semantic correction metadata
    # while replacing only the unsafe provider epoch.  Its committed replay
    # transaction binds that full inherited request; the QC-ancestry validator
    # independently proves the retained direct QC edge.
    replay_parent = item.get("replays_unresolved_request_id")
    if isinstance(replay_parent, str) and replay_parent:
        request_id = item.get("request_id")
        return (isinstance(request_id, str) and bool(request_id)
                and _unresolved_replay_transaction(paths, project_id, replay_parent, request_id) is not None)
    # A mandatory-QC replacement may retain the semantic/pre-dispatch fields
    # of its parent.  Its immediate immutable origin is nevertheless the QC
    # replacement transaction, not the inherited corrective edge.
    if item.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON:
        request_id = item.get("request_id")
        parent_id = item.get("replacement_of")
        return (isinstance(request_id, str) and bool(request_id)
                and isinstance(parent_id, str) and bool(parent_id)
                and _qc_rejected_asset_replacement_transaction(paths, project_id, parent_id, request_id) is not None)
    request_id = item.get("request_id")
    parent_id = item.get("supersedes_request_id")
    if (not isinstance(request_id, str) or not request_id
            or not isinstance(parent_id, str) or not parent_id):
        return False
    reason = item.get("correction_reason")
    creative_epoch = item.get("creative_correction_epoch")
    is_full_creative_correction = (
        item.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON
        and isinstance(creative_epoch, int)
        and creative_epoch >= 2
    )
    if reason == QC_CORRECTIVE_REPLAN_REASON:
        resolved = _qc_corrective_replan_transaction(paths, project_id, parent_id, request_id)
        projection = _qc_corrective_replan_genesis_projection
    elif reason == QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON:
        resolved = _qc_corrective_pre_dispatch_transaction(paths, project_id, parent_id, request_id)
        projection = _qc_corrective_pre_dispatch_genesis_projection
    elif is_full_creative_correction:
        resolved = _qc_rejected_asset_replacement_transaction(paths, project_id, parent_id, request_id)
        projection = _qc_replacement_genesis_projection
    else:
        return False
    if resolved is None:
        return False
    transaction, _receipt = resolved
    stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
    stored = next((request for request in stored_requests if request.get("request_id") == request_id), None)
    if "fingerprint" not in item or "prompt" not in item:
        if is_full_creative_correction:
            return (
                projection(stored) is not None
                and item.get("request_identity_sha256") == stored.get("fingerprint")
                and item.get("prompt_sha256") == hashlib.sha256(stored.get("prompt", "").encode("utf-8")).hexdigest()
                and item.get("related_identity") == (stored.get("shot_id") or stored.get("entity_id"))
                and item.get("media_type") == stored.get("media_type")
                and item.get("provider") == stored.get("provider")
                and item.get("replacement_of") == stored.get("replacement_of")
                and item.get("replacement_reason") == stored.get("replacement_reason")
                and item.get("replacement_epoch") == stored.get("replacement_epoch")
                and item.get("root_request_id") == stored.get("root_request_id")
                and item.get("supersedes_request_id") == stored.get("supersedes_request_id")
                and item.get("creative_correction_epoch") == stored.get("creative_correction_epoch")
                and item.get("creative_correction_replan_proof") == stored.get("creative_correction_replan_proof")
            )
        common = (
            projection(stored) is not None
            and item.get("request_identity_sha256") == stored.get("fingerprint")
            and item.get("prompt_sha256") == hashlib.sha256(stored.get("prompt", "").encode("utf-8")).hexdigest()
            and item.get("related_identity") == (stored.get("shot_id") or stored.get("entity_id"))
            and item.get("media_type") == stored.get("media_type")
            and item.get("provider") == stored.get("provider")
            and item.get("root_request_id") == stored.get("root_request_id")
            and item.get("supersedes_request_id") == stored.get("supersedes_request_id")
            and item.get("correction_epoch") == stored.get("correction_epoch")
            and item.get("correction_nonce") == stored.get("correction_nonce")
            and item.get("correction_reason") == stored.get("correction_reason")
            and item.get("corrected_semantic_intent") == stored.get("corrected_semantic_intent")
        )
        if reason == QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON:
            return common and item.get("pre_dispatch_supersession_provenance") == stored.get("pre_dispatch_supersession_provenance")
        return common and item.get("corrective_replan_provenance") == stored.get("corrective_replan_provenance")
    return (
        projection(item) is not None
        and projection(item) == projection(stored)
    )


def _qc_corrective_replan_valid(paths, project_id: str, entry: dict, requests: list[dict],
                                entries: dict[str, dict]) -> bool:
    if (entry.get("status") != QC_CORRECTIVE_REPLANNED_STATUS
            or not isinstance(entry.get("selected_asset"), dict)):
        return False
    correction_id = entry.get("correction_request_id")
    events = entry.get("qc_corrective_replan_events")
    if not isinstance(correction_id, str) or not isinstance(events, list) or len(events) != 1:
        return False
    event = events[0] if isinstance(events[0], dict) else None
    if (not isinstance(event, dict) or event.get("event") != QC_CORRECTIVE_REPLAN_REASON
            or event.get("supersedes_request_id") != entry.get("request_id")
            or event.get("correction_request_id") != correction_id
            or event.get("prior_qc_evidence_sha256") != _json_sha256(_qc_rejection_evidence_projection(entry))):
        return False
    resolved = _qc_corrective_replan_transaction(paths, project_id, entry.get("request_id"), correction_id)
    if resolved is None:
        return False
    transaction, _receipt = resolved
    stored_requests = transaction["targets"]["generation_requests"]["value"].get("requests", [])
    stored_manifest = transaction["targets"]["generation_manifest"]["value"].get("requests", [])
    superseded_request = transaction.get("superseded_request")
    stored_parent = next((item for item in stored_manifest if item.get("request_id") == entry.get("request_id")), None)
    stored_child = next((item for item in stored_requests if item.get("request_id") == correction_id), None)
    stored_child_entry = next((item for item in stored_manifest if item.get("request_id") == correction_id), None)
    child = next((item for item in requests if item.get("request_id") == correction_id), None)
    child_entry = entries.get(correction_id)
    if (not isinstance(superseded_request, dict)
            or superseded_request.get("request_id") != entry.get("request_id")
            or transaction.get("superseded_request_sha256") != _json_sha256(superseded_request)
            or not isinstance(stored_parent, dict)
            or _qc_rejection_evidence_projection(stored_parent) != _qc_rejection_evidence_projection(entry)
            or not isinstance(stored_child, dict)
            or _qc_corrective_replan_genesis_projection(stored_child) is None
            or not isinstance(stored_child_entry, dict)
            or stored_child_entry.get("attempts") != []
            or stored_child_entry.get("provider_submissions") != 0
            or stored_child_entry.get("selected_asset") is not None
            or stored_child_entry.get("attribution_claim") != "NONE"
            or not isinstance(child_entry, dict)
            or _direct_qc_corrective_child_ids(paths, project_id, entry.get("request_id")) != [correction_id]):
        return False
    if isinstance(child, dict):
        return (
            _qc_corrective_replan_genesis_projection(child)
            == _qc_corrective_replan_genesis_projection(stored_child)
            and child_entry.get("status") in {
                "PENDING", "GENERATING", "NOT_DISPATCHED", "AMBIGUOUS", "FAILED_RETRYABLE", "QC_PENDING",
                "SUCCEEDED", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED",
            }
        )
    return _historical_replacement_parent(child_entry) and _manifest_identity_matches_request(child_entry, stored_child)


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
        elif status == QC_CORRECTIVE_REPLANNED_STATUS:
            if not _qc_corrective_replan_valid(paths, project_id, entry, requests, entries):
                return None
            child_id = entry.get("correction_request_id")
        elif status == QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS:
            if not _qc_corrective_pre_dispatch_supersession_valid(paths, project_id, entry, requests, entries):
                return None
            child_id = entry.get("pre_dispatch_supersession_request_id")
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
        current_epoch = _creative_correction_epoch(old_request, old_entry)
        if current_epoch >= MAX_CREATIVE_CORRECTION_EPOCHS:
            raise FlowError("CORRECTION_CHAIN_EXHAUSTED")
        attempts_sha256 = _json_sha256(old_entry["attempts"])
        selected_sha256 = old_entry["selected_asset"].get("sha256")
        historical_prompt = old_request["prompt"]
        epoch = current_epoch + 1
        root_request_id = _creative_correction_root_id(old_request, entries)
        full_replan_proof = None
        corrective_constraint = _qc_corrective_prompt_constraint(reason)
        if epoch >= 2:
            replacement_prompt, full_replan_proof = _deterministic_creative_full_replan(
                paths, old_request, old_entry, epoch=epoch, root_request_id=root_request_id, operator_reason=reason)
            prompt_construction = None
        else:
            replacement_prompt, prompt_construction = _current_caption_safe_qc_replacement_prompt(
                old_request, corrective_constraint=corrective_constraint
            )
        nonce = uuid.uuid4().hex
        replacement_id, replacement_fingerprint = _replacement_identity(old_request, nonce=nonce, epoch=epoch)
        if replacement_id in entries or any(item.get("request_id") == replacement_id for item in requests):
            raise FlowError("QC_REJECTED_ASSET_REPLACEMENT_IDENTITY_COLLISION")
        replacement = dict(old_request)
        if isinstance(replacement.get("visual_brief"), dict):
            replacement_brief = dict(replacement["visual_brief"])
            composition = replacement_brief.get("composition_intent")
            if isinstance(composition, str):
                replacement_brief["composition_intent"] = caption_safe_composition_intent(composition)
            replacement["visual_brief"] = replacement_brief
        replacement.update({"request_id": replacement_id, "fingerprint": replacement_fingerprint,
                            "prompt": replacement_prompt, "prompt_construction": prompt_construction,
                            "replaces_request_id": request_id, "replacement_of": request_id,
                            "replacement_reason": QC_REJECTED_ASSET_REPLACEMENT_REASON,
                            "replacement_epoch": epoch, "epoch_nonce": nonce})
        if full_replan_proof is not None:
            replacement.update({
                "root_request_id": root_request_id, "logical_visual_id": root_request_id,
                "supersedes_request_id": request_id, "correction_epoch": epoch,
                "creative_correction_epoch": epoch,
                "creative_correction_replan_proof": full_replan_proof,
            })
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
                  "historical_attribution": "CONFIRMED",
                  "historical_prompt": historical_prompt,
                  "historical_prompt_sha256": hashlib.sha256(historical_prompt.encode("utf-8")).hexdigest(),
                  "correction_epoch": epoch,
                  **({"creative_correction_replan_proof_sha256": _json_sha256(full_replan_proof)}
                     if full_replan_proof is not None else {})}
        old_entry.setdefault("qc_replacement_events", []).append(event)
        old_entry.update({"status": QC_REJECTED_ASSET_REPLACED_STATUS, "replacement_request_id": replacement_id,
                          "replacement_reason": QC_REJECTED_ASSET_REPLACEMENT_REASON,
                          "historical_prompt": historical_prompt,
                          "historical_prompt_sha256": hashlib.sha256(historical_prompt.encode("utf-8")).hexdigest(),
                          "updated_at": at})
        manifest["requests"].append({"request_id": replacement_id, "request_identity_sha256": replacement_fingerprint,
                                     "related_identity": replacement.get("shot_id") or replacement.get("entity_id"),
                                     "media_type": replacement["media_type"], "provider": replacement.get("provider", "google_flow"),
                                     "prompt_sha256": hashlib.sha256(replacement["prompt"].encode("utf-8")).hexdigest(),
                                     "reference_asset_hashes": [], "attempts": [], "provider_submissions": 0,
                                     "selected_asset": None, "attribution_claim": "NONE", "status": "PENDING", "created_at": at,
                                     "replaces_request_id": request_id, "replacement_of": request_id,
                                     "replacement_reason": QC_REJECTED_ASSET_REPLACEMENT_REASON,
                                     "replacement_epoch": epoch, "epoch_nonce": nonce,
                                     **({"root_request_id": root_request_id, "logical_visual_id": root_request_id,
                                         "supersedes_request_id": request_id, "correction_epoch": epoch,
                                         "creative_correction_epoch": epoch,
                                         "creative_correction_replan_proof": full_replan_proof}
                                        if full_replan_proof is not None else {})})
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


def _scene_geometry_contract(*, compatible_reference_asset_ids: list[str], omitted_reference_asset_ids: list[str]) -> dict:
    """The bounded spatial contract for the persistent Scene 3A failure family."""
    return {
        "version": SCENE_GEOMETRY_CONTRACT_VERSION,
        "location_type": "INTERIOR",
        "composition": {
            "desk_document": "CENTER_LOWER/FOREGROUND/DOMINANT",
            "character": "UPPER_CENTER/MIDGROUND/POSITIONED_AT_DESK",
            "document_access": "VISIBLE_AND_UNOCCLUDED",
            "finger_document_interaction": "CENTER_LOWER/FOREGROUND/VISIBLE",
        },
        "subject_anchors": {
            "character_region": "UPPER_CENTER/MIDGROUND",
            "hand_region": "CENTER_LOWER/FOREGROUND",
            "document_region": "CENTER_LOWER/FOREGROUND",
        },
        "action_progression": ["APPROACH_DOCUMENT", "CONTACT_DOCUMENT", "TRACE_DOCUMENT"],
        "required_visual_state": ["interior_room", "desk", "printed_document", "visible_finger_document_interaction"],
        "forbidden_scene_family": ["exterior", "porch", "veranda", "outdoor_doorway", "unrelated_exterior_architecture"],
        "reference_policy": {
            "compatible_reference_asset_ids": list(compatible_reference_asset_ids),
            "omitted_conflicting_reference_asset_ids": list(omitted_reference_asset_ids),
        },
    }


def _compile_scene_geometry_prompt(contract: dict, subject: str, action: str) -> str:
    """Compile the semantic contract into the only provider-visible geometry input."""
    if not isinstance(contract, dict) or contract.get("version") != SCENE_GEOMETRY_CONTRACT_VERSION:
        raise FlowError("SCENE_GEOMETRY_CONTRACT_INVALID")
    return (
        "Authoritative scene geometry contract. location_type=INTERIOR. "
        "Composition: a desk and printed document dominate the CENTER_LOWER FOREGROUND; "
        "the character is positioned at the desk in the UPPER_CENTER MIDGROUND; "
        "the hand and document remain visibly accessible in the CENTER_LOWER FOREGROUND. "
        "Subject anchors: character=UPPER_CENTER/MIDGROUND, hand=CENTER_LOWER/FOREGROUND, "
        "document=CENTER_LOWER/FOREGROUND. "
        "Action progression: APPROACH_DOCUMENT -> CONTACT_DOCUMENT -> TRACE_DOCUMENT. "
        f"Required visual state: interior room, desk, printed document, visible finger-document interaction. {subject} {action} "
        "Forbidden scene family: exterior, porch, veranda, outdoor doorway, unrelated exterior architecture. "
        "No attached reference may override this geometry."
    )


def _validate_effective_scene_geometry_provider_input(request: dict, reference_paths: list[str]) -> dict | None:
    """Fail closed before Flow when compiled input loses a persisted geometry contract."""
    contract = request.get("scene_geometry_contract")
    if contract is None:
        return None
    if not isinstance(contract, dict) or contract.get("version") != SCENE_GEOMETRY_CONTRACT_VERSION:
        raise FlowError("SCENE_GEOMETRY_PROVIDER_INPUT_INVALID")
    prompt = request.get("prompt")
    policy = contract.get("reference_policy")
    material = request.get("semantic_reset_material_delta")
    required = ("location_type=INTERIOR", "desk and printed document dominate", "APPROACH_DOCUMENT -> CONTACT_DOCUMENT -> TRACE_DOCUMENT", "Forbidden scene family: exterior, porch, veranda, outdoor doorway, unrelated exterior architecture")
    if (not isinstance(prompt, str) or any(token not in prompt for token in required)
            or not isinstance(policy, dict) or not isinstance(material, dict)
            or request.get("reference_asset_ids") != policy.get("compatible_reference_asset_ids")
            or not isinstance(reference_paths, list)):
        raise FlowError("SCENE_GEOMETRY_PROVIDER_INPUT_INVALID")
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    failed = material.get("failed_generation_inputs")
    if (material.get("scene_geometry_contract_sha256") != _json_sha256(contract)
            or material.get("compiled_geometry_prompt_sha256") != prompt_sha256
            or not isinstance(failed, list)
            or any(item.get("prompt_sha256") == prompt_sha256 for item in failed if isinstance(item, dict))):
        raise FlowError("SCENE_GEOMETRY_PROVIDER_INPUT_INVALID")
    return {
        "version": SCENE_GEOMETRY_CONTRACT_VERSION,
        "validated_at": _now(),
        "scene_geometry_contract_sha256": _json_sha256(contract),
        "compiled_prompt_sha256": prompt_sha256,
        "attached_reference_paths": list(reference_paths),
        "conflicting_reference_assets_omitted": list(policy.get("omitted_conflicting_reference_asset_ids", [])),
        "stale_prompt_or_reasoning_cache_reused": False,
    }


def semantic_reset_exhausted_correction(runtime_root: Path | str, project_id: str, request_id: str, *,
                                        reason: str) -> dict:
    """Create the one fresh, canonical-only reset permitted after correction exhaustion.

    This is deliberately not a fourth correction epoch: it preserves the four
    rejected provider epochs as immutable evidence and creates a zero-attempt
    child whose prompt and effective references are rebuilt from the shot plan.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("SEMANTIC_RESET_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest_path, manifest = _manifest(paths, project_id)
        requests_path = paths.artifact_path("output/generation_requests.json")
        try:
            requests_data = read_json(requests_path)
            requests = requests_data.get("requests")
            shot_plan = read_json(paths.artifact_path("output/shot_plan.json"))
        except Exception as error:
            raise FlowError("SEMANTIC_RESET_CANONICAL_INPUT_INVALID") from error
        if not isinstance(requests, list):
            raise FlowError("SEMANTIC_RESET_CANONICAL_INPUT_INVALID")
        entries = {item.get("request_id"): item for item in manifest["requests"] if isinstance(item, dict)}
        tip_request = next((item for item in requests if item.get("request_id") == request_id), None)
        tip = entries.get(request_id)
        if isinstance(tip, dict) and (tip.get("semantic_reset_request_id")
                                     or tip.get("status") == SEMANTIC_RESET_PENDING_STATUS):
            raise FlowError("SEMANTIC_RESET_ALREADY_USED")
        if not isinstance(tip_request, dict) or not isinstance(tip, dict):
            raise FlowError("SEMANTIC_RESET_NOT_ELIGIBLE")
        if _creative_correction_epoch(tip_request, tip) != MAX_CREATIVE_CORRECTION_EPOCHS:
            raise FlowError("SEMANTIC_RESET_NOT_ELIGIBLE")
        chain: list[dict] = []
        current = tip
        seen: set[str] = set()
        while isinstance(current, dict) and isinstance(current.get("request_id"), str):
            current_id = current["request_id"]
            if current_id in seen:
                raise FlowError("SEMANTIC_RESET_LINEAGE_INVALID")
            seen.add(current_id); chain.append(current)
            parent_id = current.get("replacement_of")
            if parent_id is None: break
            current = entries.get(parent_id)
        if len(chain) != MAX_CREATIVE_CORRECTION_EPOCHS + 1:
            raise FlowError("SEMANTIC_RESET_NOT_ELIGIBLE")
        failed_inputs = []
        for historical in chain:
            selected = historical.get("selected_asset")
            attempts = historical.get("attempts")
            reviews = historical.get("quality_reviews")
            latest = reviews[-1] if isinstance(reviews, list) and reviews else None
            selected_attempt = selected.get("attempt") if isinstance(selected, dict) else None
            attempt = next((item for item in attempts or [] if isinstance(item, dict) and item.get("attempt") == selected_attempt), None)
            if (not isinstance(attempt, dict) or attempt.get("dispatch_confirmation_state") != "CONFIRMED"
                    or attempt.get("attribution_state") != "CONFIRMED" or not isinstance(selected, dict)
                    or not isinstance(latest, dict) or latest.get("status") != "REJECTED"
                    or latest.get("failure_class") != "VISUAL_NARRATION_ALIGNMENT_MISMATCH"):
                raise FlowError("SEMANTIC_RESET_NOT_ELIGIBLE")
            prompt = tip_request["prompt"] if historical.get("request_id") == request_id else historical.get("historical_prompt")
            if not isinstance(prompt, str) or not prompt:
                raise FlowError("SEMANTIC_RESET_LINEAGE_INVALID")
            failed_inputs.append({"request_id": historical["request_id"], "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                                  "reference_asset_hashes": list(historical.get("reference_asset_hashes", [])),
                                  "selected_asset_sha256": selected.get("sha256")})
        root_id = chain[-1]["request_id"]
        if any(item.get("semantic_reset_root_request_id") == root_id for item in requests):
            raise FlowError("SEMANTIC_RESET_ALREADY_USED")
        shot = next((item for item in shot_plan.get("shots", []) if item.get("shot_id") == tip_request.get("shot_id")), None)
        if not isinstance(shot, dict) or not all(isinstance(shot.get(key), str) and shot[key].strip()
                                                  for key in ("subject", "action", "composition_intent")):
            raise FlowError("SEMANTIC_RESET_CANONICAL_INPUT_INVALID")
        compatible_refs = [item for item in shot.get("prop_ids", []) if isinstance(item, str) and item]
        if len(compatible_refs) != 1:
            raise FlowError("SEMANTIC_RESET_CANONICAL_INPUT_INVALID")
        omitted_refs = [item for item in tip_request.get("reference_asset_ids", []) if item not in compatible_refs]
        geometry = _scene_geometry_contract(
            compatible_reference_asset_ids=compatible_refs, omitted_reference_asset_ids=omitted_refs
        )
        core = {"version": "story-auto-semantic-reset-core/1.0.0", "source": "shot_plan_only",
                "location": "INTERIOR", "composition": "DESK_DOCUMENT_DETAIL",
                "interaction": "INDEX_FINGER_TRACES_TRANSACTION_LIST",
                "subject": shot["subject"].strip(), "action": shot["action"].strip(),
                "compatible_reference_asset_ids": compatible_refs,
                "forbidden": ["exterior", "porch", "outdoor", "veranda", "yard", "daylight exterior"],
                "failed_request_ids": [item["request_id"] for item in reversed(failed_inputs)],
                "scene_geometry_contract": geometry}
        prompt = caption_safe_effective_prompt(_compile_scene_geometry_prompt(geometry, core["subject"], core["action"]))
        candidate_input = {"prompt": prompt, "depends_on": [], "reference_asset_ids": compatible_refs}
        reset_prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if any(item["prompt_sha256"] == reset_prompt_sha256 for item in failed_inputs):
            raise FlowError("SEMANTIC_RESET_MATERIAL_DELTA_REQUIRED")
        nonce = uuid.uuid4().hex
        fingerprint = hashlib.sha256(_json_sha256({"root": root_id, "core": core, "nonce": nonce}).encode("utf-8")).hexdigest()
        reset_id = "req_" + fingerprint[:20]
        reset = dict(tip_request)
        for key in ("replacement_of", "replaces_request_id", "replacement_reason", "replacement_epoch", "creative_correction_epoch",
                    "creative_correction_replan_proof", "root_request_id", "logical_visual_id", "supersedes_request_id", "correction_epoch"):
            reset.pop(key, None)
        reset.update({"request_id": reset_id, "fingerprint": fingerprint, "prompt": prompt, "depends_on": [],
                      "reference_asset_ids": compatible_refs, "epoch_nonce": nonce,
                      "semantic_reset_of_exhausted_request_id": request_id, "semantic_reset_root_request_id": root_id,
                      "semantic_reset_epoch": 1, "semantic_reset_core": core, "scene_geometry_contract": geometry,
                      "semantic_reset_material_delta": {"failed_generation_inputs": failed_inputs,
                          "reset_prompt_sha256": reset_prompt_sha256,
                          "reset_generation_input_sha256": _json_sha256(candidate_input),
                          "scene_geometry_contract_sha256": _json_sha256(geometry),
                          "compiled_geometry_prompt_sha256": reset_prompt_sha256,
                          "material_delta_against_all_failed": True}})
        at = _now()
        tip.update({"status": SEMANTIC_RESET_PENDING_STATUS, "semantic_reset_request_id": reset_id,
                    "semantic_reset_reason": reason.strip(), "updated_at": at})
        requests[requests.index(tip_request)] = reset
        _migrate_request_references(requests_data, request_id, reset_id)
        media_plan_path = paths.artifact_path("output/media_plan.json")
        media_plan = read_json(media_plan_path) if media_plan_path.is_file() else None
        media_plan_changed = isinstance(media_plan, dict) and _migrate_request_references(media_plan, request_id, reset_id)
        manifest["requests"].append({"request_id": reset_id, "request_identity_sha256": fingerprint,
            "related_identity": reset.get("shot_id"), "media_type": reset["media_type"], "provider": reset.get("provider", "google_flow"),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "reference_asset_hashes": [], "attempts": [],
            "provider_submissions": 0, "selected_asset": None, "attribution_claim": "NONE", "status": "PENDING", "created_at": at,
            "semantic_reset_of_exhausted_request_id": request_id, "semantic_reset_root_request_id": root_id, "semantic_reset_epoch": 1,
            "semantic_reset_core": core})
        transaction_id = "semantic-reset-" + _json_sha256({"project_id": project_id, "old": request_id, "new": reset_id})[:24]
        transaction = {"schema_version": SEMANTIC_RESET_TRANSACTION_SCHEMA, "state": "PREPARED", "transaction_id": transaction_id,
            "project_id": project_id, "old_request_id": request_id, "replacement_request_id": reset_id,
            "targets": {"generation_requests": _target("output/generation_requests.json", requests_data),
                        "generation_manifest": _target("output/generation_manifest.json", manifest)}}
        if media_plan_changed:
            transaction["targets"]["media_plan"] = _target("output/media_plan.json", media_plan)
        _publish_replacement_transaction(paths, transaction)
        return {"exhausted_request_id": request_id, "reset_request_id": reset_id, "provider_submissions": 0,
                "status": SEMANTIC_RESET_PENDING_STATUS, "root_cause": "CONFLICTING_EXTERIOR_REFERENCE_CAPACITY_SELECTION"}


def _canonical_parent_ids(paths, project_id: str, child_id: str, requests: list[dict],
                          entries: dict[str, dict]) -> list[str]:
    parents = []
    for parent_id, entry in entries.items():
        status = entry.get("status")
        if status == SUPERSEDED_AMBIGUOUS_STATUS:
            valid = entry.get("replacement_request_id") == child_id and _superseded_entry_valid(
                paths, project_id, entry, requests, entries)
        elif status == ABANDONED_UNRESOLVED_STATUS:
            valid = entry.get("replacement_request_id") == child_id and _abandoned_unresolved_entry_valid(
                paths, project_id, entry, requests, entries)
        elif status == QC_REJECTED_ASSET_REPLACED_STATUS:
            valid = entry.get("replacement_request_id") == child_id and _qc_rejected_asset_replacement_valid(
                paths, project_id, entry, requests, entries)
        elif status == SEMANTIC_RESET_PENDING_STATUS:
            valid = entry.get("semantic_reset_request_id") == child_id and _semantic_reset_parent_valid(
                paths, project_id, entry, requests, entries)
        elif status == QC_CORRECTIVE_REPLANNED_STATUS:
            valid = entry.get("correction_request_id") == child_id and _qc_corrective_replan_valid(
                paths, project_id, entry, requests, entries)
        elif status == QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS:
            valid = entry.get("pre_dispatch_supersession_request_id") == child_id and _qc_corrective_pre_dispatch_supersession_valid(
                paths, project_id, entry, requests, entries)
        else:
            valid = False
        if valid:
            parents.append(parent_id)
    return parents


def _resolve_logical_root_request_id(paths, project_id: str, request_id: str, requests: list[dict],
                                     entries: dict[str, dict]) -> tuple[str, list[str]]:
    """Walk only receipt-proven reverse edges to the immutable logical root."""
    lineage = [request_id]
    current = request_id
    while True:
        parents = _canonical_parent_ids(paths, project_id, current, requests, entries)
        if not parents:
            break
        if len(parents) != 1 or parents[0] in lineage:
            raise FlowError("QC_CORRECTIVE_REPLAN_LINEAGE_INVALID")
        current = parents[0]
        lineage.append(current)
    if current not in entries:
        raise FlowError("QC_CORRECTIVE_REPLAN_LINEAGE_INVALID")
    return current, lineage


def _latest_qc_rejection(entry: dict) -> dict:
    reviews = entry.get("quality_reviews")
    latest = reviews[-1] if isinstance(reviews, list) and reviews else None
    if not isinstance(latest, dict):
        raise FlowError("QC_CORRECTIVE_REPLAN_NOT_ELIGIBLE")
    return latest


def _video_continuity_qc_approved(entry: dict | None) -> bool:
    """A VIDEO correction may preserve motion only for an approved temporal, continuity-only rejection."""
    if not isinstance(entry, dict):
        return False
    selected = entry.get("selected_asset")
    latest = _latest_qc_rejection(entry)
    report = latest.get("report") if isinstance(latest, dict) else None
    results = report.get("results") if isinstance(report, dict) else None
    if not isinstance(selected, dict) or selected.get("temporal_qc") != "APPROVED" or not isinstance(results, dict):
        return False
    if str(results.get("CONTINUITY", "")).upper() != "FAIL":
        return False
    return all(str(value).upper() == "PASS" for field, value in results.items() if field != "CONTINUITY")


def _confirmed_selected_attempt(entry: dict | None) -> bool:
    """A corrective epoch can only start from attributed selected bytes."""
    if not isinstance(entry, dict) or not isinstance(entry.get("selected_asset"), dict):
        return False
    selected_attempt = entry["selected_asset"].get("attempt")
    return isinstance(entry.get("attempts"), list) and any(
        isinstance(attempt, dict)
        and attempt.get("attempt") == selected_attempt
        and attempt.get("attribution_state") == "CONFIRMED"
        for attempt in entry["attempts"]
    )


def _video_temporal_qc_rejected(entry: dict | None) -> bool:
    if not isinstance(entry, dict) or entry.get("media_type") != "VIDEO":
        return False
    selected = entry.get("selected_asset")
    if not isinstance(selected, dict) or selected.get("temporal_qc") != "REJECTED":
        return False
    reviews = selected.get("temporal_reviews")
    latest = reviews[-1] if isinstance(reviews, list) and reviews else None
    report = latest.get("report") if isinstance(latest, dict) else None
    return (isinstance(report, dict)
            and str(report.get("state", "")) in TERMINAL_TEMPORAL_FAILURES)


def _latest_temporal_qc_rejection(entry: dict) -> dict:
    selected = entry.get("selected_asset")
    reviews = selected.get("temporal_reviews") if isinstance(selected, dict) else None
    latest = reviews[-1] if isinstance(reviews, list) and reviews else None
    if not isinstance(latest, dict) or not isinstance(latest.get("report"), dict):
        raise FlowError("QC_CORRECTIVE_REPLAN_NOT_ELIGIBLE")
    return {
        "status": "REJECTED",
        "failure_class": entry.get("failure_class"),
        "report": latest["report"],
        "selected_asset_path": selected.get("path"),
        "selected_asset_sha256": selected.get("sha256"),
    }


def _intent_terms(value: Any) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", str(value).lower()) if len(term) > 2}


def _persisted_action_contradicts_shot(request: dict, shot: dict) -> bool:
    """Detect an explicit failed-request action/state contradiction deterministically."""
    prompt = str(request.get("prompt", "")).lower()
    action = str(shot.get("action", "")).lower()
    # These concrete state transitions are material generation semantics, not
    # style words.  If the canonical action requires one yet the provider
    # prompt omits it (or states its opposite), a preserved-motion correction
    # would reintroduce the defect.
    for cue in ("lower", "raise", "open", "close", "pick", "place", "lift", "walk", "turn"):
        if cue in action and cue not in prompt:
            return True
    return ("lower" in action and ("elevated" in prompt or "remain still" in prompt))


def _qc_corrective_mode(request: dict, entry: dict, shot: dict) -> str | None:
    if request.get("media_type") != "VIDEO":
        return SEMANTIC_ONLY if _terminal_qc_rejection(entry) else None
    if _video_temporal_qc_rejected(entry) or _persisted_action_contradicts_shot(request, shot):
        return FULL_REPLAN if _confirmed_selected_attempt(entry) else None
    return SEMANTIC_ONLY if _terminal_qc_rejection(entry) and _video_continuity_qc_approved(entry) else None


def _canonical_scene_continuity(shot: dict, shots: list[dict], entities: dict[str, dict]) -> dict:
    """Derive only adjacent, same-scene continuity facts from the shot plan."""
    scene_id = shot.get("scene_id")
    start = shot.get("start")
    if not isinstance(scene_id, str) or not isinstance(start, (int, float)):
        return {}
    predecessors = [item for item in shots if isinstance(item, dict)
                    and item is not shot and item.get("scene_id") == scene_id
                    and isinstance(item.get("end"), (int, float)) and item["end"] <= start + .05]
    if not predecessors:
        return {}
    previous = max(predecessors, key=lambda item: float(item["end"]))
    source_text = " ".join(str(previous.get(field, "")) for field in (
        "action", "camera_intent", "composition_intent", "previous_shot_context", "next_shot_handoff"))
    location = entities.get(shot.get("location_id"), {})
    required_location = ""
    if "dim kitchen" in source_text.lower():
        required_location = f"dim kitchen inside {location.get('name') or shot.get('location_id')}"
    return {
        "previous_shot_id": previous.get("shot_id"),
        "previous_shot_action": previous.get("action"),
        "previous_shot_camera_intent": previous.get("camera_intent"),
        "previous_shot_composition_intent": previous.get("composition_intent"),
        "required_location": required_location,
    }


def _canonical_locked_corrective_core(old_request: dict, *, shot: dict, entities: dict[str, dict],
                                      scene_continuity: dict) -> dict:
    """Derive the non-negotiable shot semantics before Gemini can reason.

    This core is intentionally source-derived rather than reconstructed from a
    failed provider prompt.  A corrective model may improve mechanics and
    presentation, but it never owns story identity, location, continuity,
    principal action, props, timing, or media type.
    """
    location_entity = entities.get(shot.get("location_id"), {})
    location_source = " ".join([
        str(location_entity.get("name", "")),
        *[str(item) for item in location_entity.get("constraints", []) if isinstance(item, str)],
        str(shot.get("composition_intent", "")),
        str(scene_continuity.get("required_location", "")),
    ])
    location_name = str(location_entity.get("name") or shot.get("location_id") or "").strip()
    canonical_location = str(scene_continuity.get("required_location", "")).strip()
    if not canonical_location and "dim kitchen" in location_source.lower() and location_name:
        canonical_location = f"dim kitchen inside {location_name}"
    if not canonical_location:
        canonical_location = location_name
    if not canonical_location:
        # Abstract closing beats can intentionally omit a concrete location.
        # Keep the correction runnable without inventing a story place or
        # copying the rejected provider composition back into the prompt.
        canonical_location = "a neutral, text-free cinematic setting consistent with the narrated moment"
    prop_names = [str(entities.get(prop_id, {}).get("name", "")).strip()
                  for prop_id in shot.get("prop_ids", []) if isinstance(prop_id, str)]
    prop_names = [item for item in prop_names if item]
    continuity_requirements = []
    previous_shot_id = scene_continuity.get("previous_shot_id")
    if isinstance(previous_shot_id, str) and previous_shot_id:
        continuity_requirements.append(f"Direct continuation from canonical preceding shot {previous_shot_id}.")
    elif "continu" in str(shot.get("composition_intent", "")).lower():
        continuity_requirements.append(f"Direct continuation of canonical shot {shot.get('shot_id')}.")
    if canonical_location:
        continuity_requirements.append(f"Location continuity: {canonical_location}.")
    if prop_names:
        continuity_requirements.append("Required props remain present: " + ", ".join(prop_names) + ".")
    canonical_exclusions = []
    if not location_name:
        canonical_exclusions.append(
            "no readable words, letters, logos, screens, signs, title cards, captions, or interface elements"
        )
    if "kitchen" in canonical_location.lower():
        canonical_exclusions.extend((
            "no lantern room",
            "no great lighthouse lens",
            "no ocean-facing gallery",
            "no tower/gallery interior or relocation away from the kitchen",
        ))
    return {
        "logical_shot_id": shot.get("shot_id"),
        "scene_id": shot.get("scene_id"),
        "subject": str(shot.get("subject", "")).strip(),
        "location": canonical_location,
        "continuity_requirements": continuity_requirements,
        "action": str(shot.get("action", "")).strip(),
        "required_props": prop_names,
        "canonical_exclusions": canonical_exclusions,
        "target_start": old_request.get("target_start"),
        "target_end": old_request.get("target_end"),
        "target_duration": old_request.get("target_duration"),
        "media_type": old_request.get("media_type"),
    }


def _locked_core_override_evidence(model_intent: dict, locked_core: dict) -> dict:
    """Record attempted semantic substitutions without ever promoting them."""
    overrides = {}
    for field in ("subject", "location", "action", "continuity_requirements"):
        model_value = model_intent.get(field)
        canonical_value = locked_core.get(field)
        if model_value != canonical_value:
            overrides[field] = {"model_value": model_value, "canonical_value": canonical_value}
    return overrides


def _compile_locked_corrective_intent(model_intent: dict, locked_core: dict, *, shot: dict) -> dict:
    """Combine a validated Gemini delta with immutable canonical semantics."""
    compiled = dict(model_intent)
    compiled.update({
        "subject": locked_core["subject"],
        "action": locked_core["action"],
        "location": locked_core["location"],
        "continuity_requirements": list(locked_core["continuity_requirements"]),
        # Composition is provider-facing detail, but must begin with canonical
        # location/continuity rather than an untrusted rewritten room or beat.
        "composition_intent": str(shot.get("composition_intent") or locked_core["location"]),
    })
    compiled["exclusions"] = list(dict.fromkeys([
        *locked_core.get("canonical_exclusions", []),
        *[item for item in model_intent.get("exclusions", []) if isinstance(item, str)],
    ]))
    return compiled


def _require_canonical_corrective_intent(*, correction: dict, corrected_intent: dict,
                                         locked_core: dict) -> None:
    """Fail closed unless the final runnable request exactly retains locked core."""
    for field in ("subject", "action", "location", "continuity_requirements"):
        if corrected_intent.get(field) != locked_core.get(field):
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_MISMATCH", field)
    for field in ("media_type", "target_start", "target_end", "target_duration"):
        if correction.get(field) != locked_core.get(field):
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_MISMATCH", field)
    prompt_terms = _intent_terms(correction.get("prompt"))
    for field in ("subject", "action", "location"):
        required_terms = _intent_terms(locked_core.get(field))
        if required_terms and not required_terms <= prompt_terms:
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_MISMATCH", field)
    semantic_terms = prompt_terms | _intent_terms(corrected_intent.get("continuity_requirements"))
    for prop_name in locked_core.get("required_props", []):
        prop_terms = _intent_terms(prop_name)
        if prop_terms and not prop_terms <= semantic_terms:
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_MISMATCH", "prop")


_REFERENCE_CONFLICT_CUES = (
    "lantern room", "lantern-room", "great lighthouse lens", "great lens",
    "ocean-facing gallery", "ocean gallery", "tower/gallery", "tower gallery",
    "rotating fresnel lens", "fresnel lens",
)


def _safe_reference_candidate(request: dict, entry: dict, canonical_entity: dict | None) -> dict:
    """Expose only planner-relevant, non-secret provenance for a reference."""
    selected = entry.get("selected_asset") if isinstance(entry, dict) else None
    metadata = selected.get("metadata") if isinstance(selected, dict) else None
    return {
        "entity_id": request.get("entity_id"),
        "reference_request_id": request.get("request_id"),
        "reference_type": request.get("reference_type"),
        "reference_prompt": request.get("prompt"),
        "reference_visual_brief": request.get("visual_brief"),
        "canonical_entity": canonical_entity,
        "selected_asset": ({
            "sha256": selected.get("sha256"),
            "pixel_sha256": metadata.get("pixel_sha256") if isinstance(metadata, dict) else None,
            "dhash256": metadata.get("dhash256") if isinstance(metadata, dict) else None,
        } if isinstance(selected, dict) else None),
    }


def _corrective_reference_policy(corrected_intent: dict, reference_candidates: list[dict],
                                 *, capacity: int = FLOW_REFERENCE_CAPACITY) -> dict:
    """Evaluate the references Flow will actually receive; never infer from order."""
    selected = corrected_intent.get("selected_reference_entity_ids") if isinstance(corrected_intent, dict) else None
    if (not isinstance(capacity, int) or capacity < 0 or not isinstance(selected, list)
            or len(selected) != len(set(selected))):
        raise FlowError("QC_CORRECTIVE_REPLAN_REFERENCE_POLICY_INVALID")
    candidates = {item.get("entity_id"): item for item in reference_candidates if isinstance(item, dict)}
    if any(not isinstance(item, str) or item not in candidates for item in selected):
        raise FlowError("QC_CORRECTIVE_REPLAN_REFERENCE_POLICY_INVALID")
    context = " ".join([
        str(corrected_intent.get("location", "")),
        *[str(item) for item in corrected_intent.get("continuity_requirements", [])],
        *[str(item) for item in corrected_intent.get("exclusions", [])],
    ]).lower()
    conflicts = []
    for entity_id in selected:
        candidate = candidates[entity_id]
        evidence = json.dumps({
            "reference_prompt": candidate.get("reference_prompt"),
            "reference_visual_brief": candidate.get("reference_visual_brief"),
            "canonical_entity": candidate.get("canonical_entity"),
        }, ensure_ascii=False).lower()
        cues = [cue for cue in _REFERENCE_CONFLICT_CUES if cue in evidence and (cue in context or "kitchen" in context)]
        if cues:
            conflicts.append({"entity_id": entity_id, "cues": cues})
    effective = []
    removed_conflicts = []
    conflict_ids = {item["entity_id"] for item in conflicts}
    for entity_id in selected:
        if entity_id in conflict_ids:
            removed_conflicts.append(entity_id)
        elif len(effective) < capacity:
            effective.append(entity_id)
    return {
        "reference_capacity": capacity,
        "selected_reference_entity_ids": list(selected),
        "effective_reference_entity_ids": effective,
        "conflicts": conflicts,
        "removed_conflicting_reference_entity_ids": removed_conflicts,
    }


def _require_valid_corrective_reference_policy(corrected_intent: dict, reference_candidates: list[dict]) -> dict:
    policy = _corrective_reference_policy(corrected_intent, reference_candidates)
    if len(policy["effective_reference_entity_ids"]) > policy["reference_capacity"]:
        raise FlowError("QC_CORRECTIVE_REPLAN_REFERENCE_POLICY_INVALID")
    return policy


def qc_corrective_replan(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str,
                         router: GeminiReasoningRouter | None = None,
                         _fault_injector: Callable[[str], None] | None = None) -> dict:
    """Create one canonical semantic correction epoch from a terminal QC rejection.

    This is intentionally not a general replacement-of-replacement operation:
    only the current IMAGE-shot or approved-temporal continuity-only VIDEO
    lineage tip with confirmed attribution and a
    latest terminal QC rejection can reach Gemini or receive a fresh identity.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("QC_CORRECTIVE_REPLAN_REASON_REQUIRED")
    paths, _config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    active_router = router or GeminiReasoningRouter(
        cache_dir=paths.runtime.cache / "gemini_reasoning",
        ledger_path=paths.runtime.evidence / "gemini_reasoning_ledger.json",
    )
    with ProjectLock(paths.runtime, project_id):
        recovered = _recover_pending_qc_corrective_replans(paths, project_id)
        manifest_path, manifest = _manifest(paths, project_id)
        requests_path = paths.artifact_path("output/generation_requests.json")
        shot_path = paths.artifact_path("output/shot_plan.json")
        continuity_path = paths.artifact_path("output/continuity_bible.json")
        media_plan_path = paths.artifact_path("output/media_plan.json")
        try:
            requests_data = read_json(requests_path)
            requests = requests_data.get("requests") if isinstance(requests_data, dict) else None
            shot_plan = read_json(shot_path)
            continuity = read_json(continuity_path)
            media_plan = read_json(media_plan_path)
        except Exception as error:
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_INVALID") from error
        if not isinstance(requests, list):
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_INVALID")
        entries = {item.get("request_id"): item for item in manifest.get("requests", []) if isinstance(item, dict)}
        old_request = next((item for item in requests if item.get("request_id") == request_id), None)
        old_entry = entries.get(request_id)
        if not isinstance(old_request, dict):
            completed = recovered.get(request_id)
            if (isinstance(old_entry, dict) and completed
                    and _qc_corrective_replan_valid(paths, project_id, old_entry, requests, entries)):
                child_id = completed["replacement_request_id"]
                child_entry = entries.get(child_id, {})
                return {
                    "root_request_id": child_entry.get("root_request_id"),
                    "supersedes_request_id": request_id,
                    "correction_request_id": child_id,
                    "correction_epoch": child_entry.get("correction_epoch"),
                    "provider_submissions": 0,
                    "gemini_model": child_entry.get("corrective_replan_provenance", {}).get("model"),
                    "status": QC_CORRECTIVE_REPLANNED_STATUS,
                    "idempotent": True,
                }
            raise FlowError("QC_CORRECTIVE_REPLAN_ALREADY_COMPLETED")
        media_type = old_request.get("media_type")
        if (old_request.get("purpose") != "SHOT" or media_type not in {"IMAGE", "VIDEO"}
                or not isinstance(old_entry, dict)):
            raise FlowError("QC_CORRECTIVE_REPLAN_NOT_ELIGIBLE")
        if _direct_qc_corrective_child_ids(paths, project_id, request_id) != []:
            raise FlowError("QC_CORRECTIVE_REPLAN_ALREADY_COMPLETED")
        try:
            validate_generation_requests(requests_data, media_plan, continuity)
        except PlanningError as error:
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_INVALID", error.failure_class) from error
        root_request_id, lineage = _resolve_logical_root_request_id(
            paths, project_id, request_id, requests, entries)
        if _resolve_current_canonical_descendant(paths, project_id, root_request_id, requests, entries) != request_id:
            raise FlowError("QC_CORRECTIVE_REPLAN_LINEAGE_INVALID")
        shot_id = old_request.get("shot_id")
        shot = next((item for item in shot_plan.get("shots", []) if item.get("shot_id") == shot_id), None)
        media = next((item for item in media_plan.get("shots", []) if item.get("shot_id") == shot_id), None)
        if (not isinstance(shot, dict) or not isinstance(media, dict)
                or media.get("media_type") != media_type):
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_INVALID")
        correction_mode = _qc_corrective_mode(old_request, old_entry, shot)
        if correction_mode is None:
            raise FlowError("QC_CORRECTIVE_REPLAN_NOT_ELIGIBLE")
        relevant_entity_ids = list(dict.fromkeys(
            shot.get("character_ids", []) + shot.get("prop_ids", [])
            + ([shot["location_id"]] if shot.get("location_id") else [])
        ))
        entities = {
            item.get("entity_id"): item
            for kind in ("characters", "locations", "props")
            for item in continuity.get(kind, []) if isinstance(item, dict)
        }
        scene_continuity = _canonical_scene_continuity(
            shot, [item for item in shot_plan.get("shots", []) if isinstance(item, dict)], entities)
        locked_core = _canonical_locked_corrective_core(
            old_request, shot=shot, entities=entities, scene_continuity=scene_continuity)
        if (not all(isinstance(locked_core.get(field), str) and locked_core[field] for field in
                    ("logical_shot_id", "subject", "location", "action", "media_type"))
                or not isinstance(locked_core.get("continuity_requirements"), list)
                or not locked_core["continuity_requirements"]):
            raise FlowError("QC_CORRECTIVE_REPLAN_CANONICAL_INPUT_INVALID", "locked_core")
        reference_request_by_entity = {}
        reference_candidates = []
        reference_media: list[LLMMedia] = []
        for request in requests:
            entity_id = request.get("entity_id")
            entry = entries.get(request.get("request_id"))
            if (request.get("purpose") != "REFERENCE" or entity_id not in relevant_entity_ids
                    or not isinstance(entry, dict) or entry.get("status") != "SUCCEEDED"):
                continue
            reference_request_by_entity[entity_id] = request["request_id"]
            candidate = _safe_reference_candidate(request, entry, entities.get(entity_id))
            selected_asset = entry.get("selected_asset")
            asset_path = selected_asset.get("path") if isinstance(selected_asset, dict) else None
            asset_sha = selected_asset.get("sha256") if isinstance(selected_asset, dict) else None
            source = paths.artifact_path(asset_path) if isinstance(asset_path, str) else None
            suffixes = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            if (source is not None and source.is_file() and source.suffix.lower() in suffixes
                    and len(reference_media) < len(relevant_entity_ids)
                    and source.stat().st_size <= 12 * 1024 * 1024):
                label = f"reference:{entity_id}:{str(asset_sha)[:16]}"
                candidate["reference_media_label"] = label
                reference_media.append(LLMMedia(label=label, mime_type=suffixes[source.suffix.lower()], data=source.read_bytes()))
            reference_candidates.append(candidate)
        root_entry = entries[root_request_id]
        original_prompt = root_entry.get("historical_prompt")
        if not isinstance(original_prompt, str) or not original_prompt.strip():
            original_prompt = old_request.get("prompt")
        latest_rejection = (_latest_temporal_qc_rejection(old_entry)
                            if correction_mode == FULL_REPLAN and _video_temporal_qc_rejected(old_entry)
                            else _latest_qc_rejection(old_entry))
        original_logical_request = {
            "root_request_id": root_request_id,
            "purpose": old_request.get("purpose"),
            "shot_id": shot_id,
            "media_type": old_request.get("media_type"),
            "prompt": original_prompt,
            "visual_brief": old_request.get("visual_brief"),
        }
        superseded_request_snapshot = json.loads(json.dumps(old_request, ensure_ascii=False))
        canonical_context = {
            "canonical_locked_core": locked_core,
            "shot_plan_shot": shot,
            "continuity_entities": [entities[item] for item in relevant_entity_ids if item in entities],
            "media_plan_shot": media,
            "adjacent_scene_continuity": scene_continuity,
            "original_logical_request_intent": original_logical_request,
            "latest_qc_rejection": latest_rejection,
            "reference_candidates": reference_candidates,
            "provider_reference_capacity": FLOW_REFERENCE_CAPACITY,
            "prior_reference_selection": {
                "entity_ids": old_request.get("reference_asset_ids", []),
                "request_ids": old_request.get("depends_on", []),
            },
        }
        try:
            model_corrective_intent, reasoning = plan_qc_corrective_intent(
                active_router,
                canonical_context=canonical_context,
                reference_entity_ids=set(reference_request_by_entity),
                reference_capacity=FLOW_REFERENCE_CAPACITY,
                reference_media=tuple(reference_media),
            )
            model_override_evidence = _locked_core_override_evidence(model_corrective_intent, locked_core)
            corrected_intent = _compile_locked_corrective_intent(
                model_corrective_intent, locked_core, shot=shot)
            reference_policy = _require_valid_corrective_reference_policy(
                corrected_intent, reference_candidates)
            corrected_intent["selected_reference_entity_ids"] = list(
                reference_policy["effective_reference_entity_ids"])
            full_motion_plan = None
            motion_reasoning = None
            if correction_mode == FULL_REPLAN:
                motion_intent = {
                    "schema_version": MOTION_PLAN_VERSION,
                    "request_id": old_request["request_id"],
                    "shot_id": shot_id,
                    "target_start": old_request.get("target_start"),
                    "target_end": old_request.get("target_end"),
                    "target_duration": old_request.get("target_duration"),
                    "subject": corrected_intent["subject"],
                    "action": corrected_intent["action"],
                    "location": corrected_intent["location"],
                    "camera_intent": shot.get("camera_intent"),
                    "composition_intent": corrected_intent["composition_intent"],
                    "visual_emotional_purpose": shot.get("visual_emotional_purpose"),
                    "reference_asset_ids": list(corrected_intent["selected_reference_entity_ids"]),
                    # A corrective transaction has one fresh child.  Ask the
                    # shared planner for mechanics that fit that exact Flow
                    # request rather than silently dropping planned clips.
                    "required_atomic_clip_count": 1,
                }
                full_motion_plan, motion_reasoning = plan_motion(active_router, motion_intent)
            correction = compile_qc_corrected_request(
                old_request,
                corrected_intent,
                reference_request_by_entity=reference_request_by_entity,
                correction_mode=correction_mode,
                full_motion_plan=full_motion_plan,
            )
            _require_canonical_corrective_intent(
                correction=correction, corrected_intent=corrected_intent, locked_core=locked_core)
        except QCCorrectiveReplanError as error:
            raise FlowError(error.failure_class) from error
        except Exception as error:
            failure = getattr(error, "failure_class", "QC_CORRECTIVE_REPLAN_GEMINI_FAILED")
            raise FlowError(failure) from error
        previous_entities = list(old_request.get("reference_asset_ids", []))
        previous_dependencies = list(old_request.get("depends_on", []))
        reference_delta = {
            "previous_reference_entity_ids": previous_entities,
            "selected_reference_entity_ids": list(correction["reference_asset_ids"]),
            "removed_reference_entity_ids": [item for item in previous_entities if item not in correction["reference_asset_ids"]],
            "added_reference_entity_ids": [item for item in correction["reference_asset_ids"] if item not in previous_entities],
            "previous_dependency_request_ids": previous_dependencies,
            "selected_dependency_request_ids": list(correction["depends_on"]),
        }
        epoch = max(
            [0] + [int(old_request.get(field, 0)) for field in ("replacement_epoch", "replay_epoch", "correction_epoch")
                   if isinstance(old_request.get(field, 0), int)]
        ) + 1
        nonce = uuid.uuid4().hex
        identity = {
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "correction_nonce": nonce,
            "corrected_semantic_intent": corrected_intent,
            "prompt": correction["prompt"],
            "depends_on": correction["depends_on"],
        }
        fingerprint = _json_sha256(identity)
        correction_id = "req_" + fingerprint[:20]
        if correction_id in entries or any(item.get("request_id") == correction_id for item in requests):
            raise FlowError("QC_CORRECTIVE_REPLAN_IDENTITY_COLLISION")
        canonical_inputs = {
            "shot_plan_sha256": sha256_file(shot_path),
            "continuity_bible_sha256": sha256_file(continuity_path),
            "media_plan_sha256": sha256_file(media_plan_path),
            "original_logical_request_sha256": _json_sha256(original_logical_request),
            "superseded_request_sha256": _json_sha256(superseded_request_snapshot),
            "latest_qc_rejection_sha256": _json_sha256(latest_rejection),
        }
        provenance = {
            "provider": "gemini",
            "model": reasoning.model,
            "router_input_hash": reasoning.input_hash,
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "canonical_inputs": canonical_inputs,
            "canonical_locked_core": locked_core,
            "non_authoritative_model_output": model_corrective_intent,
            "non_authoritative_locked_core_overrides": model_override_evidence,
            "corrected_semantic_intent": corrected_intent,
            "semantic_delta": list(corrected_intent["semantic_delta"]),
            "correction_mode": correction_mode,
            "reference_selection_delta": reference_delta,
            "reference_policy": reference_policy,
            "deterministic_compiler": (
                "compile_flow_motion_prompt" if media_type == "VIDEO" else "compile_image_prompt"
            ),
        }
        if motion_reasoning is not None:
            provenance["motion_replan"] = {
                "schema_version": MOTION_PLAN_VERSION,
                "model": motion_reasoning.model,
                "router_input_hash": motion_reasoning.input_hash,
                "cache_hit": motion_reasoning.cache_hit,
                "fallback_count": motion_reasoning.fallback_count,
                "request_count": motion_reasoning.request_count,
                "plan": full_motion_plan,
            }
        for field in (
            "replacement_of", "replaces_request_id", "replacement_reason", "replacement_epoch",
            "replays_unresolved_request_id", "replay_epoch", "replay_creation_transaction_id",
            "replay_genesis_sha256", "epoch_nonce",
        ):
            correction.pop(field, None)
        correction.update({
            "request_id": correction_id,
            "fingerprint": fingerprint,
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "correction_nonce": nonce,
            "correction_reason": QC_CORRECTIVE_REPLAN_REASON,
            "corrective_replan_provenance": provenance,
        })
        position = requests.index(old_request)
        requests[position] = correction
        _migrate_request_references(requests_data, request_id, correction_id)
        media_plan_changed = _migrate_request_references(media_plan, request_id, correction_id)
        try:
            validate_generation_requests(requests_data, media_plan, continuity)
        except PlanningError as error:
            raise FlowError("QC_CORRECTIVE_REPLAN_DETERMINISTIC_VALIDATION_FAILED", error.failure_class) from error
        prior_evidence_hash = _json_sha256(_qc_rejection_evidence_projection(old_entry))
        at = _now()
        event = {
            "at": at,
            "event": QC_CORRECTIVE_REPLAN_REASON,
            "operator_reason": reason.strip(),
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_request_id": correction_id,
            "correction_epoch": epoch,
            "prior_qc_evidence_sha256": prior_evidence_hash,
            "superseded_request_sha256": canonical_inputs["superseded_request_sha256"],
            "latest_qc_rejection_sha256": canonical_inputs["latest_qc_rejection_sha256"],
            "gemini_model": reasoning.model,
            "semantic_delta": list(corrected_intent["semantic_delta"]),
            "reference_selection_delta": reference_delta,
        }
        old_entry.setdefault("qc_corrective_replan_events", []).append(event)
        old_entry.update({
            "status": QC_CORRECTIVE_REPLANNED_STATUS,
            "correction_request_id": correction_id,
            "correction_reason": QC_CORRECTIVE_REPLAN_REASON,
            "updated_at": at,
        })
        manifest["requests"].append({
            "request_id": correction_id,
            "request_identity_sha256": fingerprint,
            "related_identity": shot_id,
            "media_type": correction["media_type"],
            "provider": correction.get("provider", "google_flow"),
            "prompt_sha256": hashlib.sha256(correction["prompt"].encode("utf-8")).hexdigest(),
            "reference_asset_hashes": [],
            "attempts": [],
            "provider_submissions": 0,
            "selected_asset": None,
            "attribution_claim": "NONE",
            "status": "PENDING",
            "created_at": at,
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "correction_nonce": nonce,
            "correction_reason": QC_CORRECTIVE_REPLAN_REASON,
            "corrected_semantic_intent": corrected_intent,
            "corrective_replan_provenance": provenance,
        })
        if _json_sha256(_qc_rejection_evidence_projection(old_entry)) != prior_evidence_hash:
            raise FlowError("QC_CORRECTIVE_REPLAN_APPEND_ONLY_VIOLATION")
        transaction_id = "qc-corrective-replan-" + _json_sha256({
            "project_id": project_id,
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_request_id": correction_id,
        })[:24]
        targets = {
            "generation_requests": _target("output/generation_requests.json", requests_data),
            "generation_manifest": _target("output/generation_manifest.json", manifest),
        }
        if media_plan_changed:
            targets["media_plan"] = _target("output/media_plan.json", media_plan)
        transaction = {
            "schema_version": QC_CORRECTIVE_REPLAN_TRANSACTION_SCHEMA,
            "state": "PREPARED",
            "transaction_id": transaction_id,
            "project_id": project_id,
            "old_request_id": request_id,
            "replacement_request_id": correction_id,
            "root_request_id": root_request_id,
            "correction_epoch": epoch,
            "superseded_request": superseded_request_snapshot,
            "superseded_request_sha256": canonical_inputs["superseded_request_sha256"],
            "targets": targets,
        }
        _publish_replacement_transaction(paths, transaction, fault_injector=_fault_injector)
        return {
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_request_id": correction_id,
            "correction_epoch": epoch,
            "provider_submissions": 0,
            "gemini_model": reasoning.model,
            "status": QC_CORRECTIVE_REPLANNED_STATUS,
            "idempotent": False,
        }


def supersede_invalid_pending_qc_corrective_child(runtime_root: Path | str, project_id: str, request_id: str, *,
                                                  reason: str,
                                                  _fault_injector: Callable[[str], None] | None = None) -> dict:
    """Replace one policy-invalid, never-dispatched corrective child with a zero-reference child.

    This is deliberately narrower than prompt editing or generic pending replacement:
    it preserves the rejected corrective intent, accepts only an untouched
    qc-corrective child, and only runs after deterministic reference-policy
    rejection proves that Flow would receive a conflicting reference.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        recovered = _recover_pending_qc_corrective_pre_dispatch_supersessions(paths, project_id)
        manifest_path, manifest = _manifest(paths, project_id)
        requests_path = paths.artifact_path("output/generation_requests.json")
        media_plan_path = paths.artifact_path("output/media_plan.json")
        continuity_path = paths.artifact_path("output/continuity_bible.json")
        try:
            requests_data = read_json(requests_path)
            requests = requests_data.get("requests") if isinstance(requests_data, dict) else None
            media_plan = read_json(media_plan_path)
            continuity = read_json(continuity_path)
        except Exception as error:
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_INVALID") from error
        if not isinstance(requests, list):
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_INVALID")
        entries = {item.get("request_id"): item for item in manifest.get("requests", []) if isinstance(item, dict)}
        old_request = next((item for item in requests if item.get("request_id") == request_id), None)
        old_entry = entries.get(request_id)
        if not isinstance(old_request, dict):
            completed = recovered.get(request_id)
            if (isinstance(old_entry, dict) and completed
                    and _qc_corrective_pre_dispatch_supersession_valid(paths, project_id, old_entry, requests, entries)):
                return {"old_request_id": request_id,
                        "replacement_request_id": completed["replacement_request_id"],
                        "provider_submissions": 0,
                        "status": QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS,
                        "idempotent": True}
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_ALREADY_COMPLETED")
        direct_pending_reference_conflict = (
            old_request.get("purpose") == "SHOT"
            and old_request.get("correction_reason") is None
            and old_request.get("root_request_id") is None
            and old_request.get("supersedes_request_id") is None
            and isinstance(old_request.get("reference_asset_ids"), list)
            and len(old_request["reference_asset_ids"]) > FLOW_REFERENCE_CAPACITY
        )
        if (old_request.get("purpose") != "SHOT"
                or (old_request.get("correction_reason") != QC_CORRECTIVE_REPLAN_REASON
                    and not direct_pending_reference_conflict)
                or not isinstance(old_entry, dict)
                or old_entry.get("status") != "PENDING"
                or old_entry.get("attempts") != []
                or old_entry.get("provider_submissions", 0) != 0
                or old_entry.get("selected_asset") is not None
                or old_entry.get("attribution_claim", "NONE") != "NONE"
                or not _qc_corrective_metadata_has_direct_origin(paths, project_id, old_request)):
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_NOT_ELIGIBLE")
        selected_entities = list(old_request.get("reference_asset_ids", []))
        candidate_by_entity = {}
        for candidate_request in requests:
            entity_id = candidate_request.get("entity_id")
            candidate_entry = entries.get(candidate_request.get("request_id"))
            if (candidate_request.get("purpose") == "REFERENCE" and entity_id in selected_entities
                    and isinstance(candidate_entry, dict) and candidate_entry.get("status") == "SUCCEEDED"):
                candidate_by_entity[entity_id] = _safe_reference_candidate(candidate_request, candidate_entry, None)
        corrected_intent = old_request.get("corrected_semantic_intent")
        if direct_pending_reference_conflict:
            corrected_intent = {
                "selected_reference_entity_ids": selected_entities,
                "location": old_request.get("prompt", ""),
                "continuity_requirements": [],
                "exclusions": ["reference capacity conflict must not select an arbitrary visual family"],
            }
        policy = _corrective_reference_policy(corrected_intent, list(candidate_by_entity.values()))
        if (len(policy["selected_reference_entity_ids"]) <= policy["reference_capacity"]
                and not policy["conflicts"]):
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_NOT_ELIGIBLE")
        old_request_snapshot = json.loads(json.dumps(old_request, ensure_ascii=False))
        old_entry_snapshot = json.loads(json.dumps(old_entry, ensure_ascii=False))
        root_request_id = old_request.get("root_request_id") or request_id
        epoch = int(old_request.get("correction_epoch", 0)) + 1
        nonce = uuid.uuid4().hex
        identity = {
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "correction_nonce": nonce,
            "prompt": old_request.get("prompt"),
            "corrected_semantic_intent": corrected_intent,
            "effective_reference_entity_ids": [],
        }
        fingerprint = _json_sha256(identity)
        replacement_id = "req_" + fingerprint[:20]
        if replacement_id in entries or any(item.get("request_id") == replacement_id for item in requests):
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_IDENTITY_COLLISION")
        provenance = {
            "root_request_id": root_request_id,
            "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "reference_capacity": FLOW_REFERENCE_CAPACITY,
            "reference_policy": policy,
            "source_request_sha256": _json_sha256(old_request_snapshot),
            "source_manifest_sha256": _json_sha256(old_entry_snapshot),
        }
        replacement = dict(old_request)
        replacement.update({
            "request_id": replacement_id,
            "fingerprint": fingerprint,
                "reference_asset_ids": [],
                "depends_on": [],
                "root_request_id": root_request_id,
                "supersedes_request_id": request_id,
            "correction_epoch": epoch,
            "correction_nonce": nonce,
            "correction_reason": QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON,
            "corrected_semantic_intent": corrected_intent,
            "pre_dispatch_supersession_provenance": provenance,
        })
        if _qc_corrective_pre_dispatch_genesis_projection(replacement) is None:
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_INVALID")
        position = requests.index(old_request)
        requests[position] = replacement
        media_plan_changed = _migrate_request_references(media_plan, request_id, replacement_id)
        try:
            validate_generation_requests(requests_data, media_plan, continuity)
        except PlanningError as error:
            raise FlowError("QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_INVALID", error.failure_class) from error
        event = {
            "at": _now(), "event": QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON,
            "operator_reason": reason.strip(), "old_request_id": request_id,
            "replacement_request_id": replacement_id, "attempts_sha256": _json_sha256([]),
            "provider_submissions": 0, "source_request_sha256": provenance["source_request_sha256"],
            "reference_policy": policy,
        }
        old_entry.setdefault("pre_dispatch_supersession_events", []).append(event)
        old_entry.update({
            "status": QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS,
            "pre_dispatch_supersession_request_id": replacement_id,
            "pre_dispatch_supersession_reason": QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_REASON,
            "updated_at": event["at"],
        })
        manifest["requests"].append({
            "request_id": replacement_id, "request_identity_sha256": fingerprint,
            "related_identity": replacement.get("shot_id"), "media_type": replacement["media_type"],
            "provider": replacement.get("provider", "google_flow"),
            "prompt_sha256": hashlib.sha256(replacement["prompt"].encode("utf-8")).hexdigest(),
            "reference_asset_hashes": [], "attempts": [], "provider_submissions": 0,
            "selected_asset": None, "attribution_claim": "NONE", "status": "PENDING",
            "created_at": event["at"], "root_request_id": replacement["root_request_id"],
            "supersedes_request_id": request_id, "correction_epoch": epoch,
            "correction_nonce": nonce, "correction_reason": replacement["correction_reason"],
            "corrected_semantic_intent": replacement.get("corrected_semantic_intent"),
            "pre_dispatch_supersession_provenance": provenance,
        })
        transaction_id = "qc-corrective-pre-dispatch-" + _json_sha256({
            "project_id": project_id, "old_request_id": request_id,
            "replacement_request_id": replacement_id,
        })[:24]
        targets = {
            "generation_requests": _target("output/generation_requests.json", requests_data),
            "generation_manifest": _target("output/generation_manifest.json", manifest),
        }
        if media_plan_changed:
            targets["media_plan"] = _target("output/media_plan.json", media_plan)
        transaction = {
            "schema_version": QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_TRANSACTION_SCHEMA,
            "state": "PREPARED", "transaction_id": transaction_id, "project_id": project_id,
            "old_request_id": request_id, "replacement_request_id": replacement_id,
            "superseded_request": old_request_snapshot,
            "superseded_manifest_entry": old_entry_snapshot,
            "targets": targets,
        }
        _publish_replacement_transaction(paths, transaction, fault_injector=_fault_injector)
        return {"old_request_id": request_id, "replacement_request_id": replacement_id,
                "provider_submissions": 0, "status": QC_CORRECTIVE_PRE_DISPATCH_SUPERSEDED_STATUS,
                "idempotent": False, "effective_references": [],
                "reference_capacity": FLOW_REFERENCE_CAPACITY}


def queue_regeneration(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str) -> dict | None:
    """Route QC-rejected owned assets to replacement; retain proven no-dispatch retries."""
    if not isinstance(reason, str) or not reason.strip(): raise FlowError("REGENERATION_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") in {"GENERATING", "AMBIGUOUS"}: raise FlowError("REGENERATION_NOT_ALLOWED")
        # A generated replacement already consumed this corrective lineage's
        # single fresh epoch.  Reject a further UI regeneration *before*
        # recording any creative-rejection state: otherwise the UI would
        # mutate the parent and then fail when the canonical replacement
        # transaction correctly refuses an unbounded chain.
        is_confirmed_creative_regeneration = (
            entry.get("status") == "QC_PENDING"
            and _confirmed_selected_attempt(entry)
        ) or (
            entry.get("status") == "FAILED_RETRYABLE"
            and entry.get("failure_class") in {"OPERATOR_REGENERATION", "CREATIVE_REJECTED"}
            and _confirmed_selected_attempt(entry)
        )
        if entry.get("replacement_of") and is_confirmed_creative_regeneration:
            epoch = entry.get("creative_correction_epoch")
            if epoch is None:
                epoch = 1 if entry.get("replacement_reason") == QC_REJECTED_ASSET_REPLACEMENT_REASON else 0
            if not isinstance(epoch, int) or epoch >= MAX_CREATIVE_CORRECTION_EPOCHS:
                raise FlowError("CORRECTION_CHAIN_EXHAUSTED")
        if entry.get("status") == QC_REJECTED_ASSET_REPLACED_STATUS or _owned_mandatory_qc_rejection(entry):
            # Release before the replacement operation takes its own project lock.
            pass
        elif (
            entry.get("status") == "QC_PENDING"
            and _confirmed_selected_attempt(entry)
        ) or (
            entry.get("status") == "FAILED_RETRYABLE"
            and entry.get("failure_class") == "OPERATOR_REGENERATION"
            and _confirmed_selected_attempt(entry)
            and any(isinstance(action, dict) and action.get("action") == "REGENERATE"
                    for action in entry.get("operator_actions", []))
        ):
            # The UI's Regenerate control is an explicit creative rejection.
            # Preserve the provider-bound original, then create one fresh
            # replacement epoch below; it must never reopen the old attempt.
            selected = entry["selected_asset"]
            entry.setdefault("creative_rejections", []).append({
                "rejected_at": _now(), "asset_path": selected.get("path"),
                "asset_sha256": selected.get("sha256"), "reason": reason.strip(),
                "provenance": "OPERATOR_REGENERATE_ACTION",
            })
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": "CREATIVE_REJECTED", "updated_at": _now()})
            atomic_write_json(path, manifest)
        else:
            raw_attempt, _ = _successful_raw_image(paths, entry)
            raw_video_attempt, _ = _successful_raw_video(paths, entry)
            retry_local = ((raw_attempt is not None and entry.get("failure_class") in LOCAL_IMAGE_FAILURES)
                           or (raw_video_attempt is not None and entry.get("failure_class") in LOCAL_VIDEO_FAILURES))
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
        _assert_media_not_tombstoned(paths, project_id, metadata["sha256"])
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
        _assert_media_not_tombstoned(paths, project_id, metadata["sha256"])
        number=len(entry["attempts"])+1; suffix=source.suffix.lower() or (".png" if entry["media_type"] == "IMAGE" else ".mp4")
        rel=f"assets/{entry['media_type'].lower()}/{request_id}/exact_flow_recovery_{number:03d}{suffix}"
        target=paths.artifact_path(rel); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
        at=_now(); attempt={"attempt":number,"status":"SUCCEEDED","dispatch_origin":"human_exact_flow_recovery",
            "attribution_evidence":evidence.strip(),"attribution_state":"CONFIRMED","attribution_method":"operator_exact_provider_identity",
            "attribution_method_version":"operator-exact-flow-recovery/1.0.0","attributed_provider_identity":dict(provider_identity),
            "attribution_confirmation_timestamp":at,"provider_settings":settings or {},"asset_path":rel,"asset_sha256":metadata["sha256"],
            "downloaded_raw_path":rel,"raw_sha256":metadata["sha256"],"metadata":metadata,"completed_at":at}
        if production and entry["media_type"] == "IMAGE": attempt["production_image_postprocess_required"] = True
        if production and entry["media_type"] == "VIDEO": attempt["production_video_postprocess_required"] = True
        entry["attempts"].append(attempt)
        if production and entry["media_type"] == "IMAGE":
            try: selected = _process_raw_image(paths, entry, attempt)
            except FlowImagePostprocessError as error:
                atomic_write_json(path, manifest); raise FlowError(error.failure_class, str(error)) from error
            selected["provenance"] = "EXACT_FLOW_RECOVERY"
        elif production and entry["media_type"] == "VIDEO":
            try: selected = _process_raw_video(paths, entry, attempt)
            except FlowVideoPostprocessError as error:
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
        _assert_media_not_tombstoned(paths, project_id, metadata["sha256"])
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
        SEMANTIC_RESET_PENDING_STATUS,
    }:
        return False
    if entry.get("status") in {"SUCCEEDED", "QC_PENDING"}:
        return False
    attempts = entry.get("attempts")
    latest = attempts[-1] if isinstance(attempts, list) and attempts else None
    terminal_log = latest.get("terminal_evidence") if isinstance(latest, dict) else None
    if (isinstance(terminal_log, list) and terminal_log
            and isinstance(terminal_log[-1], dict)
            and terminal_log[-1].get("authoritative") is True):
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


def _fail_closed_unproven_not_dispatched_entries(manifest: dict) -> int:
    """Correct a legacy misclassification without making its attempt runnable.

    Earlier execution paths could label a post-boundary adapter failure as
    ``NOT_DISPATCHED`` based solely on adapter-local evidence.  Preserve the
    original record, append a classification event, and restore the serial
    ambiguity barrier before any lineage validator or execution selector
    consumes it.
    """
    corrected = 0
    for entry in manifest.get("requests", []):
        attempts = entry.get("attempts") if isinstance(entry, dict) else None
        attempt = attempts[-1] if isinstance(attempts, list) and attempts else None
        if (entry.get("status") != "NOT_DISPATCHED" or not isinstance(attempt, dict)
                or canonical_no_dispatch_proof(attempt)):
            continue
        if (attempt.get("provider_execution_state") in {None, "NOT_STARTED"}
                and attempt.get("provider_boundary_entered_at") is None):
            continue
        event = {
            "at": _now(), "state": "FAIL_CLOSED_UNPROVEN_NOT_DISPATCHED",
            "prior_status": attempt.get("status"),
            "reason": "provider boundary entered without canonical no-dispatch proof",
        }
        attempt.setdefault("reconciliation_events", []).append(event)
        attempt["status"] = "AMBIGUOUS"
        entry.setdefault("reconciliation_events", []).append({
            "at": event["at"], "attempt": attempt.get("attempt"), "state": event["state"],
        })
        entry.update({"status": "AMBIGUOUS", "updated_at": event["at"]})
        corrected += 1
    return corrected


def _first_unresolved(paths, project_id: str, requests: list[dict], entries: dict[str, dict]) -> tuple[dict, dict] | None:
    malformed = _first_invalid_request_replacement(paths, project_id, entries, requests)
    if malformed is not None:
        return malformed
    for request in requests:
        entry = entries.get(request.get("request_id"))
        # A verified corrective parent is immutable historical QC evidence;
        # only its fresh child is current queue work.  Do not send the parent
        # through provider reconciliation merely because it has prior attempts.
        if (isinstance(entry, dict)
                and entry.get("status") == QC_CORRECTIVE_REPLANNED_STATUS
                and _qc_corrective_replan_valid(paths, project_id, entry, requests, entries)):
            continue
        if (isinstance(entry, dict)
                and entry.get("status") == SEMANTIC_RESET_PENDING_STATUS
                and _semantic_reset_parent_valid(paths, project_id, entry, requests, entries)):
            continue
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
        binding = ProviderPollEvidenceTimeline.verify_authoritative_binding(
            settings["provider_poll_evidence"]
        )
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
    raw_label = f"attempt_{number:03d}_raw" if production and request["media_type"] in {"IMAGE", "VIDEO"} else f"attempt_{number:03d}"
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
    elif production and request["media_type"] == "VIDEO":
        attempt["production_video_postprocess_required"] = True
        try:
            selected_asset = _process_raw_video(paths, entry, attempt)
        except FlowVideoPostprocessError:
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
    terminal_log = attempt.get("terminal_evidence")
    if (isinstance(terminal_log, list) and terminal_log
            and isinstance(terminal_log[-1], dict)
            and terminal_log[-1].get("authoritative") is True):
        return True, None, 0

    # The coordinator persists NOT_STARTED before entering the adapter and
    # synchronously replaces it immediately before Generate.  If that marker
    # remains intact and no contradictory provider identity exists, recovery
    # is local: no Flow inspection or asset attachment is needed.
    if _materialize_persisted_pre_dispatch_proof(
            attempt, proof="PERSISTED_PROVIDER_BOUNDARY_NOT_ENTERED"):
        event = {
            "at": _now(), "state": "PROVEN_PRE_DISPATCH_FAILURE",
            "evidence": {
                "input_dispatched": False,
                "reason": "PERSISTED_PROVIDER_BOUNDARY_NOT_ENTERED",
                "canonical_no_dispatch_proof": True,
            },
        }
        attempt.setdefault("reconciliation_events", []).append(event)
        attempt.update({
            "status": "NOT_DISPATCHED",
            "failure_class": "FLOW_RECONCILED_PRE_DISPATCH_FAILURE",
            "completed_at": event["at"],
        })
        entry.update({
            "status": "NOT_DISPATCHED",
            "failure_class": "FLOW_RECONCILED_PRE_DISPATCH_FAILURE",
            "updated_at": event["at"],
        })
        return True, None, 1

    # This is the persisted positive proof that the provider boundary was
    # never crossed.  It is already the sole authorization consumed by the
    # RecoveryExecutionGate below, so reconciliation must release it to that
    # gate rather than turn an explicitly safe retry into a no-progress loop.
    if _provider_generation_retry_authorized(entry):
        return True, None, 0

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
    reconciliation_attempt = _hydrate_attempt_external_poll_evidence(
        paths, request["request_id"], attempt
    )
    result = executor.reconcile_attempt(request_context, reconciliation_attempt, temporary)
    if not isinstance(result, dict):
        return False, request["request_id"], 0
    state = result.get("state")
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    if isinstance(evidence.get("provider_poll_evidence_ref"), dict):
        prior_reference = _verified_embedded_poll_evidence_reference(
            paths, request["request_id"], attempt
        )
        merged_settings = copy.deepcopy(attempt.get("provider_settings")) \
            if isinstance(attempt.get("provider_settings"), dict) else {}
        merged_settings.update(evidence)
        attempt["provider_settings"] = _persisted_provider_settings(merged_settings)
        attempt["provider_poll_evidence_ref"] = copy.deepcopy(
            evidence["provider_poll_evidence_ref"]
        )
        _append_poll_evidence_history(attempt, prior_reference)
    event = {
        "at": _now(), "state": state, "prior_status": attempt.get("status"),
        "evidence": _persisted_provider_settings(evidence),
    }
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
    if state == "TERMINAL_NO_OUTPUT_PROVEN" and evidence.get("terminal_no_output_proven") is True:
        try:
            from .live import ProviderPollEvidenceTimeline
            snapshot = evidence.get("provider_poll_evidence")
            verified_terminal = ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
            binding = ProviderPollEvidenceTimeline.verify_authoritative_binding(snapshot)
            durable_identity = binding.get("durable_identity_used")
            expected_identity = attempt.get("durable_dispatch_identity")
            if not expected_identity and attempt.get("provider_lineage_card_id"):
                expected_identity = f"card:{attempt['provider_lineage_card_id']}"
            if (binding.get("resulting_dispatch_state") != "CONFIRMED"
                    or binding.get("resulting_attribution_state") != "TERMINAL_NO_OUTPUT_PROVEN"
                    or not isinstance(durable_identity, str) or not durable_identity
                    or (expected_identity and durable_identity != expected_identity)
                    or verified_terminal.get("terminal_state") != "TERMINAL_NO_OUTPUT_PROVEN"):
                raise FlowError("FLOW_TERMINAL_NO_OUTPUT_EVIDENCE_INVALID")
        except Exception:
            event["state"] = "TERMINAL_NO_OUTPUT_EVIDENCE_REJECTED"
            return False, request["request_id"], 1
        merged_settings = copy.deepcopy(attempt.get("provider_settings")) \
            if isinstance(attempt.get("provider_settings"), dict) else {}
        merged_settings.update(evidence)
        attempt.update({
            "status": "AMBIGUOUS",
            "failure_class": "FLOW_TERMINAL_NO_OUTPUT_PROVEN",
            "dispatch_confirmed": True,
            "dispatch_confirmation_state": "CONFIRMED",
            "dispatch_confirmation_signal": "exact_lineage_terminal_failure",
            "durable_dispatch_identity": durable_identity,
            "attribution_state": "TERMINAL_NO_OUTPUT_PROVEN",
            "terminal_no_output_proven": True,
            "terminal_no_output_evidence_head_sha256": snapshot.get("evidence_head_sha256"),
            "provider_settings": _persisted_provider_settings(merged_settings),
            "completed_at": event["at"],
        })
        entry.update({
            "status": "AMBIGUOUS",
            "failure_class": "FLOW_TERMINAL_NO_OUTPUT_PROVEN",
            "updated_at": event["at"],
        })
        # This proves the existing provider execution is terminal, but does not
        # itself authorize a replacement dispatch.
        return False, request["request_id"], 1
    if state == "CONFIRMED_DISPATCH":
        attempt["dispatch_confirmed"] = True
        entry.update({"status": "AMBIGUOUS", "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN", "updated_at": event["at"]})
    return False, request["request_id"], 1

@dataclass
class FlowExecutor:
    """A live adapter supplies generate(); it must acquire to the given temp file."""
    capabilities: Any
    generate: Any

    def run(self, request, refs, temporary: Path, *, before_provider_boundary=None):
        self.capabilities.require(request["media_type"], bool(refs))
        setter = getattr(self.generate, "set_before_provider_boundary", None)
        if not callable(setter):
            if before_provider_boundary is not None:
                before_provider_boundary()
            return self.generate(request, refs, temporary)
        setter(before_provider_boundary)
        try:
            return self.generate(request, refs, temporary)
        finally:
            setter(None)

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
        reconciliation_attempt = _hydrate_attempt_external_poll_evidence(
            paths, request_id, attempt
        )
        result = executor.reconcile_attempt(request_context, reconciliation_attempt, temporary)
        if not isinstance(result, dict) or result.get("state") != "REMAINS_AMBIGUOUS":
            raise FlowError("GENERATION_RECONCILIATION_ORDER_BLOCKED")
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        if isinstance(evidence.get("provider_poll_evidence_ref"), dict):
            prior_reference = _verified_embedded_poll_evidence_reference(
                paths, request_id, attempt
            )
            merged_settings = copy.deepcopy(attempt.get("provider_settings")) \
                if isinstance(attempt.get("provider_settings"), dict) else {}
            merged_settings.update(evidence)
            attempt["provider_settings"] = _persisted_provider_settings(merged_settings)
            attempt["provider_poll_evidence_ref"] = copy.deepcopy(
                evidence["provider_poll_evidence_ref"]
            )
            _append_poll_evidence_history(attempt, prior_reference)
        event = {"at": _now(), "state": "REMAINS_AMBIGUOUS", "prior_status": attempt.get("status"),
                 "evidence": _persisted_provider_settings(evidence)}
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
                       max_requests: int | None = None, flow_connection_provenance: dict | None = None,
                       recovery_timing: RecoveryRetryTiming | None = None) -> dict:
    """Run the bounded vertical slice while preserving every provider attempt."""
    if not execute: raise FlowError("EXECUTION_CONFIRMATION_REQUIRED", "pass explicit execute-generation permission")
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    review = read_json(paths.artifact_path("output/review_state.json"))
    if review.get("plan_approval", {}).get("status") != "APPROVED": raise FlowError("PLAN_APPROVAL_REQUIRED")
    storage=config.settings.get("storage",{})
    if not isinstance(storage,dict): raise FlowError("STORAGE_SETTINGS_INVALID")
    ensure_free_space(paths.runtime.temp,minimum_free_bytes=int(storage.get("minimum_free_bytes",64*1024*1024)))
    timing = recovery_timing or RecoveryRetryTiming()
    session_identity = _flow_session_identity(paths, config, executor)
    with ProjectLock(paths.runtime, project_id), _transaction_read_scope():
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
        session_blocker = _session_preparation_blocker(manifest)
        if session_blocker is not None:
            return {"selected": len(selected), "new_submissions": 0, "paused": False,
                    "blocked": True, "blocked_request_id": session_blocker["request_id"],
                    "attention": "FLOW_SESSION_PREPARATION_FAILED", "reconciliations": 0,
                    "manifest": "output/generation_manifest.json"}
        if _fail_closed_unproven_not_dispatched_entries(manifest):
            atomic_write_json(path, manifest)
            entries = {entry["request_id"]: entry for entry in manifest["requests"]}
        malformed = _first_invalid_request_replacement(paths, project_id, entries, requests)
        if malformed is not None:
            return {"selected": len(selected), "new_submissions": 0, "paused": False,
                    "blocked": True, "blocked_request_id": malformed[0]["request_id"],
                    "attention": "FLOW_GENERATION_RECONCILIATION_REQUIRED", "reconciliations": 0,
                    "manifest": "output/generation_manifest.json"}
        # Preserved raw production media is recoverable without a provider
        # activation.  Do that local-only work before asking the reconciliation
        # adapter about an unresolved provider attempt; its failure status is
        # never authority to cross the Generate boundary again.
        initial_blocker = _first_unresolved(paths, project_id, requests, entries)
        if (initial_blocker is not None
                and (_repair_local_image(paths, initial_blocker[1], initial_blocker[0])
                     or _repair_local_video(paths, initial_blocker[1], initial_blocker[0]))):
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
                # Preserved raw production media can be repaired locally
                # without invoking Generate.  Give that separate recovery path
                # precedence over the provider-resubmission barrier only for
                # the blocked request itself.
                if (blocker[0].get("request_id") == request.get("request_id")
                        and (_repair_local_image(paths, blocker[1], request)
                             or _repair_local_video(paths, blocker[1], request))):
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
            if _repair_local_image(paths, entry, request) or _repair_local_video(paths, entry, request):
                atomic_write_json(path, manifest); entries[request["request_id"]] = entry
                continue
            if entry.get("status") == "AMBIGUOUS":
                blocked_request_id = request["request_id"]
                break
            if entry.get("status") in (FINAL - {"SUCCEEDED"}): continue
            if not _runnable(request, entries, paths): continue
            entry["reference_asset_hashes"] = [entries[dep]["selected_asset"]["sha256"] for dep in request.get("depends_on", [])]
            # This check is deliberately after dependency resolution and
            # immediately before attempt creation: it validates the exact
            # prompt/reference projection that can reach the provider, not
            # merely the canonical planning contract.
            refs = [str(paths.artifact_path(entries[d]["selected_asset"]["path"])) for d in request.get("depends_on", [])]
            geometry_validation = _validate_effective_scene_geometry_provider_input(request, refs)
            if geometry_validation is not None:
                entry.setdefault("pre_dispatch_geometry_validations", []).append(geometry_validation)
                atomic_write_json(path, manifest)
            initial_facts = _recovery_input_from_entry(entry)
            # A first request has no manifest on disk yet. Persist the exact
            # canonical state that the final gate must re-read.
            atomic_write_json(path, manifest)
            execution: dict[str, Any] = {}
            rate_limit_ready = False
            initial_decision = evaluate_recovery(initial_facts)
            if initial_decision.action is RecoveryAction.AUTO_RETRY:
                if not timing.wait(initial_facts.transient_redispatch_count):
                    blocked_request_id = request["request_id"]
                    break
            elif (initial_decision.action is RecoveryAction.WAIT_AND_RETRY
                  and initial_facts.failure_family is FailureFamily.PROVIDER_RATE_LIMIT):
                if not timing.wait(initial_facts.transient_redispatch_count):
                    blocked_request_id = request["request_id"]
                    break
                manifest = read_json(path)
                entries = {item["request_id"]: item for item in manifest["requests"]}
                entry = entries.get(request["request_id"])
                if not isinstance(entry, dict):
                    blocked_request_id = request["request_id"]
                    break
                rate_limit_ready = True
                initial_facts = _recovery_input_from_entry(entry, rate_limit_backoff_ready=True)

            # The capability object is immutable local evidence.  It must be
            # accepted before a recovery attempt can claim that the provider
            # boundary was entered or consume provider-submission accounting.
            executor.capabilities.require(request["media_type"], bool(refs))

            def fresh_recovery_facts() -> RecoveryInput:
                """Re-read durable evidence after owning ProjectLock, never reuse a decision."""
                nonlocal manifest, entries, entry
                manifest = read_json(path)
                entries = {item["request_id"]: item for item in manifest["requests"]}
                entry = entries.get(request["request_id"])
                if not isinstance(entry, dict) or not _runnable(request, entries, paths):
                    return RecoveryInput(FailureFamily.DISPATCH_AMBIGUOUS, AttemptOutcome.FAILED,
                                         DispatchCertainty.DISPATCH_UNCERTAIN)
                return _recovery_input_from_entry(
                    entry, rate_limit_backoff_ready=rate_limit_ready,
                )

            def append_authorized_attempt(decision) -> dict:
                """Append and persist one attempt before a provider boundary exists."""
                nonlocal entry
                if not isinstance(entry, dict):
                    raise FlowError("FLOW_RECOVERY_EVIDENCE_CHANGED")
                attempt_number = len(entry["attempts"]) + 1
                attempt = {
                    "attempt": attempt_number, "status": "SUBMITTED", "started_at": _now(),
                    "provider_mode": request["media_type"], "dispatch_confirmed": False,
                    "provider_execution_state": "NOT_STARTED", "recovery_action": decision.action.value,
                    "recovery_policy_version": decision.policy_version,
                }
                entry["attempts"].append(attempt)
                entry.update({"status": "GENERATING", "updated_at": _now()})
                execution["attempt"] = attempt
                execution["attempt_number"] = attempt_number
                if flow_connection_provenance is not None:
                    if (not isinstance(flow_connection_provenance, dict)
                            or not isinstance(flow_connection_provenance.get("flow_connection_id"), str)):
                        raise FlowError("FLOW_CONNECTION_PROVENANCE_INVALID")
                    attempt["flow_connection"] = dict(flow_connection_provenance)
                    entry["flow_connection"] = dict(flow_connection_provenance)
                atomic_write_json(path, manifest)
                return attempt

            def provider_boundary(attempt: dict) -> None:
                """The one and only recovery-authorized Flow generation crossing."""
                attempt_number = execution["attempt_number"]
                temp = paths.artifact_path(
                    f"assets/attempts/{request['request_id']}/attempt_{attempt_number:03d}/provider_result."
                    f"{'png' if request['media_type'] == 'IMAGE' else 'mp4'}"
                )
                temp.parent.mkdir(parents=True, exist_ok=True)
                request_context = dict(request)
                request_context["_flow_provider_identity_history"] = _provider_identity_history(
                    manifest, exclude_request_id=request["request_id"], exclude_attempt=attempt_number,
                )
                request_context["_flow_reference_paths"] = list(refs)
                def mark_provider_boundary() -> None:
                    # The live adapter calls this only after reference
                    # attachment, Generate readiness, and the final baseline
                    # are all complete, immediately before its one activation.
                    if attempt.get("provider_execution_state") != "NOT_STARTED":
                        raise FlowError("FLOW_PROVIDER_BOUNDARY_REENTERED")
                    attempt["provider_execution_state"] = "PROVIDER_BOUNDARY_ENTERED"
                    attempt["provider_boundary_entered_at"] = _now()
                    attempt["provider_submission_recorded"] = True
                    entry["provider_submissions"] = int(entry.get("provider_submissions", 0)) + 1
                    atomic_write_json(path, manifest)
                execution["result"] = executor.run(
                    request_context, refs, temp,
                    before_provider_boundary=mark_provider_boundary,
                )
                execution["temporary"] = temp

            try:
                outcome = RecoveryExecutionGate(
                    FlowSessionSingleFlight(paths.runtime, session_identity),
                ).execute(
                    initial_facts, load_fresh=fresh_recovery_facts,
                    append_attempt=append_authorized_attempt, dispatch=provider_boundary,
                )
                if not outcome.dispatched:
                    blocked_request_id = request["request_id"]
                    break
                attempt = execution["attempt"]
                temp = execution["temporary"]
                result = execution["result"]
                attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", True))
                _record_attempt_provider_state(attempt, executor.generate)
                _confirm_executor_attribution(attempt, executor.generate)
                source = Path(result or temp)
                if _finalize_attributed_result(paths, manifest, entry, request, attempt, temp, source):
                    submissions += 1
            except (FlowError, FlowSessionError) as error:
                attempt = execution.get("attempt")
                if not isinstance(attempt, dict):
                    raise
                attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", attempt.get("dispatch_confirmed", False)))
                _record_attempt_provider_state(attempt, executor.generate)
                _append_terminal_observations(request, attempt, executor.generate)
                _materialize_persisted_pre_dispatch_proof(
                    attempt, proof="PERSISTED_PROVIDER_BOUNDARY_NOT_ENTERED",
                )
                safe_pre_dispatch_candidate = error.failure_class in {
                    "FLOW_NOT_DISPATCHED", "FLOW_PRE_DISPATCH_ACTIVATION_FAILED",
                    "OUTPUT_ATTRIBUTION_NOT_QUIESCENT", "FLOW_REFERENCE_UPLOAD_FAILED",
                }
                if canonical_no_dispatch_proof(attempt):
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
                if (request.get("media_type") == "VIDEO"
                        and error.failure_class in SESSION_PREPARATION_FAILURES
                        and canonical_no_dispatch_proof(attempt)):
                    # This is provider/session preparation, not an individual
                    # creative failure. Preserve exact request evidence, then
                    # stop sibling videos until an operator reviews the Flow
                    # session; no automatic Generate retry is authorized.
                    manifest["session_preparation_blocker"] = {
                        "scope": "FLOW_SESSION", "failure_class": error.failure_class,
                        "request_id": request["request_id"], "media_type": "VIDEO",
                        "at": _now(), "diagnostic": str(error),
                        "canonical_no_dispatch_proof": True,
                    }
            except AssetValidationError as error:
                attempt = execution.get("attempt")
                if not isinstance(attempt, dict):
                    raise
                attempt.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "completed_at":_now()}); entry.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "updated_at":_now()})
            atomic_write_json(path, manifest); entries[request["request_id"]] = entry
            if _session_preparation_blocker(manifest) is not None:
                blocked_request_id = request["request_id"]
                break
            if _unresolved_flow_entry(entry):
                blocked_request_id = request["request_id"]
                break
    return {"selected":len(selected), "new_submissions":submissions, "paused":paused,
            "blocked":blocked_request_id is not None, "blocked_request_id":blocked_request_id,
            "attention":("FLOW_SESSION_PREPARATION_FAILED" if _session_preparation_blocker(manifest) is not None
                         else "FLOW_GENERATION_RECONCILIATION_REQUIRED") if blocked_request_id else None,
            "reconciliations":reconciliation_count, "manifest":"output/generation_manifest.json"}
