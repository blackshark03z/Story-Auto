#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import hashlib, json, sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "PROJECT_BRIEF.md", "PROJECT_STATUS.md", "ARCHITECTURE.md", "ENGINEERING.md", "ROADMAP.md", "CHANGELOG.md", "DESIGN_FREEZE.md",
    "OPERATIONS.md", "SECURITY.md", "MIGRATIONS.md",
    "docs/specs/FROZEN_PRODUCT_DESIGN_V1.md", "docs/specs/DOMAIN_MODEL_V1.md", "docs/specs/ARTIFACT_CONTRACTS_V1.md", "docs/specs/FAILURE_RECOVERY_V1.md", "docs/specs/QUALITY_ACCEPTANCE_V1.md",
    "contracts/frozen_design_v1.json", "contracts/FROZEN_DESIGN_MANIFEST.json"
]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def fail(msg: str) -> None:
    print(f"QUALITY_GATE=FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)

for rel in REQUIRED:
    if not (ROOT / rel).is_file():
        fail(f"missing required file: {rel}")

try:
    frozen = json.loads((ROOT / "contracts/frozen_design_v1.json").read_text(encoding="utf-8"))
except Exception as exc:
    fail(f"frozen design invalid JSON: {exc}")

if frozen.get("schema") != "story-auto.frozen-design/1.0.0" or frozen.get("status") != "FROZEN":
    fail("unexpected frozen design schema/status")

expected = {
    "baseline_model": "gemini-3.5-flash",
    "visual_provider": "google_flow",
    "modes": {"hybrid_hook", "full_video_ai"},
    "tts": {"elevenlabs", "typecast"},
}
if frozen.get("providers", {}).get("llm", {}).get("baseline_model") != expected["baseline_model"]:
    fail("Gemini baseline model drift")
if frozen.get("providers", {}).get("visual", {}).get("provider") != expected["visual_provider"]:
    fail("visual provider drift")
if set(frozen.get("render_modes", {}).keys()) != expected["modes"]:
    fail("render mode drift")
if set(frozen.get("providers", {}).get("tts", [])) != expected["tts"]:
    fail("TTS provider drift")
if frozen.get("render_modes", {}).get("full_video_ai", {}).get("silent_still_fallback") is not False:
    fail("full-video fallback invariant drift")
if frozen.get("providers", {}).get("source_video_audio") != "MUTE":
    fail("source video audio policy drift")

manifest_path = ROOT / "contracts/FROZEN_DESIGN_MANIFEST.json"
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail(f"design manifest invalid JSON: {exc}")
for rel, expected_hash in manifest.get("files", {}).items():
    p = ROOT / rel
    if not p.is_file():
        fail(f"frozen manifest file missing: {rel}")
    observed = sha256(p)
    if observed != expected_hash:
        fail(f"frozen design drift: {rel} expected={expected_hash} observed={observed}")

# Schemas/examples must at least be valid JSON at the zero-dependency baseline.
for folder in [ROOT / "contracts/schemas", ROOT / "contracts/examples"]:
    for p in sorted(folder.glob("*.json")):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            fail(f"invalid JSON {p.relative_to(ROOT)}: {exc}")

print("QUALITY_GATE=PASS")
print("DESIGN_CONTRACT=story-auto.frozen-design/1.0.0")
