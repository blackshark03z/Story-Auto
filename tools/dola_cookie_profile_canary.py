"""Exactly one authorized Dola canary using the newly qualified cookie alias.

Each action is explicit. Preparation does not contact Dola. Dispatch is
single-use for this isolated project, even if the provider returns no receipt.
Recovery requires a persisted receipt and never submits again.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import story_auto

if not Path(story_auto.__file__).resolve().is_relative_to(REPO_ROOT / "story_auto"):
    raise SystemExit("CANDIDATE_IMPORT_MISMATCH: no provider request")

from story_auto.core.artifacts import read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project
from story_auto.core.visual.opening_builder import configure_opening_builder
from story_auto.providers.dola_cookie.accounts import DolaAccountStore
from story_auto.providers.dola_cookie.opening import generate_dola_opening


RUNTIME_ROOT = Path(r"D:\Story Auto\evidence\dola-profile-canary-20260923")
PROJECT_ID = "prj_dola_profile_canary_20260923"
ACCOUNT_ID = "dola-profile-20260923"
SLOT_ID = "OPENING_O1"
PROMPT = ("A five-second cinematic wide shot of a peaceful river beside a "
          "small village at sunrise. Gentle water movement and warm natural "
          "light. No people, text, logos, or audio requirement.")
SLOTS = [
    {"duration_seconds": 5, "purpose": "Establish the river", "prompt": PROMPT},
    {"duration_seconds": 5, "purpose": "Follow the path", "prompt":
     "A quiet riverside footpath and wild flowers at sunrise. No people, text, or logos."},
    {"duration_seconds": 5, "purpose": "Reveal the bridge", "prompt":
     "An old wooden bridge over the same quiet river at sunrise. No people, text, or logos."},
]


def _manifest() -> dict:
    runtime = RuntimeLayout.from_root(RUNTIME_ROOT)
    paths, _ = load_project(runtime, PROJECT_ID)
    return read_json(paths.artifact_path("output/opening_manifest.json"))


def _status() -> None:
    manifest = _manifest()
    slot = next(item for item in manifest["slots"] if item["slot_id"] == SLOT_ID)
    generation = slot.get("api_generation") or {}
    print(json.dumps({
        "project_id": PROJECT_ID, "slot_id": SLOT_ID,
        "account_id": generation.get("account_id") or ACCOUNT_ID,
        "plan_sha256": manifest["plan_sha256"],
        "slot_status": slot["status"],
        "attempt_id": generation.get("attempt_id"),
        "generation_status": generation.get("status"),
        "dispatch_state": generation.get("dispatch_state"),
        "submit_attempts": generation.get("submit_attempts", 0),
        "provider_submissions": generation.get("provider_submissions", 0),
        "submission_http_status": generation.get("submission_http_status"),
        "submission_response_kind": generation.get("submission_response_kind"),
        "submission_receipt_state": generation.get("submission_receipt_state"),
        "provider_task_id_present": bool(generation.get("provider_task_id")),
        "asset_ready": bool(slot.get("source_asset")),
    }, sort_keys=True))


def _prepare() -> None:
    if RUNTIME_ROOT.exists() or RuntimeLayout.from_root(RUNTIME_ROOT).projects.joinpath(PROJECT_ID).exists():
        raise SystemExit("EVIDENCE_ROOT_EXISTS: inspect; never replace it")
    DolaAccountStore().get_cookie(ACCOUNT_ID)
    runtime = RuntimeLayout.from_root(RUNTIME_ROOT).ensure()
    create_project(runtime, ProjectConfig(PROJECT_ID, render_mode="hybrid_hook", settings={
        "render": {"width": 1280, "height": 720, "fps": 24, "pixel_format": "yuv420p"},
        "hybrid_visual": {"opening_provider_policy": "DOLA"},
    }))
    configure_opening_builder(
        RUNTIME_ROOT, PROJECT_ID,
        shared_context="A quiet riverside village at sunrise; no recognizable people, text, or logos.",
        slot_specs=SLOTS,
    )
    _status()


def _dispatch() -> None:
    manifest = _manifest()
    if len(manifest.get("slots", [])) != 3 or any(item.get("api_generation") for item in manifest["slots"]):
        raise SystemExit("ATTEMPT_EXISTS: no new provider request")
    slot = manifest["slots"][0]
    if slot.get("slot_id") != SLOT_ID or slot.get("prompt") != PROMPT:
        raise SystemExit("PLAN_MISMATCH: no provider request")
    generate_dola_opening(RUNTIME_ROOT, PROJECT_ID, SLOT_ID, account_id=ACCOUNT_ID,
                          max_poll_seconds=45, poll_interval=3,
                          allow_new_submission=True)
    _status()


def _recover() -> None:
    manifest = _manifest()
    slot = next(item for item in manifest["slots"] if item["slot_id"] == SLOT_ID)
    generation = slot.get("api_generation") or {}
    if (generation.get("provider") != "dola_cookie"
            or generation.get("account_id") != ACCOUNT_ID
            or not generation.get("provider_task_id")
            or generation.get("dispatch_state") != "CONFIRMED"):
        raise SystemExit("NO_CONFIRMED_RECEIPT: recovery cannot submit")
    generate_dola_opening(RUNTIME_ROOT, PROJECT_ID, SLOT_ID, account_id=ACCOUNT_ID,
                          max_poll_seconds=45, poll_interval=3,
                          allow_new_submission=False)
    _status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "status", "dispatch", "recover"))
    parser.add_argument("--ack-one-request", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        _prepare()
    elif args.action == "status":
        _status()
    elif args.action == "recover":
        _recover()
    else:
        if not args.ack_one_request:
            raise SystemExit("ACK_REQUIRED: --ack-one-request")
        _dispatch()


if __name__ == "__main__":
    main()
