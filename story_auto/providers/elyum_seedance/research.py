"""Durable research ledger for Goal 54 Elyum preview experiments.

This service deliberately stops at a provider preview. `keep` and `kill` are
separate explicit operations because keep spends Credits and kill consumes a
limited allowance.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from .client import ElyumSeedanceClient, ElyumSeedanceError


LEDGER_VERSION = "story-auto-goal54-elyum-experiment/1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": LEDGER_VERSION, "experiments": {}}
    try:
        value = read_json(path)
    except Exception as error:
        raise ElyumSeedanceError("EXPERIMENT_LEDGER_INVALID") from error
    if value.get("schema_version") != LEDGER_VERSION or not isinstance(value.get("experiments"), dict):
        raise ElyumSeedanceError("EXPERIMENT_LEDGER_INVALID")
    return value


def _entry(ledger: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    value = ledger["experiments"].get(recipe_id)
    if value is None:
        value = {"recipe_id": recipe_id, "status": "NEW", "created_at": _now(), "updated_at": _now()}
        ledger["experiments"][recipe_id] = value
    if not isinstance(value, dict):
        raise ElyumSeedanceError("EXPERIMENT_LEDGER_INVALID")
    return value


def prepare_reference_upload(ledger_path: Path | str, *, recipe_id: str, reference_path: Path | str,
                             client: ElyumSeedanceClient) -> dict[str, Any]:
    ledger_path = Path(ledger_path)
    source = Path(reference_path)
    if not source.is_file():
        raise ElyumSeedanceError("REFERENCE_FILE_MISSING")
    sha = _sha256(source)
    ledger = _load(ledger_path)
    entry = _entry(ledger, recipe_id)
    existing = entry.get("reference")
    if isinstance(existing, dict) and existing.get("sha256") == sha and isinstance(existing.get("provider_url"), str):
        return {"status": "REUSED", "sha256": sha, "provider_url": existing["provider_url"]}
    provider_url = client.upload_file(source)
    entry["reference"] = {"sha256": sha, "filename": source.name, "provider_url": provider_url,
                          "uploaded_at": _now()}
    entry["updated_at"] = _now()
    atomic_write_json(ledger_path, ledger)
    return {"status": "UPLOADED", "sha256": sha, "provider_url": provider_url}


def run_experiment_preview(ledger_path: Path | str, *, recipe_id: str, prompt: str,
                           reference_url: str, client: ElyumSeedanceClient,
                           model: str, duration: int = 4, aspect_ratio: str = "16:9",
                           resolution: str = "480p", max_credits: int | None = None,
                           wait_seconds: int = 50) -> dict[str, Any]:
    """Create or resume one preview without ever keeping/killing it automatically."""
    ledger_path = Path(ledger_path)
    ledger = _load(ledger_path)
    entry = _entry(ledger, recipe_id)
    identity = {
        "recipe_id": recipe_id,
        "prompt": prompt,
        "reference_url": reference_url,
        "model": model,
        "duration": int(duration),
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "mode": "i2v",
    }
    identity_sha = _fingerprint(identity)
    observed = entry.get("identity_sha256")
    if observed not in {None, identity_sha}:
        raise ElyumSeedanceError("EXPERIMENT_IDENTITY_MISMATCH")
    client_ref = entry.get("client_ref")
    if not isinstance(client_ref, str):
        client_ref = "story-auto-g54-" + identity_sha[:48]
        entry.update({"identity_sha256": identity_sha, "client_ref": client_ref,
                      "provider": client.provider, "settings": identity,
                      "status": "PRE_DISPATCH", "updated_at": _now()})
        # Critical ordering: stable clientRef exists durably before make_video.
        atomic_write_json(ledger_path, ledger)

    if entry.get("status") in {"KEPT", "KILLED"}:
        return {"status": entry["status"], "recipe_id": recipe_id, "client_ref": client_ref,
                "job_id": entry.get("job_id"), "gen_id": entry.get("gen_id")}

    if not isinstance(entry.get("job_id"), str):
        balance = client.account_balance()
        estimate = client.estimate_video(model=model, duration=int(duration), mode="i2v")
        entry["balance_before"] = balance
        entry["estimate_credits"] = estimate
        entry["estimated_at"] = _now()
        entry["updated_at"] = _now()
        atomic_write_json(ledger_path, ledger)
        if balance < estimate:
            entry.update({"status": "BLOCKED_BALANCE", "failure_class": "INSUFFICIENT_CREDIT_BALANCE", "updated_at": _now()})
            atomic_write_json(ledger_path, ledger)
            return {"status": "BLOCKED_BALANCE", "recipe_id": recipe_id, "balance": balance,
                    "estimate_credits": estimate, "client_ref": client_ref}
        if max_credits is not None and estimate > int(max_credits):
            entry.update({"status": "BLOCKED_COST", "failure_class": "ESTIMATE_EXCEEDS_BOUND", "updated_at": _now()})
            atomic_write_json(ledger_path, ledger)
            return {"status": "BLOCKED_COST", "recipe_id": recipe_id, "estimate_credits": estimate,
                    "max_credits": int(max_credits), "client_ref": client_ref}
        try:
            job_id, _create_result = client.make_video(
                client_ref=client_ref,
                model=model,
                prompt=prompt,
                duration=int(duration),
                mode="i2v",
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                image_url=reference_url,
                audio=False,
            )
        except ElyumSeedanceError as error:
            if error.dispatch_state == "RECONCILE_BY_CLIENT_REF":
                entry.update({"status": "REPLAY_SAME_CLIENT_REF", "failure_class": error.failure_class,
                              "updated_at": _now()})
                atomic_write_json(ledger_path, ledger)
                return {"status": "REPLAY_SAME_CLIENT_REF", "recipe_id": recipe_id,
                        "client_ref": client_ref, "failure_class": error.failure_class}
            raise
        entry.update({"job_id": job_id, "status": "SUBMITTED", "submitted_at": _now(),
                      "failure_class": None, "updated_at": _now()})
        atomic_write_json(ledger_path, ledger)
    else:
        job_id = entry["job_id"]

    try:
        observed_result = client.wait(job_id, timeout_seconds=wait_seconds, thumbnails=True)
    except ElyumSeedanceError as error:
        entry.update({"status": "WAIT_UNAVAILABLE", "failure_class": error.failure_class, "updated_at": _now()})
        atomic_write_json(ledger_path, ledger)
        return {"status": "WAIT_UNAVAILABLE", "recipe_id": recipe_id, "job_id": job_id,
                "client_ref": client_ref, "failure_class": error.failure_class}

    gen_id = client.gen_id(observed_result)
    execution = client.execution_state(observed_result)
    previews = client.preview_urls(observed_result)
    entry.update({"last_observed_at": _now(), "provider_execution_state": execution,
                  "preview_urls": previews, "failure_class": None, "updated_at": _now()})
    if gen_id:
        entry.update({"gen_id": gen_id, "status": "PREVIEW_READY"})
    elif execution in {"failed", "error", "cancelled", "canceled"}:
        entry.update({"status": "FAILED_TERMINAL", "failure_class": f"PROVIDER_{execution.upper()}"})
    else:
        entry.update({"status": "GENERATING"})
    atomic_write_json(ledger_path, ledger)
    return {"status": entry["status"], "recipe_id": recipe_id, "job_id": job_id,
            "client_ref": client_ref, "gen_id": entry.get("gen_id"),
            "preview_urls": list(entry.get("preview_urls") or []),
            "estimate_credits": entry.get("estimate_credits"),
            "balance_before": entry.get("balance_before")}


def keep_experiment_preview(ledger_path: Path | str, *, recipe_id: str,
                            client: ElyumSeedanceClient, index: int = 0) -> dict[str, Any]:
    ledger_path = Path(ledger_path)
    ledger = _load(ledger_path)
    entry = _entry(ledger, recipe_id)
    gen_id = entry.get("gen_id")
    if entry.get("status") != "PREVIEW_READY" or not isinstance(gen_id, str):
        raise ElyumSeedanceError("PREVIEW_NOT_READY")
    result = client.keep(gen_id, index=index)
    entry.update({"status": "KEPT", "kept_at": _now(), "updated_at": _now(),
                  "download_urls": client.downloadable_urls(result)})
    atomic_write_json(ledger_path, ledger)
    return {"status": "KEPT", "recipe_id": recipe_id, "gen_id": gen_id,
            "download_urls": list(entry.get("download_urls") or [])}


def kill_experiment_preview(ledger_path: Path | str, *, recipe_id: str,
                            client: ElyumSeedanceClient, index: int = 0,
                            reason: str | None = None) -> dict[str, Any]:
    ledger_path = Path(ledger_path)
    ledger = _load(ledger_path)
    entry = _entry(ledger, recipe_id)
    gen_id = entry.get("gen_id")
    if entry.get("status") != "PREVIEW_READY" or not isinstance(gen_id, str):
        raise ElyumSeedanceError("PREVIEW_NOT_READY")
    client.kill(gen_id, index=index, reason=reason)
    entry.update({"status": "KILLED", "killed_at": _now(), "kill_reason": reason, "updated_at": _now()})
    atomic_write_json(ledger_path, ledger)
    return {"status": "KILLED", "recipe_id": recipe_id, "gen_id": gen_id, "reason": reason}
