"""Bounded Goal 54 Elyum experiment CLI.

`prepare` uploads/reuses the deterministic reference (provider documents upload
as free). `preview` requires an explicit dispatch flag and stops at PREVIEW_READY.
`keep` and `kill` each require their own explicit consequence flag. No action
prints credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_auto.core.artifacts import read_json
from story_auto.providers.elyum_seedance import (
    DEFAULT_FAST_I2V_MODEL,
    ElyumSeedanceClient,
    ElyumSeedanceError,
    keep_experiment_preview,
    kill_experiment_preview,
    prepare_reference_upload,
    run_experiment_preview,
)


R1_PROMPT = (
    "Preserve the exact same illustrated adult woman from the reference image: "
    "teal bob haircut, crimson round glasses, mustard jacket over a blue shirt, "
    "silver triangle earrings, and the small beauty mark below her right eye. "
    "Preserve the same living-room layout: window on camera-left, sofa and plant "
    "on camera-right. Medium eye-level framing. The camera performs one slow, "
    "smooth push-in only. The subject remains mostly still with subtle natural "
    "breathing and a very slight head turn toward the window near the end, then "
    "holds. No pan, no tilt, no orbit, no handheld shake, no cut, no scene change, "
    "no identity/wardrobe/color changes, and no extra limbs. Silent visual only."
)


def confirmation_failure(action: str, *, confirm_dispatch: bool, confirm_spend: bool,
                         confirm_kill: bool) -> str | None:
    if action == "preview" and not confirm_dispatch:
        return "CONFIRM_DISPATCH_REQUIRED"
    if action == "keep" and not confirm_spend:
        return "CONFIRM_SPEND_REQUIRED"
    if action == "kill" and not confirm_kill:
        return "CONFIRM_KILL_REQUIRED"
    return None


def _load_key(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ElyumSeedanceError("KEY_FILE_UNREADABLE") from error
    if not value:
        raise ElyumSeedanceError("KEY_EMPTY")
    return value


def _safe_show(path: Path, recipe_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "NOT_STARTED", "recipe_id": recipe_id}
    value = read_json(path)
    experiments = value.get("experiments") if isinstance(value, dict) else None
    entry = experiments.get(recipe_id) if isinstance(experiments, dict) else None
    if not isinstance(entry, dict):
        return {"status": "NOT_STARTED", "recipe_id": recipe_id}
    allowed = {
        key: entry[key] for key in (
            "recipe_id", "status", "identity_sha256", "client_ref", "provider",
            "reference", "settings", "balance_before", "estimate_credits",
            "job_id", "provider_execution_state", "gen_id", "preview_urls",
            "failure_class", "download_urls", "kill_reason", "created_at",
            "updated_at", "submitted_at", "last_observed_at", "kept_at", "killed_at",
        ) if key in entry
    }
    return allowed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded Elyum Goal 54 experiment runner.")
    parser.add_argument("action", choices=("show", "prepare", "preview", "keep", "kill"))
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--recipe-id", default="R1")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--model", default=DEFAULT_FAST_I2V_MODEL)
    parser.add_argument("--prompt", default=R1_PROMPT)
    parser.add_argument("--duration", type=int, default=4)
    parser.add_argument("--resolution", default="480p")
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--max-credits", type=int, default=44)
    parser.add_argument("--wait-seconds", type=int, default=50)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--confirm-dispatch", action="store_true")
    parser.add_argument("--confirm-spend", action="store_true")
    parser.add_argument("--confirm-kill", action="store_true")
    args = parser.parse_args(argv)

    if args.action == "show":
        print(json.dumps(_safe_show(args.ledger, args.recipe_id), ensure_ascii=True, sort_keys=True))
        return 0

    failure = confirmation_failure(
        args.action,
        confirm_dispatch=args.confirm_dispatch,
        confirm_spend=args.confirm_spend,
        confirm_kill=args.confirm_kill,
    )
    if failure:
        print(json.dumps({"status": "BLOCKED", "reason_code": failure}, sort_keys=True))
        return 2
    if args.key_file is None:
        print(json.dumps({"status": "BLOCKED", "reason_code": "KEY_FILE_REQUIRED"}, sort_keys=True))
        return 2

    try:
        key = _load_key(args.key_file)
        client = ElyumSeedanceClient(key=key)
        if args.action in {"prepare", "preview"}:
            if args.reference_file is None:
                raise ElyumSeedanceError("REFERENCE_FILE_REQUIRED")
            reference = prepare_reference_upload(
                args.ledger, recipe_id=args.recipe_id,
                reference_path=args.reference_file, client=client,
            )
            if args.action == "prepare":
                result = reference
            else:
                result = run_experiment_preview(
                    args.ledger,
                    recipe_id=args.recipe_id,
                    prompt=args.prompt,
                    reference_url=reference["provider_url"],
                    client=client,
                    model=args.model,
                    duration=args.duration,
                    aspect_ratio=args.aspect_ratio,
                    resolution=args.resolution,
                    max_credits=args.max_credits,
                    wait_seconds=args.wait_seconds,
                )
        elif args.action == "keep":
            result = keep_experiment_preview(args.ledger, recipe_id=args.recipe_id, client=client)
        else:
            result = kill_experiment_preview(
                args.ledger, recipe_id=args.recipe_id, client=client, reason=args.reason,
            )
    except ElyumSeedanceError as error:
        print(json.dumps({"status": "FAIL", "reason_code": error.failure_class}, sort_keys=True))
        return 1
    finally:
        if "key" in locals():
            key = ""

    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("status") not in {"BLOCKED", "BLOCKED_COST", "BLOCKED_BALANCE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
