# Hybrid Visual H1/H2 — Opening Builder evidence

Date: 2026-09-16
Status: ENGINEERING_COMPLETE / RELEASE_DISABLED

## Scope

This checkpoint implements only the provider-independent H1/H2 foundation accepted in Decision 0004.

It does **not** enable `hybrid_hook` for new production projects and does not add Pexels, paid/API generation, mid-body AI video, or release activation.

## H1 — durable opening-slot contract

Canonical artifact: `output/opening_manifest.json` (`story-auto-opening-builder/1.0.0`).

Contract properties:

- only `hybrid_hook` projects may own an Opening Builder manifest;
- total opening duration must remain 15–20 seconds;
- opening contains 2–4 contiguous stable slots;
- each slot is 5–10 seconds and receives deterministic IDs `OPENING_O1`…`OPENING_O4`;
- exact per-slot prompt text and SHA-256 are durable;
- shared continuity/style context and SHA-256 are durable;
- render target is snapshotted into the manifest;
- once any normalized asset is bound, a materially changed plan cannot silently replace the slot contract;
- product projection exposes an exact `Copy all prompts` pack without requiring provider access.

## H2 — manual external-video round trip

The user may generate each opening clip in any external tool and import it into one explicit slot.

Import behavior:

1. browser/import payload is bound to an explicit slot ID; no filename guessing is authoritative;
2. source is FFprobe-validated and copied into project-owned durable storage;
3. sources longer than the slot are trimmed to exact target duration;
4. a small shortage is handled with a bounded frozen tail; material shortages fail closed as `OPENING_IMPORT_TOO_SHORT`;
5. clip is normalized through the existing FFmpeg compiler to project width/height/FPS/pixel format;
6. embedded source audio is stripped; Story Auto master narration/BGM/subtitle/waveform remain authoritative;
7. source SHA and normalized SHA are persisted;
8. replacing one slot increments only that slot revision and preserves prior source/normalized provenance in `replacement_history`;
9. Opening Builder becomes `READY` only when every required normalized slot still exists and its SHA matches.

## Product surface

- ordinary project workspace includes an `opening_builder` projection for `hybrid_hook` projects;
- UI can materialize the Opening Builder from already-saved canonical required VIDEO generation requests without provider calls, preserving exact prompts and source request IDs;
- UI displays shared continuity, exact per-slot prompts, `Copy prompt`, `Copy all opening prompts`, per-slot import/replace actions, normalized preview, and readiness;
- HTTP actions exist for provider-free builder configuration and exact-slot manual import;
- `hybrid_hook` still returns `FEATURE_NOT_AVAILABLE` through the canonical release availability guard. The Opening Builder surface does not bypass production activation.

## Verification

Environment recovery after SSD migration:

- restored the repo-declared Python dependencies from `requirements.txt` (`Pillow`, `websocket-client`, `playwright`);
- no Playwright browser installation was performed.

Targeted Opening Builder integration:

- `7 tests` PASS;
- covers stable slot/timing contract, prompt hashes/copy pack, canonical generation-request -> opening-slot materialization, request-identity preservation, continuity-bible context projection, invalid duration fail-closed, FFmpeg normalization, embedded-audio stripping, bounded duration mismatch, all-slot readiness, replacement history, locked plan after asset binding, browser-style base64 import, and workspace projection while the mode remains unavailable.

Regression:

- Full Image: `7 tests` PASS;
- Render: `19 tests` PASS;
- Application: `18 tests` PASS;
- Goal 54 product surface: `4 tests` PASS;
- total focused regression: `48 tests` PASS;
- Python compile gate PASS;
- JavaScript `node --check` PASS.

## Next bounded slice

H3/H4 must remain separate from this checkpoint:

- optional API acquisition for the same opening slots;
- Pexels semantic stock-video body slots;
- mixed body compositor/UAT.

Before either provider path is added, the H1/H2 manual opening contract remains the canonical acceptance baseline.
