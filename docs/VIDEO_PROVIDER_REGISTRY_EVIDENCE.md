# Video Provider Registry Evidence

Date: 2026-09-16

## CADS basis

- CADS local/remote HEAD verified aligned at `62cf2aa4909d1953a94c1c519e497e3c369e80c5`.
- Applied current CADS guidance: capability/invariant-first architecture, REUSE/WIRE before ADD, behavioral/system-flow separation, explicit external-effect identity/idempotency/recovery, and evidence continuity.

## Story Auto subject

- Baseline Product HEAD: `8b07446a15aa0617a1dc5e12c215c7c38c2b7678`.
- Decision: `docs/decisions/0006-capability-first-video-provider-boundary.md`.
- Architecture corrected to the current Hybrid 15–20 second Opening contract.

## Implemented

- Added a small capability-first registry at `story_auto/providers/video_generation.py`.
- Registry separates `model_family=seedance` from provider identity.
- Current catalog: BytePlus (Tier A/direct API), Elyum (Tier A/MCP, not yet production-routed), Dola (Tier B/experimental session), Manual external (Tier C/always available).
- Encoded the safety invariant that cross-provider fallback is allowed only before dispatch/effect ambiguity.
- Settings receives and renders the registry as a read-only capability/readiness surface.
- No generation router, spend behavior, provider dispatch, or existing BytePlus/Elyum execution path was changed in this slice.

## Verification

- `test_video_provider_registry.py`: 4/4 PASS, including browser Settings visibility.
- `test_application.py`: 18/18 PASS.
- Python compile and JavaScript syntax PASS before targeted tests.

## Next bounded slice

Promote Elyum from qualified Goal54 implementation into the canonical provider contract: credential/readiness product UX, opening-provider selection, then explicit Preview -> Owner review -> Keep/Kill -> normalized slot binding. Dola remains experimental until its session/API contract is independently qualified.
