# Goal 54 — Production Integration Slice A Evidence

Date: 2026-09-14
Status: ACCEPTED_ENGINEERING_CHECKPOINT

## Scope

Slice A introduces only the narrow Full Video provider capability contract and durable provider snapshot required by the qualified Goal 54 method. It does not enable Elyum production dispatch.

## Implemented contract

- `byteplus_seedance` remains the default and only production-enabled Full Video provider.
- Historical Full Video projects with no explicit provider field resolve to BytePlus without rewriting their project truth.
- New Full Video project creation snapshots `settings.full_video_provider=byteplus_seedance`.
- Generation requests bind a `full_video_provider_snapshot` containing provider id, generation mode, reference-image policy, durable recovery shape, cost-preflight shape, consequence policy and production-enabled state.
- `elyum_seedance` is represented as the proven I2V capability shape (`reference_image_policy=REQUIRED`, durable clientRef/jobId recovery, balance+estimate preflight, explicit Keep/unlock consequence), but remains `production_enabled=false` until Slice B/C land.
- Unknown providers fail validation.
- An unenabled provider fails closed before provider dispatch with `FULL_VIDEO_PROVIDER_NOT_PRODUCTION_ENABLED`.
- Full Video generation continues to call the existing BytePlus production service only after the capability gate resolves to production-enabled BytePlus.
- No automatic cross-provider fallback was introduced.

## Verification

Targeted contract/planning/BytePlus regression:

- `tests/test_full_video_provider_contract.py`
- `tests/test_planning.py`
- `tests/test_byteplus_seedance.py`
- result: `21 passed`
- Python compile: PASS
- `git diff --check`: PASS

Broader application/release/project-binding regression:

- `tests/test_application.py`
- `tests/test_two_mode_release.py`
- `tests/test_production_flow_v2_phase_c.py`
- `tests/test_flow_project_binding.py`
- `tests/test_flow_project_activation.py`
- result: `53 passed, 6 subtests passed`

An initial broader command referenced the nonexistent `tests/test_project.py` and therefore collected zero tests; it was corrected to the real test files above and is not a product failure.

## Boundary

Slice A does not authorize Elyum production routing. The next implementation slice is Slice B continuity-reference lifecycle: canonical first-shot anchor, deterministic accepted-shot frame extraction, SHA binding, request/job ownership, stale-frame prevention and rejection/replacement behavior.
