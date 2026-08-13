"""Materialize the sanitized Goal 08 blind provider-quality review workspace."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from story_auto.core.artifacts import sha256_file
from story_auto.core.benchmark import build_benchmark_workspace, write_review_package
from story_auto.providers.flow.validation import validate_image, validate_video
from story_auto.providers.gemini_media import GeminiMediaClient


def capability_evidence() -> list[dict]:
    result = []
    for item in GeminiMediaClient().discover_models():
        result.append({"model": item.model, "display_name": item.display_name, "methods": list(item.methods),
                       "media_type": item.media_type, "reference_mode": item.reference_mode,
                       "live_account_listing": "AVAILABLE"})
    return result


def bind_flow_baseline(root: Path, manifest: dict) -> None:
    sources = {
        "IMAGE-A": Path("runtime/goal07_hybrid/projects/prj_goal07hybrid/assets/image/req_goal06_image/manual_recovery_002.png"),
        "VIDEO-A": Path("runtime/goal07_hybrid/projects/prj_goal07hybrid/assets/video/req_goal06_video/manual_recovery_008.mp4"),
    }
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for case, source in sources.items():
        candidate = next(item for item in manifest["requests"]
                         if item["case"] == case and item["actual_model"] == "google_flow_web" and item["attempt"] == 1)
        suffix = source.suffix.lower()
        destination = assets / f"flow_{case.lower()}_attempt_1{suffix}"
        shutil.copy2(source, destination)
        metadata = validate_image(destination) if candidate["media_type"] == "IMAGE" else validate_video(destination)
        candidate.update({
            "status": "SUCCEEDED", "failure_class": None, "local_asset": destination.relative_to(root).as_posix(),
            "asset_sha256": sha256_file(destination), "technical_validation": {"status": "PASS", **metadata},
            "visible_watermark": "YES", "human_review": "PENDING",
            "attempt_history": [{"attempt": 1, "status": "SUCCEEDED", "source": "accepted_existing_flow_provenance"}],
        })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("runtime/evidence/goal08/provider_benchmark"))
    parser.add_argument("--valid-quota-denials", type=int, required=True)
    parser.add_argument("--invalid-credentials", type=int, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    credential_probe = {
        "status": "BLOCKED_PROVIDER_ACCOUNT",
        "failure_class": "GEMINI_API_PAID_QUOTA_REQUIRED",
        "nano_banana_2_pool": {"quota_denied": args.valid_quota_denials, "invalid_or_unauthenticated": args.invalid_credentials},
        "bounded_candidate_probes": {
            "gemini-3-pro-image": "RATE_LIMITED_ZERO_QUOTA",
            "gemini-omni-flash-preview": "RATE_LIMITED_ZERO_QUOTA",
            "veo-3.1-generate-preview": "RATE_LIMITED_ZERO_QUOTA",
        },
        "provider_requests_accepted": 0,
        "provider_jobs_created": 0,
        "secrets_recorded": False,
    }
    manifest, _ = build_benchmark_workspace(root, capability_evidence=capability_evidence(), credential_probe=credential_probe)
    bind_flow_baseline(root, manifest)
    write_review_package(root, manifest)
    print(root / "review.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
