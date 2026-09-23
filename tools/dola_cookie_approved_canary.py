"""One explicitly authorized Dola cookie canary; never retries a saved attempt.

Preparation is local-only. Dispatch is limited to the first missing slot of a
fixed isolated project and requires an explicit command-line acknowledgement.
The old ambiguous Dola project is never opened or modified here.

Canonical invocation from this checkout: python tools/dola_cookie_approved_canary.py status
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
from story_auto.providers.dola_cookie.opening import generate_dola_opening


RUNTIME_ROOT = Path(r"D:\Story Auto\evidence\dola-cookie-approved-canary-20260923")
PROJECT_ID = "prj_dola_cookie_canary_20260923"
ACCOUNT_ID = "dola-main"
SLOT_ID = "OPENING_O1"
CONTEXT = "A quiet riverside village at sunrise; no recognizable people, text, or logos."
SLOTS = [
    {"duration_seconds": 5, "purpose": "Establish the river", "prompt":
     "A five-second cinematic wide shot of a peaceful river beside a small village at sunrise. Gentle water movement and warm natural light. No people, text, logos, or audio requirement."},
    {"duration_seconds": 5, "purpose": "Follow the path", "prompt":
     "A five-second cinematic shot of a narrow riverside path and wild flowers in soft morning light. No people, text, logos, or audio requirement."},
    {"duration_seconds": 5, "purpose": "Reveal the bridge", "prompt":
     "A five-second cinematic shot of an old wooden bridge over the same quiet river at sunrise. No people, text, logos, or audio requirement."},
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
        "project_id": PROJECT_ID,
        "slot_id": SLOT_ID,
        "plan_sha256": manifest["plan_sha256"],
        "slot_status": slot["status"],
        "attempt_id": generation.get("attempt_id"),
        "generation_status": generation.get("status"),
        "dispatch_state": generation.get("dispatch_state"),
        "submit_attempts": generation.get("submit_attempts", 0),
        "provider_submissions": generation.get("provider_submissions", 0),
        "submission_http_status": generation.get("submission_http_status"),
        "provider_task_id_present": bool(generation.get("provider_task_id")),
        "asset_ready": bool(slot.get("source_asset")),
    }, sort_keys=True))


def _prepare() -> None:
    runtime = RuntimeLayout.from_root(RUNTIME_ROOT).ensure()
    project_dir = runtime.projects / PROJECT_ID
    if project_dir.exists():
        raise SystemExit("PROJECT_ALREADY_EXISTS: inspect status; never replace it")
    create_project(runtime, ProjectConfig(PROJECT_ID, render_mode="hybrid_hook", settings={
        "render": {"width": 1280, "height": 720, "fps": 24, "pixel_format": "yuv420p"},
        "hybrid_visual": {"opening_provider_policy": "DOLA"},
    }))
    configure_opening_builder(RUNTIME_ROOT, PROJECT_ID, shared_context=CONTEXT, slot_specs=SLOTS)
    _status()


def _dispatch() -> None:
    manifest = _manifest()
    if len(manifest.get("slots", [])) != 3 or any(
        item.get("api_generation") for item in manifest["slots"]
    ):
        raise SystemExit("ATTEMPT_EXISTS: no new provider request; inspect status")
    slot = manifest["slots"][0]
    if slot.get("slot_id") != SLOT_ID or slot.get("prompt") != SLOTS[0]["prompt"]:
        raise SystemExit("PLAN_MISMATCH: no provider request")
    generate_dola_opening(RUNTIME_ROOT, PROJECT_ID, SLOT_ID, account_id=ACCOUNT_ID,
                          max_poll_seconds=45, poll_interval=3)
    _status()


def _recover() -> None:
    manifest = _manifest()
    slot = next(item for item in manifest["slots"] if item["slot_id"] == SLOT_ID)
    generation = slot.get("api_generation") or {}
    if (generation.get("provider") != "dola_cookie"
            or generation.get("account_id") != ACCOUNT_ID
            or not generation.get("provider_task_id")
            or generation.get("dispatch_state") != "CONFIRMED"):
        raise SystemExit("NO_CONFIRMED_RECEIPT: recovery must not submit a new request")
    generate_dola_opening(RUNTIME_ROOT, PROJECT_ID, SLOT_ID, account_id=ACCOUNT_ID,
                          max_poll_seconds=45, poll_interval=3)
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
