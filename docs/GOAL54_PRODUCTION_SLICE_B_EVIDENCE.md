# Goal 54 — Production Integration Slice B Evidence

Date: 2026-09-14
Status: ENGINEERING_COMPLETE / PRODUCTION_PROVIDER_UNCHANGED

## Scope

Slice B implements the provider-free continuity-reference lifecycle required by the repeatability-qualified Elyum/Seedance I2V method. It does not enable Elyum production routing and performs no provider dispatch, Keep/Kill or Credit mutation.

## Durable contract

Canonical state is `output/full_video_continuity.json` using schema `story-auto-full-video-continuity/1.0.0`.

Each continuity run is bound to:

- exact `run_id`;
- exact SHA-256 of `output/generation_requests.json`;
- exact target request ID and request fingerprint;
- exact source asset SHA-256 and selected attempt when derived from prior accepted video;
- deterministic frame-selection policy and timestamp;
- exact extracted/local reference path and SHA-256.

The immutable snapshot returned for provider-attempt ownership uses schema `story-auto-full-video-reference-snapshot/1.0.0` and contains the run, generation-request scope, target identity, binding revision, source provenance/identity, frame policy/timestamp, and exact reference hash/path. Slice C must persist that snapshot before entering the Elyum provider boundary.

## Initial anchor lifecycle

The first I2V video request cannot infer or reuse a Flow entity reference. It requires an explicit canonical anchor supplied through `bind_initial_anchor(...)` with non-empty provenance.

The anchor is locally validated, copied into the project under `assets/continuity/<run>/<request>/`, hash-bound, and can be reused idempotently only for the same run/request/source bytes. Binding after the target request has entered a provider boundary is blocked.

## Shot-to-shot lifecycle

For later requests, `bind_previous_accepted_frame(...)` selects the immediate prior temporal video interval and requires exactly one current accepted source. The source manifest entry must be `SUCCEEDED`, its selected asset must carry accepted production QC, and the on-disk video SHA-256 must match the manifest.

The continuity frame policy is `TARGET_END_MINUS_0_5_SECONDS`: the source request target end minus 0.5 seconds, clamped to the validated local video duration. The frame is extracted locally by FFmpeg, validated as an image, and SHA-bound before it can be resolved.

## Stale/replacement safety

- Different `run_id` values never inherit each other's bindings.
- Reusing the same `run_id` with a changed generation-request artifact fails closed as `CONTINUITY_RUN_PLAN_MISMATCH`.
- Manual rejection or disappearance/change of the source selected asset makes the existing reference unusable; reconciliation durably marks it `INVALIDATED`.
- A replacement accepted source may create a new binding revision only before the downstream target enters the provider boundary; the previous revision is preserved as `SUPERSEDED`.
- Once the downstream target has a provider submission/job/confirmed boundary, rebinding is blocked as `CONTINUITY_TARGET_ALREADY_DISPATCHED` so an in-flight job cannot silently acquire different reference bytes.

## Provider capability shape

The narrow Full Video provider contract now records:

- BytePlus: `continuity_reference_policy=NONE`, `initial_anchor_policy=NONE`;
- Elyum: `continuity_reference_policy=SHOT_TO_SHOT_ACCEPTED_FRAME`, `initial_anchor_policy=EXPLICIT_CANONICAL_ANCHOR`.

Elyum remains `production_enabled=false`; Slice B does not alter production routing.

## Verification

- targeted continuity/provider contract suite: `11 passed`;
- broader planning/BytePlus/application/release regression: `55 passed, 2 subtests passed`;
- Python compilation: PASS;
- `git diff --check`: PASS;
- full hermetic repository regression: `748 passed, 283 subtests passed`; the sole failure was the repository security gate flagging a pre-existing synthetic Elyum test URL shaped like a signed provider URL (`?sig=x`), not a runtime credential or Slice B behavior;
- the synthetic fixture was hardened to a non-signed preview query, after which `SECURITY_GATE=PASS` and the focused Elyum + hardening suite passed `18/18`;
- differential qualification is therefore closed without rerunning the 748 already-passing tests a second time.

## Next boundary

Slice C may now implement the Elyum production service adapter. It must consume the exact continuity reference snapshot from this lifecycle and persist it into the canonical generation-manifest attempt before provider mutation. Research ledgers remain forbidden as production state.
